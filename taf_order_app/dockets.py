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
    """The filters on one order, as rows for a docket: the item code and the
    wording the Xero invoice uses, so the docket and the invoice read alike.
    """
    from . import invoice_wording as _wording
    out = []
    for item in items or []:
        try:
            part = _pricing.line_part_number(item)
        except Exception:
            part = ""
        try:
            text = _wording.describe(item)
        except Exception:
            text = ""
        out.append({
            "quantity": str(_int(item.get("Quantity") or item.get("quantity"), 1)
                            or 1),
            "part": (part or str(item.get("Part Number") or "")).strip() or "-",
            "description": text or _pricing.describe_item(item),
        })
    return out


def address_lines(customer: Optional[Dict[str, Any]], prefix: str) -> List[str]:
    """A customer's delivery or billing address as Xero prints it: street
    lines, then "YATALA QLD 4207", then the country in capitals."""
    c = customer or {}

    def g(k):
        return str(c.get(f"{prefix}_{k}") or "").strip()
    if not g("address1"):
        return []
    town = " ".join(x for x in (g("city").upper(), g("state"), g("postcode")) if x)
    return [x for x in (g("address1"), g("address2"), town,
                        (g("country") or "Australia").upper()) if x]


def bill_to_lines(customer: Optional[Dict[str, Any]]) -> List[str]:
    """Where the invoice goes: the billing address, or the delivery one when
    billing is the same (or none was given)."""
    c = customer or {}
    if c.get("billing_same", True) is not False or not str(
            c.get("billing_address1") or "").strip():
        return address_lines(c, "delivery")
    return address_lines(c, "billing")


def build_docket(customer: str, orders: List[Dict[str, Any]],
                 items_for: Callable[[Dict[str, Any]], Any],
                 customer_for: Optional[Callable[[str, List[Dict[str, Any]]],
                                                 Any]] = None) -> Dict[str, Any]:
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
    # Their account, for the addresses. Looked up by the caller, like the
    # lines; a docket with no address still lists what is being handed over.
    try:
        account = customer_for(customer, orders) if customer_for else None
    except Exception:
        account = None
    account = account or {}
    invoices = []
    for order in orders:
        no = str(order.get("invoice_no") or "").strip()
        if no and no not in invoices:
            invoices.append(no)
    return {
        "customer": customer,
        "bill_name": str(account.get("legal_name") or "").strip() or customer,
        "deliver_to": address_lines(account, "delivery"),
        "bill_to": bill_to_lines(account),
        "invoices": invoices,
        "kind": handover(orders),
        "orders": entries,
        "order_count": len(entries),
        "item_count": sum(_int(l["quantity"]) for e in entries
                          for l in e["lines"]),
    }


def build_dockets(grouped: List[tuple],
                  items_for: Callable[[Dict[str, Any]], Any],
                  customer_for: Optional[Callable[[str, List[Dict[str, Any]]],
                                                  Any]] = None
                  ) -> List[Dict[str, Any]]:
    return [build_docket(name, orders, items_for, customer_for)
            for name, orders in grouped]


def summary(dockets: List[Dict[str, Any]]) -> str:
    """One line for the status bar and the audit log."""
    if not dockets:
        return "Nothing to make a docket for."
    people = len(dockets)
    orders = sum(d["order_count"] for d in dockets)
    return (f"{people} docket{'s' if people != 1 else ''} covering "
            f"{orders} order{'s' if orders != 1 else ''}")


# ── The printed docket ───────────────────────────────────────────────────────
# Laid out like the packing slip Xero prints with an invoice: the title and
# the logo across the top; who it goes to, the dates and numbers, who is
# billed and who it is from in a row under them; then the lines as Item,
# Description and Quantity, ruled and unfilled.

def _logo_path() -> Optional[str]:
    import sys
    from pathlib import Path
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    p = base / "TAF_logo_horizontal.png"
    return str(p) if p.exists() else None


def _esc(text: Any) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _company_lines(company_address: str) -> List[str]:
    """"Unit 1/19 Tradelink Road, Hillcrest Queensland 4118 Australia" as
    the lines it is printed on."""
    return [p.strip() for p in str(company_address or "").split(",") if p.strip()]


def build_dockets_pdf(out_path, dockets: List[Dict[str, Any]],
                      when: Optional[_dt.date] = None,
                      prepared_by: str = "",
                      company_address: str = "") -> str:
    """Two pages per customer: their copy, then the one they sign.

    Both pages list exactly the same thing. The only difference is the block
    at the bottom — which is the point of there being two.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors as _c
    from reportlab.lib.units import mm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, PageBreak, Image,
                                    KeepTogether)
    from pathlib import Path
    from . import calc_settings as _settings

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    when = when or _dt.date.today()
    company_address = company_address or _settings.BASE_ADDRESS_DEFAULT
    company = _settings.COMPANY

    black = _c.HexColor("#1A1A1A")
    muted = _c.HexColor("#6B7280")
    rule = _c.HexColor("#CFCFCF")
    box = _c.HexColor("#C8C8C8")

    # Explicit leading everywhere: ReportLab defaults to 12pt whatever the
    # font size, so a large heading draws over the line beneath it.
    s_title = ParagraphStyle("title", fontName="Helvetica", fontSize=24,
                             leading=28, textColor=black)
    s_copy = ParagraphStyle("copy", fontName="Helvetica-Bold", fontSize=8.5,
                            leading=11, textColor=muted)
    s_label = ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=9,
                             leading=11.5, textColor=black)
    s_text = ParagraphStyle("text", fontName="Helvetica", fontSize=9.5,
                            leading=13.5, textColor=black)
    s_head = ParagraphStyle("head", fontName="Helvetica-Bold", fontSize=9.5,
                            leading=12, textColor=black)
    s_head_r = ParagraphStyle("head_r", parent=s_head, alignment=2)
    s_cell = ParagraphStyle("cell", fontName="Helvetica", fontSize=9.5,
                            leading=12.5, textColor=black)
    s_cell_r = ParagraphStyle("cell_r", parent=s_cell, alignment=2)
    s_order = ParagraphStyle("order", fontName="Helvetica-Bold", fontSize=9.5,
                             leading=12.5, textColor=black)
    s_note = ParagraphStyle("note", fontName="Helvetica-Oblique", fontSize=8.5,
                            leading=11.5, textColor=muted)
    s_sign = ParagraphStyle("sign", fontName="Helvetica", fontSize=9.5,
                            leading=24, textColor=black)

    doc = SimpleDocTemplate(str(out_path), pagesize=A4,
                            leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"Delivery dockets {when:%d/%m/%Y}")
    width = A4[0] - 30 * mm
    logo = _logo_path()

    story: List[Any] = []

    if not dockets:
        story.append(Paragraph("DELIVERY DOCKET", s_title))
        story.append(Spacer(1, 8))
        story.append(Paragraph(
            "Nothing was selected to make a docket for. Pick the orders "
            "going out on the Delivery tab and print again.", s_cell))
        doc.build(story)
        return str(out_path)

    def _lines(label: str, lines: List[str]) -> List[Any]:
        return ([Paragraph(_esc(label), s_label)]
                + [Paragraph(_esc(t), s_text) for t in lines])

    def _block(*parts) -> Table:
        """Label-and-lines groups stacked in one cell, a little apart."""
        rows = []
        for i, part in enumerate(p for p in parts if p):
            if i:
                rows.append([Spacer(1, 5)])
            rows.extend([[x] for x in part])
        t = Table(rows or [[""]], colWidths=[None])
        t.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        return t

    def _page(docket: Dict[str, Any], copy_label: str) -> List[Any]:
        bits: List[Any] = []
        collected = docket["kind"] == COLLECTED

        # ── Title and logo ────────────────────────────────────────────────
        title = [Paragraph(f"{docket['kind']} DOCKET", s_title),
                 Spacer(1, 3), Paragraph(copy_label, s_copy)]
        right = (Image(logo, width=62 * mm, height=21 * mm, kind="proportional")
                 if logo else Paragraph("Total Air Filtration", s_label))
        head = Table([[title, right]], colWidths=[width - 66 * mm, 66 * mm])
        head.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        bits.append(head)
        bits.append(Spacer(1, 12))

        # ── Who, when, billed to, from ────────────────────────────────────
        orders = docket["orders"]
        to = _lines("Collection for" if collected else "Deliver to",
                    [docket["customer"]] + list(docket.get("deliver_to") or []))
        numbers = [_lines("Date", [f"{when:%d %b %Y}"])]
        if docket.get("invoices"):
            numbers.append(_lines(
                "Invoice Number" if len(docket["invoices"]) == 1
                else "Invoice Numbers", [", ".join(docket["invoices"])]))
        if len(orders) == 1:
            numbers.append(_lines("Order Number", [orders[0]["order_no"]]))
            if orders[0].get("job"):
                numbers.append(_lines("Job", [orders[0]["job"]]))
        else:
            numbers.append(_lines("Orders", [f"{len(orders)} - listed below"]))
        bill = _lines("Bill to", [docket.get("bill_name") or docket["customer"]]
                      + list(docket.get("bill_to") or []))
        ours = ([Paragraph(_esc(str(company.get("legal_name")
                                    or "Total Air Filtration Pty Ltd").upper()),
                           s_text)]
                + [Paragraph(_esc(t), s_text) for t in _company_lines(company_address)])
        abn = _lines("ABN", [company.get("abn", "")]) if company.get("abn") else []

        to_box = Table([[_block(to)]], colWidths=[58 * mm])
        to_box.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.6, box),
            ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
        ]))
        rest = width - 58 * mm
        row = Table([[to_box, _block(*numbers), _block(bill),
                      _block(ours, abn)]],
                    colWidths=[58 * mm + 6 * mm, rest * 0.24 - 2 * mm,
                               rest * 0.38 - 2 * mm, rest * 0.38 - 2 * mm])
        row.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (0, 0), 6 * mm),
        ]))
        bits.append(row)
        bits.append(Spacer(1, 24))

        # ── The lines ─────────────────────────────────────────────────────
        body = [[Paragraph("Item", s_head), Paragraph("Description", s_head),
                 Paragraph("Quantity", s_head_r)]]
        spans = []
        several = len(orders) > 1
        for entry in orders:
            if several:
                label = f"Order {_esc(entry['order_no'])}"
                extra = []
                if entry["job"]:
                    extra.append(f"Job {_esc(entry['job'])}")
                if entry["due"]:
                    extra.append(f"due {_esc(entry['due'])}")
                if extra:
                    label += ("&nbsp;&nbsp;<font name='Helvetica' color='#6B7280'>"
                              + " &nbsp;·&nbsp; ".join(extra) + "</font>")
                spans.append(len(body))
                body.append([Paragraph(label, s_order), "", ""])
            if entry["note"]:
                spans.append(len(body))
                body.append([Paragraph(_esc(entry["note"]), s_note), "", ""])
                continue
            for line in entry["lines"]:
                qty = _int(line["quantity"], 1)
                body.append([
                    Paragraph(_esc(line["part"]), s_cell),
                    Paragraph(_esc(line["description"]).replace("\n", "<br/>"),
                              s_cell),
                    Paragraph(f"{qty:.2f}", s_cell_r)])
        # The count to check the pallet against, under the Quantity column.
        body.append(["", Paragraph("Total items", s_head_r),
                     Paragraph(f"{docket['item_count']:.2f}", s_head_r)])
        table = Table(body, colWidths=[38 * mm, None, 24 * mm], repeatRows=1)
        style = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LINEBELOW", (0, 0), (-1, 0), 0.9, black),
            ("LINEBELOW", (0, 1), (-1, -2), 0.5, rule),
            ("TOPPADDING", (0, -1), (-1, -1), 8),
        ]
        for r in spans:
            style.append(("SPAN", (0, r), (-1, r)))
            if r > 1:
                style.append(("TOPPADDING", (0, r), (-1, r), 10))
        table.setStyle(TableStyle(style))
        bits.append(table)
        bits.append(Spacer(1, 16))

        # ── Signed for, or the customer's copy ────────────────────────────
        if copy_label == OFFICE_COPY:
            taking = "Collected by" if collected else "Received by"
            sign = Table([
                [Paragraph(f"{taking} (print name)", s_cell),
                 Paragraph("_" * 46, s_sign)],
                [Paragraph("Signature", s_cell), Paragraph("_" * 46, s_sign)],
                [Paragraph("Date and time", s_cell), Paragraph("_" * 46, s_sign)],
            ], colWidths=[46 * mm, None])
            sign.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            # The signature and what it is for stay on one page together.
            bits.append(KeepTogether([sign, Spacer(1, 4), Paragraph(
                "Signed for the orders listed above. Total Air Filtration "
                "keeps this copy."
                + (f" Prepared by {_esc(prepared_by)}." if prepared_by else ""),
                s_note)]))
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
