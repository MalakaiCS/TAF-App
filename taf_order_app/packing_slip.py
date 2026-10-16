"""The packing slip that goes with an invoice.

Xero prints a packing slip from an invoice - the invoice without its prices -
but only from its own screen: there is no way to ask its API for one. So it
is made here, the way Xero lays it out, from the same invoice: the invoice
number and reference Xero has, the customer, where it is going, and every
line with its item code and quantity, worded exactly as on the invoice.

The delivery charge is not something anybody packs, so it is left off.

Nothing here touches Tk or the database.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional

COMPANY = "Total Air Filtration"


def deliver_to(customer: Optional[Dict[str, Any]], name: str = "") -> List[str]:
    """The delivery address, a line at a time, from the customer's card."""
    c = customer or {}
    lines = [str(c.get("legal_name") or c.get("name") or name or "").strip()]
    for key in ("delivery_address1", "delivery_address2"):
        value = str(c.get(key) or "").strip()
        if value:
            lines.append(value)
    town = " ".join(str(c.get(k) or "").strip() for k in
                    ("delivery_city", "delivery_state", "delivery_postcode")
                    if str(c.get(k) or "").strip())
    if town:
        lines.append(town)
    return [line for line in lines if line]


def slip_from(invoice: Dict[str, Any], invoice_number: str,
              customer: Optional[Dict[str, Any]] = None,
              header: Optional[Dict[str, Any]] = None,
              company_address: str = "") -> Dict[str, Any]:
    """What the packing slip says, from the invoice as it was sent to Xero
    (xero.draft_from's "invoice") and the number Xero gave it."""
    from .pricing import DELIVERY_CODE
    header = header or {}
    lines = []
    for line in list(invoice.get("lines") or []) + list(invoice.get("unpriced") or []):
        if (line.get("item_code") or "") == DELIVERY_CODE:
            continue
        qty = float(line.get("quantity") or 0)
        lines.append({"code": str(line.get("item_code") or ""),
                      "description": str(line.get("description") or ""),
                      "quantity": int(qty) if qty == int(qty) else qty})
    return {
        "invoice_number": invoice_number or "",
        "reference": str(invoice.get("reference") or ""),
        "date": str(invoice.get("date") or _dt.date.today().isoformat()),
        "customer": str(header.get("Customer Name") or ""),
        "deliver_to": deliver_to(customer, str(header.get("Customer Name") or "")),
        "attention": str(header.get("Attention") or ""),
        "company": COMPANY,
        "company_address": company_address,
        "lines": lines,
    }


def _date_text(iso: str) -> str:
    try:
        return _dt.date.fromisoformat(iso[:10]).strftime("%d %b %Y")
    except ValueError:
        return iso


def build_packing_slip_pdf(out_path, slip: Dict[str, Any]) -> str:
    """One page (more if the lines run on): PACKING SLIP, who it is for and
    where it goes, the invoice it belongs to, and what is in it."""
    from pathlib import Path
    from xml.sax.saxutils import escape
    from reportlab.lib import colors as _c
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dark = _c.HexColor("#2D3748")
    muted = _c.HexColor("#718096")
    rule = _c.HexColor("#D5DDE5")
    s_title = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=22,
                             leading=26, textColor=dark)
    s_body = ParagraphStyle("b", fontName="Helvetica", fontSize=9.5,
                            leading=12.5, textColor=dark)
    s_label = ParagraphStyle("l", parent=s_body, fontName="Helvetica-Bold")
    s_head = ParagraphStyle("h", parent=s_body, fontName="Helvetica-Bold",
                            textColor=muted)
    s_qty = ParagraphStyle("q", parent=s_body, alignment=2)
    s_qty_head = ParagraphStyle("qh", parent=s_head, alignment=2)
    s_small = ParagraphStyle("s", parent=s_body, fontSize=8, textColor=muted)

    def para(text, style=s_body):
        return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), style)

    doc = SimpleDocTemplate(str(out_path), pagesize=A4, leftMargin=18 * mm,
                            rightMargin=18 * mm, topMargin=18 * mm,
                            bottomMargin=18 * mm,
                            title=f"Packing slip {slip.get('invoice_number') or ''}")
    width = A4[0] - 36 * mm

    company = [para(slip.get("company") or COMPANY, s_label)]
    if slip.get("company_address"):
        company.append(para(slip["company_address"]))
    top = Table([[para("PACKING SLIP", s_title), company]],
                colWidths=[width * 0.6, width * 0.4])
    top.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                             ("LEFTPADDING", (0, 0), (-1, -1), 0)]))

    to = [para("Deliver To", s_head)] + [para(l) for l in slip.get("deliver_to") or []]
    if slip.get("attention"):
        to.append(para(f"Attention: {slip['attention']}"))
    facts = []
    for label, value in (("Invoice Date", _date_text(slip.get("date") or "")),
                         ("Invoice Number", slip.get("invoice_number") or "-"),
                         ("Reference", slip.get("reference") or "-")):
        facts += [para(label, s_head), para(value)]
    who = Table([[to, facts]], colWidths=[width * 0.6, width * 0.4])
    who.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                             ("LEFTPADDING", (0, 0), (-1, -1), 0)]))

    rows = [[para("Item", s_head), para("Description", s_head),
             para("Quantity", s_qty_head)]]
    for line in slip.get("lines") or []:
        rows.append([para(line.get("code") or ""), para(line.get("description")),
                     para(line.get("quantity"), s_qty)])
    if len(rows) == 1:
        rows.append([para(""), para("Nothing on this invoice to pack."), para("")])
    table = Table(rows, colWidths=[width * 0.2, width * 0.65, width * 0.15],
                  repeatRows=1)
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, dark),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, rule),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
    ]))
    total = sum(float(l.get("quantity") or 0) for l in slip.get("lines") or [])
    total_text = int(total) if total == int(total) else total

    story = [top, Spacer(1, 10 * mm), who, Spacer(1, 8 * mm), table,
             Spacer(1, 4 * mm),
             para(f"Total items: {total_text}", s_label),
             Spacer(1, 8 * mm),
             para("Please check the goods against this slip when they arrive.",
                  s_small)]
    doc.build(story)
    return str(out_path)
