"""Read/write helpers for intel artifacts (catalogs, maps, meta).

Centralizes JSON/YAML I/O for intel layer files so scaffold tools don't
duplicate parse/serialize logic. All writes go through atomic_write_text
(per concurrency.py) — no partial states on disk.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from etc_platform.sdlc.concurrency import atomic_write_text

# ---------------------------------------------------------------------------
# Canonical paths within workspace
# ---------------------------------------------------------------------------


def intel_dir(workspace_path: Path) -> Path:
    return workspace_path / "docs" / "intel"


def feature_catalog_path(workspace_path: Path) -> Path:
    return intel_dir(workspace_path) / "feature-catalog.json"


def module_catalog_path(workspace_path: Path) -> Path:
    return intel_dir(workspace_path) / "module-catalog.json"


def module_map_path(workspace_path: Path) -> Path:
    return intel_dir(workspace_path) / "module-map.yaml"


def feature_map_path(workspace_path: Path) -> Path:
    return intel_dir(workspace_path) / "feature-map.yaml"


def id_aliases_path(workspace_path: Path) -> Path:
    return intel_dir(workspace_path) / "id-aliases.json"


def module_dir(workspace_path: Path, module_id: str, slug: str) -> Path:
    return workspace_path / "docs" / "modules" / f"{module_id}-{slug}"


def feature_dir(
    workspace_path: Path,
    module_id: str,
    module_slug: str,
    feature_id: str,
    feature_slug: str,
) -> Path:
    return module_dir(workspace_path, module_id, module_slug) / "features" / f"{feature_id}-{feature_slug}"


def hotfix_dir(workspace_path: Path, hotfix_id: str, slug: str) -> Path:
    return workspace_path / "docs" / "hotfixes" / f"{hotfix_id}-{slug}"


# ---------------------------------------------------------------------------
# Read helpers (return canonical empty structures if file missing)
# ---------------------------------------------------------------------------


def read_json(path: Path, *, default: Any = None) -> Any:
    """Read JSON file. If missing, return default."""
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_yaml(path: Path, *, default: Any = None) -> Any:
    """Read YAML file. If missing, return default."""
    if not path.exists():
        return default
    return yaml.safe_load(path.read_text(encoding="utf-8")) or default


def read_module_catalog(workspace_path: Path) -> dict[str, Any]:
    """Read module-catalog.json. Returns empty skeleton if absent."""
    return read_json(
        module_catalog_path(workspace_path),
        default={"schema_version": "1.0", "modules": []},
    )


def read_feature_catalog(workspace_path: Path) -> dict[str, Any]:
    return read_json(
        feature_catalog_path(workspace_path),
        default={
            "schema_version": "1.0",
            "multi_role": False,
            "roles": [],
            "services": [],
            "features": [],
        },
    )


def read_module_map(workspace_path: Path) -> dict[str, Any]:
    return read_yaml(
        module_map_path(workspace_path),
        default={"schema_version": "1.0", "modules": {}},
    )


def read_feature_map(workspace_path: Path) -> dict[str, Any]:
    return read_yaml(
        feature_map_path(workspace_path),
        default={"schema_version": "1.0", "features": {}},
    )


def read_id_aliases(workspace_path: Path) -> dict[str, Any]:
    return read_json(
        id_aliases_path(workspace_path),
        default={
            "schema_version": "1.0",
            "id_renames": [],
            "slug_renames": [],
            "reservations": [],
        },
    )


# ---------------------------------------------------------------------------
# Serialization helpers (deterministic output for stable hashes + diffs)
# ---------------------------------------------------------------------------


def serialize_json(data: Any, *, sort_keys: bool = True) -> str:
    """Deterministic JSON: indent=2, sort keys, UTF-8 (no ASCII escape)."""
    return json.dumps(data, indent=2, sort_keys=sort_keys, ensure_ascii=False) + "\n"


def serialize_yaml(data: Any) -> str:
    """Deterministic YAML: sort keys, no flow style."""
    return yaml.safe_dump(
        data,
        sort_keys=True,
        default_flow_style=False,
        allow_unicode=True,
    )


# ---------------------------------------------------------------------------
# Write helpers (atomic via concurrency.atomic_write_text)
# ---------------------------------------------------------------------------


def write_json_atomic(path: Path, data: Any) -> None:
    atomic_write_text(path, serialize_json(data))


def write_yaml_atomic(path: Path, data: Any) -> None:
    atomic_write_text(path, serialize_yaml(data))


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def find_module(catalog: dict[str, Any], module_id: str) -> dict[str, Any] | None:
    """Find module by ID in catalog. Returns None if absent."""
    for mod in catalog.get("modules", []):
        if mod.get("id") == module_id:
            return mod
    return None


def find_feature(catalog: dict[str, Any], feature_id: str) -> dict[str, Any] | None:
    """Find feature by ID in catalog. Returns None if absent."""
    for feat in catalog.get("features", []):
        if feat.get("id") == feature_id:
            return feat
    return None


def all_module_ids(catalog: dict[str, Any], map_data: dict[str, Any]) -> set[str]:
    """All known module IDs from catalog + map (union for collision check)."""
    ids: set[str] = set()
    for mod in catalog.get("modules", []):
        if mid := mod.get("id"):
            ids.add(mid)
    ids.update(map_data.get("modules", {}).keys())
    return ids


def all_feature_ids(catalog: dict[str, Any], map_data: dict[str, Any]) -> set[str]:
    """All known feature IDs from catalog + map (union for collision check)."""
    ids: set[str] = set()
    for feat in catalog.get("features", []):
        if fid := feat.get("id"):
            ids.add(fid)
    ids.update(map_data.get("features", {}).keys())
    return ids
