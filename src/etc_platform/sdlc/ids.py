"""ID parsing + uniqueness helpers (per CLAUDE.md CD-19 + ADR-003 D2).

Canonical ID formats:
    M-NNN     module ID (e.g. M-001)
    F-NNN     feature ID (e.g. F-001, F-009a sub-suffix allowed)
    H-NNN     hotfix ID (e.g. H-001)

Slugs in folder names: kebab-case ASCII (e.g. M-001-iam, F-001-vneid-link).

ID immutability: once committed, ID never changes. Slug CAN change via
``rename_module_slug`` MCP tool (D10-1) — but ID stays.
"""
from __future__ import annotations

import re

# Match M-NNN, F-NNN, H-NNN with optional sub-suffix on F-NNN (e.g. F-009a)
_MODULE_ID_RE = re.compile(r"^M-(\d{3,})$")
_FEATURE_ID_RE = re.compile(r"^F-(\d{3,})([a-z])?$")
_HOTFIX_ID_RE = re.compile(r"^H-(\d{3,})$")
_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


class IdKind:
    MODULE = "module"
    FEATURE = "feature"
    HOTFIX = "hotfix"


def is_valid_module_id(value: str) -> bool:
    return bool(_MODULE_ID_RE.match(value))


def is_valid_feature_id(value: str) -> bool:
    return bool(_FEATURE_ID_RE.match(value))


def is_valid_hotfix_id(value: str) -> bool:
    return bool(_HOTFIX_ID_RE.match(value))


def is_valid_slug(value: str) -> bool:
    """Slug rules: ASCII kebab-case, must start with letter, no trailing hyphen."""
    return bool(_SLUG_RE.match(value)) and not value.endswith("-")


def parse_id(value: str) -> tuple[str, int, str | None]:
    """Parse any ID; return (kind, numeric, sub_suffix).

    Raises ValueError if not a valid M-/F-/H- ID.
    """
    if m := _MODULE_ID_RE.match(value):
        return (IdKind.MODULE, int(m.group(1)), None)
    if m := _FEATURE_ID_RE.match(value):
        return (IdKind.FEATURE, int(m.group(1)), m.group(2))
    if m := _HOTFIX_ID_RE.match(value):
        return (IdKind.HOTFIX, int(m.group(1)), None)
    raise ValueError(f"Invalid ID: {value!r} (expected M-NNN, F-NNN, or H-NNN)")


def folder_name(entity_id: str, slug: str) -> str:
    """Compose canonical folder name: {ID}-{slug}.

    Example: folder_name("M-001", "iam") → "M-001-iam"
    """
    return f"{entity_id}-{slug}"


def split_folder_name(folder: str) -> tuple[str, str]:
    """Split folder name back into (id, slug).

    Raises ValueError on invalid format.
    """
    parts = folder.split("-", 2)
    if len(parts) < 3:
        raise ValueError(f"Invalid folder name: {folder!r}")
    entity_id = f"{parts[0]}-{parts[1]}"
    slug = parts[2]
    return (entity_id, slug)
