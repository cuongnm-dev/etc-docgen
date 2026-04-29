"""etc-platform CLI — typer-based, rich-formatted."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from etc_platform import __version__
from etc_platform.config import Config, load_config, write_example_config
from etc_platform.paths import schema, template, templates_dir

app = typer.Typer(
    name="etc-platform",
    help="Template-first documentation generator for ETC projects.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)
console = Console()
err_console = Console(stderr=True)


# ─────────────────────────── Version ───────────────────────────


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"[bold]etc-platform[/bold] v{__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-V",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit",
        ),
    ] = None,
) -> None:
    """etc-platform — turn codebase + Docker into TKKT, TKCS, Test Case, HDSD documents."""


# ─────────────────────────── init ───────────────────────────


@app.command()
def init(
    path: Annotated[
        Path,
        typer.Argument(help="Directory to initialize (default: current dir)"),
    ] = Path("."),
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite existing etc-platform.yaml"),
    ] = False,
) -> None:
    """Initialize etc-platform config in current directory."""
    config_file = path / "etc-platform.yaml"
    if config_file.exists() and not force:
        err_console.print(
            f"[yellow]⚠[/yellow] {config_file} already exists. Use [cyan]--force[/cyan] to overwrite."
        )
        raise typer.Exit(1)

    write_example_config(config_file)

    # Also create .gitignore entry if repo is git-tracked
    gitignore = path / ".gitignore"
    gitignore_lines = (
        gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
    )
    if "auth.json" not in "".join(gitignore_lines):
        with gitignore.open("a", encoding="utf-8") as f:
            f.write("\n# etc-platform\nauth.json\nstate.json\n.auth/\n")
        console.print("[green]✓[/green] Added credentials to .gitignore")

    console.print(
        Panel(
            f"[green]✓[/green] Created [cyan]{config_file}[/cyan]\n\n"
            f"Next steps:\n"
            f"  1. Edit [cyan]etc-platform.yaml[/cyan] with your project info\n"
            f"  2. Set credentials: [yellow]export DOCGEN_USERNAME=...[/yellow]\n"
            f"  3. Run: [cyan]etc-platform generate[/cyan]",
            title="Config created",
        )
    )


# ─────────────────────────── generate (full pipeline) ───────────────────────────


@app.command()
def generate(
    config_path: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Config file path (default: ./etc-platform.yaml)"),
    ] = None,
    skip: Annotated[
        list[str] | None,
        typer.Option("--skip", help="Skip phases: research, capture, data, export"),
    ] = None,
    only: Annotated[
        list[str] | None,
        typer.Option("--only", help="Run only these phases"),
    ] = None,
    incremental: Annotated[
        bool,
        typer.Option("--incremental", help="Regen only changed services (Git diff)"),
    ] = False,
) -> None:
    """Run full pipeline: research → capture → data → export."""
    cfg = _load_cfg(config_path)

    phases_all = ["research", "capture", "data", "export"]
    skip_set = set(skip or [])
    only_set = set(only or [])
    phases_to_run = [p for p in phases_all if p not in skip_set and (not only_set or p in only_set)]

    console.print(
        Panel(
            f"[bold]Project:[/bold] {cfg.project.name}\n"
            f"[bold]Phases:[/bold] {' → '.join(phases_to_run)}\n"
            f"[bold]Output:[/bold] {cfg.output.path}",
            title="etc-platform pipeline",
        )
    )

    for phase in phases_to_run:
        console.rule(f"[bold cyan]Phase: {phase}[/bold cyan]")
        if phase == "research":
            _run_research(cfg)
        elif phase == "capture":
            _run_capture(cfg)
        elif phase == "data":
            _run_data(cfg)
        elif phase == "export":
            _run_export(cfg)

    console.print("[green]✓ Pipeline complete[/green]")


# ─────────────────────────── Individual phase commands ───────────────────────────


@app.command()
def research(
    config_path: Annotated[Path | None, typer.Option("--config", "-c")] = None,
) -> None:
    """Phase 1: scan codebase, produce intel/*.json reports."""
    cfg = _load_cfg(config_path)
    _run_research(cfg)


@app.command()
def capture(
    config_path: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    service: Annotated[
        str | None,
        typer.Option("--service", help="Only capture this service"),
    ] = None,
) -> None:
    """Phase 2: run Playwright to capture UI screenshots."""
    cfg = _load_cfg(config_path)
    _run_capture(cfg, service=service)


@app.command()
def data(
    config_path: Annotated[Path | None, typer.Option("--config", "-c")] = None,
) -> None:
    """Phase 3: build content-data.json from intel reports."""
    cfg = _load_cfg(config_path)
    _run_data(cfg)


@app.command()
def export(
    config_path: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    data_file: Annotated[
        Path | None,
        typer.Option(
            "--data", "-d", help="Path to content-data.json (default: {output}/content-data.json)"
        ),
    ] = None,
    only: Annotated[
        list[str] | None,
        typer.Option("--only", help="Only these formats: xlsx, hdsd, tkkt, tkcs"),
    ] = None,
) -> None:
    """Phase 4: render Office files from content-data.json."""
    cfg = _load_cfg(config_path)
    _run_export(cfg, data_file=data_file, only=only)


# ─────────────────────────── Template management ───────────────────────────

template_app = typer.Typer(help="Manage document templates.")
app.add_typer(template_app, name="template")


@template_app.command("list")
def template_list() -> None:
    """List bundled templates."""
    tbl = Table(title="Bundled templates", show_lines=True)
    tbl.add_column("Filename")
    tbl.add_column("Size (KB)", justify="right")
    tbl.add_column("Path")
    for p in sorted(templates_dir().glob("*")):
        size_kb = p.stat().st_size // 1024
        tbl.add_row(p.name, str(size_kb), str(p))
    console.print(tbl)


@template_app.command("fork")
def template_fork(
    source: Annotated[Path, typer.Argument(help="Path to ETC template file to fork")],
    kind: Annotated[
        str,
        typer.Option("--kind", "-k", help="Template kind: hdsd | tkkt | tkcs"),
    ] = "hdsd",
) -> None:
    """Fork an ETC template with Jinja2 tags for docxtpl rendering.

    Example:
      etc-platform template fork ~/Downloads/BM.QT.04.05-v2.docx --kind hdsd
    """
    from etc_platform.tools.jinjafy_templates import jinjafy_hdsd, jinjafy_tkcs, jinjafy_tkkt

    dest = (
        templates_dir()
        / {
            "hdsd": "huong-dan-su-dung.docx",
            "tkkt": "thiet-ke-kien-truc.docx",
            "tkcs": "thiet-ke-co-so.docx",
        }[kind]
    )

    console.print(f"Forking [cyan]{kind.upper()}[/cyan]: {source} → {dest}")
    if kind == "hdsd":
        jinjafy_hdsd(source, dest)
    elif kind == "tkkt":
        jinjafy_tkkt(source, dest)
    elif kind == "tkcs":
        jinjafy_tkcs(source, dest)
    else:
        err_console.print(f"[red]Unknown kind:[/red] {kind}")
        raise typer.Exit(1)

    console.print(f"[green]✓[/green] Forked template saved: {dest}")


# ─────────────────────────── validate ───────────────────────────


@app.command()
def validate(
    data_file: Annotated[Path, typer.Argument(help="Path to content-data.json")],
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Treat warnings as errors"),
    ] = False,
) -> None:
    """Validate content-data.json against Pydantic schema + advisory checks."""
    from etc_platform.data.validation import validate_file

    result = validate_file(data_file)

    if not result.valid:
        err_console.print(f"[red]✗ Validation failed[/red] — {len(result.errors)} errors:")
        for e in result.errors[:20]:
            err_console.print(f"  [red]•[/red] {e}")
        raise typer.Exit(1)

    # Show warnings
    if result.warnings:
        console.print(f"\n[yellow]⚠ {len(result.warnings)} warnings:[/yellow]")
        for w in result.warnings:
            console.print(f"  [yellow]•[/yellow] {w}")

    if strict and result.warnings:
        err_console.print(
            f"\n[red]✗ Strict mode:[/red] {len(result.warnings)} warnings treated as errors"
        )
        raise typer.Exit(1)

    # Show stats
    stats = result.stats
    pri_dist = stats.get("priority_distribution", {})
    pri_str = ", ".join(f"{k}: {v}" for k, v in sorted(pri_dist.items())) or "N/A"

    console.print(
        Panel(
            f"[green]✓ Valid[/green]\n\n"
            f"Services:        {stats.get('services', 0)}\n"
            f"Features:        {stats.get('features', 0)}\n"
            f"Test cases (UI): {stats.get('test_cases_ui', 0)}\n"
            f"Test cases (API):{stats.get('test_cases_api', 0)}\n"
            f"Total TCs:       {stats.get('test_cases_total', 0)}\n"
            f"Priority dist:   {pri_str}",
            title="content-data.json",
        )
    )


@app.command(name="schema")
def dump_schema(
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write JSON Schema to file (default: stdout)"),
    ] = None,
) -> None:
    """Print or export the JSON Schema for content-data.json."""
    from etc_platform.data.validation import generate_json_schema

    schema = generate_json_schema()
    schema_json = json.dumps(schema, indent=2, ensure_ascii=False)

    if output:
        output.write_text(schema_json, encoding="utf-8")
        console.print(f"[green]✓[/green] Schema written to [cyan]{output}[/cyan]")
    else:
        console.print(schema_json)


# ─────────────────────────── Internal helpers ───────────────────────────


def _load_cfg(path: Path | None) -> Config:
    """Load config with user-friendly error."""
    try:
        return load_config(path)
    except FileNotFoundError as e:
        err_console.print(f"[red]Config not found:[/red] {e}")
        err_console.print("[dim]Run [cyan]etc-platform init[/cyan] to create one.[/dim]")
        raise typer.Exit(1) from e
    except Exception as e:
        err_console.print(f"[red]Config error:[/red] {e}")
        raise typer.Exit(1) from e


def _run_research(cfg: Config) -> None:
    """Phase 1 — stub in v0.1; will call research module in v0.2."""
    console.print("[yellow]⚠[/yellow] Research phase not yet implemented in v0.1.")
    console.print(
        "[dim]For now, produce intel/*.json manually or via AI (Cursor/Claude Code).[/dim]"
    )


def _run_capture(cfg: Config, service: str | None = None) -> None:
    """Phase 2 — stub; requires [capture] extras. Wire in v0.2."""
    console.print("[yellow]⚠[/yellow] Capture phase not yet implemented in v0.1.")
    console.print("[dim]For now, use Playwright MCP in Cursor or Claude Code.[/dim]")


def _run_data(cfg: Config) -> None:
    """Phase 3 — stub; AI integration in v0.2."""
    console.print("[yellow]⚠[/yellow] Data writer phase not yet implemented in v0.1.")
    console.print(
        "[dim]For now, AI agent in Cursor/Claude Code produces "
        "[cyan]content-data.json[/cyan] manually.[/dim]"
    )


def _run_export(cfg: Config, data_file: Path | None = None, only: list[str] | None = None) -> None:
    """Phase 4 — fully working in v0.1.

    Renders xlsx + 3 docx from content-data.json using bundled templates.
    """
    output_dir = Path(cfg.output.path)
    output_dir.mkdir(parents=True, exist_ok=True)

    if data_file is None:
        data_file = output_dir / "content-data.json"

    if not data_file.exists():
        err_console.print(
            f"[red]content-data.json not found:[/red] {data_file}\n"
            f"[dim]Run Phase 3 first, or pass [cyan]--data PATH[/cyan][/dim]"
        )
        raise typer.Exit(1)

    only_set = set(only or []) or {"xlsx", "hdsd", "tkkt", "tkcs", "tkct"}

    from etc_platform.engines import docx as docx_engine
    from etc_platform.engines import xlsx as xlsx_engine

    jobs = [
        (
            "xlsx",
            {
                "template": template("test-case.xlsx"),
                "schema": schema("test-case.xlsx.schema.yaml"),
                "output": output_dir / "kich-ban-kiem-thu.xlsx",
                "engine": "xlsx",
            },
        ),
        (
            "hdsd",
            {
                "template": template("huong-dan-su-dung.docx"),
                "output": output_dir / "huong-dan-su-dung.docx",
                "engine": "docx",
                "screenshots_dir": Path("screenshots"),
            },
        ),
        (
            "tkkt",
            {
                "template": template("thiet-ke-kien-truc.docx"),
                "output": output_dir / "thiet-ke-kien-truc.docx",
                "engine": "docx",
            },
        ),
        (
            "tkcs",
            {
                "template": template("thiet-ke-co-so.docx"),
                "output": output_dir / "thiet-ke-co-so.docx",
                "engine": "docx",
            },
        ),
        (
            "tkct",
            {
                "template": template("thiet-ke-chi-tiet.docx"),
                "output": output_dir / "thiet-ke-chi-tiet.docx",
                "engine": "docx",
            },
        ),
    ]

    failed = []
    for name, spec in jobs:
        if name not in only_set:
            continue
        console.print(f"  [cyan]→[/cyan] {name}: {spec['output'].name}")
        try:
            if spec["engine"] == "xlsx":
                report = xlsx_engine.fill(
                    spec["template"], spec["schema"], data_file, spec["output"]
                )
                if report.validator_failures:
                    failed.append((name, report.validator_failures))
            else:
                screenshots = (
                    spec.get("screenshots_dir")
                    if spec.get("screenshots_dir", Path()).exists()
                    else None
                )
                report = docx_engine.render(
                    spec["template"],
                    data_file,
                    spec["output"],
                    screenshots_dir=screenshots,
                )
                if report.errors:
                    failed.append((name, report.errors))
        except Exception as e:
            failed.append((name, [str(e)]))
            err_console.print(f"    [red]✗ {e}[/red]")

    if failed:
        err_console.print(f"\n[red]Export failed for {len(failed)} targets:[/red]")
        for name, errs in failed:
            for e in errs[:3]:
                err_console.print(f"  [red]✗ {name}:[/red] {e}")
        raise typer.Exit(1)

    console.print(f"\n[green]✓ All outputs written to {output_dir}[/green]")


# ─────────────────────────── MCP server ───────────────────────────


@app.command(
    name="mcp", context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def mcp_serve(
    ctx: typer.Context,
    transport: Annotated[
        str,
        typer.Option("--transport", "-t", help="Transport: stdio, sse, streamable-http"),
    ] = "stdio",
    host: Annotated[
        str,
        typer.Option("--host", help="Host for sse/streamable-http (default: 127.0.0.1)"),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option("--port", "-p", help="Port for sse/streamable-http (default: 8000)"),
    ] = 8000,
) -> None:
    """Start MCP server for IDE agent integration.

    Transports:
      stdio (default) — for local IDE (VS Code, Cursor, Claude Desktop)
      sse             — for Docker / remote (HTTP + Server-Sent Events)
      streamable-http — newer HTTP-based MCP transport

    Examples:
      etc-platform mcp                              # stdio (local)
      etc-platform mcp -t sse -p 8000               # SSE on port 8000
      etc-platform mcp -t sse --host 0.0.0.0        # SSE, all interfaces (Docker)
    """
    import sys

    # Build argv for mcp_server.main() argparse
    sys.argv = [
        "etc-platform-mcp",
        "--transport",
        transport,
        "--host",
        host,
        "--port",
        str(port),
    ]

    from etc_platform.mcp_server import main as mcp_main

    mcp_main()


if __name__ == "__main__":
    app()
