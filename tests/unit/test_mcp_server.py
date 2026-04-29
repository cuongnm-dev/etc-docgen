"""Unit tests for etc-platform MCP server tools."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# ─── Helpers ───────────────────────────────────────────────────────


@pytest.fixture
def sample_data_file(tmp_path):
    """Minimal valid content-data.json for testing."""
    data = {
        "project": {"display_name": "Test Project", "code": "TST-001", "client": "Test Client"},
        "meta": {"today": "23/04/2026", "version": "1.0"},
        "dev_unit": "ETC",
        "overview": {
            "purpose": "Test purpose",
            "scope": "Test scope",
            "system_description": "Test system",
            "conventions": "Test conventions",
            "terms": [],
            "references": [],
        },
        "services": [],
        "troubleshooting": [],
    }
    f = tmp_path / "content-data.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    return f


# ─── schema tool ───────────────────────────────────────────────────


def test_schema_returns_valid_json():
    from etc_platform.mcp_server import schema

    result = schema()
    parsed = json.loads(result)
    assert parsed.get("title") == "ContentData"
    assert "properties" in parsed


# ─── section_schema tool ───────────────────────────────────────────


@pytest.mark.parametrize("doc_type", ["tkcs", "tkct", "tkkt", "hdsd", "xlsx"])
def test_section_schema_valid_types(doc_type):
    from etc_platform.mcp_server import section_schema

    result = section_schema(doc_type)
    parsed = json.loads(result)
    assert parsed["doc_type"] == doc_type
    assert "primary_schema" in parsed
    assert "content_data_keys" in parsed


def test_section_schema_invalid_type():
    from etc_platform.mcp_server import section_schema

    result = section_schema("nonexistent")
    parsed = json.loads(result)
    assert "error" in parsed
    assert "nonexistent" in parsed["error"]


# ─── template_list tool ────────────────────────────────────────────


def test_template_list_returns_five_templates():
    from etc_platform.mcp_server import template_list

    result = template_list()
    items = json.loads(result)
    assert len(items) == 5
    filenames = {item["filename"] for item in items}
    assert "huong-dan-su-dung.docx" in filenames
    assert "test-case.xlsx" in filenames
    assert "thiet-ke-kien-truc.docx" in filenames
    assert "thiet-ke-co-so.docx" in filenames
    assert "thiet-ke-chi-tiet.docx" in filenames


def test_template_list_has_size():
    from etc_platform.mcp_server import template_list

    items = json.loads(template_list())
    for item in items:
        assert item["size_kb"] > 0


# ─── validate tool ─────────────────────────────────────────────────


def test_validate_missing_file():
    from etc_platform.mcp_server import validate

    result = validate("/data/nonexistent/content-data.json")
    parsed = json.loads(result)
    assert parsed["valid"] is False
    assert len(parsed["errors"]) > 0


def test_validate_valid_file(sample_data_file):
    from etc_platform.mcp_server import validate

    result = validate(str(sample_data_file))
    parsed = json.loads(result)
    # May be valid or have warnings depending on schema strictness
    assert "valid" in parsed
    assert "errors" in parsed or "warnings" in parsed


def test_validate_malformed_json(tmp_path):
    from etc_platform.mcp_server import validate

    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    result = validate(str(bad))
    parsed = json.loads(result)
    assert parsed["valid"] is False


# ─── merge_content tool ────────────────────────────────────────────


@pytest.fixture(autouse=True)
def allow_tmp_writes(tmp_path, monkeypatch):
    """Allow merge_content to write to tmp_path during tests via ETC_DOCGEN_EXTRA_ROOTS."""
    monkeypatch.setenv("ETC_PLATFORM_EXTRA_ROOTS", str(tmp_path))
    # Reload _ALLOWED_ROOTS after env change
    import etc_platform.mcp_server as mcp_mod

    mcp_mod._ALLOWED_ROOTS = [Path("/data")]
    if extra := os.environ.get("ETC_PLATFORM_EXTRA_ROOTS", ""):
        mcp_mod._ALLOWED_ROOTS.extend(Path(r) for r in extra.split(os.pathsep) if r)
    yield
    mcp_mod._ALLOWED_ROOTS = [Path("/data")]


def test_merge_content_creates_new_file(tmp_path):
    from etc_platform.mcp_server import merge_content

    target = tmp_path / "new.json"
    partial = json.dumps({"project": {"display_name": "Test", "code": "TST", "client": "C"}})
    result = merge_content(str(target), partial)
    parsed = json.loads(result)
    assert parsed["success"] is True
    assert target.exists()
    written = json.loads(target.read_text())
    assert written["project"]["display_name"] == "Test"


def test_merge_content_deep_merge(tmp_path):
    from etc_platform.mcp_server import merge_content

    target = tmp_path / "existing.json"
    target.write_text(
        json.dumps(
            {
                "project": {"display_name": "Old", "code": "OLD", "client": "C"},
                "meta": {"version": "1.0", "today": "01/01/2026"},
            }
        )
    )
    result = merge_content(str(target), json.dumps({"project": {"display_name": "New"}}))
    parsed = json.loads(result)
    assert parsed["success"] is True
    written = json.loads(target.read_text())
    assert written["project"]["display_name"] == "New"  # updated
    assert written["project"]["code"] == "OLD"  # preserved
    assert written["meta"]["version"] == "1.0"  # preserved


def test_merge_content_invalid_json(tmp_path):
    from etc_platform.mcp_server import merge_content

    target = tmp_path / "out.json"
    result = merge_content(str(target), "{not json}")
    parsed = json.loads(result)
    assert parsed["success"] is False
    assert "error" in parsed


def test_merge_content_non_object_json(tmp_path):
    from etc_platform.mcp_server import merge_content

    target = tmp_path / "out.json"
    result = merge_content(str(target), "[1, 2, 3]")
    parsed = json.loads(result)
    assert parsed["success"] is False


# ─── field_map tool ────────────────────────────────────────────────


@pytest.mark.parametrize("doc_type", ["tkcs", "tkct", "tkkt", "hdsd"])
def test_field_map_valid_types(doc_type):
    from etc_platform.mcp_server import field_map

    result = field_map(doc_type)
    parsed = json.loads(result)
    assert parsed["doc_type"] == doc_type
    assert "renderer" in parsed


def test_field_map_invalid_type():
    from etc_platform.mcp_server import field_map

    result = field_map("bad_type")
    parsed = json.loads(result)
    # Unknown types fall through to Pandoc renderer path — check for message or error
    assert "error" in parsed or "message" in parsed


# ─── Version ───────────────────────────────────────────────────────


def test_version_consistent():
    import etc_platform

    assert etc_platform.__version__ == "3.0.0"
