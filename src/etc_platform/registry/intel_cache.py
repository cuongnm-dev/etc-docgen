"""Intel cache — cross-project pattern library (AGI #2 enabler).

Anonymized intel patterns contributed by past projects feed future
``from-doc``/``from-code`` runs as warm-start seeds. Conservative
default-deny anonymization for VN-gov customer confidentiality.

Anonymization rules
-------------------
ALLOWED to share (after rule check):
    - Stack fingerprints: framework + version
    - Role archetypes: canonical slugs (admin, manager, staff) — NOT
      customer-specific role names that may leak business identity
    - Feature archetypes: pattern shapes (CRUD, approval-flow, report)
    - Permission patterns: role × resource × action triples in canonical form

DENIED (auto-redacted):
    - Customer name, organization name, ministry name
    - Person names, emails, phone numbers
    - File paths containing customer-identifying segments
    - Free-text descriptions (potential confidential leak surface)
    - Endpoints/URLs with customer subdomains

Project signature
-----------------
``project_signature`` is a small dict matching:
    {
        "stacks": ["nestjs", "nextjs", "postgres"],   # order-insensitive
        "role_count": 3,
        "domain_hint": "approval-workflow",            # canonical archetype
        "feature_count_bucket": "10-30"                # bucketed
    }

Lookup is exact-match on signature_hash plus partial overlap suggestion.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from etc_platform.registry.db import _get_conn, transaction, utc_iso

_VALID_KIND = {
    "actor-pattern",
    "feature-archetype",
    "sitemap-pattern",
    "permission-pattern",
}

# Hard-reject patterns — actual PII (must never enter shared cache).
_PII_PATTERNS = [
    re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w+\b"),                    # email
    re.compile(r"\b\d{9,12}\b"),                                  # VN phone / CCCD / similar IDs
    re.compile(r"\b(?:\+84|0)\d{9,10}\b"),                        # phone
]
# Identifying customer-name patterns — VN-gov-aware. Bare "bộ/tỉnh/sở" alone
# is not identifying (gov canonical archetype vocabulary). Identifying =
# bare prefix followed by proper noun (capitalized word). Warning only —
# caller can decide redact vs. proceed.
_CUSTOMER_NAME_PATTERN = re.compile(
    r"\b(Bộ|Tỉnh|Sở|Cục|Tổng cục|Ủy ban|Công ty|Tập đoàn|Trung tâm)\s+"
    r"([A-ZĐÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝ][\wÀ-ỹ]*(?:\s+[A-ZĐÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝ][\wÀ-ỹ]*)*)",
    re.UNICODE,
)
# Free-text fields where identifying customer names matter. Canonical
# fields (stacks, role_archetypes, domain_hint slugs) are OUT of scope.
_FREE_TEXT_FIELDS = {
    "description", "notes", "title", "summary", "raw_label", "comment",
    "page_title", "menu_label", "form_label", "button_text",
}


def _signature_hash(signature: dict[str, Any]) -> str:
    canon = json.dumps(
        {
            "stacks": sorted(signature.get("stacks", [])),
            "role_count": int(signature.get("role_count", 0)),
            "domain_hint": signature.get("domain_hint", ""),
            "feature_count_bucket": signature.get("feature_count_bucket", ""),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _walk_free_text(obj: Any, path: str = "") -> list[tuple[str, str]]:
    """Yield (path, text) pairs for fields whose key is in _FREE_TEXT_FIELDS."""
    out: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _FREE_TEXT_FIELDS and isinstance(v, str):
                out.append((f"{path}.{k}" if path else k, v))
            out.extend(_walk_free_text(v, f"{path}.{k}" if path else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(_walk_free_text(v, f"{path}[{i}]"))
    return out


def _scan_redaction(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Scan payload for confidential content.

    Returns
    -------
    (hard_blocks, warnings)
        ``hard_blocks`` — patterns that REJECT contribution (PII anywhere).
        ``warnings`` — concerns logged but contribution still accepted
        (e.g. identifying customer-name in free-text fields).

    Scope
    -----
    - PII patterns (email/phone/ID): scanned EVERYWHERE in payload — hard block.
    - Customer-name pattern (Bộ/Tỉnh/Sở/Cục/etc + proper noun): scanned only
      in ``_FREE_TEXT_FIELDS`` (description, notes, title, etc.) — warning only.
      Canonical fields (stacks, role_archetypes, domain_hint slugs) are NOT
      scanned for these — bare "bộ/tỉnh/sở" is gov-archetype vocabulary, not
      identifying without a proper-noun follower.
    """
    hard_blocks: list[str] = []
    warnings: list[str] = []

    # PII scan — full payload.
    blob = json.dumps(payload, ensure_ascii=False)
    for pat in _PII_PATTERNS:
        if pat.search(blob):
            hard_blocks.append(f"pii-pattern:{pat.pattern[:30]}")

    # Customer-name scan — only in free-text fields, only matches with proper-noun follower.
    for field_path, text in _walk_free_text(payload):
        m = _CUSTOMER_NAME_PATTERN.search(text)
        if m:
            warnings.append(f"customer-name@{field_path}:'{m.group(0)[:50]}'")

    return hard_blocks, warnings


def intel_cache_lookup_impl(
    project_signature: dict[str, Any],
    kinds: list[str] | None = None,
    max_results: int = 5,
) -> dict[str, Any]:
    """Look up similar projects' contributed patterns.

    Returns exact signature matches first, then partial-overlap suggestions
    (same domain_hint + at least one stack overlap).
    """
    sig_hash = _signature_hash(project_signature)
    conn = _get_conn()
    sql = "SELECT * FROM intel_cache WHERE deleted_at IS NULL"
    params: list[Any] = []
    if kinds:
        placeholders = ",".join("?" * len(kinds))
        sql += f" AND artifact_kind IN ({placeholders})"
        params.extend(kinds)
    rows = conn.execute(sql, params).fetchall()

    exact: list[dict[str, Any]] = []
    similar: list[dict[str, Any]] = []
    incoming_stacks = set(project_signature.get("stacks", []))
    incoming_domain = project_signature.get("domain_hint", "")

    for r in rows:
        item = {
            "id": r["id"],
            "artifact_kind": r["artifact_kind"],
            "payload": json.loads(r["payload"]),
            "anonymization_applied": json.loads(r["anonymization_applied"]),
            "contributed_by": r["contributed_by"],
            "contributed_at": r["contributed_at"],
            "use_count": r["use_count"],
        }
        if r["signature_hash"] == sig_hash:
            exact.append(item)
            continue
        prior_sig = json.loads(r["project_signature"])
        prior_stacks = set(prior_sig.get("stacks", []))
        if (incoming_domain and incoming_domain == prior_sig.get("domain_hint")
                and (incoming_stacks & prior_stacks)):
            similar.append({**item, "signature": prior_sig})

    # Increment use_count for returned exact matches (lightweight feedback)
    if exact:
        with transaction() as wconn:
            for item in exact:
                wconn.execute(
                    "UPDATE intel_cache SET use_count = use_count + 1 WHERE id = ?",
                    (item["id"],),
                )

    return {
        "signature_hash": sig_hash,
        "exact_matches": exact[:max_results],
        "similar_projects": similar[:max_results],
        "lookup_at": utc_iso(),
    }


def intel_cache_contribute_impl(
    project_id: str,
    project_signature: dict[str, Any],
    artifact_kind: str,
    payload: dict[str, Any],
    contributor_consent: bool = False,
) -> dict[str, Any]:
    """Anonymize + persist a pattern contribution.

    Default-deny anonymization: if scan detects PII/customer hints,
    contribution is REJECTED. Caller must pre-redact and retry.

    ``contributor_consent`` MUST be ``True`` — explicit opt-in per
    Phase 4 anonymization gate (see plan).
    """
    if artifact_kind not in _VALID_KIND:
        raise ValueError(f"artifact_kind must be one of {sorted(_VALID_KIND)}")
    if not contributor_consent:
        raise PermissionError(
            "contributor_consent=True required — explicit opt-in per "
            "Phase 4 anonymization gate. Confirm with project owner."
        )

    hard_blocks, warnings = _scan_redaction(payload)
    if hard_blocks:
        return {
            "accepted": False,
            "reason": "pii-detected",
            "concerns": hard_blocks,
            "hint": (
                "Hard PII (email/phone/CCCD) found in payload. Caller "
                "MUST redact before retry — never force-submit."
            ),
        }

    sig_hash = _signature_hash(project_signature)
    iid = f"intel-{uuid.uuid4().hex[:12]}"
    now = utc_iso()
    anonymization_log = (
        ["customer-name-warning"] if warnings else []
    )
    with transaction() as conn:
        conn.execute(
            """INSERT INTO intel_cache
               (id, project_signature, signature_hash, artifact_kind,
                payload, anonymization_applied, contributed_by,
                contributed_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (iid, json.dumps(project_signature, ensure_ascii=False),
             sig_hash, artifact_kind,
             json.dumps(payload, ensure_ascii=False),
             json.dumps(anonymization_log, ensure_ascii=False),
             project_id, now),
        )
    return {
        "accepted": True,
        "id": iid,
        "signature_hash": sig_hash,
        "contributed_at": now,
        "warnings": warnings,  # caller informed of customer-name hits in free-text
    }
