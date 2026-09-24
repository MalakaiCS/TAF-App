"""
Barcode labels for stock items.

A scanning gun is worth nothing until the things it scans carry a code, and
nothing in a filter shop does by default. This writes a sheet of labels to
stick on the racking and the rolls.

Avery L7160 by default - 21 to an A4 sheet, three across and seven down, the
common office label. `start_at` skips labels already peeled off a part-used
sheet, because otherwise the first print of the day wastes most of one.

Every label carries the code twice: as bars for the gun and as text for the
person, because a smudged label still has to be readable by someone standing
in front of the rack.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

MM = 72.0 / 25.4          # points per millimetre


class Layout:
    """A label sheet, in millimetres, as the box it came in describes it."""

    def __init__(self, name: str, page: str, across: int, down: int,
                 label_w: float, label_h: float,
                 left: float, top: float, pitch_x: float, pitch_y: float):
        self.name = name
        self.page = page
        self.across, self.down = across, down
        self.label_w, self.label_h = label_w * MM, label_h * MM
        self.left, self.top = left * MM, top * MM
        self.pitch_x, self.pitch_y = pitch_x * MM, pitch_y * MM

    @property
    def per_sheet(self) -> int:
        return self.across * self.down


L7160 = Layout("Avery L7160 (21 per A4 sheet)", "A4", 3, 7,
               63.5, 38.1, 7.21, 15.15, 66.0, 38.1)
L7163 = Layout("Avery L7163 (14 per A4 sheet)", "A4", 2, 7,
               99.1, 38.1, 5.0, 15.15, 101.6, 38.1)

LAYOUTS = {"L7160": L7160, "L7163": L7163}

# The narrow-bar width, in points. Measured by printing these and decoding
# them back: below 0.75pt a scanner in someone's hand starts missing them.
# See pdf_generator.draw_order_barcode, which is where the numbers came from.
NARROW_IDEAL = 1.0
NARROW_MIN = 0.75
BAR_HEIGHT = 30.0


def label_code(item: Dict[str, Any]) -> str:
    """The code a label carries. A stock item's SKU is its barcode."""
    return (item.get("sku") or "").strip().upper()


def _fit(text: str, font: str, size: float, max_w: float) -> str:
    """Shorten to fit, with an ellipsis, so nothing runs off the label."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    if stringWidth(text, font, size) <= max_w:
        return text
    while text and stringWidth(text + "...", font, size) > max_w:
        text = text[:-1]
    return text + "..."


def _fit_barcode(code: str, max_w: float):
    """The widest bars that fit `max_w`, and the width used.

    Wider bars read from further away and survive a scuffed label, so this
    takes the most it can rather than a fixed size. ReportLab's width is not
    proportional to the bar width — there is a fixed quiet zone either side —
    so it measures instead of calculating.
    """
    from reportlab.graphics.barcode import code128
    narrow = NARROW_IDEAL
    while narrow > 0.2:
        bar = code128.Code128(code, barWidth=narrow, barHeight=BAR_HEIGHT,
                              humanReadable=False)
        if bar.width <= max_w:
            return bar, narrow
        narrow -= 0.05
    # Nothing sensible fits. Draw it at the floor and let the caller report it
    # rather than silently printing a label nobody can scan.
    return code128.Code128(code, barWidth=0.2, barHeight=BAR_HEIGHT,
                           humanReadable=False), 0.2


def _draw_label(c, x: float, y: float, lay: Layout,
                item: Dict[str, Any]) -> Optional[str]:
    """Draw one label with its origin at bottom-left. Returns a problem, or None."""
    from reportlab.graphics.barcode import code128

    pad = 5.0
    inner_w = lay.label_w - pad * 2
    code = label_code(item)
    name = (item.get("name") or "").strip() or "(unnamed)"
    where = (item.get("location") or "").strip()
    unit = (item.get("unit") or "").strip()

    problem = None
    bar = None
    if code:
        bar, narrow = _fit_barcode(code, inner_w)
        if narrow < NARROW_MIN:
            problem = (f"{code} ({name}) is too long for this label — its bars "
                       f"print at {narrow:.2f}pt and a handheld needs "
                       f"{NARROW_MIN:.2f}pt to read reliably. Shorten the SKU, "
                       f"or print on the wider L7163 sheet.")
    else:
        problem = f"{name} has no SKU, so there is nothing to scan"

    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x + pad, y + lay.label_h - pad - 7,
                 _fit(name, "Helvetica-Bold", 8, inner_w))

    if where or unit:
        c.setFont("Helvetica", 6.5)
        line = " · ".join(p for p in (where, unit) if p)
        c.drawString(x + pad, y + lay.label_h - pad - 16,
                     _fit(line, "Helvetica", 6.5, inner_w))

    if bar is not None:
        bx = x + (lay.label_w - bar.width) / 2
        bar.drawOn(c, bx, y + pad + 9)
        c.setFont("Helvetica", 7)
        c.drawCentredString(x + lay.label_w / 2, y + pad + 1, code)
    else:
        c.setFont("Helvetica-Oblique", 7)
        c.drawCentredString(x + lay.label_w / 2, y + lay.label_h / 2 - 3,
                            "no SKU - add one in Stock")
    return problem


def build_label_sheet(path, items: Iterable[Dict[str, Any]],
                      layout: Layout = L7160,
                      start_at: int = 1,
                      guides: bool = False) -> Tuple[str, List[str]]:
    """Write barcode labels for `items`. Returns (path, problems).

    `start_at` is the first label position to print on, counting left to right
    then down from 1, so a part-used sheet can be fed back in.

    Problems name the items whose label will not scan well rather than
    silently printing something useless.
    """
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.pagesizes import A4

    items = [i for i in (items or [])]
    if not items:
        raise ValueError("No stock items selected, so there is nothing to print.")

    lay = layout
    page_w, page_h = A4
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    c = rl_canvas.Canvas(str(path), pagesize=A4)

    problems: List[str] = []
    slot = max(1, int(start_at or 1)) - 1          # 0-based position on sheet
    slot %= lay.per_sheet
    drawn_on_page = slot > 0

    for item in items:
        if slot >= lay.per_sheet:
            c.showPage()
            slot = 0
            drawn_on_page = False
        col, row = slot % lay.across, slot // lay.across
        x = lay.left + col * lay.pitch_x
        # Rows run down the page; PDF y counts up from the bottom.
        y = page_h - lay.top - (row + 1) * lay.label_h - row * (lay.pitch_y - lay.label_h)
        if guides:
            c.setStrokeColorRGB(0.85, 0.85, 0.85)
            c.setLineWidth(0.25)
            c.rect(x, y, lay.label_w, lay.label_h)
        problem = _draw_label(c, x, y, lay, item)
        if problem:
            problems.append(problem)
        slot += 1
        drawn_on_page = True

    if drawn_on_page:
        c.showPage()
    c.save()
    return str(path), problems
