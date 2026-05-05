"""Workspace path validation (per P0 §2.1).

All SDLC tools that accept ``workspace_path`` must validate it server-side
to prevent accidental writes outside controlled tree (security guard against
path traversal + writes into Documents/Downloads/etc).

Mandatory checks:
    1. Absolute path
    2. Resolves to existing directory
    3. Normalized (no .., no symlink escape after resolve)
    4. Contains marker file (.git/ OR AGENTS.md OR CLAUDE.md)
    5. Writes confined to workspace_path/docs/** OR
       workspace_path/{apps,services,libs,packages,tools}/**
    6. No unexpanded environment variables (~, $, ${VAR})
"""
from __future__ import annotations

import os
from pathlib import Path

from etc_platform.sdlc.errors import InvalidWorkspaceError

_MARKER_FILES = (".git", "AGENTS.md", "CLAUDE.md", "package.json", "pyproject.toml", "go.mod")
_ALLOWED_WRITE_PREFIXES = ("docs", "apps", "services", "libs", "packages", "tools")


def validate_workspace_path(workspace_path: str | Path) -> Path:
    """Validate workspace_path; return normalized Path.

    Raises InvalidWorkspaceError on any violation per P0 §2.1.
    """
    if not workspace_path:
        raise InvalidWorkspaceError(
            "workspace_path is empty",
            details={"reason": "empty"},
        )

    raw = str(workspace_path)

    # Reject unexpanded env vars + ~
    if "~" in raw or "$" in raw or "${" in raw:
        raise InvalidWorkspaceError(
            "workspace_path contains unexpanded shell variables",
            details={"reason": "env_var_unexpanded", "value": raw},
            fix_hint="Caller must expand ~ via Path.expanduser() and $VAR via os.path.expandvars().",
        )

    p = Path(raw)

    # Must be absolute
    if not p.is_absolute():
        raise InvalidWorkspaceError(
            "workspace_path must be absolute",
            details={"reason": "not_absolute", "value": raw},
            fix_hint="Pass absolute path (e.g. /home/user/project or C:/Users/.../project).",
        )

    # Resolve symlinks + ..
    try:
        resolved = p.resolve(strict=True)
    except FileNotFoundError as exc:
        raise InvalidWorkspaceError(
            "workspace_path does not exist",
            details={"reason": "not_exists", "value": raw},
        ) from exc
    except OSError as exc:
        raise InvalidWorkspaceError(
            f"workspace_path resolution failed: {exc}",
            details={"reason": "resolve_failed", "value": raw, "os_error": str(exc)},
        ) from exc

    # Must be a directory
    if not resolved.is_dir():
        raise InvalidWorkspaceError(
            "workspace_path is not a directory",
            details={"reason": "not_directory", "value": str(resolved)},
        )

    # Marker check (avoid writes into ~/Documents accidentally)
    if not _has_marker(resolved):
        raise InvalidWorkspaceError(
            "workspace_path missing marker file",
            details={
                "reason": "no_marker",
                "value": str(resolved),
                "expected_one_of": list(_MARKER_FILES),
            },
            fix_hint=(
                "Workspace must contain at least one marker file: "
                f"{', '.join(_MARKER_FILES)}. Run scaffold_workspace first OR "
                "verify path is correct project root."
            ),
        )

    return resolved


def _has_marker(path: Path) -> bool:
    """Return True if any marker file exists in path."""
    return any((path / marker).exists() for marker in _MARKER_FILES)


def assert_write_confined(workspace_path: Path, target_path: Path) -> None:
    """Assert target_path is within allowed write prefixes under workspace_path.

    Raises InvalidWorkspaceError if target_path attempts to write outside
    workspace_path/{docs|apps|services|libs|packages|tools}/**.

    Args:
        workspace_path: Already-validated absolute path.
        target_path: Path to be written (relative or absolute).
    """
    # Normalize target to absolute under workspace
    if not target_path.is_absolute():
        target_path = (workspace_path / target_path).resolve()
    else:
        target_path = target_path.resolve()

    # Must be under workspace_path
    try:
        rel = target_path.relative_to(workspace_path)
    except ValueError as exc:
        raise InvalidWorkspaceError(
            "Target path escapes workspace boundary",
            details={
                "reason": "traversal_attempt",
                "workspace": str(workspace_path),
                "target": str(target_path),
            },
            fix_hint="All writes must be confined to workspace_path subtree.",
        ) from exc

    # First path component must be in allowed list
    if not rel.parts:
        raise InvalidWorkspaceError(
            "Target path is workspace root itself",
            details={"reason": "root_write", "target": str(target_path)},
        )

    top_dir = rel.parts[0]
    # Allow root-level config files (AGENTS.md, .gitignore, package.json, etc.)
    # Only enforce subtree restriction for nested writes.
    if len(rel.parts) > 1 and top_dir not in _ALLOWED_WRITE_PREFIXES:
        raise InvalidWorkspaceError(
            f"Target path's top dir '{top_dir}' not in allowed list",
            details={
                "reason": "disallowed_prefix",
                "target": str(target_path),
                "top_dir": top_dir,
                "allowed": list(_ALLOWED_WRITE_PREFIXES),
            },
            fix_hint=(
                f"Writes restricted to: {', '.join(_ALLOWED_WRITE_PREFIXES)}/** "
                "or workspace-root config files (AGENTS.md, .gitignore, etc.)."
            ),
        )


def expand_path(raw: str) -> str:
    """Expand ~ and environment variables. Caller-side helper.

    Server-side validation rejects unexpanded paths; this helper is for
    callers (skill code) to pre-process before calling MCP tools.
    """
    return os.path.expandvars(os.path.expanduser(raw))
