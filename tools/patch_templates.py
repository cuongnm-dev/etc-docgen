#!/usr/bin/env python3
"""
patch_templates.py — Standardize docx template styles per NĐ 30/2020.

Fixes applied to ALL templates:
  1. docDefaults → Times New Roman 13pt, line spacing 1.5, justify
  2. Normal style → Times New Roman 13pt, 1.5 spacing, justify
  3. Heading 1 → Times New Roman 13pt Bold, spacing before 6pt, after 3pt
  4. Heading 2 → Times New Roman 13pt Bold, spacing before 6pt, after 3pt
  5. Heading 3 → Times New Roman 13pt Normal (not bold), spacing before 3pt
  6. Default Paragraph Font → Times New Roman 13pt

Requirements per NĐ 30/2020:
  - Font: Times New Roman 13pt
  - Line spacing: 1.5
  - Margins: Top/Bottom 20mm, Left 30mm, Right 15mm (already correct in templates)
  - Justification: both (justify)
  - Heading levels: 1=Bold, 2=Bold, 3=Normal weight
"""

import re
import shutil
import zipfile
from pathlib import Path

# ── Constants (OOXML half-points and twips) ──────────────────────────────────
FONT_NAME = "Times New Roman"
FONT_SIZE_HP = "26"       # 13pt × 2 half-points
FONT_SIZE_H1_HP = "26"   # NĐ 30/2020: tất cả 13pt kể cả heading
LINE_SPACING_TWIPS = "360"  # 1.5 line spacing
SPACE_BEFORE_H1 = "120"  # 6pt before heading (1pt = 20 twips)
SPACE_AFTER_H1 = "60"    # 3pt after heading
SPACE_BEFORE_H2 = "120"
SPACE_AFTER_H2 = "60"
SPACE_BEFORE_H3 = "60"
SPACE_AFTER_H3 = "0"

DOC_DEFAULTS_REPLACEMENT = f"""<w:docDefaults>
    <w:rPrDefault>
      <w:rPr>
        <w:rFonts w:ascii="{FONT_NAME}" w:hAnsi="{FONT_NAME}" w:cs="{FONT_NAME}" w:eastAsia="{FONT_NAME}"/>
        <w:sz w:val="{FONT_SIZE_HP}"/>
        <w:szCs w:val="{FONT_SIZE_HP}"/>
        <w:lang w:val="vi-VN" w:eastAsia="vi-VN" w:bidi="ar-SA"/>
      </w:rPr>
    </w:rPrDefault>
    <w:pPrDefault>
      <w:pPr>
        <w:spacing w:line="{LINE_SPACING_TWIPS}" w:lineRule="auto" w:after="0"/>
        <w:jc w:val="both"/>
      </w:pPr>
    </w:pPrDefault>
  </w:docDefaults>"""


def build_rpr_block(bold: bool = False, size_hp: str = FONT_SIZE_HP) -> str:
    """Build <w:rPr> block with font + size + optional bold."""
    bold_tag = "<w:b/><w:bCs/>" if bold else ""
    return (
        f"<w:rPr>"
        f"<w:rFonts w:ascii=\"{FONT_NAME}\" w:hAnsi=\"{FONT_NAME}\" w:cs=\"{FONT_NAME}\" w:eastAsia=\"{FONT_NAME}\"/>"
        f"{bold_tag}"
        f"<w:sz w:val=\"{size_hp}\"/>"
        f"<w:szCs w:val=\"{size_hp}\"/>"
        f"</w:rPr>"
    )


def build_ppr_spacing(before: str, after: str) -> str:
    return (
        f"<w:spacing w:before=\"{before}\" w:after=\"{after}\" "
        f"w:line=\"{LINE_SPACING_TWIPS}\" w:lineRule=\"auto\"/>"
    )


def replace_style_block(styles_xml: str, style_id: str, new_rpr: str, new_spacing: str | None = None) -> str:
    """Replace or inject <w:rPr> (and optionally spacing) inside a named style block."""
    # Match the full style element
    pattern = re.compile(
        rf'(<w:style\b[^>]*w:styleId="{re.escape(style_id)}"[^>]*>)(.*?)(</w:style>)',
        re.DOTALL,
    )
    m = pattern.search(styles_xml)
    if not m:
        return styles_xml

    style_body = m.group(2)

    # Replace or inject w:rPr
    if "<w:rPr>" in style_body:
        style_body = re.sub(r"<w:rPr>.*?</w:rPr>", new_rpr, style_body, flags=re.DOTALL)
    else:
        # Inject before </w:pPr> if it exists, else at end
        if "</w:pPr>" in style_body:
            style_body = style_body.replace("</w:pPr>", f"</w:pPr>{new_rpr}", 1)
        else:
            style_body += new_rpr

    # Replace or inject spacing inside w:pPr if requested
    if new_spacing:
        if "<w:pPr>" in style_body:
            # Remove existing spacing tag
            style_body = re.sub(r"<w:spacing\b[^/]*/?>", "", style_body)
            # Inject spacing at start of pPr content
            style_body = re.sub(r"(<w:pPr>)", rf"\1{new_spacing}", style_body)
        else:
            style_body = f"<w:pPr>{new_spacing}</w:pPr>" + style_body

    replaced = m.group(1) + style_body + m.group(3)
    return styles_xml[: m.start()] + replaced + styles_xml[m.end() :]


def patch_styles_xml(styles_xml: str) -> str:
    """Apply all style fixes to styles.xml content."""

    # ── 1. Replace docDefaults ──────────────────────────────────────────────
    if "<w:docDefaults>" in styles_xml:
        styles_xml = re.sub(
            r"<w:docDefaults>.*?</w:docDefaults>",
            DOC_DEFAULTS_REPLACEMENT,
            styles_xml,
            flags=re.DOTALL,
        )
    else:
        # Insert before first <w:style
        styles_xml = styles_xml.replace(
            "<w:style ",
            DOC_DEFAULTS_REPLACEMENT + "\n  <w:style ",
            1,
        )

    # ── 2. Normal style ──────────────────────────────────────────────────────
    for style_id in ("Normal", "DefaultParagraphFont"):
        styles_xml = replace_style_block(
            styles_xml, style_id,
            build_rpr_block(bold=False),
            new_spacing=f"<w:spacing w:line=\"{LINE_SPACING_TWIPS}\" w:lineRule=\"auto\" w:after=\"0\"/>"
            + "<w:jc w:val=\"both\"/>",
        )

    # ── 3. Heading 1 ─────────────────────────────────────────────────────────
    for style_id in ("Heading1", "1"):
        styles_xml = replace_style_block(
            styles_xml, style_id,
            build_rpr_block(bold=True, size_hp=FONT_SIZE_H1_HP),
            new_spacing=build_ppr_spacing(SPACE_BEFORE_H1, SPACE_AFTER_H1),
        )

    # ── 4. Heading 2 ─────────────────────────────────────────────────────────
    for style_id in ("Heading2", "2"):
        styles_xml = replace_style_block(
            styles_xml, style_id,
            build_rpr_block(bold=True),
            new_spacing=build_ppr_spacing(SPACE_BEFORE_H2, SPACE_AFTER_H2),
        )

    # ── 5. Heading 3 ─────────────────────────────────────────────────────────
    for style_id in ("Heading3", "3"):
        styles_xml = replace_style_block(
            styles_xml, style_id,
            build_rpr_block(bold=False),  # Level 3 = Normal weight per NĐ 30/2020
            new_spacing=build_ppr_spacing(SPACE_BEFORE_H3, SPACE_AFTER_H3),
        )

    # ── 6. ETC custom styles ─────────────────────────────────────────────────
    # ETCContent — main body content: fix line spacing to 1.5
    styles_xml = replace_style_block(
        styles_xml, "ETCContent",
        build_rpr_block(bold=False),
        new_spacing=f"<w:spacing w:line=\"{LINE_SPACING_TWIPS}\" w:lineRule=\"auto\" w:after=\"0\"/><w:jc w:val=\"both\"/>",
    )

    # HeadingLv1 — was Tahoma 10pt → Times New Roman 13pt Bold
    styles_xml = replace_style_block(
        styles_xml, "HeadingLv1",
        build_rpr_block(bold=True),
        new_spacing=build_ppr_spacing(SPACE_BEFORE_H1, SPACE_AFTER_H1),
    )

    # AHEADING1 — was 14pt → 13pt bold
    styles_xml = replace_style_block(
        styles_xml, "AHEADING1",
        build_rpr_block(bold=True),
        new_spacing=build_ppr_spacing(SPACE_BEFORE_H1, SPACE_AFTER_H1),
    )

    # AHeading2 — fix spacing 288 → 360
    styles_xml = replace_style_block(
        styles_xml, "AHeading2",
        build_rpr_block(bold=True),
        new_spacing=build_ppr_spacing(SPACE_BEFORE_H2, SPACE_AFTER_H2),
    )

    # AHeading3 — was bold → NOT bold (Level 3 = normal weight per NĐ 30/2020); fix spacing
    styles_xml = replace_style_block(
        styles_xml, "AHeading3",
        build_rpr_block(bold=False),  # Level 3 not bold
        new_spacing=build_ppr_spacing(SPACE_BEFORE_H3, SPACE_AFTER_H3),
    )

    # NormalFSC, NormalT — were Tahoma 10pt → Times New Roman 13pt
    for style_id in ("NormalFSC", "NormalT"):
        styles_xml = replace_style_block(
            styles_xml, style_id,
            build_rpr_block(bold=False),
            new_spacing=f"<w:spacing w:line=\"{LINE_SPACING_TWIPS}\" w:lineRule=\"auto\" w:after=\"0\"/><w:jc w:val=\"both\"/>",
        )

    return styles_xml


def patch_template(src: Path, dst: Path | None = None) -> Path:
    """Patch a single .docx template. Writes to dst (or overwrites src if dst=None)."""
    out = dst or src
    tmp = src.with_suffix(".patching.docx")

    with zipfile.ZipFile(src, "r") as zin:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "word/styles.xml":
                    original = data.decode("utf-8")
                    patched = patch_styles_xml(original)
                    data = patched.encode("utf-8")
                zout.writestr(item, data)

    shutil.move(str(tmp), str(out))
    return out


def main():
    import argparse, sys

    ap = argparse.ArgumentParser(description="Patch docx templates to NĐ 30/2020 style standards")
    ap.add_argument("templates", nargs="*", help="Template paths (defaults to all in assets/templates/)")
    ap.add_argument("--dry-run", action="store_true", help="Show what would be changed, don't write")
    args = ap.parse_args()

    root = Path(__file__).parent.parent / "src" / "etc_platform" / "assets" / "templates"
    targets = [Path(p) for p in args.templates] if args.templates else list(root.glob("*.docx"))

    if not targets:
        print("No templates found.", file=sys.stderr)
        sys.exit(1)

    for tpl in targets:
        if not tpl.exists():
            print(f"  SKIP (not found): {tpl}")
            continue
        if args.dry_run:
            with zipfile.ZipFile(tpl) as z:
                xml = z.read("word/styles.xml").decode("utf-8")
            patched = patch_styles_xml(xml)
            changed = xml != patched
            print(f"  {'WOULD PATCH' if changed else 'no change'}: {tpl.name}")
        else:
            patch_template(tpl)
            print(f"  PATCHED: {tpl}")

    if not args.dry_run:
        print(f"\nDone. {len(targets)} template(s) updated.")


if __name__ == "__main__":
    main()
