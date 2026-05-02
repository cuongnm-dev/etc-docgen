"""Field mapping reference: Interview/DCB data → content-data.json fields.

Used by Claude Code skill agents (doc-writer) to know which interview answers
map to which content-data.json fields. This module is the single source of truth
for the skill ↔ etc-platform contract.

Each doc type has:
  - content_data_keys: which top-level keys in content-data.json to fill
  - field_map: interview question → content-data field path
  - shared_keys: fields filled from project/overview (common across doc types)
  - export_targets: which etc-platform export targets to use
"""

from __future__ import annotations

# ──────────────────────────────────────────────────────────────────
# Routing: which doc types use etc-platform vs Pandoc
# ──────────────────────────────────────────────────────────────────

ETC_PLATFORM_DOC_TYPES = {"tkcs", "tkct", "tkkt", "hdsd", "xlsx", "nckt"}
"""Doc types rendered by etc-platform (has templates)."""

PANDOC_DOC_TYPES = {"de-an-cds", "hsmt", "hsdt", "du-toan", "bao-cao-ct", "thuyet-minh"}
"""Doc types rendered by Pandoc (no etc-platform templates)."""


def uses_etc_platform(doc_type: str) -> bool:
    """Check if a doc type should use etc-platform for rendering."""
    return doc_type.lower().replace("-", "_") in ETC_PLATFORM_DOC_TYPES


# ──────────────────────────────────────────────────────────────────
# Shared fields (project, meta, overview) — common across all doc types
# ──────────────────────────────────────────────────────────────────

SHARED_FIELDS = {
    "project.display_name": "Tên dự án / hệ thống",
    "project.code": "Mã dự án",
    "project.client": "Tên chủ đầu tư / khách hàng",
    "project.description": "Mô tả ngắn dự án",
    "project.tech_stack": "Công nghệ sử dụng (tóm tắt)",
    "dev_unit": "Tên đơn vị phát triển (default: Công ty CP Hệ thống Công nghệ ETC)",
    "meta.today": "Ngày tạo tài liệu (dd/mm/yyyy)",
    "meta.version": "Phiên bản tài liệu",
    "meta.test_period": "Thời gian kiểm thử (dd/mm/yyyy – dd/mm/yyyy)",
    "overview.purpose": "Mục đích tài liệu",
    "overview.scope": "Phạm vi áp dụng",
    "overview.system_description": "Mô tả hệ thống tổng quan",
    "overview.conventions": "Quy ước tài liệu",
    "overview.terms": "Thuật ngữ viết tắt [{short, full, explanation}]",
    "overview.references": "Tài liệu tham chiếu [{stt, name, ref}]",
}


# ──────────────────────────────────────────────────────────────────
# TKCS field map (NĐ 45/2026 Điều 13)
# ──────────────────────────────────────────────────────────────────

TKCS_FIELD_MAP = {
    "interview_source": {
        "Cơ sở pháp lý (QĐ, NĐ, CT liên quan)": "tkcs.legal_basis",
        "Hiện trạng hệ thống/quy trình": "tkcs.current_state",
        "Sự cần thiết đầu tư": "tkcs.necessity",
        "Phù hợp Khung KTCPĐT": "tkcs.architecture_compliance",
        "Phân tích công nghệ": "tkcs.technology_rationale",
        "Tổng quan thiết kế": "tkcs.detailed_design_summary",
        "Thiết kế chức năng": "tkcs.functional_design",
        "Thiết kế CSDL tổng quan": "tkcs.db_design_summary",
        "Thiết kế tích hợp": "tkcs.integration_design_summary",
        "Phương án ATTT": "tkcs.security_plan",
        "Phương án vận hành": "tkcs.operations_plan",
        "Tiến độ dự kiến": "tkcs.timeline",
        "Tổng mức đầu tư": "tkcs.total_investment",
        "Chi phí vận hành": "tkcs.operating_cost",
        "Mô hình QLDA": "tkcs.project_management",
        "Loại đầu tư": "tkcs.investment_type",
        "Nguồn vốn": "tkcs.funding_source",
        "Thời gian thực hiện": "tkcs.project_duration",
    },
    "content_data_keys": ["project", "meta", "overview", "tkcs"],
    "export_targets": ["tkcs"],
    "field_types": {
        "prose": [
            "tkcs.legal_basis",
            "tkcs.current_state",
            "tkcs.necessity",
            "tkcs.architecture_compliance",
            "tkcs.technology_rationale",
            "tkcs.detailed_design_summary",
            "tkcs.functional_design",
            "tkcs.db_design_summary",
            "tkcs.integration_design_summary",
            "tkcs.security_plan",
            "tkcs.operations_plan",
            "tkcs.timeline",
            "tkcs.total_investment",
            "tkcs.operating_cost",
            "tkcs.project_management",
        ],
        "short_text": [
            "tkcs.investment_type",
            "tkcs.funding_source",
            "tkcs.project_duration",
        ],
        "diagram": ["tkcs.architecture_diagram", "tkcs.data_model_diagram"],
    },
}


# ──────────────────────────────────────────────────────────────────
# TKCT field map
# ──────────────────────────────────────────────────────────────────

TKCT_FIELD_MAP = {
    "interview_source": {
        "Mô tả tổng quan hệ thống": "tkct.system_description",
        "Tham chiếu TKKT": "tkct.architecture_reference",
        "Thiết kế CSDL tổng quan": "tkct.db_description",
        "Thiết kế API tổng quan": "tkct.api_description",
        "Quy tắc giao diện": "tkct.ui_guidelines",
        "Bố cục giao diện": "tkct.ui_layout",
        "Thiết kế tích hợp": "tkct.integration_design",
        "Thiết kế bảo mật": "tkct.security_design",
        "Ma trận truy xuất": "tkct.traceability_description",
    },
    "structured_data": {
        "Danh sách module": "tkct.modules[]  → ModuleDesign",
        "Bảng CSDL": "tkct.db_tables[]  → DbTable → DbColumn",
        "API chi tiết": "tkct.api_details[]  → ApiDetail → ApiParameter",
        "Màn hình": "tkct.screens[]  → ScreenDesign",
    },
    "content_data_keys": ["project", "meta", "overview", "tkct"],
    "export_targets": ["tkct"],
    "field_types": {
        "prose": [
            "tkct.system_description",
            "tkct.architecture_reference",
            "tkct.db_description",
            "tkct.api_description",
            "tkct.ui_guidelines",
            "tkct.ui_layout",
            "tkct.integration_design",
            "tkct.security_design",
            "tkct.traceability_description",
        ],
        "structured": [
            "tkct.modules",
            "tkct.db_tables",
            "tkct.api_details",
            "tkct.screens",
        ],
        "diagram": [
            "tkct.architecture_overview_diagram",
            "tkct.db_erd_diagram",
            "tkct.ui_layout_diagram",
            "tkct.integration_diagram",
            "tkct.modules[].flow_diagram",
        ],
    },
}


# ──────────────────────────────────────────────────────────────────
# TKKT field map
# ──────────────────────────────────────────────────────────────────

TKKT_FIELD_MAP = {
    "interview_source": {
        "Mục đích": "architecture.purpose",
        "Phạm vi": "architecture.scope",
        "Tổng quan hệ thống": "architecture.system_overview",
        "Mô tả phạm vi": "architecture.scope_description",
        "Kiến trúc logic": "architecture.logical_description",
        "Mô tả tương tác": "architecture.interaction_description",
        "Mô tả dữ liệu": "architecture.data_description",
        "Mô tả tích hợp": "architecture.integration_description",
        "Mô tả triển khai": "architecture.deployment_description",
        "Mô tả bảo mật": "architecture.security_description",
        "Mô tả xác thực": "architecture.auth_description",
        "Bảo vệ dữ liệu": "architecture.data_protection",
    },
    "structured_data": {
        "Công nghệ sử dụng": "architecture.tech_stack[] → TechStackItem",
        "Thành phần kiến trúc": "architecture.components[] → ArchComponent",
        "Thực thể dữ liệu": "architecture.data_entities[] → DataEntity",
        "API endpoints": "architecture.apis[] → ApiEndpoint",
        "Tích hợp bên ngoài": "architecture.external_integrations[] → ExternalIntegration",
        "Môi trường triển khai": "architecture.environments[] → DeployEnvironment",
        "Container": "architecture.containers[] → ContainerInfo",
        "NFR": "architecture.nfr[] → NfrItem",
    },
    "content_data_keys": ["project", "meta", "overview", "architecture"],
    "export_targets": ["tkkt"],
    "field_types": {
        "prose": [
            "architecture.purpose",
            "architecture.scope",
            "architecture.system_overview",
            "architecture.scope_description",
            "architecture.logical_description",
            "architecture.interaction_description",
            "architecture.data_description",
            "architecture.integration_description",
            "architecture.deployment_description",
            "architecture.security_description",
            "architecture.auth_description",
            "architecture.data_protection",
        ],
        "structured": [
            "architecture.tech_stack",
            "architecture.components",
            "architecture.data_entities",
            "architecture.apis",
            "architecture.external_integrations",
            "architecture.environments",
            "architecture.containers",
            "architecture.nfr",
        ],
        "diagram": [
            "architecture.architecture_diagram",
            "architecture.logical_diagram",
            "architecture.data_diagram",
            "architecture.deployment_diagram",
            "architecture.integration_diagram",
            "architecture.security_diagram",
        ],
    },
}


# ──────────────────────────────────────────────────────────────────
# HDSD field map
# ──────────────────────────────────────────────────────────────────

HDSD_FIELD_MAP = {
    "interview_source": {
        "URL hệ thống": "(used for capture, not content-data)",
        "Tài khoản test": "(used for auth, not content-data)",
    },
    "structured_data": {
        "Dịch vụ/module": "services[] → Service",
        "Chức năng": "services[].features[] → Feature",
        "Bước thao tác": "services[].features[].steps[] → FeatureStep",
        "Thành phần giao diện": "services[].features[].ui_elements[] → UIElement",
        "Dialog/popup": "services[].features[].dialogs[] → Dialog",
        "Lỗi thường gặp": "services[].features[].error_cases[] → ErrorCase",
        "Xử lý sự cố": "troubleshooting[] → TroubleshootingItem",
    },
    "content_data_keys": ["project", "meta", "overview", "services", "troubleshooting"],
    "export_targets": ["hdsd"],
    "field_types": {
        "structured": [
            "services",
            "troubleshooting",
        ],
    },
}


# ──────────────────────────────────────────────────────────────────
# XLSX field map (Test Cases)
# ──────────────────────────────────────────────────────────────────

XLSX_FIELD_MAP = {
    "structured_data": {
        "UI test cases": "test_cases.ui[] → FeatureGroupRow | SectionHeaderRow | TestCaseRow",
        "API test cases": "test_cases.api[] → FeatureGroupRow | SectionHeaderRow | TestCaseRow",
        "Cấu hình sheet": "test_sheets → TestSheetConfig",
    },
    "content_data_keys": ["project", "meta", "dev_unit", "test_cases", "test_sheets"],
    "export_targets": ["xlsx"],
    "field_types": {
        "structured": [
            "test_cases.ui",
            "test_cases.api",
            "test_sheets",
        ],
    },
}


# ──────────────────────────────────────────────────────────────────
# NCKT field map (NĐ 45/2026 Điều 12)
# ──────────────────────────────────────────────────────────────────

NCKT_FIELD_MAP = {
    "interview_source": {
        "Thông tin chung dự án": "nckt.sections['1.1']",
        "Căn cứ pháp lý": "nckt.sections['1.2']",
        "Yêu cầu ATTT của dự án (7 mục con 1.3.1..1.3.7)": "nckt.sections['1.3.*']",
        "Hiện trạng tổ chức, nghiệp vụ": "nckt.sections['2.1']",
        "Hiện trạng ứng dụng CNTT + nhân lực": "nckt.sections['2.2.*']",
        "Hạ tầng CNTT + đánh giá": "nckt.sections['2.3.*']",
        "Sự cần thiết đầu tư": "nckt.sections['2.4']",
        "Phù hợp KT CPĐT + Quy hoạch CNTT": "nckt.sections['3.*']",
        "Mục tiêu đầu tư (TQ + cụ thể)": "nckt.sections['4.1.*']",
        "Quy mô / Thời gian / Hình thức đầu tư": "nckt.sections['4.2'..'4.4']",
        "Điều kiện tự nhiên + địa điểm": "nckt.sections['5.*']",
        "Tiêu chuẩn áp dụng (4 mục)": "nckt.sections['6.1.*']",
        "Yêu cầu chung kỹ thuật (4 mục)": "nckt.sections['6.2.*']",
        "Tiêu chí lựa chọn giải pháp": "nckt.sections['6.3']",
        "Phương án CN/KT/TB (mạng, FW, lưu trữ, máy chủ, ảo hoá, SIEM, NMS)": "nckt.sections['6.4.*']",
        "Thiết kế phần mềm nội bộ (5 mục)": "nckt.sections['6.5.*']",
        "Phần mềm thương mại": "nckt.sections['6.6']",
        "Cơ chế phục hồi & duy trì liên tục": "nckt.sections['6.7']",
        "Mô hình kiến trúc tổng thể + nghiệp vụ": "nckt.sections['7.1','7.2']",
        "Mô hình logic + vật lý hạ tầng": "nckt.sections['7.3.*','7.4.*']",
        "Định cỡ (sizing 7 mục)": "nckt.sections['8.1.*']",
        "TKCS hạ tầng + phần mềm nội bộ": "nckt.sections['8.2','8.3']",
        "Hỗ trợ vận hành trước nghiệm thu": "nckt.sections['8.4.*']",
        "Đào tạo (4 mục)": "nckt.sections['8.5.*']",
        "Khối lượng lắp đặt": "nckt.sections['8.6.*']",
        "Cấp độ ATTT (NĐ 85/2016, TT 12/2022, TCVN 11930)": "nckt.sections['9.*']",
        "PP quản lý dự án + khai thác vận hành": "nckt.sections['10.*']",
        "Vật tư, PCCC, an ninh, trách nhiệm": "nckt.sections['11.*']",
        "Tác động & BVMT": "nckt.sections['12']",
        "Tiến độ thực hiện": "nckt.sections['13']",
        "Tổng mức đầu tư + nguồn vốn (TT 04/2020)": "nckt.sections['14.*']",
        "Bảo hành + chi phí vận hành": "nckt.sections['15.*']",
        "Tổ chức QLDA + trách nhiệm các bên": "nckt.sections['16.*']",
        "Hiệu quả KT-XH + ANQP": "nckt.sections['17.*']",
        "Phân tích rủi ro + yếu tố thành công": "nckt.sections['18.*']",
        "Kết luận và kiến nghị": "nckt.sections['19']",
        "Phụ lục: mặt bằng TTDL + sơ đồ mạng + sơ đồ liên thông": "nckt.sections['pl.1'..'pl.3']",
    },
    "structured_data": {
        "Ma trận rủi ro §18.1": "nckt.risk_matrix[] → {stt, risk, probability, impact, level, mitigation}",
        "Bảng tổng mức đầu tư §14.2": "nckt.investment_summary[] → {stt, item, unit, qty, unit_price, amount, note}",
    },
    "content_data_keys": ["project", "meta", "overview", "nckt"],
    "export_targets": ["nckt"],
    "field_types": {
        "prose_dict": ["nckt.sections"],
        "structured": ["nckt.risk_matrix", "nckt.investment_summary"],
        "diagram": [
            "nckt.overall_architecture_diagram",
            "nckt.business_architecture_diagram",
            "nckt.logical_infra_diagram",
            "nckt.physical_infra_inner_diagram",
            "nckt.physical_infra_outer_diagram",
            "nckt.datacenter_layout_diagram",
            "nckt.network_topology_diagram",
            "nckt.integration_topology_diagram",
        ],
    },
}


# ──────────────────────────────────────────────────────────────────
# Aggregate lookup
# ──────────────────────────────────────────────────────────────────

FIELD_MAPS = {
    "tkcs": TKCS_FIELD_MAP,
    "tkct": TKCT_FIELD_MAP,
    "tkkt": TKKT_FIELD_MAP,
    "hdsd": HDSD_FIELD_MAP,
    "xlsx": XLSX_FIELD_MAP,
    "nckt": NCKT_FIELD_MAP,
}


def get_field_map(doc_type: str) -> dict | None:
    """Get field mapping for a doc type. Returns None if not an etc-platform type."""
    return FIELD_MAPS.get(doc_type.lower())


def get_writer_prompt_context(doc_type: str) -> str:
    """Generate a concise field reference for doc-writer agent prompts.

    Returns a text block that can be injected into agent prompts, telling
    the writer exactly which content-data.json fields to fill and their types.
    """
    fmap = get_field_map(doc_type)
    if not fmap:
        return f"Doc type '{doc_type}' uses Pandoc pipeline (no etc-platform mapping)."

    lines = [
        f"## etc-platform Field Reference: {doc_type.upper()}",
        f"content-data.json keys to fill: {fmap['content_data_keys']}",
        f"Export targets: {fmap['export_targets']}",
        "",
        "### Shared Fields (project/meta/overview — common across all doc types)",
    ]
    for field_path, question in SHARED_FIELDS.items():
        lines.append(f"  {question} → `{field_path}`")
    lines.append("")

    if "interview_source" in fmap:
        lines.append("### Interview → Field Mapping (prose)")
        for question, field_path in fmap["interview_source"].items():
            lines.append(f"  {question} → `{field_path}`")
        lines.append("")

    if "structured_data" in fmap:
        lines.append("### Structured Data Fields")
        for label, schema_ref in fmap["structured_data"].items():
            lines.append(f"  {label} → `{schema_ref}`")
        lines.append("")

    ft = fmap.get("field_types", {})
    if "prose" in ft:
        lines.append(f"### Prose fields ({len(ft['prose'])}): formal Vietnamese, vô nhân xưng")
    if "structured" in ft:
        lines.append(
            f"### Structured fields ({len(ft['structured'])}): JSON arrays/objects per schema"
        )
    if "diagram" in ft:
        lines.append(
            f"### Diagram fields ({len(ft['diagram'])}): image filenames (resolved at render)"
        )

    return "\n".join(lines)
