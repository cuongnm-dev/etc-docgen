"""Path resolution tool — replace ALL glob fallback in skills.

Per p0 §3.7 + ADR-003 D8 (CD-8 v3 forbids skill glob `docs/{modules,features}/**`).
Read-only; no lock acquired.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from etc_platform.sdlc import intel_io as io
from etc_platform.sdlc.errors import InvalidInputError, NotFoundError, success_response
from etc_platform.sdlc.path_validation import validate_workspace_path

_VALID_KINDS = {"module", "feature", "hotfix"}


def resolve_path_impl(
    workspace_path: str,
    kind: str,
    id: str,
    include_metadata: bool = False,
) -> dict[str, Any]:
    """Resolve M-NNN/F-NNN/H-NNN to canonical filesystem path.

    Looks up appropriate map (module-map.yaml / feature-map.yaml). Falls
    back to id-aliases.json for legacy ID renames. Returns NOT_FOUND error
    if neither map nor alias resolves.

    Performance: read-only, ~50ms for typical workspace (<1MB maps).
    """
    ws = validate_workspace_path(workspace_path)

    if kind not in _VALID_KINDS:
        raise InvalidInputError(
            f"Invalid kind: {kind!r} (expected one of {sorted(_VALID_KINDS)})",
            details={"kind": kind},
        )

    if kind == "module":
        return _resolve_module(ws, id, include_metadata)
    if kind == "feature":
        return _resolve_feature(ws, id, include_metadata)
    return _resolve_hotfix(ws, id, include_metadata)


def _resolve_module(ws: Path, module_id: str, include_metadata: bool) -> dict[str, Any]:
    """Resolve M-NNN via module-map.yaml + alias fallback."""
    map_data = io.read_module_map(ws)
    entry = map_data.get("modules", {}).get(module_id)

    # Alias fallback
    resolved_via_alias = False
    if not entry:
        aliases = io.read_id_aliases(ws)
        for rename in aliases.get("id_renames", []):
            if rename.get("from") == module_id:
                canonical = rename.get("to")
                entry = map_data.get("modules", {}).get(canonical)
                if entry:
                    resolved_via_alias = True
                    module_id = canonical
                    break

    if not entry:
        raise NotFoundError(
            f"Module {module_id!r} not found in map or aliases",
            details={"module_id": module_id, "kind": "module"},
            fix_hint="Verify ID exists; check id-aliases.json for legacy renames.",
        )

    abs_path = ws / entry["path"]
    data: dict[str, Any] = {
        "id": module_id,
        "kind": "module",
        "path": str(abs_path).replace("\\", "/"),
        "relative_path": entry["path"],
        "exists": abs_path.exists(),
        "resolved_via_alias": resolved_via_alias,
    }

    if include_metadata:
        catalog = io.read_module_catalog(ws)
        module = io.find_module(catalog, module_id)
        if module:
            data["metadata"] = {
                "name": module.get("name"),
                "slug": module.get("slug"),
                "status": module.get("status"),
                "depends_on": module.get("depends_on", []),
                "feature_ids": module.get("feature_ids", []),
                "primary_service": module.get("primary_service"),
                "created_at": module.get("created_at"),
            }

    return success_response(data)


def _resolve_feature(ws: Path, feature_id: str, include_metadata: bool) -> dict[str, Any]:
    """Resolve F-NNN via feature-map.yaml + alias fallback."""
    map_data = io.read_feature_map(ws)
    entry = map_data.get("features", {}).get(feature_id)

    resolved_via_alias = False
    if not entry:
        aliases = io.read_id_aliases(ws)
        for rename in aliases.get("id_renames", []):
            if rename.get("from") == feature_id:
                canonical = rename.get("to")
                entry = map_data.get("features", {}).get(canonical)
                if entry:
                    resolved_via_alias = True
                    feature_id = canonical
                    break

    if not entry:
        raise NotFoundError(
            f"Feature {feature_id!r} not found in map or aliases",
            details={"feature_id": feature_id, "kind": "feature"},
        )

    abs_path = ws / entry["path"]
    data: dict[str, Any] = {
        "id": feature_id,
        "kind": "feature",
        "path": str(abs_path).replace("\\", "/"),
        "relative_path": entry["path"],
        "exists": abs_path.exists(),
        "resolved_via_alias": resolved_via_alias,
        "module_id": entry.get("module"),
    }

    if include_metadata:
        catalog = io.read_feature_catalog(ws)
        feat = io.find_feature(catalog, feature_id)
        if feat:
            data["metadata"] = {
                "name": feat.get("name"),
                "slug": feat.get("slug"),
                "module_id": feat.get("module_id"),
                "consumed_by_modules": feat.get("consumed_by_modules", []),
                "status": feat.get("status"),
                "priority": feat.get("priority"),
            }

    return success_response(data)


def _resolve_hotfix(ws: Path, hotfix_id: str, include_metadata: bool) -> dict[str, Any]:
    """Resolve H-NNN via filesystem (no map file for hotfixes currently)."""
    hotfixes_dir = ws / "docs" / "hotfixes"
    if not hotfixes_dir.exists():
        raise NotFoundError(
            "No hotfixes directory in workspace",
            details={"workspace_path": str(ws)},
        )

    # Hotfix folders named H-NNN-{slug}
    for child in hotfixes_dir.iterdir():
        if child.is_dir() and child.name.startswith(f"{hotfix_id}-"):
            data: dict[str, Any] = {
                "id": hotfix_id,
                "kind": "hotfix",
                "path": str(child).replace("\\", "/"),
                "relative_path": str(child.relative_to(ws)).replace("\\", "/"),
                "exists": True,
                "resolved_via_alias": False,
            }
            if include_metadata:
                # Read _state.md frontmatter for hotfix metadata
                state = child / "_state.md"
                if state.exists():
                    data["metadata"] = _parse_state_md_frontmatter(state)
            return success_response(data)

    raise NotFoundError(
        f"Hotfix {hotfix_id!r} not found",
        details={"hotfix_id": hotfix_id, "kind": "hotfix"},
    )


def _parse_state_md_frontmatter(path: Path) -> dict[str, Any]:
    """Light frontmatter parse — extract YAML between leading `---` markers."""
    import yaml

    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        return yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return {}
