"""Integration tests for /workspaces HTTP endpoints + workspace-based jobs.

Exercises the multipart streaming upload, dedup, manifest readback, and the
workspace→job→download flow end-to-end. Includes the HDSD use case (multiple
screenshot files in a single bundle).
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from etc_platform.jobs.http_app import HttpSettings, create_app

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture()
async def client(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    settings = HttpSettings(
        storage_root=str(tmp_path / "storage"),
        api_key=None,
        upload_ttl_seconds=120,
        job_ttl_seconds=600,
        workspace_ttl_seconds=3600,
        max_upload_bytes=1024 * 1024,
        max_workspace_bytes=20 * 1024 * 1024,
        max_workspace_files=50,
    )
    a = create_app(settings)
    async with a.router.lifespan_context(a):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=a),
            base_url="http://testserver",
            timeout=30.0,
        ) as c:
            yield c


# ─────────────────────────── Workspace CRUD ───────────────────────────


class TestWorkspaceUpload:
    async def test_create_with_multiple_files(self, client: httpx.AsyncClient) -> None:
        files = [
            ("files[content-data.json]", ("content-data.json", b'{"hello": "world"}', "application/json")),
            ("files[screenshots/step-01.png]", ("step-01.png", b"\x89PNG\r\n\x1a\n" + b"img1", "image/png")),
            ("files[screenshots/step-02.png]", ("step-02.png", b"\x89PNG\r\n\x1a\n" + b"img2", "image/png")),
        ]
        r = await client.post("/workspaces", files=files, data={"label": "hdsd-test"})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["workspace_id"].startswith("ws_")
        assert body["file_count"] == 3
        assert body["label"] == "hdsd-test"
        # Manifest paths are canonical.
        paths = {p["path"] for p in body["parts"]}
        assert paths == {
            "content-data.json",
            "screenshots/step-01.png",
            "screenshots/step-02.png",
        }

    async def test_dedup_returns_same_id(self, client: httpx.AsyncClient) -> None:
        files = [
            ("files[content-data.json]", ("content-data.json", b'{"a": 1}', "application/json")),
            ("files[a.png]", ("a.png", b"\x89PNG\r\n\x1a\nx", "image/png")),
        ]
        r1 = await client.post("/workspaces", files=files, data={"label": "first"})
        r2 = await client.post("/workspaces", files=files, data={"label": "second"})
        assert r1.json()["workspace_id"] == r2.json()["workspace_id"]
        # Label should be updated.
        assert r2.json()["label"] == "second"

    async def test_path_traversal_rejected(self, client: httpx.AsyncClient) -> None:
        files = [
            ("files[../escape.txt]", ("escape.txt", b"x", "text/plain")),
        ]
        r = await client.post("/workspaces", files=files)
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "WORKSPACE_INVALID_PATH"

    async def test_empty_workspace_rejected(self, client: httpx.AsyncClient) -> None:
        r = await client.post("/workspaces", data={"label": "empty"})
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "EMPTY_WORKSPACE"

    async def test_oversize_workspace(self, client: httpx.AsyncClient) -> None:
        # max_workspace_bytes set to 20 MB in fixture; 22 MB should fail.
        big_data = b"X" * (22 * 1024 * 1024)
        files = [
            ("files[big.bin]", ("big.bin", big_data, "application/octet-stream")),
        ]
        r = await client.post("/workspaces", files=files)
        assert r.status_code == 413
        assert r.json()["error"]["code"] == "WORKSPACE_TOO_LARGE"

    async def test_get_workspace(self, client: httpx.AsyncClient) -> None:
        files = [
            ("files[content-data.json]", ("content-data.json", b'{"a":1}', "application/json")),
        ]
        r1 = await client.post("/workspaces", files=files)
        ws_id = r1.json()["workspace_id"]
        r2 = await client.get(f"/workspaces/{ws_id}")
        assert r2.status_code == 200
        assert r2.json()["workspace_id"] == ws_id

    async def test_get_unknown_404(self, client: httpx.AsyncClient) -> None:
        r = await client.get("/workspaces/ws_doesnotexist1234")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "WORKSPACE_NOT_FOUND"

    async def test_delete_workspace(self, client: httpx.AsyncClient) -> None:
        files = [
            ("files[content-data.json]", ("content-data.json", b'{"a":1}', "application/json")),
        ]
        r1 = await client.post("/workspaces", files=files)
        ws_id = r1.json()["workspace_id"]
        r2 = await client.delete(f"/workspaces/{ws_id}")
        assert r2.status_code == 204
        r3 = await client.get(f"/workspaces/{ws_id}")
        assert r3.status_code == 404


# ─────────────────────────── Job with workspace ───────────────────────────


class TestJobFromWorkspace:
    async def test_create_job_workspace_id(self, client: httpx.AsyncClient) -> None:
        files = [
            ("files[content-data.json]", ("content-data.json", b'{"a":1}', "application/json")),
        ]
        ws = (await client.post("/workspaces", files=files)).json()
        r = await client.post(
            "/jobs",
            json={
                "workspace_id": ws["workspace_id"],
                "targets": ["tkkt"],
                "auto_render_mermaid": False,
            },
        )
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["workspace_id"] == ws["workspace_id"]
        assert body["upload_id"] is None
        assert body["status"] == "queued"

    async def test_neither_source_rejected(self, client: httpx.AsyncClient) -> None:
        r = await client.post("/jobs", json={"targets": ["tkkt"]})
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "MISSING_SOURCE"

    async def test_both_sources_rejected(self, client: httpx.AsyncClient) -> None:
        r = await client.post(
            "/jobs",
            json={
                "workspace_id": "ws_abc",
                "upload_id": "u_xyz",
                "targets": ["tkkt"],
            },
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "AMBIGUOUS_SOURCE"

    async def test_unknown_workspace_404(self, client: httpx.AsyncClient) -> None:
        r = await client.post(
            "/jobs", json={"workspace_id": "ws_unknown1234", "targets": ["tkkt"]}
        )
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "WORKSPACE_NOT_FOUND"

    async def test_legacy_upload_still_works(self, client: httpx.AsyncClient) -> None:
        # BC: old POST /uploads + POST /jobs {upload_id} flow.
        up_resp = await client.post(
            "/uploads",
            files={"file": ("c.json", b'{"a":1}', "application/json")},
        )
        upload_id = up_resp.json()["upload_id"]
        r = await client.post(
            "/jobs", json={"upload_id": upload_id, "targets": ["tkkt"]}
        )
        assert r.status_code == 202
        body = r.json()
        assert body["upload_id"] == upload_id
        assert body["workspace_id"] is None


# ─────────────────────────── Health ───────────────────────────


class TestHealthIncludesWorkspaces:
    async def test_readyz_reports_workspace_stats(self, client: httpx.AsyncClient) -> None:
        files = [
            ("files[a.json]", ("a.json", b'{}', "application/json")),
        ]
        await client.post("/workspaces", files=files)
        r = await client.get("/readyz")
        body = r.json()
        assert body["storage"]["workspaces"] == 1
        assert body["storage"]["max_workspace_bytes"] > 0
