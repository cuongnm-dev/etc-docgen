"""SQLite layer for etc-platform shared state.

Stores KB entries, DEDUP registry, intel cache, and observation log in a
single ``etc-platform.db`` under ``$ETC_PLATFORM_DATA_DIR``. WAL mode for
concurrent reads. Schema migrations are forward-only via integer
``schema_version`` user_version pragma.

Tables
------
- ``kb_entries``: Knowledge base entries (CT 34, ecosystem, legal refs).
- ``dedup_registry``: Solution proposals, ecosystem mappings (per ST-2).
- ``intel_cache``: Cross-project pattern library (anonymized).
- ``observation_log``: Tool invocation telemetry for AGI #5 (self-improving).

All writes update ``updated_at`` (ISO-8601 UTC). Soft-delete via
``deleted_at`` (NULL when active).
"""

from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

_DATA_DIR: Path = Path(
    os.environ.get("ETC_PLATFORM_REGISTRY_DIR")
    or os.environ.get("ETC_DOCGEN_REGISTRY_DIR")  # back-compat
    or os.environ.get("ETC_PLATFORM_DATA_DIR")
    or os.environ.get("ETC_DOCGEN_DATA_DIR")  # back-compat
    or "/data/registry"
)
_DB_PATH: Path = _DATA_DIR / "etc-platform.db"

# SQLite is single-file; one connection per thread is the simplest correct
# concurrency model. fastmcp may dispatch tools across threads.
_LOCAL = threading.local()

SCHEMA_VERSION = 1

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS kb_entries (
    id            TEXT PRIMARY KEY,
    domain        TEXT NOT NULL,
    title         TEXT NOT NULL,
    body          TEXT NOT NULL,
    tags          TEXT NOT NULL DEFAULT '[]',         -- JSON array
    sources       TEXT NOT NULL DEFAULT '[]',         -- JSON array
    confidence    TEXT NOT NULL CHECK (confidence IN ('high','medium','low','manual')),
    last_verified TEXT NOT NULL,                       -- ISO-8601 date
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    deleted_at    TEXT,
    contributor   TEXT NOT NULL DEFAULT 'unknown'
);
CREATE INDEX IF NOT EXISTS idx_kb_domain ON kb_entries(domain) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_kb_verified ON kb_entries(last_verified) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS dedup_registry (
    id            TEXT PRIMARY KEY,
    proposal_hash TEXT NOT NULL UNIQUE,                -- normalized hash of proposal description
    proposal      TEXT NOT NULL,                       -- JSON: {summary, problem, solution, scope}
    ecosystem_ref TEXT,                                -- e.g. "NDXP", "LGSP", "CSDLQG-DC"
    decision      TEXT NOT NULL CHECK (decision IN ('reuse','build','combine','reject')),
    rationale     TEXT NOT NULL,
    project_id    TEXT,                                -- which project registered this
    registered_at TEXT NOT NULL,
    deleted_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_dedup_hash ON dedup_registry(proposal_hash) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_dedup_eco ON dedup_registry(ecosystem_ref) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS intel_cache (
    id              TEXT PRIMARY KEY,
    project_signature TEXT NOT NULL,                   -- JSON: {stack, role_archetypes, domain_hint}
    signature_hash  TEXT NOT NULL,                     -- sha256 of canonical signature
    artifact_kind   TEXT NOT NULL CHECK (artifact_kind IN ('actor-pattern','feature-archetype','sitemap-pattern','permission-pattern')),
    payload         TEXT NOT NULL,                     -- JSON, anonymized
    anonymization_applied TEXT NOT NULL DEFAULT '[]', -- JSON array of redaction kinds applied
    contributed_by  TEXT NOT NULL,                     -- project_id (anonymized to slug-only)
    contributed_at  TEXT NOT NULL,
    use_count       INTEGER NOT NULL DEFAULT 0,
    deleted_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_intel_sig ON intel_cache(signature_hash) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_intel_kind ON intel_cache(artifact_kind) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS observation_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    tool        TEXT NOT NULL,
    args_summary TEXT,                                 -- truncated/sanitized
    result_size INTEGER,
    elapsed_ms  INTEGER,
    success     INTEGER NOT NULL CHECK (success IN (0,1)),
    error_kind  TEXT
);
CREATE INDEX IF NOT EXISTS idx_obs_tool_time ON observation_log(tool, timestamp);
"""


def _ensure_data_dir() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


def _new_connection() -> sqlite3.Connection:
    _ensure_data_dir()
    conn = sqlite3.connect(_DB_PATH, isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current < SCHEMA_VERSION:
        conn.executescript(_SCHEMA_V1)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _get_conn() -> sqlite3.Connection:
    conn = getattr(_LOCAL, "conn", None)
    if conn is None:
        conn = _new_connection()
        _migrate(conn)
        _LOCAL.conn = conn
    return conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Yield a transactional connection. Commit on success, rollback on error."""
    conn = _get_conn()
    conn.execute("BEGIN")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def reset_for_tests() -> None:
    """Test-only: close cached conn so a fresh DB at new path is picked up."""
    conn = getattr(_LOCAL, "conn", None)
    if conn is not None:
        conn.close()
        _LOCAL.conn = None


def db_stats() -> dict:
    """Return row counts per table for health/observability."""
    conn = _get_conn()
    counts = {}
    for table in ("kb_entries", "dedup_registry", "intel_cache", "observation_log"):
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE COALESCE(deleted_at,'') = ''"
            if table != "observation_log"
            else f"SELECT COUNT(*) AS n FROM {table}"
        ).fetchone()
        counts[table] = row["n"] if row else 0
    counts["schema_version"] = conn.execute("PRAGMA user_version").fetchone()[0]
    counts["db_path"] = str(_DB_PATH)
    return counts
