#!/usr/bin/env python3
"""
render_docx.py — Jinja2-based .docx rendering via docxtpl.

REPLACES: fill_docx_engine.py (~900 lines of custom XML manipulation)

Philosophy: Templates are forks of ETC masters with {{ }} / {% %} tags added.
DocxTpl (Jinja2 for Word) does the actual rendering.

Template authoring convention:
  - {{ project.display_name }}        → simple substitution
  - {%tr for f in features %} ... {%tr endfor %}   → loop table rows
  - {%p if feat.preconditions %} ... {%p endif %}  → conditional paragraphs
  - {%p for step in steps %}{{ step.action }}{%p endfor %}   → loop paragraphs
  - Image: passed via context as InlineImage(tpl, path, width)

Post-processing after render:
  - TOC dirty flag (so Word refreshes on open)
  - Embed screenshots as InlineImage in context pre-render

Usage:
  python render_docx.py \
    --template       path/to/template-jinja.docx \
    --data           content-data.json \
    --output         out/filled.docx \
    [--screenshots-dir path/]   # optional, enables InlineImage for screenshots
    [--report        out/render-report.json]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

try:
    from docx.shared import Inches, Mm
    from docxtpl import DocxTemplate, InlineImage
except ImportError:
    print("ERROR: docxtpl required. Run: pip install docxtpl python-docx", file=sys.stderr)
    sys.exit(2)

try:
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
except ImportError:
    print("ERROR: python-docx required", file=sys.stderr)
    sys.exit(2)


WNS_QN = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


# ─────────────────────────── Report ───────────────────────────


@dataclass
class RenderReport:
    template: str = ""
    output: str = ""
    screenshots_embedded: int = 0
    screenshots_missing: int = 0
    tokens_substituted: int = 0  # approximation — count {{ }} tokens
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items()}
        d["status"] = "ok" if not self.errors else "failed"
        return d


# ─────────────────────────── Image context pre-processor ───────────────────────────


def build_image_context(
    tpl: DocxTemplate, data: dict, screenshots_dir: Path | None, report: RenderReport
) -> dict:
    """Walk services[].features[].steps[] — replace screenshot filenames
    with InlineImage objects (so Jinja renders them as embedded images).

    If file missing, replace with None — template should have
    {%p if step.screenshot %}...{%p endif %} guard to skip missing images.
    """
    if not screenshots_dir or not screenshots_dir.exists():
        # Mark all screenshots as missing but still replace strings with None
        # so Jinja conditionals can skip cleanly
        for svc in data.get("services", []):
            for feat in svc.get("features", []):
                for step in feat.get("steps", []):
                    if step.get("screenshot"):
                        report.screenshots_missing += 1
                    step["screenshot_image"] = None
        return data

    # Pre-index directory contents once to avoid repeated Path.exists() per screenshot
    stem_to_path: dict[str, Path] = {}
    for entry in screenshots_dir.iterdir():
        if entry.is_file():
            stem_to_path[entry.stem] = entry

    for svc in data.get("services", []):
        for feat in svc.get("features", []):
            for step in feat.get("steps", []):
                fn = step.get("screenshot")
                if not fn:
                    step["screenshot_image"] = None
                    continue
                stem = Path(fn).stem
                resolved = stem_to_path.get(stem)
                if resolved:
                    step["screenshot_image"] = InlineImage(tpl, str(resolved), width=Mm(165))
                    report.screenshots_embedded += 1
                else:
                    step["screenshot_image"] = None
                    report.screenshots_missing += 1
    return data


def _resolve_diagram(
    tpl: DocxTemplate,
    filename: str,
    diagrams_dir: Path | None,
    report: RenderReport,
    width: Mm = Mm(165),
    max_height: Mm = Mm(220),
) -> InlineImage | None:
    """Resolve a diagram filename to InlineImage with aspect-aware sizing.

    Default: fit to page width (165mm A4 with 30mm/15mm margins).
    Constraint: if fitting to width produces height > 220mm (over A4 text area)
    OR if image is portrait → fit to height instead.
    Constraint: if aspect ratio > 3:1 (banner-style: network LTR, Gantt) → reduce
    width so height ≥ 30mm (avoid pancake-strip look that obscures content).
    """
    if not filename or not diagrams_dir or not diagrams_dir.exists():
        return None
    candidates = [diagrams_dir / filename]
    stem = Path(filename).stem
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".svg"):
        candidates.append(diagrams_dir / (stem + ext))
    resolved = next((c for c in candidates if c.exists()), None)
    if not resolved:
        return None

    # Inspect intrinsic dimensions to compute aspect-aware sizing.
    try:
        from PIL import Image  # python-docx already pulls Pillow
        with Image.open(resolved) as im:
            iw, ih = im.size
    except Exception:
        iw = ih = 0

    if iw > 0 and ih > 0:
        # mm per pixel at 96 DPI baseline
        target_w_mm = float(width)  # Mm objects support float()
        target_h_mm = target_w_mm * ih / iw
        max_h_mm = float(max_height)

        # Banner / strip detection — aspect > 3 means height shrinks below ~30mm
        # at 165mm width; reduce width so height ≥ 35mm (legible boxes).
        if iw / ih > 3.0:
            min_height_mm = 35.0
            new_w_mm = min_height_mm * iw / ih
            # Cap to page width so we don't expand beyond margins
            new_w_mm = min(new_w_mm, target_w_mm)
            return InlineImage(tpl, str(resolved), width=Mm(new_w_mm))

        # Portrait or tall image — fit to max_height instead of width
        if target_h_mm > max_h_mm:
            new_w_mm = max_h_mm * iw / ih
            return InlineImage(tpl, str(resolved), width=Mm(new_w_mm))

    return InlineImage(tpl, str(resolved), width=width)


def build_diagram_context(
    tpl: DocxTemplate, data: dict, diagrams_dir: Path | None, report: RenderReport
) -> dict:
    """Walk architecture/tkcs/tkct diagram fields — replace filenames with InlineImage.

    Convention: for each field named `*_diagram`, creates a `*_diagram_image` key.
    Templates use {%p if arch.architecture_diagram_image %} guards.
    """
    # Architecture diagrams
    arch = data.get("architecture", {})
    for field in (
        "architecture_diagram",
        "logical_diagram",
        "data_diagram",
        "deployment_diagram",
        "integration_diagram",
        "security_diagram",
    ):
        img = _resolve_diagram(tpl, arch.get(field, ""), diagrams_dir, report)
        arch[f"{field}_image"] = img

    # TKCS diagrams
    tkcs = data.get("tkcs", {})
    for field in ("architecture_diagram", "data_model_diagram"):
        img = _resolve_diagram(tpl, tkcs.get(field, ""), diagrams_dir, report)
        tkcs[f"{field}_image"] = img

    # TKCT diagrams
    tkct = data.get("tkct", {})
    for field in (
        "architecture_overview_diagram",
        "db_erd_diagram",
        "ui_layout_diagram",
        "integration_diagram",
    ):
        img = _resolve_diagram(tpl, tkct.get(field, ""), diagrams_dir, report)
        tkct[f"{field}_image"] = img

    # Module-level flow diagrams
    for module in tkct.get("modules", []):
        img = _resolve_diagram(tpl, module.get("flow_diagram", ""), diagrams_dir, report)
        module["flow_diagram_image"] = img

    # NCKT diagrams (Báo cáo Nghiên cứu khả thi — NĐ 45/2026 Đ12)
    nckt = data.get("nckt", {})
    for field in (
        "overall_architecture_diagram",
        "business_architecture_diagram",
        "logical_infra_diagram",
        "physical_infra_inner_diagram",
        "physical_infra_outer_diagram",
        "datacenter_layout_diagram",
        "network_topology_diagram",
        "integration_topology_diagram",
    ):
        img = _resolve_diagram(tpl, nckt.get(field, ""), diagrams_dir, report)
        nckt[f"{field}_image"] = img

    return data


# ─────────────────────────── Post-process ───────────────────────────


def mark_toc_dirty(docx_path: Path):
    """Mark TOC fields as dirty (w:dirty=true) without triggering Word's update dialog.

    Does NOT set updateFields=true — that causes the "Do you want to update fields?"
    prompt on every open. Fields are marked dirty so manual F9 / Ctrl+A→F9 refreshes work.
    """
    doc = Document(docx_path)
    settings = doc.settings.element
    upd = settings.find(f"{WNS_QN}updateFields")
    if upd is not None:
        upd.set(qn("w:val"), "false")  # suppress auto-update dialog
    for fc in doc.element.body.iter(f"{WNS_QN}fldChar"):
        if fc.get(qn("w:fldCharType")) == "begin":
            fc.set(qn("w:dirty"), "true")
    doc.save(docx_path)


def strip_orphan_media(docx_path: Path) -> int:
    """Remove media files no longer referenced by document.xml.

    Handles the case of forked templates carrying orphan images (e.g. TKCS
    inherited from v1.2) — after DocxTpl render clears original body,
    those media become orphan and can be safely stripped.
    """
    REL_FILE = "word/_rels/document.xml.rels"
    DOC_FILE = "word/document.xml"

    try:
        with zipfile.ZipFile(docx_path, "r") as zin:
            doc_xml = zin.read(DOC_FILE).decode("utf-8")
            rels_xml = zin.read(REL_FILE).decode("utf-8")
    except (KeyError, zipfile.BadZipFile):
        return 0

    used_rids = set(re.findall(r'r:(?:embed|link|id)="([^"]+)"', doc_xml))
    rel_pattern = re.compile(
        r'<Relationship\s+[^/]*Id="([^"]+)"[^/]*Target="(media/[^"]+|embeddings/[^"]+)"[^/]*/>',
        re.DOTALL,
    )
    orphan_rels = {}
    for m in rel_pattern.finditer(rels_xml):
        rid, target = m.group(1), m.group(2)
        if rid not in used_rids:
            orphan_rels[rid] = target
    if not orphan_rels:
        return 0

    new_rels = rels_xml
    for rid in orphan_rels:
        new_rels = re.sub(
            rf'<Relationship\s+[^/]*Id="{re.escape(rid)}"[^/]*/>',
            "",
            new_rels,
        )
    orphan_targets = {f"word/{t}" for t in orphan_rels.values()}

    tmp = docx_path.with_suffix(".tmp.docx")
    removed = 0
    with zipfile.ZipFile(docx_path, "r") as zin:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename in orphan_targets:
                    removed += 1
                    continue
                if item.filename == REL_FILE:
                    zout.writestr(item, new_rels.encode("utf-8"))
                    continue
                zout.writestr(item, zin.read(item.filename))
    shutil.move(str(tmp), str(docx_path))
    return removed


# ─────────────────────────── Combined post-processing ───────────────────────────


def _post_process_docx(docx_path: Path) -> tuple[int, list[str]]:
    """Single-pass post-processing: TOC dirty + orphan media strip + residual check.

    Replaces three separate I/O operations (mark_toc_dirty, strip_orphan_media,
    validation Document load) with one ZIP read + one conditional ZIP write.

    Returns:
        (orphans_removed, residual_jinja_markers)
    """
    REL_FILE = "word/_rels/document.xml.rels"
    DOC_FILE = "word/document.xml"
    SET_FILE = "word/settings.xml"

    try:
        with zipfile.ZipFile(docx_path, "r") as zin:
            all_files = set(zin.namelist())
            doc_raw = zin.read(DOC_FILE) if DOC_FILE in all_files else b""
            set_raw = zin.read(SET_FILE) if SET_FILE in all_files else b""
            rels_raw = zin.read(REL_FILE).decode("utf-8") if REL_FILE in all_files else ""
    except (KeyError, zipfile.BadZipFile):
        return 0, []

    # ── 1. Detect orphan media ──
    orphan_rels: dict[str, str] = {}
    new_rels = rels_raw
    if rels_raw and doc_raw:
        used_rids = set(re.findall(r'r:(?:embed|link|id)="([^"]+)"', doc_raw.decode("utf-8")))
        rel_pat = re.compile(
            r'<Relationship\s+[^/]*Id="([^"]+)"[^/]*Target="(media/[^"]+|embeddings/[^"]+)"[^/]*/>',
            re.DOTALL,
        )
        for m in rel_pat.finditer(rels_raw):
            rid, target = m.group(1), m.group(2)
            if rid not in used_rids:
                orphan_rels[rid] = target
        for rid in orphan_rels:
            new_rels = re.sub(
                rf'<Relationship\s+[^/]*Id="{re.escape(rid)}"[^/]*/>',
                "",
                new_rels,
            )
    orphan_targets = {f"word/{t}" for t in orphan_rels.values()}

    # ── 2. Suppress auto-update dialog: ensure updateFields=false in settings.xml ──
    # Word shows "Do you want to update fields?" on open when updateFields=true.
    # We suppress that dialog by keeping updateFields=false (or absent).
    # Fields are still marked w:dirty="true" below so manual F9/Ctrl+A→F9 refreshes work.
    new_set_raw = set_raw
    if set_raw and b"w:updateFields" in set_raw:
        # If template had updateFields=true, neutralise it
        if b'w:val="true"' in set_raw:
            new_set_raw = re.sub(
                rb'(<w:updateFields\b[^/]*/?>)',
                rb'<w:updateFields w:val="false"/>',
                set_raw,
            )

    # ── 2.5. Convert floating anchor images → inline ──
    # Diagram InlineImages occasionally get wrapped in <wp:anchor> (floating)
    # instead of <wp:inline>, causing Word to overlay caption text or shrink the
    # image to a thin strip. Force-inline so images flow naturally with text.
    anchor_to_inline_pat = re.compile(
        rb"<wp:anchor\b[^>]*>(.*?)</wp:anchor>",
        re.DOTALL,
    )
    drop_pat = re.compile(
        rb"<wp:(simplePos|positionH|positionV|wrapNone|wrapSquare|wrapTopAndBottom|wrapTight|wrapThrough|wrapPolygon)\b[^>]*(?:/>|>.*?</wp:\1>)",
        re.DOTALL,
    )

    def _anchor_to_inline(m: re.Match) -> bytes:
        body = drop_pat.sub(b"", m.group(1))
        return b"<wp:inline distT=\"0\" distB=\"0\" distL=\"0\" distR=\"0\">" + body + b"</wp:inline>"

    if doc_raw and b"<wp:anchor" in doc_raw:
        doc_raw_fixed = anchor_to_inline_pat.sub(_anchor_to_inline, doc_raw)
    else:
        doc_raw_fixed = doc_raw

    # ── 3. Mark fldChar dirty + collect residual Jinja markers in document.xml ──
    new_doc_raw = doc_raw_fixed
    residuals: list[str] = []
    if doc_raw_fixed:
        doc_text = doc_raw_fixed.decode("utf-8")
        for marker in ("{{", "}}", "{%", "%}"):
            if marker in doc_text:
                residuals.append(marker)
        if b'w:fldCharType="begin"' in doc_raw_fixed:
            # Add w:dirty="true" to every <w:fldChar ... w:fldCharType="begin" ...> element
            new_doc_raw = re.sub(
                rb'(<w:fldChar\b[^>]*?w:fldCharType="begin"[^>]*?)(/?>)',
                rb'\1 w:dirty="true"\2',
                doc_raw_fixed,
            )
            # Collapse accidental duplicates if attribute was already present
            new_doc_raw = re.sub(
                rb'(w:dirty="true"\s+)+w:dirty="true"',
                rb'w:dirty="true"',
                new_doc_raw,
            )

    # ── 4. Rebuild ZIP only if changes are needed ──
    needs_rebuild = bool(orphan_rels) or new_set_raw != set_raw or new_doc_raw != doc_raw
    if not needs_rebuild:
        return 0, residuals

    tmp = docx_path.with_suffix(".tmp.docx")
    try:
        with zipfile.ZipFile(docx_path, "r") as zin:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    fn = item.filename
                    if fn in orphan_targets:
                        continue  # drop orphan media
                    if fn == REL_FILE and orphan_rels:
                        zout.writestr(item, new_rels.encode("utf-8"))
                    elif fn == SET_FILE and new_set_raw != set_raw:
                        zout.writestr(item, new_set_raw)
                    elif fn == DOC_FILE and new_doc_raw != doc_raw:
                        zout.writestr(item, new_doc_raw)
                    else:
                        zout.writestr(item, zin.read(fn))
        shutil.move(str(tmp), str(docx_path))
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise

    return len(orphan_rels), residuals


# ─────────────────────────── Main render ───────────────────────────


def render(
    template_path: Path,
    data_path: Path,
    output_path: Path,
    screenshots_dir: Path | None = None,
    diagrams_dir: Path | None = None,
) -> RenderReport:
    report = RenderReport(template=str(template_path), output=str(output_path))

    if not template_path.exists():
        report.errors.append(f"Template not found: {template_path}")
        return report

    # Load data
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception as e:
        report.errors.append(f"Cannot parse data: {e}")
        return report

    # Add `meta.today` fallback if missing
    data.setdefault("meta", {}).setdefault("today", "")

    # Ensure all top-level sections have defaults so templates don't fail on
    # missing keys (backward compat: older content-data.json may lack new sections)
    data.setdefault("overview", {})
    data.setdefault("architecture", {})
    data.setdefault("tkcs", {})
    data.setdefault("tkct", {})
    data.setdefault("nckt", {})
    data.setdefault("services", [])
    data.setdefault("troubleshooting", [])

    # Pre-compute `all_features` flat list (features with service_name embedded)
    # — simplifies templates by avoiding nested {%p for service %} + {%tr for feat %}
    # which docxtpl/Jinja cannot parse reliably.
    all_features = []
    for svc in data.get("services", []):
        svc_name = svc.get("display_name", "")
        for feat in svc.get("features", []):
            flat = dict(feat)
            flat["service_name"] = svc_name
            all_features.append(flat)
    data["all_features"] = all_features

    # Open template
    try:
        tpl = DocxTemplate(str(template_path))
    except Exception as e:
        report.errors.append(f"Cannot open template: {e}")
        return report

    # Pre-process screenshots into InlineImage objects
    data = build_image_context(tpl, data, screenshots_dir, report)

    # Pre-process diagram images into InlineImage objects
    data = build_diagram_context(tpl, data, diagrams_dir, report)

    # Render
    try:
        tpl.render(data)
    except Exception as e:
        report.errors.append(f"Render failed: {e}")
        return report

    # Save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        tpl.save(str(output_path))
    except Exception as e:
        report.errors.append(f"Save failed: {e}")
        return report

    # Post-process: TOC dirty + orphan strip + residual check (single ZIP pass)
    try:
        orphans, residuals = _post_process_docx(output_path)
        if orphans > 0:
            report.warnings.append(f"Stripped {orphans} orphan media files")
        if residuals:
            report.warnings.append(f"Residual Jinja markers in output: {residuals}")
    except Exception as e:
        report.warnings.append(f"Post-processing failed: {e}")

    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--screenshots-dir", default=None)
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    report = render(
        Path(args.template),
        Path(args.data),
        Path(args.output),
        Path(args.screenshots_dir) if args.screenshots_dir else None,
    )

    d = report.to_dict()
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(
            json.dumps(d, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(f"Template: {report.template}")
    print(f"Output:   {report.output}")
    print(
        f"Screenshots: {report.screenshots_embedded} embedded, {report.screenshots_missing} missing"
    )
    if report.warnings:
        print(f"Warnings: {len(report.warnings)}")
        for w in report.warnings:
            print(f"  - {w}")
    if report.errors:
        print(f"ERRORS: {len(report.errors)}")
        for e in report.errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
