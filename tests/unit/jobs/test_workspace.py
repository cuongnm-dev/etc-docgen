"""Tests for the Workspace pattern — multi-file content-addressed bundles.

Covers:
- Models: path validation, MIME detection, deterministic content-addressed id
- Storage: create / get / list / materialize / delete / dedup / TTL eviction
- Concurrency-adjacent: re-upload identical content returns same id (TTL refreshed)
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from etc_platform.jobs.models import (
    Workspace,
    WorkspaceExpired,
    WorkspaceInvalidPath,
    WorkspaceNotFound,
    WorkspacePart,
    WorkspaceTooLarge,
    detect_mime,
    validate_workspace_path,
)
from etc_platform.jobs.storage import JobStore

# ─────────────────────────── Path validator ───────────────────────────


class TestValidateWorkspacePath:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("content-data.json", "content-data.json"),
            ("screenshots/F-001-step-01-initial.png", "screenshots/F-001-step-01-initial.png"),
            ("diagrams/architecture_diagram.png", "diagrams/architecture_diagram.png"),
            ("a/b/c/d.txt", "a/b/c/d.txt"),  # 4 levels OK
            ("./content-data.json", "content-data.json"),  # canonicalised
        ],
    )
    def test_valid_paths(self, raw: str, expected: str) -> None:
        assert validate_workspace_path(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "../etc/passwd",
            "/absolute/path",
            "a/../b",
            "screenshots/../../escape",
            "a/b/c/d/e.txt",  # depth 5 > MAX 4
            "with space.png",  # space not allowed
            "",
            "   ",
            "C:\\windows.png",  # backslash → Windows-style absolute, forbidden
            "..",
            "./..",
        ],
    )
    def test_invalid_paths(self, raw: str) -> None:
        with pytest.raises(WorkspaceInvalidPath):
            validate_workspace_path(raw)


# ─────────────────────────── MIME detection ───────────────────────────


class TestDetectMime:
    def test_png_magic(self) -> None:
        assert detect_mime("foo.png", b"\x89PNG\r\n\x1a\n...") == "image/png"

    def test_jpeg_magic(self) -> None:
        assert detect_mime("foo.jpg", b"\xff\xd8\xff\xe0...") == "image/jpeg"

    def test_svg_magic(self) -> None:
        assert detect_mime("foo.svg", b'<?xml version="1.0"?>...') == "image/svg+xml"
        assert detect_mime("foo.svg", b'<svg xmlns="...">...') == "image/svg+xml"

    def test_pdf_magic(self) -> None:
        assert detect_mime("foo.pdf", b"%PDF-1.7...") == "application/pdf"

    def test_json_extension_fallback(self) -> None:
        assert detect_mime("content-data.json", b'{"hello": ...}') == "application/json"

    def test_unknown_falls_back_to_octet_stream(self) -> None:
        assert detect_mime("foo.bin", b"random binary garbage") == "application/octet-stream"


# ─────────────────────────── Workspace model ───────────────────────────


class TestWorkspaceModel:
    def _make_part(self, path: str, content: bytes) -> WorkspacePart:
        import hashlib

        return WorkspacePart(
            path=path,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            content_type="application/octet-stream",
        )

    def test_content_addressed_id(self) -> None:
        # Same content → same workspace_id, regardless of order at construction time.
        a = self._make_part("a.txt", b"hello")
        b = self._make_part("b.txt", b"world")
        ws1 = Workspace.new(parts=[a, b], ttl=timedelta(hours=1))
        ws2 = Workspace.new(parts=[b, a], ttl=timedelta(hours=1))  # reversed
        assert ws1.workspace_id == ws2.workspace_id
        assert ws1.sha256 == ws2.sha256

    def test_different_content_different_id(self) -> None:
        a = self._make_part("a.txt", b"hello")
        b = self._make_part("a.txt", b"goodbye")
        ws1 = Workspace.new(parts=[a], ttl=timedelta(hours=1))
        ws2 = Workspace.new(parts=[b], ttl=timedelta(hours=1))
        assert ws1.workspace_id != ws2.workspace_id

    def test_round_trip_serialisation(self) -> None:
        a = self._make_part("content-data.json", b'{"a":1}')
        ws = Workspace.new(parts=[a], ttl=timedelta(hours=1), label="test")
        roundtrip = Workspace.from_dict(ws.to_dict())
        assert roundtrip.workspace_id == ws.workspace_id
        assert roundtrip.label == "test"
        assert len(roundtrip.parts) == 1
        assert roundtrip.parts[0].path == "content-data.json"

    def test_find_part(self) -> None:
        a = self._make_part("screenshots/foo.png", b"\x89PNG\r\n\x1a\nx")
        ws = Workspace.new(parts=[a], ttl=timedelta(hours=1))
        assert ws.find_part("screenshots/foo.png") is not None
        assert ws.find_part("missing.png") is None


# ─────────────────────────── Storage CRUD ───────────────────────────


@pytest.fixture()
def store(tmp_path: Path) -> JobStore:
    return JobStore(
        root=tmp_path / "store",
        upload_ttl=timedelta(minutes=5),
        job_ttl=timedelta(minutes=10),
        workspace_ttl=timedelta(hours=1),
        max_workspace_bytes=10 * 1024 * 1024,
        max_workspace_files=20,
        max_workspace_per_file_bytes=5 * 1024 * 1024,
    )


@pytest.mark.asyncio
class TestWorkspaceStorage:
    async def test_create_and_read(self, store: JobStore) -> None:
        files = [
            ("content-data.json", b'{"hello": "world"}'),
            ("screenshots/step-01.png", b"\x89PNG\r\n\x1a\n" + b"x" * 100),
        ]
        ws = await store.create_workspace(files, label="proj-x")
        assert ws.workspace_id.startswith("ws_")
        assert ws.total_size == sum(len(b) for _, b in files)
        assert len(ws.parts) == 2
        assert ws.label == "proj-x"

        # Round-trip read.
        loaded = await store.get_workspace(ws.workspace_id)
        assert loaded.workspace_id == ws.workspace_id
        assert {p.path for p in loaded.parts} == {"content-data.json", "screenshots/step-01.png"}

    async def test_dedup_returns_same_id(self, store: JobStore) -> None:
        files = [
            ("content-data.json", b'{"a":1}'),
            ("screenshots/foo.png", b"\x89PNG\r\n\x1a\nx"),
        ]
        ws1 = await store.create_workspace(files, label="first")
        ws2 = await store.create_workspace(files, label="second")
        assert ws1.workspace_id == ws2.workspace_id
        # Label override on dedup.
        loaded = await store.get_workspace(ws1.workspace_id)
        assert loaded.label == "second"
        # TTL refreshed (newer expires_at).
        assert loaded.expires_at >= ws1.expires_at

    async def test_open_workspace_file(self, store: JobStore) -> None:
        files = [
            ("content-data.json", b'{"k": 42}'),
            ("screenshots/a.png", b"\x89PNG\r\n\x1a\nbytes"),
        ]
        ws = await store.create_workspace(files)
        data = await store.open_workspace_file(ws.workspace_id, "content-data.json")
        assert json.loads(data) == {"k": 42}

    async def test_open_unknown_file_404(self, store: JobStore) -> None:
        ws = await store.create_workspace([("a.json", b"{}")])
        with pytest.raises(WorkspaceNotFound):
            await store.open_workspace_file(ws.workspace_id, "missing.png")

    async def test_path_traversal_rejected(self, store: JobStore) -> None:
        with pytest.raises(WorkspaceInvalidPath):
            await store.create_workspace([("../escape.txt", b"x")])
        with pytest.raises(WorkspaceInvalidPath):
            await store.create_workspace([("/abs/path.txt", b"x")])

    async def test_total_size_capped(self, store: JobStore) -> None:
        # 10 MB cap; 11 MB should fail.
        big = b"X" * (11 * 1024 * 1024)
        with pytest.raises(WorkspaceTooLarge):
            await store.create_workspace([("big.bin", big)])

    async def test_per_file_size_capped(self, store: JobStore) -> None:
        # Per-file 5 MB cap.
        big = b"X" * (6 * 1024 * 1024)
        with pytest.raises(WorkspaceTooLarge):
            await store.create_workspace([("big.bin", big)])

    async def test_file_count_capped(self, store: JobStore) -> None:
        files = [(f"f{i:03d}.txt", b"x") for i in range(25)]  # > 20 cap
        with pytest.raises(WorkspaceTooLarge):
            await store.create_workspace(files)

    async def test_duplicate_path_in_bundle_rejected(self, store: JobStore) -> None:
        files = [("foo.txt", b"a"), ("foo.txt", b"b")]
        with pytest.raises(WorkspaceInvalidPath):
            await store.create_workspace(files)

    async def test_get_missing(self, store: JobStore) -> None:
        with pytest.raises(WorkspaceNotFound):
            await store.get_workspace("ws_doesnotexist1234")

    async def test_delete_idempotent(self, store: JobStore) -> None:
        ws = await store.create_workspace([("a.json", b"{}")])
        assert await store.delete_workspace(ws.workspace_id) is True
        assert await store.delete_workspace(ws.workspace_id) is False

    async def test_expired_get_raises(self, tmp_path: Path) -> None:
        s = JobStore(
            root=tmp_path / "s",
            upload_ttl=timedelta(minutes=5),
            job_ttl=timedelta(minutes=5),
            workspace_ttl=timedelta(seconds=-1),  # always expired
        )
        ws = await s.create_workspace([("a.json", b"{}")])
        with pytest.raises(WorkspaceExpired):
            await s.get_workspace(ws.workspace_id)

    async def test_list_workspaces(self, store: JobStore) -> None:
        await store.create_workspace([("a.json", b'{"a":1}')], label="A")
        await store.create_workspace([("a.json", b'{"a":2}')], label="B")
        all_ws = await store.list_workspaces()
        assert len(all_ws) == 2
        assert {w.label for w in all_ws} == {"A", "B"}


# ─────────────────────────── Materialize ───────────────────────────


@pytest.mark.asyncio
class TestMaterializeWorkspace:
    async def test_materialize_basic(self, store: JobStore, tmp_path: Path) -> None:
        files = [
            ("content-data.json", b'{"k": 1}'),
            ("screenshots/step-01.png", b"\x89PNG\r\n\x1a\n" + b"img1"),
            ("screenshots/step-02.png", b"\x89PNG\r\n\x1a\n" + b"img2"),
            ("diagrams/arch.png", b"\x89PNG\r\n\x1a\n" + b"diag"),
        ]
        ws = await store.create_workspace(files)
        target = tmp_path / "render-workspace"
        report = await store.materialize_workspace(ws.workspace_id, target)

        assert report["file_count"] == 4
        assert (target / "content-data.json").exists()
        assert (target / "screenshots" / "step-01.png").exists()
        assert (target / "screenshots" / "step-02.png").exists()
        assert (target / "diagrams" / "arch.png").exists()

        assert report["content_data_path"] == str(target / "content-data.json")
        assert report["screenshots_dir"] == str(target / "screenshots")
        assert report["diagrams_dir"] == str(target / "diagrams")

    async def test_materialize_without_screenshots(self, store: JobStore, tmp_path: Path) -> None:
        ws = await store.create_workspace([("content-data.json", b'{"k":1}')])
        target = tmp_path / "ws-out"
        report = await store.materialize_workspace(ws.workspace_id, target)
        assert report["screenshots_dir"] is None
        assert report["diagrams_dir"] is None
        assert report["content_data_path"] == str(target / "content-data.json")

    async def test_materialize_without_content_data(self, store: JobStore, tmp_path: Path) -> None:
        # Edge case: workspace with only screenshots (e.g. for HDSD update)
        ws = await store.create_workspace([("screenshots/foo.png", b"\x89PNG\r\n\x1a\n" + b"x")])
        target = tmp_path / "ws-out"
        report = await store.materialize_workspace(ws.workspace_id, target)
        assert report["content_data_path"] is None  # caller must handle
        assert report["screenshots_dir"] == str(target / "screenshots")


# ─────────────────────────── Sweep ───────────────────────────


@pytest.mark.asyncio
class TestWorkspaceSweep:
    async def test_sweep_evicts_expired(self, tmp_path: Path) -> None:
        s = JobStore(
            root=tmp_path / "s",
            upload_ttl=timedelta(minutes=5),
            job_ttl=timedelta(minutes=5),
            workspace_ttl=timedelta(seconds=-1),
        )
        ws = await s.create_workspace([("a.json", b"{}")])
        report = await s.sweep_expired()
        assert report["workspaces"] == 1
        # Idempotent
        again = await s.sweep_expired()
        assert again["workspaces"] == 0


# ─────────────────────────── Health ───────────────────────────


@pytest.mark.asyncio
class TestHealthIncludesWorkspaces:
    async def test_workspace_count_in_health(self, store: JobStore) -> None:
        await store.create_workspace([("a.json", b"{}")])
        h = await store.health()
        assert h["workspaces"] == 1
        assert h["max_workspace_bytes"] > 0
        assert h["workspace_ttl_seconds"] > 0
