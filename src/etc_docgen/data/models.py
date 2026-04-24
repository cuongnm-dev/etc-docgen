"""Pydantic models for content-data.json — the contract between AI agents and engines.

This is the single source of truth for the data format. Both producers (agents,
Playwright capture, AI data-writers) and consumers (xlsx/docx engines) reference
these models.

Design principles:
  - Match common output formats from testing tools (Xray, TestRail, Playwright)
  - Accept Vietnamese input, normalize internally (priorities, dates)
  - Cross-reference features ↔ test cases via feature_id
  - Validate completeness (coverage gaps reported as warnings, not errors)
"""

from __future__ import annotations

import re
import unicodedata
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ──────────────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────────────


class Priority(str, Enum):
    """Test case priority — accepts Vietnamese or English input."""

    CRITICAL = "Critical"
    MAJOR = "Major"
    NORMAL = "Normal"
    MINOR = "Minor"

    @classmethod
    def _missing_(cls, value: object) -> Priority | None:
        if not isinstance(value, str):
            return None
        return _PRIORITY_LOOKUP.get(_normalize_vn(value))


def _normalize_vn(s: str) -> str:
    """Strip Vietnamese diacritics + lowercase for fuzzy matching."""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


_PRIORITY_LOOKUP: dict[str, Priority] = {
    # Vietnamese (with and without diacritics)
    "rat cao": Priority.CRITICAL,
    "rất cao": Priority.CRITICAL,
    "cao": Priority.MAJOR,
    "trung binh": Priority.NORMAL,
    "trung bình": Priority.NORMAL,
    "thap": Priority.MINOR,
    "thấp": Priority.MINOR,
    # English
    "critical": Priority.CRITICAL,
    "major": Priority.MAJOR,
    "normal": Priority.NORMAL,
    "minor": Priority.MINOR,
    # Common aliases
    "high": Priority.MAJOR,
    "medium": Priority.NORMAL,
    "low": Priority.MINOR,
    "blocker": Priority.CRITICAL,
    "trivial": Priority.MINOR,
    # TestRail style (P1-P4)
    "p1": Priority.CRITICAL,
    "p2": Priority.MAJOR,
    "p3": Priority.NORMAL,
    "p4": Priority.MINOR,
}


# ──────────────────────────────────────────────────────────────────
# Shared / reusable components
# ──────────────────────────────────────────────────────────────────


class TestStep(BaseModel):
    """A single test step — compatible with Xray/TestRail/Playwright output."""

    no: int = Field(ge=1, description="Step sequence number (1-based)")
    action: str = Field(min_length=1, description="Action to perform")
    data: str = Field(default="", description="Test data for this step")
    expected: str = Field(default="", description="Expected result")
    screenshot: str = Field(default="", description="Screenshot filename (F-XXX-step-NN-state.png)")

    @field_validator("screenshot")
    @classmethod
    def validate_screenshot_naming(cls, v: str) -> str:
        if v and not re.match(r"^[A-Z]+-\d{3}-step-\d{2}-[a-z]+\.png$", v):
            pass  # warning-level, don't block — agents may use slightly different naming
        return v


class ExpectedResult(BaseModel):
    """Expected result — separate model for backward compat with split steps/expected."""

    no: int = Field(ge=1)
    expected: str = Field(min_length=1)


# ──────────────────────────────────────────────────────────────────
# Test case types (for xlsx engine)
# ──────────────────────────────────────────────────────────────────


class FeatureGroupRow(BaseModel):
    """Feature group header — rendered as merged colored row in Excel."""

    _type: Literal["feature_group"] = "feature_group"
    title: str = Field(min_length=1, description="Feature group display name")
    feature_id: str = Field(
        default="",
        description="Links to services[].features[].id for cross-validation",
    )

    # Allow both `type` and `_type` as input key
    @model_validator(mode="before")
    @classmethod
    def normalize_type_field(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "type" in data and "_type" not in data:
                data["_type"] = data.pop("type")
        return data


class SectionHeaderRow(BaseModel):
    """Section header — rendered as merged light-colored row in Excel."""

    _type: Literal["section_header"] = "section_header"
    title: str = Field(min_length=1, description="Section header text (supports \\n)")

    @model_validator(mode="before")
    @classmethod
    def normalize_type_field(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "type" in data and "_type" not in data:
                data["_type"] = data.pop("type")
        return data


class TestCaseRow(BaseModel):
    """A single test case row — the primary data unit.

    Supports two step formats:
      1. Unified: steps[] with action + expected in each step (Playwright/Xray style)
      2. Split:   steps[] (actions only) + expected[] (results only) — legacy/Excel-native

    The engine normalizes to the split format for Excel column C/D mapping.
    """

    name: str = Field(min_length=1, description="Test case name → Excel col B")

    # Format 1: unified steps (preferred — matches Playwright/Xray/TestRail)
    steps: list[TestStep | dict] = Field(
        default_factory=list,
        description="Test steps with action (+ optional expected per step)",
    )

    # Format 2: split expected (backward compat)
    expected: list[ExpectedResult | dict] = Field(
        default_factory=list,
        description="Expected results (if not embedded in steps)",
    )

    priority: Priority = Field(
        default=Priority.NORMAL,
        description="Severity: Rất cao|Cao|Trung bình|Thấp or Critical|Major|Normal|Minor",
    )
    preconditions: str = Field(default="", description="Preconditions for this TC")
    checklog: str = Field(default="", description="Check log reference → Excel col E")
    redirect: str = Field(default="", description="Redirect/navigation target → Excel col F")
    notes: str = Field(default="", description="Additional notes → Excel col M")

    # Traceability (industry standard)
    feature_id: str = Field(
        default="",
        description="Links to services[].features[].id (e.g. F-001)",
    )
    tc_id: str = Field(
        default="",
        description="Unique test case ID (auto-generated if empty)",
    )
    labels: list[str] = Field(
        default_factory=list,
        description="Tags/labels: ['smoke', 'regression', 'ui']",
    )

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, v: Any) -> Priority:
        if isinstance(v, Priority):
            return v
        if isinstance(v, str):
            result = Priority._missing_(v)
            if result is not None:
                return result
        return Priority.NORMAL

    def get_steps_for_excel(self) -> list[dict]:
        """Normalize steps to [{no, action}] for Excel col C."""
        if self.steps:
            out = []
            for i, s in enumerate(self.steps, 1):
                if isinstance(s, TestStep):
                    out.append({"no": s.no, "action": s.action})
                elif isinstance(s, dict):
                    out.append({"no": s.get("no", i), "action": s.get("action", "")})
            return out
        return []

    def get_expected_for_excel(self) -> list[dict]:
        """Normalize expected to [{no, expected}] for Excel col D.

        Prefers step-embedded expected (Format 1), falls back to split (Format 2).
        """
        # Format 1: expected embedded in steps
        embedded = []
        for i, s in enumerate(self.steps, 1):
            if isinstance(s, TestStep) and s.expected:
                embedded.append({"no": s.no, "expected": s.expected})
            elif isinstance(s, dict) and s.get("expected"):
                embedded.append({"no": s.get("no", i), "expected": s["expected"]})
        if embedded:
            return embedded

        # Format 2: separate expected list
        out = []
        for i, e in enumerate(self.expected, 1):
            if isinstance(e, ExpectedResult):
                out.append({"no": e.no, "expected": e.expected})
            elif isinstance(e, dict):
                out.append({"no": e.get("no", i), "expected": e.get("expected", "")})
        return out


# Type alias for a row in test_cases.ui / test_cases.api
TestCaseItem = FeatureGroupRow | SectionHeaderRow | TestCaseRow


# ──────────────────────────────────────────────────────────────────
# Feature model (for services — HDSD/TKCS use)
# ──────────────────────────────────────────────────────────────────


class UIElement(BaseModel):
    label: str
    type: str = ""
    rules: str = ""


class FeatureStep(BaseModel):
    """HDSD feature step — different from TestStep (has screenshot, no expected)."""

    no: int = Field(ge=1)
    action: str
    screenshot: str = ""
    expected: str = ""


class DialogComponent(BaseModel):
    name: str
    description: str = ""


class Dialog(BaseModel):
    title: str
    components: list[DialogComponent] = Field(default_factory=list)


class ErrorCase(BaseModel):
    trigger_step: int = 0
    condition: str = ""
    message: str = ""


class Feature(BaseModel):
    """A single feature — used by HDSD (docx) and cross-referenced by test cases."""

    id: str = Field(pattern=r"^F-\d{3,4}$", description="Feature ID: F-001, F-0012")
    name: str = Field(min_length=1)
    description: str = ""
    actors: list[str] = Field(default_factory=list)
    preconditions: str = ""
    ui_elements: list[UIElement] = Field(default_factory=list)
    steps: list[FeatureStep] = Field(default_factory=list)
    dialogs: list[Dialog] = Field(default_factory=list)
    error_cases: list[ErrorCase] = Field(default_factory=list)


class Service(BaseModel):
    """A service/module grouping features."""

    slug: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    features: list[Feature] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────
# Top-level content-data model
# ──────────────────────────────────────────────────────────────────


class ProjectInfo(BaseModel):
    display_name: str = Field(min_length=1)
    code: str = ""
    client: str = ""
    description: str = ""
    tech_stack: str = ""


class Meta(BaseModel):
    today: str = Field(description="dd/mm/yyyy format")
    version: str = "1.0"
    test_period: str = ""

    @field_validator("today")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        if v and not re.match(r"^\d{2}/\d{2}/\d{4}$", v):
            pass  # warning-level: allow flexible dates but prefer dd/mm/yyyy
        return v


class Term(BaseModel):
    short: str
    full: str
    explanation: str = ""


class Reference(BaseModel):
    stt: str = ""
    name: str
    ref: str = ""


class Overview(BaseModel):
    purpose: str = ""
    scope: str = ""
    system_description: str = ""
    conventions: str = ""
    terms: list[Term] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)


class TroubleshootingItem(BaseModel):
    """FAQ/troubleshooting entry — rendered in HDSD Section 2.4."""

    situation: str = Field(min_length=1, description="Problem description")
    cause: str = Field(default="", description="Root cause")
    resolution: str = Field(default="", description="How to fix")


class TechStackItem(BaseModel):
    layer: str = ""
    technology: str = ""
    version: str = ""
    role: str = ""


class ArchComponent(BaseModel):
    name: str = ""
    type: str = ""
    description: str = ""


class DataEntity(BaseModel):
    name: str = ""
    purpose: str = ""
    storage_type: str = "PostgreSQL"


class ApiEndpoint(BaseModel):
    path: str = ""
    method: str = ""
    description: str = ""
    auth: str = "JWT Bearer"


class ExternalIntegration(BaseModel):
    system: str = ""
    protocol: str = ""
    purpose: str = ""


class DeployEnvironment(BaseModel):
    name: str = ""
    infrastructure: str = ""
    purpose: str = ""


class ContainerInfo(BaseModel):
    name: str = ""
    image: str = ""
    port: str | None = ""
    depends_on: list[str] = Field(default_factory=list)


class NfrItem(BaseModel):
    criterion: str = ""
    requirement: str = ""
    solution: str = ""


class Architecture(BaseModel):
    """Architecture data — consumed by TKKT (docx) and HDSD system_overview fallback."""

    purpose: str = ""
    scope: str = ""
    system_overview: str = ""
    scope_description: str = ""
    business_overview: str = Field(default="", description="Tổng quan nghiệp vụ — Business view per Khung KT CPĐT 4.0")
    design_principles: str = Field(default="", description="Nguyên tắc thiết kế kiến trúc (scalability, security-by-design, modularity)")
    tech_stack: list[TechStackItem] = Field(default_factory=list)
    logical_description: str = ""
    components: list[ArchComponent] = Field(default_factory=list)
    interaction_description: str = ""
    data_description: str = ""
    data_entities: list[DataEntity] = Field(default_factory=list)
    integration_description: str = ""
    apis: list[ApiEndpoint] = Field(default_factory=list)
    external_integrations: list[ExternalIntegration] = Field(default_factory=list)
    deployment_description: str = ""
    environments: list[DeployEnvironment] = Field(default_factory=list)
    containers: list[ContainerInfo] = Field(default_factory=list)
    security_description: str = ""
    auth_description: str = ""
    data_protection: str = ""
    nfr: list[NfrItem] = Field(default_factory=list)

    # Diagrams (image filenames — resolved to InlineImage at render time)
    architecture_diagram: str = Field(default="", description="Sơ đồ kiến trúc tổng thể")
    logical_diagram: str = Field(default="", description="Sơ đồ kiến trúc logic")
    data_diagram: str = Field(default="", description="Sơ đồ mô hình dữ liệu (ERD tổng quan)")
    deployment_diagram: str = Field(default="", description="Sơ đồ kiến trúc triển khai")
    integration_diagram: str = Field(default="", description="Sơ đồ tích hợp hệ thống")
    security_diagram: str = Field(default="", description="Sơ đồ kiến trúc bảo mật")


class TkcsData(BaseModel):
    """TKCS-specific data — consumed by thiet-ke-co-so.docx template.

    Outline follows NĐ 73/2019 Điều 13 (thay thế bởi NĐ 45/2026 Điều 13):
    Section 1: Giới thiệu chung (filled from project/overview)
    Section 2-11: TKCS-specific content below
    """

    # Sự cần thiết đầu tư
    legal_basis: str = Field(default="", description="Cơ sở pháp lý (viện dẫn QĐ, NĐ, CT)")
    current_state: str = Field(default="", description="Hiện trạng hệ thống/quy trình hiện tại")
    necessity: str = Field(default="", description="Sự cần thiết đầu tư")

    # Đánh giá phù hợp quy hoạch
    architecture_compliance: str = Field(
        default="",
        description="Phù hợp Khung KTCPĐT, Kế hoạch ứng dụng CNTT",
    )

    # Phân tích lựa chọn công nghệ
    technology_rationale: str = Field(default="", description="Phân tích lựa chọn phương án CN")

    # Thiết kế cơ sở phương án chọn
    detailed_design_summary: str = Field(default="", description="Tổng quan thiết kế cơ sở")
    functional_design: str = Field(default="", description="Thiết kế chức năng tổng quan")
    db_design_summary: str = Field(default="", description="Thiết kế CSDL tổng quan")
    integration_design_summary: str = Field(default="", description="Thiết kế tích hợp tổng quan")

    # Phương án ATTT
    security_plan: str = Field(default="", description="Phương án bảo đảm ATTT")

    # Tổ chức vận hành
    operations_plan: str = Field(default="", description="Phương án tổ chức quản lý, khai thác")

    # Tiến độ
    timeline: str = Field(default="", description="Dự kiến tiến độ thực hiện")

    # Tổng mức đầu tư + vận hành
    total_investment: str = Field(default="", description="Xác định tổng mức đầu tư")
    operating_cost: str = Field(default="", description="Chi phí vận hành hàng năm")

    # Tổ chức QLDA
    project_management: str = Field(default="", description="Mô hình tổ chức quản lý dự án")

    # Thông tin bổ sung (hiển thị trong Section 1)
    investment_type: str = Field(
        default="", description="Đầu tư mới / Nâng cấp / Thuê dịch vụ CNTT"
    )
    funding_source: str = Field(default="", description="Ngân sách nhà nước / Vốn tự có")
    project_duration: str = Field(default="", description="Thời gian thực hiện dự kiến")

    # Diagrams (image filenames)
    architecture_diagram: str = Field(default="", description="Sơ đồ kiến trúc phương án chọn")
    data_model_diagram: str = Field(default="", description="Sơ đồ mô hình dữ liệu tổng quan")

    # ── NĐ 45/2026 Điều 13 — 11-section expansion (added 2026-04) ──
    # Sec 3c — Mục tiêu đầu tư (tách khỏi necessity)
    objectives: str = Field(default="", description="Mục tiêu đầu tư tổng quát + cụ thể, có KPI đo được")

    # Sec 5 — Phân tích lựa chọn công nghệ (chi tiết)
    software_arch_pattern: str = Field(default="", description="Pattern kiến trúc phần mềm (microservices/monolith/SOA)")
    dbms_choice: str = Field(default="", description="Lựa chọn DBMS có biện luận (RDBMS vs NoSQL, vendor)")
    os_choice: str = Field(default="", description="Lựa chọn hệ điều hành máy chủ (Linux distro / Windows Server)")
    standards: str = Field(default="", description="Tiêu chuẩn áp dụng (TCVN, ISO, IEEE, OpenAPI)")

    # Sec 6d — Thiết kế phần mềm + hạ tầng chi tiết
    software_design: str = Field(default="", description="Thiết kế phần mềm tổng quan (module, layer, interface)")
    infrastructure_design: str = Field(default="", description="Thiết kế hạ tầng (server, network, storage)")

    # Sec 7 — An toàn thông tin (chi tiết)
    security_design: str = Field(default="", description="Thiết kế bảo mật chi tiết theo TCVN 11930 (quản lý/kỹ thuật/vật lý/con người/vận hành)")
    security_tech: str = Field(default="", description="Giải pháp kỹ thuật ATTT (WAF, SIEM, IDS/IPS, mã hóa)")

    # Sec 8 — Vận hành & chuẩn bị
    prep_resources: str = Field(default="", description="Chuẩn bị nhân lực, thiết bị, hạ tầng vận hành")
    prep_policies: str = Field(default="", description="Chuẩn bị quy chế, quy trình vận hành")
    user_support: str = Field(default="", description="Phương án hỗ trợ, đào tạo người dùng")

    # Sec 9 — Tiến độ chi tiết
    milestones: str = Field(default="", description="Các mốc (milestone) chính của dự án")
    schedule: str = Field(default="", description="Bảng tiến độ Gantt / WBS")

    # Sec 10 — Kinh phí chi tiết
    budget_detail: str = Field(default="", description="Chi tiết dự toán theo TT 04/2020/TT-BTTTT")
    opex: str = Field(default="", description="Chi phí vận hành chi tiết (O&M) hàng năm")
    warranty: str = Field(default="", description="Điều khoản bảo hành, bảo trì")

    # Sec 11 — Quản lý dự án chi tiết
    pm_form: str = Field(default="", description="Hình thức QLDA (BQL chuyên trách / kiêm nhiệm / thuê tư vấn)")
    stakeholders: str = Field(default="", description="Các bên liên quan: chủ đầu tư, nhà thầu, tư vấn, thẩm định")
    pm_method: str = Field(default="", description="Phương pháp QLDA (waterfall/agile/hybrid)")


class DbColumn(BaseModel):
    """Column specification for detailed database design."""

    name: str = ""
    type: str = ""
    nullable: bool = True
    description: str = ""
    constraints: str = Field(default="", description="PK, FK, UNIQUE, CHECK, etc.")


class DbTable(BaseModel):
    """Table specification for detailed database design."""

    name: str = ""
    description: str = ""
    columns: list[DbColumn] = Field(default_factory=list)


class ApiParameter(BaseModel):
    """API parameter specification."""

    name: str = ""
    location: str = Field(default="body", description="body | query | path | header")
    type: str = "string"
    required: bool = False
    description: str = ""


class ApiDetail(BaseModel):
    """Detailed API specification — richer than Architecture.ApiEndpoint."""

    path: str = ""
    method: str = ""
    summary: str = ""
    description: str = ""
    auth: str = "JWT Bearer"
    request_body: str = Field(default="", description="JSON schema hoặc mô tả cấu trúc request")
    response_body: str = Field(default="", description="JSON schema hoặc mô tả cấu trúc response")
    parameters: list[ApiParameter] = Field(default_factory=list)
    error_codes: list[str] = Field(default_factory=list, description="Mã lỗi: 400, 401, 404, 500")


class ScreenDesign(BaseModel):
    """UI screen specification."""

    name: str = ""
    description: str = ""
    screenshot: str = Field(default="", description="Screenshot filename")
    feature_id: str = Field(default="", description="Links to Feature.id")


class ModuleDesign(BaseModel):
    """Detailed design for a module/service."""

    name: str = ""
    description: str = ""
    flow_description: str = Field(default="", description="Mô tả luồng xử lý")
    flow_diagram: str = Field(default="", description="Sơ đồ luồng xử lý (image filename)")
    business_rules: str = Field(default="", description="Quy tắc nghiệp vụ")
    input_data: str = Field(default="", description="Dữ liệu đầu vào")
    output_data: str = Field(default="", description="Dữ liệu đầu ra")
    feature_ids: list[str] = Field(default_factory=list, description="Feature IDs liên quan")


class TkctData(BaseModel):
    """TKCT (Thiết kế chi tiết) data — consumed by thiet-ke-chi-tiet.docx template.

    Standard outline for Vietnamese IT detailed design document:
    1. Tổng quan thiết kế
    2. Thiết kế chi tiết chức năng (per module)
    3. Thiết kế cơ sở dữ liệu
    4. Thiết kế API
    5. Thiết kế giao diện
    6. Thiết kế tích hợp
    7. Thiết kế bảo mật
    8. Ma trận truy xuất nguồn gốc
    """

    # Tổng quan
    system_description: str = Field(default="", description="Mô tả tổng quan hệ thống")
    architecture_reference: str = Field(default="", description="Tham chiếu tài liệu TKKT")

    # Thiết kế chi tiết chức năng
    modules: list[ModuleDesign] = Field(default_factory=list)

    # Thiết kế CSDL
    db_description: str = Field(default="", description="Mô tả thiết kế CSDL tổng quan")
    db_tables: list[DbTable] = Field(default_factory=list)

    # Thiết kế API
    api_description: str = Field(default="", description="Mô tả thiết kế API tổng quan")
    api_details: list[ApiDetail] = Field(default_factory=list)

    # Thiết kế giao diện
    ui_guidelines: str = Field(default="", description="Quy tắc thiết kế giao diện chung")
    ui_layout: str = Field(default="", description="Bố cục giao diện chung")
    screens: list[ScreenDesign] = Field(default_factory=list)

    # Thiết kế tích hợp + bảo mật
    integration_design: str = Field(default="", description="Thiết kế tích hợp chi tiết")
    security_design: str = Field(default="", description="Thiết kế bảo mật chi tiết")

    # Diagrams (image filenames)
    architecture_overview_diagram: str = Field(default="", description="Sơ đồ kiến trúc tổng quan")
    db_erd_diagram: str = Field(default="", description="Sơ đồ ERD chi tiết")
    ui_layout_diagram: str = Field(default="", description="Sơ đồ bố cục giao diện")
    integration_diagram: str = Field(default="", description="Sơ đồ tích hợp chi tiết")

    # Ma trận truy xuất
    traceability_description: str = Field(
        default="",
        description="Mô tả ma trận truy xuất features ↔ modules ↔ test cases",
    )


class TestSheetConfig(BaseModel):
    """Optional labels for test result sheet."""

    ui_label: str = "Chức năng hệ thống"
    api_label: str = "API hệ thống"
    ui_requirement: str = "Kiểm tra các chức năng hệ thống"
    api_requirement: str = "Kiểm tra các API hệ thống"


class TestCases(BaseModel):
    """Test cases grouped by sheet — the primary input for xlsx engine."""

    ui: list[FeatureGroupRow | SectionHeaderRow | TestCaseRow] = Field(
        default_factory=list,
        description="UI test cases → 'Tên chức năng' sheet",
    )
    api: list[FeatureGroupRow | SectionHeaderRow | TestCaseRow] = Field(
        default_factory=list,
        description="API test cases → 'Tên API' sheet",
    )

    @field_validator("ui", "api", mode="before")
    @classmethod
    def parse_items(cls, v: list[Any]) -> list[Any]:
        """Discriminate row types based on _type field."""
        if not isinstance(v, list):
            return v
        parsed = []
        for item in v:
            if not isinstance(item, dict):
                parsed.append(item)
                continue
            row_type = item.get("_type") or item.get("type")
            if row_type == "feature_group":
                parsed.append(FeatureGroupRow(**item))
            elif row_type == "section_header":
                parsed.append(SectionHeaderRow(**item))
            else:
                parsed.append(TestCaseRow(**item))
        return parsed


class ContentData(BaseModel):
    """Root model for content-data.json — the contract between all pipeline phases.

    Producers:
      - Phase 1 (tdoc-researcher): populates services[], overview
      - Phase 2 (tdoc-test-runner): populates services[].features[].steps[].screenshot
      - Phase 3 (tdoc-data-writer): populates test_cases, meta, project
      - Manual: user edits directly

    Consumers:
      - xlsx engine: reads project, meta, dev_unit, test_cases, test_sheets
      - docx engine: reads project, meta, dev_unit, overview, services
    """

    project: ProjectInfo
    dev_unit: str = Field(
        default="",
        description=(
            "Development company name. Left blank by default so downstream "
            "renderers can flag it as '[CẦN BỔ SUNG]' instead of silently "
            "stamping a hardcoded vendor on third-party projects."
        ),
    )
    meta: Meta
    overview: Overview = Field(default_factory=Overview)
    test_sheets: TestSheetConfig = Field(default_factory=TestSheetConfig)
    services: list[Service] = Field(default_factory=list)
    test_cases: TestCases = Field(default_factory=TestCases)
    troubleshooting: list[TroubleshootingItem] = Field(
        default_factory=list,
        description="FAQ items for HDSD Section 2.4",
    )
    architecture: Architecture = Field(
        default_factory=Architecture,
        description="Architecture data for TKKT template",
    )
    tkcs: TkcsData = Field(
        default_factory=TkcsData,
        description="TKCS-specific data",
    )
    tkct: TkctData = Field(
        default_factory=TkctData,
        description="TKCT (detailed design) data",
    )

    def feature_ids(self) -> set[str]:
        """All feature IDs defined in services."""
        return {f.id for svc in self.services for f in svc.features}

    def tc_feature_ids(self) -> set[str]:
        """Feature IDs referenced in test_cases (via feature_group.feature_id and tc.feature_id)."""
        ids: set[str] = set()
        for sheet in (self.test_cases.ui, self.test_cases.api):
            for item in sheet:
                if (
                    isinstance(item, FeatureGroupRow)
                    and item.feature_id
                    or isinstance(item, TestCaseRow)
                    and item.feature_id
                ):
                    ids.add(item.feature_id)
        return ids

    def coverage_report(self) -> dict:
        """Check which features have test cases and which don't."""
        defined = self.feature_ids()
        covered = self.tc_feature_ids()
        return {
            "total_features": len(defined),
            "covered_features": len(defined & covered),
            "missing_coverage": sorted(defined - covered),
            "orphan_tc_refs": sorted(covered - defined),
        }

    def to_engine_dict(self) -> dict:
        """Serialize to the dict format that xlsx/docx engines expect.

        Key transformations:
          - Priority enum → Vietnamese string (for priority_map in engine)
          - TestCaseRow.steps normalized to split format for backward compat
          - FeatureGroupRow/SectionHeaderRow kept as dicts with _type
        """
        d = self.model_dump(mode="json")

        # Normalize test_cases for engine consumption
        for sheet_key in ("ui", "api"):
            items = d.get("test_cases", {}).get(sheet_key, [])
            for item in items:
                if item.get("_type") in ("feature_group", "section_header"):
                    continue
                # Normalize priority to Vietnamese for engine priority_map
                pri = item.get("priority")
                item["priority"] = _PRIORITY_TO_VN.get(pri, "Trung bình")

                # Ensure split steps/expected format for engine
                steps = item.get("steps", [])
                expected = item.get("expected", [])

                # If steps have embedded expected and no separate expected list
                if steps and not expected:
                    embedded_expected = []
                    for s in steps:
                        if s.get("expected"):
                            embedded_expected.append({"no": s["no"], "expected": s["expected"]})
                    if embedded_expected:
                        item["expected"] = embedded_expected

        return d


_PRIORITY_TO_VN: dict[str, str] = {
    "Critical": "Rất cao",
    "Major": "Cao",
    "Normal": "Trung bình",
    "Minor": "Thấp",
}
