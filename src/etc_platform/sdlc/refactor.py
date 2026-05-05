"""Refactor tools — rename + restructure operations.

Currently exposes:
    rename_module_slug — atomic slug change across folder + all references
                          + emit alias entry. Per p0 §3.6 + ADR-003 D10-1.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from etc_platform.sdlc import intel_io as io
from etc_platform.sdlc.concurrency import FileTransaction, workspace_lock
from etc_platform.sdlc.errors import (
    InvalidInputError,
    NameCollisionError,
    NotFoundError,
    success_response,
)
from etc_platform.sdlc.ids import is_valid_module_id, is_valid_slug
from etc_platform.sdlc.path_validation import validate_workspace_path
from etc_platform.sdlc.templates import utc_iso_now
from etc_platform.sdlc.versioning import bump_artifact, read_meta, write_meta


def rename_module_slug_impl(
    workspace_path: str,
    module_id: str,
    new_slug: str,
    reason: str,
    *,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Atomic slug rename. Per p0 §3.6.

    Steps:
        1. Validate inputs + verify module exists
        2. Acquire workspace lock
        3. Compute new folder path; reject if collision
        4. Multi-file txn:
           - Rename folder (Python os.rename, atomic on same filesystem)
           - Update module-catalog.modules[].slug
           - Update module-map[M-NNN].slug + path
           - Update feature-map entries (paths under old folder)
           - Append id-aliases.json.slug_renames
        5. Bump versions in _meta.json
    """
    ws = validate_workspace_path(workspace_path)

    if not is_valid_module_id(module_id):
        raise InvalidInputError(
            f"Invalid module_id: {module_id!r}",
            details={"module_id": module_id},
        )
    if not is_valid_slug(new_slug):
        raise InvalidInputError(
            f"Invalid new_slug: {new_slug!r} (kebab-case ASCII required)",
            details={"new_slug": new_slug},
        )
    if not reason or len(reason) < 10:
        raise InvalidInputError(
            "reason required (min 10 chars) for audit trail",
            details={"reason_length": len(reason)},
        )

    with workspace_lock(str(ws)):
        catalog = io.read_module_catalog(ws)
        mod_map = io.read_module_map(ws)
        feat_map = io.read_feature_map(ws)
        aliases = io.read_id_aliases(ws)
        meta = read_meta(ws)

        # Find module
        module = io.find_module(catalog, module_id)
        if not module:
            raise NotFoundError(
                f"Module {module_id} not found",
                details={"module_id": module_id},
            )
        old_slug = module["slug"]
        if old_slug == new_slug:
            raise InvalidInputError(
                f"new_slug equals current slug: {new_slug!r} (no-op rename)",
                details={"current_slug": old_slug},
            )

        # Check collision: any other module already has new_slug?
        for other in catalog.get("modules", []):
            if other.get("id") != module_id and other.get("slug") == new_slug:
                raise NameCollisionError(
                    f"Slug {new_slug!r} already used by {other.get('id')}",
                    details={"new_slug": new_slug, "conflicts_with": other.get("id")},
                )

        old_folder = io.module_dir(ws, module_id, old_slug)
        new_folder = io.module_dir(ws, module_id, new_slug)

        if not old_folder.exists():
            raise NotFoundError(
                f"Old module folder missing: {old_folder.relative_to(ws)}",
                details={"path": str(old_folder.relative_to(ws))},
                fix_hint="Folder may have been manually renamed or deleted; run autofix.",
            )
        if new_folder.exists():
            raise NameCollisionError(
                f"New folder path already occupied: {new_folder.relative_to(ws)}",
                details={"path": str(new_folder.relative_to(ws))},
            )

        # Step 1: rename folder atomically (os.rename within same filesystem)
        # Done OUTSIDE FileTransaction since it's directory-rename, not file write.
        old_folder.rename(new_folder)

        # Step 2: update catalog entry
        module["slug"] = new_slug

        # Step 3: update module-map entry
        new_path_rel = str(new_folder.relative_to(ws)).replace("\\", "/")
        if module_id in mod_map.get("modules", {}):
            mod_map["modules"][module_id]["slug"] = new_slug
            mod_map["modules"][module_id]["path"] = new_path_rel

        # Step 4: update feature-map entries that reference old folder
        old_path_segment = f"docs/modules/{module_id}-{old_slug}/"
        new_path_segment = f"docs/modules/{module_id}-{new_slug}/"
        feat_map_updated = False
        for fid, entry in feat_map.get("features", {}).items():
            if entry.get("module") == module_id and entry.get("path", "").startswith(
                old_path_segment
            ):
                entry["path"] = entry["path"].replace(old_path_segment, new_path_segment, 1)
                feat_map_updated = True

        # Step 5: append slug_rename entry to id-aliases.json
        aliases.setdefault("slug_renames", []).append(
            {
                "module_id": module_id,
                "old_slug": old_slug,
                "new_slug": new_slug,
                "renamed_at": utc_iso_now(),
                "reason": reason,
            }
        )

        catalog_content = io.serialize_json(catalog)
        mod_map_content = io.serialize_yaml(mod_map)
        feat_map_content = io.serialize_yaml(feat_map) if feat_map_updated else None
        aliases_content = io.serialize_json(aliases)

        # Multi-file write
        tx = FileTransaction()
        tx.add(io.module_catalog_path(ws), catalog_content)
        tx.add(io.module_map_path(ws), mod_map_content)
        if feat_map_content is not None:
            tx.add(io.feature_map_path(ws), feat_map_content)
        tx.add(io.id_aliases_path(ws), aliases_content)
        finals = tx.commit()

        # Bump versions
        new_cat_v = bump_artifact(
            meta, "module-catalog.json", content=catalog_content, producer="etc-platform/rename_module_slug"
        )
        new_map_v = bump_artifact(
            meta, "module-map.yaml", content=mod_map_content, producer="etc-platform/rename_module_slug"
        )
        if feat_map_content is not None:
            bump_artifact(
                meta,
                "feature-map.yaml",
                content=feat_map_content,
                producer="etc-platform/rename_module_slug",
            )
        bump_artifact(
            meta, "id-aliases.json", content=aliases_content, producer="etc-platform/rename_module_slug"
        )
        write_meta(ws, meta)

    return success_response(
        {
            "module_id": module_id,
            "old_slug": old_slug,
            "new_slug": new_slug,
            "old_path": str(old_folder.relative_to(ws)).replace("\\", "/"),
            "new_path": new_path_rel,
            "alias_added": True,
            "references_updated": [str(p.relative_to(ws)).replace("\\", "/") for p in finals],
            "feature_map_updated": feat_map_updated,
            "new_versions": {
                "module-catalog.json": new_cat_v,
                "module-map.yaml": new_map_v,
            },
        }
    )
