"""
307 Vision practice branding.

All practice-specific visual identity lives here:
  - Color palette
  - Page header (navy bar with practice name and providers)
  - Page footer (Casper, WY confidentiality line)
  - Page geometry (margins, sizes)

To rebrand for a different practice, edit only this file.
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch

# ── Page geometry ──────────────────────────────────────────────────────────
PAGE_W, PAGE_H = letter
MARGIN = 0.55 * inch
TOP_MARGIN = 0.95 * inch
BOTTOM_MARGIN = 0.55 * inch

# ── Color palette ──────────────────────────────────────────────────────────
NAVY      = colors.HexColor('#1B3A6B')
TEAL      = colors.HexColor('#2E6DA4')
LTBLUE    = colors.HexColor('#D6E8F7')
LIGHTGRAY = colors.HexColor('#F2F4F6')
BORDER    = colors.HexColor('#CCCCCC')
WHITE     = colors.white
DARKGRAY  = colors.HexColor('#333333')

GREEN_BG  = colors.HexColor('#C8E6C9')   # WNL
YELLOW_BG = colors.HexColor('#FFF176')   # BRDL
RED_BG    = colors.HexColor('#FFCDD2')   # ABNL

STATUS_COLORS = {
    'WNL':  GREEN_BG,
    'BRDL': YELLOW_BG,
    'ABNL': RED_BG,
}

# ── Practice identity ──────────────────────────────────────────────────────
PRACTICE_NAME = '307 VISION'
PRACTICE_PROVIDERS = 'Ryan Larsen, O.D.  |  Jerry Larsen, O.D.  |  Jason B. Whitman, O.D.'
PRACTICE_LOCATION = 'Casper, WY'
FOOTER_TEXT = f'307 Vision  •  {PRACTICE_LOCATION}  •  Confidential clinical document'


def make_header_footer(title: str, subtitle: str):
    """
    Build a canvas-level header/footer drawer for a given report title.

    Returns a function suitable for SimpleDocTemplate's
    onFirstPage / onLaterPages callbacks.
    """
    def draw(c, doc):
        c.saveState()

        # Navy header bar
        c.setFillColor(NAVY)
        c.rect(0, PAGE_H - 0.72*inch, PAGE_W, 0.72*inch, fill=1, stroke=0)

        # Practice name (left)
        c.setFillColor(WHITE)
        c.setFont('Helvetica-Bold', 15)
        c.drawString(MARGIN, PAGE_H - 0.31*inch, PRACTICE_NAME)
        c.setFont('Helvetica', 8)
        c.drawString(MARGIN, PAGE_H - 0.46*inch, PRACTICE_PROVIDERS)

        # Report title (right)
        c.setFont('Helvetica-Bold', 11)
        c.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.31*inch, title)
        c.setFont('Helvetica', 8)
        c.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.46*inch, subtitle)

        # Footer
        c.setFillColor(colors.HexColor('#888888'))
        c.setFont('Helvetica', 7)
        c.drawCentredString(PAGE_W / 2.0, 0.35 * inch, FOOTER_TEXT)

        c.restoreState()

    return draw
