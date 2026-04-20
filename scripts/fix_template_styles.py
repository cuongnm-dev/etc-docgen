#!/usr/bin/env python3
"""
Fix HDSD template styles and margins to comply with Vietnamese document standards.

Reference: NĐ 30/2020/NĐ-CP (Văn bản hành chính)
- Font: Times New Roman 13pt body, 14pt heading 1
- Alignment: Justify for body text
- Margins: Top 20mm, Bottom 20mm, Left 30mm, Right 15mm
- Line spacing: 1.3-1.5
"""

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Mm, Pt

TEMPLATE = "src/etc_docgen/assets/templates/huong-dan-su-dung.docx"

doc = Document(TEMPLATE)

# ────────────── 1. Fix page margins (NĐ 30/2020) ──────────────
for sec in doc.sections:
    sec.top_margin = Mm(20)
    sec.bottom_margin = Mm(20)
    sec.left_margin = Mm(30)
    sec.right_margin = Mm(15)
print("✓ Margins: top=20mm bot=20mm left=30mm right=15mm")

# ────────────── 2. Fix ETC_Content style ──────────────
style = doc.styles["ETC_Content"]
style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
style.font.size = Pt(13)
style.font.name = "Times New Roman"
# line_spacing 1.3 already set, keep it
print("✓ ETC_Content: JUSTIFY, 13pt, Times New Roman")

# ────────────── 3. Fix heading styles ──────────────
# A_HEADING 1: Chapter headings (I. TỔNG QUAN, II. NỘI DUNG)
h1 = doc.styles["A_HEADING 1"]
h1.font.size = Pt(14)
h1.font.name = "Times New Roman"
h1.font.bold = True
h1.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
print("✓ A_HEADING 1: 14pt, bold, JUSTIFY")

# A_Heading 2: Section headings (1.1 Mục đích, 2.3 Hướng dẫn)
h2 = doc.styles["A_Heading 2"]
h2.font.size = Pt(13)
h2.font.name = "Times New Roman"
h2.font.bold = True
h2.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
print("✓ A_Heading 2: 13pt, bold, JUSTIFY")

# A_Heading 3: Sub-section (2.1.1 Tổng quan, service names)
h3 = doc.styles["A_Heading 3"]
h3.font.size = Pt(13)
h3.font.name = "Times New Roman"
h3.font.bold = True
h3.font.italic = True
h3.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
print("✓ A_Heading 3: 13pt, bold+italic, JUSTIFY")

# A_Heading 4: Feature names (3.2.3 Xem chi tiết văn bản)
h4 = doc.styles["A_Heading 4"]
h4.font.size = Pt(13)
h4.font.name = "Times New Roman"
h4.font.bold = True
h4.font.italic = True
h4.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
print("✓ A_Heading 4: 13pt, bold+italic, JUSTIFY")

# A_Normal: if used as body text elsewhere
a_normal = doc.styles["A_Normal"]
a_normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
a_normal.font.size = Pt(13)
a_normal.font.name = "Times New Roman"
print("✓ A_Normal: 13pt, JUSTIFY")

# ETC-Dash: used for dash-prefixed items
etc_dash = doc.styles["ETC-Dash"]
etc_dash.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
etc_dash.font.size = Pt(13)
etc_dash.font.name = "Times New Roman"
print("✓ ETC-Dash: 13pt, JUSTIFY")

# ────────────── 4. Save ──────────────
doc.save(TEMPLATE)
print()
print(f"✓ Saved: {TEMPLATE}")

# ────────────── 5. Verify ──────────────
doc2 = Document(TEMPLATE)
style2 = doc2.styles["ETC_Content"]
assert style2.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.JUSTIFY
assert style2.font.size == Pt(13)
sec2 = doc2.sections[0]
assert sec2.left_margin == Mm(30)
assert sec2.right_margin == Mm(15)
print("✓ Verification passed")
