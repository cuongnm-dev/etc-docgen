"""Integration tests for SDLC tool workflows.

End-to-end + concurrent + F-061 bug detection scenarios.
"""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest
import yaml

from etc_platform.sdlc.errors import (
    DestructiveNotConfirmedError,
    ForbiddenError,
    InvalidInputError,
    NameCollisionError,
    NotFoundError,
    TemplateNotFoundError,
    VerificationFailedError,
)
from etc_platform.sdlc.refactor import rename_module_slug_impl
from etc_platform.sdlc.repair import autofix_impl
from etc_platform.sdlc.resolve import resolve_path_impl
from etc_platform.sdlc.scaffold import (
    scaffold_app_or_service_impl,
    scaffold_feature_impl,
    scaffold_hotfix_impl,
    scaffold_module_impl,
    scaffold_workspace_impl,
)
from etc_platform.sdlc.state import update_state_impl
from etc_platform.sdlc.template_registry import template_registry_impl
from etc_platform.sdlc.verify import verify_impl


@pytest.fixture
def workspace(tmp_path) -> Path:
    """Bootstrapped mini workspace ready for tests."""
    ws = tmp_path / "ws"
    ws.mkdir()
    scaffold_workspace_impl(str(ws), "mini", "nodejs")
    return ws


@pytest.fixture
def workspace_with_module(workspace) -> Path:
    """Workspace + 1 module M-001 iam."""
    scaffold_module_impl(
        str(workspace), "M-001", "Identity & Access", "iam",
        primary_service="services/iam",
        business_goal="Identity & access management",
    )
    return workspace


@pytest.fixture
def workspace_full(workspace_with_module) -> Path:
    """Workspace + module + feature."""
    scaffold_feature_impl(
        str(workspace_with_module), "M-001", "F-001", "VNeID Link", "vneid-link",
        priority="high",
        acceptance_criteria=["AC1", "AC2", "AC3"],
    )
    return workspace_with_module


# ---------------------------------------------------------------------------
# End-to-end scaffold workflow
# ---------------------------------------------------------------------------


class TestScaffoldWorkflow:
    def test_workspace_creates_intel_layer(self, workspace):
        intel = workspace / "docs" / "intel"
        assert (intel / "_meta.json").exists()
        assert (intel / "feature-catalog.json").exists()
        assert (intel / "module-catalog.json").exists()
        assert (intel / "module-map.yaml").exists()
        assert (intel / "feature-map.yaml").exists()

    def test_module_creates_atomic(self, workspace_with_module):
        mod_dir = workspace_with_module / "docs" / "modules" / "M-001-iam"
        assert mod_dir.is_dir()
        assert (mod_dir / "_state.md").exists()
        assert (mod_dir / "module-brief.md").exists()
        assert (mod_dir / "implementations.yaml").exists()
        for sub in ("ba", "sa", "designer", "security", "tech-lead", "qa", "reviewer"):
            assert (mod_dir / sub).is_dir()

    def test_module_updates_catalog_and_map(self, workspace_with_module):
        catalog = json.loads(
            (workspace_with_module / "docs" / "intel" / "module-catalog.json").read_text(encoding="utf-8")
        )
        assert len(catalog["modules"]) == 1
        assert catalog["modules"][0]["id"] == "M-001"
        assert catalog["modules"][0]["slug"] == "iam"

        map_data = yaml.safe_load(
            (workspace_with_module / "docs" / "intel" / "module-map.yaml").read_text(encoding="utf-8")
        )
        assert "M-001" in map_data["modules"]
        assert map_data["modules"]["M-001"]["path"] == "docs/modules/M-001-iam"

    def test_feature_nests_under_module(self, workspace_full):
        feat_dir = (
            workspace_full / "docs" / "modules" / "M-001-iam" / "features" / "F-001-vneid-link"
        )
        assert feat_dir.is_dir()
        assert (feat_dir / "_feature.md").exists()
        assert (feat_dir / "test-evidence.json").exists()

    def test_feature_updates_parent_module_feature_ids(self, workspace_full):
        catalog = json.loads(
            (workspace_full / "docs" / "intel" / "module-catalog.json").read_text(encoding="utf-8")
        )
        assert catalog["modules"][0]["feature_ids"] == ["F-001"]

    def test_resolve_path_module(self, workspace_with_module):
        r = resolve_path_impl(str(workspace_with_module), "module", "M-001", include_metadata=True)
        assert r["ok"] is True
        assert r["data"]["relative_path"] == "docs/modules/M-001-iam"
        assert r["data"]["metadata"]["slug"] == "iam"

    def test_resolve_path_feature(self, workspace_full):
        r = resolve_path_impl(str(workspace_full), "feature", "F-001", include_metadata=True)
        assert r["ok"] is True
        assert "F-001-vneid-link" in r["data"]["relative_path"]
        assert r["data"]["module_id"] == "M-001"

    def test_resolve_path_not_found(self, workspace):
        with pytest.raises(NotFoundError):
            resolve_path_impl(str(workspace), "module", "M-999")


# ---------------------------------------------------------------------------
# update_state — 5 ops
# ---------------------------------------------------------------------------


class TestUpdateState:
    def test_op_field(self, workspace_with_module):
        target = "docs/modules/M-001-iam/_state.md"
        r = update_state_impl(str(workspace_with_module), target, "field", field_path="current-stage", field_value="sa")
        assert r["ok"] is True
        assert r["data"]["new_value"] == "sa"

    def test_op_field_locked_rejected(self, workspace_with_module):
        target = workspace_with_module / "docs" / "modules" / "M-001-iam" / "_state.md"
        # Add 'feature-id' to locked-fields
        from etc_platform.sdlc.frontmatter import read_frontmatter, write_frontmatter
        fm, body = read_frontmatter(target)
        fm["locked-fields"] = ["feature-id"]
        write_frontmatter(target, fm, body)

        with pytest.raises(ForbiddenError):
            update_state_impl(
                str(workspace_with_module),
                "docs/modules/M-001-iam/_state.md",
                "field",
                field_path="feature-id",
                field_value="HACKED",
            )

    def test_op_progress_appends(self, workspace_with_module):
        target = "docs/modules/M-001-iam/_state.md"
        update_state_impl(str(workspace_with_module), target, "progress", stage="ba", verdict="Approved", artifact="ba/00.md")
        body = (workspace_with_module / target).read_text(encoding="utf-8")
        assert "Approved" in body

    def test_op_kpi_increment(self, workspace_with_module):
        target = "docs/modules/M-001-iam/_state.md"
        r = update_state_impl(str(workspace_with_module), target, "kpi", metric="tokens-total", delta_value=5000, kpi_op="increment")
        assert r["data"]["new_value"] == 5000
        r = update_state_impl(str(workspace_with_module), target, "kpi", metric="tokens-total", delta_value=3000, kpi_op="increment")
        assert r["data"]["new_value"] == 8000

    def test_op_log_appends(self, workspace_with_module):
        target = "docs/modules/M-001-iam/_state.md"
        update_state_impl(str(workspace_with_module), target, "log", log_kind="escalation", entry={"item": "Issue X", "decision": "Resolved by PM"})
        body = (workspace_with_module / target).read_text(encoding="utf-8")
        assert "Issue X" in body

    def test_op_status_cross_file(self, workspace_full):
        target = "docs/modules/M-001-iam/_state.md"
        r = update_state_impl(str(workspace_full), target, "status", entity_id="M-001", status="done")
        assert r["ok"] is True
        # Catalog also updated
        catalog = json.loads(
            (workspace_full / "docs" / "intel" / "module-catalog.json").read_text(encoding="utf-8")
        )
        assert catalog["modules"][0]["status"] == "done"


# ---------------------------------------------------------------------------
# verify — 8 scopes
# ---------------------------------------------------------------------------


class TestVerify:
    def test_clean_workspace_passes_id_uniqueness(self, workspace_full):
        r = verify_impl(str(workspace_full), scopes=["id_uniqueness"])
        assert r["ok"] is True
        # No HIGH findings
        assert not any(f["severity"] == "high" for f in r["data"]["findings"])

    def test_clean_workspace_passes_structure(self, workspace_full):
        r = verify_impl(str(workspace_full), scopes=["structure"])
        assert r["ok"] is True
        assert r["data"]["summary"]["failed"] == 0

    def test_cross_references_clean(self, workspace_full):
        r = verify_impl(str(workspace_full), scopes=["cross_references"])
        assert r["data"]["summary"]["failed"] == 0

    def test_f061_class_filesystem_orphan_detection(self, workspace_with_module):
        """Manually inject orphan folder; verify catches it."""
        orphan = workspace_with_module / "docs" / "modules" / "M-099-orphan"
        orphan.mkdir(parents=True)
        (orphan / "_state.md").write_text("---\nfeature-id: M-099\n---\n")

        r = verify_impl(str(workspace_with_module), scopes=["id_uniqueness"])
        findings = r["data"]["findings"]
        orphan_findings = [f for f in findings if f["rule"] == "filesystem-orphan"]
        assert len(orphan_findings) > 0
        assert any("M-099" in f["message"] for f in orphan_findings)

    def test_strict_mode_block_raises(self, workspace_with_module):
        """current-stage=sa but no sa/00-lean-architecture.md exists."""
        with pytest.raises(VerificationFailedError):
            verify_impl(
                str(workspace_with_module),
                scopes=["completeness"],
                strict_mode="block",
                context={"current_stage": "sa"},
            )

    def test_invalid_scope_rejected(self, workspace):
        with pytest.raises(InvalidInputError):
            verify_impl(str(workspace), scopes=["invalid-scope"])


# ---------------------------------------------------------------------------
# rename_module_slug
# ---------------------------------------------------------------------------


class TestRenameModuleSlug:
    def test_rename_updates_folder_and_refs(self, workspace_full):
        r = rename_module_slug_impl(
            str(workspace_full),
            "M-001",
            "identity-access",
            reason="Renamed for clarity per BA review",
        )
        assert r["ok"] is True
        assert r["data"]["new_slug"] == "identity-access"
        # Old folder gone, new folder exists
        assert not (workspace_full / "docs" / "modules" / "M-001-iam").exists()
        assert (workspace_full / "docs" / "modules" / "M-001-identity-access").exists()
        # Feature-map updated
        feat_map = yaml.safe_load(
            (workspace_full / "docs" / "intel" / "feature-map.yaml").read_text(encoding="utf-8")
        )
        assert "identity-access" in feat_map["features"]["F-001"]["path"]
        # Alias entry added
        aliases = json.loads(
            (workspace_full / "docs" / "intel" / "id-aliases.json").read_text(encoding="utf-8")
        )
        slug_renames = aliases["slug_renames"]
        assert slug_renames[-1]["old_slug"] == "iam"
        assert slug_renames[-1]["new_slug"] == "identity-access"

    def test_rename_collision_rejected(self, workspace_with_module):
        scaffold_module_impl(str(workspace_with_module), "M-002", "Other", "other")
        with pytest.raises(NameCollisionError):
            rename_module_slug_impl(
                str(workspace_with_module),
                "M-001",
                "other",
                reason="Should fail collision",
            )


# ---------------------------------------------------------------------------
# autofix
# ---------------------------------------------------------------------------


class TestAutofix:
    def test_orphan_removal_dry_run(self, workspace):
        # Create fake orphan
        orphan = workspace / "docs" / "intel" / "fake.json.tmp"
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_text("{}")

        r = autofix_impl(str(workspace), fix_classes=["orphan-removal"], dry_run=True)
        assert r["ok"] is True
        assert len(r["data"]["fixes_planned"]) == 1
        assert len(r["data"]["fixes_applied"]) == 0
        assert orphan.exists()  # still there

    def test_orphan_removal_applied(self, workspace):
        orphan = workspace / "docs" / "intel" / "fake.json.tmp"
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_text("{}")

        r = autofix_impl(
            str(workspace),
            fix_classes=["orphan-removal"],
            dry_run=False,
            confirm_destructive=True,
        )
        assert len(r["data"]["fixes_applied"]) == 1
        assert not orphan.exists()

    def test_destructive_requires_confirm(self, workspace):
        with pytest.raises(DestructiveNotConfirmedError):
            autofix_impl(str(workspace), fix_classes=["orphan-removal"], dry_run=False)


# ---------------------------------------------------------------------------
# template_registry
# ---------------------------------------------------------------------------


class TestTemplateRegistry:
    def test_list_module(self):
        r = template_registry_impl("module", "list")
        assert r["ok"] is True
        assert r["data"]["count"] == 3
        ids = [t["id"] for t in r["data"]["templates"]]
        assert any("_state.md.j2" in i for i in ids)

    def test_load_existing(self):
        r = template_registry_impl("feature", "load", "_feature.md.j2")
        assert r["ok"] is True
        assert "feature-id" in r["data"]["content"]
        assert r["data"]["sha256"].startswith("sha256:")

    def test_load_missing(self):
        with pytest.raises(TemplateNotFoundError):
            template_registry_impl("module", "load", "nonexistent.j2")

    def test_load_traversal_rejected(self):
        with pytest.raises(InvalidInputError):
            template_registry_impl("module", "load", "../etc/passwd")


# ---------------------------------------------------------------------------
# Concurrency — 5 parallel scaffold_feature on same module
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_parallel_scaffold_features(self, workspace_with_module):
        """5 threads scaffold features F-001..F-005 in parallel.

        Per workspace_lock, writes serialize per workspace. All 5 must succeed
        and all must appear in final feature-catalog.json + feature-map.yaml.
        """
        ws_path = str(workspace_with_module)

        def make_feature(n: int):
            return scaffold_feature_impl(
                ws_path,
                "M-001",
                f"F-{n:03d}",
                f"Feature {n}",
                f"feature-{n}",
                priority="medium",
            )

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(make_feature, i) for i in range(1, 6)]
            results = [f.result() for f in as_completed(futures)]

        # All succeeded
        assert all(r["ok"] for r in results)

        # Final catalog has 5 features
        catalog = json.loads(
            (workspace_with_module / "docs" / "intel" / "feature-catalog.json").read_text(encoding="utf-8")
        )
        feature_ids = {f["id"] for f in catalog["features"]}
        assert feature_ids == {f"F-{n:03d}" for n in range(1, 6)}

        # Module's feature_ids has all 5
        mod_catalog = json.loads(
            (workspace_with_module / "docs" / "intel" / "module-catalog.json").read_text(encoding="utf-8")
        )
        assert set(mod_catalog["modules"][0]["feature_ids"]) == feature_ids

        # No orphan .tmp files
        intel = workspace_with_module / "docs" / "intel"
        tmps = list(intel.glob("*.tmp"))
        assert tmps == []
