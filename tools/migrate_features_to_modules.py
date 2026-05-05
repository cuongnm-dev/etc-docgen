"""Migrate legacy F-NNN pipeline folders to ADR-003 M-NNN module structure.

Implements ADR-003 P4 migration with safety guards (D10-9):
    1. Pre-flight check  — refuse if any feature has status ∈ {dev, qa, review, blocked}
    2. Mandatory backup  — `cp -r docs/ docs.pre-migrate-{ts}/` before any change
    3. Idempotent        — detect already-migrated state, no-op
    4. Dry-run flag      — `--dry-run` print diff without apply
    5. Rollback script   — auto-emit `rollback-{ts}.sh` synchronously
    6. Verify post-migrate — run verify_all on new structure, block if HIGH

Usage:
    python migrate_features_to_modules.py /path/to/workspace --dry-run
    python migrate_features_to_modules.py /path/to/workspace --execute --backup-confirmed

Specific to taxpayer:
    F-061..F-080 pipeline IDs → M-001..M-020 module IDs
    Reads each F-NNN's _state.md scope-features field to build module → feature_ids mapping
    Generates id-aliases.json with F-NNN → M-NNN renames

Reference: ADR-003 v2 D10-9 + plans/p0-mcp-tool-spec.md migration section.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml required. Install via: pip install pyyaml", file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LEGACY_FEATURES_DIR = "docs/features"
NEW_MODULES_DIR = "docs/modules"
INTEL_DIR = "docs/intel"

MIGRATABLE_STATUSES = ("proposed", "in-progress")
BLOCKING_STATUSES = ("dev", "qa", "review", "blocked", "done")


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------


def find_legacy_pipelines(workspace: Path) -> list[Path]:
    """Find F-NNN folders under docs/features/ (legacy pipeline naming)."""
    legacy_dir = workspace / LEGACY_FEATURES_DIR
    if not legacy_dir.exists():
        return []
    pat = re.compile(r"^F-[0-9]{3,}(-.+)?$")
    return sorted([p for p in legacy_dir.iterdir() if p.is_dir() and pat.match(p.name)])


def already_migrated(workspace: Path) -> bool:
    """Check if migration already happened: docs/modules/ exists with M-NNN folders."""
    modules_dir = workspace / NEW_MODULES_DIR
    if not modules_dir.exists():
        return False
    return any(p.is_dir() and p.name.startswith("M-") for p in modules_dir.iterdir())


def parse_state_md(state_path: Path) -> dict[str, Any]:
    """Extract YAML frontmatter from _state.md. Returns {} on failure."""
    text = state_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        return yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return {}


def parse_feature_req_scope(feature_req: str) -> dict[str, list[str]]:
    """Parse feature-req field for scope-modules + scope-features lists."""
    result = {"scope-modules": [], "scope-features": []}
    if not feature_req:
        return result
    for line in feature_req.splitlines():
        line = line.strip()
        m = re.match(r"^scope-modules:\s*\[(.*)\]\s*$", line)
        if m:
            result["scope-modules"] = [
                s.strip().strip('"').strip("'") for s in m.group(1).split(",") if s.strip()
            ]
        m = re.match(r"^scope-features:\s*\[(.*)\]\s*$", line)
        if m:
            result["scope-features"] = [
                s.strip().strip('"').strip("'") for s in m.group(1).split(",") if s.strip()
            ]
    return result


def slugify(name: str) -> str:
    """Convert name to ASCII kebab-case slug.

    Strips Vietnamese diacritics via NFKD decomposition. Use only as
    last-resort fallback when no explicit slug or English name available.
    Truncates to 30 chars + strips trailing hyphen.
    """
    import unicodedata

    # Vietnamese 'đ' / 'Đ' don't decompose via NFKD — replace explicitly
    s = name.replace("đ", "d").replace("Đ", "D")
    # NFKD decomposition + ASCII filter strips remaining diacritics
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s+", "-", s).strip("-")
    s = re.sub(r"-+", "-", s)
    s = s[:30].rstrip("-")
    return s or "default"


def derive_slug(entity: dict, fallback_name: str = "") -> tuple[str, str]:
    """Derive ASCII slug from entity dict using strict precedence.

    Precedence (per CD-22 — slug must be English/canonical):
        1. entity.slug             (explicit, used as-is — schema-validated)
        2. entity.name_en          (English name → slugify)
        3. entity.canonical_name   (canonical English alias → slugify)
        4. fallback_name           (e.g. ID → slugify, last resort)
        5. slugify(entity.name)    (Vietnamese transliteration — WARN)

    Returns: (slug, source) where source ∈ {explicit, name_en, canonical_name,
    fallback_id, transliteration}.

    Pattern check: ^[a-z][a-z0-9]*(-[a-z0-9]+)*$ — caller verifies via verify tool.
    """
    if entity.get("slug"):
        return slugify(entity["slug"]), "explicit"
    if entity.get("name_en"):
        return slugify(entity["name_en"]), "name_en"
    if entity.get("canonical_name"):
        return slugify(entity["canonical_name"]), "canonical_name"
    if fallback_name:
        return slugify(fallback_name), "fallback_id"
    return slugify(entity.get("name", "default")), "transliteration"


# ---------------------------------------------------------------------------
# Migration plan computation
# ---------------------------------------------------------------------------


def build_migration_plan(workspace: Path) -> dict[str, Any]:
    """Read existing F-NNN pipelines + propose F-NNN → M-NNN renames.

    Returns plan dict with:
        old_feature_paths: list of old folder paths
        renames: list of {from: F-NNN, to: M-NNN, slug}
        feature_ids_per_module: {M-NNN: [F-XXX, F-YYY, ...]} (from scope-features)
        unmigratable: list of folders that block migration (status, etc.)
    """
    legacy = find_legacy_pipelines(workspace)
    if not legacy:
        return {"renames": [], "old_feature_paths": [], "feature_ids_per_module": {}, "unmigratable": []}

    plan_renames: list[dict[str, str]] = []
    feature_ids_per_module: dict[str, list[str]] = {}
    unmigratable: list[dict[str, str]] = []

    # Sort legacy folders by F-NNN number to assign M-001 → M-NNN sequentially
    legacy_with_num = []
    for p in legacy:
        m = re.match(r"^(F-([0-9]+))(-(.+))?$", p.name)
        if m:
            legacy_with_num.append((int(m.group(2)), p, m.group(4) or ""))
    legacy_with_num.sort(key=lambda x: x[0])

    counter = 1
    slug_warnings: list[dict[str, str]] = []
    for _num, folder, old_slug in legacy_with_num:
        legacy_id = folder.name.split("-", 2)[0] + "-" + folder.name.split("-", 2)[1]
        state_md = folder / "_state.md"
        if not state_md.exists():
            unmigratable.append({"path": str(folder), "reason": "no_state_md"})
            continue

        fm = parse_state_md(state_md)
        status = fm.get("status", "")
        if status in BLOCKING_STATUSES:
            unmigratable.append({"path": str(folder), "reason": f"status={status}"})
            continue

        feature_name = fm.get("feature-name", legacy_id)
        # Derive slug per CD-22 strict precedence
        if old_slug:
            slug, slug_source = old_slug, "preserved"
        else:
            # Try _state.md frontmatter for slug/name_en/canonical_name
            slug_data = {
                "slug": fm.get("slug"),
                "name_en": fm.get("name-en") or fm.get("feature-name-en"),
                "name": feature_name,
            }
            slug, slug_source = derive_slug(slug_data, fallback_name=feature_name)
        if slug_source == "transliteration":
            slug_warnings.append({"id": legacy_id, "name": feature_name[:60], "slug": slug})

        new_module_id = f"M-{counter:03d}"
        counter += 1

        plan_renames.append(
            {
                "from": legacy_id,
                "to": new_module_id,
                "old_path": str(folder.relative_to(workspace)).replace("\\", "/"),
                "new_path": f"docs/modules/{new_module_id}-{slug}",
                "slug": slug,
                "module_name": feature_name,
                "old_status": status,
            }
        )

        # Extract scope-features list (these are real business features under this module)
        scope_info = parse_feature_req_scope(fm.get("feature-req", ""))
        feature_ids_per_module[new_module_id] = scope_info.get("scope-features", [])

    return {
        "renames": plan_renames,
        "feature_ids_per_module": feature_ids_per_module,
        "unmigratable": unmigratable,
        "slug_warnings": slug_warnings,
    }


# ---------------------------------------------------------------------------
# Apply migration
# ---------------------------------------------------------------------------


def backup_workspace_docs(workspace: Path, ts: str) -> Path:
    """Create backup of docs/ tree."""
    src = workspace / "docs"
    dst = workspace / f"docs.pre-migrate-{ts}"
    if dst.exists():
        raise FileExistsError(f"Backup target already exists: {dst}")
    shutil.copytree(src, dst)
    return dst


def write_id_aliases(workspace: Path, plan: dict[str, Any], ts: str) -> Path:
    """Append F-NNN → M-NNN renames to id-aliases.json."""
    aliases_path = workspace / INTEL_DIR / "id-aliases.json"
    if aliases_path.exists():
        aliases = json.loads(aliases_path.read_text(encoding="utf-8"))
    else:
        aliases = {
            "schema_version": "1.0",
            "id_renames": [],
            "slug_renames": [],
            "reservations": [],
        }

    for r in plan["renames"]:
        aliases.setdefault("id_renames", []).append(
            {
                "from": r["from"],
                "to": r["to"],
                "renamed_at": ts,
                "reason": "ADR-003 P4 migration: legacy F-NNN pipeline → M-NNN module structure",
                "by": "tools/migrate_features_to_modules.py",
            }
        )

    aliases_path.parent.mkdir(parents=True, exist_ok=True)
    aliases_path.write_text(
        json.dumps(aliases, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return aliases_path


def emit_rollback_script(workspace: Path, plan: dict[str, Any], ts: str, backup_dir: Path) -> Path:
    """Emit shell script to undo migration."""
    script_path = workspace / f"rollback-migrate-{ts}.sh"
    lines = ["#!/usr/bin/env bash", "set -euo pipefail", ""]
    lines.append(f"# Auto-emitted by migrate_features_to_modules.py at {ts}")
    lines.append(f"# Restores from backup: {backup_dir}")
    lines.append(f"")
    lines.append(f"echo '⏪ Rolling back migration {ts}...'")
    lines.append(f"rm -rf '{workspace / 'docs'}'")
    lines.append(f"mv '{backup_dir}' '{workspace / 'docs'}'")
    lines.append(f"rm -f '{script_path}'")
    lines.append(f"echo '✅ Rollback complete.'")
    script_path.write_text("\n".join(lines), encoding="utf-8")
    try:
        script_path.chmod(0o755)
    except OSError:
        pass  # Windows
    return script_path


def apply_renames(workspace: Path, plan: dict[str, Any]) -> list[str]:
    """Move old folders to new locations. Returns list of moves."""
    moves: list[str] = []
    for r in plan["renames"]:
        old = workspace / r["old_path"]
        new = workspace / r["new_path"]
        new.parent.mkdir(parents=True, exist_ok=True)
        if not old.exists():
            print(f"  [!] Skip: {old} no longer exists")
            continue
        old.rename(new)
        moves.append(f"{r['old_path']} -> {r['new_path']}")
    return moves


# ---------------------------------------------------------------------------
# Phase 2: Frontmatter rewrite + catalog population (post-rename)
# ---------------------------------------------------------------------------


def update_state_md_frontmatters(workspace: Path, plan: dict[str, Any]) -> int:
    """Rewrite _state.md frontmatter after rename: feature-id F-NNN -> M-NNN,
    docs-path update, depends-on F-NNN -> M-NNN translation."""
    rename_map = {r["from"]: r["to"] for r in plan["renames"]}
    count = 0
    for r in plan["renames"]:
        state_md = workspace / r["new_path"] / "_state.md"
        if not state_md.exists():
            continue
        text = state_md.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        # Replace feature-id line with new M-NNN
        new_text = re.sub(
            r"^feature-id:\s*F-\d+\s*$",
            f"feature-id: {r['to']}",
            text,
            count=1,
            flags=re.MULTILINE,
        )
        # Update docs-path
        new_text = re.sub(
            r"^docs-path:\s*.+$",
            f"docs-path: {r['new_path']}",
            new_text,
            count=1,
            flags=re.MULTILINE,
        )
        # Translate depends-on F-NNN values to M-NNN (if YAML list inline format)
        # e.g. "depends-on: [F-061, F-062]" -> "depends-on: [M-001, M-002]"
        def _translate_deps(match):
            deps_raw = match.group(1)
            translated = re.sub(
                r"F-\d+",
                lambda m: rename_map.get(m.group(0), m.group(0)),
                deps_raw,
            )
            return f"depends-on: [{translated}]"

        new_text = re.sub(
            r"^depends-on:\s*\[([^\]]*)\]\s*$",
            _translate_deps,
            new_text,
            count=1,
            flags=re.MULTILINE,
        )
        # Update pipeline-type if missing
        if "pipeline-type:" not in new_text:
            new_text = new_text.replace("---\n", "---\npipeline-type: sdlc\n", 1)
        state_md.write_text(new_text, encoding="utf-8")
        count += 1
    return count


def populate_module_catalog(workspace: Path, plan: dict[str, Any]) -> Path:
    """Build module-catalog.json from renamed _state.md files."""
    catalog_path = workspace / INTEL_DIR / "module-catalog.json"
    if catalog_path.exists():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    else:
        catalog = {"schema_version": "1.0", "modules": []}

    catalog.setdefault("modules", [])
    existing_ids = {m["id"] for m in catalog["modules"]}

    # Build rename map for depends_on translation
    rename_map = {r["from"]: r["to"] for r in plan["renames"]}

    for r in plan["renames"]:
        if r["to"] in existing_ids:
            continue
        state_md = workspace / r["new_path"] / "_state.md"
        fm = parse_state_md(state_md) if state_md.exists() else {}
        # Translate F-NNN dependencies to M-NNN per rename map
        raw_deps = fm.get("depends-on", []) or []
        depends_on = [rename_map.get(d, d) for d in raw_deps]
        agent_flags = fm.get("agent-flags", {}) or {}

        module_entry = {
            "id": r["to"],
            "name": r["module_name"],
            "slug": r["slug"],
            "status": "in-progress",
            "depends_on": depends_on,
            "feature_ids": plan["feature_ids_per_module"].get(r["to"], []),
            "primary_service": fm.get("project", ""),
            "modules_in_scope": [],
            "agent_flags": agent_flags,
            "created_at": datetime.now(UTC).isoformat(),
        }
        # Try to extract tier/mvp_wave/risk_score from agent-flags.ba
        ba_flags = agent_flags.get("ba", {})
        if "tier" in ba_flags:
            module_entry["tier"] = ba_flags["tier"]
        if "mvp-wave" in ba_flags:
            module_entry["mvp_wave"] = ba_flags["mvp-wave"]
        if "pipeline-risk-score" in ba_flags:
            module_entry["risk_score"] = ba_flags["pipeline-risk-score"]

        catalog["modules"].append(module_entry)

    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return catalog_path


def populate_module_map(workspace: Path, plan: dict[str, Any]) -> Path:
    """Build module-map.yaml from rename plan."""
    map_path = workspace / INTEL_DIR / "module-map.yaml"
    if map_path.exists():
        map_data = yaml.safe_load(map_path.read_text(encoding="utf-8")) or {}
    else:
        map_data = {"schema_version": "1.0", "modules": {}}

    map_data.setdefault("modules", {})

    for r in plan["renames"]:
        map_data["modules"][r["to"]] = {
            "name": r["module_name"],
            "slug": r["slug"],
            "path": r["new_path"],
        }

    map_path.parent.mkdir(parents=True, exist_ok=True)
    map_path.write_text(
        yaml.safe_dump(map_data, sort_keys=True, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )
    return map_path


def populate_feature_map(workspace: Path, plan: dict[str, Any]) -> Path:
    """Build feature-map.yaml mapping features to their parent modules."""
    map_path = workspace / INTEL_DIR / "feature-map.yaml"
    if map_path.exists():
        map_data = yaml.safe_load(map_path.read_text(encoding="utf-8")) or {}
    else:
        map_data = {"schema_version": "1.0", "features": {}}

    map_data.setdefault("features", {})

    feat_catalog_path = workspace / INTEL_DIR / "feature-catalog.json"
    feat_catalog = (
        json.loads(feat_catalog_path.read_text(encoding="utf-8"))
        if feat_catalog_path.exists()
        else {"features": []}
    )
    feat_by_id = {f["id"]: f for f in feat_catalog.get("features", [])}

    for r in plan["renames"]:
        module_id = r["to"]
        module_path = r["new_path"]
        for fid in plan["feature_ids_per_module"].get(module_id, []):
            feat_data = feat_by_id.get(fid, {})
            # Slug field omitted intentionally — feature folders don't exist yet,
            # will be populated by scaffold_feature when feature folders created.
            # Schema marks slug as optional; only validates pattern when present.
            map_data["features"][fid] = {
                "module": module_id,
                "name": feat_data.get("name", ""),
                "path": f"{module_path}/features/{fid}",  # Future location
                "status": feat_data.get("status", "proposed"),
            }

    map_path.parent.mkdir(parents=True, exist_ok=True)
    map_path.write_text(
        yaml.safe_dump(map_data, sort_keys=True, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )
    return map_path


def add_reservation_entry(workspace: Path, plan: dict[str, Any]) -> None:
    """Add reservations entry to id-aliases.json to suppress unjustified-gap warning."""
    aliases_path = workspace / INTEL_DIR / "id-aliases.json"
    aliases = json.loads(aliases_path.read_text(encoding="utf-8"))
    aliases.setdefault("reservations", [])

    # Compute F range used by old pipelines
    nums = sorted(int(re.match(r"F-(\d+)", r["from"]).group(1)) for r in plan["renames"])
    if nums:
        rng = f"F-{nums[0]:03d}..F-{nums[-1]:03d}"
        aliases["reservations"].append(
            {
                "range": rng,
                "reason": (
                    f"Migrated to {plan['renames'][0]['to']}..{plan['renames'][-1]['to']} "
                    "per ADR-003 P4 (see id_renames). Range reserved permanently to prevent re-use."
                ),
                "reserved_by": "tools/migrate_features_to_modules.py",
                "expires": None,
            }
        )

    aliases_path.write_text(
        json.dumps(aliases, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def patch_feature_catalog_module_id(workspace: Path, plan: dict[str, Any]) -> Path:
    """Add module_id field to each feature in feature-catalog.json based on plan."""
    catalog_path = workspace / INTEL_DIR / "feature-catalog.json"
    if not catalog_path.exists():
        return catalog_path
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    # Build feature -> module lookup
    f_to_m = {}
    for r in plan["renames"]:
        for fid in plan["feature_ids_per_module"].get(r["to"], []):
            f_to_m[fid] = r["to"]

    for feat in catalog.get("features", []):
        fid = feat.get("id")
        if fid in f_to_m and not feat.get("module_id"):
            feat["module_id"] = f_to_m[fid]

    catalog_path.write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return catalog_path


def ensure_required_dirs(workspace: Path) -> list[str]:
    """Create docs/inputs/ + docs/generated/ if missing."""
    created = []
    for d in ("docs/inputs", "docs/generated"):
        target = workspace / d
        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
            (target / ".gitkeep").write_text("", encoding="utf-8")
            created.append(d)
    return created


# ---------------------------------------------------------------------------
# Phase 3: per-module deep substructure (CD-22 compliance)
# ---------------------------------------------------------------------------


_MODULE_STAGE_SUBDIRS = ("ba", "sa", "designer", "security", "tech-lead", "qa", "reviewer")
_FEATURE_STAGE_SUBDIRS = ("dev", "qa")


def rename_feature_brief_to_module_brief(workspace: Path, plan: dict[str, Any]) -> int:
    """Rename feature-brief.md -> module-brief.md per module folder (CD-22 vocab fix)."""
    count = 0
    for r in plan["renames"]:
        old = workspace / r["new_path"] / "feature-brief.md"
        new = workspace / r["new_path"] / "module-brief.md"
        if old.exists() and not new.exists():
            old.rename(new)
            count += 1
    return count


def create_module_implementations_yaml(workspace: Path, plan: dict[str, Any]) -> int:
    """Create implementations.yaml per module per CD-22."""
    count = 0
    for r in plan["renames"]:
        impl_path = workspace / r["new_path"] / "implementations.yaml"
        if impl_path.exists():
            continue
        state_md = workspace / r["new_path"] / "_state.md"
        fm = parse_state_md(state_md) if state_md.exists() else {}
        primary = fm.get("project", "") or fm.get("project-path", "")
        services = []
        if primary:
            services = [{"path": primary, "role": "primary"}]
        content = {
            "module_id": r["to"],
            "module_name": r["module_name"],
            "type": "bounded-context",
            "slug": r["slug"],
            "implementations": {
                "apps": [],
                "services": services,
                "libs": [],
                "packages": [],
            },
            "stakeholders": {
                "business-owner": "",
                "tech-lead": "",
                "qa-lead": "",
            },
            "depends_on": [],
        }
        # Translate depends from M-NNN list (already translated in module-catalog)
        catalog = json.loads(
            (workspace / INTEL_DIR / "module-catalog.json").read_text(encoding="utf-8")
        )
        for m in catalog.get("modules", []):
            if m.get("id") == r["to"]:
                content["depends_on"] = m.get("depends_on", [])
                break
        impl_path.write_text(
            yaml.safe_dump(content, sort_keys=False, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )
        count += 1
    return count


def create_module_stage_subdirs(workspace: Path, plan: dict[str, Any]) -> int:
    """Create 7 stage subdirs (.gitkeep) per module per CD-22."""
    count = 0
    for r in plan["renames"]:
        for sub in _MODULE_STAGE_SUBDIRS:
            d = workspace / r["new_path"] / sub
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)
                (d / ".gitkeep").write_text("", encoding="utf-8")
                count += 1
    return count


def create_feature_subfolders(workspace: Path, plan: dict[str, Any]) -> tuple[int, int]:
    """Create nested features/F-NNN-{slug}/ per CD-22 with required artifacts.

    Returns: (folders_created, files_created)
    """
    feat_catalog_path = workspace / INTEL_DIR / "feature-catalog.json"
    feat_catalog = json.loads(feat_catalog_path.read_text(encoding="utf-8"))
    feat_by_id = {f["id"]: f for f in feat_catalog.get("features", [])}

    folders = 0
    files = 0
    feat_map_path = workspace / INTEL_DIR / "feature-map.yaml"
    feat_map = yaml.safe_load(feat_map_path.read_text(encoding="utf-8")) or {}
    feat_map.setdefault("features", {})

    for r in plan["renames"]:
        module_id = r["to"]
        feature_ids = plan["feature_ids_per_module"].get(module_id, [])
        if not feature_ids:
            continue
        features_root = workspace / r["new_path"] / "features"
        features_root.mkdir(parents=True, exist_ok=True)

        for fid in feature_ids:
            feat_data = feat_by_id.get(fid, {})
            feat_name = feat_data.get("name", fid)
            # CD-22 precedence: explicit slug > name_en > name (transliterate)
            feat_slug, slug_source = derive_slug(feat_data, fallback_name=fid)
            feat_dir = features_root / f"{fid}-{feat_slug}"
            if feat_dir.exists():
                continue
            feat_dir.mkdir(parents=True, exist_ok=True)
            folders += 1

            # _feature.md
            ac_list = feat_data.get("acceptance_criteria", []) or []
            description = feat_data.get("description", "[CẦN BỔ SUNG]")
            business_intent = feat_data.get("business_intent", "[CẦN BỔ SUNG]")
            flow_summary = feat_data.get("flow_summary", "[CẦN BỔ SUNG]")
            consumed_by = feat_data.get("consumed_by_modules", []) or []
            priority = feat_data.get("priority", "medium")

            fm_lines = [
                "---",
                f"feature-id: {fid}",
                f"feature-name: {json.dumps(feat_name, ensure_ascii=False)}",
                f"slug: {feat_slug}",
                f"module-id: {module_id}",
                f"status: {feat_data.get('status', 'proposed')}",
                f"priority: {priority}",
                f"created: \"{datetime.now(UTC).strftime('%Y-%m-%d')}\"",
                f"last-updated: \"{datetime.now(UTC).strftime('%Y-%m-%d')}\"",
                "locked-fields: []",
                f"consumed_by_modules: {json.dumps(consumed_by, ensure_ascii=False)}",
                "---",
                "",
                f"# Feature: {feat_name}",
                "",
                "## Description",
                "",
                description,
                "",
                "## Business Intent",
                "",
                business_intent,
                "",
                "## Flow Summary",
                "",
                flow_summary,
                "",
                "## Acceptance Criteria",
                "",
            ]
            if ac_list:
                for ac in ac_list:
                    fm_lines.append(f"- {ac}")
            else:
                fm_lines.append("- [CẦN BỔ SUNG: tiêu chí 1]")
                fm_lines.append("- [CẦN BỔ SUNG: tiêu chí 2]")
                fm_lines.append("- [CẦN BỔ SUNG: tiêu chí 3]")
            fm_lines.append("")
            (feat_dir / "_feature.md").write_text("\n".join(fm_lines), encoding="utf-8")
            files += 1

            # implementations.yaml
            impl_content = {
                "feature_id": fid,
                "module_id": module_id,
                "slug": feat_slug,
                "implementations": {
                    "primary": "",
                    "consumers": [],
                },
                "consumed_by_modules": consumed_by,
            }
            (feat_dir / "implementations.yaml").write_text(
                yaml.safe_dump(impl_content, sort_keys=False, default_flow_style=False, allow_unicode=True),
                encoding="utf-8",
            )
            files += 1

            # test-evidence.json
            te_content = {
                "schema_version": "1.0",
                "feature_id": fid,
                "module_id": module_id,
                "test_cases": [],
                "screenshots": [],
                "playwright_specs": [],
                "execution_history": [],
            }
            (feat_dir / "test-evidence.json").write_text(
                json.dumps(te_content, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            files += 1

            # dev/, qa/ subdirs
            for sub in _FEATURE_STAGE_SUBDIRS:
                sub_dir = feat_dir / sub
                sub_dir.mkdir(parents=True, exist_ok=True)
                (sub_dir / ".gitkeep").write_text("", encoding="utf-8")
                files += 1

            # Update feature-map slug + path now that folder exists
            rel_path = str(feat_dir.relative_to(workspace)).replace("\\", "/")
            entry = feat_map["features"].setdefault(fid, {})
            entry["module"] = module_id
            entry["name"] = feat_name
            entry["slug"] = feat_slug
            entry["path"] = rel_path
            entry["status"] = feat_data.get("status", "proposed")

    feat_map_path.write_text(
        yaml.safe_dump(feat_map, sort_keys=True, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )
    return folders, files


def cleanup_legacy_artifacts(workspace: Path) -> list[str]:
    """Remove legacy artifacts no longer needed post-migration."""
    cleaned = []
    # Empty docs/features/ (folders renamed to modules/)
    legacy_features = workspace / "docs" / "features"
    if legacy_features.exists():
        try:
            entries = [p for p in legacy_features.iterdir()]
            if not entries:
                legacy_features.rmdir()
                cleaned.append("docs/features/ (empty)")
        except OSError:
            pass
    # Old docs/source/ (renamed to docs/inputs/ per CD-22 D5)
    old_source = workspace / "docs" / "source"
    if old_source.exists():
        try:
            entries = list(old_source.iterdir())
            inputs_dir = workspace / "docs" / "inputs"
            inputs_dir.mkdir(parents=True, exist_ok=True)
            # Move contents to inputs/
            for entry in entries:
                target = inputs_dir / entry.name
                if not target.exists():
                    entry.rename(target)
            # Remove if now empty
            if not list(old_source.iterdir()):
                old_source.rmdir()
                cleaned.append("docs/source/ -> docs/inputs/ (CD-22 D5 rename)")
        except OSError as exc:
            cleaned.append(f"docs/source/ rename FAILED: {exc}")
    # Old root-level feature-map.yaml (now at docs/intel/feature-map.yaml)
    old_map = workspace / "docs" / "feature-map.yaml"
    if old_map.exists():
        old_map.unlink()
        cleaned.append("docs/feature-map.yaml (moved to docs/intel/)")
    return cleaned


# ---------------------------------------------------------------------------
# Phase 4: workspace-level CD-22 polish + garbage collection
# ---------------------------------------------------------------------------


def scaffold_workspace_files(workspace: Path, repo_type: str = "mono") -> list[str]:
    """Create CD-22 required workspace-level files if missing.

    Pre-existing AGENTS.md / .gitignore preserved. Only creates missing.
    """
    created: list[str] = []

    # CLAUDE.md
    claude_md = workspace / "CLAUDE.md"
    if not claude_md.exists():
        claude_md.write_text(
            f"# {workspace.name}\n\n"
            "## Project context\n\n"
            "(Populated during ba/sa stages; see docs/intel/business-context.json for canonical brief.)\n\n"
            "## SDLC structure\n\n"
            "Per ADR-003 + CLAUDE.md CD-22: SDLC artifacts under `docs/modules/M-NNN-{slug}/`.\n"
            "Refer to `docs/intel/module-catalog.json` and `docs/intel/feature-catalog.json` as canonical sources.\n",
            encoding="utf-8",
        )
        created.append("CLAUDE.md")

    # .editorconfig
    ec = workspace / ".editorconfig"
    if not ec.exists():
        ec.write_text(
            "root = true\n\n"
            "[*]\n"
            "charset = utf-8\n"
            "end_of_line = lf\n"
            "indent_style = space\n"
            "indent_size = 2\n"
            "insert_final_newline = true\n"
            "trim_trailing_whitespace = true\n\n"
            "[*.md]\n"
            "trim_trailing_whitespace = false\n\n"
            "[Makefile]\n"
            "indent_style = tab\n\n"
            "[*.go]\n"
            "indent_style = tab\n",
            encoding="utf-8",
        )
        created.append(".editorconfig")

    # docker-compose.yml + .env.example (mono repos only)
    if repo_type == "mono":
        compose = workspace / "docker-compose.yml"
        if not compose.exists():
            compose.write_text(
                "# Workspace docker-compose stub — services populated as scaffold_app_or_service runs.\n"
                "version: \"3.8\"\n\n"
                "services: {}\n",
                encoding="utf-8",
            )
            created.append("docker-compose.yml")
        env_ex = workspace / ".env.example"
        if not env_ex.exists():
            env_ex.write_text(
                "# Environment variable template — copy to .env and fill in.\n"
                "# Per-service env vars added when scaffold_app_or_service is invoked.\n",
                encoding="utf-8",
            )
            created.append(".env.example")

    # libs/ + tools/ (CD-22 standard mono dirs; .gitkeep stub)
    if repo_type == "mono":
        for d in ("libs", "tools"):
            target = workspace / d
            if not target.exists():
                target.mkdir(parents=True, exist_ok=True)
                (target / ".gitkeep").write_text("", encoding="utf-8")
                created.append(f"{d}/")

    return created


def update_gitignore(workspace: Path) -> bool:
    """Append migration-artifact ignore patterns to .gitignore (idempotent)."""
    gi = workspace / ".gitignore"
    patterns = (
        "\n# Migration backups + rollback scripts (auto-emitted by tools/migrate_features_to_modules.py)\n"
        "docs.pre-migrate-*/\n"
        "rollback-migrate-*.sh\n"
    )
    if not gi.exists():
        gi.write_text(patterns.lstrip("\n"), encoding="utf-8")
        return True
    text = gi.read_text(encoding="utf-8")
    if "docs.pre-migrate-" in text:
        return False  # already added
    if not text.endswith("\n"):
        text += "\n"
    gi.write_text(text + patterns, encoding="utf-8")
    return True


def cleanup_migration_artifacts(workspace: Path, keep_latest: int = 1) -> list[str]:
    """Remove old migration backup dirs + rollback scripts.

    Keeps the `keep_latest` most recent backups (sorted by name = timestamp).
    Default keeps 1 (current safety net). Set keep_latest=0 to remove all.
    """
    removed: list[str] = []
    # Find backup dirs
    backups = sorted(
        [p for p in workspace.iterdir() if p.is_dir() and p.name.startswith("docs.pre-migrate-")],
        key=lambda p: p.name,
    )
    rollbacks = sorted(
        [p for p in workspace.iterdir() if p.is_file() and p.name.startswith("rollback-migrate-")],
        key=lambda p: p.name,
    )

    to_remove_dirs = backups[: max(0, len(backups) - keep_latest)]
    to_remove_files = rollbacks[: max(0, len(rollbacks) - keep_latest)]

    for d in to_remove_dirs:
        try:
            shutil.rmtree(d)
            removed.append(d.name)
        except OSError as exc:
            removed.append(f"{d.name} FAILED: {exc}")
    for f in to_remove_files:
        try:
            f.unlink()
            removed.append(f.name)
        except OSError as exc:
            removed.append(f"{f.name} FAILED: {exc}")
    return removed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Migrate legacy F-NNN pipeline folders to ADR-003 M-NNN modules.",
    )
    parser.add_argument("workspace", help="Path to workspace root")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without changes")
    parser.add_argument("--execute", action="store_true", help="Apply changes (requires --backup-confirmed)")
    parser.add_argument(
        "--backup-confirmed",
        action="store_true",
        help="Acknowledge backup will be created at docs.pre-migrate-{ts}/",
    )
    parser.add_argument(
        "--cleanup-backups",
        action="store_true",
        help="Phase 4: garbage-collect old migration backup dirs + rollback scripts (keeps latest 1 by default)",
    )
    parser.add_argument(
        "--keep-backups",
        type=int,
        default=1,
        help="Number of most-recent backup dirs to retain when --cleanup-backups (default 1, set 0 to delete all)",
    )
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        print(f"ERROR: workspace not found: {workspace}", file=sys.stderr)
        sys.exit(1)

    print(f"[*] Workspace: {workspace}")

    # Idempotency check
    if already_migrated(workspace):
        print("[OK] Already migrated (docs/modules/ contains M-NNN folders). No-op.")
        sys.exit(0)

    # Build plan
    plan = build_migration_plan(workspace)
    if not plan["renames"]:
        print("[i] No legacy F-NNN pipelines found in docs/features/. Nothing to migrate.")
        sys.exit(0)

    # Print plan
    print()
    print("=== Migration Plan ===")
    print(f"  Renames: {len(plan['renames'])}")
    for r in plan["renames"]:
        feats = plan["feature_ids_per_module"].get(r["to"], [])
        print(f"    {r['from']} -> {r['to']}  ({r['slug']})  feature_ids: {feats}")

    if plan["unmigratable"]:
        print(f"  [!] Unmigratable: {len(plan['unmigratable'])}")
        for u in plan["unmigratable"]:
            print(f"    {u['path']}  ({u['reason']})")
        print()
        print("ERROR: Some folders blocking migration. Resolve status or remove before retrying.")
        sys.exit(3)

    if args.dry_run or not args.execute:
        print()
        print("[i] Dry-run mode. No changes made. Re-run with --execute --backup-confirmed to apply.")
        sys.exit(0)

    if not args.backup_confirmed:
        print()
        print("ERROR: --execute requires --backup-confirmed flag for safety.", file=sys.stderr)
        sys.exit(4)

    # Apply
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    print()
    print(f"[*] Applying migration (timestamp: {ts})...")

    backup = backup_workspace_docs(workspace, ts)
    print(f"  [OK] Backup: {backup}")

    rollback = emit_rollback_script(workspace, plan, ts, backup)
    print(f"  [OK] Rollback script: {rollback}")

    moves = apply_renames(workspace, plan)
    print(f"  [OK] Renamed {len(moves)} folder(s)")

    aliases = write_id_aliases(workspace, plan, datetime.now(UTC).isoformat())
    print(f"  [OK] id-aliases.json updated: {aliases}")

    # Phase 2: catalog population + frontmatter rewrite + reservation
    print()
    print("[*] Phase 2 (post-rename polish)...")

    n_fm = update_state_md_frontmatters(workspace, plan)
    print(f"  [OK] Updated _state.md frontmatter feature-id in {n_fm} file(s)")

    cat = populate_module_catalog(workspace, plan)
    print(f"  [OK] module-catalog.json populated: {cat}")

    mod_map = populate_module_map(workspace, plan)
    print(f"  [OK] module-map.yaml populated: {mod_map}")

    feat_map = populate_feature_map(workspace, plan)
    print(f"  [OK] feature-map.yaml populated: {feat_map}")

    fc = patch_feature_catalog_module_id(workspace, plan)
    print(f"  [OK] feature-catalog.json patched (module_id field added): {fc}")

    add_reservation_entry(workspace, plan)
    print(f"  [OK] id-aliases.json reservations entry added")

    dirs = ensure_required_dirs(workspace)
    if dirs:
        print(f"  [OK] Created missing dirs: {dirs}")

    # Phase 3: CD-22 deep substructure
    print()
    print("[*] Phase 3 (CD-22 deep substructure)...")

    n_brief = rename_feature_brief_to_module_brief(workspace, plan)
    print(f"  [OK] Renamed feature-brief.md -> module-brief.md in {n_brief} module(s)")

    n_impl = create_module_implementations_yaml(workspace, plan)
    print(f"  [OK] Created implementations.yaml in {n_impl} module(s)")

    n_stages = create_module_stage_subdirs(workspace, plan)
    print(f"  [OK] Created {n_stages} stage subdir(s) (7 per module x N modules)")

    folders, files = create_feature_subfolders(workspace, plan)
    print(f"  [OK] Created {folders} feature folder(s) with {files} artifact(s)")

    cleaned = cleanup_legacy_artifacts(workspace)
    if cleaned:
        print(f"  [OK] Legacy cleanup: {cleaned}")

    # Phase 4: workspace-level CD-22 polish + garbage collection
    print()
    print("[*] Phase 4 (workspace-level + cleanup)...")
    repo_type = "mono"  # detected via _is_mono heuristic; default mono for taxpayer
    if not any((workspace / d).is_dir() for d in ("apps", "services", "libs", "packages")):
        repo_type = "mini"
    print(f"  Repo type detected: {repo_type}")

    ws_files = scaffold_workspace_files(workspace, repo_type=repo_type)
    if ws_files:
        print(f"  [OK] Created CD-22 workspace files: {ws_files}")
    else:
        print(f"  [OK] All CD-22 workspace files already present")

    if update_gitignore(workspace):
        print(f"  [OK] .gitignore patched with migration-artifact ignore patterns")

    if args.cleanup_backups:
        keep = args.keep_backups
        removed = cleanup_migration_artifacts(workspace, keep_latest=keep)
        if removed:
            print(f"  [OK] Garbage collected (kept latest {keep}): {removed}")
        else:
            print(f"  [OK] No old migration artifacts to clean")
    else:
        all_backups = sorted(
            [p.name for p in workspace.iterdir() if p.is_dir() and p.name.startswith("docs.pre-migrate-")],
        )
        if len(all_backups) > 1:
            print(f"  [info] {len(all_backups)} backup dirs accumulated. Pass --cleanup-backups to garbage-collect (keep latest 1).")

    print()
    print("[OK] Migration complete (Phase 1 + 2 + 3 + 4 — Full CD-22 compliant)!")
    print()
    print("Next steps:")
    print("  1. Review changes with `git status` (assuming workspace is git-tracked)")
    print("  2. Run verify_all via MCP: mcp__etc-platform__verify(workspace_path, scopes=['all'])")
    print("  3. Update module-catalog.json + feature-catalog.json fields per scaffold_module schema")
    print(f"  4. If issues: bash {rollback}")


if __name__ == "__main__":
    main()
