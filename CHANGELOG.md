# Changelog

All notable changes to `etc-platform` will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [3.2.0] — 2026-05-06

### Added

- **SDLC scaffolding namespace** (`src/etc_platform/sdlc/`) per ADR-003 D6/D7/D8/D11.
  Implements 11 NEW MCP tools for enterprise-grade SDLC workspace/module/feature
  scaffolding + verification + state mutation, replacing skill-side Write/glob
  patterns. Catches F-061 namespace collision bug class via `verify_id_uniqueness`.

  - **Foundation modules** (~770 lines):
    - `errors.py` — uniform `MCPSdlcError` base + 11 specific subclasses with
      `to_response()` mapping to `{ ok, error: { code, message, details, fix_hint } }`
    - `path_validation.py` — workspace marker check, traversal prevention,
      write-confinement to `{docs,apps,services,libs,packages,tools}/**`
    - `concurrency.py` — atomic write protocol (`tmp + fsync + rename`),
      per-workspace `threading.Lock`, `FileTransaction` multi-file commit with
      rollback-on-verify-failure
    - `versioning.py` — optimistic concurrency via `_meta.json` (read/assert/bump)
    - `ids.py` — M-NNN/F-NNN/H-NNN regex parsers + slug validation + folder
      name composition
    - `frontmatter.py` — YAML frontmatter parse/serialize for .md files +
      dot-path get/set helpers
    - `intel_io.py` — Read/write helpers for catalogs, maps, _meta with
      deterministic JSON/YAML serialization for stable hashes
    - `templates.py` — Jinja2 environment cached + `render_template` +
      `list_templates` + `utc_iso_now`

  - **11 NEW MCP tools** registered via FastMCP `@mcp.tool()`:
    - **Tier-1 atomic create** (5):
      - `scaffold_workspace(workspace_path, workspace_type, stack, config)`
      - `scaffold_app_or_service(workspace_path, name, kind, stack)`
      - `scaffold_module(workspace_path, module_id, name, slug, depends_on, ...)`
      - `scaffold_feature(workspace_path, module_id, feature_id, name, slug, ...)`
      - `scaffold_hotfix(workspace_path, hotfix_id, name, slug, patch_summary, ...)`
    - **Tier-1 refactor** (1): `rename_module_slug` — atomic slug evolution
      with id-aliases.json audit entry
    - **Tier-1 read** (1): `resolve_path` — replaces ALL skill glob fallbacks
      with map-based lookup + alias chain
    - **Tier-1 repair** (1): `autofix(fix_classes, dry_run, confirm_destructive)` —
      orphan-removal functional, schema-migrate/missing-scaffold/
      id-collision-resolve/cross-ref-repair require P0.7 verify integration
    - **Tier-2 consolidated** (2 via discriminator):
      - `update_state(file_path, op, ...)` — 5 ops (`field`, `progress`, `kpi`,
        `log`, `status`), enforces `locked-fields[]`, status op atomic 2-file write
      - `verify(scopes[], strict_mode, context)` — 8 scopes (`structure`,
        `schemas`, `ownership`, `cross_references`, `freshness`, `completeness`,
        `id_uniqueness`, `all`); HIGH/MEDIUM/LOW severity per D10-6;
        `strict_mode=block` raises `VerificationFailedError`
    - **Tier-3 consolidated** (1): `template_registry(namespace, action, template_id)` —
      list+load with path traversal guard

  - **14 Jinja2 templates** baked at `assets/scaffolds/{intel,module,feature,hotfix}/`
    for atomic rendering by scaffold tools.

  - **8 JSON Schemas (draft-07)** baked at `assets/schemas/intel/`:
    - `module-catalog.schema.json` (NEW)
    - `feature-catalog.schema.json` (UPDATED — required `module_id` +
      `consumed_by_modules` per D10-2 cross-cutting)
    - `_state.md.schema.json` (`oneOf` discriminator: `sdlc | hotfix`)
    - `_feature.md.schema.json`, `module-map.yaml.schema.json`,
      `feature-map.yaml.schema.json`, `implementations.yaml.schema.json`,
      `id-aliases.json.schema.json`

- **Tool surface budget**: 35 tools total (cap per D10-5). 11 new SDLC + 24
  existing (doc rendering, KB, dedup, intel cache, templates registry, outlines).
  D11 consolidation saved 17 slots vs the initial 29-tool sketch.

### Changed

- `pyproject.toml` description updated to reflect SDLC scope.

### Tests

- 66 tests passing — 35 unit + 31 integration including 5-thread parallel
  `scaffold_feature` race-condition test (per-workspace lock guarantees no
  corruption). Run via:
  `PYTHONPATH=src python -m pytest tests/{unit,integration}/sdlc/ --no-cov`.

- F-061 bug class regression test verified: orphan folder injection +
  `verify(scopes=['id_uniqueness'])` flags HIGH severity finding-orphan rule.

### References

- ADR: `D:\AI-Platform\maintainer-notes\adr\ADR-003-sdlc-2tier-module-feature.md` (locked D1-D11)
- Spec: `D:\AI-Platform\maintainer-notes\plans\p0-mcp-tool-spec.md`
- Backlog: B-021 P0 phase



## [3.0.0] — 2026-04-28

### Added

- **Workspace pattern** — content-addressed multi-file bundles for render jobs.
  - `Workspace`, `WorkspacePart` dataclasses with manifest sha256 + path validation
  - `JobStore.create_workspace / get_workspace / open_workspace_file /
materialize_workspace / list_workspaces / delete_workspace / lock_workspace`
  - HTTP endpoints: `POST /workspaces`, `GET /workspaces/{id}`, `DELETE /workspaces/{id}`
  - Form-field convention: `files[<workspace-relative-path>]=@local-file`
  - Content-addressed dedup: same content → same `workspace_id` (TTL refreshed)
  - Validators: path traversal, depth ≤ 4, charset, total/per-file/file-count caps
  - Default constraints: 100 MB total, 10 MB per file, 200 files, TTL 24h
- **`POST /jobs` accepts `workspace_id`** as preferred source; `upload_id` retained for back-compat.
- **Runner materializes workspace** into per-job temp dir, auto-detects:
  - `content-data.json` (canonical name)
  - `screenshots/` directory → `screenshots_dir` for HDSD render
  - `diagrams/` directory → `diagrams_dir` (overrides server-side Mermaid render)
- **MCP tools**: `validate_workspace(workspace_id)`; `export_async` now accepts
  `workspace_id` OR `upload_id` (mutex).
- **Sweep** evicts workspaces alongside uploads + jobs; `health()` reports workspace count.
- New tests: `tests/unit/jobs/test_workspace.py` (44 tests), `tests/integration/http/test_workspace_http.py` (14 tests), `tests/integration/http/test_e2e_workspace.py` (E2E with HDSD-like bundle).
- New quality checks (`quality_checks.py`): `check_module_diversity`,
  `check_diagrams_block`, `check_db_table_columns`, `check_test_case_ids` plus
  15 minimum word counts for previously-ungated TKCS sections "phụ".

### Changed

- **HDSD render bug fixed**: previous v2.0.0 dropped screenshots silently because
  the job pipeline only carried single-file uploads. Workspaces solve this by
  carrying screenshots/\* alongside content-data.json in one bundle.
- `Job.upload_id` is now `Optional`; new `Job.workspace_id` field; exactly one is set.
- `sweep_expired()` return shape: `{uploads, jobs, workspaces}` (added `workspaces` key).
- `health()` includes `workspaces`, `max_workspace_bytes`, `max_workspace_files`,
  `workspace_ttl_seconds`.
- `s6-export.md` skill phase: workspace upload as primary path; legacy `/uploads` documented as fallback.
- `docs/API_JOBS.md`: rewritten to lead with workspaces; legacy upload kept as section.

### Deprecated

- Job creation via `upload_id` for HDSD (no screenshots support). Use workspaces.

## [2.0.0] — 2026-04-26

### Added

- **Async job pipeline** (`etc_platform.jobs`) — production-grade upload→render→download
  flow that keeps `content_data` payloads out of the LLM context window.
  - `Job`, `JobStatus`, `Upload`, `JobOutput` dataclasses with full (de)serialisation.
  - `JobStore` — filesystem-backed atomic CRUD, per-resource asyncio locks, TTL eviction,
    Windows-safe `os.replace` retries for concurrent reader/writer races.
  - `JobRunner` — bounded worker pool (`asyncio.Queue`), CPU-bound rendering via
    `asyncio.to_thread`, per-job timeout, graceful shutdown.
  - `http_app.py` — FastAPI app: `POST /uploads`, `POST /jobs`, `GET /jobs/{id}`,
    `GET /jobs/{id}/files/{filename}`, `DELETE /uploads/{id}`, `DELETE /jobs/{id}`,
    `GET /healthz`, `GET /readyz`.
  - Optional API-key auth via `ETC_PLATFORM_API_KEY` + `X-API-Key` header.
  - Configurable CORS origins, TTLs, queue depth, worker count, upload size cap.
- **MCP async tools** that pair with the HTTP layer through one in-process JobStore:
  `validate_uploaded`, `export_async`, `job_status`, `cancel_job`, `upload_capacity`.
- **Unified ASGI entry point** (`etc_platform.server` / `etc-platform-server` script):
  combines HTTP API at `/`, MCP streamable-http at `/mcp`, MCP SSE at `/sse`.
- New tests under `tests/unit/jobs/` (38 tests) + `tests/integration/http/` (12 tests).
- New docs: `docs/API_JOBS.md` — full API reference + migration guide + threat model.

### Changed

- **BREAKING (operationally)**: Docker image entrypoint switched from
  `etc-platform-mcp` (stdio/SSE only) to `etc-platform-server` (HTTP + MCP unified).
  All previous MCP endpoints (`/sse`, `/mcp`) remain reachable; HTTP joins them
  on the same port (default `8000`).
- `Dockerfile` — healthcheck moved from `/sse` to `/healthz` (faster, no MCP deps).
- `docker-compose.yaml` (renamed from `docker-compose.mcp.yaml` + replaces `compose.yaml`) — exposes job pipeline env vars; persistent `data` volume
  now holds both project content and the `_jobs/` job store.
- `pyproject.toml` — added `fastapi`, `python-multipart`, `starlette` to core deps;
  added `httpx` to `[serve]` extra; bumped uvicorn to `[standard]` flavor.
- `phases/s6-export.md` (generate-docs skill) — rewritten to use job-based flow as
  primary; legacy inline `export()` documented as deprecated for >50 KB payloads.

### Deprecated

- `mcp__etc-platform__export(content_data=…)` — kept for backwards compatibility on
  small payloads but emits a server-side warning above 50 KB. Use `export_async`
  - HTTP upload/download instead.

## [0.1.0] — 2026-04-18

### Added

- Initial MVP extracted from Claude Code + Cursor 3 skills
- Typer CLI with subcommands: `init`, `generate`, `research`, `capture`, `data`, `export`, `validate`, `template`
- Pydantic v2 config model + YAML loader with env var interpolation
- Bundled ETC templates (BM.QT.04.04 + BM.QT.04.05) forked with Jinja2 tags
- `engines/xlsx.py` — openpyxl-based Excel filler (preserves formulas, merged cells, DV, CF)
- `engines/docx.py` — docxtpl-based Word renderer (Jinja2-for-Word, TOC auto-refresh, orphan media cleanup)
- `capture/auth.py` — simple auth runner (user-supplied credentials + optional recording mode)
- `tools/jinjafy_templates.py` — fork ETC template into Jinja-tagged version (one-time)
- `tools/extract_*_schema.py` — analyze template structure for schema authoring

### Working end-to-end

- `etc-platform export` — render 4 Office files from `content-data.json`
- `etc-platform validate` — check content-data shape + priority values
- `etc-platform template list` / `fork` — manage templates

### Integrations

- Thin skill adapters for Cursor 3 + Claude Code (orchestrate CLI)

### Not yet implemented (planned for v0.2)

- Native `research` phase (currently via AI adapter)
- Native `capture` phase (currently via AI adapter using Playwright MCP)
- Native `data` phase (currently AI produces content-data.json)
- Jira Xray integration
- Web portal (MkDocs) output
- Sharding support for enterprise-scale projects
- Git-diff incremental regeneration
