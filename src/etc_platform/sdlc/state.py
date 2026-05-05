"""update_state — consolidated state mutation tool (5 ops via op discriminator).

Per p0 §3.9 + ADR-003 D10-3. Replaces 5 separate update_* tools with single
tool dispatching by ``op`` parameter. Caller passes only fields relevant
to chosen op.

Operations:
    field    — set non-locked frontmatter field via dot-path
    progress — append row to body Stage Progress table
    kpi      — mutate kpi metric (set/increment/append)
    log      — append entry to escalation/wave/audit log
    status   — atomic cross-file: update _state status + catalog
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from etc_platform.sdlc import intel_io as io
from etc_platform.sdlc.concurrency import FileTransaction, atomic_write_text, workspace_lock
from etc_platform.sdlc.errors import (
    ForbiddenError,
    InvalidInputError,
    NotFoundError,
    success_response,
)
from etc_platform.sdlc.frontmatter import (
    get_dotpath,
    read_frontmatter,
    serialize,
    set_dotpath,
    write_frontmatter,
)
from etc_platform.sdlc.path_validation import validate_workspace_path
from etc_platform.sdlc.versioning import bump_artifact, read_meta, write_meta

_VALID_OPS = ("field", "progress", "kpi", "log", "status")
_VALID_LOG_KINDS = ("escalation", "wave", "audit")
_VALID_KPI_OPS = ("set", "increment", "append")
_VALID_STATUSES = ("proposed", "in-progress", "blocked", "done")


def update_state_impl(
    workspace_path: str,
    file_path: str,
    op: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Update state file (frontmatter or body section) per ``op``."""
    ws = validate_workspace_path(workspace_path)

    if op not in _VALID_OPS:
        raise InvalidInputError(
            f"Invalid op: {op!r} (expected one of {_VALID_OPS})",
            details={"op": op, "valid": list(_VALID_OPS)},
        )

    # Resolve target file
    target = ws / file_path if not Path(file_path).is_absolute() else Path(file_path)
    if not target.is_absolute():
        target = (ws / file_path).resolve()
    if not target.exists():
        raise NotFoundError(
            f"State file not found: {file_path}",
            details={"file_path": file_path, "resolved": str(target)},
        )

    expected_version = kwargs.get("expected_version")

    with workspace_lock(str(ws)):
        if op == "field":
            return _op_field(ws, target, kwargs, expected_version)
        if op == "progress":
            return _op_progress(ws, target, kwargs, expected_version)
        if op == "kpi":
            return _op_kpi(ws, target, kwargs, expected_version)
        if op == "log":
            return _op_log(ws, target, kwargs, expected_version)
        if op == "status":
            return _op_status(ws, target, kwargs, expected_version)

    raise InvalidInputError(f"Unhandled op: {op}", details={"op": op})


# ---------------------------------------------------------------------------
# op=field
# ---------------------------------------------------------------------------


def _op_field(
    ws: Path,
    target: Path,
    kwargs: dict[str, Any],
    expected_version: int | None,
) -> dict[str, Any]:
    """Set frontmatter field via dot-path. Enforces locked_fields[]."""
    field_path = kwargs.get("field_path")
    if not field_path:
        raise InvalidInputError(
            "op=field requires field_path",
            details={"missing": ["field_path"]},
        )
    if "field_value" not in kwargs:
        raise InvalidInputError(
            "op=field requires field_value",
            details={"missing": ["field_value"]},
        )
    field_value = kwargs["field_value"]

    fm, body = read_frontmatter(target)
    locked = fm.get("locked-fields", []) or []
    # Check both 'locked-fields' (markdown convention) and 'locked_fields'
    locked_alt = fm.get("locked_fields", []) or []
    all_locked = set(locked) | set(locked_alt)

    if field_path in all_locked:
        raise ForbiddenError(
            f"Field {field_path!r} is in locked_fields",
            details={"field_path": field_path, "locked_fields": sorted(all_locked)},
            fix_hint="Remove field from locked-fields list first, OR use a different field.",
        )

    old_value, new_value = set_dotpath(fm, field_path, field_value)
    fm["last-updated"] = _utc_now()
    write_frontmatter(target, fm, body)

    return success_response(
        {
            "file_path": str(target.relative_to(ws)).replace("\\", "/"),
            "op": "field",
            "field_path": field_path,
            "old_value": old_value,
            "new_value": new_value,
        }
    )


# ---------------------------------------------------------------------------
# op=progress
# ---------------------------------------------------------------------------

_PROGRESS_HEADER_RE = re.compile(r"^##\s+Stage\s+Progress\s*$", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\|.*\|\s*$", re.MULTILINE)


def _op_progress(
    ws: Path,
    target: Path,
    kwargs: dict[str, Any],
    expected_version: int | None,
) -> dict[str, Any]:
    """Append row to ``## Stage Progress`` markdown table."""
    stage = kwargs.get("stage")
    verdict = kwargs.get("verdict")
    artifact = kwargs.get("artifact", "")
    date = kwargs.get("date") or _utc_now_short()

    if not stage or not verdict:
        raise InvalidInputError(
            "op=progress requires stage + verdict",
            details={"missing": [k for k in ("stage", "verdict") if not kwargs.get(k)]},
        )

    fm, body = read_frontmatter(target)

    # Find table under "## Stage Progress" header
    new_body = _append_table_row(
        body,
        section_header="Stage Progress",
        cells=[stage, stage, verdict, artifact, date],
    )

    fm["last-updated"] = _utc_now()
    write_frontmatter(target, fm, new_body)

    return success_response(
        {
            "file_path": str(target.relative_to(ws)).replace("\\", "/"),
            "op": "progress",
            "stage": stage,
            "verdict": verdict,
            "artifact": artifact,
            "date": date,
        }
    )


def _append_table_row(body: str, *, section_header: str, cells: list[str]) -> str:
    """Append `| c1 | c2 | ... |` row at end of named markdown table.

    Strategy:
        1. Find line `## {section_header}`
        2. Find next markdown table (lines starting with `|`)
        3. Find last row of that table
        4. Insert new row after last row
    """
    lines = body.split("\n")
    section_idx = None
    for i, line in enumerate(lines):
        if line.strip().lower() == f"## {section_header}".lower():
            section_idx = i
            break

    if section_idx is None:
        # Section missing — append at end of body
        new_row = "| " + " | ".join(cells) + " |"
        return body.rstrip() + f"\n\n## {section_header}\n\n{new_row}\n"

    # Find table within section (between section_idx and next ## heading or end)
    table_start = None
    table_end = None
    next_section_idx = len(lines)
    for i in range(section_idx + 1, len(lines)):
        if lines[i].startswith("## "):
            next_section_idx = i
            break

    for i in range(section_idx + 1, next_section_idx):
        line = lines[i]
        if line.startswith("|"):
            if table_start is None:
                table_start = i
            table_end = i

    new_row = "| " + " | ".join(str(c) for c in cells) + " |"

    if table_start is None or table_end is None:
        # No table yet — insert one with header + separator + new row
        skeleton = (
            f"\n| # | Stage | Agent | Verdict | Artifact | Date |\n"
            f"|---|---|---|---|---|---|\n"
            f"{new_row}\n"
        )
        return "\n".join(lines[: section_idx + 1]) + skeleton + "\n".join(lines[section_idx + 1:])

    # Insert new row after table_end
    return "\n".join(lines[: table_end + 1]) + "\n" + new_row + "\n" + "\n".join(lines[table_end + 1:])


# ---------------------------------------------------------------------------
# op=kpi
# ---------------------------------------------------------------------------


def _op_kpi(
    ws: Path,
    target: Path,
    kwargs: dict[str, Any],
    expected_version: int | None,
) -> dict[str, Any]:
    """Mutate kpi metric in frontmatter."""
    metric = kwargs.get("metric")
    if not metric:
        raise InvalidInputError(
            "op=kpi requires metric",
            details={"missing": ["metric"]},
        )
    if "delta_value" not in kwargs:
        raise InvalidInputError(
            "op=kpi requires delta_value",
            details={"missing": ["delta_value"]},
        )
    delta = kwargs["delta_value"]
    kpi_op = kwargs.get("kpi_op", "set")
    if kpi_op not in _VALID_KPI_OPS:
        raise InvalidInputError(
            f"Invalid kpi_op: {kpi_op!r}",
            details={"kpi_op": kpi_op, "valid": list(_VALID_KPI_OPS)},
        )

    fm, body = read_frontmatter(target)
    kpi = fm.setdefault("kpi", {})

    metric_dotpath = f"kpi.{metric}"
    old = get_dotpath(fm, metric_dotpath)

    if kpi_op == "set":
        set_dotpath(fm, metric_dotpath, delta)
        new = delta
    elif kpi_op == "increment":
        try:
            new = (old or 0) + delta
        except TypeError as exc:
            raise InvalidInputError(
                f"Cannot increment non-numeric kpi {metric!r}: current={old!r}",
                details={"metric": metric, "current": old, "delta": delta},
            ) from exc
        set_dotpath(fm, metric_dotpath, new)
    else:  # append
        if old is None:
            new = [delta]
        elif isinstance(old, list):
            new = old + [delta]
        else:
            raise InvalidInputError(
                f"Cannot append to non-list kpi {metric!r}: current={old!r}",
                details={"metric": metric, "current_type": type(old).__name__},
            )
        set_dotpath(fm, metric_dotpath, new)

    fm["last-updated"] = _utc_now()
    write_frontmatter(target, fm, body)

    return success_response(
        {
            "file_path": str(target.relative_to(ws)).replace("\\", "/"),
            "op": "kpi",
            "metric": metric,
            "kpi_op": kpi_op,
            "old_value": old,
            "new_value": new,
        }
    )


# ---------------------------------------------------------------------------
# op=log
# ---------------------------------------------------------------------------


def _op_log(
    ws: Path,
    target: Path,
    kwargs: dict[str, Any],
    expected_version: int | None,
) -> dict[str, Any]:
    """Append entry to body log section (Escalation Log / Wave Tracker / Audit Log)."""
    log_kind = kwargs.get("log_kind")
    entry = kwargs.get("entry")
    if not log_kind:
        raise InvalidInputError(
            "op=log requires log_kind",
            details={"missing": ["log_kind"]},
        )
    if log_kind not in _VALID_LOG_KINDS:
        raise InvalidInputError(
            f"Invalid log_kind: {log_kind!r}",
            details={"log_kind": log_kind, "valid": list(_VALID_LOG_KINDS)},
        )
    if not entry or not isinstance(entry, dict):
        raise InvalidInputError(
            "op=log requires entry (dict)",
            details={"entry_type": type(entry).__name__},
        )

    section_header = {
        "escalation": "Escalation Log",
        "wave": "Wave Tracker",
        "audit": "Audit Log",
    }[log_kind]

    fm, body = read_frontmatter(target)
    cells = _entry_to_cells(log_kind, entry)
    new_body = _append_table_row(body, section_header=section_header, cells=cells)

    fm["last-updated"] = _utc_now()
    write_frontmatter(target, fm, new_body)

    return success_response(
        {
            "file_path": str(target.relative_to(ws)).replace("\\", "/"),
            "op": "log",
            "log_kind": log_kind,
            "appended": entry,
        }
    )


def _entry_to_cells(log_kind: str, entry: dict[str, Any]) -> list[str]:
    """Convert entry dict to ordered cells per log_kind."""
    if log_kind == "escalation":
        return [entry.get("date", _utc_now_short()), entry.get("item", ""), entry.get("decision", "")]
    if log_kind == "wave":
        return [
            str(entry.get("wave", "")),
            str(entry.get("tasks", "")),
            entry.get("dev_status", ""),
            entry.get("qa_status", ""),
        ]
    # audit
    return [
        entry.get("date", _utc_now_short()),
        entry.get("actor", ""),
        entry.get("action", ""),
        entry.get("note", ""),
    ]


# ---------------------------------------------------------------------------
# op=status (atomic cross-file)
# ---------------------------------------------------------------------------


def _op_status(
    ws: Path,
    target: Path,
    kwargs: dict[str, Any],
    expected_version: int | None,
) -> dict[str, Any]:
    """Atomic update _state.md status + matching catalog entry."""
    entity_id = kwargs.get("entity_id")
    new_status = kwargs.get("status")
    evidence = kwargs.get("evidence")

    if not entity_id or not new_status:
        raise InvalidInputError(
            "op=status requires entity_id + status",
            details={"missing": [k for k in ("entity_id", "status") if not kwargs.get(k)]},
        )
    if new_status not in _VALID_STATUSES:
        raise InvalidInputError(
            f"Invalid status: {new_status!r}",
            details={"status": new_status, "valid": list(_VALID_STATUSES)},
        )

    fm, body = read_frontmatter(target)
    old_status = fm.get("status")
    fm["status"] = new_status
    fm["last-updated"] = _utc_now()

    state_md_content = serialize(fm, body)

    # Determine catalog file based on entity_id prefix
    if entity_id.startswith("M-"):
        catalog_path = io.module_catalog_path(ws)
        catalog = io.read_module_catalog(ws)
        entity = io.find_module(catalog, entity_id)
        catalog_key = "module-catalog.json"
    elif entity_id.startswith("F-"):
        catalog_path = io.feature_catalog_path(ws)
        catalog = io.read_feature_catalog(ws)
        entity = io.find_feature(catalog, entity_id)
        catalog_key = "feature-catalog.json"
    else:
        # Hotfix or unknown — only update _state.md, no catalog
        atomic_write_text(target, state_md_content)
        return success_response(
            {
                "file_path": str(target.relative_to(ws)).replace("\\", "/"),
                "op": "status",
                "entity_id": entity_id,
                "old_status": old_status,
                "new_status": new_status,
                "catalog_updated": False,
            }
        )

    if not entity:
        raise NotFoundError(
            f"Entity {entity_id} not found in {catalog_key}",
            details={"entity_id": entity_id, "catalog": catalog_key},
        )

    entity["status"] = new_status
    if evidence:
        entity.setdefault("implementation_evidence", {}).update(evidence)

    catalog_content = io.serialize_json(catalog)

    # Atomic 2-file write
    tx = FileTransaction()
    tx.add(target, state_md_content)
    tx.add(catalog_path, catalog_content)
    tx.commit()

    # Bump catalog version
    meta = read_meta(ws)
    new_v = bump_artifact(
        meta,
        catalog_key,
        content=catalog_content,
        producer="etc-platform/update_state",
    )
    write_meta(ws, meta)

    return success_response(
        {
            "file_path": str(target.relative_to(ws)).replace("\\", "/"),
            "op": "status",
            "entity_id": entity_id,
            "old_status": old_status,
            "new_status": new_status,
            "catalog_updated": True,
            "new_catalog_version": new_v,
        }
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_now_short() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")
