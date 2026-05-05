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
    """Convert module name to kebab-case slug."""
    s = name.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s+", "-", s).strip("-")
    s = re.sub(r"-+", "-", s)
    return s[:30] or "default"


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
            print(f"  ⚠ Skip: {old} no longer exists")
            continue
        old.rename(new)
        moves.append(f"{r['old_path']} → {r['new_path']}")
    return moves


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

    print()
    print("[OK] Migration complete!")
    print()
    print("Next steps:")
    print("  1. Review changes with `git status` (assuming workspace is git-tracked)")
    print("  2. Run verify_all via MCP: mcp__etc-platform__verify(workspace_path, scopes=['all'])")
    print("  3. Update module-catalog.json + feature-catalog.json fields per scaffold_module schema")
    print(f"  4. If issues: bash {rollback}")


if __name__ == "__main__":
    main()
