"""etc-docgen MCP Server — expose documentation tools via Model Context Protocol.

Allows AI agents in any MCP-compatible IDE (VS Code, Cursor, Claude Desktop,
Windsurf, etc.) to call etc-docgen tools directly without subprocess CLI parsing.

Tools exposed:
  - validate:       validate content-data.json against Pydantic schema
  - export:         render Office files from content-data.json
  - schema:         get JSON Schema for content-data.json
  - section_schema: get schema for a specific doc type (saves tokens)
  - merge_content:  deep-merge partial JSON into content-data.json
  - field_map:      get interview-to-field mapping for a doc type
  - template_list:  list bundled templates with sizes
  - template_fork:  fork an ETC template with Jinja2 tags

Resources exposed:
  - schema://content-data  → JSON Schema for content-data.json

Transports:
  - stdio (default): for local IDE integration
  - sse: for remote/Docker deployment (HTTP + Server-Sent Events)
  - streamable-http: newer HTTP-based MCP transport

Usage:
  # stdio transport (default for IDE integration)
  python -m etc_docgen.mcp_server

  # SSE transport (for Docker / remote)
  python -m etc_docgen.mcp_server --transport sse --host 0.0.0.0 --port 8000

  # or via etc-docgen CLI
  etc-docgen mcp
  etc-docgen mcp --transport sse --port 8000
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from etc_docgen.paths import template, templates_dir

mcp = FastMCP(
    "etc-docgen",
    instructions=(
        "etc-docgen is a template-first documentation generator for Vietnamese "
        "government IT projects. It turns structured data into standardized "
        "documents (HDSD, TKKT, TKCS, TKCT, Test Cases) via a content-data.json "
        "intermediate format.\n\n"
        "Integration workflow for doc-writer agents:\n"
        "  1. section_schema(doc_type) → get schema for your section (saves tokens)\n"
        "  2. Produce JSON matching the schema fields\n"
        "  3. merge_content(path, json) → write into content-data.json\n"
        "  4. validate(path) → verify correctness\n"
        "  5. export(path, out, targets) → render Office files\n\n"
        "Tools: validate, export, schema, section_schema, merge_content, "
        "template_list, template_fork."
    ),
)


# ─────────────────────────── Resources ───────────────────────────


@mcp.resource("schema://content-data")
def get_content_data_schema() -> str:
    """JSON Schema for content-data.json — the contract between agents and engines."""
    from etc_docgen.data.models import ContentData

    schema = ContentData.model_json_schema()
    return json.dumps(schema, indent=2, ensure_ascii=False)


# ─────────────────────────── Tools ───────────────────────────


@mcp.tool()
def validate(data_path: str) -> str:
    """Validate a content-data.json file against the Pydantic schema.

    Returns validation result with errors, warnings, and statistics.
    Use this after producing or editing content-data.json to ensure correctness.

    Args:
        data_path: Absolute or relative path to content-data.json
    """
    from etc_docgen.data.validation import validate_file

    path = Path(data_path)
    if not path.exists():
        return json.dumps({"valid": False, "errors": [f"File not found: {data_path}"]})

    result = validate_file(path)
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)


@mcp.tool()
def export(
    data_path: str,
    output_dir: str,
    targets: list[str] | None = None,
    screenshots_dir: str | None = None,
    diagrams_dir: str | None = None,
    auto_render_mermaid: bool = True,
) -> str:
    """Render Office files from content-data.json using bundled ETC templates.

    Produces up to 5 files:
      - kich-ban-kiem-thu.xlsx  (test cases)
      - huong-dan-su-dung.docx (user manual — HDSD)
      - thiet-ke-kien-truc.docx (architecture design — TKKT)
      - thiet-ke-co-so.docx (basic design — TKCS)
      - thiet-ke-chi-tiet.docx (detailed design — TKCT)

    Args:
        data_path: Path to content-data.json
        output_dir: Directory to write output files
        targets: Which files to export. Options: xlsx, hdsd, tkkt, tkcs, tkct. Default: all.
        screenshots_dir: Directory containing screenshots for HDSD (optional)
    """
    from etc_docgen.engines import docx as docx_engine
    from etc_docgen.engines import xlsx as xlsx_engine

    data_file = Path(data_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not data_file.exists():
        return json.dumps({"success": False, "error": f"Data file not found: {data_path}"})

    target_set = set(targets or ["xlsx", "hdsd", "tkkt", "tkcs", "tkct"])

    # Auto-render Mermaid diagrams if data has `diagrams` block (Mermaid source)
    # and caller didn't provide pre-rendered diagrams_dir.
    mermaid_report = None
    if auto_render_mermaid and diagrams_dir is None:
        try:
            data_preview = json.loads(data_file.read_text(encoding="utf-8"))
            if data_preview.get("diagrams"):
                from etc_docgen.tools.render_mermaid import check_mmdc, render_one

                render_dir = out_dir / "diagrams"
                render_dir.mkdir(parents=True, exist_ok=True)
                mmdc = check_mmdc()
                mermaid_report = {"rendered": [], "failed": [], "mmdc_available": bool(mmdc)}
                if mmdc:
                    for key, source in data_preview["diagrams"].items():
                        if not isinstance(source, str) or not source.strip():
                            continue
                        out_png = render_dir / f"{key}.png"
                        ok, err = render_one(mmdc, source, out_png)
                        if ok:
                            mermaid_report["rendered"].append(key)
                        else:
                            mermaid_report["failed"].append({"key": key, "error": err[:200]})
                    diagrams_dir = str(render_dir)
        except Exception as e:
            mermaid_report = {"error": str(e)}

    jobs = {
        "xlsx": {
            "template": "test-case.xlsx",
            "output": "kich-ban-kiem-thu.xlsx",
            "engine": "xlsx",
        },
        "hdsd": {
            "template": "huong-dan-su-dung.docx",
            "output": "huong-dan-su-dung.docx",
            "engine": "docx",
        },
        "tkkt": {
            "template": "thiet-ke-kien-truc.docx",
            "output": "thiet-ke-kien-truc.docx",
            "engine": "docx",
        },
        "tkcs": {
            "template": "thiet-ke-co-so.docx",
            "output": "thiet-ke-co-so.docx",
            "engine": "docx",
        },
        "tkct": {
            "template": "thiet-ke-chi-tiet.docx",
            "output": "thiet-ke-chi-tiet.docx",
            "engine": "docx",
        },
    }

    results = []
    for name, spec in jobs.items():
        if name not in target_set:
            continue

        output_path = out_dir / spec["output"]
        try:
            tpl_path = template(spec["template"])
        except FileNotFoundError:
            results.append({"target": name, "success": False, "error": "Template not found"})
            continue

        try:
            if spec["engine"] == "xlsx":
                from etc_docgen.paths import schema as schema_path

                report = xlsx_engine.fill(
                    tpl_path,
                    schema_path("test-case.xlsx.schema.yaml"),
                    data_file,
                    output_path,
                )
                results.append(
                    {
                        "target": name,
                        "success": not report.validator_failures,
                        "output": str(output_path),
                        "warnings": report.validator_failures[:5]
                        if report.validator_failures
                        else [],
                    }
                )
            else:
                ss_dir = Path(screenshots_dir) if screenshots_dir and name == "hdsd" else None
                if ss_dir and not ss_dir.exists():
                    ss_dir = None

                dg_dir = Path(diagrams_dir) if diagrams_dir else None
                if dg_dir and not dg_dir.exists():
                    dg_dir = None
                report = docx_engine.render(
                    tpl_path, data_file, output_path,
                    screenshots_dir=ss_dir, diagrams_dir=dg_dir,
                )
                results.append(
                    {
                        "target": name,
                        "success": not report.errors,
                        "output": str(output_path),
                        "screenshots_embedded": report.screenshots_embedded,
                        "screenshots_missing": report.screenshots_missing,
                        "warnings": report.warnings[:5],
                        "errors": report.errors[:5],
                    }
                )
        except Exception as e:
            results.append({"target": name, "success": False, "error": str(e)})

    all_ok = all(r["success"] for r in results)
    return json.dumps(
        {"success": all_ok, "targets": results},
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
def schema() -> str:
    """Get the full JSON Schema for content-data.json.

    Use this to understand the exact format agents must produce.
    The schema defines all fields for HDSD, TKKT, TKCS, TKCT and test case data.
    """
    from etc_docgen.data.models import ContentData

    return json.dumps(
        ContentData.model_json_schema(),
        indent=2,
        ensure_ascii=False,
    )


@mcp.tool()
def section_schema(doc_type: str) -> str:
    """Get the JSON Schema for a specific document type — saves tokens vs full schema.

    Returns only the relevant Pydantic model schema for the target document type,
    plus shared models (project, meta, overview) needed as context.

    This is the recommended first call for doc-writer agents: get the schema for
    the section you need to fill, understand the fields, then produce JSON.

    Args:
        doc_type: Target document type. Options:
            - tkcs: Thiết kế cơ sở (NĐ 45/2026 Điều 13)
            - tkct: Thiết kế chi tiết
            - tkkt: Thiết kế kiến trúc
            - hdsd: Hướng dẫn sử dụng
            - xlsx: Kịch bản kiểm thử (test cases)
    """
    from etc_docgen.data.models import (
        Architecture,
        Feature,
        Meta,
        Overview,
        ProjectInfo,
        Service,
        TestCases,
        TestSheetConfig,
        TkcsData,
        TkctData,
        TroubleshootingItem,
    )

    # Map doc type → primary models + which content-data keys to fill
    type_map: dict[str, dict] = {
        "tkcs": {
            "primary_model": TkcsData,
            "support_models": [ProjectInfo, Meta, Overview],
            "content_data_keys": ["project", "meta", "overview", "tkcs"],
            "description": (
                "TKCS (Thiết kế cơ sở) — NĐ 45/2026 Điều 13. "
                "Fill tkcs.* fields with formal Vietnamese prose. "
                "Reuse project/meta/overview from shared context."
            ),
        },
        "tkct": {
            "primary_model": TkctData,
            "support_models": [ProjectInfo, Meta, Overview],
            "content_data_keys": ["project", "meta", "overview", "tkct"],
            "description": (
                "TKCT (Thiết kế chi tiết). Fill tkct.* with detailed design: "
                "modules, db_tables, api_details, screens, integration, security."
            ),
        },
        "tkkt": {
            "primary_model": Architecture,
            "support_models": [ProjectInfo, Meta, Overview],
            "content_data_keys": ["project", "meta", "overview", "architecture"],
            "description": (
                "TKKT (Thiết kế kiến trúc). Fill architecture.* with: "
                "tech_stack, components, data_entities, apis, deployment, security, nfr."
            ),
        },
        "hdsd": {
            "primary_model": Service,
            "support_models": [ProjectInfo, Meta, Overview, Feature, TroubleshootingItem],
            "content_data_keys": ["project", "meta", "overview", "services", "troubleshooting"],
            "description": (
                "HDSD (Hướng dẫn sử dụng). Fill services[].features[] with steps, "
                "ui_elements, dialogs, error_cases. Also fill troubleshooting[]."
            ),
        },
        "xlsx": {
            "primary_model": TestCases,
            "support_models": [ProjectInfo, Meta, TestSheetConfig],
            "content_data_keys": ["project", "meta", "dev_unit", "test_cases", "test_sheets"],
            "description": (
                "Test cases (xlsx). Fill test_cases.ui[] and test_cases.api[] "
                "with feature_group, section_header, and test_case rows. "
                "Also fill dev_unit (đơn vị phát triển) and test_sheets labels if needed."
            ),
        },
    }

    if doc_type not in type_map:
        return json.dumps(
            {"error": f"Unknown doc_type: {doc_type}. Options: {list(type_map.keys())}"}
        )

    spec = type_map[doc_type]
    primary_schema = spec["primary_model"].model_json_schema()
    support_schemas = {m.__name__: m.model_json_schema() for m in spec["support_models"]}

    return json.dumps(
        {
            "doc_type": doc_type,
            "description": spec["description"],
            "content_data_keys": spec["content_data_keys"],
            "primary_schema": primary_schema,
            "support_schemas": support_schemas,
        },
        indent=2,
        ensure_ascii=False,
    )


@mcp.tool()
def merge_content(data_path: str, partial_json: str) -> str:
    """Merge partial content into an existing content-data.json file.

    Use this for incremental writing: each doc-writer agent fills its section,
    then merges into the shared content-data.json. Supports deep merge —
    nested dicts are merged recursively, lists are replaced (not appended).

    Workflow:
      1. Agent calls section_schema(doc_type) to get field definitions
      2. Agent produces JSON for its section (e.g. {"tkcs": {...}})
      3. Agent calls merge_content to write it into content-data.json
      4. Agent calls validate to verify the merged result

    Args:
        data_path: Path to existing content-data.json (created if missing)
        partial_json: JSON string with partial content to merge.
            Example: {"tkcs": {"legal_basis": "...", "necessity": "..."}}
    """
    path = Path(data_path)

    # Load existing or start with minimal skeleton
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return json.dumps({"success": False, "error": f"Invalid JSON in {data_path}: {e}"})
    else:
        existing = {}

    # Parse partial
    try:
        partial = json.loads(partial_json) if isinstance(partial_json, str) else partial_json
    except json.JSONDecodeError as e:
        return json.dumps({"success": False, "error": f"Invalid partial JSON: {e}"})

    if not isinstance(partial, dict):
        return json.dumps({"success": False, "error": "partial_json must be a JSON object"})

    # Deep merge
    def _deep_merge(base: dict, patch: dict) -> dict:
        for k, v in patch.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                _deep_merge(base[k], v)
            else:
                base[k] = v
        return base

    merged = _deep_merge(existing, partial)

    # Write back
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")

    # Quick validation pass
    merged_keys = list(merged.keys())
    partial_keys = list(partial.keys())

    return json.dumps(
        {
            "success": True,
            "path": str(path),
            "merged_keys": partial_keys,
            "total_keys": merged_keys,
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
def field_map(doc_type: str) -> str:
    """Get the interview-to-field mapping for a doc type.

    Returns a structured reference showing which interview questions/data
    map to which content-data.json fields, organized by field type
    (prose, structured, diagram).

    Use this to understand HOW to fill content-data.json from interview/DCB data.
    Complements section_schema which shows WHAT fields exist.

    Args:
        doc_type: Target document type (tkcs, tkct, tkkt, hdsd)
    """
    from etc_docgen.integrations.field_maps import (
        get_field_map,
        get_writer_prompt_context,
        uses_docgen,
    )

    if not uses_docgen(doc_type):
        return json.dumps(
            {
                "doc_type": doc_type,
                "renderer": "pandoc",
                "message": f"'{doc_type}' uses Pandoc pipeline. No etc-docgen field mapping.",
            }
        )

    fmap = get_field_map(doc_type)
    if not fmap:
        return json.dumps({"error": f"No field map for '{doc_type}'"})

    return json.dumps(
        {
            "doc_type": doc_type,
            "renderer": "etc-docgen",
            "field_map": fmap,
            "writer_prompt_context": get_writer_prompt_context(doc_type),
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
def template_list() -> str:
    """List all bundled ETC document templates with their sizes.

    Returns template filenames and sizes. These templates are pre-configured
    with Jinja2 tags for docxtpl rendering.
    """
    tpl_dir = templates_dir()
    items = []
    for p in sorted(tpl_dir.glob("*")):
        items.append(
            {
                "filename": p.name,
                "size_kb": p.stat().st_size // 1024,
                "path": str(p),
            }
        )
    return json.dumps(items, ensure_ascii=False, indent=2)


@mcp.tool()
def template_fork(source_path: str, kind: str = "hdsd") -> str:
    """Fork an original ETC template by adding Jinja2 (docxtpl) tags.

    Use this when ETC releases a new template version. The forked template
    replaces the bundled one and is used by the export tool.

    Args:
        source_path: Path to the original ETC .docx template
        kind: Template type — hdsd, tkkt, tkcs, or tkct
    """
    from etc_docgen.tools.jinjafy_templates import (
        jinjafy_hdsd,
        jinjafy_tkcs,
        jinjafy_tkct,
        jinjafy_tkkt,
    )

    source = Path(source_path)
    if not source.exists():
        return json.dumps({"success": False, "error": f"Source not found: {source_path}"})

    dest_map = {
        "hdsd": "huong-dan-su-dung.docx",
        "tkkt": "thiet-ke-kien-truc.docx",
        "tkcs": "thiet-ke-co-so.docx",
        "tkct": "thiet-ke-chi-tiet.docx",
    }
    if kind not in dest_map:
        return json.dumps(
            {"success": False, "error": f"Unknown kind: {kind}. Use: hdsd, tkkt, tkcs, tkct"}
        )

    dest = templates_dir() / dest_map[kind]
    fork_fn = {
        "hdsd": jinjafy_hdsd,
        "tkkt": jinjafy_tkkt,
        "tkcs": jinjafy_tkcs,
        "tkct": jinjafy_tkct,
    }[kind]

    try:
        fork_fn(source, dest)
        return json.dumps(
            {
                "success": True,
                "kind": kind,
                "source": str(source),
                "output": str(dest),
            }
        )
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


# ─────────────────────────── Entry point ───────────────────────────


def main():
    """Run MCP server. Supports stdio, sse, and streamable-http transports.

    Use --transport to select transport, --host/--port for network transports.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="etc-docgen MCP Server",
        prog="etc-docgen-mcp",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind for sse/streamable-http (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind for sse/streamable-http (default: 8000)",
    )

    args = parser.parse_args()

    # Update host/port on the mcp settings for network transports
    if args.transport in ("sse", "streamable-http"):
        mcp.settings.host = args.host
        mcp.settings.port = args.port

    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
