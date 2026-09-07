"""
Template-driven PDF renderer.

Takes a ReportContext + a YAML template path and produces a PDF.
The template defines section order and types; the context provides data.
The renderer is modality-agnostic — it dispatches section types to the
matching primitive in primitives.py.

To add a new section type:
  1. Add a primitive in primitives.py
  2. Add a case in _render_section() below
  3. Reference it from any template's `sections:` list
"""

from io import BytesIO
from pathlib import Path

import yaml
from reportlab.platypus import SimpleDocTemplate, Spacer

from .brand import MARGIN, TOP_MARGIN, BOTTOM_MARGIN, make_header_footer
from .schemas import ReportContext
from .primitives import (
    section_header, kv_table, results_table,
    interpretation_block, assessment_plan_box,
)
from reportlab.lib.pagesizes import letter


SECTION_GAP = 4  # vertical space between sections (matches original)


def _render_section(section: dict, context: ReportContext):
    """
    Dispatch one template section to the appropriate primitive.

    Returns a list of flowables to append to the story.
    """
    sec_type = section['type']
    header_text = section.get('header', '')
    source = section.get('source')

    flowables = [section_header(header_text)] if header_text else []

    if sec_type == 'kv_table':
        rows = getattr(context, source)
        col_ratio = tuple(section.get('col_ratio', (0.30, 0.70)))
        flowables.append(kv_table(rows, col_ratio=col_ratio))

    elif sec_type == 'results_table':
        findings = getattr(context, source)
        col_widths = tuple(section.get('col_widths', (0.36, 0.18, 0.13, 0.18, 0.13)))
        flowables.append(results_table(
            findings,
            param_label=section.get('param_label', 'Parameter'),
            od_label=section.get('od_label', 'OD'),
            os_label=section.get('os_label', 'OS'),
            col_widths=col_widths,
        ))

    elif sec_type == 'interpretation':
        sections = getattr(context, source)
        flowables.extend(interpretation_block(sections))

    elif sec_type == 'assessment_plan':
        text = getattr(context, source)
        flowables.append(assessment_plan_box(text))

    else:
        raise ValueError(f'Unknown section type: {sec_type}')

    return flowables


def render(context: ReportContext,
           template_path: str | Path,
           output_path: str | Path | None = None) -> bytes:
    """
    Render a ReportContext to PDF using the given YAML template.

    If output_path is provided, the PDF is also written to disk.
    Always returns the PDF bytes.
    """
    template_path = Path(template_path)
    with open(template_path) as f:
        template = yaml.safe_load(f)

    title = template.get('title', context.modality.upper() + ' REPORT')
    subtitle = template.get('subtitle', '')

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=TOP_MARGIN, bottomMargin=BOTTOM_MARGIN,
    )

    story = []
    for i, section in enumerate(template['sections']):
        if i > 0:
            story.append(Spacer(1, SECTION_GAP))
        story.extend(_render_section(section, context))

    draw = make_header_footer(title=title, subtitle=subtitle)
    doc.build(story, onFirstPage=draw, onLaterPages=draw)

    pdf_bytes = buf.getvalue()

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(pdf_bytes)

    return pdf_bytes
