"""
engines/diagram.py — Unified diagram rendering engine.

Renders entries in `content-data.json` → `diagrams: {...}` block to PNG files,
ready for InlineImage embedding into DOCX by engines/docx.py.

Supported source forms (detected per-entry):

1. **Mermaid source (string)** — existing behavior:
       "architecture": "graph TD\\n..."
   Rendered via `mmdc` CLI (render_mermaid.render_one).

2. **SVG Jinja2 hero (dict)** — new in Stage B:
       "T1-kien-truc": {
           "template": "kien-truc-4-lop",     # picks svg/kien-truc-4-lop.svg.j2
           "data":     { ... template-specific schema ... }
       }
   Rendered via Jinja2 → SVG → Chromium (Playwright) → PNG.

3. **Mermaid explicit (dict)**:
       "comp": {"type": "mermaid", "source": "graph TD..."}

Output: PNG files named `{key}.png` under `out_dir`. The docx engine's
`build_diagram_context` later resolves diagram filenames referenced from
architecture/tkcs/tkct fields → InlineImage objects.

Hero SVG templates available (Tier 1):
  - kien-truc-4-lop       (T1 — 4-layer architecture)
  - ndxp-hub-spoke        (T2 — NDXP hub-spoke)
  - swimlane-workflow     (T3 — DVC swimlane)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("etc-docgen.diagram")

# Directory containing Jinja2 source templates (shipped with package).
_PKG_DIR = Path(__file__).resolve().parent.parent
SVG_TPL_DIR = _PKG_DIR / "templates" / "diagrams" / "svg"
MERMAID_TPL_DIR = _PKG_DIR / "templates" / "diagrams" / "mermaid"

# Known Mermaid source prefixes — used to distinguish Mermaid string vs accidental plaintext
_MERMAID_PREFIXES = (
    "graph", "flowchart", "sequenceDiagram", "erDiagram", "classDiagram",
    "stateDiagram", "journey", "gantt", "pie", "gitGraph", "mindmap",
    "timeline", "quadrantChart", "requirementDiagram", "C4Context",
    "C4Container", "C4Component", "C4Dynamic",
)


@dataclass
class DiagramReport:
    rendered: list[dict] = field(default_factory=list)     # [{key,type,path,size_kb}]
    failed: list[dict] = field(default_factory=list)       # [{key,type,error}]
    warnings: list[str] = field(default_factory=list)
    out_dir: str = ""
    mmdc_available: bool = False
    playwright_available: bool = False

    def to_dict(self) -> dict:
        status = "ok"
        if self.failed and self.rendered:
            status = "partial"
        elif self.failed and not self.rendered:
            status = "failed"
        elif not self.rendered and not self.failed:
            status = "empty"
        return {
            "status": status,
            "out_dir": self.out_dir,
            "rendered": self.rendered,
            "failed": self.failed,
            "warnings": self.warnings,
            "mmdc_available": self.mmdc_available,
            "playwright_available": self.playwright_available,
        }


# ─────────────────────── SVG Jinja2 rendering ───────────────────────


def _render_svg_template(template_name: str, data: dict) -> str:
    """Render an SVG Jinja2 template by bare name (no .svg.j2).

    Example: _render_svg_template("kien-truc-4-lop", {...}) →
        loads src/etc_docgen/templates/diagrams/svg/kien-truc-4-lop.svg.j2
    """
    from jinja2 import Environment, FileSystemLoader, StrictUndefined

    # Accept both bare name and full filename
    candidates = [
        f"{template_name}.svg.j2",
        template_name if template_name.endswith(".svg.j2") else f"{template_name}.svg.j2",
        template_name,
    ]
    env = Environment(
        loader=FileSystemLoader(str(SVG_TPL_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=True,  # Escape &, <, > — required for Vietnamese text in SVG
    )
    last_err: Exception | None = None
    for name in candidates:
        try:
            tpl = env.get_template(name)
            return tpl.render(**(data or {}))
        except Exception as e:  # jinja2.TemplateNotFound or render error
            last_err = e
            continue
    available = sorted(p.name for p in SVG_TPL_DIR.glob("*.svg.j2"))
    raise FileNotFoundError(
        f"SVG template not found or failed to render: {template_name}. "
        f"Available: {available}. Last error: {last_err}"
    )


def _svg_to_png_playwright(svg_text: str, png_path: Path, scale: float = 2.0) -> None:
    """Convert SVG source → PNG via headless Chromium (pixel-perfect)."""
    from playwright.sync_api import sync_playwright

    # Escape only `<`/`>` inside the SVG? No — SVG is already valid XML, inject as-is.
    body = svg_text
    page_html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>body{margin:0;padding:0;background:white;} svg{display:block;}</style>"
        f"</head><body>{body}</body></html>"
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
        ctx = browser.new_context(device_scale_factor=scale)
        page = ctx.new_page()
        page.set_content(page_html, wait_until="domcontentloaded")
        svg_el = page.locator("svg").first
        box = svg_el.bounding_box()
        if box:
            page.set_viewport_size(
                {"width": int(box["width"]) + 10, "height": int(box["height"]) + 10}
            )
        svg_el.screenshot(path=str(png_path), omit_background=False)
        browser.close()


def _render_svg_hero(
    key: str, spec: dict, out_dir: Path, report: DiagramReport
) -> Path | None:
    """Render an SVG hero entry → PNG (+ side-by-side .svg for debug).

    Returns Path to PNG on success, None on failure.
    """
    tpl_name = spec.get("template")
    data = spec.get("data") or {}
    if not tpl_name:
        report.failed.append({"key": key, "type": "svg", "error": "Missing 'template' field"})
        return None

    # Render Jinja2 → SVG string
    try:
        svg_text = _render_svg_template(tpl_name, data)
    except Exception as e:
        report.failed.append({"key": key, "type": "svg", "error": f"Jinja render: {e}"})
        return None

    # Save SVG artifact (useful even if PNG step fails — docx engine can fall back to SVG)
    svg_path = out_dir / f"{key}.svg"
    svg_path.write_text(svg_text, encoding="utf-8")

    # Convert SVG → PNG
    png_path = out_dir / f"{key}.png"
    if not report.playwright_available:
        report.failed.append({
            "key": key, "type": "svg",
            "error": "Playwright not installed — SVG saved but PNG not rendered. "
                     "Install: pip install playwright && playwright install chromium",
        })
        return None

    try:
        _svg_to_png_playwright(svg_text, png_path)
    except Exception as e:
        report.failed.append({"key": key, "type": "svg", "error": f"SVG→PNG: {type(e).__name__}: {e}"})
        return None

    report.rendered.append({
        "key": key, "type": "svg", "template": tpl_name,
        "path": str(png_path),
        "size_kb": png_path.stat().st_size // 1024,
    })
    return png_path


# ─────────────────────── Mermaid rendering ───────────────────────


def _render_mermaid(
    key: str, source: str, out_dir: Path, mmdc_cmd: str, report: DiagramReport
) -> Path | None:
    from etc_docgen.tools.render_mermaid import render_one

    source = source.replace("\x00", "").strip()
    if len(source) > 500_000:
        report.failed.append({"key": key, "type": "mermaid", "error": "Source too large (>500KB)"})
        return None

    out_png = out_dir / f"{key}.png"
    ok, err = render_one(mmdc_cmd, source, out_png)
    if ok:
        report.rendered.append({
            "key": key, "type": "mermaid",
            "path": str(out_png),
            "size_kb": out_png.stat().st_size // 1024,
        })
        return out_png

    # Save source for debugging
    (out_dir / f"{key}.mmd").write_text(source, encoding="utf-8")
    report.failed.append({"key": key, "type": "mermaid", "error": (err or "")[:300]})
    return None


# ─────────────────────── Dispatch ───────────────────────


def _detect_type(value) -> str:
    """Return 'svg' | 'mermaid' | 'unknown'."""
    if isinstance(value, str):
        return "mermaid"  # strings default to Mermaid (back-compat)
    if isinstance(value, dict):
        t = (value.get("type") or "").lower()
        if t == "svg":
            return "svg"
        if t == "mermaid":
            return "mermaid"
        if "template" in value:  # implicit SVG (has template field)
            return "svg"
        if "source" in value:    # implicit Mermaid (has source field)
            return "mermaid"
    return "unknown"


def _check_playwright() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def render_all(data: dict, out_dir: Path) -> DiagramReport:
    """Render every entry in `data['diagrams']` to `out_dir`. Returns a report.

    Entries may be Mermaid strings OR SVG Jinja2 template refs. The engine
    auto-detects per entry — Mermaid and SVG can coexist in one content-data.json.
    """
    from etc_docgen.tools.render_mermaid import check_mmdc

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = DiagramReport(out_dir=str(out_dir))
    report.mmdc_available = bool(check_mmdc())
    report.playwright_available = _check_playwright()

    diagrams = (data or {}).get("diagrams") or {}
    if not diagrams:
        report.warnings.append("No 'diagrams' block in content-data.json")
        return report

    if not report.mmdc_available:
        report.warnings.append(
            "Mermaid CLI (mmdc) not found — Mermaid entries will be skipped. "
            "Install: npm install -g @mermaid-js/mermaid-cli"
        )
    if not report.playwright_available:
        report.warnings.append(
            "Playwright not installed — SVG hero entries cannot render to PNG. "
            "Install: pip install playwright && playwright install chromium"
        )

    mmdc_cmd = check_mmdc() if report.mmdc_available else None

    for key, value in diagrams.items():
        # Skip empty entries cleanly
        if value is None or (isinstance(value, str) and not value.strip()):
            report.warnings.append(f"Empty diagram source: {key}")
            continue

        # Sanitize key: filesystem-safe (no slashes, quotes)
        safe_key = re.sub(r"[^\w.\-]+", "_", str(key)).strip("_") or "diagram"

        dtype = _detect_type(value)
        if dtype == "svg":
            _render_svg_hero(safe_key, value, out_dir, report)
        elif dtype == "mermaid":
            if not mmdc_cmd:
                report.failed.append({"key": safe_key, "type": "mermaid", "error": "mmdc not available"})
                continue
            # Extract source string
            src = value if isinstance(value, str) else (value.get("source") or "")
            if not src.strip():
                report.warnings.append(f"Empty Mermaid source: {safe_key}")
                continue
            _render_mermaid(safe_key, src, out_dir, mmdc_cmd, report)
        else:
            report.failed.append({
                "key": safe_key, "type": "unknown",
                "error": f"Cannot detect diagram type for value of kind {type(value).__name__}",
            })

    log.info(
        "diagram render done: rendered=%d failed=%d out=%s",
        len(report.rendered), len(report.failed), out_dir,
    )
    return report


__all__ = ["DiagramReport", "render_all", "SVG_TPL_DIR", "MERMAID_TPL_DIR"]
