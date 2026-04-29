"""Validation logic for content-data.json using Pydantic models.

Provides both strict (Pydantic) and advisory (coverage, consistency) validation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from etc_platform.data.models import ContentData


@dataclass
class ValidationResult:
    """Structured validation output."""

    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "stats": self.stats,
        }


def validate_content_data(data: dict) -> ValidationResult:
    """Full validation: schema + advisory checks.

    Returns ValidationResult with errors (blocking) and warnings (advisory).
    """
    result = ValidationResult()

    # ── Step 1: Pydantic schema validation ──
    try:
        model = ContentData.model_validate(data)
    except Exception as e:
        result.valid = False
        result.errors.append(f"Schema validation failed: {e}")
        return result

    # ── Step 2: Stats ──
    ui_tcs = [
        r
        for r in model.test_cases.ui
        if not hasattr(r, "_type") or getattr(r, "_type", None) is None
    ]
    api_tcs = [
        r
        for r in model.test_cases.api
        if not hasattr(r, "_type") or getattr(r, "_type", None) is None
    ]

    # Count actual test case rows (not headers)
    from etc_platform.data.models import TestCaseRow

    ui_tc_count = sum(1 for r in model.test_cases.ui if isinstance(r, TestCaseRow))
    api_tc_count = sum(1 for r in model.test_cases.api if isinstance(r, TestCaseRow))

    result.stats = {
        "services": len(model.services),
        "features": sum(len(svc.features) for svc in model.services),
        "test_cases_ui": ui_tc_count,
        "test_cases_api": api_tc_count,
        "test_cases_total": ui_tc_count + api_tc_count,
    }

    # ── Step 3: Advisory — feature coverage ──
    coverage = model.coverage_report()
    if coverage["missing_coverage"]:
        result.warnings.append(
            f"Features without test cases: {', '.join(coverage['missing_coverage'])}"
        )
    if coverage["orphan_tc_refs"]:
        result.warnings.append(
            f"Test cases reference undefined features: {', '.join(coverage['orphan_tc_refs'])}"
        )

    # ── Step 4: Advisory — empty test case sheets ──
    if ui_tc_count == 0 and api_tc_count == 0:
        result.warnings.append("No test cases found in either ui or api sheet")

    # ── Step 5: Advisory — feature_group without feature_id ──
    from etc_platform.data.models import FeatureGroupRow

    for sheet_name, items in [("ui", model.test_cases.ui), ("api", model.test_cases.api)]:
        for item in items:
            if isinstance(item, FeatureGroupRow) and not item.feature_id:
                result.warnings.append(
                    f"test_cases.{sheet_name}: feature_group '{item.title}' "
                    f"has no feature_id (cross-validation disabled)"
                )

    # ── Step 6: Advisory — priority distribution ──
    from etc_platform.data.models import Priority

    priority_counts: dict[str, int] = {}
    for sheet_items in (model.test_cases.ui, model.test_cases.api):
        for item in sheet_items:
            if isinstance(item, TestCaseRow):
                pri_name = (
                    item.priority.value
                    if isinstance(item.priority, Priority)
                    else str(item.priority)
                )
                priority_counts[pri_name] = priority_counts.get(pri_name, 0) + 1
    result.stats["priority_distribution"] = priority_counts

    # ── Step 7: Quality checks (Phase 1 integrity + Phase 2/3 depth) ──
    try:
        from etc_platform.data.quality_checks import run_all_quality_checks
        quality_warnings = run_all_quality_checks(data)
        result.warnings.extend(quality_warnings)
        result.stats["quality_warnings_count"] = len(quality_warnings)
    except Exception as e:
        result.warnings.append(f"quality_checks failed: {e}")

    return result


def validate_file(path: Path) -> ValidationResult:
    """Load and validate a content-data.json file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        result = ValidationResult(valid=False)
        result.errors.append(f"Invalid JSON: {e}")
        return result
    except FileNotFoundError:
        result = ValidationResult(valid=False)
        result.errors.append(f"File not found: {path}")
        return result

    return validate_content_data(data)


def generate_json_schema() -> dict:
    """Generate JSON Schema from the Pydantic models."""
    return ContentData.model_json_schema()
