---
name: generate-docs
description: Thin wrapper around etc-platform CLI. Orchestrate pipeline từ codebase → ETC docs (TKKT, TKCS, Test Case, HDSD). Cursor 3 leverage — @Codebase, Playwright MCP, Design Mode, Composer diff review. Pipeline chạy qua `etc-platform` command trong integrated terminal.
---

# Generate Documentation (Cursor 3 — wrapper cho etc-platform CLI)

Skill này là **thin wrapper** gọi `etc-platform` CLI. Logic chính nằm trong Python package, không nhúng vào skill.

**Prerequisites**: `pip install etc-platform` (hoặc `pip install -e D:/Projects/etc-platform`).

---

## Workflow

### Step 0 — Verify install + config

```bash
etc-platform --version
# Nếu chưa có etc-platform.yaml:
etc-platform init
```

Agent guide user edit `etc-platform.yaml` — dùng `@-mentions` để inject context từ repo:
- `@docker-compose.yml` để detect services
- `@package.json` / `@pyproject.toml` cho project info
- `@README.md` cho project description

### Step 1 — Set credentials

```bash
export DOCGEN_USERNAME="admin@etc.vn"
export DOCGEN_PASSWORD="..."
```

Hoặc Windows PowerShell:
```powershell
$env:DOCGEN_USERNAME = "admin@etc.vn"
$env:DOCGEN_PASSWORD = "..."
```

### Step 2 — Phase 1: Research (Cursor leverage @Codebase)

**v0.1 — AI đóng vai researcher**: agent dùng `@Codebase` để scan, tự sinh `intel/*.json`.

```
@Codebase "@Controller @RestController @Get @Post"
→ Map routes theo service
→ Sinh intel/arch-report.json

@Codebase "@Entity @Table"
→ Extract data models

Extended thinking cho FLOW phase (grouping controllers → features).
```

Output: `docs/generated/intel/{stack,arch,flow,frontend}-report.json`

**v0.2+**: `etc-platform research` native — skip AI role này.

### Step 3 — Phase 2: Capture (Playwright MCP)

Cursor có Playwright MCP native. Agent dùng trực tiếp:

```
mcp__playwright__browser_navigate(...)
mcp__playwright__browser_snapshot()
mcp__playwright__browser_take_screenshot(filename=...)
```

Cho auth, chạy qua terminal:
```bash
python -c "from etc_platform.capture.auth import cmd_login; ..."
# hoặc v0.2+ sẽ có: etc-platform capture
```

**💡 YOLO mode**: cho dự án ≥ 20 features, user bật YOLO mode để agent chạy autonomous qua hàng trăm MCP calls.

### Step 4 — Phase 2.5: Design Mode review

User press `Cmd+Shift+D` (Mac) / `Ctrl+Shift+D` (Win) mở Design Mode → review screenshots visual.

### Step 5 — Phase 3: Data writer

Agent đọc `intel/*.json` + cross-ref BA specs nếu có:
```
@docs/features/*/ba/03-acceptance-criteria.md
@intel/flow-report.json
@intel/screenshot-map.json
```

Sinh `content-data.json` theo schema. **Composer hiển thị diff** → user approve trước khi save.

Validate:
```bash
etc-platform validate docs/generated/content-data.json
```

### Step 6 — Phase 4: Export (CLI subprocess)

```bash
etc-platform export --data docs/generated/content-data.json
```

Chạy ~15 giây, sinh 4 file Office. Cursor integrated terminal hiển thị progress inline.

### Step 7 — Completion + MEMORIES

Agent ghi vào `MEMORIES.md`:
```markdown
## generate-docs learnings
### {project-slug} (last-run: {date})
- dev-unit: "..."
- client-name: "..."
- service-ports: {...}
- output: docs/generated/
```

Lần chạy kế tiếp, agent đọc MEMORIES pre-fill config.

---

## Commands quick reference

```bash
etc-platform --version
etc-platform --help
etc-platform init                  # Tạo etc-platform.yaml
etc-platform generate              # Full pipeline
etc-platform research              # Phase 1 (v0.2+)
etc-platform capture               # Phase 2 (v0.2+)
etc-platform data                  # Phase 3 (v0.2+)
etc-platform export                # Phase 4 ✅ working v0.1
etc-platform validate FILE         # Validate content-data.json
etc-platform template list
etc-platform template fork FILE --kind hdsd
```

---

## Cursor 3 unique features leveraged

1. **@Codebase** → Phase 1 research (semantic search)
2. **Playwright MCP native** → Phase 2 capture (không cần generate spec.ts)
3. **Design Mode** (Cmd+Shift+D) → Phase 2.5 screenshot review
4. **Composer diff review** → Phase 3 data-writer validation
5. **Integrated terminal** → CLI output hiển thị inline
6. **MEMORIES.md** → cross-session cache
7. **YOLO mode** → Phase 2 autonomous run

---

## What's Next

| Situation | Action |
|---|---|
| Docs complete | Open `docs/generated/output/` trong Word/Excel |
| Code thay đổi | Chạy lại `/generate-docs` — MEMORIES pre-fill |
| ETC ra template v2 | `etc-platform template fork new-template.docx --kind hdsd` |
| Scale >500 features | Wait for v0.2 sharding support |
| CI/CD auto-regen | GitHub Actions example ở `etc-platform/examples/incremental-ci/` |
