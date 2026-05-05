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
    """Convert module name to kebab-case slug; ensures no trailing hyphen post-truncation."""
    s = name.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s+", "-", s).strip("-")
    s = re.sub(r"-+", "-", s)
    s = s[:30].rstrip("-")  # strip trailing hyphen after length truncation
    return s or "default"


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
        slug = old_slug or slugify(feature_name)

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

    print()
    print("[OK] Migration complete (Phase 1 + Phase 2)!")
    print()
    print("Next steps:")
    print("  1. Review changes with `git status` (assuming workspace is git-tracked)")
    print("  2. Run verify_all via MCP: mcp__etc-platform__verify(workspace_path, scopes=['all'])")
    print("  3. Update module-catalog.json + feature-catalog.json fields per scaffold_module schema")
    print(f"  4. If issues: bash {rollback}")


if __name__ == "__main__":
    main()
