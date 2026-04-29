"""KB (Knowledge Base) tools.

Backed by ``kb_entries`` table. Entries are owned by their contributor;
``kb_save`` upserts when ``id`` matches existing row. Soft-delete only —
KB-1/KB-3 require traceability of past entries.

Frontmatter contract per CLAUDE.md KB-1:
    domain, last_verified, confidence, sources, tags
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any

from etc_platform.registry.db import _get_conn, transaction, utc_iso

_VALID_CONFIDENCE = {"high", "medium", "low", "manual"}
_DEFAULT_MAX_AGE = 90  # KB-2: <90 days fresh


def _stable_id(domain: str, title: str) -> str:
    """Deterministic id from (domain, title) so repeated saves upsert."""
    digest = hashlib.sha256(f"{domain}::{title}".encode()).hexdigest()[:16]
    return f"kb-{digest}"


def _days_ago(iso_date: str) -> int:
    try:
        d = date.fromisoformat(iso_date[:10])
    except ValueError:
        return 9999
    return (datetime.now(UTC).date() - d).days


def kb_query_impl(
    domain: str | None = None,
    max_age_days: int = _DEFAULT_MAX_AGE,
    tags: list[str] | None = None,
    include_stale: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """Search KB. Returns active (non-deleted) entries matching filters.

    Parameters
    ----------
    domain
        Exact domain match (e.g. ``"ecosystem"``, ``"legal"``, ``"ct34"``).
    max_age_days
        Filter to entries with ``last_verified`` within this many days.
        Per KB-2: <90 fresh, 90-180 flag, >180 verify required.
    tags
        Optional tag filter; entry matches if it contains ANY of the given
        tags (OR semantics).
    include_stale
        If True, include entries beyond ``max_age_days`` with a ``stale: true``
        marker.
    limit
        Max rows returned (default 50).
    """
    conn = _get_conn()
    sql = "SELECT * FROM kb_entries WHERE deleted_at IS NULL"
    params: list[Any] = []
    if domain:
        sql += " AND domain = ?"
        params.append(domain)
    sql += " ORDER BY last_verified DESC LIMIT ?"
    params.append(limit * 3)  # over-fetch then post-filter

    rows = conn.execute(sql, params).fetchall()
    entries: list[dict[str, Any]] = []
    for r in rows:
        age = _days_ago(r["last_verified"])
        is_stale = age > max_age_days
        if is_stale and not include_stale:
            continue
        row_tags = json.loads(r["tags"])
        if tags and not (set(row_tags) & set(tags)):
            continue
        entries.append(
            {
                "id": r["id"],
                "domain": r["domain"],
                "title": r["title"],
                "body": r["body"],
                "tags": row_tags,
                "sources": json.loads(r["sources"]),
                "confidence": r["confidence"],
                "last_verified": r["last_verified"],
                "age_days": age,
                "stale": is_stale,
                "contributor": r["contributor"],
            }
        )
        if len(entries) >= limit:
            break
    return {
        "entries": entries,
        "total": len(entries),
        "filters": {
            "domain": domain,
            "max_age_days": max_age_days,
            "tags": tags,
            "include_stale": include_stale,
            "limit": limit,
        },
    }


def kb_save_impl(
    domain: str,
    title: str,
    body: str,
    tags: list[str],
    sources: list[str],
    confidence: str,
    last_verified: str | None = None,
    contributor: str = "unknown",
    overwrite_if_id_exists: bool = True,
) -> dict[str, Any]:
    """Insert or upsert a KB entry.

    Per KB-3 (no duplicate), id is deterministic on (domain, title) — repeated
    saves upsert into the same row by default. Set
    ``overwrite_if_id_exists=False`` to fail loudly when a duplicate is
    detected.
    """
    if confidence not in _VALID_CONFIDENCE:
        raise ValueError(f"confidence must be one of {sorted(_VALID_CONFIDENCE)}")
    if last_verified is None:
        last_verified = date.today().isoformat()

    entry_id = _stable_id(domain, title)
    now = utc_iso()
    with transaction() as conn:
        existing = conn.execute("SELECT id FROM kb_entries WHERE id = ?", (entry_id,)).fetchone()
        if existing and not overwrite_if_id_exists:
            raise ValueError(
                f"KB entry exists for ({domain}, {title}); pass "
                f"overwrite_if_id_exists=True to update."
            )
        if existing:
            conn.execute(
                """UPDATE kb_entries SET body=?, tags=?, sources=?, confidence=?,
                          last_verified=?, updated_at=?, contributor=?
                   WHERE id=?""",
                (
                    body,
                    json.dumps(tags),
                    json.dumps(sources),
                    confidence,
                    last_verified,
                    now,
                    contributor,
                    entry_id,
                ),
            )
            action = "updated"
        else:
            conn.execute(
                """INSERT INTO kb_entries
                   (id, domain, title, body, tags, sources, confidence,
                    last_verified, created_at, updated_at, contributor)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    entry_id,
                    domain,
                    title,
                    body,
                    json.dumps(tags),
                    json.dumps(sources),
                    confidence,
                    last_verified,
                    now,
                    now,
                    contributor,
                ),
            )
            action = "created"
    return {"id": entry_id, "action": action, "saved_at": now}
