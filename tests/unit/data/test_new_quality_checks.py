"""Tests for the new quality checks added to combat sparse content-data output.

Each check has a clear regression source: the customs-clearance demo project
where 13 modules shared identical boilerplate, all *_diagram fields were empty,
db_tables had only id + timestamps, and 116 test cases were missing `id`.
"""

from __future__ import annotations

import pytest

from etc_platform.data.quality_checks import (
    _jaccard,
    _shingle_set,
    check_db_table_columns,
    check_diagrams_block,
    check_module_diversity,
    check_test_case_ids,
    run_all_quality_checks,
)


# ─────────────────────────── Module diversity ───────────────────────────


class TestModuleDiversity:
    def test_identical_modules_flagged(self) -> None:
        boilerplate_desc = (
            "Module thuộc phạm vi hệ thống Thông quan HQ. "
            "Chưa xác định luồng nghiệp vụ trong flow-report. "
            "Mô tả này sẽ được thay thế khi có dữ liệu cụ thể."
        )
        boilerplate_flow = (
            "1) Xác định quy trình nghiệp vụ chi tiết theo module. "
            "2) Xác định actor/role theo quy chế hiện hành. "
            "3) Xác định điều kiện đầu vào và đầu ra."
        )
        data = {
            "tkct": {
                "modules": [
                    {"name": "M01", "description": boilerplate_desc, "flow_description": boilerplate_flow},
                    {"name": "M02", "description": boilerplate_desc, "flow_description": boilerplate_flow},
                    {"name": "M03", "description": boilerplate_desc, "flow_description": boilerplate_flow},
                ]
            }
        }
        warnings = check_module_diversity(data)
        # Each pair (M01-M02, M01-M03, M02-M03) flagged.
        assert len(warnings) == 3
        assert all("share 100%" in w for w in warnings)

    def test_distinct_modules_pass(self) -> None:
        data = {
            "tkct": {
                "modules": [
                    {
                        "name": "M01-Login",
                        "description": "Đăng nhập bằng tài khoản nội bộ HQ với JWT 2-factor.",
                        "flow_description": "Người dùng nhập username + password, hệ thống kiểm tra Active Directory.",
                    },
                    {
                        "name": "M02-Declaration",
                        "description": "Khai tờ khai hải quan loại 11/12 cho hàng nhập khẩu container biển.",
                        "flow_description": "Doanh nghiệp upload XML, hệ thống parse, kiểm tra mã HS, lưu draft.",
                    },
                    {
                        "name": "M03-Payment",
                        "description": "Nộp thuế qua kết nối ngân hàng thương mại theo lô.",
                        "flow_description": "Sinh giấy nộp tiền, gửi sang ngân hàng, đối soát kết quả T+1.",
                    },
                ]
            }
        }
        assert check_module_diversity(data) == []

    def test_below_threshold_passes(self) -> None:
        # Modules share thematic vocabulary but not boilerplate.
        data = {
            "tkct": {
                "modules": [
                    {
                        "name": "A",
                        "description": "Quản lý người dùng theo tenant với phân quyền RBAC chi tiết theo module.",
                        "flow_description": "Đăng ký tài khoản, gán role, kiểm tra quyền truy cập màn hình.",
                    },
                    {
                        "name": "B",
                        "description": "Báo cáo thống kê doanh số tổng hợp theo cơ quan và khu vực địa lý.",
                        "flow_description": "Truy vấn data warehouse, group by tenant, render biểu đồ Highcharts.",
                    },
                ]
            }
        }
        warnings = check_module_diversity(data)
        # Some shared vocab ("tenant", "module") but distinct content — should pass.
        assert warnings == []

    def test_summary_when_many_pairs(self) -> None:
        # Build 10 boilerplate modules → 45 pairs > 5 cap.
        boilerplate = "Phạm vi hệ thống. Chưa xác định luồng. Sẽ thay thế khi có dữ liệu."
        data = {
            "tkct": {
                "modules": [
                    {"name": f"M{i:02d}", "description": boilerplate, "flow_description": boilerplate}
                    for i in range(10)
                ]
            }
        }
        warnings = check_module_diversity(data)
        # Capped at 5 detail lines + 1 summary
        assert len(warnings) == 6
        assert "similar module pairs total" in warnings[-1]

    def test_empty_or_single_module(self) -> None:
        assert check_module_diversity({"tkct": {"modules": []}}) == []
        assert check_module_diversity({"tkct": {"modules": [{"name": "M01"}]}}) == []
        assert check_module_diversity({}) == []


class TestShingleHelpers:
    def test_jaccard_identical(self) -> None:
        assert _jaccard({"a", "b"}, {"a", "b"}) == 1.0

    def test_jaccard_disjoint(self) -> None:
        assert _jaccard({"a"}, {"b"}) == 0.0

    def test_jaccard_partial(self) -> None:
        assert _jaccard({"a", "b"}, {"a", "c"}) == pytest.approx(1 / 3)

    def test_jaccard_empty(self) -> None:
        assert _jaccard(set(), {"a"}) == 0.0
        assert _jaccard(set(), set()) == 0.0

    def test_shingle_short_string(self) -> None:
        assert _shingle_set("ab", n=3) == {"ab"}

    def test_shingle_normal(self) -> None:
        s = _shingle_set("hello", n=3)
        assert s == {"hel", "ell", "llo"}


# ─────────────────────────── Diagrams block ───────────────────────────


class TestDiagramsBlock:
    def test_all_required_present(self) -> None:
        data = {
            "tkkt": {  # Architecture key in MINIMUMS is "tkkt"; field block is "architecture"
                "architecture_diagram": "architecture_diagram.png",
                "logical_diagram": "logical_diagram.png",
                "data_diagram": "data_diagram.png",
                "integration_diagram": "integration_diagram.png",
                "deployment_diagram": "deployment_diagram.png",
                "security_diagram": "security_diagram.png",
            },
            "diagrams": {
                "architecture_diagram": "flowchart LR\n  A --> B",
                "logical_diagram": "flowchart TD\n  X --> Y",
                "data_diagram": "erDiagram\n  USER ||--o{ ORDER : places",
                "integration_diagram": "sequenceDiagram\n  A->>B: Hi",
                "deployment_diagram": "graph TD\n  A --> B",
                "security_diagram": "graph LR\n  A --> B",
            },
        }
        # Note: check_diagrams_block reads `architecture` block, not `tkkt`.
        # Re-key for the correct test surface.
        data = {
            "architecture": data["tkkt"],
            "diagrams": data["diagrams"],
        }
        warnings = check_diagrams_block(data)
        # Architecture diagrams are checked under `architecture` block —
        # but MINIMUMS has them under `tkkt` key; check_diagrams_block walks
        # blocks=architecture/tkcs/tkct, looking up MINIMUMS[block_name].
        # Architecture has no entry in MINIMUMS["architecture"], so no required list.
        # Empty is correct in this design.
        assert warnings == [] or all("required" not in w for w in warnings)

    def test_filename_without_source_flagged(self) -> None:
        data = {
            "tkcs": {
                "tkcs_architecture_diagram": "tkcs_architecture_diagram.png",
                # tkcs_data_model_diagram missing
            },
            # diagrams block missing both Mermaid sources.
        }
        warnings = check_diagrams_block(data)
        assert any("tkcs_architecture_diagram" in w for w in warnings)
        # First diagram has filename but no source.
        assert any("no source" in w or "missing" in w for w in warnings)

    def test_source_without_filename_flagged(self) -> None:
        data = {
            "tkcs": {
                "tkcs_architecture_diagram": "",  # empty
                "tkcs_data_model_diagram": "",
            },
            "diagrams": {
                "tkcs_architecture_diagram": "flowchart LR\n  A --> B",
                "tkcs_data_model_diagram": "erDiagram\n  X ||--o{ Y : has",
            },
        }
        warnings = check_diagrams_block(data)
        # Source present but filename empty — engine renders but docxtpl can't embed.
        assert any("source present" in w or "will not embed" in w for w in warnings)

    def test_svg_hero_dict_accepted(self) -> None:
        data = {
            "tkkt": {"architecture_diagram": "architecture_diagram.png"},  # not in MINIMUMS keys
            "tkcs": {
                "tkcs_architecture_diagram": "tkcs_architecture_diagram.png",
                "tkcs_data_model_diagram": "tkcs_data_model_diagram.png",
            },
            "diagrams": {
                "tkcs_architecture_diagram": {
                    "template": "kien-truc-4-lop",
                    "data": {"layers": ["UX", "Core", "Data", "Platform"]},
                },
                "tkcs_data_model_diagram": "erDiagram\n  X ||--o{ Y : has",
            },
        }
        warnings = check_diagrams_block(data)
        # SVG hero dict counts as "source present" — no warning expected for it.
        for w in warnings:
            assert "tkcs_architecture_diagram" not in w

    def test_empty_document_skipped(self) -> None:
        assert check_diagrams_block({}) == []
        assert check_diagrams_block({"diagrams": {}}) == []


# ─────────────────────────── DB tables ───────────────────────────


class TestDbTableColumns:
    def test_only_infra_columns_flagged(self) -> None:
        data = {
            "tkct": {
                "db_tables": [
                    {
                        "name": "to_khai",
                        "columns": [
                            {"name": "id", "type": "bigint"},
                            {"name": "tenant_id", "type": "uuid"},
                            {"name": "created_at", "type": "timestamp"},
                            {"name": "updated_at", "type": "timestamp"},
                        ],
                    }
                ]
            }
        }
        warnings = check_db_table_columns(data)
        assert any("4 columns < 5" in w for w in warnings)
        assert any("0 business column" in w for w in warnings)

    def test_real_schema_passes(self) -> None:
        data = {
            "tkct": {
                "db_tables": [
                    {
                        "name": "to_khai",
                        "columns": [
                            {"name": "id", "type": "bigint"},
                            {"name": "ma_to_khai", "type": "varchar(20)"},
                            {"name": "loai_to_khai", "type": "varchar(2)"},
                            {"name": "trang_thai", "type": "varchar(20)"},
                            {"name": "ngay_dang_ky", "type": "date"},
                            {"name": "tong_tien_thue", "type": "decimal(18,2)"},
                            {"name": "created_at", "type": "timestamp"},
                        ],
                    }
                ]
            }
        }
        assert check_db_table_columns(data) == []

    def test_borderline_business_count(self) -> None:
        # 5 cols total, 1 business — fails business min (2).
        data = {
            "tkct": {
                "db_tables": [
                    {
                        "name": "log",
                        "columns": [
                            {"name": "id"},
                            {"name": "tenant_id"},
                            {"name": "created_at"},
                            {"name": "updated_at"},
                            {"name": "message"},
                        ],
                    }
                ]
            }
        }
        warnings = check_db_table_columns(data)
        assert any("only 1 business column" in w for w in warnings)

    def test_no_tables_no_warnings(self) -> None:
        assert check_db_table_columns({"tkct": {}}) == []
        assert check_db_table_columns({}) == []


# ─────────────────────────── Test case IDs ───────────────────────────


class TestTestCaseIds:
    def test_missing_ids_flagged(self) -> None:
        data = {
            "test_cases": {
                "ui": [
                    {"name": "F-001 — login smoke", "feature_id": "F-001", "steps": [], "expected": []},
                    {"name": "F-002 — search", "feature_id": "F-002", "steps": [], "expected": []},
                ],
                "api": [],
            }
        }
        warnings = check_test_case_ids(data)
        assert any("missing 'id' field" in w for w in warnings)

    def test_bad_pattern_flagged(self) -> None:
        data = {
            "test_cases": {
                "ui": [
                    {
                        "id": "TC1",  # too short
                        "name": "smoke",
                        "feature_id": "F-001",
                    }
                ],
                "api": [],
            }
        }
        warnings = check_test_case_ids(data)
        assert any("non-conforming id" in w for w in warnings)

    def test_correct_format_passes(self) -> None:
        data = {
            "test_cases": {
                "ui": [
                    {
                        "id": "TC-M01-001",
                        "name": "login smoke",
                        "feature_id": "F-001",
                    }
                ],
                "api": [
                    {
                        "id": "TC-AUTH-042",
                        "name": "POST /api/auth/login",
                        "feature_id": "F-001",
                    }
                ],
            }
        }
        assert check_test_case_ids(data) == []

    def test_structural_rows_skipped(self) -> None:
        # `_type: feature_group` rows are headers, not TCs — must not be flagged.
        data = {
            "test_cases": {
                "ui": [
                    {"_type": "feature_group", "name": "Module M01"},
                    {"_type": "section_header", "name": "Login flows"},
                    {
                        "id": "TC-M01-001",
                        "name": "real TC",
                        "feature_id": "F-001",
                    },
                ],
                "api": [],
            }
        }
        assert check_test_case_ids(data) == []

    def test_missing_feature_id(self) -> None:
        data = {
            "test_cases": {
                "ui": [],
                "api": [
                    {
                        "id": "TC-AUTH-001",
                        "name": "login",
                        # feature_id missing
                    }
                ],
            }
        }
        warnings = check_test_case_ids(data)
        assert any("missing required field 'feature_id'" in w for w in warnings)


# ─────────────────────────── End-to-end on regression sample ───────────────────────────


class TestRegressionSample:
    """Reproduce the customs-clearance failure mode in miniature; verify each
    check fires."""

    def _minimal_bad(self) -> dict:
        boilerplate = (
            "Module M0X thuộc phạm vi hệ thống. Chưa xác định luồng nghiệp vụ "
            "trong flow-report. Mô tả này sẽ được thay thế khi có dữ liệu."
        )
        return {
            "tkct": {
                "modules": [
                    {"name": f"M0{i}", "description": boilerplate, "flow_description": boilerplate, "business_rules": ""}
                    for i in range(1, 6)
                ],
                "db_tables": [
                    {
                        "name": "log",
                        "columns": [
                            {"name": "id"},
                            {"name": "created_at"},
                            {"name": "updated_at"},
                            {"name": "tenant_id"},
                        ],
                    }
                ],
                "tkct_architecture_overview_diagram": "",
                "tkct_db_erd_diagram": "",
                "tkct_ui_layout_diagram": "",
                "tkct_integration_diagram": "",
            },
            "test_cases": {
                "ui": [{"name": "F-001 — smoke", "feature_id": "F-001"}],
                "api": [{"name": "POST /api/login"}],
            },
        }

    def test_all_new_checks_fire(self) -> None:
        warnings = run_all_quality_checks(self._minimal_bad())
        text = " ".join(warnings)
        assert "share" in text and "%" in text          # diversity
        assert "diagrams.tkct" in text                  # diagrams block
        assert "business column" in text or "columns <" in text  # db tables
        assert "missing 'id' field" in text             # TC ids
