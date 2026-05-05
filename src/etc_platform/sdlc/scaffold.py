"""Scaffold tools — atomic create operations for SDLC entities.

Implements 5 of the 11 NEW MCP tools per ADR-003 D6/D8 + p0-mcp-tool-spec §3.1-3.5:

    scaffold_workspace      §3.1
    scaffold_app_or_service §3.2
    scaffold_module         §3.3
    scaffold_feature        §3.4
    scaffold_hotfix         §3.5

Each function:
    - Validates workspace path + IDs + slugs
    - Acquires workspace lock (per concurrency.workspace_lock)
    - Reads relevant intel state
    - Checks ID collision via all_*_ids() set lookup
    - Renders templates from assets/scaffolds/
    - Multi-file atomic transaction via FileTransaction
    - Updates _meta.json with version bumps + content hashes
    - Returns uniform success/error response

The functions return dicts following the standard MCP tool response shape;
see sdlc.errors.success_response and MCPSdlcError.to_response().
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from etc_platform.sdlc import intel_io as io
from etc_platform.sdlc.concurrency import FileTransaction, atomic_write_text, workspace_lock
from etc_platform.sdlc.errors import (
    AlreadyExistsError,
    IdCollisionError,
    InvalidInputError,
    InvalidWorkspaceError,
    NotFoundError,
    NotMonoRepoError,
    success_response,
)
from etc_platform.sdlc.ids import (
    folder_name,
    is_valid_feature_id,
    is_valid_hotfix_id,
    is_valid_module_id,
    is_valid_slug,
)
from etc_platform.sdlc.path_validation import _MARKER_FILES, validate_workspace_path
from etc_platform.sdlc.templates import render_template, utc_iso_now
from etc_platform.sdlc.versioning import (
    assert_version,
    bump_artifact,
    read_meta,
    write_meta,
)

_DEFAULT_STAGES_QUEUE_S = ["tech-lead", "dev-wave-1", "reviewer"]
_DEFAULT_STAGES_QUEUE_M = ["sa", "tech-lead", "dev-wave-1", "qa-wave-1", "reviewer"]
_DEFAULT_STAGES_QUEUE_L = [
    "sa",
    "security-design",
    "tech-lead",
    "dev-wave-1",
    "qa-wave-1",
    "security-review",
    "reviewer",
]


# ---------------------------------------------------------------------------
# scaffold_workspace (§3.1)
# ---------------------------------------------------------------------------


def scaffold_workspace_impl(
    workspace_path: str,
    workspace_type: str,
    stack: str = "none",
    config: dict[str, Any] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Bootstrap workspace base structure (mini or mono).

    Per p0 §3.1. Creates docs/{intel,inputs,generated}/ + map files +
    minimal config files (AGENTS.md, CLAUDE.md, .gitignore).
    """
    if workspace_type not in ("mini", "mono"):
        raise InvalidInputError(
            f"workspace_type must be 'mini' or 'mono', got {workspace_type!r}",
            details={"workspace_type": workspace_type},
        )

    raw = Path(workspace_path)
    if not raw.is_absolute():
        raise InvalidWorkspaceError(
            "workspace_path must be absolute",
            details={"reason": "not_absolute", "value": str(raw)},
        )

    # Create dir if missing (caller may pre-create or rely on us)
    raw.mkdir(parents=True, exist_ok=True)
    ws = raw.resolve()

    # Refuse if already scaffolded unless force
    existing_marker = next((m for m in _MARKER_FILES if (ws / m).exists()), None)
    has_intel = (ws / "docs" / "intel" / "_meta.json").exists()
    if (existing_marker or has_intel) and not force:
        raise AlreadyExistsError(
            "Workspace already scaffolded",
            details={
                "workspace_path": str(ws),
                "marker_found": existing_marker,
                "has_intel": has_intel,
            },
            fix_hint="Pass force=true to re-scaffold, or use scaffold_module/feature for incremental.",
        )

    cfg = config or {}
    workspace_name = ws.name
    created_at = utc_iso_now()

    with workspace_lock(str(ws)):
        # Render intel layer artifacts
        ctx_intel = {
            "workspace_name": workspace_name,
            "created_at": created_at,
            "multi_role": False,
        }
        meta_content = render_template("intel/_meta.json.j2", ctx_intel)
        feature_catalog_content = render_template("intel/feature-catalog.json.j2", ctx_intel)
        module_catalog_content = render_template("intel/module-catalog.json.j2", ctx_intel)
        module_map_content = render_template("intel/module-map.yaml.j2", ctx_intel)
        feature_map_content = render_template("intel/feature-map.yaml.j2", ctx_intel)

        # Minimal workspace-level files (AGENTS.md, CLAUDE.md, .gitignore)
        # Stack-specific templates deferred — emit minimal placeholders.
        agents_md = _minimal_agents_md(workspace_name, workspace_type, stack)
        claude_md = _minimal_claude_md(workspace_name)
        gitignore = _minimal_gitignore(stack)
        editorconfig = _minimal_editorconfig()

        # Multi-file transaction
        tx = FileTransaction()
        tx.add(io.intel_dir(ws) / "_meta.json", meta_content)
        tx.add(io.feature_catalog_path(ws), feature_catalog_content)
        tx.add(io.module_catalog_path(ws), module_catalog_content)
        tx.add(io.module_map_path(ws), module_map_content)
        tx.add(io.feature_map_path(ws), feature_map_content)
        tx.add(ws / "AGENTS.md", agents_md)
        tx.add(ws / "CLAUDE.md", claude_md)
        tx.add(ws / ".gitignore", gitignore)
        tx.add(ws / ".editorconfig", editorconfig)

        # Stub directories (use .gitkeep)
        for stub in (
            ws / "docs" / "inputs" / ".gitkeep",
            ws / "docs" / "generated" / ".gitkeep",
            ws / "docs" / "architecture" / "adr" / ".gitkeep",
        ):
            tx.add(stub, "")

        finals = tx.commit()

        # Record _meta.json version=1 for all 5 intel artifacts
        meta = read_meta(ws)
        for art_name, content in [
            ("_meta.json", meta_content),
            ("feature-catalog.json", feature_catalog_content),
            ("module-catalog.json", module_catalog_content),
            ("module-map.yaml", module_map_content),
            ("feature-map.yaml", feature_map_content),
        ]:
            bump_artifact(meta, art_name, content=content, producer="etc-platform/scaffold_workspace")
        write_meta(ws, meta)

    return success_response(
        {
            "workspace_path": str(ws),
            "workspace_type": workspace_type,
            "stack": stack,
            "files_created": [str(p.relative_to(ws)).replace("\\", "/") for p in finals],
            "directories_created": ["docs/intel", "docs/inputs", "docs/generated", "docs/architecture/adr"],
            "intel_versions": {
                "_meta.json": 1,
                "feature-catalog.json": 1,
                "module-catalog.json": 1,
                "module-map.yaml": 1,
                "feature-map.yaml": 1,
            },
        }
    )


# ---------------------------------------------------------------------------
# scaffold_module (§3.3)
# ---------------------------------------------------------------------------


def scaffold_module_impl(
    workspace_path: str,
    module_id: str,
    module_name: str,
    slug: str,
    *,
    modules_in_scope: list[str] | None = None,
    depends_on: list[str] | None = None,
    primary_service: str = "",
    agent_flags: dict[str, Any] | None = None,
    business_goal: str = "",
    output_mode: str = "lean",
    risk_path: str = "M",  # S | M | L → stages-queue selection
    expected_catalog_version: int | None = None,
) -> dict[str, Any]:
    """Atomic create SDLC module + update catalog + map. Per p0 §3.3."""
    ws = validate_workspace_path(workspace_path)

    if not is_valid_module_id(module_id):
        raise InvalidInputError(
            f"Invalid module_id: {module_id!r} (expected M-NNN)",
            details={"module_id": module_id},
        )
    if not is_valid_slug(slug):
        raise InvalidInputError(
            f"Invalid slug: {slug!r} (expected kebab-case ASCII)",
            details={"slug": slug},
        )
    if len(module_name) < 3:
        raise InvalidInputError(
            "module_name too short (min 3 chars)",
            details={"module_name": module_name},
        )
    if risk_path not in ("S", "M", "L"):
        raise InvalidInputError(
            f"Invalid risk_path: {risk_path!r}",
            details={"risk_path": risk_path},
        )

    depends_on = depends_on or []
    modules_in_scope = modules_in_scope or []
    agent_flags = agent_flags or {}

    with workspace_lock(str(ws)):
        # Read current state
        catalog = io.read_module_catalog(ws)
        map_data = io.read_module_map(ws)
        meta = read_meta(ws)

        # Optimistic version check
        assert_version(meta, "module-catalog.json", expected_catalog_version)

        # ID collision check
        existing_ids = io.all_module_ids(catalog, map_data)
        if module_id in existing_ids:
            raise IdCollisionError(
                f"Module ID {module_id} already exists",
                details={"module_id": module_id, "existing": sorted(existing_ids)},
                fix_hint="Choose next available M-NNN or use rename_module_slug if intent was to change slug.",
            )

        # Verify depends-on exist
        for dep_id in depends_on:
            if dep_id not in existing_ids:
                raise NotFoundError(
                    f"Dependency module {dep_id} not found",
                    details={"missing": dep_id, "module_id": module_id},
                )

        # Compute paths + content
        mod_path = io.module_dir(ws, module_id, slug)
        mod_path_rel = str(mod_path.relative_to(ws)).replace("\\", "/")
        stages_queue = _stages_queue_for_path(risk_path, agent_flags)

        ctx = {
            "module_id": module_id,
            "module_name": module_name,
            "slug": slug,
            "modules_in_scope": modules_in_scope,
            "depends_on": depends_on,
            "primary_service": primary_service,
            "agent_flags": agent_flags,
            "business_goal": business_goal,
            "output_mode": output_mode,
            "repo_type": _detect_repo_type(ws),
            "stages_queue": stages_queue,
            "created_at": utc_iso_now(),
            "services": agent_flags.get("services", []),
        }
        state_md = render_template("module/_state.md.j2", ctx)
        brief_md = render_template("module/module-brief.md.j2", ctx)
        impl_yaml = render_template("module/implementations.yaml.j2", ctx)

        # Update catalog + map
        new_module = {
            "id": module_id,
            "name": module_name,
            "slug": slug,
            "status": "in-progress",
            "depends_on": depends_on,
            "feature_ids": [],
            "primary_service": primary_service,
            "modules_in_scope": modules_in_scope,
            "created_at": ctx["created_at"],
            "agent_flags": agent_flags,
        }
        catalog["modules"].append(new_module)
        map_data["modules"][module_id] = {
            "name": module_name,
            "slug": slug,
            "path": mod_path_rel,
        }

        catalog_content = io.serialize_json(catalog)
        map_content = io.serialize_yaml(map_data)

        # Multi-file transaction
        tx = FileTransaction()
        tx.add(mod_path / "_state.md", state_md)
        tx.add(mod_path / "module-brief.md", brief_md)
        tx.add(mod_path / "implementations.yaml", impl_yaml)
        for sub in ("ba", "sa", "designer", "security", "tech-lead", "qa", "reviewer"):
            tx.add(mod_path / sub / ".gitkeep", "")
        tx.add(io.module_catalog_path(ws), catalog_content)
        tx.add(io.module_map_path(ws), map_content)
        finals = tx.commit()

        # Bump versions in _meta
        new_cat_v = bump_artifact(
            meta, "module-catalog.json", content=catalog_content, producer="etc-platform/scaffold_module"
        )
        new_map_v = bump_artifact(
            meta, "module-map.yaml", content=map_content, producer="etc-platform/scaffold_module"
        )
        write_meta(ws, meta)

    return success_response(
        {
            "module_id": module_id,
            "module_path": mod_path_rel,
            "files_created": [str(p.relative_to(ws)).replace("\\", "/") for p in finals],
            "intel_updated": ["docs/intel/module-catalog.json", "docs/intel/module-map.yaml"],
            "new_versions": {
                "module-catalog.json": new_cat_v,
                "module-map.yaml": new_map_v,
            },
            "stages_queue": stages_queue,
        }
    )


# ---------------------------------------------------------------------------
# scaffold_feature (§3.4)
# ---------------------------------------------------------------------------


def scaffold_feature_impl(
    workspace_path: str,
    module_id: str,
    feature_id: str,
    feature_name: str,
    slug: str,
    *,
    description: str = "",
    business_intent: str = "",
    flow_summary: str = "",
    acceptance_criteria: list[str] | None = None,
    consumed_by_modules: list[str] | None = None,
    priority: str = "medium",
    expected_module_version: int | None = None,
) -> dict[str, Any]:
    """Atomic create feature nested under module + cross-update catalogs/maps. Per p0 §3.4."""
    ws = validate_workspace_path(workspace_path)

    if not is_valid_module_id(module_id):
        raise InvalidInputError(f"Invalid module_id: {module_id!r}", details={"module_id": module_id})
    if not is_valid_feature_id(feature_id):
        raise InvalidInputError(f"Invalid feature_id: {feature_id!r}", details={"feature_id": feature_id})
    if not is_valid_slug(slug):
        raise InvalidInputError(f"Invalid slug: {slug!r}", details={"slug": slug})
    if priority not in ("critical", "high", "medium", "low"):
        raise InvalidInputError(f"Invalid priority: {priority!r}", details={"priority": priority})

    consumed_by_modules = consumed_by_modules or []
    acceptance_criteria = acceptance_criteria or []

    with workspace_lock(str(ws)):
        mod_catalog = io.read_module_catalog(ws)
        feat_catalog = io.read_feature_catalog(ws)
        mod_map = io.read_module_map(ws)
        feat_map = io.read_feature_map(ws)
        meta = read_meta(ws)

        assert_version(meta, "module-catalog.json", expected_module_version)

        # Verify parent module exists
        parent = io.find_module(mod_catalog, module_id)
        if not parent:
            raise NotFoundError(
                f"Parent module {module_id} not found",
                details={"module_id": module_id, "feature_id": feature_id},
                fix_hint="Run scaffold_module first.",
            )
        module_slug = parent["slug"]

        # Feature ID collision check
        existing_feat_ids = io.all_feature_ids(feat_catalog, feat_map)
        if feature_id in existing_feat_ids:
            raise IdCollisionError(
                f"Feature ID {feature_id} already exists",
                details={"feature_id": feature_id},
            )

        # Verify consumed_by_modules exist
        all_mod_ids = io.all_module_ids(mod_catalog, mod_map)
        for mid in consumed_by_modules:
            if mid not in all_mod_ids:
                raise NotFoundError(
                    f"consumed_by module {mid} not found",
                    details={"missing": mid, "feature_id": feature_id},
                )

        feat_path = io.feature_dir(ws, module_id, module_slug, feature_id, slug)
        feat_path_rel = str(feat_path.relative_to(ws)).replace("\\", "/")

        ctx = {
            "feature_id": feature_id,
            "feature_name": feature_name,
            "slug": slug,
            "module_id": module_id,
            "description": description,
            "business_intent": business_intent,
            "flow_summary": flow_summary,
            "acceptance_criteria": acceptance_criteria,
            "consumed_by_modules": consumed_by_modules,
            "priority": priority,
            "created_at": utc_iso_now(),
        }
        feature_md = render_template("feature/_feature.md.j2", ctx)
        impl_yaml = render_template("feature/implementations.yaml.j2", ctx)
        evidence_json = render_template("feature/test-evidence.json.j2", ctx)

        # Update catalogs + maps
        new_feature: dict[str, Any] = {
            "id": feature_id,
            "module_id": module_id,
            "name": feature_name,
            "slug": slug,
            "status": "proposed",
            "priority": priority,
            "consumed_by_modules": consumed_by_modules,
        }
        # Required-by-schema fields filled with placeholder if caller didn't provide
        if description:
            new_feature["description"] = description
        if business_intent:
            new_feature["business_intent"] = business_intent
        if flow_summary:
            new_feature["flow_summary"] = flow_summary
        if acceptance_criteria:
            new_feature["acceptance_criteria"] = acceptance_criteria

        feat_catalog["features"].append(new_feature)
        feat_map["features"][feature_id] = {
            "module": module_id,
            "name": feature_name,
            "slug": slug,
            "path": feat_path_rel,
            "status": "proposed",
        }
        # Append to parent module's feature_ids
        parent.setdefault("feature_ids", []).append(feature_id)

        feat_catalog_content = io.serialize_json(feat_catalog)
        feat_map_content = io.serialize_yaml(feat_map)
        mod_catalog_content = io.serialize_json(mod_catalog)

        tx = FileTransaction()
        tx.add(feat_path / "_feature.md", feature_md)
        tx.add(feat_path / "implementations.yaml", impl_yaml)
        tx.add(feat_path / "test-evidence.json", evidence_json)
        for sub in ("dev", "qa"):
            tx.add(feat_path / sub / ".gitkeep", "")
        tx.add(io.feature_catalog_path(ws), feat_catalog_content)
        tx.add(io.feature_map_path(ws), feat_map_content)
        tx.add(io.module_catalog_path(ws), mod_catalog_content)
        finals = tx.commit()

        new_feat_cat_v = bump_artifact(
            meta, "feature-catalog.json", content=feat_catalog_content, producer="etc-platform/scaffold_feature"
        )
        new_feat_map_v = bump_artifact(
            meta, "feature-map.yaml", content=feat_map_content, producer="etc-platform/scaffold_feature"
        )
        new_mod_cat_v = bump_artifact(
            meta, "module-catalog.json", content=mod_catalog_content, producer="etc-platform/scaffold_feature"
        )
        write_meta(ws, meta)

    return success_response(
        {
            "feature_id": feature_id,
            "module_id": module_id,
            "feature_path": feat_path_rel,
            "files_created": [str(p.relative_to(ws)).replace("\\", "/") for p in finals],
            "intel_updated": [
                "docs/intel/feature-catalog.json",
                "docs/intel/feature-map.yaml",
                "docs/intel/module-catalog.json",
            ],
            "new_versions": {
                "feature-catalog.json": new_feat_cat_v,
                "feature-map.yaml": new_feat_map_v,
                "module-catalog.json": new_mod_cat_v,
            },
        }
    )


# ---------------------------------------------------------------------------
# scaffold_hotfix (§3.5)
# ---------------------------------------------------------------------------


def scaffold_hotfix_impl(
    workspace_path: str,
    hotfix_id: str,
    hotfix_name: str,
    slug: str,
    patch_summary: str,
    *,
    affected_modules: list[str] | None = None,
    severity: str = "high",
    severity_rationale: str = "",
) -> dict[str, Any]:
    """Create hotfix entry with skip-ba-sa flow. Per p0 §3.5."""
    ws = validate_workspace_path(workspace_path)

    if not is_valid_hotfix_id(hotfix_id):
        raise InvalidInputError(f"Invalid hotfix_id: {hotfix_id!r}", details={"hotfix_id": hotfix_id})
    if not is_valid_slug(slug):
        raise InvalidInputError(f"Invalid slug: {slug!r}", details={"slug": slug})
    if severity not in ("critical", "high", "medium"):
        raise InvalidInputError(f"Invalid severity: {severity!r}", details={"severity": severity})
    if len(patch_summary) < 50:
        raise InvalidInputError(
            "patch_summary too short (min 50 chars)",
            details={"length": len(patch_summary)},
        )

    affected_modules = affected_modules or []

    with workspace_lock(str(ws)):
        # Verify affected modules exist (warning only, not blocking)
        mod_catalog = io.read_module_catalog(ws)
        mod_map = io.read_module_map(ws)
        all_mod_ids = io.all_module_ids(mod_catalog, mod_map)
        unknown = [m for m in affected_modules if m not in all_mod_ids]

        # Check hotfix folder doesn't exist
        hf_path = io.hotfix_dir(ws, hotfix_id, slug)
        if hf_path.exists():
            raise IdCollisionError(
                f"Hotfix folder already exists: {hf_path.relative_to(ws)}",
                details={"hotfix_id": hotfix_id, "path": str(hf_path.relative_to(ws))},
            )

        ctx = {
            "hotfix_id": hotfix_id,
            "hotfix_name": hotfix_name,
            "slug": slug,
            "patch_summary": patch_summary,
            "affected_modules": affected_modules,
            "severity": severity,
            "severity_rationale": severity_rationale,
            "repo_type": _detect_repo_type(ws),
            "created_at": utc_iso_now(),
        }
        state_md = render_template("hotfix/_state.md.j2", ctx)
        brief_md = render_template("hotfix/patch-brief.md.j2", ctx)
        impl_yaml = render_template("hotfix/implementations.yaml.j2", ctx)

        tx = FileTransaction()
        tx.add(hf_path / "_state.md", state_md)
        tx.add(hf_path / "patch-brief.md", brief_md)
        tx.add(hf_path / "implementations.yaml", impl_yaml)
        for sub in ("tech-lead", "dev", "qa", "reviewer"):
            tx.add(hf_path / sub / ".gitkeep", "")
        finals = tx.commit()

    warnings: list[dict[str, Any]] = []
    if unknown:
        warnings.append(
            {
                "code": "AFFECTED_MODULE_UNKNOWN",
                "message": f"affected_modules contains unknown IDs: {unknown}",
                "ids": unknown,
            }
        )

    return success_response(
        {
            "hotfix_id": hotfix_id,
            "hotfix_path": str(hf_path.relative_to(ws)).replace("\\", "/"),
            "files_created": [str(p.relative_to(ws)).replace("\\", "/") for p in finals],
            "severity": severity,
            "affected_modules": affected_modules,
        },
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# scaffold_app_or_service (§3.2)
# ---------------------------------------------------------------------------


def scaffold_app_or_service_impl(
    workspace_path: str,
    name: str,
    kind: str,
    stack: str = "none",
    *,
    expected_workspace_version: int | None = None,
) -> dict[str, Any]:
    """Add 1 deployable project (app/service/lib/package) to monorepo. Per p0 §3.2.

    Stack-specific scaffolding deferred to future image versions; current
    implementation creates minimal directory + .gitkeep so subsequent dev
    can populate per stack convention manually.
    """
    ws = validate_workspace_path(workspace_path)

    if kind not in ("app", "service", "lib", "package"):
        raise InvalidInputError(
            f"Invalid kind: {kind!r} (expected app|service|lib|package)",
            details={"kind": kind},
        )
    if not name or not name.replace("-", "").isalnum() or not name[0].isalpha():
        raise InvalidInputError(
            f"Invalid name: {name!r} (must be lowercase kebab-case, start with letter)",
            details={"name": name},
        )

    if not _is_mono_repo(ws):
        raise NotMonoRepoError(
            "scaffold_app_or_service requires monorepo workspace",
            details={"workspace_path": str(ws)},
            fix_hint="Initialize workspace with workspace_type='mono' first.",
        )

    plural = {"app": "apps", "service": "services", "lib": "libs", "package": "packages"}[kind]
    project_path = ws / plural / name
    if project_path.exists():
        raise AlreadyExistsError(
            f"{kind} {name!r} already exists",
            details={"path": str(project_path.relative_to(ws))},
        )

    with workspace_lock(str(ws)):
        tx = FileTransaction()
        tx.add(project_path / ".gitkeep", "")
        tx.add(project_path / "src" / ".gitkeep", "")
        tx.add(
            project_path / "README.md",
            f"# {name}\n\nKind: {kind}\nStack: {stack}\n",
        )
        finals = tx.commit()

    return success_response(
        {
            "project_path": str(project_path.relative_to(ws)).replace("\\", "/"),
            "kind": kind,
            "name": name,
            "stack": stack,
            "files_created": [str(p.relative_to(ws)).replace("\\", "/") for p in finals],
            "warnings": [
                {
                    "code": "STACK_TEMPLATE_DEFERRED",
                    "message": f"Stack template '{stack}' not bundled yet; populated minimal scaffold only.",
                }
            ],
        }
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detect_repo_type(ws: Path) -> str:
    """Detect repo-type from AGENTS.md or workspace structure."""
    if _is_mono_repo(ws):
        return "mono"
    return "mini"


def _is_mono_repo(ws: Path) -> bool:
    """Check if workspace is monorepo (has apps/ services/ libs/ + workspace tool)."""
    has_workspace_tool = any(
        (ws / f).exists()
        for f in ("nx.json", "turbo.json", "pnpm-workspace.yaml", "lerna.json")
    )
    has_project_dirs = any((ws / d).is_dir() for d in ("apps", "services", "libs", "packages"))
    return has_workspace_tool or has_project_dirs


def _stages_queue_for_path(risk_path: str, agent_flags: dict[str, Any]) -> list[str]:
    """Compute stages-queue per risk path + conditional inserts (designer, security)."""
    if risk_path == "S":
        base = list(_DEFAULT_STAGES_QUEUE_S)
    elif risk_path == "L":
        base = list(_DEFAULT_STAGES_QUEUE_L)
    else:
        base = list(_DEFAULT_STAGES_QUEUE_M)

    # Conditional: designer if screens > 0
    designer_flags = agent_flags.get("designer", {})
    if designer_flags and designer_flags.get("screen_count", 0) > 0:
        if "designer" not in base:
            # Insert before sa (or at start if no sa)
            try:
                idx = base.index("sa")
                base.insert(idx, "designer")
            except ValueError:
                base.insert(0, "designer")

    # Conditional: security-design if PII found AND not already present
    security_flags = agent_flags.get("security", {})
    if security_flags.get("pii_found") and "security-design" not in base:
        try:
            idx = base.index("tech-lead")
            base.insert(idx, "security-design")
        except ValueError:
            pass

    return base


def _minimal_agents_md(workspace_name: str, workspace_type: str, stack: str) -> str:
    return (
        f"# {workspace_name}\n\n"
        f"workspace-type: {workspace_type}\n"
        f"repo-type: {workspace_type}\n"
        f"stack: {stack}\n\n"
        "## Convention\n\n"
        "All SDLC scaffolding goes through `etc-platform` MCP tools (CD-8 v3).\n"
        "Skills MUST NOT Write/mkdir under docs/{modules,features,hotfixes}/**.\n"
    )


def _minimal_claude_md(workspace_name: str) -> str:
    return (
        f"# {workspace_name}\n\n"
        "## Project context\n\n"
        "(Populated during ba/sa stages.)\n"
    )


def _minimal_gitignore(stack: str) -> str:
    base = "# OS\n.DS_Store\nThumbs.db\n\n# IDE\n.vscode/\n.idea/\n\n# Env\n.env\n.env.local\n\n"
    stack_rules = {
        "nodejs": "node_modules/\ndist/\n.next/\n*.log\n",
        "python": "__pycache__/\n*.pyc\n.venv/\n.pytest_cache/\n.mypy_cache/\n",
        "go": "*.exe\nvendor/\n",
        "rust": "target/\nCargo.lock\n",
    }
    return base + stack_rules.get(stack, "")


def _minimal_editorconfig() -> str:
    return (
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
        "indent_style = tab\n"
    )
