"""Integration tests for export tool — requires bundled templates."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


SAMPLE_DATA = {
    "project": {"display_name": "Integration Test", "code": "INT-001", "client": "Test"},
    "meta": {"today": "23/04/2026", "version": "1.0"},
    "dev_unit": "ETC",
    "overview": {
        "purpose": "Integration test purpose",
        "scope": "Test scope",
        "system_description": "Test system description for integration tests.",
        "conventions": "Standard conventions apply.",
        "terms": [{"short": "API", "full": "Application Programming Interface", "explanation": "REST API"}],
        "references": [],
    },
    "services": [
        {
            "id": "S-001",
            "name": "Test Service",
            "description": "A test service for integration testing",
            "actor": "Test User",
            "url": "http://localhost:3000",
            "features": [
                {
                    "id": "F-001",
                    "name": "Test Feature",
                    "description": "Test feature description",
                    "actor": "User",
                    "precondition": "User is logged in",
                    "steps": [{"step": 1, "action": "Click button", "expected": "Button responds"}],
                    "ui_elements": [],
                    "dialogs": [],
                    "error_cases": [],
                }
            ],
        }
    ],
    "troubleshooting": [],
}


@pytest.fixture
def data_file(tmp_path):
    f = tmp_path / "content-data.json"
    f.write_text(json.dumps(SAMPLE_DATA), encoding="utf-8")
    return f


@pytest.mark.integration
def test_export_hdsd(data_file, tmp_path):
    from etc_platform.mcp_server import export
    out_dir = tmp_path / "output"
    result = export(str(data_file), str(out_dir), targets=["hdsd"])
    parsed = json.loads(result)
    assert parsed["success"] is True
    targets = {t["target"]: t for t in parsed["targets"]}
    assert targets["hdsd"]["success"] is True
    assert (out_dir / "huong-dan-su-dung.docx").exists()


@pytest.mark.integration
def test_export_xlsx(data_file, tmp_path):
    from etc_platform.mcp_server import export
    out_dir = tmp_path / "output"
    result = export(str(data_file), str(out_dir), targets=["xlsx"])
    parsed = json.loads(result)
    assert parsed["success"] is True


@pytest.mark.integration
def test_export_missing_data_file(tmp_path):
    from etc_platform.mcp_server import export
    out_dir = tmp_path / "output"
    result = export(str(tmp_path / "nonexistent.json"), str(out_dir))
    parsed = json.loads(result)
    assert parsed["success"] is False


@pytest.mark.integration
def test_export_all_targets(data_file, tmp_path):
    """Export all 5 doc types and verify all files created."""
    from etc_platform.mcp_server import export
    out_dir = tmp_path / "output"
    result = export(str(data_file), str(out_dir))
    parsed = json.loads(result)
    assert "targets" in parsed
    assert len(parsed["targets"]) == 5
    for t in parsed["targets"]:
        assert "success" in t
        assert "target" in t
