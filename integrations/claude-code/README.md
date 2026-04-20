# Claude Code Integration

etc-docgen serves as the **rendering engine** for Claude Code document skills.
Skills handle research, interview, analysis — etc-docgen handles deterministic Office output.

## Architecture

```
Skills (THINK + WRITE)                    etc-docgen (RENDER)
┌──────────────────────────┐              ┌──────────────────────┐
│ strategy-analyst         │              │                      │
│ policy-researcher        │  content-    │ section_schema       │
│ doc-orchestrator         │──data.json──→│ field_map            │
│ doc-writer (×N parallel) │              │ merge_content        │
│ doc-reviewer             │              │ validate             │
│ structure-advisor        │              │ export → .docx/.xlsx │
└──────────────────────────┘              └──────────────────────┘
```

## Render Routing

| Doc Type   | Renderer   | Notes                  |
| ---------- | ---------- | ---------------------- |
| TKCS       | etc-docgen | NĐ 45/2026 Điều 13     |
| TKCT       | etc-docgen | Detailed design        |
| TKKT       | etc-docgen | Architecture design    |
| HDSD       | etc-docgen | User manual            |
| Test Cases | etc-docgen | xlsx format            |
| Đề án CĐS  | Pandoc     | No etc-docgen template |
| Dự toán    | Pandoc     | TT 04/2020             |
| HSMT/HSDT  | Pandoc     | Luật 22/2023           |
| NCKT       | Pandoc     | NĐ 45/2026 Điều 12     |

## MCP Tools for Agents

| Tool                         | Purpose                              | When to call                       |
| ---------------------------- | ------------------------------------ | ---------------------------------- |
| `section_schema(doc_type)`   | Schema for 1 doc type (saves tokens) | doc-writer needs field definitions |
| `field_map(doc_type)`        | Interview → field mapping            | doc-orchestrator plans waves       |
| `merge_content(path, json)`  | Deep merge partial JSON              | doc-writer writes each wave        |
| `validate(path)`             | Validate content-data.json           | After each wave + final            |
| `export(path, dir, targets)` | Render Office files                  | Final export                       |
| `schema()`                   | Full JSON Schema                     | When full schema needed            |

## Agent Workflow (for etc-docgen doc types)

```
1. doc-orchestrator calls: section_schema({doc_type}) + field_map({doc_type})
2. doc-orchestrator plans waves based on field dependencies
3. Per wave:
   a. doc-writer gets field defs + DCB context
   b. doc-writer produces JSON matching schema
   c. merge_content(content-data.json, writer_output)
   d. validate(content-data.json)
   e. doc-reviewer checks quality
4. Final: export(content-data.json, output/, [doc_type])
```

## Installation

```bash
pip install etc-docgen
```

## MCP Server Setup

```bash
# stdio transport (IDE integration)
etc-docgen mcp
# or directly
python -m etc_docgen.mcp_server
```

## Skills Integration

Three skills are updated to use etc-docgen:

- **new-document-workspace** (`~/.claude/skills/new-document-workspace/`):
  Routes TKCS/TKCT/TKKT/HDSD through etc-docgen, others through Pandoc.
- **new-strategic-document** (`~/.claude/skills/new-strategic-document/`):
  Đề án CĐS itself uses Pandoc. Downstream projects (TKCS/TKCT) use etc-docgen.

- **resume-document** (`~/.claude/skills/resume-document/`):
  EXPORT stage routes to etc-docgen or Pandoc based on doc type.

## doc-writer Prompt Pattern (etc-docgen types)

```
Output format: JSON (NOT Markdown prose)
Target: content-data.json → etc-docgen renders .docx

Fields to fill: {from section_schema}
Field mapping: {from field_map}

Instructions:
1. Produce VALID JSON matching schema exactly
2. Prose fields: văn phong hành chính VN, vô nhân xưng
3. Structured fields: follow nested model schema
4. Use [CẦN BỔ SUNG: describe] for unknowns
5. Return JSON with ONLY fields you are filling
```

## Cross-renderer Handoff

When pipeline crosses renderers (e.g., NCKT → TKCS):

- **Pandoc → etc-docgen**: Orchestrator reads Markdown content files, populates content-data.json
- **etc-docgen → Pandoc**: Orchestrator reads content-data.json, injects into DCB for Pandoc writer
