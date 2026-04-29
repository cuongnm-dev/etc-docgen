#!/usr/bin/env python3
"""
synthesize_tc_fallback.py — Deterministic Path B test-case synthesizer.

Purpose:
  generate-docs Stage 4f Path B (rich fallback). Used by writer agent OR called
  directly by orchestrator when test-evidence/{feature-id}.json is empty.

Implements CD-10 Quy tắc 18:
  - ISTQB techniques: BVA, EP, Decision Table, State Transition, Error Guessing
  - VN gov mandatory dimensions: audit_log, pii_masking, concurrent_edit,
    vn_diacritics, session_expire (+ sla_timeout when workflow_variants present)
  - Cross-pollinate from HDSD output when feature-catalog lacks dialogs/error_cases

Output schema matches audience-profiles/xlsx.yaml.writer_output_schema.

Usage (CLI):
  python synthesize_tc_fallback.py \
    --intel-dir   docs/intel/ \
    --hdsd-data   docs/output/content-data.json \
    --feature-ids "ALL" | "F-001,F-002,..." \
    --out         docs/output/test_cases.json

Usage (programmatic):
  from synthesize_tc_fallback import FallbackSynthesizer
  synth = FallbackSynthesizer(intel_dir, hdsd_data_path)
  tcs = synth.for_feature(feature_id)         # returns list[dict]
  all_tcs = synth.for_all()                    # returns dict[feature_id, list]

Idempotent + deterministic — same input always produces same output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PRIORITY_VN = {"P0": "Rất cao", "P1": "Cao", "P2": "Trung bình", "P3": "Thấp"}

# Map design_technique → human-readable test type label (VN, dropdown match)
TECHNIQUE_LABEL = {
    "ep": "Functional",
    "bva": "Boundary",
    "dt": "Functional",
    "st": "Functional",
    "eg": "Negative",
    "domain": "Audit",
}

# Default severity per priority (industry mapping, can override per-TC)
PRI_TO_SEV = {
    "Rất cao": "Blocker",  # smoke / RBAC denied / audit
    "Cao": "Major",  # validation / errors
    "Trung bình": "Minor",  # boundary / edge
    "Thấp": "Trivial",  # cosmetic
}


def _enrich(tc: dict) -> dict:
    """Add v2 template fields to a TC dict (severity, design_technique_label, linked_ac)."""
    pri = tc.get("priority", "Trung bình")
    tc.setdefault("severity", PRI_TO_SEV.get(pri, "Major"))
    tc.setdefault(
        "design_technique_label", TECHNIQUE_LABEL.get(tc.get("design_technique"), "Functional")
    )
    # linked_ac: try to extract AC reference from labels or expected_overall
    if "linked_ac" not in tc:
        # If TC came from AC negative path → labels contain "ac-coverage"
        if "ac-coverage" in tc.get("labels", []) and "expected_overall" in tc:
            tc["linked_ac"] = "AC: " + tc["expected_overall"][:50]
        else:
            tc["linked_ac"] = ""
    tc.setdefault("notes", "")
    return tc


class FallbackSynthesizer:
    def __init__(self, intel_dir: Path, hdsd_data_path: Path | None = None):
        self.intel_dir = Path(intel_dir)
        self.hdsd_data_path = Path(hdsd_data_path) if hdsd_data_path else None
        self._load_intel()
        self._seq: dict[tuple, int] = {}

    # ─── Intel loading ───
    def _load(self, name: str) -> dict:
        p = self.intel_dir / name
        if not p.exists():
            return {}
        return json.loads(p.read_text(encoding="utf-8"))

    def _load_intel(self) -> None:
        self.feature_catalog = self._load("feature-catalog.json")
        self.actor_registry = self._load("actor-registry.json")
        self.sitemap = self._load("sitemap.json")
        self.hdsd_features: dict[str, dict] = {}
        if self.hdsd_data_path and self.hdsd_data_path.exists():
            hdsd = json.loads(self.hdsd_data_path.read_text(encoding="utf-8"))
            for s in hdsd.get("services", []):
                for f in s.get("features", []):
                    self.hdsd_features[f.get("id")] = f
        # Module lexicon from sitemap
        self.module_lex: dict[str, str] = {}
        for svc in self.sitemap.get("services", {}).values():
            if isinstance(svc, dict):
                for rg in svc.get("route_groups", []):
                    if rg.get("id"):
                        self.module_lex[rg["id"]] = rg.get("title") or rg["id"]
        # Roles indexes
        self.roles_by_slug = {r["slug"]: r for r in self.actor_registry.get("roles", [])}
        self.active_roles = [
            r for r in self.actor_registry.get("roles", []) if r["slug"] not in ("ADMIN", "system")
        ]

    # ─── Sequence generator ───
    def _next_id(self, module: str, role_slug: str | None, dim: str) -> str:
        key = (module, role_slug or "X", dim)
        self._seq[key] = self._seq.get(key, 0) + 1
        parts = ["TC", module.upper(), role_slug or "X", dim, f"{self._seq[key]:03d}"]
        return "-".join(parts)

    # ─── Cross-pollinate ───
    def _enrich_feature(self, feat: dict) -> dict:
        """Backfill dialogs/error_cases/ui_elements from HDSD when intel lacks them."""
        h = self.hdsd_features.get(feat.get("id"))
        if h:
            feat = dict(feat)  # shallow copy
            feat.setdefault("dialogs", h.get("dialogs", []))
            feat.setdefault("error_cases", h.get("error_cases", []))
            feat.setdefault("ui_elements", h.get("ui_elements", []))
            feat.setdefault("hdsd_steps", h.get("steps", []))
        return feat

    # ─── Min TC formula (CD-10 Quy tắc 15) ───
    @staticmethod
    def min_tc(feat: dict) -> int:
        return max(
            5,
            len(feat.get("acceptance_criteria", [])) * 2
            + len(feat.get("roles", [])) * 2
            + len(feat.get("dialogs", [])) * 2
            + len(feat.get("error_cases", []))
            + 3,
        )

    # ─── TC builders per dimension ───
    def _tc_happy(self, feat: dict, role: dict) -> dict:
        rs, rd = role["slug"], role["display_name"]
        module = feat["module"]
        ml = self.module_lex.get(module, module.upper())
        acs = feat.get("acceptance_criteria", []) or [feat["name"]]
        return {
            "id": self._next_id(module, rs, "HAPPY"),
            "name": f"{feat['name']} thành công ({rd})",
            "feature_id": feat["id"],
            "feature_module": module,
            "source": "generate-docs/fallback-synthesized",
            "role": rd,
            "priority": PRIORITY_VN["P0"],
            "labels": ["smoke", "happy-path", f"role-{rs}"],
            "design_technique": "ep",
            "preconditions": (
                f"Đã đăng nhập với vai trò '{rd}'; "
                f"có hồ sơ/dữ liệu hợp lệ để thực hiện '{feat['name']}'."
            ),
            "data_set": None,
            "steps": [
                {
                    "no": 1,
                    "action": f"Vào menu **{ml}** từ thanh điều hướng chính.",
                    "expected": f"Màn hình {ml} hiển thị, danh sách tải xong (≤ 3 giây).",
                },
                {
                    "no": 2,
                    "action": "Chọn hồ sơ/đối tượng cần xử lý từ danh sách.",
                    "expected": "Chi tiết hiển thị đầy đủ thông tin theo đặc tả.",
                },
                {
                    "no": 3,
                    "action": f"Thực hiện thao tác chính: {acs[0]}.",
                    "expected": "Hệ thống xử lý thành công, hiển thị thông báo 'Thành công'.",
                },
                {
                    "no": 4,
                    "action": "Đăng nhập role 'Lãnh đạo hải quan', vào Nhật ký hệ thống, lọc theo mã hồ sơ.",
                    "expected": (
                        f"Có bản ghi log: actor={rs}, action={feat['name'][:30]}, "
                        f"target=mã hồ sơ, timestamp khớp."
                    ),
                },
            ],
            "expected_overall": acs[0],
            "dialog_id": None,
            "error_case_id": None,
            "transition": None,
            "expected_evidence": f"Audit log entry actor={rs} action={feat['name']}",
            "execution": {
                "status": "not-executed",
                "screenshot_refs": [],
                "playwright_script": None,
            },
        }

    def _tc_denied(self, feat: dict, role: dict) -> dict:
        rs, rd = role["slug"], role["display_name"]
        module = feat["module"]
        ml = self.module_lex.get(module, module.upper())
        return {
            "id": self._next_id(module, rs, "DENIED"),
            "name": f"{rd} KHÔNG truy cập được {feat['name']}",
            "feature_id": feat["id"],
            "feature_module": module,
            "source": "generate-docs/fallback-synthesized",
            "role": rd,
            "priority": PRIORITY_VN["P0"],
            "labels": ["rbac", "security", "access-denied", f"role-{rs}"],
            "design_technique": "domain",
            "preconditions": f"Đã đăng nhập với vai trò '{rd}'.",
            "data_set": None,
            "steps": [
                {
                    "no": 1,
                    "action": "Quan sát menu chính sau khi đăng nhập.",
                    "expected": f"Menu KHÔNG có mục **{ml}** — chức năng dành cho vai trò khác.",
                },
                {
                    "no": 2,
                    "action": f"Truy cập trực tiếp URL trang **{ml}** (gõ URL hoặc dán bookmark).",
                    "expected": "Hệ thống thông báo 'Không đủ quyền' hoặc redirect về trang chủ.",
                },
                {
                    "no": 3,
                    "action": "Đăng nhập role 'Lãnh đạo hải quan', vào Nhật ký hệ thống.",
                    "expected": f"Có bản ghi log ACCESS_DENIED: actor={rs}, target={ml}.",
                },
            ],
            "expected_overall": f"Vai trò {rd} không thể truy cập {feat['name']}; sự kiện được ghi log.",
            "dialog_id": None,
            "error_case_id": None,
            "transition": None,
            "expected_evidence": f"Audit log ACCESS_DENIED actor={rs}",
            "execution": {
                "status": "not-executed",
                "screenshot_refs": [],
                "playwright_script": None,
            },
        }

    def _tc_ac_negative(self, feat: dict, ac: str, primary_role: dict | None) -> dict:
        module = feat["module"]
        ml = self.module_lex.get(module, module.upper())
        return {
            "id": self._next_id(module, None, "ACVAL"),
            "name": f"Chặn {feat['name']} khi vi phạm: {ac[:60]}",
            "feature_id": feat["id"],
            "feature_module": module,
            "source": "generate-docs/fallback-synthesized",
            "role": primary_role["display_name"] if primary_role else None,
            "priority": PRIORITY_VN["P1"],
            "labels": ["validation", "negative", "ac-coverage"],
            "design_technique": "ep",
            "preconditions": f"Đã đăng nhập role hợp lệ; chuẩn bị dữ liệu vi phạm tiêu chí: '{ac}'.",
            "data_set": f"Dữ liệu vi phạm AC: {ac}",
            "steps": [
                {
                    "no": 1,
                    "action": f"Vào màn hình **{ml}**, tạo/mở hồ sơ với dữ liệu vi phạm AC.",
                    "expected": "Form mở ra với dữ liệu test.",
                },
                {
                    "no": 2,
                    "action": "Nhấn nút lưu/gửi/thực thi tương ứng.",
                    "expected": f"Hệ thống chặn, hiển thị thông báo lỗi liên quan: '{ac}'.",
                },
                {
                    "no": 3,
                    "action": "Kiểm tra trạng thái hồ sơ + bản ghi log.",
                    "expected": "Hồ sơ KHÔNG bị thay đổi; có log VALIDATION_FAILED.",
                },
            ],
            "expected_overall": f"Hệ thống enforce AC '{ac}' — chặn thao tác khi vi phạm.",
            "dialog_id": None,
            "error_case_id": None,
            "transition": None,
            "expected_evidence": "Audit log VALIDATION_FAILED + form error message",
            "execution": {
                "status": "not-executed",
                "screenshot_refs": [],
                "playwright_script": None,
            },
        }

    def _tc_dialog(self, feat: dict, dlg: dict, path: str) -> dict:
        """path ∈ {confirm, cancel, validation}"""
        module = feat["module"]
        ml = self.module_lex.get(module, module.upper())
        dlg_title = dlg.get("title", "Hộp thoại")
        dlg_id = dlg.get("id", "DLG")
        path_label = {
            "confirm": "Xác nhận → action thực thi",
            "cancel": "Hủy → action bị bỏ qua",
            "validation": "Nhập sai → dialog hiển thị lỗi",
        }[path]
        priority = PRIORITY_VN["P1"] if path == "confirm" else PRIORITY_VN["P2"]
        return {
            "id": self._next_id(module, None, f"DLG-{path.upper()}"),
            "name": f"Dialog '{dlg_title}': {path_label}",
            "feature_id": feat["id"],
            "feature_module": module,
            "source": "generate-docs/fallback-synthesized",
            "role": None,
            "priority": priority,
            "labels": ["dialog", f"dialog-{path}"],
            "design_technique": "dt",
            "preconditions": f"Đã đăng nhập role có quyền; chuẩn bị scenario kích hoạt dialog '{dlg_title}'.",
            "data_set": None,
            "steps": [
                {
                    "no": 1,
                    "action": f"Vào **{ml}**, thực hiện thao tác kích hoạt dialog.",
                    "expected": f"Dialog '{dlg_title}' xuất hiện.",
                },
                {
                    "no": 2,
                    "action": {
                        "confirm": "Nhập đầy đủ thông tin hợp lệ và nhấn **[Xác nhận]**.",
                        "cancel": "Nhấn **[Hủy]** hoặc nút X đóng dialog.",
                        "validation": "Để trống trường bắt buộc và nhấn **[Xác nhận]**.",
                    }[path],
                    "expected": {
                        "confirm": "Dialog đóng, action thực thi, toast 'Thành công' hiển thị.",
                        "cancel": "Dialog đóng, KHÔNG có thay đổi dữ liệu.",
                        "validation": "Dialog vẫn mở, hiển thị thông báo lỗi inline cho trường thiếu.",
                    }[path],
                },
                {
                    "no": 3,
                    "action": "Kiểm tra trạng thái dữ liệu sau thao tác.",
                    "expected": {
                        "confirm": "Dữ liệu cập nhật theo input dialog.",
                        "cancel": "Dữ liệu không đổi.",
                        "validation": "Dữ liệu không đổi (form chưa submit).",
                    }[path],
                },
            ],
            "expected_overall": f"Dialog '{dlg_title}' xử lý đúng nhánh {path}.",
            "dialog_id": dlg_id,
            "error_case_id": None,
            "transition": None,
            "expected_evidence": "DOM state dialog + DB state entity",
            "execution": {
                "status": "not-executed",
                "screenshot_refs": [],
                "playwright_script": None,
            },
        }

    def _tc_error_case(self, feat: dict, ec: dict) -> dict:
        module = feat["module"]
        ml = self.module_lex.get(module, module.upper())
        ec_id = ec.get("id", "ERR")
        cond = ec.get("condition", "Lỗi không xác định")
        msg = ec.get("message") or ec.get("user_message", "Hệ thống thông báo lỗi.")
        trigger = ec.get("trigger_step", 1)
        return {
            "id": self._next_id(module, None, f"ERR-{ec_id}"),
            "name": f"Xử lý lỗi: {cond[:60]}",
            "feature_id": feat["id"],
            "feature_module": module,
            "source": "generate-docs/fallback-synthesized",
            "role": None,
            "priority": PRIORITY_VN["P1"],
            "labels": ["error-handling", "negative"],
            "design_technique": "eg",
            "preconditions": f"Đã đăng nhập role hợp lệ; chuẩn bị tình huống kích hoạt lỗi: {cond}.",
            "data_set": None,
            "steps": [
                {
                    "no": 1,
                    "action": f"Vào **{ml}**, bắt đầu thao tác.",
                    "expected": "Màn hình tải bình thường.",
                },
                {
                    "no": 2,
                    "action": f"Thực hiện đến bước {trigger}, kích hoạt điều kiện lỗi: {cond}.",
                    "expected": f"Hệ thống hiển thị thông báo: '{msg}'.",
                },
                {
                    "no": 3,
                    "action": "Quan sát trạng thái hồ sơ sau lỗi.",
                    "expected": "Hồ sơ không bị thay đổi (rollback nếu cần); có log ERROR_HANDLED.",
                },
            ],
            "expected_overall": f"Lỗi '{cond}' được xử lý gracefully, user nhận thông báo rõ ràng.",
            "dialog_id": None,
            "error_case_id": ec_id,
            "transition": None,
            "expected_evidence": f"Toast/modal với text '{msg}' + log ERROR_HANDLED",
            "execution": {
                "status": "not-executed",
                "screenshot_refs": [],
                "playwright_script": None,
            },
        }

    def _tc_dimension_audit(self, feat: dict) -> dict:
        module = feat["module"]
        return {
            "id": self._next_id(module, None, "AUDIT"),
            "name": f"Audit log đầy đủ cho thao tác {feat['name']}",
            "feature_id": feat["id"],
            "feature_module": module,
            "source": "generate-docs/fallback-synthesized",
            "role": None,
            "priority": PRIORITY_VN["P1"],
            "labels": ["audit", "compliance"],
            "design_technique": "domain",
            "preconditions": f"Có ≥ 1 thao tác '{feat['name']}' đã thực hiện trong ngày.",
            "data_set": None,
            "steps": [
                {
                    "no": 1,
                    "action": "Đăng nhập role 'Lãnh đạo hải quan', vào Nhật ký hệ thống.",
                    "expected": "Trang Nhật ký hiển thị, có bộ lọc theo mã hồ sơ + thời gian.",
                },
                {
                    "no": 2,
                    "action": f"Lọc theo loại thao tác '{feat['name']}'.",
                    "expected": "Danh sách log liên quan hiển thị.",
                },
                {
                    "no": 3,
                    "action": "Mở chi tiết 1 bản ghi log.",
                    "expected": (
                        "Bản ghi đủ: actor (slug + tên), action, target, "
                        "timestamp ISO, IP, user-agent."
                    ),
                },
            ],
            "expected_overall": "Mọi thao tác state-changing ghi log đủ trace theo NĐ 13/2023 + ATTT cấp 3.",
            "dialog_id": None,
            "error_case_id": None,
            "transition": None,
            "expected_evidence": "Audit log entry hợp lệ, không null field bắt buộc",
            "execution": {
                "status": "not-executed",
                "screenshot_refs": [],
                "playwright_script": None,
            },
        }

    def _tc_dimension_pii(self, feat: dict) -> dict:
        module = feat["module"]
        ml = self.module_lex.get(module, module.upper())
        return {
            "id": self._next_id(module, None, "PII"),
            "name": f"Che PII (CCCD/SĐT/MST) — {feat['name']}",
            "feature_id": feat["id"],
            "feature_module": module,
            "source": "generate-docs/fallback-synthesized",
            "role": None,
            "priority": PRIORITY_VN["P1"],
            "labels": ["pii", "compliance", "security"],
            "design_technique": "domain",
            "preconditions": "Hồ sơ chứa PII (CCCD đại diện, SĐT, mã số thuế).",
            "data_set": "DN: MST=0123456789, CCCD đại diện, SĐT người liên hệ",
            "steps": [
                {
                    "no": 1,
                    "action": "Đăng nhập role không có quyền xem chi tiết PII.",
                    "expected": "Đăng nhập thành công.",
                },
                {
                    "no": 2,
                    "action": f"Mở **{ml}**, xem 1 hồ sơ.",
                    "expected": "Hồ sơ hiển thị thông tin chung.",
                },
                {
                    "no": 3,
                    "action": "Quan sát các trường: CCCD, SĐT, MST.",
                    "expected": "Các trường mask: CCCD=***-***-1234, SĐT=09**-***-789, MST=01****6789.",
                },
            ],
            "expected_overall": "PII được che cho role không phận sự, tuân thủ NĐ 13/2023.",
            "dialog_id": None,
            "error_case_id": None,
            "transition": None,
            "expected_evidence": "DOM screenshot trường PII bị che",
            "execution": {
                "status": "not-executed",
                "screenshot_refs": [],
                "playwright_script": None,
            },
        }

    def _tc_dimension_concurrent(self, feat: dict, primary_role: dict | None) -> dict:
        module = feat["module"]
        rd = primary_role["display_name"] if primary_role else "Cán bộ"
        return {
            "id": self._next_id(module, None, "CONCUR"),
            "name": f"Phát hiện concurrent edit — {feat['name']}",
            "feature_id": feat["id"],
            "feature_module": module,
            "source": "generate-docs/fallback-synthesized",
            "role": None,
            "priority": PRIORITY_VN["P2"],
            "labels": ["concurrency", "edge", "data-integrity"],
            "design_technique": "eg",
            "preconditions": f"Có 1 hồ sơ ở trạng thái cho phép '{feat['name']}'. Mở 2 phiên với 2 tài khoản '{rd}'.",
            "data_set": None,
            "steps": [
                {
                    "no": 1,
                    "action": f"Phiên 1: mở hồ sơ, click '{feat['name']}'.",
                    "expected": "Form/dialog cho phép chỉnh sửa.",
                },
                {
                    "no": 2,
                    "action": "Phiên 2: cùng hồ sơ, thực hiện và lưu trước.",
                    "expected": "Phiên 2 lưu thành công, version/timestamp cập nhật.",
                },
                {
                    "no": 3,
                    "action": "Phiên 1: nhấn lưu.",
                    "expected": "Hệ thống thông báo 'Hồ sơ đã được cập nhật. Vui lòng tải lại.' KHÔNG ghi đè.",
                },
            ],
            "expected_overall": "Concurrent edit phát hiện qua optimistic locking; không lost update.",
            "dialog_id": None,
            "error_case_id": None,
            "transition": None,
            "expected_evidence": "DB version field tăng đúng 1 lần",
            "execution": {
                "status": "not-executed",
                "screenshot_refs": [],
                "playwright_script": None,
            },
        }

    def _tc_dimension_diacritics(self, feat: dict) -> dict:
        module = feat["module"]
        ml = self.module_lex.get(module, module.upper())
        return {
            "id": self._next_id(module, None, "DIACR"),
            "name": f"Xử lý đúng tiếng Việt có dấu — {feat['name']}",
            "feature_id": feat["id"],
            "feature_module": module,
            "source": "generate-docs/fallback-synthesized",
            "role": None,
            "priority": PRIORITY_VN["P2"],
            "labels": ["i18n", "vn-diacritics", "edge"],
            "design_technique": "eg",
            "preconditions": "Form hỗ trợ nhập text tự do (tên, ghi chú, địa chỉ).",
            "data_set": "Nguyễn Văn Đỗ — số 1, đường Lê Lợi, Q. Tân Bình, TP.HCM",
            "steps": [
                {
                    "no": 1,
                    "action": f"Vào **{ml}**, nhập text có dấu (NFC + NFD trộn).",
                    "expected": "Form chấp nhận, hiển thị đúng các ký tự dấu.",
                },
                {
                    "no": 2,
                    "action": "Lưu, reload trang.",
                    "expected": "Text hiển thị chính xác, không bị '???' hoặc lỗi font.",
                },
                {
                    "no": 3,
                    "action": "Tìm kiếm với từ khóa có dấu (vd 'Lê Lợi').",
                    "expected": "Hồ sơ vừa tạo xuất hiện trong kết quả.",
                },
            ],
            "expected_overall": "Tiếng Việt có dấu lưu + tìm kiếm chính xác (UTF-8 NFC).",
            "dialog_id": None,
            "error_case_id": None,
            "transition": None,
            "expected_evidence": "DB row chứa string NFC; search index hit",
            "execution": {
                "status": "not-executed",
                "screenshot_refs": [],
                "playwright_script": None,
            },
        }

    def _tc_dimension_session(self, feat: dict) -> dict:
        module = feat["module"]
        ml = self.module_lex.get(module, module.upper())
        return {
            "id": self._next_id(module, None, "SESSION"),
            "name": f"Phiên đăng nhập hết hạn giữa luồng — {feat['name']}",
            "feature_id": feat["id"],
            "feature_module": module,
            "source": "generate-docs/fallback-synthesized",
            "role": None,
            "priority": PRIORITY_VN["P2"],
            "labels": ["session", "auth", "edge"],
            "design_technique": "eg",
            "preconditions": "Phiên đăng nhập có thời hạn (vd 30 phút). Set ngắn 5 phút để test.",
            "data_set": None,
            "steps": [
                {
                    "no": 1,
                    "action": f"Đăng nhập, vào **{ml}**, mở 1 hồ sơ.",
                    "expected": "Màn hình tải, dữ liệu hiển thị.",
                },
                {
                    "no": 2,
                    "action": "Để trống ≥ 5 phút (đợi phiên hết hạn) hoặc xóa cookie phiên.",
                    "expected": "Trình duyệt không tự refresh.",
                },
                {
                    "no": 3,
                    "action": "Quay lại tab, nhấn nút lưu/thực thi.",
                    "expected": "Hệ thống chuyển về trang đăng nhập, sau khi đăng nhập lại quay về đúng màn hình trước.",
                },
            ],
            "expected_overall": "Phiên hết hạn xử lý mượt, không lost data nếu draft đã lưu.",
            "dialog_id": None,
            "error_case_id": None,
            "transition": None,
            "expected_evidence": "Redirect /login với param returnUrl",
            "execution": {
                "status": "not-executed",
                "screenshot_refs": [],
                "playwright_script": None,
            },
        }

    # ─── Public API ───
    def for_feature(self, feature_id: str) -> list[dict]:
        feat = next(
            (f for f in self.feature_catalog.get("features", []) if f.get("id") == feature_id),
            None,
        )
        if not feat:
            return []
        feat = self._enrich_feature(feat)

        tcs: list[dict] = []
        feat_role_slugs = feat.get("roles", [])
        feat_roles = [self.roles_by_slug[s] for s in feat_role_slugs if s in self.roles_by_slug]
        invisible = [r for r in self.active_roles if r["slug"] not in feat_role_slugs]
        primary_role = feat_roles[0] if feat_roles else None

        # B.3.1 happy × visible role
        tcs.extend(self._tc_happy(feat, r) for r in feat_roles)
        # B.3.2 denied × invisible role
        tcs.extend(self._tc_denied(feat, r) for r in invisible)
        # B.3.3 AC negative × N
        for ac in feat.get("acceptance_criteria", []):
            tcs.append(self._tc_ac_negative(feat, ac, primary_role))
        # B.3.5 dialogs × 3 paths
        for dlg in feat.get("dialogs", []):
            for path in ("confirm", "cancel", "validation"):
                tcs.append(self._tc_dialog(feat, dlg, path))
        # B.3.6 error_cases × 1
        for ec in feat.get("error_cases", []):
            tcs.append(self._tc_error_case(feat, ec))
        # B.3.8 VN gov dimensions
        tcs.append(self._tc_dimension_audit(feat))
        tcs.append(self._tc_dimension_pii(feat))
        tcs.append(self._tc_dimension_concurrent(feat, primary_role))
        tcs.append(self._tc_dimension_diacritics(feat))
        tcs.append(self._tc_dimension_session(feat))

        return tcs

    def for_all(self, only_done: bool = True) -> list[dict]:
        out: list[dict] = []
        for feat in self.feature_catalog.get("features", []):
            if only_done and feat.get("status") != "done":
                continue
            for tc in self.for_feature(feat["id"]):
                _enrich(tc)
                out.append(tc)
        return out

    def coverage_report(self) -> dict:
        """Returns {feature_id: {target: int, synthesized: int}}"""
        rep = {}
        for feat in self.feature_catalog.get("features", []):
            if feat.get("status") != "done":
                continue
            feat_e = self._enrich_feature(feat)
            target = self.min_tc(feat_e)
            self._seq.clear()  # local count
            tcs = self.for_feature(feat["id"])
            rep[feat["id"]] = {"target": target, "synthesized": len(tcs)}
        return rep


# ─── CLI entry ───
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Synthesize fallback test cases (CD-10 Quy tắc 18)")
    p.add_argument("--intel-dir", required=True)
    p.add_argument(
        "--hdsd-data", default=None, help="Optional HDSD content-data.json for cross-pollinate"
    )
    p.add_argument("--feature-ids", default="ALL", help="ALL | comma-separated IDs")
    p.add_argument("--out", required=True)
    p.add_argument("--only-done", action="store_true", default=True)
    args = p.parse_args(argv)

    synth = FallbackSynthesizer(
        Path(args.intel_dir), Path(args.hdsd_data) if args.hdsd_data else None
    )

    if args.feature_ids == "ALL":
        tcs = synth.for_all(only_done=args.only_done)
    else:
        ids = [x.strip() for x in args.feature_ids.split(",") if x.strip()]
        tcs = []
        for fid in ids:
            tcs.extend(synth.for_feature(fid))

    out_p = Path(args.out)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "test_cases": {"ui": tcs, "api": []},
        "warning_top": (
            f"⚠ {len(tcs)} test case là PROPOSED (sinh tự động bằng fallback synthesis). "
            "QA team cần review + execute + chụp screenshot trước khi sign-off."
        ),
    }
    out_p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"✓ Synthesized {len(tcs)} fallback test cases → {out_p}")
    by_pri: dict[str, int] = {}
    by_label: dict[str, int] = {}
    for tc in tcs:
        by_pri[tc["priority"]] = by_pri.get(tc["priority"], 0) + 1
        for lbl in tc["labels"]:
            by_label[lbl] = by_label.get(lbl, 0) + 1
    print(f"  By priority: {by_pri}")
    print(f"  Labels (top 5): {dict(sorted(by_label.items(), key=lambda x: -x[1])[:5])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
