# etc-docgen

**Template-first documentation generator for ETC projects.**

Turn your codebase + running Docker stack into a complete set of ETC-compliant documents:

- 📘 **Thiết kế Kiến trúc** (TKKT) — architecture design
- 📗 **Thiết kế Cơ sở** (TKCS) — technical specification (NĐ 45/2026 Điều 13)
- � **Thiết kế Chi tiết** (TKCT) — detailed design
- 📙 **Hướng dẫn Sử dụng** (HDSD) — user manual with screenshots
- 📊 **Bộ Test Case** — test cases in ETC Excel template (BM.QT.04.04)

## Architecture — Docs-as-Code

```
Codebase + Docker   →   intel/*.json   →   content-data.json   →   5 Office files
                          (AI)              (AI)                    (Python deterministic)
```

**No AI-generated binaries.** AI produces structured JSON; Python engines render using:

- `openpyxl` for Excel (preserves formulas, validations, conditional formatting)
- `docxtpl` (Jinja2-for-Word) for Word (preserves styles, TOC, signing pages)

## Quick start

```bash
# Install
pip install etc-docgen

# Or from source
git clone https://github.com/etc-vn/etc-docgen
cd etc-docgen
pip install -e ".[all]"

# Bootstrap in your project
cd my-project/
etc-docgen init
# → creates etc-docgen.yaml + .gitignore entries

# Edit config with your project info
vim etc-docgen.yaml

# Set credentials for Playwright capture (never commit)
export DOCGEN_USERNAME=admin@example.com
export DOCGEN_PASSWORD=yourpass

# Run full pipeline
etc-docgen generate

# Or step-by-step
etc-docgen research         # Phase 1: scan code → intel/*.json
etc-docgen capture          # Phase 2: Playwright screenshots
etc-docgen data             # Phase 3: build content-data.json
etc-docgen export           # Phase 4: render 5 Office files
```

## Status

**v0.1 MVP** — export phase fully working end-to-end. Research + Capture + Data phases have AI integration hooks (work via Cursor/Claude Code for now).

| Phase      | v0.1              | v0.2                  | v0.3             |
| ---------- | ----------------- | --------------------- | ---------------- |
| Research   | 🟡 via AI adapter | ✅ Native LLM         | ✅ Native        |
| Capture    | 🟡 via AI adapter | ✅ Native Playwright  | ✅ Incremental   |
| Data       | 🟡 via AI adapter | ✅ Native LLM (batch) | ✅ Sharded       |
| Export     | ✅ Complete       | ✅ Complete           | ✅ + Web portal  |
| Sharding   | ❌                | 🟡 by_service         | ✅ Incremental   |
| Jira Xray  | ❌                | 🟡 Push TCs           | ✅ Bidirectional |
| Web portal | ❌                | 🟡 MkDocs             | ✅ Custom theme  |

## Commands

```bash
etc-docgen init                           # Create etc-docgen.yaml
etc-docgen generate                       # Full pipeline (research → export)
etc-docgen research                       # Phase 1 only
etc-docgen capture                        # Phase 2 only
etc-docgen data                           # Phase 3 only
etc-docgen export                         # Phase 4 only
etc-docgen export --only tkcs             # Export single doc type
etc-docgen export --only tkcs --only hdsd # Export multiple
etc-docgen validate content-data.json     # Validate against schema
etc-docgen validate data.json --strict    # Treat warnings as errors
etc-docgen schema                         # Print JSON Schema to stdout
etc-docgen schema -o schema.json          # Export JSON Schema to file
etc-docgen template list                  # Show bundled templates
etc-docgen template fork FILE --kind hdsd # Fork new ETC template
etc-docgen mcp                            # MCP server (stdio)
etc-docgen mcp -t sse -p 8000            # MCP server (SSE)
etc-docgen mcp -t sse --host 0.0.0.0     # MCP server (SSE, all interfaces)
etc-docgen --version                      # Show version
```

## Configuration

`etc-docgen.yaml` — created by `etc-docgen init`:

```yaml
version: "1.0"

project:
  name: "Hệ thống Quản lý Tác nghiệp" # Tên dự án tiếng Việt
  code: "QLTN-2026" # Mã dự án (trang bìa)
  client: "Bộ Tài Chính" # Tên chủ đầu tư

repo:
  path: "." # Đường dẫn source code
  # services_root: "src/services/"        # Monorepo services folder
  # apps_root: "src/apps/"               # Monorepo apps folder

docker:
  compose_file: "docker-compose.yml"
  auto_discover_services: true
  # services:                             # Manual port override
  #   web: 3000
  #   api: 8080

auth:
  base_url: "http://localhost:3000" # URL cho Playwright capture
  login_url: "/login"
  username_env: "DOCGEN_USERNAME" # Env var chứa username
  password_env: "DOCGEN_PASSWORD" # Env var chứa password
  mode: "auto" # auto | recording | unauthenticated

capture:
  profile: "desktop" # desktop | mobile | tablet | [list]
  concurrency: 5 # Max parallel Playwright instances

output:
  path: "docs/generated" # Output directory
  formats: [docx, xlsx] # docx | xlsx | pdf | web
  sharding: "monolithic" # monolithic | by_service | by_module

llm:
  provider: "none" # anthropic | openai | gemini | ollama | none
  model: "claude-sonnet-4-5"
  batch_mode: false
  max_parallel: 5

# templates:                              # Override bundled templates
#   hdsd: "path/to/custom-hdsd.docx"
#   tkkt: "path/to/custom-tkkt.docx"
#   tkcs: "path/to/custom-tkcs.docx"
#   tkct: "path/to/custom-tkct.docx"
#   test_case: "path/to/custom-tc.xlsx"

# integrations:
#   jira_xray:
#     enabled: true
#     url: "https://jira.company.com"
#     project_key: "QLTN"
#   confluence:
#     enabled: true
#     url: "https://confluence.company.com"
#     space_key: "QLTN"
```

**Config resolution order** (if `--config` not specified):

1. `$ETC_DOCGEN_CONFIG` env var
2. `./etc-docgen.yaml`
3. `./.etc-docgen.yaml`
4. `~/.config/etc-docgen/config.yaml`

## content-data.json — the contract

`content-data.json` is the single intermediate format between AI agents and rendering engines. All 5 output documents are rendered from this one file.

### Schema overview

```
ContentData (root)
├── project: ProjectInfo          # Tên, mã, chủ đầu tư
├── dev_unit: str                 # Đơn vị phát triển
├── meta: Meta                    # Ngày, phiên bản
├── overview: Overview            # Mục đích, phạm vi, thuật ngữ, tham chiếu
│   ├── terms: [Term]
│   └── references: [Reference]
├── services: [Service]           # → HDSD (user manual)
│   └── features: [Feature]
│       ├── steps: [FeatureStep]
│       ├── ui_elements: [UIElement]
│       ├── dialogs: [Dialog]
│       └── error_cases: [ErrorCase]
├── test_cases: TestCases         # → xlsx (test cases)
│   ├── ui: [FeatureGroup | SectionHeader | TestCaseRow]
│   └── api: [FeatureGroup | SectionHeader | TestCaseRow]
├── troubleshooting: [TroubleshootingItem]
├── architecture: Architecture    # → TKKT
│   ├── tech_stack: [TechStackItem]
│   ├── components: [ArchComponent]
│   ├── data_entities: [DataEntity]
│   ├── apis: [ApiEndpoint]
│   ├── external_integrations: [ExternalIntegration]
│   ├── environments: [DeployEnvironment]
│   ├── containers: [ContainerInfo]
│   ├── nfr: [NfrItem]
│   └── 6 diagram fields
├── tkcs: TkcsData                # → TKCS (NĐ 45/2026 Điều 13)
│   ├── legal_basis, current_state, necessity
│   ├── architecture_compliance, technology_rationale
│   ├── functional_design, db_design_summary, integration_design_summary
│   ├── security_plan, operations_plan, timeline
│   ├── total_investment, operating_cost, project_management
│   └── 2 diagram fields
└── tkct: TkctData                # → TKCT (detailed design)
    ├── modules: [ModuleDesign]
    ├── db_tables: [DbTable] → [DbColumn]
    ├── api_details: [ApiDetail] → [ApiParameter]
    ├── screens: [ScreenDesign]
    └── 4 diagram fields
```

### Minimal example

```json
{
  "project": {
    "display_name": "Hệ thống Quản lý Tác nghiệp",
    "code": "QLTN-2026",
    "client": "Bộ Tài Chính"
  },
  "meta": { "today": "18/04/2026", "version": "1.0" },
  "overview": {
    "purpose": "Tài liệu hướng dẫn sử dụng...",
    "scope": "Hệ thống QLTN gồm 3 phân hệ...",
    "terms": [
      { "short": "HDSD", "full": "Hướng dẫn sử dụng", "explanation": "..." }
    ],
    "references": [
      { "stt": "1", "name": "TKCS hệ thống", "ref": "TKCS-QLTN-v1.0" }
    ]
  },
  "services": [
    {
      "slug": "task-management",
      "display_name": "Phân hệ Tác nghiệp",
      "features": [
        {
          "id": "F-001",
          "name": "Đăng nhập",
          "actors": ["Tất cả người dùng"],
          "steps": [
            {
              "order": 1,
              "action": "Mở trình duyệt...",
              "expected": "Hiển thị form đăng nhập"
            }
          ]
        }
      ]
    }
  ]
}
```

### Validate

```bash
etc-docgen validate content-data.json
# ✓ Valid
# Services: 3, Features: 12, Test cases: 45
# ⚠ Features without test cases: F-011, F-012
```

### Export JSON Schema

```bash
etc-docgen schema -o schema.json
# → Full Pydantic-generated JSON Schema for IDE autocompletion
```

## Document outlines

### TKKT — Thiết kế Kiến trúc

Maps to `architecture.*` fields in content-data.json.

| Section                  | Content                      | Fields                                                                        |
| ------------------------ | ---------------------------- | ----------------------------------------------------------------------------- |
| 1. Giới thiệu            | Mục đích, phạm vi, thuật ngữ | `overview.*`                                                                  |
| 2. Tổng quan hệ thống    | Mô tả hệ thống, phạm vi      | `architecture.system_overview`, `.scope_description`                          |
| 3. Kiến trúc tổng thể    | Sơ đồ kiến trúc, tech stack  | `architecture.architecture_diagram`, `.tech_stack[]`                          |
| 4. Kiến trúc logic       | Components, tương tác        | `architecture.logical_diagram`, `.components[]`                               |
| 5. Kiến trúc dữ liệu     | Entities, mô hình            | `architecture.data_diagram`, `.data_entities[]`                               |
| 6. Kiến trúc tích hợp    | APIs, external systems       | `architecture.integration_diagram`, `.apis[]`, `.external_integrations[]`     |
| 7. Kiến trúc triển khai  | Environments, containers     | `architecture.deployment_diagram`, `.environments[]`, `.containers[]`         |
| 8. Kiến trúc bảo mật     | Auth, data protection        | `architecture.security_diagram`, `.security_description`, `.auth_description` |
| 9. Yêu cầu phi chức năng | Performance, SLA             | `architecture.nfr[]`                                                          |

**Diagrams** (6): `architecture_diagram`, `logical_diagram`, `data_diagram`, `deployment_diagram`, `integration_diagram`, `security_diagram`

### TKCS — Thiết kế Cơ sở (NĐ 45/2026 Điều 13)

Maps to `tkcs.*` fields in content-data.json.

| Section                       | Content                                 | Fields                                                                                                    |
| ----------------------------- | --------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| 1. Giới thiệu chung           | Thông tin dự án, loại đầu tư            | `project.*`, `overview.*`, `tkcs.investment_type`, `.funding_source`, `.project_duration`                 |
| 2. Cơ sở pháp lý              | Viện dẫn QĐ, NĐ, CT                     | `tkcs.legal_basis`                                                                                        |
| 3. Hiện trạng và sự cần thiết | Hiện trạng, đánh giá, lý do đầu tư      | `tkcs.current_state`, `tkcs.necessity`                                                                    |
| 4. Đánh giá phù hợp quy hoạch | Khung KTCPĐT, Kế hoạch CNTT             | `tkcs.architecture_compliance`                                                                            |
| 5. Phân tích lựa chọn CN      | So sánh phương án                       | `tkcs.technology_rationale`                                                                               |
| 6. Thiết kế cơ sở             | Tổng quan TK, chức năng, CSDL, tích hợp | `tkcs.detailed_design_summary`, `.functional_design`, `.db_design_summary`, `.integration_design_summary` |
| 7. Phương án ATTT             | An toàn thông tin                       | `tkcs.security_plan`                                                                                      |
| 8. Tổ chức vận hành           | Phương án quản lý, khai thác            | `tkcs.operations_plan`                                                                                    |
| 9. Tiến độ                    | Lộ trình thực hiện                      | `tkcs.timeline`                                                                                           |
| 10. Tổng mức đầu tư           | Kinh phí, vận hành                      | `tkcs.total_investment`, `tkcs.operating_cost`                                                            |
| 11. Tổ chức QLDA              | Mô hình quản lý                         | `tkcs.project_management`                                                                                 |

**Diagrams** (2): `architecture_diagram`, `data_model_diagram`

### TKCT — Thiết kế Chi tiết

Maps to `tkct.*` fields in content-data.json.

| Section               | Content                         | Fields                                                                      |
| --------------------- | ------------------------------- | --------------------------------------------------------------------------- |
| 1. Tổng quan thiết kế | Mô tả hệ thống, tham chiếu TKKT | `tkct.system_description`, `.architecture_reference`                        |
| 2. Thiết kế chức năng | Chi tiết per module             | `tkct.modules[]` → `ModuleDesign` (name, flow, rules, I/O)                  |
| 3. Thiết kế CSDL      | ERD, bảng, cột                  | `tkct.db_description`, `tkct.db_tables[]` → `DbTable` → `DbColumn`          |
| 4. Thiết kế API       | Endpoint chi tiết               | `tkct.api_description`, `tkct.api_details[]` → `ApiDetail` → `ApiParameter` |
| 5. Thiết kế giao diện | Guidelines, layout, screens     | `tkct.ui_guidelines`, `.ui_layout`, `tkct.screens[]` → `ScreenDesign`       |
| 6. Thiết kế tích hợp  | Tích hợp chi tiết               | `tkct.integration_design`                                                   |
| 7. Thiết kế bảo mật   | Bảo mật chi tiết                | `tkct.security_design`                                                      |
| 8. Ma trận truy xuất  | Features ↔ Modules ↔ TCs        | `tkct.traceability_description`                                             |

**Diagrams** (4): `architecture_overview_diagram`, `db_erd_diagram`, `ui_layout_diagram`, `integration_diagram`

**Module-level diagrams**: Each `ModuleDesign` has its own `flow_diagram`.

### HDSD — Hướng dẫn Sử dụng

Maps to `services[]` + `troubleshooting[]` in content-data.json.

| Section                  | Content                    | Fields                                               |
| ------------------------ | -------------------------- | ---------------------------------------------------- |
| 1. Giới thiệu            | Mục đích, phạm vi, quy ước | `overview.purpose`, `.scope`, `.conventions`         |
| 1.1. Thuật ngữ           | Bảng viết tắt              | `overview.terms[]`                                   |
| 1.2. Tài liệu tham chiếu | Tài liệu liên quan         | `overview.references[]`                              |
| 2. Hướng dẫn chi tiết    | Per service → per feature  | `services[]` → `Service`                             |
| 2.1–2.N. Chức năng X     | Mô tả, bước, ảnh           | `features[].steps[]`, `.ui_elements[]`, `.dialogs[]` |
| 2.N+1. Xử lý sự cố       | FAQ/Troubleshooting        | `troubleshooting[]`                                  |

**Screenshots**: Each `FeatureStep.screenshot` → InlineImage embedded in Word.

### Test Cases — Kịch bản Kiểm thử (xlsx)

Maps to `test_cases.ui[]` + `test_cases.api[]` in content-data.json.

| Sheet              | Row types                                        | Fields             |
| ------------------ | ------------------------------------------------ | ------------------ |
| Tên chức năng (UI) | FeatureGroupRow → SectionHeaderRow → TestCaseRow | `test_cases.ui[]`  |
| Tên API            | FeatureGroupRow → SectionHeaderRow → TestCaseRow | `test_cases.api[]` |

**TestCaseRow fields**: `name`, `steps[]` (action + expected), `priority`, `preconditions`, `checklog`, `redirect`, `notes`, `feature_id`, `tc_id`, `labels[]`

**Priority mapping**: Accepts Vietnamese (Rất cao/Cao/Trung bình/Thấp), English (Critical/Major/Normal/Minor), TestRail (P1-P4).

## MCP Server

AI agents trong IDE gọi trực tiếp etc-docgen tools qua [Model Context Protocol](https://modelcontextprotocol.io/).

### Transports

| Transport         | Use case                                    | Command                                        |
| ----------------- | ------------------------------------------- | ---------------------------------------------- |
| `stdio` (default) | Local IDE (VS Code, Cursor, Claude Desktop) | `etc-docgen mcp`                               |
| `sse`             | Docker / remote server                      | `etc-docgen mcp -t sse --host 0.0.0.0 -p 8000` |
| `streamable-http` | Newer MCP clients                           | `etc-docgen mcp -t streamable-http`            |

### IDE Configuration

**VS Code** — `settings.json`:

```jsonc
{
  "mcp": {
    "servers": {
      "etc-docgen": {
        "command": "etc-docgen-mcp",
        "type": "stdio",
      },
    },
  },
}
```

**VS Code remote (SSE)**:

```jsonc
{
  "mcp": {
    "servers": {
      "etc-docgen": {
        "url": "http://your-server:8000/sse",
        "type": "sse",
      },
    },
  },
}
```

**Cursor** — `.cursor/mcp.json`:

```jsonc
{
  "mcpServers": {
    "etc-docgen": {
      "command": "etc-docgen-mcp",
    },
  },
}
```

**Cursor remote (SSE)**:

```jsonc
{
  "mcpServers": {
    "etc-docgen": {
      "url": "http://your-server:8000/sse",
    },
  },
}
```

**Claude Desktop** — `claude_desktop_config.json`:

```jsonc
{
  "mcpServers": {
    "etc-docgen": {
      "command": "etc-docgen-mcp",
    },
  },
}
```

**Windsurf** — `~/.codeium/windsurf/mcp_config.json`:

```jsonc
{
  "mcpServers": {
    "etc-docgen": {
      "command": "etc-docgen-mcp",
    },
  },
}
```

### Docker deployment

```bash
# Build image
docker build -t etc-docgen-mcp .

# Run with port mapping
docker run -p 8000:8000 etc-docgen-mcp

# With volume mount for project data (validate/export use file paths)
docker run -p 8000:8000 -v /path/to/project:/data etc-docgen-mcp

# Docker Compose
docker compose -f docker-compose.mcp.yaml up -d
```

SSE endpoint: `http://localhost:8000/sse`

### MCP Tools (8)

| Tool                                                        | Description                                        | Returns                                       |
| ----------------------------------------------------------- | -------------------------------------------------- | --------------------------------------------- |
| `validate(data_path)`                                       | Validate content-data.json against Pydantic schema | `{valid, errors, warnings, stats}`            |
| `export(data_path, output_dir, targets?, screenshots_dir?)` | Render Office files from content-data.json         | `{success, targets: [{target, output, ...}]}` |
| `schema()`                                                  | Full JSON Schema for content-data.json             | JSON Schema string                            |
| `section_schema(doc_type)`                                  | Schema for 1 doc type — saves 65-80% tokens        | `{doc_type, primary_schema, support_schemas}` |
| `merge_content(data_path, partial_json)`                    | Deep-merge partial JSON into content-data.json     | `{success, merged_keys, total_keys}`          |
| `field_map(doc_type)`                                       | Interview → field mapping for a doc type           | `{field_map, writer_prompt_context}`          |
| `template_list()`                                           | List bundled ETC templates with sizes              | `[{filename, size_kb, path}]`                 |
| `template_fork(source_path, kind)`                          | Fork an ETC template with Jinja2 tags              | `{success, kind, output}`                     |

`section_schema` doc_type options: `tkcs`, `tkct`, `tkkt`, `hdsd`, `xlsx`

## AI Agent Integration

etc-docgen integrates with Claude Code and Cursor IDE via skills and agents.

### Render routing

```
doc_type ∈ {tkcs, tkct, tkkt, hdsd, xlsx}  → etc-docgen (content-data.json → docxtpl/openpyxl)
doc_type ∈ {du-toan, hsmt, hsdt, nckt, ...} → Pandoc (Markdown → docx)
```

### Agent workflow (etc-docgen doc types)

```
doc-orchestrator
  │
  ├─ 1. MCP: section_schema({doc_type}) → get field definitions
  ├─ 2. MCP: field_map({doc_type})      → plan waves by field dependencies
  ├─ 3. MCP: merge_content(path, skeleton) → init content-data.json
  │
  ├─ Per wave:
  │   ├─ dispatch doc-writer (×N parallel)
  │   │   └─ Output: JSON matching section_schema fields
  │   ├─ MCP: merge_content(path, writer_json) per writer
  │   ├─ MCP: validate(path)
  │   └─ dispatch doc-reviewer (checks quality + validation_result)
  │
  └─ Final:
      └─ MCP: export(path, output_dir, [doc_type])
          → {doc_type}.docx or .xlsx
```

### Agent roles

| Agent                | Role                                                     | Output           |
| -------------------- | -------------------------------------------------------- | ---------------- |
| **doc-orchestrator** | Điều phối pipeline, wave planning, merge + validate      | State management |
| **doc-writer**       | Viết nội dung (JSON for etc-docgen, Markdown for Pandoc) | Section content  |
| **doc-reviewer**     | Rà soát chất lượng, pháp lý, nhất quán                   | Findings YAML    |
| **doc-diagram**      | Tạo sơ đồ (Mermaid/Figma)                                | PNG/SVG diagrams |

### Skills

| Skill                      | Purpose                                                          |
| -------------------------- | ---------------------------------------------------------------- |
| **new-document-workspace** | Scaffold workspace + route etc-docgen vs Pandoc                  |
| **new-strategic-document** | Đề án CĐS pipeline (Pandoc) — downstream projects use etc-docgen |
| **resume-document**        | Tiếp tục pipeline dang dở                                        |
| **generate-docs**          | Code-to-docs: codebase → content-data.json → 5 Office files      |

See `integrations/claude-code/` for detailed integration docs.

## Template customization

### Bundled templates

```bash
etc-docgen template list
# huong-dan-su-dung.docx    42 KB
# test-case.xlsx             38 KB
# thiet-ke-chi-tiet.docx    45 KB
# thiet-ke-co-so.docx       40 KB
# thiet-ke-kien-truc.docx   43 KB
```

### Forking new templates

When ETC releases a new template version:

```bash
# Fork adds Jinja2 tags to template while preserving styles
etc-docgen template fork ~/Downloads/BM.QT.04.05-v3.docx --kind hdsd
# → Saved to bundled templates directory

# Supported kinds: hdsd, tkkt, tkcs, tkct
```

### Custom template override

In `etc-docgen.yaml`:

```yaml
templates:
  hdsd: "path/to/my-custom-hdsd.docx"
  tkkt: "path/to/my-custom-tkkt.docx"
```

Templates use docxtpl (Jinja2 for Word) syntax:

- `{{ project.display_name }}` — simple substitution
- `{%tr for f in all_features %}...{%tr endfor %}` — table row loop
- `{%p if arch.architecture_diagram_image %}...{%p endif %}` — conditional paragraph

### Diagram images

Diagrams are embedded as `InlineImage` at render time. Convention:

- Model field: `architecture.architecture_diagram = "arch-overview.png"`
- Template tag: `{%p if architecture.architecture_diagram_image %}{{ architecture.architecture_diagram_image }}{%p endif %}`
- Engine creates `*_image` variant → `InlineImage(tpl, path, width=Inches(5.5))`

Place diagram files in the screenshots directory.

## Features

### Template-first

Templates are the layout authority — Jinja2 tags embedded in Word/Excel files. Change layout by editing Office files, not Python code.

### Zero AI hallucination at render

AI outputs JSON only. Binary generation is 100% deterministic Python code. No AI touches .docx/.xlsx bytes.

### Scale-ready

Designed for enterprise: monorepo sharding (`by_service`, `by_module`), parallel LLM calls (Claude Batch API), incremental regen from Git diff.

### Standards-compliant

ETC templates (BM.QT.04.04, BM.QT.04.05) preserved pixel-perfect. NĐ 45/2026 structure for TKCS. All Word files have TOC auto-refresh on open.

### MCP-first integration

8 MCP tools expose the full pipeline to any AI IDE. `section_schema` saves 65-80% tokens vs full schema. `merge_content` enables incremental writing.

## Project structure

```
etc-docgen/
├── pyproject.toml              # Hatchling build, dependencies
├── Dockerfile                  # MCP server Docker image (SSE)
├── docker-compose.mcp.yaml     # Compose for SSE deployment
├── src/etc_docgen/
│   ├── __init__.py             # Version
│   ├── __main__.py             # python -m etc_docgen
│   ├── cli.py                  # Typer CLI (init, generate, export, validate, mcp, ...)
│   ├── config.py               # Pydantic config model (etc-docgen.yaml)
│   ├── paths.py                # Asset path resolution
│   ├── mcp_server.py           # MCP server (stdio/sse/streamable-http, 8 tools)
│   ├── engines/
│   │   ├── docx.py             # docxtpl rendering (4 Word files)
│   │   ├── xlsx.py             # openpyxl rendering (test cases)
│   │   └── screenshots.py     # Screenshot post-processing
│   ├── capture/
│   │   ├── __init__.py         # Playwright automation
│   │   └── auth.py             # Login flow (auto/recording/unauthenticated)
│   ├── data/
│   │   ├── models.py           # Pydantic models — THE schema (38+ definitions)
│   │   └── validation.py       # Schema + advisory validation
│   ├── integrations/
│   │   ├── __init__.py
│   │   └── field_maps.py       # Routing (etc-docgen vs Pandoc) + field mapping
│   ├── research/               # Codebase analysis (v0.2+)
│   ├── sharding/               # Enterprise-scale support (v0.2+)
│   ├── assets/
│   │   ├── templates/          # 5 bundled ETC templates (.docx + .xlsx)
│   │   └── schemas/            # YAML schemas for template validation
│   └── tools/
│       ├── extract_docx_schema.py  # Extract tags from Word templates
│       ├── extract_xlsx_schema.py  # Extract structure from Excel templates
│       └── jinjafy_templates.py    # Add Jinja2 tags to ETC templates
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── examples/
│   ├── minimal/                # Minimal content-data.json + config
│   └── enterprise-microservices/
├── docs/
│   ├── template/               # Template authoring guide
│   └── integrations/           # IDE integration docs
└── integrations/
    ├── claude-code/            # Claude Code skill adapter + README
    └── cursor/                 # Cursor skill adapter
```

## Requirements

- Python ≥ 3.11
- **Export only**: `pip install etc-docgen` (no extra dependencies)
- **Playwright capture**: `pip install "etc-docgen[capture]"` + `playwright install chromium`
- **SSE/Docker MCP server**: `pip install "etc-docgen[serve]"` (adds uvicorn)
- **All features**: `pip install "etc-docgen[all]"`

## License

Proprietary — Công ty CP Hệ thống Công nghệ ETC.

## Links

- **Issues**: https://github.com/etc-vn/etc-docgen/issues
- **Docs**: https://etc-vn.github.io/etc-docgen/
- **Changelog**: [CHANGELOG.md](CHANGELOG.md)
