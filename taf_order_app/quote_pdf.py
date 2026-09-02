"""
The quote PDF.

A quote goes out to a customer with TAF's name on it, so this prints only what
it was given: every line, its part number, its area, its price, and totals that
add up. Nothing is estimated here — a line with no price arrives priced at zero
and is shown as "TO BE CONFIRMED", because a plausible-looking guessed figure
is the one mistake a quote must never make.
"""
from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import pricing as _pricing

GST_RATE = 0.10
VALID_DAYS = 30


def _logo_path() -> Optional[str]:
    base = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "frozen", False) \
        else Path(__file__).resolve().parent.parent
    p = base / "TAF_logo.png"
    return str(p) if p.exists() else None


def build_quote_pdf(out_path,
                    header: Dict[str, Any],
                    lines: Iterable[Dict[str, Any]],
                    customer: Optional[Dict[str, Any]] = None,
                    quote_number: str = "",
                    prepared_by: str = "",
                    gst_rate: float = GST_RATE,
                    valid_days: int = VALID_DAYS) -> str:
    """Write a quote PDF and return its path."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors as _c
    from reportlab.lib.units import mm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, Image, HRFlowable)

    lines = list(lines)
    customer = customer or {}
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    navy  = _c.HexColor("#1A4F8A")
    dark  = _c.HexColor("#2D3748")
    muted = _c.HexColor("#718096")
    rule  = _c.HexColor("#D5DDE5")
    warn  = _c.HexColor("#B03A2E")

    # leading has to be set explicitly: ReportLab's default is 12pt whatever
    # the font size, so a 20pt heading draws on top of the line beneath it.
    s_h1   = ParagraphStyle("h1", fontSize=20, leading=24, textColor=navy,
                            fontName="Helvetica-Bold", spaceAfter=2)
    s_meta = ParagraphStyle("meta", fontSize=9, textColor=muted, leading=13)
    s_body = ParagraphStyle("body", fontSize=9, textColor=dark, leading=12)
    s_cell = ParagraphStyle("cell", fontSize=8.5, textColor=dark, leading=11)
    s_note = ParagraphStyle("note", fontSize=8.5, textColor=muted, leading=12)

    doc = SimpleDocTemplate(str(out_path), pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"Quote {quote_number}".strip())

    story: List[Any] = []

    # ── Masthead ─────────────────────────────────────────────────────────
    logo = _logo_path()
    left = [Paragraph("QUOTATION", s_h1),
            Paragraph("Total Air Filtration", s_meta)]
    if logo:
        try:
            masthead = Table(
                [[Image(logo, width=42 * mm, height=16 * mm, kind="proportional"),
                  left]],
                colWidths=[46 * mm, None])
            masthead.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("LEFTPADDING", (1, 0), (1, 0), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            story.append(masthead)
        except Exception:
            story.extend(left)      # a missing logo never stops a quote
    else:
        story.extend(left)

    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1, color=navy,
                            spaceBefore=2, spaceAfter=8))

    # ── Who and when ─────────────────────────────────────────────────────
    today = _dt.date.today()
    bill_to = ((customer.get("legal_name") or "").strip()
               or (customer.get("name") or "").strip()
               or (header.get("Customer Name") or "").strip() or "—")
    addr = " ".join(x for x in [
        (customer.get("delivery_address1") or "").strip(),
        (customer.get("delivery_city") or "").strip(),
        (customer.get("delivery_state") or "").strip(),
        (customer.get("delivery_postcode") or "").strip(),
    ] if x)

    detail_rows = [
        ["Quote number", quote_number or "—",
         "Date", today.strftime("%d/%m/%Y")],
        ["Customer", bill_to,
         "Valid until",
         (today + _dt.timedelta(days=valid_days)).strftime("%d/%m/%Y")],
        ["Reference", (header.get("Order Number") or "—"),
         "Prepared by", prepared_by or "—"],
    ]
    if addr:
        detail_rows.insert(2, ["Deliver to", addr, "Region",
                               (header.get("Location") or "—")])
    elif header.get("Location"):
        detail_rows.append(["Region", header.get("Location"), "", ""])

    details = Table([[Paragraph(f"<b>{a}</b>", s_body), Paragraph(str(b), s_body),
                      Paragraph(f"<b>{c}</b>", s_body), Paragraph(str(d), s_body)]
                     for a, b, c, d in detail_rows],
                    colWidths=[24 * mm, 78 * mm, 24 * mm, None])
    details.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(details)
    story.append(Spacer(1, 10))

    # ── Lines ────────────────────────────────────────────────────────────
    # A Paragraph carries its own colour, so the table's TEXTCOLOR can't lift
    # the heading off the navy band — the heading style has to say white.
    s_head = ParagraphStyle("head", parent=s_cell, textColor=_c.white,
                            fontName="Helvetica-Bold")
    head = ["#", "Part Number", "Description", "Qty", "Unit", "Total"]
    body = [[Paragraph(h, s_head) for h in head]]
    unpriced_rows: List[int] = []

    for i, line in enumerate(lines, start=1):
        priced = bool(line.get("source"))
        if not priced:
            unpriced_rows.append(i)
        body.append([
            Paragraph(str(i), s_cell),
            Paragraph(line.get("part_number") or "—", s_cell),
            Paragraph(line.get("description") or "", s_cell),
            Paragraph(str(line.get("quantity", 0)), s_cell),
            Paragraph(f'{line.get("unit_price", 0):,.2f}' if priced
                      else "TO BE CONFIRMED", s_cell),
            Paragraph(f'{line.get("line_total", 0):,.2f}' if priced else "—", s_cell),
        ])

    table = Table(body, colWidths=[9 * mm, 30 * mm, None, 12 * mm,
                                   24 * mm, 22 * mm], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), navy),
        ("TEXTCOLOR", (0, 0), (-1, 0), _c.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.4, rule),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for r in range(1, len(body)):
        if r % 2 == 0:
            style.append(("BACKGROUND", (0, r), (-1, r), _c.HexColor("#F5F8FB")))
    for r in unpriced_rows:
        style.append(("TEXTCOLOR", (4, r), (5, r), warn))
    table.setStyle(TableStyle(style))
    story.append(table)
    story.append(Spacer(1, 8))

    # ── Totals ───────────────────────────────────────────────────────────
    totals = _pricing.quote_totals(lines, gst_rate)
    trows = [["Subtotal (ex GST)", f'{totals["subtotal"]:,.2f}'],
             [f"GST ({gst_rate * 100:.0f}%)", f'{totals["gst"]:,.2f}'],
             ["Total (inc GST)", f'{totals["total"]:,.2f}']]
    ttable = Table([[Paragraph(a, s_body), Paragraph(b, s_body)] for a, b in trows],
                   colWidths=[38 * mm, 24 * mm], hAlign="RIGHT")
    ttable.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, 2), (-1, 2), 0.8, navy),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(ttable)
    story.append(Spacer(1, 10))

    if unpriced_rows:
        listed = ", ".join(str(r) for r in unpriced_rows)
        story.append(Paragraph(
            f'<font color="#B03A2E"><b>Line{"s" if len(unpriced_rows) != 1 else ""} '
            f'{listed} {"are" if len(unpriced_rows) != 1 else "is"} not priced.</b></font> '
            "The totals above exclude them and this quote is incomplete until "
            "they are confirmed.", s_note))
        story.append(Spacer(1, 6))

    story.append(HRFlowable(width="100%", thickness=0.6, color=rule,
                            spaceBefore=2, spaceAfter=6))
    story.append(Paragraph(
        f"Prices are in AUD and valid for {valid_days} days from the date above. "
        "Goods remain the property of Total Air Filtration until paid for in full.",
        s_note))

    doc.build(story)
    return str(out_path)
