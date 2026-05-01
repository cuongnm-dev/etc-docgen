"""Advisory quality checks for content-data.json.

Three phases:
  Phase 1 — Structural integrity (diagram cross-refs, orphan refs).
  Phase 2 — Quantity/prose quality (word counts, banned phrases, min counts).
  Phase 3 — Semantic depth (5 ATTT groups, cấp độ N, 5-layer coverage, NFR measurable).

All checks return list[str] of warnings. Non-blocking — errors stay in Pydantic layer.
"""
from __future__ import annotations

import re
from typing import Any

# ── Constants ──────────────────────────────────────────────────────────────

BANNED_PHRASES = [
    # Original boilerplate phrases
    "đáp ứng đầy đủ",
    "tiên tiến hiện đại",
    "phù hợp với thực tiễn",
    "tối ưu hóa toàn diện",
    "hiệu quả cao",
    "chất lượng cao",
    "đảm bảo đầy đủ",
    "toàn diện và đồng bộ",
    "công nghệ hiện đại",
    "giải pháp tối ưu",
    # Generic filler — true for any project, contains zero specifics
    "ngày càng tăng",
    "nhu cầu thực tế",
    "yêu cầu nghiệp vụ",
    "đáp ứng nhu cầu",
    "phát triển bền vững",
    "nâng cao hiệu quả",
    "tăng cường năng lực",
    "kết hợp hài hòa",
    "linh hoạt và hiệu quả",
    "ổn định và bảo mật",
    "nhanh chóng và chính xác",
    "dễ dàng sử dụng",
    "thân thiện người dùng",
    "đồng bộ hóa dữ liệu",
    "tích hợp liền mạch",
    "giải pháp toàn diện",
    "hệ thống đồng bộ",
    "vận hành ổn định",
    "đáng tin cậy",
    "chuyển đổi số toàn diện",
]

# TCVN 11930:2017 — 5 nhóm biện pháp ATTT (keywords đại diện mỗi nhóm)
FIVE_ATTT_GROUPS = {
    "quản lý": ["quản lý", "chính sách", "rủi ro"],
    "kỹ thuật": ["kỹ thuật", "firewall", "mã hóa", "mfa", "ids", "ips", "waf"],
    "vật lý": ["vật lý", "phòng máy", "ups", "pccc", "camera"],
    "con người": ["con người", "đào tạo", "nhân viên", "rbac", "phân quyền"],
    "vận hành": ["vận hành", "backup", "dr", "incident", "log", "sla"],
}

# TT 12/2022 + QĐ 292/2025 — 5 tầng kiến trúc CPĐT 4.0
FIVE_LAYERS = {
    "nghiệp vụ": ["nghiệp vụ", "quy trình", "actor", "usecase", "kpi"],
    "ứng dụng": ["ứng dụng", "module", "service", "api"],
    "dữ liệu": ["dữ liệu", "entity", "csdl", "database", "storage"],
    "công nghệ": ["công nghệ", "hạ tầng", "stack", "cloud", "on-prem", "k8s"],
    "an toàn": ["an toàn", "bảo mật", "tcvn 11930", "attt"],
}

# Regex: văn bản pháp lý (NĐ 30/2020 format)
LEGAL_REF_PATTERN = re.compile(
    r"(Nghị định|Thông tư|Luật|Quyết định|Chỉ thị)\s+số\s+\d+",
    re.IGNORECASE,
)

# Regex: count digit groups (metric presence proxy)
NUMBER_PATTERN = re.compile(r"\d[\d.,]*")

# ── Minimums dict (surfaced by section_schema) ─────────────────────────────

MINIMUMS: dict[str, dict[str, Any]] = {
    "tkkt": {
        "fields_min_words": {
            "purpose": 200,
            "scope": 200,
            "system_overview": 400,
            "scope_description": 300,
            "business_overview": 500,
            "design_principles": 400,
            "logical_description": 400,
            "interaction_description": 300,
            "data_description": 300,
            "integration_description": 400,
            "deployment_description": 400,
            "security_description": 500,
            "auth_description": 300,
            "data_protection": 300,
        },
        "arrays_min_count": {
            "tech_stack": 5,
            "components": 3,
            "data_entities": 3,
            "apis": 5,
            "containers": 1,
            "nfr": 6,
        },
        "semantic": {
            "business_overview_must_cover_5_layers": list(FIVE_LAYERS.keys()),
            "nfr_measurable": "each nfr.requirement must contain a number + unit",
        },
        "placeholders_max": 3,
        "diagrams_required": [
            "architecture_diagram", "logical_diagram", "data_diagram",
            "integration_diagram", "deployment_diagram", "security_diagram",
        ],
    },
    "tkcs": {
        "fields_min_words": {
            "legal_basis": 400,
            "current_state": 800,
            "necessity": 500,
            "objectives": 400,
            "architecture_compliance": 300,
            "technology_rationale": 600,
            "standards": 300,
            "detailed_design_summary": 300,
            "functional_design": 1000,
            "db_design_summary": 400,
            "integration_design_summary": 400,
            "software_design": 300,
            "infrastructure_design": 300,
            "security_plan": 500,
            "security_design": 300,
            "security_tech": 300,
            "operations_plan": 400,
            # ── Section "phụ" — previously ungated; writers got away with 13–28 word filler.
            #    Each is gated at 80–150 words depending on whether it carries
            #    project-specific facts (≥150) or business policy summary (≥80).
            "scope_tkcs": 100,
            "assumptions": 100,
            "constraints": 100,
            "risks": 150,
            "stakeholders": 150,
            "high_level_solution": 150,
            "deployment_model": 100,
            "security_model": 100,
            "data_model_summary": 150,
            "schedule": 100,
            "budget_detail": 150,
            "opex": 100,
            "warranty": 80,
            "pm_form": 80,
            "pm_method": 80,
        },
        "current_state_min_numbers": 10,
        "legal_basis_min_refs": 7,
        "placeholders_max": 15,
        "semantic": {
            "security_plan_must_contain": ["cấp độ"],
            "security_design_must_cover_5_groups": list(FIVE_ATTT_GROUPS.keys()),
        },
        "diagrams_required": [
            "tkcs_architecture_diagram", "tkcs_data_model_diagram",
        ],
    },
    "tkct": {
        "arrays_min_count": {
            "modules": 3,
            "db_tables": 3,
            "api_details": 5,
            "screens": 3,
        },
        # Per-module description gate. Boilerplate ≤ 50 words ("Module M0X thuộc
        # phạm vi… Chưa xác định luồng…") slips past the existing 100-word check
        # only because writers pad with template text. Diversity check below catches that.
        "module_min_description_words": 100,
        "module_required_diagram": "flow_diagram",
        "diagrams_required": [
            "tkct_architecture_overview_diagram", "tkct_db_erd_diagram",
            "tkct_ui_layout_diagram", "tkct_integration_diagram",
        ],
        # Cosine-like similarity ceiling between any two module description+flow texts.
        # 0.80 catches "M01 thuộc..." / "M02 thuộc..." copy-paste while still allowing
        # legitimate cross-module phrases ("tenant", "JWT", "audit log") to repeat.
        "module_text_similarity_max": 0.80,
        # db_tables column requirements — id+timestamps alone is not a real schema.
        "db_table_min_columns": 5,
        "db_table_min_business_columns": 2,
        # api_details extra gates beyond word counts.
        "api_required_fields": ["request_body", "response_body"],
    },
    # Test case structural requirements — applied to test_cases.{ui,api}[].
    # Writers in the wild produce TCs with `name: "F-001 — ..."` but no `id` field,
    # which breaks Stage 6 xlsx rendering (cells lookup `id`, get blank).
    "test_cases": {
        "tc_required_fields": ["id", "name", "feature_id"],
        "tc_id_pattern": r"^TC-[A-Z0-9]+-\d{3,}$",
    },
    # NCKT (Báo cáo Nghiên cứu khả thi) — NĐ 45/2026/NĐ-CP Điều 12.
    # Outline: nghien-cuu-kha-thi/nd45-2026.md (19 chương + Phụ lục).
    # Storage: nckt.sections[<key>] dict — keyed by section path "1.1", "2.2.1", ..., "pl.3".
    "nckt": {
        # Required section keys (canonical, từ outline). Missing = empty string.
        "required_sections": [
            # 1 Tổng quan
            "1.1", "1.2",
            "1.3.1", "1.3.2", "1.3.3", "1.3.4", "1.3.5", "1.3.6", "1.3.7",
            # 2 Sự cần thiết
            "2.1", "2.2.1", "2.2.2",
            "2.3.1", "2.3.2", "2.3.3", "2.3.4", "2.4",
            # 3 Quy hoạch
            "3.1", "3.2",
            # 4 Mục tiêu
            "4.1.1", "4.1.2", "4.2", "4.3", "4.4",
            # 5 Điều kiện + địa điểm
            "5.1", "5.2",
            # 6 Phương án
            "6.1.1", "6.1.2", "6.1.3", "6.1.4",
            "6.2.1", "6.2.2", "6.2.3", "6.2.4",
            "6.3",
            "6.4.1", "6.4.2", "6.4.3", "6.4.4", "6.4.5", "6.4.6", "6.4.7",
            "6.5.1", "6.5.2", "6.5.3", "6.5.4", "6.5.5",
            "6.6", "6.7",
            # 7 Mô hình
            "7.1", "7.2", "7.3.1", "7.4.1", "7.4.2", "7.4.3",
            # 8 TKCS
            "8.1.1", "8.1.2", "8.1.3", "8.1.4", "8.1.5", "8.1.6", "8.1.7",
            "8.2", "8.3",
            "8.4.1", "8.4.2",
            "8.5.1", "8.5.2", "8.5.3", "8.5.4",
            "8.6.1", "8.6.2",
            # 9 ATTT
            "9.1", "9.2",
            # 10 Quản lý-khai thác
            "10.1.1", "10.1.2", "10.1.3",
            "10.2.1", "10.2.2", "10.2.3", "10.2.4", "10.2.5",
            # 11 Vật tư + PCCC
            "11.1",
            "11.2.1", "11.2.2", "11.2.3", "11.2.4", "11.2.5",
            "11.3",
            # 12-13 standalone
            "12", "13",
            # 14 Tổng mức đầu tư
            "14.1", "14.2", "14.3",
            # 15 Bảo hành + chi phí
            "15.1.1", "15.1.2", "15.1.3", "15.1.4",
            "15.2.1", "15.2.2", "15.2.3",
            # 16 Tổ chức QLDA
            "16.1",
            "16.2.1", "16.2.2",
            "16.3.1", "16.3.2", "16.3.3", "16.3.4", "16.3.5", "16.3.6",
            # 17 Hiệu quả
            "17.1", "17.2",
            # 18 Rủi ro + thành công
            "18.1", "18.2",
            # 19 Kết luận
            "19",
            # PL Phụ lục
            "pl.1", "pl.2", "pl.3",
        ],
        # Per-section minimum word counts (default = 80; selected sections override).
        # High-impact sections require more depth; hub sections (12, 13, 19) less.
        "sections_min_words_default": 80,
        "sections_min_words_overrides": {
            # Tổng quan: thông tin chung + căn cứ pháp lý cần đầy đủ
            "1.1": 200,
            "1.2": 400,         # ≥ 7 văn bản pháp lý
            # Sự cần thiết: hiện trạng cần data-rich
            "2.1": 250,
            "2.3.1": 300,       # hạ tầng — phải có thông số
            "2.3.3": 250,
            "2.3.4": 300,
            "2.4": 400,         # justification chính
            # Quy hoạch: phù hợp KT CPĐT
            "3.1": 250,
            "3.2": 250,
            # Mục tiêu
            "4.1.1": 150,
            "4.1.2": 250,       # KPI cụ thể
            # Phương án CN/KT/TB — mỗi section so sánh + lựa chọn
            "6.4.1": 150,
            "6.4.2": 200,
            "6.4.3": 200,
            "6.4.4": 200,
            "6.4.5": 200,
            "6.4.6": 150,
            "6.4.7": 150,
            "6.5.1": 200,
            "6.5.2": 200,
            "6.5.3": 150,
            "6.5.4": 250,
            "6.5.5": 200,
            "6.7": 200,
            # Mô hình kiến trúc
            "7.1": 250,
            "7.2": 200,
            "7.3.1": 300,
            "7.4.3": 300,
            # TKCS — định cỡ phải có numbers
            "8.1.1": 150,
            "8.1.3": 300,
            "8.1.4": 250,
            "8.1.5": 200,
            "8.1.6": 250,
            "8.2": 250,
            "8.3": 250,
            "8.5.2": 200,
            # ATTT
            "9.1": 400,         # phải nêu cấp độ N + 5 nhóm biện pháp
            "9.2": 300,
            # Quản lý
            "10.2.4": 200,
            "10.2.5": 150,      # Luật ANM
            # Tổng mức đầu tư
            "14.1": 200,
            "14.2": 250,
            "14.3": 150,
            # Tổ chức QLDA
            "16.3.2": 150,
            "16.3.5": 150,
            # Hiệu quả
            "17.1": 250,
            "17.2": 200,
            # Rủi ro
            "18.1": 300,        # ≥ 5 rủi ro
            "18.2": 200,
            # Kết luận
            "19": 200,
        },
        # Section 1.2 phải viện dẫn ≥ 7 văn bản pháp lý (NĐ/TT/Luật/QĐ).
        "section_1_2_min_legal_refs": 7,
        # Section 2.4 phải có numbers (specific facts, không chung chung).
        "section_2_4_min_numbers": 5,
        # Section 9.1 phải nêu "cấp độ" theo NĐ 85/2016.
        "section_9_1_must_contain": ["cấp độ"],
        # Section 14.2 phải có giá trị tiền tệ (tỷ/triệu/đồng).
        "section_14_2_must_contain_currency": True,
        # risk_matrix structured ≥ 5 dòng khi §18.1 fired.
        "risk_matrix_min_rows": 5,
        # Số lượng [CẦN BỔ SUNG] tối đa toàn block (placeholders_max).
        "placeholders_max": 25,
        # Required diagram filename refs (filename) + matching diagrams.* sources.
        "diagrams_required": [
            "nckt_overall_architecture_diagram",
            "nckt_business_architecture_diagram",
            "nckt_logical_infra_diagram",
            "nckt_physical_infra_inner_diagram",
            "nckt_physical_infra_outer_diagram",
            "nckt_datacenter_layout_diagram",
            "nckt_network_topology_diagram",
            "nckt_integration_topology_diagram",
        ],
        # Field mapping diagram → diagram_field key on NcktData (no nckt_ prefix in field names)
        "diagram_field_map": {
            "nckt_overall_architecture_diagram": "overall_architecture_diagram",
            "nckt_business_architecture_diagram": "business_architecture_diagram",
            "nckt_logical_infra_diagram": "logical_infra_diagram",
            "nckt_physical_infra_inner_diagram": "physical_infra_inner_diagram",
            "nckt_physical_infra_outer_diagram": "physical_infra_outer_diagram",
            "nckt_datacenter_layout_diagram": "datacenter_layout_diagram",
            "nckt_network_topology_diagram": "network_topology_diagram",
            "nckt_integration_topology_diagram": "integration_topology_diagram",
        },
    },
}

# ── Helpers ────────────────────────────────────────────────────────────────

def word_count(s: Any) -> int:
    if not isinstance(s, str):
        return 0
    return len(s.split())


def number_count(s: Any) -> int:
    if not isinstance(s, str):
        return 0
    return len(NUMBER_PATTERN.findall(s))


def count_legal_refs(s: Any) -> int:
    if not isinstance(s, str):
        return 0
    return len(LEGAL_REF_PATTERN.findall(s))


def _iter_strings(obj: Any, path: str = "") -> list[tuple[str, str]]:
    """Recursively yield (jsonpath, string_value) for all string leaves."""
    out: list[tuple[str, str]] = []
    if isinstance(obj, str):
        out.append((path, obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(_iter_strings(v, f"{path}.{k}" if path else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(_iter_strings(v, f"{path}[{i}]"))
    return out


# ── Phase 1 — Structural integrity ─────────────────────────────────────────

DIAGRAM_FIELDS = {
    "architecture": [
        "architecture_diagram", "logical_diagram", "data_diagram",
        "deployment_diagram", "integration_diagram", "security_diagram",
    ],
    "tkcs": ["architecture_diagram", "data_model_diagram"],
    "tkct": [
        "architecture_overview_diagram", "db_erd_diagram",
        "ui_layout_diagram", "integration_diagram",
    ],
    "nckt": [
        "overall_architecture_diagram",
        "business_architecture_diagram",
        "logical_infra_diagram",
        "physical_infra_inner_diagram",
        "physical_infra_outer_diagram",
        "datacenter_layout_diagram",
        "network_topology_diagram",
        "integration_topology_diagram",
    ],
}


def check_diagram_quality(data: dict) -> list[str]:
    """Static-analyse PlantUML / Mermaid sources for govt-grade quality bar.

    Triggers: any non-empty entry in `data.diagrams` is checked. Mermaid sources
    pass through with a generic recommendation; PlantUML sources are scanned for
    the mandatory skinparam preset + title + grouping + anti-patterns documented
    in ``skills/generate-docs/notepads/diagram-quality-patterns.md``.

    Failure modes detected:
      - PlantUML missing skinparam preset (defaultFontName / shadowing / linetype)
      - PlantUML missing title
      - PlantUML missing direction hint (top to bottom / left to right)
      - PlantUML > 25 nodes (too dense — split required)
      - PlantUML uses ``rectangle "..."`` everywhere instead of semantic shapes
      - PlantUML uses markdown code fences (engine rejects raw fences)
      - Source lacks @enduml / @endmindmap / @endgantt closing
      - Mermaid source emitted when prefix is plantuml-style (mismatched)
    """
    warnings: list[str] = []
    diagrams = data.get("diagrams", {}) or {}
    if not diagrams:
        return []

    plantuml_starts = (
        "@startuml", "@startmindmap", "@startgantt", "@startwbs",
        "@startsalt", "@startjson", "@startyaml",
    )

    for key, val in diagrams.items():
        if val is None:
            continue
        # Extract raw source string
        if isinstance(val, dict):
            if "template" in val:  # SVG hero — skip text checks
                continue
            src = str(val.get("source") or "")
            forced_type = (val.get("type") or "").lower()
        elif isinstance(val, str):
            src = val
            forced_type = ""
        else:
            continue
        s = src.strip()
        if not s:
            continue

        low = s.lower()
        is_plantuml = forced_type == "plantuml" or any(
            low.startswith(p) for p in plantuml_starts
        )
        if not is_plantuml:
            # Mermaid path — only detect fence error
            if "```" in s:
                warnings.append(
                    f"diagrams.{key}: source contains markdown fence (```). "
                    f"Engine wants raw source — strip ``` markers."
                )
            continue

        # ── PlantUML quality bar ──
        prefix = f"diagrams.{key} (PlantUML)"

        # Closing tag
        end_markers = (
            "@enduml", "@endmindmap", "@endgantt", "@endwbs",
            "@endsalt", "@endjson", "@endyaml",
        )
        if not any(end in low for end in end_markers):
            warnings.append(f"{prefix}: missing closing @end... directive.")

        # Gantt-specific: enforce printscale to avoid 8000+px renders
        if "@startgantt" in low and "printscale" not in low:
            warnings.append(
                f"{prefix}: @startgantt missing `printscale weekly` (or monthly/"
                f"quarterly). Without it PlantUML renders 1 cell per day → "
                f"output may exceed 8000px wide and become unreadable. "
                f"See diagram-quality-patterns.md §10f."
            )

        # Skinparam preset
        if "defaultfontname" not in low:
            warnings.append(
                f"{prefix}: missing `skinparam defaultFontName \"Times New Roman\"` — "
                f"required for VN diacritics + NĐ 30/2020 compliance. "
                f"See diagram-quality-patterns.md §2."
            )
        if "shadowing" not in low:
            warnings.append(
                f"{prefix}: missing `skinparam shadowing false` — govt-grade "
                f"diagrams must be flat (no shadows)."
            )
        # linetype only enforced for non-sequence diagrams
        if "@startuml" in low and "sequencediagram" not in low and "participant " not in low:
            if "linetype ortho" not in low and "linetype polyline" not in low:
                warnings.append(
                    f"{prefix}: missing `skinparam linetype ortho` — required "
                    f"for clean structural diagrams (use polyline only for sequence)."
                )

        # Title
        # Match `title ...` not part of skinparam title block
        title_re = re.compile(r"(?m)^\s*title\s+\S+")
        if not title_re.search(s):
            warnings.append(
                f"{prefix}: missing `title <b>Hình X.Y</b>: ...` — diagram needs caption."
            )

        # Detect sequence-style diagram (participant / actor "X" -> Y / autonumber)
        is_sequence = "@startuml" in low and (
            "sequencediagram" in low
            or re.search(r"(?im)^\s*(participant|actor|boundary|control|database|queue|collections)\s+\S+\s*$", s) is not None
            or "autonumber" in low
            or re.search(r"->\s*\w+\s*:", s) is not None  # `A -> B :` is sequence syntax
        )

        # Direction hint (only meaningful for @startuml structural diagrams)
        if "@startuml" in low and not is_sequence:
            if "top to bottom direction" not in low and "left to right direction" not in low:
                warnings.append(
                    f"{prefix}: missing direction hint (`top to bottom direction` "
                    f"or `left to right direction`). Auto-layout may produce poor result."
                )

        # Grouping — at least one package/frame/node container
        # Sequence diagrams are exempt — participants serve as structure.
        if "@startuml" in low and not is_sequence:
            has_grouping = any(
                kw in low for kw in (
                    "package ", "frame ", "node ", "rectangle ", "cloud ",
                    "boundary ", "control ",
                )
            )
            if not has_grouping:
                warnings.append(
                    f"{prefix}: no grouping container (package/frame/node). "
                    f"Govt-grade diagrams require visual grouping."
                )

        # Node count proxy — count entity/component/database/node/rectangle declarations
        node_decls = len(re.findall(
            r"(?im)^\s*(component|entity|database|node|rectangle|cloud|actor|usecase|participant|boundary|control)\s+",
            s,
        ))
        node_decls += len(re.findall(r"\[[^\]\n]+\]\s+as\s+\w+", s))  # `[Name] as id`
        if node_decls > 25:
            warnings.append(
                f"{prefix}: ~{node_decls} nodes detected (>25 limit). "
                f"Split into 2-3 sub-diagrams for readability."
            )

        # Anti-pattern: rectangle-only (semantic-blind)
        rect_count = len(re.findall(r"(?im)^\s*rectangle\s+", s))
        non_rect = len(re.findall(
            r"(?im)^\s*(component|entity|database|node|cloud|actor|usecase|participant|boundary|control)\s+",
            s,
        ))
        if rect_count >= 5 and non_rect == 0:
            warnings.append(
                f"{prefix}: uses {rect_count} `rectangle` declarations and zero "
                f"semantic shapes (component/database/node/cloud). "
                f"Use proper shapes per diagram-quality-patterns.md §1 rule 5."
            )

        # Advisory: diagram tổng thể "khung kiến trúc" / "tổng thể" / "ngữ cảnh" → recommend SVG hero
        title_match = re.search(r"(?im)^\s*title\s+(.{0,200})", s)
        title_text = (title_match.group(1) if title_match else "").lower()
        overview_keywords = (
            "khung kiến trúc", "khung kt", "kiến trúc tổng thể",
            "tổng quát", "tổng thể", "ngữ cảnh", "context", "khung cpđt",
        )
        if any(kw in title_text for kw in overview_keywords):
            warnings.append(
                f"{prefix}: title nhận diện diagram tổng thể ('{title_text[:60]}'). "
                f"PlantUML không vẽ được layered architecture đều full-width + cylinder bus. "
                f"Khuyến nghị: dùng SVG hero template `kien-truc-cpdt` / `khung-kt-quoc-gia` "
                f"thay PlantUML. Xem diagram-quality-patterns.md §13b Pattern N."
            )

        # Markdown fence smell
        if "```plantuml" in low or "```uml" in low:
            warnings.append(
                f"{prefix}: source contains ```plantuml fence. Engine wants raw "
                f"source starting with @startuml — strip ``` markers."
            )

    return warnings


def check_diagram_cross_refs(data: dict) -> list[str]:
    """Verify architecture/tkcs/tkct.*_diagram filename refs match diagrams.{key}.

    Catches the most dangerous class of errors: orphan filename (will crash
    InlineImage) and orphan diagram source (wasted render).
    """
    warnings: list[str] = []
    diagrams = data.get("diagrams", {}) or {}
    referenced: set[str] = set()

    for block_name, fields in DIAGRAM_FIELDS.items():
        block = data.get(block_name, {}) or {}
        if not isinstance(block, dict):
            continue
        for field in fields:
            val = block.get(field, "")
            if not val or not isinstance(val, str):
                continue
            # Check: is this a Mermaid source accidentally left in filename field?
            if val.lstrip().startswith(("flowchart", "graph", "sequenceDiagram",
                                         "erDiagram", "classDiagram", "```")):
                warnings.append(
                    f"{block_name}.{field}: contains Mermaid source instead of filename. "
                    f"Move source to diagrams.{{key}}, set this field to '{{key}}.png'."
                )
                continue
            # Check: filename must end in .png/.svg/.jpg
            if not val.lower().endswith((".png", ".svg", ".jpg", ".jpeg")):
                warnings.append(
                    f"{block_name}.{field}='{val}': does not look like a filename "
                    f"(must end in .png/.svg/.jpg)."
                )
                continue
            # Check: key must exist in diagrams block
            stem = val.rsplit(".", 1)[0]
            if stem not in diagrams:
                # Try canonical forms (block prefix)
                candidates = [stem]
                if block_name in ("tkcs", "tkct", "nckt"):
                    candidates.append(f"{block_name}_{stem}")
                if not any(c in diagrams for c in candidates):
                    warnings.append(
                        f"{block_name}.{field}='{val}': orphan filename reference — "
                        f"no diagrams.{stem} (or diagrams.{block_name}_{stem}) source exists. "
                        f"Will crash InlineImage at render."
                    )
                    continue
            referenced.add(stem)

    # Module-level flow_diagrams
    modules = (data.get("tkct", {}) or {}).get("modules", []) or []
    for idx, mod in enumerate(modules):
        if not isinstance(mod, dict):
            continue
        val = mod.get("flow_diagram", "")
        if not val:
            warnings.append(
                f"tkct.modules[{idx}] ({mod.get('name', '?')}): missing flow_diagram filename."
            )
            continue
        if isinstance(val, str) and val.lstrip().startswith(("flowchart", "graph", "sequence")):
            warnings.append(
                f"tkct.modules[{idx}].flow_diagram: contains Mermaid source instead of filename."
            )

    # Orphan diagrams (source exists but nothing references it)
    for key in diagrams.keys():
        # Skip module flow diagrams (naming convention varies)
        if key.endswith("_flow_diagram") or "flow" in key:
            continue
        if key not in referenced:
            # Try checking against canonical names with stripped prefix
            stripped = key.replace("tkcs_", "").replace("tkct_", "").replace("nckt_", "")
            if stripped not in referenced:
                warnings.append(
                    f"diagrams.{key}: orphan diagram source — rendered to PNG but no "
                    f"*_diagram field references it. Add '{key}.png' to architecture/tkcs/tkct "
                    f"or remove from diagrams."
                )

    return warnings


# ── Phase 2 — Quantity/prose quality ───────────────────────────────────────

def check_banned_phrases(data: dict) -> list[str]:
    """Scan all prose fields for banned vague phrases."""
    warnings: list[str] = []
    for path, s in _iter_strings(data):
        low = s.lower()
        for phrase in BANNED_PHRASES:
            if phrase in low:
                warnings.append(
                    f"{path}: banned phrase '{phrase}' — văn phong hành chính "
                    f"phải cụ thể, có số liệu, không khẩu hiệu."
                )
                break  # one warning per field
    return warnings


def check_word_counts(block: dict, mins: dict[str, int], block_name: str) -> list[str]:
    """Per-field minimum word count check."""
    warnings: list[str] = []
    for field, min_w in mins.items():
        actual = word_count(block.get(field, ""))
        if actual < min_w:
            warnings.append(
                f"{block_name}.{field}: {actual} words < {min_w} required."
            )
    return warnings


def check_array_counts(block: dict, mins: dict[str, int], block_name: str) -> list[str]:
    warnings: list[str] = []
    for field, min_n in mins.items():
        arr = block.get(field, []) or []
        if not isinstance(arr, list):
            continue
        if len(arr) < min_n:
            warnings.append(
                f"{block_name}.{field}: {len(arr)} items < {min_n} required."
            )
    return warnings


def count_placeholders(block: Any) -> int:
    """Count [CẦN BỔ SUNG: ...] occurrences recursively."""
    n = 0
    for _, s in _iter_strings(block if isinstance(block, (dict, list)) else {}):
        n += s.count("[CẦN BỔ SUNG")
    return n


# ── Phase 3 — Semantic depth ───────────────────────────────────────────────

def check_5_attt_groups(security_design: str) -> list[str]:
    """Verify security_design covers all 5 TCVN 11930 groups."""
    if not isinstance(security_design, str) or not security_design.strip():
        return ["tkcs.security_design: empty — cannot verify 5 nhóm ATTT coverage."]
    low = security_design.lower()
    missing = []
    for group, kws in FIVE_ATTT_GROUPS.items():
        if not any(kw in low for kw in kws):
            missing.append(group)
    if missing:
        return [
            f"tkcs.security_design: thiếu {len(missing)}/5 nhóm ATTT TCVN 11930 "
            f"({', '.join(missing)}). Mỗi nhóm ≥ 100 words."
        ]
    return []


def check_5_layers(business_overview: str) -> list[str]:
    """Verify business_overview covers 5 layers per QĐ 292/2025."""
    if not isinstance(business_overview, str) or not business_overview.strip():
        return []  # word-count check already fires
    low = business_overview.lower()
    missing = []
    for layer, kws in FIVE_LAYERS.items():
        if not any(kw in low for kw in kws):
            missing.append(layer)
    if len(missing) >= 2:  # tolerate 1 missing keyword
        return [
            f"architecture.business_overview: chưa phủ đủ 5 tầng CPĐT 4.0 "
            f"(thiếu: {', '.join(missing)}). Theo QĐ 292/2025 + TT 12/2022."
        ]
    return []


def check_security_level(security_plan: str) -> list[str]:
    """Verify security_plan specifies cấp độ N per NĐ 85/2016 Đ7."""
    if not isinstance(security_plan, str):
        return []
    low = security_plan.lower()
    if "cấp độ" not in low:
        return [
            "tkcs.security_plan: thiếu xác định 'cấp độ N' theo NĐ 85/2016 Điều 7 "
            "(5 tiêu chí). Phải ghi rõ 'Hệ thống được xác định cấp độ X'."
        ]
    return []


def check_nfr_measurable(nfr_list: list) -> list[str]:
    """Each NFR.requirement should contain a number + unit."""
    warnings: list[str] = []
    if not isinstance(nfr_list, list):
        return warnings
    for i, item in enumerate(nfr_list):
        if not isinstance(item, dict):
            continue
        req = item.get("requirement", "")
        if not isinstance(req, str) or not NUMBER_PATTERN.search(req):
            warnings.append(
                f"architecture.nfr[{i}] ({item.get('criterion', '?')}): "
                f"requirement không có số đo được — NFR phải measurable."
            )
    return warnings


# ── Aggregators ────────────────────────────────────────────────────────────

def check_specificity_density(text: str, field_path: str, min_numbers_per_500: int = 5) -> list[str]:
    """Warn when a prose field has fewer than min_numbers_per_500 numeric values per 500 words.

    Proxy for specificity: fields with very few numbers tend to be generic/boilerplate.
    Only fires on fields ≥ 200 words (shorter fields may legitimately have fewer numbers).
    """
    if not isinstance(text, str):
        return []
    wc = word_count(text)
    if wc < 200:
        return []
    nc = number_count(text)
    expected = (wc / 500) * min_numbers_per_500
    if nc < expected * 0.5:  # only warn on significant deficit (< 50% of target)
        return [
            f"{field_path}: {nc} numeric values for {wc} words — prose may be too generic. "
            f"Target ≥ {min_numbers_per_500} numbers per 500 words (specific metrics, versions, counts)."
        ]
    return []


def run_tkkt_checks(data: dict) -> list[str]:
    arch = data.get("architecture", {}) or {}
    if not arch:
        return []
    mins = MINIMUMS["tkkt"]
    w: list[str] = []
    w += check_word_counts(arch, mins["fields_min_words"], "architecture")
    w += check_array_counts(arch, mins["arrays_min_count"], "architecture")
    w += check_5_layers(arch.get("business_overview", ""))
    w += check_nfr_measurable(arch.get("nfr", []))
    ph = count_placeholders(arch)
    if ph > mins["placeholders_max"]:
        w.append(f"architecture: {ph} placeholders > {mins['placeholders_max']} allowed.")
    # Specificity density on high-impact fields
    for field in ("system_overview", "security_description", "deployment_description", "logical_description"):
        w += check_specificity_density(arch.get(field, ""), f"architecture.{field}")
    return w


def run_tkcs_checks(data: dict) -> list[str]:
    tkcs = data.get("tkcs", {}) or {}
    if not tkcs:
        return []
    mins = MINIMUMS["tkcs"]
    w: list[str] = []
    w += check_word_counts(tkcs, mins["fields_min_words"], "tkcs")
    # Section 3 numbers check
    cs_numbers = number_count(tkcs.get("current_state", ""))
    if cs_numbers < mins["current_state_min_numbers"]:
        w.append(
            f"tkcs.current_state: {cs_numbers} numbers < "
            f"{mins['current_state_min_numbers']} required (metrics-heavy section)."
        )
    # Legal refs count
    lb_refs = count_legal_refs(tkcs.get("legal_basis", ""))
    if lb_refs < mins["legal_basis_min_refs"]:
        w.append(
            f"tkcs.legal_basis: {lb_refs} legal refs < "
            f"{mins['legal_basis_min_refs']} required (NĐ/TT/Luật/QĐ số ...)."
        )
    # Semantic
    w += check_security_level(tkcs.get("security_plan", ""))
    w += check_5_attt_groups(tkcs.get("security_design", ""))
    # Placeholders
    ph = count_placeholders(tkcs)
    if ph > mins["placeholders_max"]:
        w.append(f"tkcs: {ph} placeholders > {mins['placeholders_max']} allowed.")
    # Specificity density — current_state and technology_rationale must be metrics-heavy
    w += check_specificity_density(tkcs.get("current_state", ""), "tkcs.current_state", min_numbers_per_500=8)
    w += check_specificity_density(tkcs.get("technology_rationale", ""), "tkcs.technology_rationale", min_numbers_per_500=5)
    w += check_specificity_density(tkcs.get("functional_design", ""), "tkcs.functional_design", min_numbers_per_500=4)
    return w


def run_tkct_checks(data: dict) -> list[str]:
    tkct = data.get("tkct", {}) or {}
    if not tkct:
        return []
    mins = MINIMUMS["tkct"]
    w: list[str] = []
    w += check_array_counts(tkct, mins["arrays_min_count"], "tkct")

    # Per-module word count checks (previously unchecked)
    modules = tkct.get("modules", []) or []
    for i, mod in enumerate(modules):
        if not isinstance(mod, dict):
            continue
        name = mod.get("name", f"[{i}]")
        prefix = f"tkct.modules[{i}] ({name})"

        min_desc = mins.get("module_min_description_words", 100)
        desc_words = word_count(mod.get("description", ""))
        if desc_words < min_desc:
            w.append(f"{prefix}.description: {desc_words} words < {min_desc} required.")

        flow_words = word_count(mod.get("flow_description", ""))
        if flow_words < 200:
            w.append(f"{prefix}.flow_description: {flow_words} words < 200 required.")

        # business_rules is a multi-line string — check total AND rule count
        rules_str = mod.get("business_rules", "") or ""
        rules_words = word_count(rules_str)
        if rules_words < 450:  # 3 rules × 150 words minimum
            w.append(
                f"{prefix}.business_rules: {rules_words} words < 450 required "
                f"(≥ 3 rules × 150 words each)."
            )
        # Count rules by BR- prefix (each rule line starts with BR-NNN:)
        import re as _re
        br_count = len(_re.findall(r"(?m)^BR-\d+", rules_str))
        if br_count < 3:
            w.append(
                f"{prefix}.business_rules: {br_count} BR- rules found < 3 required. "
                f"Each rule must start with 'BR-NNN:' on its own line."
            )

    # Per-API detail checks
    api_details = tkct.get("api_details", []) or []
    for i, api in enumerate(api_details):
        if not isinstance(api, dict):
            continue
        path = api.get("path", f"[{i}]")
        desc_words = word_count(api.get("description", ""))
        if desc_words < 200:
            w.append(
                f"tkct.api_details[{i}] ({api.get('method','')} {path}).description: "
                f"{desc_words} words < 200 required."
            )
        if not api.get("request_body"):
            w.append(
                f"tkct.api_details[{i}] ({api.get('method','')} {path}): "
                f"missing request_body — document payload schema."
            )
        if not api.get("response_body"):
            w.append(
                f"tkct.api_details[{i}] ({api.get('method','')} {path}): "
                f"missing response_body — document 200 response schema."
            )

    return w


def run_nckt_checks(data: dict) -> list[str]:
    """NCKT (Báo cáo Nghiên cứu khả thi) — NĐ 45/2026 Điều 12 quality gates."""
    nckt = data.get("nckt", {}) or {}
    if not nckt:
        return []

    mins = MINIMUMS["nckt"]
    sections = nckt.get("sections", {}) or {}
    if not isinstance(sections, dict):
        return [
            "nckt.sections: phải là dict keyed theo section path (ví dụ '1.1', '2.4', 'pl.1'). "
            "Tham chiếu outline nghien-cuu-kha-thi/nd45-2026.md."
        ]

    w: list[str] = []

    # ── 1. Required sections present (allow [CẦN BỔ SUNG] but not empty) ──
    required = mins["required_sections"]
    missing: list[str] = []
    for key in required:
        val = sections.get(key, "")
        if not isinstance(val, str) or not val.strip():
            missing.append(key)
    if missing:
        # Group by chapter for readable output
        by_chapter: dict[str, list[str]] = {}
        for k in missing:
            ch = k.split(".")[0] if "." in k else k
            by_chapter.setdefault(ch, []).append(k)
        chunks = [f"§{ch}: {', '.join(ks)}" for ch, ks in sorted(by_chapter.items())]
        w.append(
            f"nckt.sections: thiếu {len(missing)}/{len(required)} section bắt buộc theo "
            f"NĐ 45/2026 Điều 12. Missing: {' | '.join(chunks)}"
        )

    # ── 2. Per-section minimum word counts ──
    default_min = mins["sections_min_words_default"]
    overrides = mins["sections_min_words_overrides"]
    for key, val in sections.items():
        if not isinstance(val, str):
            continue
        actual = word_count(val)
        if actual == 0:
            continue  # already flagged in step 1
        min_w = overrides.get(key, default_min)
        if actual < min_w:
            w.append(
                f"nckt.sections['{key}']: {actual} words < {min_w} required."
            )

    # ── 3. §1.2 — căn cứ pháp lý ≥ N văn bản ──
    s12 = sections.get("1.2", "")
    refs_count = count_legal_refs(s12)
    if isinstance(s12, str) and s12.strip() and refs_count < mins["section_1_2_min_legal_refs"]:
        w.append(
            f"nckt.sections['1.2'] (Căn cứ pháp lý): {refs_count} văn bản pháp lý "
            f"< {mins['section_1_2_min_legal_refs']} required. Phải viện dẫn đầy đủ "
            f"Luật / Nghị định / Thông tư / Quyết định / Chỉ thị (số hiệu, ngày, cơ quan)."
        )

    # ── 4. §2.4 — sự cần thiết phải có numbers (data-driven justification) ──
    s24 = sections.get("2.4", "")
    if isinstance(s24, str) and word_count(s24) >= 200:
        nums = number_count(s24)
        min_nums = mins["section_2_4_min_numbers"]
        if nums < min_nums:
            w.append(
                f"nckt.sections['2.4'] (Sự cần thiết đầu tư): {nums} numbers < "
                f"{min_nums} required. Phải có số liệu cụ thể (lượng người dùng, "
                f"khối lượng hồ sơ, chi phí hiện tại, thời gian xử lý...)."
            )

    # ── 5. §9.1 — ATTT phải nêu cấp độ N theo NĐ 85/2016 ──
    s91 = sections.get("9.1", "")
    if isinstance(s91, str) and s91.strip():
        low = s91.lower()
        for phrase in mins["section_9_1_must_contain"]:
            if phrase not in low:
                w.append(
                    f"nckt.sections['9.1'] (Yêu cầu ATTT): thiếu xác định 'cấp độ N' "
                    f"theo NĐ 85/2016 Điều 7 + TT 12/2022. Phải ghi rõ 'Hệ thống "
                    f"được xác định cấp độ X', kèm 5 nhóm biện pháp TCVN 11930."
                )
                break
        # 5 ATTT groups coverage
        missing_groups = [
            g for g, kws in FIVE_ATTT_GROUPS.items()
            if not any(kw in low for kw in kws)
        ]
        if missing_groups:
            w.append(
                f"nckt.sections['9.1']: thiếu {len(missing_groups)}/5 nhóm ATTT "
                f"TCVN 11930 ({', '.join(missing_groups)})."
            )

    # ── 6. §14.2 — tổng mức đầu tư phải có giá trị tiền tệ ──
    s142 = sections.get("14.2", "")
    investment_summary = nckt.get("investment_summary", []) or []
    if (isinstance(s142, str) and s142.strip()
            and mins["section_14_2_must_contain_currency"]):
        currency_re = re.compile(
            r"(\d[\d.,]*\s*(tỷ|triệu|nghìn|đồng|VND|VNĐ))",
            re.IGNORECASE,
        )
        if not currency_re.search(s142) and not investment_summary:
            w.append(
                "nckt.sections['14.2'] (Tổng mức đầu tư): không tìm thấy giá trị "
                "tiền tệ (tỷ/triệu/đồng) và investment_summary trống. Phải điền "
                "bảng nckt.investment_summary[] HOẶC nêu số liệu trong prose §14.2."
            )

    # ── 7. §18.1 — risk_matrix ≥ N rows when section is filled ──
    s181 = sections.get("18.1", "")
    rmin = mins["risk_matrix_min_rows"]
    risk_matrix = nckt.get("risk_matrix", []) or []
    if isinstance(s181, str) and s181.strip() and len(risk_matrix) < rmin:
        w.append(
            f"nckt.risk_matrix: {len(risk_matrix)} rows < {rmin} required. "
            f"§18.1 phải bao quát ≥ 5 rủi ro (ngân sách, tiến độ, yêu cầu, ATTT, "
            f"năng lực nhà thầu) với cột {{stt, risk, probability, impact, level, "
            f"mitigation}}."
        )
    # Validate risk_matrix row schema
    required_risk_fields = {"stt", "risk", "probability", "impact", "level", "mitigation"}
    for i, r in enumerate(risk_matrix):
        if not isinstance(r, dict):
            continue
        miss = required_risk_fields - set(r.keys())
        if miss:
            w.append(
                f"nckt.risk_matrix[{i}]: thiếu field {sorted(miss)}. "
                f"Schema: {sorted(required_risk_fields)}."
            )

    # ── 8. investment_summary row schema ──
    required_inv_fields = {"stt", "item", "unit", "qty", "unit_price", "amount"}
    for i, r in enumerate(investment_summary):
        if not isinstance(r, dict):
            continue
        miss = required_inv_fields - set(r.keys())
        if miss:
            w.append(
                f"nckt.investment_summary[{i}]: thiếu field {sorted(miss)}. "
                f"Schema: {sorted(required_inv_fields)} + optional 'note'."
            )

    # ── 9. Placeholder cap ──
    ph = count_placeholders(nckt)
    if ph > mins["placeholders_max"]:
        w.append(
            f"nckt: {ph} placeholders [CẦN BỔ SUNG] > {mins['placeholders_max']} "
            f"allowed. Bổ sung dữ liệu hoặc giảm scope tài liệu."
        )

    # ── 10. Specificity density on key data-rich sections ──
    for key, min_per_500 in (
        ("2.1", 5),
        ("2.3.1", 8),
        ("2.4", 6),
        ("8.1.3", 8),
        ("8.1.4", 8),
        ("14.2", 8),
        ("17.1", 5),
    ):
        text = sections.get(key, "")
        if isinstance(text, str):
            w += check_specificity_density(
                text, f"nckt.sections['{key}']", min_numbers_per_500=min_per_500
            )

    return w


def check_tc_quality(data: dict) -> list[str]:
    """Phase 2 — Test case depth checks.

    Rules:
    - UI TCs: ≥ 2 steps per TC (single-step = not a real TC)
    - API TCs: ≥ 1 step per TC
    - All TCs with feature_id: expected results must be non-empty
    - Features with dialogs: must have ≥ 1 TC covering confirm/cancel dialog path
    - Error cases with trigger: must have expected_http_code (API) or expected_ui_state (UI)
    """
    warnings: list[str] = []
    test_cases = data.get("test_cases", {}) or {}

    # ── UI TCs: ≥ 2 steps ────────────────────────────────────────────────────
    ui_tcs = test_cases.get("ui", []) or []
    for item in ui_tcs:
        if not isinstance(item, dict) or item.get("_type") in ("feature_group", "section_header"):
            continue
        name = item.get("name", "?")
        steps = item.get("steps", []) or []
        expected = item.get("expected", []) or []
        fid = item.get("feature_id", "")

        # Count effective steps
        step_count = len(steps)
        if step_count < 2 and not expected:
            # Single-step or empty
            warnings.append(
                f"test_cases.ui TC '{name}' ({fid}): {step_count} step(s) — "
                f"UI TCs require ≥ 2 steps (navigate + action + verify is minimum)."
            )
        # Expected results presence
        has_expected = any(
            (isinstance(s, dict) and s.get("expected")) for s in steps
        ) or len(expected) > 0
        if not has_expected and fid:
            warnings.append(
                f"test_cases.ui TC '{name}' ({fid}): no expected results. "
                f"Each step or TC must document expected outcome."
            )

    # ── API TCs: ≥ 1 step ────────────────────────────────────────────────────
    api_tcs = test_cases.get("api", []) or []
    for item in api_tcs:
        if not isinstance(item, dict) or item.get("_type") in ("feature_group", "section_header"):
            continue
        name = item.get("name", "?")
        steps = item.get("steps", []) or []
        fid = item.get("feature_id", "")
        if len(steps) < 1:
            warnings.append(
                f"test_cases.api TC '{name}' ({fid}): 0 steps — "
                f"API TCs require ≥ 1 step (call + expected HTTP code + response body)."
            )

    # ── Dialog TC coverage per feature ───────────────────────────────────────
    services = data.get("services", []) or []
    # Build feature_id → dialogs map
    feature_dialogs: dict[str, list[dict]] = {}
    for svc in services:
        for feat in (svc.get("features", []) or []):
            fid = feat.get("id", "")
            dialogs = feat.get("dialogs", []) or []
            if fid and dialogs:
                feature_dialogs[fid] = dialogs

    # Build feature_id → list of TC names (UI + API) for coverage lookup
    feature_tcs: dict[str, list[str]] = {}
    for item in ui_tcs + api_tcs:
        if not isinstance(item, dict) or item.get("_type") in ("feature_group", "section_header"):
            continue
        fid = item.get("feature_id", "")
        if fid:
            feature_tcs.setdefault(fid, []).append(item.get("name", "").lower())

    DIALOG_KEYWORDS = ["xác nhận", "hủy", "dialog", "modal", "popup", "đóng", "confirm", "cancel"]

    for fid, dialogs in feature_dialogs.items():
        tc_names = feature_tcs.get(fid, [])
        # Check if any TC name contains dialog-related keywords
        has_dialog_tc = any(
            any(kw in tc_name for kw in DIALOG_KEYWORDS)
            for tc_name in tc_names
        )
        if not has_dialog_tc:
            dialog_titles = [d.get("title", "?") for d in dialogs[:3] if isinstance(d, dict)]
            warnings.append(
                f"test_cases [{fid}]: feature has {len(dialogs)} dialog(s) "
                f"({', '.join(dialog_titles)}) but no dialog-covering TC found "
                f"(TC name should contain 'xác nhận', 'hủy', 'dialog', 'modal', etc.)."
            )

    # ── Error cases: expected_http_code / expected_ui_state ──────────────────
    for svc in services:
        for feat in (svc.get("features", []) or []):
            fid = feat.get("id", "")
            for i, ec in enumerate(feat.get("error_cases", []) or []):
                if not isinstance(ec, dict):
                    continue
                trigger = ec.get("trigger_step", 0)
                if not trigger:
                    continue  # no trigger = generic error, skip
                if not ec.get("expected_http_code") and not ec.get("expected_ui_state"):
                    cond = ec.get("condition", "?")
                    warnings.append(
                        f"{fid}.error_cases[{i}] (trigger step {trigger}, condition '{cond}'): "
                        f"missing expected_http_code and expected_ui_state. "
                        f"Document observable outcome so TC can verify it."
                    )

    return warnings


def _shingle_set(text: str, n: int = 3) -> set:
    """Return character-trigram shingle set for similarity comparison.

    Char trigrams (rather than word shingles) handle Vietnamese diacritics + short
    fragment matches like "Module M0X thuộc phạm vi" cleanly without tokenisation.
    """
    if not text or not isinstance(text, str):
        return set()
    s = re.sub(r"\s+", " ", text.strip().lower())
    if len(s) < n:
        return {s}
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def _jaccard(a: set, b: set) -> float:
    """Jaccard similarity ∈ [0, 1]. 1 = identical, 0 = disjoint."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def check_module_diversity(data: dict) -> list[str]:
    """Detect copy-paste boilerplate across `tkct.modules[]`.

    Triggered the customs-clearance regression where 13 modules shared identical
    template text ("Module M0X thuộc phạm vi… Chưa xác định luồng…"). Writers
    that replicate template strings hit this gate — they must produce
    module-specific content for each module.

    Compares description + flow_description per module pairwise; any pair above
    `module_text_similarity_max` (default 0.80 Jaccard on char-trigrams) is flagged.
    Reports the highest-similarity pair per module to keep noise low.
    """
    tkct = data.get("tkct", {}) or {}
    modules = tkct.get("modules", []) or []
    if len(modules) < 2:
        return []

    threshold = MINIMUMS["tkct"].get("module_text_similarity_max", 0.80)

    # Pre-compute shingle sets once.
    sigs: list[tuple[str, set]] = []
    for i, m in enumerate(modules):
        if not isinstance(m, dict):
            continue
        text = (m.get("description", "") or "") + " " + (m.get("flow_description", "") or "")
        sigs.append((m.get("name", f"[{i}]"), _shingle_set(text)))

    warnings: list[str] = []
    flagged_pairs: set[tuple[int, int]] = set()
    for i, (name_i, sig_i) in enumerate(sigs):
        for j in range(i + 1, len(sigs)):
            name_j, sig_j = sigs[j]
            sim = _jaccard(sig_i, sig_j)
            if sim >= threshold:
                flagged_pairs.add((i, j))
                warnings.append(
                    f"tkct.modules: '{name_i}' and '{name_j}' share "
                    f"{sim * 100:.0f}% text (threshold {threshold * 100:.0f}%) — "
                    f"description+flow appear to be copy-paste boilerplate. "
                    f"Each module must have distinct, project-specific content "
                    f"derived from intel (flow-report, code analysis, interview)."
                )

    # If many pairs are flagged, emit one summary line so the report stays readable.
    if len(flagged_pairs) > 5:
        warnings = warnings[:5] + [
            f"tkct.modules: {len(flagged_pairs)} similar module pairs total — "
            f"{len(modules)} modules but content is largely template. "
            f"Re-extract per-module flows from intel before re-rendering."
        ]
    return warnings


def check_diagrams_block(data: dict) -> list[str]:
    """Ensure every non-empty `*_diagram` filename reference has matching
    Mermaid/SVG source in the top-level `diagrams` block.

    Catches the regression where writers fill `architecture.architecture_diagram`
    with a filename (or leave it blank) but forget to populate
    `diagrams.architecture_diagram` with renderable source. Stage 6 export then
    produces docs without any diagrams.

    Two failure modes detected:
      1. *_diagram field is non-empty BUT diagrams[key] missing/empty
         → engine cannot render PNG; docx will have a broken InlineImage.
      2. *_diagram field is empty AND the block lists this diagram as required
         (per MINIMUMS[block].diagrams_required) → declared diagram never declared.

    Whitelisted: tkct.modules[].flow_diagram is optional per MINIMUMS rule;
    only flagged via the existing module_required_diagram check.
    """
    warnings: list[str] = []
    diagrams_block = data.get("diagrams", {}) or {}

    # Collect every *_diagram field across architecture/tkcs/tkct/nckt blocks.
    blocks = {
        "architecture": data.get("architecture", {}) or {},
        "tkcs": data.get("tkcs", {}) or {},
        "tkct": data.get("tkct", {}) or {},
        "nckt": data.get("nckt", {}) or {},
    }

    has_block_with_content = any(blocks[b] for b in blocks)
    if not has_block_with_content:
        return []  # nothing to check — empty document

    for block_name, block in blocks.items():
        if not block:
            continue

        # Required diagrams per block.
        required = MINIMUMS.get(block_name, {}).get("diagrams_required", [])
        # NCKT uses different field names than diagrams.* keys (no nckt_ prefix on field).
        diagram_field_map = MINIMUMS.get(block_name, {}).get("diagram_field_map", {})
        for key in required:
            # Resolve actual block field name (NCKT field names lack the nckt_ prefix).
            field_name = diagram_field_map.get(key, key)
            field_value = (
                (block.get(field_name) or "").strip()
                if isinstance(block.get(field_name), str) else ""
            )
            mermaid_src = diagrams_block.get(key)
            mermaid_present = bool(
                (isinstance(mermaid_src, str) and mermaid_src.strip())
                or (isinstance(mermaid_src, dict) and mermaid_src.get("template"))
            )

            if not field_value and not mermaid_present:
                warnings.append(
                    f"diagrams.{key}: required for {block_name} but missing — "
                    f"set {block_name}.{field_name} to a filename (e.g. '{key}.png') AND "
                    f"populate diagrams.{key} with Mermaid source or SVG hero dict."
                )
            elif field_value and not mermaid_present:
                warnings.append(
                    f"diagrams.{key}: {block_name}.{field_name} references '{field_value}' "
                    f"but diagrams.{key} has no source. Engine cannot render PNG — "
                    f"docx will contain a broken image. Add Mermaid source or "
                    f"clear the filename reference."
                )
            elif mermaid_present and not field_value:
                warnings.append(
                    f"diagrams.{key}: source present but {block_name}.{field_name} is empty — "
                    f"docxtpl will not embed the rendered PNG. Set {block_name}.{field_name} "
                    f"to '{key}.png' (engine writes there)."
                )

    return warnings


def check_db_table_columns(data: dict) -> list[str]:
    """Ensure `tkct.db_tables[]` carry real schema, not just id + timestamps.

    Heuristic: any column whose name matches /^id$|_id$|created_at|updated_at|
    deleted_at|version|tenant/ counts as "infrastructure", not business. A real
    table must have ≥ `db_table_min_business_columns` business columns out of
    ≥ `db_table_min_columns` total.
    """
    warnings: list[str] = []
    tkct = data.get("tkct", {}) or {}
    tables = tkct.get("db_tables", []) or []
    if not tables:
        return []

    min_cols = MINIMUMS["tkct"]["db_table_min_columns"]
    min_biz = MINIMUMS["tkct"]["db_table_min_business_columns"]
    INFRA_RE = re.compile(
        r"^(id|.*_id|created_at|updated_at|deleted_at|version|tenant_?id?|"
        r"row_version|created_by|updated_by|is_deleted)$",
        re.IGNORECASE,
    )

    for i, t in enumerate(tables):
        if not isinstance(t, dict):
            continue
        name = t.get("name", f"[{i}]")
        cols = t.get("columns", []) or []
        col_names = [
            c.get("name", "") for c in cols if isinstance(c, dict) and c.get("name")
        ]
        total = len(col_names)
        biz = [n for n in col_names if not INFRA_RE.fullmatch(n.strip())]
        biz_count = len(biz)

        if total < min_cols:
            warnings.append(
                f"tkct.db_tables[{i}] ({name}): {total} columns < {min_cols} required — "
                f"document the full schema, not just primary key + timestamps."
            )
        if biz_count < min_biz:
            warnings.append(
                f"tkct.db_tables[{i}] ({name}): only {biz_count} business column(s) "
                f"({total} total) — at least {min_biz} non-infrastructure columns "
                f"required (id, *_id, created_at, updated_at, version, tenant_id are "
                f"infrastructure). Found business: {biz[:5] or '∅'}."
            )

    return warnings


def check_test_case_ids(data: dict) -> list[str]:
    """Enforce structural fields on `test_cases.{ui,api}[]`.

    The xlsx render pipeline reads `id`, `name`, `feature_id` directly into cells.
    Writers commonly skip `id` (using `name: "F-001 — ..."` as both label and key)
    which leaves the id column blank in the rendered xlsx and breaks downstream
    traceability.
    """
    warnings: list[str] = []
    test_cases = data.get("test_cases", {}) or {}
    cfg = MINIMUMS.get("test_cases", {})
    required = cfg.get("tc_required_fields", ["id", "name", "feature_id"])
    id_pattern = re.compile(cfg.get("tc_id_pattern", r"^TC-[A-Z0-9]+-\d{3,}$"))

    for kind in ("ui", "api"):
        items = test_cases.get(kind, []) or []
        missing_id_count = 0
        bad_pattern_count = 0
        sample_bad: list[str] = []

        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("_type") in ("feature_group", "section_header"):
                continue  # structural rows, not TCs
            for f in required:
                if not item.get(f):
                    if f == "id":
                        missing_id_count += 1
                        if len(sample_bad) < 3:
                            sample_bad.append(item.get("name", "?")[:40])
                    else:
                        warnings.append(
                            f"test_cases.{kind}: TC '{item.get('name','?')}' "
                            f"missing required field '{f}'."
                        )
            tc_id = item.get("id", "")
            if tc_id and not id_pattern.fullmatch(tc_id):
                bad_pattern_count += 1
                if len(sample_bad) < 3:
                    sample_bad.append(f"id={tc_id!r}")

        if missing_id_count:
            warnings.append(
                f"test_cases.{kind}: {missing_id_count}/{len(items)} TCs missing 'id' field — "
                f"sample: {sample_bad}. xlsx render fills id column from this field; "
                f"name alone is not enough. Use pattern TC-<MODULE>-<NNN>."
            )
        if bad_pattern_count:
            warnings.append(
                f"test_cases.{kind}: {bad_pattern_count} TCs with non-conforming id — "
                f"expected pattern '{cfg.get('tc_id_pattern')}'. Sample: {sample_bad}."
            )

    return warnings


def run_all_quality_checks(data: dict) -> list[str]:
    """Entry point: all Phase 1+2+3 checks."""
    w: list[str] = []
    # Phase 1 — diagrams integrity (cross-refs + block consistency + quality bar).
    w += check_diagram_cross_refs(data)
    w += check_diagrams_block(data)
    w += check_diagram_quality(data)
    # Phase 2 — content quality.
    w += check_banned_phrases(data)
    # Phase 2+3 per block.
    w += run_tkkt_checks(data)
    w += run_tkcs_checks(data)
    w += run_tkct_checks(data)
    w += run_nckt_checks(data)
    # Phase 3 — structural integrity beyond word counts.
    w += check_module_diversity(data)
    w += check_db_table_columns(data)
    w += check_test_case_ids(data)
    # Phase 2 — TC depth (existing).
    w += check_tc_quality(data)
    return w
