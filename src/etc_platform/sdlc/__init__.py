"""SDLC scaffolding namespace — implements ADR-003 D6/D7/D8/D11.

This module exposes 11 NEW MCP tools for SDLC workspace/module/feature
scaffolding + verification + state mutation, replacing skill-side Write/glob
patterns.

Tool surface (registered in mcp_server.py):

    Tier-1 atomic create (5 tools)
        scaffold_workspace          — bootstrap workspace base structure
        scaffold_app_or_service     — add 1 project to monorepo
        scaffold_module             — atomic module + catalog + map
        scaffold_feature            — nested feature + cross-update
        scaffold_hotfix             — hotfix flow (skip ba+sa)

    Tier-1 refactor (1 tool)
        rename_module_slug          — atomic slug change across all refs

    Tier-1 read (1 tool)
        resolve_path                — map-based path resolution

    Tier-1 repair (1 tool)
        autofix                     — repair violations with safeguards

    Tier-2 consolidated (2 tools)
        update_state                — 5 ops: field, progress, kpi, log, status
        verify                      — 8 scopes via discriminator pattern

Plus existing (recap, no P0 work):
        intel_cache, dedup, template_registry — already in registry/

Cross-cutting modules:
    concurrency.py      — atomic write + per-workspace locks
    path_validation.py  — security: confine writes to workspace
    errors.py           — uniform MCP_E_* error codes
    versioning.py       — optimistic concurrency control
"""
from __future__ import annotations
