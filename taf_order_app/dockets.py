"""The paperwork that goes out with the filters.

A run sheet is for the driver: every drop on one page, ticked off as the van
empties. A docket is for one customer — what they are actually being handed,
and their signature saying they got it.

Two copies of each, which is the whole point. The customer keeps one; the
other is signed and comes back, and that signed sheet is the only thing that
settles "we never received those" three weeks later. Run sheets get written
on, folded up and lost in a van; a docket with a name and a signature on it
goes in a folder.

One docket per customer, not per order. Somebody who collects five orders at
once signs once for the lot, and what they sign has to list all five — each
order number with its own filters underneath, so a dispute about one order
does not put the other four in doubt.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Callable, Dict, Iterable, List, Optional

from . import delivery as _delivery
from . import pricing as _pricing

# A pick-up never leaves the building, so the paperwork should not say
# "delivered to" — the wording on a signed docket is the wording that gets
# read back to you later.
COLLECTED = "COLLECTION"
DELIVERED = "DELIVERY"
BOTH = "COLLECTION / DELIVERY"

CUSTOMER_COPY = "CUSTOMER COPY"
OFFICE_COPY = "OFFICE COPY"


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip() or default)
    except (TypeError, ValueError):
        return default


def group_by_customer(orders: Iterable[Dict[str, Any]]) -> List[tuple]:
    """[(customer, [orders])] — one entry per customer, A to Z.

    Grouped on the name as it will be printed. Two spellings of one customer
    would produce two dockets, which is wrong but is also exactly what the
    order list says: inventing a match here would hide it.
    """
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for order in orders or []:
        name = (order.get("customer") or "").strip() or "(no customer)"
        buckets.setdefault(name, []).append(order)
    out = []
    for name in sorted(buckets, key=str.lower):
        out.append((name, sorted(buckets[name], key=_delivery._sort_key)))
    return out


def handover(orders: Iterable[Dict[str, Any]]) -> str:
    """Whether this lot is being collected, delivered, or some of each."""
    regions = {_delivery.region_of(o) for o in (orders or [])}
    if not regions:
        return DELIVERED
    pickups = {r for r in regions if r == "Pick Up"}
    if pickups == regions:
        return COLLECTED
    if not pickups:
        return DELIVERED
    return BOTH


def order_lines(items: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
    """The filters on one order, as rows for a docket.

    Quantity first, because the person checking the pallet is counting.
    """
    out = []
    for item in items or []:
        out.append({
            "quantity": str(_int(item.get("Quantity"), 1) or 1),
            "part": str(item.get("Part Number") or "").strip() or "-",
            "description": _pricing.describe_item(item),
        })
    return out


def build_docket(customer: str, orders: List[Dict[str, Any]],
                 items_for: Callable[[Dict[str, Any]], Any]) -> Dict[str, Any]:
    """Everything one docket needs, with the lines already looked up.

    `items_for` is passed in rather than called here so this module never
    touches the database — it is the part that has to be testable without
    one, and the part a wrong answer would print onto a signed document.

    An order whose lines could not be read is kept with a note saying so.
    Dropping it would hand somebody a docket to sign that is missing an
    order they are being given.
    """
    entries = []
    for order in orders:
        try:
            items = items_for(order)
            failed = items is None
        except Exception:
            items, failed = None, True
        lines = order_lines(items or [])
        entries.append({
            "order_no": (order.get("order_no") or "").strip() or "-",
            "job": (order.get("job") or "").strip(),
            "due": (order.get("date_due") or "").strip(),
            "region": _delivery.region_of(order),
            "lines": lines,
            # Told straight, rather than printing an order with nothing
            # under it as though it were empty.
            "note": "Lines could not be read from the database" if failed
                    else ("No lines recorded on this order" if not lines
                          else ""),
        })
    return {
        "customer": customer,
        "kind": handover(orders),
        "orders": entries,
        "order_count": len(entries),
        "item_count": sum(_int(l["quantity"]) for e in entries
                          for l in e["lines"]),
    }


def build_dockets(grouped: List[tuple],
                  items_for: Callable[[Dict[str, Any]], Any]
                  ) -> List[Dict[str, Any]]:
    return [build_docket(name, orders, items_for) for name, orders in grouped]


def summary(dockets: List[Dict[str, Any]]) -> str:
    """One line for the status bar and the audit log."""
    if not dockets:
        return "Nothing to make a docket for."
    people = len(dockets)
    orders = sum(d["order_count"] for d in dockets)
    return (f"{people} docket{'s' if people != 1 else ''} covering "
            f"{orders} order{'s' if orders != 1 else ''}")


# ── The printed docket ───────────────────────────────────────────────────────

def build_dockets_pdf(out_path, dockets: List[Dict[str, Any]],
                      when: Optional[_dt.date] = None,
                      prepared_by: str = "") -> str:
    """Two pages per customer: their copy, then the one they sign.

    Both pages list exactly the same thing. The only difference is the block
    at the bottom — which is the point of there being two.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors as _c
    from reportlab.lib.units import mm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, HRFlowable, PageBreak)
    from pathlib import Path

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    when = when or _dt.date.today()

    navy = _c.HexColor("#1A4F8A")
    dark = _c.HexColor("#2D3748")
    muted = _c.HexColor("#718096")
    rule = _c.HexColor("#D5DDE5")

    # Explicit leading everywhere: ReportLab defaults to 12pt whatever the
    # font size, so a large heading draws over the line beneath it.
    s_h1 = ParagraphStyle("h1", fontSize=17, leading=21, textColor=navy,
                          fontName="Helvetica-Bold")
    s_copy = ParagraphStyle("copy", fontSize=12, leading=15, textColor=dark,
                            fontName="Helvetica-Bold", alignment=2)
    s_meta = ParagraphStyle("meta", fontSize=9, leading=12, textColor=muted)
    s_who = ParagraphStyle("who", fontSize=14, leading=18, textColor=dark,
                           fontName="Helvetica-Bold")
    s_order = ParagraphStyle("order", fontSize=10, leading=13, textColor=navy,
                             fontName="Helvetica-Bold")
    s_cell = ParagraphStyle("cell", fontSize=9, leading=12, textColor=dark)
    s_head = ParagraphStyle("head", parent=s_cell, textColor=_c.white,
                            fontName="Helvetica-Bold")
    s_note = ParagraphStyle("note", fontSize=9, leading=12, textColor=muted,
                            fontName="Helvetica-Oblique")
    s_sign = ParagraphStyle("sign", fontSize=10, leading=26, textColor=dark)

    doc = SimpleDocTemplate(str(out_path), pagesize=A4,
                            leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"Delivery dockets {when:%d/%m/%Y}")

    story: List[Any] = []

    if not dockets:
        story.append(Paragraph("DELIVERY DOCKET", s_h1))
        story.append(Paragraph(
            "Nothing was selected to make a docket for. Pick the orders "
            "going out on the Delivery tab and print again.", s_cell))
        doc.build(story)
        return str(out_path)

    def _page(docket: Dict[str, Any], copy_label: str) -> List[Any]:
        bits: List[Any] = []
        head = Table(
            [[Paragraph(f"{docket['kind']} DOCKET", s_h1),
              Paragraph(copy_label, s_copy)]],
            colWidths=[110 * mm, None])
        head.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        bits.append(head)
        bits.append(Paragraph(
            f"Total Air Filtration &nbsp;·&nbsp; {when:%A %d %B %Y}"
            + (f" &nbsp;·&nbsp; prepared by {prepared_by}" if prepared_by else ""),
            s_meta))
        bits.append(HRFlowable(width="100%", thickness=1, color=navy,
                               spaceBefore=6, spaceAfter=8))

        bits.append(Paragraph(docket["customer"], s_who))
        bits.append(Paragraph(
            f"{docket['order_count']} order"
            f"{'s' if docket['order_count'] != 1 else ''} &nbsp;·&nbsp; "
            f"{docket['item_count']} item"
            f"{'s' if docket['item_count'] != 1 else ''} in total", s_meta))
        bits.append(Spacer(1, 10))

        for entry in docket["orders"]:
            label = f"Order {entry['order_no']}"
            extra = []
            if entry["job"]:
                extra.append(f"job {entry['job']}")
            if entry["due"]:
                extra.append(f"due {entry['due']}")
            if entry["region"] and entry["region"] != "Unassigned":
                extra.append(entry["region"])
            if extra:
                label += ("&nbsp;&nbsp;<font size=9 color='#718096'>"
                          + " &nbsp;·&nbsp; ".join(extra) + "</font>")
            bits.append(Paragraph(label, s_order))
            bits.append(Spacer(1, 3))

            if entry["note"]:
                bits.append(Paragraph(entry["note"], s_note))
                bits.append(Spacer(1, 10))
                continue

            body = [[Paragraph(h, s_head)
                     for h in ("Qty", "Part Number", "Description")]]
            for line in entry["lines"]:
                body.append([Paragraph(line["quantity"], s_cell),
                             Paragraph(line["part"], s_cell),
                             Paragraph(line["description"], s_cell)])
            table = Table(body, colWidths=[14 * mm, 38 * mm, None],
                          repeatRows=1)
            style = [
                ("BACKGROUND", (0, 0), (-1, 0), navy),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.4, rule),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("TOPPADDING", (0, 1), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
            ]
            for r in range(1, len(body)):
                if r % 2 == 0:
                    style.append(("BACKGROUND", (0, r), (-1, r),
                                  _c.HexColor("#F5F8FB")))
            table.setStyle(TableStyle(style))
            bits.append(table)
            bits.append(Spacer(1, 10))

        bits.append(HRFlowable(width="100%", thickness=0.6, color=rule,
                               spaceBefore=4, spaceAfter=8))

        if copy_label == OFFICE_COPY:
            taking = ("Collected by" if docket["kind"] == COLLECTED
                      else "Received by")
            sign = Table([
                [Paragraph(f"{taking} (print name)", s_cell),
                 Paragraph("_" * 34, s_sign)],
                [Paragraph("Signature", s_cell),
                 Paragraph("_" * 34, s_sign)],
                [Paragraph("Date and time", s_cell),
                 Paragraph("_" * 34, s_sign)],
            ], colWidths=[46 * mm, None])
            sign.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            bits.append(sign)
            bits.append(Spacer(1, 4))
            bits.append(Paragraph(
                "Signed for the orders listed above. Total Air Filtration "
                "keeps this copy.", s_note))
        else:
            bits.append(Paragraph(
                "This is your copy - keep it. Please check the items listed "
                "above against what you have received and tell us straight "
                "away if anything is missing or damaged.", s_cell))
            bits.append(Spacer(1, 4))
            bits.append(Paragraph(
                "Goods remain the property of Total Air Filtration until "
                "paid for in full.", s_note))
        return bits

    for i, docket in enumerate(dockets):
        if i:
            story.append(PageBreak())
        story.extend(_page(docket, CUSTOMER_COPY))
        story.append(PageBreak())
        story.extend(_page(docket, OFFICE_COPY))

    doc.build(story)
    return str(out_path)
