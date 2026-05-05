"""Optimistic version control for intel artifacts (per P0 §2.5).

Each entity (module-catalog.json, feature-catalog.json, _state.md, etc.)
carries a ``version`` integer in ``_meta.json``. Mutating tools accept an
optional ``expected_version``; if mismatched → reject (caller retry).

Rationale:
    File-based storage doesn't get DB transactions for free. Optimistic
    concurrency lets multiple writers (5 parallel agents) detect conflicts
    instead of last-write-wins corruption.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from etc_platform.sdlc.concurrency import atomic_write_text
from etc_platform.sdlc.errors import VersionConflictError


def meta_path(workspace_path: Path) -> Path:
    """Canonical _meta.json location."""
    return workspace_path / "docs" / "intel" / "_meta.json"


def read_meta(workspace_path: Path) -> dict[str, Any]:
    """Read _meta.json, returning empty skeleton if absent."""
    p = meta_path(workspace_path)
    if not p.exists():
        return _empty_meta()
    return json.loads(p.read_text(encoding="utf-8"))


def get_artifact_version(meta: dict[str, Any], artifact_name: str) -> int:
    """Return current version of artifact (0 if not yet tracked)."""
    artifacts = meta.get("artifacts", {})
    entry = artifacts.get(artifact_name, {})
    return int(entry.get("version", 0))


def assert_version(
    meta: dict[str, Any],
    artifact_name: str,
    expected_version: int | None,
) -> int:
    """Assert expected_version matches stored version.

    Args:
        meta: _meta.json content (read via read_meta).
        artifact_name: e.g. "feature-catalog.json".
        expected_version: caller's last-known version. None = skip check.

    Returns:
        Current stored version.

    Raises:
        VersionConflictError: expected_version doesn't match stored.
    """
    current = get_artifact_version(meta, artifact_name)
    if expected_version is not None and expected_version != current:
        raise VersionConflictError(
            f"Version conflict on {artifact_name}: expected {expected_version}, current {current}",
            details={
                "artifact": artifact_name,
                "expected": expected_version,
                "current": current,
            },
            fix_hint="Re-read artifact, retry with current version.",
        )
    return current


def bump_artifact(
    meta: dict[str, Any],
    artifact_name: str,
    *,
    content: bytes | str,
    producer: str = "etc-platform/sdlc",
    timestamp: str | None = None,
) -> int:
    """Increment version + update hash + timestamp for artifact in meta dict.

    Mutates ``meta`` in place. Returns new version number.
    """
    if isinstance(content, str):
        content_bytes = content.encode("utf-8")
    else:
        content_bytes = content

    sha256 = hashlib.sha256(content_bytes).hexdigest()
    artifacts = meta.setdefault("artifacts", {})
    entry = artifacts.setdefault(artifact_name, {})
    new_version = int(entry.get("version", 0)) + 1
    entry["version"] = new_version
    entry["content_hash"] = f"sha256:{sha256}"
    entry["last_modified"] = timestamp or _utc_iso_now()
    entry["last_producer"] = producer
    return new_version


def write_meta(workspace_path: Path, meta: dict[str, Any]) -> None:
    """Atomic write _meta.json."""
    p = meta_path(workspace_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(meta, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    atomic_write_text(p, content)


def _empty_meta() -> dict[str, Any]:
    """Skeleton meta for fresh workspace."""
    return {
        "schema_version": "1.0",
        "default_reuse_mode": "reuse_if_fresh",
        "artifacts": {},
    }


def _utc_iso_now() -> str:
    """Current UTC ISO-8601 timestamp."""
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
