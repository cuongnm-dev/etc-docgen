"""verify — consolidated structural integrity check (8 scopes via discriminator).

Per p0 §3.10 + ADR-003 D7/D10-6. Read-only; replaces 8 separate verify_*
tools with single tool + ``scopes[]`` parameter.

Scopes:
    structure          — filesystem layout matches locked tree
    schemas            — JSON Schema validation for catalogs + frontmatter
    ownership          — single-writer rule (CD-10 §1) — needs context.agent_log
    cross_references   — FK integrity (feature.module_id ∈ modules, etc.)
    freshness          — TTL exceeded; hash mismatch with sources
    completeness       — required artifacts for context.current_stage exist
    id_uniqueness      — duplicate IDs (catches F-061 bug class)
    all                — aggregator
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from etc_platform.paths import schemas_dir
from etc_platform.sdlc import intel_io as io
from etc_platform.sdlc.errors import (
    InvalidInputError,
    VerificationFailedError,
    success_response,
)
from etc_platform.sdlc.frontmatter import read_frontmatter
from etc_platform.sdlc.path_validation import validate_workspace_path

_VALID_SCOPES = {
    "structure",
    "schemas",
    "ownership",
    "cross_references",
    "freshness",
    "completeness",
    "id_uniqueness",
    "all",
}
_STRICT_MODES = ("block", "warn", "info")
_SEVERITY_HIGH = "high"
_SEVERITY_MEDIUM = "medium"
_SEVERITY_LOW = "low"


def verify_impl(
    workspace_path: str,
    scopes: list[str],
    *,
    strict_mode: str = "warn",
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run requested verify scopes; aggregate findings + summary.

    Args:
        scopes: subset of _VALID_SCOPES. 'all' expands to all 7 specific scopes.
        strict_mode: 'block' raises VerificationFailedError on HIGH severity.
                     'warn' returns success with warnings. 'info' suppresses
                     to data only.
        context: { current_stage, feature_id, agent_log } — used by some scopes.

    Returns:
        { summary: { passed, failed, warnings, info }, findings: [...] }
    """
    ws = validate_workspace_path(workspace_path)
    context = context or {}

    if not scopes:
        raise InvalidInputError("scopes is empty", details={"scopes": scopes})

    invalid = [s for s in scopes if s not in _VALID_SCOPES]
    if invalid:
        raise InvalidInputError(
            f"Invalid scopes: {invalid}",
            details={"invalid": invalid, "valid": sorted(_VALID_SCOPES)},
        )
    if strict_mode not in _STRICT_MODES:
        raise InvalidInputError(
            f"Invalid strict_mode: {strict_mode!r}",
            details={"strict_mode": strict_mode, "valid": list(_STRICT_MODES)},
        )

    expanded = set(scopes)
    if "all" in expanded:
        expanded = _VALID_SCOPES - {"all"}

    findings: list[dict[str, Any]] = []
    if "structure" in expanded:
        findings.extend(_check_structure(ws))
    if "schemas" in expanded:
        findings.extend(_check_schemas(ws))
    if "ownership" in expanded:
        findings.extend(_check_ownership(ws, context.get("agent_log", [])))
    if "cross_references" in expanded:
        findings.extend(_check_cross_references(ws))
    if "freshness" in expanded:
        findings.extend(_check_freshness(ws))
    if "completeness" in expanded:
        findings.extend(_check_completeness(ws, context.get("current_stage")))
    if "id_uniqueness" in expanded:
        findings.extend(_check_id_uniqueness(ws))

    summary = _aggregate(findings)

    if strict_mode == "block" and summary["failed"] > 0:
        raise VerificationFailedError(
            f"{summary['failed']} HIGH-severity violation(s) detected",
            details={"summary": summary, "findings": findings},
        )

    return success_response(
        {
            "summary": summary,
            "findings": findings,
            "scopes_checked": sorted(expanded),
            "strict_mode": strict_mode,
        }
    )


# ---------------------------------------------------------------------------
# scope: structure
# ---------------------------------------------------------------------------


_REQUIRED_INTEL_FILES = (
    "_meta.json",
    "feature-catalog.json",
    "module-catalog.json",
    "module-map.yaml",
    "feature-map.yaml",
)
_REQUIRED_DIRS = ("docs/intel", "docs/inputs", "docs/generated")


def _check_structure(ws: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for d in _REQUIRED_DIRS:
        if not (ws / d).is_dir():
            findings.append(
                _finding(
                    "structure",
                    _SEVERITY_HIGH,
                    "missing-required-dir",
                    str(d),
                    f"Required directory missing: {d}",
                    fix_hint="Run scaffold_workspace OR autofix(missing-scaffold).",
                )
            )

    intel = ws / "docs" / "intel"
    if intel.is_dir():
        for f in _REQUIRED_INTEL_FILES:
            if not (intel / f).exists():
                findings.append(
                    _finding(
                        "structure",
                        _SEVERITY_HIGH,
                        "missing-required-intel-file",
                        f"docs/intel/{f}",
                        f"Required intel file missing: {f}",
                    )
                )

    # Folder name pattern check: docs/modules/M-NNN-{slug}/
    modules_dir = ws / "docs" / "modules"
    if modules_dir.is_dir():
        pat = re.compile(r"^M-[0-9]{3,}-[a-z][a-z0-9]*(-[a-z0-9]+)*$")
        for child in modules_dir.iterdir():
            if child.is_dir() and not pat.match(child.name):
                findings.append(
                    _finding(
                        "structure",
                        _SEVERITY_MEDIUM,
                        "module-folder-name-malformed",
                        f"docs/modules/{child.name}",
                        f"Module folder name doesn't match M-NNN-{{slug}} pattern",
                    )
                )

    return findings


# ---------------------------------------------------------------------------
# scope: schemas
# ---------------------------------------------------------------------------


def _check_schemas(ws: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    intel_schemas = schemas_dir() / "intel"

    pairs = [
        ("module-catalog.json", "module-catalog.schema.json", "json"),
        ("feature-catalog.json", "feature-catalog.schema.json", "json"),
        ("module-map.yaml", "module-map.yaml.schema.json", "yaml"),
        ("feature-map.yaml", "feature-map.yaml.schema.json", "yaml"),
        ("id-aliases.json", "id-aliases.json.schema.json", "json"),
    ]

    for artifact_name, schema_name, fmt in pairs:
        artifact = ws / "docs" / "intel" / artifact_name
        schema = intel_schemas / schema_name
        if not artifact.exists() or not schema.exists():
            continue
        try:
            data = (
                json.loads(artifact.read_text(encoding="utf-8"))
                if fmt == "json"
                else yaml.safe_load(artifact.read_text(encoding="utf-8"))
            )
            schema_data = json.loads(schema.read_text(encoding="utf-8"))
            jsonschema.validate(data, schema_data)
        except jsonschema.ValidationError as exc:
            findings.append(
                _finding(
                    "schemas",
                    _SEVERITY_HIGH,
                    "schema-violation",
                    f"docs/intel/{artifact_name}",
                    f"Schema violation: {exc.message}",
                    details={"path": list(exc.absolute_path), "validator": exc.validator},
                )
            )
        except (json.JSONDecodeError, yaml.YAMLError) as exc:
            findings.append(
                _finding(
                    "schemas",
                    _SEVERITY_HIGH,
                    "parse-error",
                    f"docs/intel/{artifact_name}",
                    f"Parse error: {exc}",
                )
            )

    # Check _state.md frontmatter for each module + hotfix
    state_schema_path = intel_schemas / "_state.md.schema.json"
    if state_schema_path.exists():
        state_schema = json.loads(state_schema_path.read_text(encoding="utf-8"))
        for state_file in (ws / "docs" / "modules").rglob("_state.md"):
            if "/features/" in str(state_file).replace("\\", "/"):
                continue  # only module-level _state.md
            _validate_frontmatter(state_file, state_schema, "schemas", findings, ws)
        for state_file in (ws / "docs" / "hotfixes").rglob("_state.md"):
            _validate_frontmatter(state_file, state_schema, "schemas", findings, ws)

    return findings


def _validate_frontmatter(
    path: Path,
    schema: dict[str, Any],
    scope: str,
    findings: list[dict[str, Any]],
    ws: Path,
) -> None:
    try:
        fm, _ = read_frontmatter(path)
        jsonschema.validate(fm, schema)
    except jsonschema.ValidationError as exc:
        findings.append(
            _finding(
                scope,
                _SEVERITY_HIGH,
                "frontmatter-schema-violation",
                str(path.relative_to(ws)).replace("\\", "/"),
                f"Frontmatter schema violation: {exc.message}",
                details={"path": list(exc.absolute_path)},
            )
        )
    except Exception as exc:
        findings.append(
            _finding(
                scope,
                _SEVERITY_MEDIUM,
                "frontmatter-parse-error",
                str(path.relative_to(ws)).replace("\\", "/"),
                f"Frontmatter parse error: {exc}",
            )
        )


# ---------------------------------------------------------------------------
# scope: ownership
# ---------------------------------------------------------------------------


def _check_ownership(ws: Path, agent_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ownership check requires agent_log input. Skeleton — full impl P1."""
    findings: list[dict[str, Any]] = []
    if not agent_log:
        findings.append(
            _finding(
                "ownership",
                _SEVERITY_LOW,
                "no-agent-log",
                "",
                "No agent_log provided — ownership check skipped",
            )
        )
    # TODO P1: cross-check each agent_log entry against ownership matrix
    # (Producer: ba writes ba/00-lean-spec.md; sa writes sa/...; etc.)
    return findings


# ---------------------------------------------------------------------------
# scope: cross_references
# ---------------------------------------------------------------------------


def _check_cross_references(ws: Path) -> list[dict[str, Any]]:
    """FK integrity — feature.module_id ∈ modules, etc."""
    findings: list[dict[str, Any]] = []
    mod_catalog = io.read_module_catalog(ws)
    feat_catalog = io.read_feature_catalog(ws)
    mod_map = io.read_module_map(ws)
    feat_map = io.read_feature_map(ws)

    all_mod_ids = io.all_module_ids(mod_catalog, mod_map)

    # feature.module_id ∈ modules
    for feat in feat_catalog.get("features", []):
        fid = feat.get("id")
        mid = feat.get("module_id")
        if not mid:
            findings.append(
                _finding(
                    "cross_references",
                    _SEVERITY_HIGH,
                    "feature-missing-module_id",
                    f"feature {fid}",
                    f"Feature {fid} missing required module_id",
                )
            )
            continue
        if mid not in all_mod_ids:
            findings.append(
                _finding(
                    "cross_references",
                    _SEVERITY_HIGH,
                    "feature-module-fk-broken",
                    f"feature {fid}",
                    f"Feature {fid}.module_id={mid} not found in module-catalog/map",
                )
            )

        # consumed_by_modules ⊆ modules
        for cm in feat.get("consumed_by_modules", []):
            if cm not in all_mod_ids:
                findings.append(
                    _finding(
                        "cross_references",
                        _SEVERITY_MEDIUM,
                        "feature-consumed-by-fk-broken",
                        f"feature {fid}",
                        f"Feature {fid}.consumed_by_modules contains unknown {cm}",
                    )
                )

    # module.depends_on ⊆ modules
    for mod in mod_catalog.get("modules", []):
        mid = mod.get("id")
        for dep in mod.get("depends_on", []):
            if dep not in all_mod_ids:
                findings.append(
                    _finding(
                        "cross_references",
                        _SEVERITY_HIGH,
                        "module-depends-on-fk-broken",
                        f"module {mid}",
                        f"Module {mid}.depends_on={dep} not found",
                    )
                )

        # module.feature_ids ⊆ feature-catalog
        all_feat_ids = io.all_feature_ids(feat_catalog, feat_map)
        for fid in mod.get("feature_ids", []):
            if fid not in all_feat_ids:
                findings.append(
                    _finding(
                        "cross_references",
                        _SEVERITY_HIGH,
                        "module-feature-fk-broken",
                        f"module {mid}",
                        f"Module {mid}.feature_ids contains unknown {fid}",
                    )
                )

    # feature-map.module ∈ module-catalog
    for fid, entry in feat_map.get("features", {}).items():
        mid = entry.get("module")
        if mid and mid not in all_mod_ids:
            findings.append(
                _finding(
                    "cross_references",
                    _SEVERITY_HIGH,
                    "feature-map-module-fk-broken",
                    f"feature-map {fid}",
                    f"feature-map[{fid}].module={mid} not found",
                )
            )

    return findings


# ---------------------------------------------------------------------------
# scope: freshness
# ---------------------------------------------------------------------------


def _check_freshness(ws: Path) -> list[dict[str, Any]]:
    """TTL + hash mismatch via _meta.json."""
    findings: list[dict[str, Any]] = []
    meta_path = ws / "docs" / "intel" / "_meta.json"
    if not meta_path.exists():
        findings.append(
            _finding(
                "freshness",
                _SEVERITY_HIGH,
                "missing-meta",
                "docs/intel/_meta.json",
                "_meta.json missing — cannot check freshness",
            )
        )
        return findings

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        findings.append(
            _finding(
                "freshness",
                _SEVERITY_HIGH,
                "meta-parse-error",
                "docs/intel/_meta.json",
                f"Parse error: {exc}",
            )
        )
        return findings

    now = datetime.now(UTC)
    for art_name, entry in meta.get("artifacts", {}).items():
        ttl_days = entry.get("ttl_days")
        if ttl_days is None:
            continue
        last_modified = entry.get("last_modified")
        if not last_modified:
            continue
        try:
            lm = datetime.fromisoformat(last_modified.replace("Z", "+00:00"))
        except ValueError:
            continue
        age_days = (now - lm).days
        if age_days > ttl_days:
            findings.append(
                _finding(
                    "freshness",
                    _SEVERITY_MEDIUM,
                    "ttl-exceeded",
                    f"docs/intel/{art_name}",
                    f"{art_name}: age {age_days}d > TTL {ttl_days}d",
                )
            )

        # Hash check: re-compute current sha256 vs stored
        art_path = ws / "docs" / "intel" / art_name
        if art_path.exists() and entry.get("content_hash"):
            current_hash = hashlib.sha256(art_path.read_bytes()).hexdigest()
            stored = entry["content_hash"].replace("sha256:", "")
            if current_hash != stored:
                findings.append(
                    _finding(
                        "freshness",
                        _SEVERITY_MEDIUM,
                        "content-hash-mismatch",
                        f"docs/intel/{art_name}",
                        f"{art_name}: stored hash != current (modified outside MCP?)",
                    )
                )

    return findings


# ---------------------------------------------------------------------------
# scope: completeness
# ---------------------------------------------------------------------------


_STAGE_REQUIRED_ARTIFACTS = {
    "ba": ["ba/00-lean-spec.md"],
    "sa": ["sa/00-lean-architecture.md"],
    "designer": ["designer/01-wireframes.md"],
    "tech-lead": ["tech-lead/04-plan.md"],
    "qa-wave-1": ["qa/07-qa-report-w1.md"],
    "reviewer": ["reviewer/08-review-report.md"],
    "security-design": ["security/03-threat-model.md"],
    "security-review": ["security/06-security-review.md"],
}


def _check_completeness(ws: Path, current_stage: str | None) -> list[dict[str, Any]]:
    """Required artifacts per current_stage exist + non-empty."""
    findings: list[dict[str, Any]] = []
    if not current_stage:
        findings.append(
            _finding(
                "completeness",
                _SEVERITY_LOW,
                "no-current-stage",
                "",
                "No current_stage in context — completeness check skipped",
            )
        )
        return findings

    required = _STAGE_REQUIRED_ARTIFACTS.get(current_stage)
    if required is None:
        return findings  # unknown stage — skip

    for module_dir in (ws / "docs" / "modules").iterdir() if (ws / "docs" / "modules").exists() else []:
        if not module_dir.is_dir():
            continue
        for rel in required:
            artifact = module_dir / rel
            if not artifact.exists() or artifact.stat().st_size == 0:
                findings.append(
                    _finding(
                        "completeness",
                        _SEVERITY_HIGH,
                        "missing-stage-artifact",
                        str(artifact.relative_to(ws)).replace("\\", "/"),
                        f"Required for stage '{current_stage}': {rel}",
                    )
                )

    return findings


# ---------------------------------------------------------------------------
# scope: id_uniqueness — catches F-061 bug class (D10-6)
# ---------------------------------------------------------------------------


_ID_RE = re.compile(r"^([MFH])-([0-9]+)([a-z]?)$")


def _check_id_uniqueness(ws: Path) -> list[dict[str, Any]]:
    """Detect ID collisions + unjustified gaps. Catches F-061 bug class."""
    findings: list[dict[str, Any]] = []

    mod_catalog = io.read_module_catalog(ws)
    feat_catalog = io.read_feature_catalog(ws)
    mod_map = io.read_module_map(ws)
    feat_map = io.read_feature_map(ws)
    aliases = io.read_id_aliases(ws)

    # Collect IDs from each source
    sources: dict[str, set[str]] = defaultdict(set)
    for m in mod_catalog.get("modules", []):
        if mid := m.get("id"):
            sources["module-catalog"].add(mid)
    for mid in mod_map.get("modules", {}):
        sources["module-map"].add(mid)

    for f in feat_catalog.get("features", []):
        if fid := f.get("id"):
            sources["feature-catalog"].add(fid)
    for fid in feat_map.get("features", {}):
        sources["feature-map"].add(fid)

    # Filesystem
    if (ws / "docs" / "modules").exists():
        for child in (ws / "docs" / "modules").iterdir():
            if child.is_dir():
                m = re.match(r"^(M-[0-9]+)-", child.name)
                if m:
                    sources["filesystem-modules"].add(m.group(1))
        for child in (ws / "docs" / "modules").rglob("F-*-*"):
            if child.is_dir() and child.parent.name == "features":
                m = re.match(r"^(F-[0-9]+[a-z]?)-", child.name)
                if m:
                    sources["filesystem-features"].add(m.group(1))

    if (ws / "docs" / "hotfixes").exists():
        for child in (ws / "docs" / "hotfixes").iterdir():
            if child.is_dir():
                m = re.match(r"^(H-[0-9]+)-", child.name)
                if m:
                    sources["filesystem-hotfixes"].add(m.group(1))

    # Detect: same ID across multiple sources but with mismatched info
    # Currently only check union for collision sanity; deep mismatch (slug,
    # name) check is deferred to verify(scopes=['cross_references']).

    # Detect gaps: per kind, collect numeric IDs, find sequence gaps > 10
    reservations = _parse_reservations(aliases.get("reservations", []))
    for kind_prefix, label in (("M", "module"), ("F", "feature"), ("H", "hotfix")):
        all_ids: set[str] = set()
        for src_name, src_ids in sources.items():
            for sid in src_ids:
                if sid.startswith(kind_prefix + "-"):
                    all_ids.add(sid)
        if not all_ids:
            continue
        nums = sorted(_extract_num(sid) for sid in all_ids if _extract_num(sid) is not None)
        if not nums:
            continue
        prev = nums[0]
        for n in nums[1:]:
            gap = n - prev - 1
            if gap > 0:
                gap_start = prev + 1
                gap_end = n - 1
                gap_range = f"{kind_prefix}-{gap_start:03d}..{kind_prefix}-{gap_end:03d}"
                if gap > 10 and not _is_reserved(gap_start, gap_end, kind_prefix, reservations):
                    findings.append(
                        _finding(
                            "id_uniqueness",
                            _SEVERITY_MEDIUM,
                            "unjustified-gap",
                            f"{kind_prefix}-NNN sequence",
                            f"Unjustified gap > 10 IDs at {gap_range} ({gap} missing). "
                            "Add id-aliases.json reservations entry to justify.",
                        )
                    )
                elif gap > 1:
                    findings.append(
                        _finding(
                            "id_uniqueness",
                            _SEVERITY_LOW,
                            "non-contiguous",
                            f"{kind_prefix}-NNN sequence",
                            f"Non-contiguous ID gap at {gap_range} ({gap} missing)",
                        )
                    )
            prev = n

    # Detect: filesystem entry not in catalog (orphan folders)
    fs_only_modules = sources.get("filesystem-modules", set()) - sources.get("module-catalog", set())
    for mid in fs_only_modules:
        findings.append(
            _finding(
                "id_uniqueness",
                _SEVERITY_HIGH,
                "filesystem-orphan",
                f"docs/modules/{mid}-*",
                f"Module folder {mid} exists on filesystem but not in module-catalog",
                fix_hint="Run autofix(missing-scaffold) OR remove orphan folder.",
            )
        )
    fs_only_features = sources.get("filesystem-features", set()) - sources.get("feature-catalog", set())
    for fid in fs_only_features:
        findings.append(
            _finding(
                "id_uniqueness",
                _SEVERITY_HIGH,
                "filesystem-orphan",
                f"feature {fid}",
                f"Feature folder {fid} exists on filesystem but not in feature-catalog",
            )
        )

    # Detect: catalog entry without filesystem
    cat_only_modules = sources.get("module-catalog", set()) - sources.get("filesystem-modules", set())
    for mid in cat_only_modules:
        findings.append(
            _finding(
                "id_uniqueness",
                _SEVERITY_HIGH,
                "catalog-orphan",
                f"module-catalog {mid}",
                f"Module {mid} in catalog but no folder on filesystem",
            )
        )

    return findings


def _extract_num(sid: str) -> int | None:
    m = _ID_RE.match(sid)
    if not m:
        return None
    return int(m.group(2))


def _parse_reservations(items: list[dict[str, Any]]) -> list[tuple[str, int, int]]:
    """Parse [{range: 'F-061..F-080'}] → [('F', 61, 80)]."""
    out: list[tuple[str, int, int]] = []
    pat = re.compile(r"^([MFH])-([0-9]+)\.\.\1-([0-9]+)$")
    for item in items:
        rng = item.get("range", "")
        m = pat.match(rng)
        if m:
            out.append((m.group(1), int(m.group(2)), int(m.group(3))))
    return out


def _is_reserved(
    start: int,
    end: int,
    kind: str,
    reservations: list[tuple[str, int, int]],
) -> bool:
    return any(
        r_kind == kind and r_start <= start and end <= r_end for r_kind, r_start, r_end in reservations
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _finding(
    scope: str,
    severity: str,
    rule: str,
    location: str,
    message: str,
    *,
    fix_hint: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "scope": scope,
        "severity": severity,
        "rule": rule,
        "location": location,
        "message": message,
    }
    if fix_hint:
        finding["fix_hint"] = fix_hint
    if details:
        finding["details"] = details
    return finding


def _aggregate(findings: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"passed": 0, "failed": 0, "warnings": 0, "info": 0}
    for f in findings:
        sev = f.get("severity")
        if sev == _SEVERITY_HIGH:
            summary["failed"] += 1
        elif sev == _SEVERITY_MEDIUM:
            summary["warnings"] += 1
        else:
            summary["info"] += 1
    return summary
