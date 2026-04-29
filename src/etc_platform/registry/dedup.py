"""DEDUP registry tools.

Per CLAUDE.md ST-2 + CT 34 §6: every solution proposal must pass DEDUP
before being adopted. Registry holds normalized proposal hashes →
ecosystem reuse decisions, so subsequent projects benefit from prior
analysis.

Hash strategy
-------------
``proposal_hash`` = sha256 of canonical JSON form of
``{problem, solution_summary}`` lowercase + whitespace-normalized.
Similar proposals produce identical hashes; near-matches surface via
exact-token Jaccard scoring inside ``dedup_check``.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import uuid
from typing import Any

from etc_platform.registry.db import _get_conn, transaction, utc_iso

_VALID_DECISION = {"reuse", "build", "combine", "reject"}
_TOKEN_RE = re.compile(r"[\wÀ-ỹà-ỹ]+", re.UNICODE)


def _canonical_text(s: str) -> str:
    return " ".join(_TOKEN_RE.findall((s or "").lower()))


def _proposal_hash(proposal: dict[str, Any]) -> str:
    blob = json.dumps(
        {
            "problem": _canonical_text(proposal.get("problem", "")),
            "solution": _canonical_text(proposal.get("solution_summary", "")),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _jaccard(a: str, b: str) -> float:
    ta = set(_TOKEN_RE.findall(a.lower()))
    tb = set(_TOKEN_RE.findall(b.lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def dedup_check_impl(proposal: dict[str, Any], threshold: float = 0.5) -> dict[str, Any]:
    """Look up exact + similar prior proposals.

    Parameters
    ----------
    proposal
        Dict with at minimum ``problem`` and ``solution_summary`` strings.
        Optional: ``scope``, ``project_id``.
    threshold
        Jaccard similarity ≥ threshold → reported as ``similar``.

    Returns
    -------
    dict
        ``exact_match``: prior registry row when hash collision (or None).
        ``similar``: list of {row, similarity} pairs above threshold.
        ``proposal_hash``: computed hash for caller reference.
    """
    h = _proposal_hash(proposal)
    conn = _get_conn()
    exact = conn.execute(
        "SELECT * FROM dedup_registry WHERE proposal_hash = ? AND deleted_at IS NULL",
        (h,),
    ).fetchone()
    exact_dict = _row_to_dict(exact) if exact else None

    new_problem = _canonical_text(proposal.get("problem", ""))
    new_solution = _canonical_text(proposal.get("solution_summary", ""))
    similar = []
    rows = conn.execute(
        "SELECT * FROM dedup_registry WHERE deleted_at IS NULL ORDER BY registered_at DESC LIMIT 200"
    ).fetchall()
    for r in rows:
        if r["proposal_hash"] == h:
            continue
        prior = json.loads(r["proposal"])
        sim_p = _jaccard(new_problem, _canonical_text(prior.get("problem", "")))
        sim_s = _jaccard(new_solution, _canonical_text(prior.get("solution_summary", "")))
        sim = max(sim_p, sim_s)
        if sim >= threshold:
            similar.append({"row": _row_to_dict(r), "similarity": round(sim, 3)})
    similar.sort(key=lambda x: x["similarity"], reverse=True)
    return {
        "proposal_hash": h,
        "exact_match": exact_dict,
        "similar": similar[:10],
        "threshold": threshold,
    }


def dedup_register_impl(
    proposal: dict[str, Any],
    decision: str,
    rationale: str,
    ecosystem_ref: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Record a DEDUP decision so future projects see this analysis.

    Parameters
    ----------
    proposal
        Same shape used by ``dedup_check``.
    decision
        One of ``reuse``, ``build``, ``combine``, ``reject``.
    rationale
        Short Vietnamese justification — must explain WHY (CT 34 §6).
    ecosystem_ref
        When ``decision in {"reuse","combine"}``: which canonical platform
        is being referenced (e.g. ``"NDXP"``, ``"LGSP"``,
        ``"CSDLQG-DC"``).
    project_id
        Identifier of the project taking this decision (for traceability).
    """
    if decision not in _VALID_DECISION:
        raise ValueError(f"decision must be one of {sorted(_VALID_DECISION)}")
    if decision in {"reuse", "combine"} and not ecosystem_ref:
        raise ValueError("ecosystem_ref required when decision in {reuse, combine}")
    if not rationale or len(rationale.strip()) < 20:
        raise ValueError("rationale too short — explain WHY in ≥20 chars")

    h = _proposal_hash(proposal)
    rid = f"dedup-{uuid.uuid4().hex[:12]}"
    now = utc_iso()
    with transaction() as conn:
        conn.execute(
            """INSERT INTO dedup_registry
               (id, proposal_hash, proposal, ecosystem_ref, decision,
                rationale, project_id, registered_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(proposal_hash) DO UPDATE SET
                 ecosystem_ref=excluded.ecosystem_ref,
                 decision=excluded.decision,
                 rationale=excluded.rationale,
                 project_id=excluded.project_id,
                 registered_at=excluded.registered_at""",
            (
                rid,
                h,
                json.dumps(proposal, ensure_ascii=False),
                ecosystem_ref,
                decision,
                rationale,
                project_id,
                now,
            ),
        )
    return {"id": rid, "proposal_hash": h, "registered_at": now}


def _row_to_dict(row: Any) -> dict[str, Any]:
    d = dict(row)
    if "proposal" in d and isinstance(d["proposal"], str):
        with contextlib.suppress(json.JSONDecodeError):
            d["proposal"] = json.loads(d["proposal"])
    return d
