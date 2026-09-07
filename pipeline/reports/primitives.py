"""
Reusable ReportLab primitives shared by all modality reports.

These are the visual building blocks that templates compose:
  - section_header(text)         → teal section bar
  - kv_table(rows)               → two-column key/value table
  - results_table(rows, columns) → color-coded clinical results
  - interpretation_block(rows)   → alternating-bg labeled paragraphs
  - assessment_plan_box(text)    → bordered free-text box

All visual constants come from brand.py — these primitives never
hardcode colors or geometry.
"""

from reportlab.platypus import Table, TableStyle, Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

from .brand import (
    PAGE_W, MARGIN,
    NAVY, TEAL, LIGHTGRAY, BORDER, WHITE, DARKGRAY,
    STATUS_COLORS,
)


# ── Paragraph styles ───────────────────────────────────────────────────────
BODY = ParagraphStyle(
    'body', fontName='Helvetica', fontSize=9,
    textColor=DARKGRAY, leading=11,
)
BODY_BOLD = ParagraphStyle(
    'body_bold', fontName='Helvetica-Bold', fontSize=9,
    textColor=NAVY, leading=11,
)
INTERP_TXT = ParagraphStyle(
    'interp', fontName='Helvetica', fontSize=8.5,
    textColor=DARKGRAY, leading=11,
)
SECTION_HDR = ParagraphStyle(
    'section', fontName='Helvetica-Bold', fontSize=10,
    textColor=WHITE, alignment=TA_LEFT, leading=12,
)
CENTERED = ParagraphStyle(
    'centered', fontName='Helvetica', fontSize=9,
    textColor=DARKGRAY, alignment=TA_CENTER, leading=11,
)
TABLE_HDR_LEFT = ParagraphStyle(
    'th_left', fontName='Helvetica-Bold', fontSize=9,
    textColor=WHITE, alignment=TA_LEFT,
)
TABLE_HDR_CENTER = ParagraphStyle(
    'th_center', fontName='Helvetica-Bold', fontSize=9,
    textColor=WHITE, alignment=TA_CENTER,
)


def _content_width():
    return PAGE_W - 2 * MARGIN


# ── Section header bar ─────────────────────────────────────────────────────
def section_header(text: str) -> Table:
    """Teal full-width bar with white bold section title."""
    t = Table([[Paragraph(text, SECTION_HDR)]], colWidths=[_content_width()])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), TEAL),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    return t


# ── Two-column key/value table ─────────────────────────────────────────────
def kv_table(rows: list[tuple[str, str]],
             col_ratio: tuple[float, float] = (0.30, 0.70)) -> Table:
    """Two-column table with bold navy keys and gray-zebra row backgrounds."""
    tw = _content_width()
    data = [[Paragraph(k, BODY_BOLD), Paragraph(v, BODY)] for k, v in rows]
    t = Table(data, colWidths=[tw * col_ratio[0], tw * col_ratio[1]])
    t.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.25, BORDER),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [WHITE, LIGHTGRAY]),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    return t


# ── Color-coded clinical results table ────────────────────────────────────
def results_table(findings,
                  param_label: str = 'Parameter',
                  od_label: str = 'OD',
                  os_label: str = 'OS',
                  col_widths: tuple = (0.36, 0.18, 0.13, 0.18, 0.13)) -> Table:
    """
    Render a list of Finding objects as a color-coded results table.

    Columns: Parameter | OD value | OD status | OS value | OS status
    Status cells are tinted green/yellow/red per WNL/BRDL/ABNL.

    col_widths is a 5-tuple of fractions (must sum to 1.0). Generalized
    so future modalities (OCT, VF) can adjust column proportions without
    rewriting this function.
    """
    header = [
        Paragraph(param_label, TABLE_HDR_LEFT),
        Paragraph(od_label, TABLE_HDR_CENTER),
        Paragraph('Status', TABLE_HDR_CENTER),
        Paragraph(os_label, TABLE_HDR_CENTER),
        Paragraph('Status', TABLE_HDR_CENTER),
    ]

    data = [header]
    style_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), NAVY),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.25, BORDER),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]

    for i, f in enumerate(findings, start=1):
        data.append([
            Paragraph(f.parameter, BODY_BOLD),
            Paragraph(f.od_value, CENTERED),
            Paragraph(f.od_status, CENTERED),
            Paragraph(f.os_value, CENTERED),
            Paragraph(f.os_status, CENTERED),
        ])
        style_cmds.append(
            ('BACKGROUND', (2, i), (2, i), STATUS_COLORS[f.od_status])
        )
        style_cmds.append(
            ('BACKGROUND', (4, i), (4, i), STATUS_COLORS[f.os_status])
        )

    tw = _content_width()
    t = Table(data, colWidths=[tw * w for w in col_widths])
    t.setStyle(TableStyle(style_cmds))
    return t


# ── Interpretation block ───────────────────────────────────────────────────
def interpretation_block(sections) -> list[Table]:
    """
    Render a list of InterpretationSection objects as labeled rows
    with alternating gray/white backgrounds.

    Returns a list of flowables — append each to the story.
    """
    tw = _content_width()
    out = []
    for i, sec in enumerate(sections):
        bg = LIGHTGRAY if i % 2 == 0 else WHITE
        row = Table(
            [[Paragraph(sec.label, BODY_BOLD), Paragraph(sec.text, INTERP_TXT)]],
            colWidths=[tw * 0.20, tw * 0.80],
        )
        row.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), bg),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('GRID', (0, 0), (-1, -1), 0.25, BORDER),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ]))
        out.append(row)
    return out


# ── Assessment / Plan box ─────────────────────────────────────────────────
def assessment_plan_box(text: str) -> Table:
    """Navy-bordered free-text box for the A&P narrative."""
    t = Table(
        [[Paragraph(text or '', INTERP_TXT)]],
        colWidths=[_content_width()],
    )
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), WHITE),
        ('BOX', (0, 0), (-1, -1), 0.75, NAVY),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 22),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    return t
