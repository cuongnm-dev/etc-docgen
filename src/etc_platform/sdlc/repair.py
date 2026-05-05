"""autofix tool — repair structure violations with safeguards.

Per p0 §3.8 + ADR-003 D7. Reads verify findings (P0.7 dependency) and
applies fixes per fix_class. Some fixes destructive → require explicit
``confirm_destructive`` flag.

Initial implementation focuses on classes that don't depend on verify
output (orphan-removal works standalone). Schema migrations + collision
resolution defer to P0.7 once verify exists.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

from etc_platform.sdlc.concurrency import detect_orphan_tmps, workspace_lock
from etc_platform.sdlc.errors import (
    DestructiveNotConfirmedError,
    InvalidInputError,
    success_response,
)
from etc_platform.sdlc.path_validation import validate_workspace_path

_VALID_FIX_CLASSES = {
    "orphan-removal",
    "missing-scaffold",
    "schema-migrate",
    "id-collision-resolve",
    "cross-ref-repair",
    "all",
}

_DESTRUCTIVE_CLASSES = {"orphan-removal", "id-collision-resolve"}


def autofix_impl(
    workspace_path: str,
    fix_classes: list[str],
    *,
    dry_run: bool = True,
    confirm_destructive: bool = False,
) -> dict[str, Any]:
    """Repair workspace per requested fix classes.

    Args:
        fix_classes: Subset of {orphan-removal, missing-scaffold, schema-migrate,
                     id-collision-resolve, cross-ref-repair, all}.
        dry_run: If True, return fix plan only (no mutations).
        confirm_destructive: Required True for destructive classes when not dry_run.

    Returns:
        { fixes_planned[], fixes_applied[], unfixable[], requires_user_input[] }
    """
    ws = validate_workspace_path(workspace_path)

    if not fix_classes:
        raise InvalidInputError(
            "fix_classes is empty",
            details={"fix_classes": fix_classes},
        )

    invalid = [c for c in fix_classes if c not in _VALID_FIX_CLASSES]
    if invalid:
        raise InvalidInputError(
            f"Invalid fix_classes: {invalid}",
            details={"invalid": invalid, "valid": sorted(_VALID_FIX_CLASSES)},
        )

    # Expand 'all'
    classes: set[str] = set(fix_classes)
    if "all" in classes:
        classes = _VALID_FIX_CLASSES - {"all"}

    # Check destructive confirm
    if not dry_run and not confirm_destructive:
        destructive = classes & _DESTRUCTIVE_CLASSES
        if destructive:
            raise DestructiveNotConfirmedError(
                f"Destructive fix_classes require confirm_destructive=true: {sorted(destructive)}",
                details={"destructive_classes": sorted(destructive)},
                fix_hint="Set confirm_destructive=true OR use dry_run=true to preview.",
            )

    fixes_planned: list[dict[str, Any]] = []
    fixes_applied: list[dict[str, Any]] = []
    unfixable: list[dict[str, Any]] = []
    requires_user_input: list[dict[str, Any]] = []

    with workspace_lock(str(ws)) if not dry_run else _nullctx():
        if "orphan-removal" in classes:
            _plan_orphan_removal(ws, fixes_planned, fixes_applied, dry_run=dry_run)

        if "missing-scaffold" in classes:
            unfixable.append(
                {
                    "class": "missing-scaffold",
                    "reason": "Requires verify(scopes=['structure', 'completeness']) to identify gaps. "
                    "Implementation deferred to P0.7.",
                }
            )

        if "schema-migrate" in classes:
            unfixable.append(
                {
                    "class": "schema-migrate",
                    "reason": "Requires verify(scopes=['schemas']) + schema version detection. "
                    "Implementation deferred to P0.7.",
                }
            )

        if "id-collision-resolve" in classes:
            requires_user_input.append(
                {
                    "class": "id-collision-resolve",
                    "reason": "Manual decision needed: which colliding ID is canonical? "
                    "Will use verify(scopes=['id_uniqueness']) findings in P0.7.",
                }
            )

        if "cross-ref-repair" in classes:
            unfixable.append(
                {
                    "class": "cross-ref-repair",
                    "reason": "Requires verify(scopes=['cross_references']) for FK gap list. "
                    "Implementation deferred to P0.7.",
                }
            )

    return success_response(
        {
            "dry_run": dry_run,
            "fixes_planned": fixes_planned,
            "fixes_applied": fixes_applied,
            "unfixable": unfixable,
            "requires_user_input": requires_user_input,
        }
    )


# ---------------------------------------------------------------------------
# Fix-class implementations
# ---------------------------------------------------------------------------


def _plan_orphan_removal(
    ws: Path,
    fixes_planned: list[dict[str, Any]],
    fixes_applied: list[dict[str, Any]],
    *,
    dry_run: bool,
) -> None:
    """Find + remove .tmp files left from failed FileTransaction commits."""
    orphans = detect_orphan_tmps(ws, subdir="docs")
    for tmp in orphans:
        plan = {
            "class": "orphan-removal",
            "file": str(tmp.relative_to(ws)).replace("\\", "/"),
            "action": "delete",
        }
        fixes_planned.append(plan)
        if not dry_run:
            try:
                tmp.unlink()
                fixes_applied.append(plan)
            except OSError as exc:
                plan["error"] = str(exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def _nullctx():
    """Null context manager for dry_run path (no lock needed)."""
    yield
