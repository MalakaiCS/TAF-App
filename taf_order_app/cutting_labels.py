"""Wire and media cutting labels: 3" x 2", for a thermal label printer.

The worksheet already says what each line's wire and media are cut to. This
puts the same numbers on small labels - one for the wire and one for the
media of each worksheet line - for whoever is at the cutting table to stick
on the stack they cut, so a stack says which order and line it is for, not
just a size. Flyscreens are left out.

The sizes come from the same place as the worksheet's WIRE CUT and MEDIA
CUT columns (filter_calc.worksheet_cuts, and the flyscreen and bag-header
rules beside it), so a label and its sheet cannot disagree.

Each label is its own 3" x 2" page, which is what a label printer prints
one label from.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

LABEL_W = 3 * 72.0           # 3 inches, in points
LABEL_H = 2 * 72.0           # 2 inches


def _int(value: Any) -> int:
    try:
        return int(float(str(value).strip() or 0))
    except (TypeError, ValueError):
        return 0


def _pair(text: str) -> Optional[tuple]:
    """"580*580" -> (580, 580)."""
    parts = str(text or "").replace("x", "*").replace("×", "*").split("*")
    if len(parts) != 2:
        return None
    a, b = _int(parts[0]), _int(parts[1])
    return (a, b) if a and b else None


def cuts_for(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    """What is cut for one worksheet line: one entry for the wire and one
    for the media, each its own label - they are cut at different tables
    and go on different stacks. Each is {"kind": "WIRE" | "MEDIA", "title",
    "size", "media_type", "qty", "cut": (w, l, how many)}. Flyscreens are
    left out (their mesh is cut on the flyscreen bench), and so is anything
    with nothing to cut: a stock V-form, a header-only line."""
    from .filter_calc import worksheet_cuts
    qty = _int(item.get("Quantity") or item.get("quantity") or 0)
    short, long_ = _int(item.get("Short")), _int(item.get("Long"))
    channel = _int(item.get("Channel"))
    media = str(item.get("Media Type") or "").upper()
    ftype = str(item.get("Filter Type") or "").lower()

    if item.get("Bag Header"):
        wire = _pair(item.get("Header Wire Cut"))
        if not wire:
            return []
        n = _int(item.get("Header Wire Qty")) or qty
        return [{"kind": "WIRE", "title": f"Bag header H{channel}",
                 "size": f"{short} × {long_}", "media_type": "", "qty": qty,
                 "cut": (wire[0], wire[1], n)}]

    def framed(s: int, l: int, ch: int, kind: str, title: str):
        label = f"F{ch}" if kind == "flat panel" else f"V{ch}"
        ws, wl, ms, ml = worksheet_cuts(s, l, ch, label)
        common = {"title": title or label, "size": f"{s} × {l}",
                  "media_type": media, "qty": qty}
        return [dict(common, kind="WIRE", cut=(ws, wl, qty * 2)),
                dict(common, kind="MEDIA", cut=(ms, ml, qty))]

    if ftype == "flyscreen":
        return []
    if ftype == "stepped filter":
        # Only the V-form inside it; the flyscreen outside is left out.
        return framed(max(0, short - 25), max(0, long_ - 25),
                      max(0, channel - 10), "v-form",
                      f"Stepped - inner V{max(0, channel - 10)}")
    if item.get("Use Stock V-form") or item.get("Header"):
        return []
    return framed(short, long_, channel, ftype, "")


def labels_for_order(header: Dict[str, Any], items: List[Dict[str, Any]],
                     page_start: int = 1, grand_total: Optional[int] = None
                     ) -> List[Dict[str, Any]]:
    """Every cutting label for an order's worksheet lines, in sheet order.
    `items` are the lines the filter worksheet prints, page by page."""
    total = grand_total if grand_total is not None else len(items)
    out = []
    for i, item in enumerate(items):
        for cut in cuts_for(item):
            out.append(dict(cut,
                            order_number=str(header.get("Order Number") or ""),
                            customer=str(header.get("Customer Name") or ""),
                            due=str(header.get("Date Due") or ""),
                            line=f"{page_start + i} of {total}"))
    return out


def render_pdf(labels: List[Dict[str, Any]], path: str) -> str:
    """One 3" x 2" page per label."""
    from reportlab.pdfgen import canvas
    if not labels:
        raise ValueError("there is nothing to cut on this order")
    c = canvas.Canvas(str(path), pagesize=(LABEL_W, LABEL_H))
    c.setTitle("Cutting labels")
    m = 7.0
    w = LABEL_W - 2 * m

    def fit(text, font, size, width, least=6.0):
        while size > least and c.stringWidth(text, font, size) > width:
            size -= 0.5
        return size

    for lab in labels:
        top = LABEL_H - m
        # Order number, big; the line it is for, beside it.
        line = f"LINE {lab['line']}"
        c.setFont("Helvetica-Bold", 9)
        lw = c.stringWidth(line, "Helvetica-Bold", 9)
        c.drawRightString(m + w, top - 10, line)
        on = lab["order_number"] or "-"
        size = fit(on, "Helvetica-Bold", 15, w - lw - 8)
        c.setFont("Helvetica-Bold", size)
        c.drawString(m, top - 13, on)
        cust = lab["customer"].upper()
        size = fit(cust, "Helvetica", 8, w)
        c.setFont("Helvetica", size)
        c.drawString(m, top - 24, cust)
        what = "   ".join(x for x in (
            lab["title"], lab.get("media_type") or "", lab["size"],
            f"x {lab['qty']}" if lab.get("qty") else "") if x)
        size = fit(what, "Helvetica-Bold", 10, w)
        c.setFont("Helvetica-Bold", size)
        c.drawString(m, top - 37, what)
        c.setLineWidth(1.2)
        c.line(m, top - 42, m + w, top - 42)

        # The cut: what it is, how big, how many - big, the one thing on it.
        name = lab["kind"]
        if lab["kind"] == "MEDIA" and lab.get("media_type"):
            name += f"  {lab['media_type']}"
        a, b, n = lab["cut"]
        y = top - 42
        c.setFont("Helvetica-Bold", 14)
        c.drawString(m, y - 16, name)
        count = f"x {n}"
        c.setFont("Helvetica-Bold", 20)
        cw = c.stringWidth(count, "Helvetica-Bold", 20)
        cut = f"{a} × {b}"
        size = fit(cut, "Helvetica-Bold", 30, w - cw - 10)
        base = m + 22
        c.setFont("Helvetica-Bold", size)
        c.drawString(m, base, cut)
        c.setFont("Helvetica-Bold", 20)
        c.drawRightString(m + w, base, count)
        # Due date along the foot.
        due = str(lab.get("due") or "").strip()
        if due:
            try:
                from .bag_filler import due_text
                due = due_text(due)
            except Exception:
                due = due.upper()
            c.setFont("Helvetica-Bold", 8)
            c.drawString(m, m - 1, f"DUE {due}")
        c.showPage()
    c.save()
    return str(path)
