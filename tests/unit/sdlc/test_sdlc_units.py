"""Unit tests for SDLC foundation modules (errors, ids, paths, concurrency, frontmatter)."""
from __future__ import annotations

from pathlib import Path

import pytest

from etc_platform.sdlc.concurrency import (
    FileTransaction,
    atomic_write_bytes,
    atomic_write_text,
    detect_orphan_tmps,
    workspace_lock,
)
from etc_platform.sdlc.errors import (
    InvalidWorkspaceError,
    MCPSdlcError,
    NotFoundError,
    TransactionFailedError,
)
from etc_platform.sdlc.frontmatter import (
    get_dotpath,
    parse_frontmatter,
    serialize,
    set_dotpath,
)
from etc_platform.sdlc.ids import (
    folder_name,
    is_valid_feature_id,
    is_valid_hotfix_id,
    is_valid_module_id,
    is_valid_slug,
    parse_id,
    split_folder_name,
)
from etc_platform.sdlc.path_validation import (
    assert_write_confined,
    validate_workspace_path,
)


# ---------------------------------------------------------------------------
# ids
# ---------------------------------------------------------------------------


class TestIds:
    def test_module_id_valid(self):
        assert is_valid_module_id("M-001")
        assert is_valid_module_id("M-999")
        assert is_valid_module_id("M-0001")

    def test_module_id_invalid(self):
        assert not is_valid_module_id("M-1")
        assert not is_valid_module_id("M-01")
        assert not is_valid_module_id("F-001")
        assert not is_valid_module_id("m-001")
        assert not is_valid_module_id("M-001a")

    def test_feature_id_valid(self):
        assert is_valid_feature_id("F-001")
        assert is_valid_feature_id("F-009a")
        assert is_valid_feature_id("F-100z")

    def test_feature_id_invalid(self):
        assert not is_valid_feature_id("F-1")
        assert not is_valid_feature_id("F-001ab")
        assert not is_valid_feature_id("M-001")

    def test_hotfix_id_valid(self):
        assert is_valid_hotfix_id("H-001")
        assert not is_valid_hotfix_id("H-001a")  # no sub-suffix for hotfix

    def test_slug_valid(self):
        assert is_valid_slug("iam")
        assert is_valid_slug("identity-access")
        assert is_valid_slug("a-b-c-1")

    def test_slug_invalid(self):
        assert not is_valid_slug("")
        assert not is_valid_slug("IAM")
        assert not is_valid_slug("1iam")
        assert not is_valid_slug("iam-")
        assert not is_valid_slug("iam_access")
        assert not is_valid_slug("iam access")

    def test_parse_id_module(self):
        kind, num, suffix = parse_id("M-042")
        assert kind == "module"
        assert num == 42
        assert suffix is None

    def test_parse_id_feature_subsuffix(self):
        kind, num, suffix = parse_id("F-009d")
        assert kind == "feature"
        assert num == 9
        assert suffix == "d"

    def test_parse_id_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_id("invalid")

    def test_folder_name_roundtrip(self):
        name = folder_name("M-001", "iam")
        assert name == "M-001-iam"
        eid, slug = split_folder_name(name)
        assert eid == "M-001"
        assert slug == "iam"

    def test_split_folder_with_hyphen_slug(self):
        eid, slug = split_folder_name("M-001-identity-access")
        assert eid == "M-001"
        assert slug == "identity-access"


# ---------------------------------------------------------------------------
# path_validation
# ---------------------------------------------------------------------------


class TestPathValidation:
    def test_validate_existing_workspace(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("test")
        result = validate_workspace_path(str(tmp_path))
        assert result == tmp_path.resolve()

    def test_validate_no_marker_rejects(self, tmp_path):
        with pytest.raises(InvalidWorkspaceError) as exc_info:
            validate_workspace_path(str(tmp_path))
        assert exc_info.value.details["reason"] == "no_marker"

    def test_validate_not_absolute_rejects(self):
        with pytest.raises(InvalidWorkspaceError) as exc_info:
            validate_workspace_path("relative/path")
        assert exc_info.value.details["reason"] == "not_absolute"

    def test_validate_unexpanded_var_rejects(self):
        with pytest.raises(InvalidWorkspaceError) as exc_info:
            validate_workspace_path("~/project")
        assert exc_info.value.details["reason"] == "env_var_unexpanded"

    def test_validate_not_exists_rejects(self, tmp_path):
        nonexistent = tmp_path / "does-not-exist"
        with pytest.raises(InvalidWorkspaceError):
            validate_workspace_path(str(nonexistent))

    def test_assert_write_confined_ok(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("")
        ws = tmp_path.resolve()
        assert_write_confined(ws, ws / "docs" / "intel" / "test.json")
        assert_write_confined(ws, ws / "apps" / "x" / "src" / "main.ts")

    def test_assert_write_confined_root_files(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("")
        ws = tmp_path.resolve()
        # Root-level config file allowed
        assert_write_confined(ws, ws / ".gitignore")

    def test_assert_write_confined_traversal_rejected(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("")
        ws = tmp_path.resolve()
        with pytest.raises(InvalidWorkspaceError) as exc_info:
            assert_write_confined(ws, ws.parent / "outside" / "file.txt")
        assert exc_info.value.details["reason"] == "traversal_attempt"

    def test_assert_write_confined_disallowed_prefix(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("")
        ws = tmp_path.resolve()
        with pytest.raises(InvalidWorkspaceError) as exc_info:
            assert_write_confined(ws, ws / "secret" / "file.txt")
        assert exc_info.value.details["reason"] == "disallowed_prefix"


# ---------------------------------------------------------------------------
# concurrency
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_atomic_write_bytes(self, tmp_path):
        target = tmp_path / "subdir" / "file.bin"
        atomic_write_bytes(target, b"hello")
        assert target.read_bytes() == b"hello"
        # No leftover .tmp
        assert not (tmp_path / "subdir" / "file.bin.tmp").exists()

    def test_atomic_write_text(self, tmp_path):
        target = tmp_path / "file.txt"
        atomic_write_text(target, "VN: tiếng Việt")
        assert target.read_text(encoding="utf-8") == "VN: tiếng Việt"

    def test_workspace_lock_reuses_same_lock(self, tmp_path):
        from etc_platform.sdlc.concurrency import get_workspace_lock

        a = get_workspace_lock(str(tmp_path))
        b = get_workspace_lock(str(tmp_path))
        assert a is b

    def test_file_transaction_commit(self, tmp_path):
        tx = FileTransaction()
        tx.add(tmp_path / "a.txt", "A")
        tx.add(tmp_path / "b.txt", "B")
        tx.commit()
        assert (tmp_path / "a.txt").read_text() == "A"
        assert (tmp_path / "b.txt").read_text() == "B"
        # No orphans
        assert not list(tmp_path.glob("*.tmp"))

    def test_file_transaction_verify_failure_rolls_back(self, tmp_path):
        tx = FileTransaction()
        tx.add(tmp_path / "a.txt", "A")

        def reject(_):
            return ["fake error"]

        with pytest.raises(TransactionFailedError):
            tx.commit(verify=reject)

        assert not (tmp_path / "a.txt").exists()
        assert not list(tmp_path.glob("*.tmp"))

    def test_detect_orphan_tmps(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("")
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "orphan.json.tmp").write_text("{}")
        orphans = detect_orphan_tmps(tmp_path, subdir="docs")
        assert len(orphans) == 1
        assert orphans[0].name == "orphan.json.tmp"


# ---------------------------------------------------------------------------
# frontmatter
# ---------------------------------------------------------------------------


class TestFrontmatter:
    def test_parse_simple(self):
        text = "---\nkey: value\nnum: 42\n---\nbody text\n"
        fm, body = parse_frontmatter(text)
        assert fm == {"key": "value", "num": 42}
        assert body == "body text\n"

    def test_parse_no_frontmatter(self):
        fm, body = parse_frontmatter("just body\n")
        assert fm == {}
        assert body == "just body\n"

    def test_serialize_roundtrip(self):
        original_fm = {"a": 1, "b": "x", "c": [1, 2]}
        original_body = "# Title\n\ncontent here\n"
        text = serialize(original_fm, original_body)
        parsed_fm, parsed_body = parse_frontmatter(text)
        assert parsed_fm == original_fm
        # Body preserved (with leading newline added by serialize)
        assert "# Title" in parsed_body

    def test_set_dotpath_simple(self):
        d = {"a": {"b": 1}}
        old, new = set_dotpath(d, "a.b", 2)
        assert old == 1
        assert new == 2
        assert d == {"a": {"b": 2}}

    def test_set_dotpath_creates_nested(self):
        d = {}
        set_dotpath(d, "x.y.z", "v")
        assert d == {"x": {"y": {"z": "v"}}}

    def test_get_dotpath_missing_returns_default(self):
        assert get_dotpath({}, "a.b.c", default="MISSING") == "MISSING"

    def test_get_dotpath_existing(self):
        assert get_dotpath({"a": {"b": 5}}, "a.b") == 5


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------


class TestErrors:
    def test_to_response_format(self):
        exc = NotFoundError("missing", details={"id": "X-001"}, fix_hint="check")
        resp = exc.to_response()
        assert resp["ok"] is False
        assert resp["error"]["code"] == "MCP_E_NOT_FOUND"
        assert resp["error"]["message"] == "missing"
        assert resp["error"]["details"] == {"id": "X-001"}
        assert resp["error"]["fix_hint"] == "check"

    def test_inheritance(self):
        exc = NotFoundError("x")
        assert isinstance(exc, MCPSdlcError)
        assert isinstance(exc, Exception)
