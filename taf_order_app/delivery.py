"""
Getting finished work out the door.

Orders carry a delivery region and a due date already; this turns those into
the two things the yard actually needs — a run sheet the driver takes with
them, grouped by region and in the order the van is loaded, and a record of
what actually went out.

Nothing here decides that an order is ready. Only a person marks work
complete, and only complete work reaches a run.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, Iterable, List, Optional

from . import part_numbers as _pn
from .validation import parse_date

# Regions in the order a run sheet lists them: the pick-ups first because
# they never leave the building, then the runs, then freight.
RUN_ORDER = ["Pick Up", "Local", "Logan", "Ipswich", "North",
             "Gold Coast", "Sunshine Coast", "Freight"]

# Statuses an order can be in and still need delivering. Anything already
# dispatched has been.
READY_STATUSES = ("Complete",)
NOT_YET_STATUSES = ("Pending", "In Production")
DISPATCHED = "Dispatched"


def region_of(order: Dict[str, Any]) -> str:
    """The region an order goes to, or "Unassigned"."""
    value = (order.get("location") or "").strip()
    if not value:
        header = order.get("db_header") or {}
        value = (header.get("Location") or "").strip()
    for name in _pn.REGION_NAMES:
        if value.lower() == name.lower():
            return name
    return value or "Unassigned"


def _sort_key(order: Dict[str, Any]):
    """Oldest promise first: what is most overdue is loaded first."""
    raw = (order.get("date_due") or "").strip()
    if raw.lower() == "asap":
        return (0, _dt.date.min, order.get("customer", ""))
    parsed = parse_date(raw)
    if parsed:
        return (0, parsed.date(), order.get("customer", ""))
    return (1, _dt.date.max, order.get("customer", ""))


def ready_for_delivery(orders: Iterable[Dict[str, Any]],
                       include_in_production: bool = False
                       ) -> List[Dict[str, Any]]:
    """The orders that could go out, newest promise last.

    Only work someone has marked Complete is ready. `include_in_production`
    adds what is still being made, for planning tomorrow's run rather than
    loading today's.
    """
    wanted = set(READY_STATUSES)
    if include_in_production:
        wanted |= set(NOT_YET_STATUSES)
    out = [o for o in (orders or [])
           if (o.get("status") or "Pending") in wanted]
    return sorted(out, key=_sort_key)


def group_by_region(orders: Iterable[Dict[str, Any]]
                    ) -> List[tuple]:
    """[(region, [orders])] in run order, skipping regions with nothing."""
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for order in orders or []:
        buckets.setdefault(region_of(order), []).append(order)
    ordered = [(name, buckets.pop(name)) for name in RUN_ORDER if name in buckets]
    # Anything with a region we don't recognise still has to be delivered.
    ordered += sorted(buckets.items())
    return ordered


def run_summary(grouped: List[tuple]) -> str:
    """One line describing a run: what is on it and where it goes."""
    total = sum(len(rows) for _region, rows in grouped)
    if not total:
        return "Nothing is ready to go out."
    regions = len(grouped)
    return (f"{total} order{'s' if total != 1 else ''} across "
            f"{regions} region{'s' if regions != 1 else ''}")


def item_count(order: Dict[str, Any]) -> int:
    try:
        return int(order.get("n_items") or 0)
    except (TypeError, ValueError):
        return 0


def is_overdue(order: Dict[str, Any], today: Optional[_dt.date] = None) -> bool:
    raw = (order.get("date_due") or "").strip()
    if not raw or raw.lower() == "asap":
        return raw.lower() == "asap"
    parsed = parse_date(raw)
    if not parsed:
        return False
    return parsed.date() < (today or _dt.date.today())


# ── The run sheet ────────────────────────────────────────────────────────────

def build_run_sheet_pdf(out_path, grouped: List[tuple],
                        run_date: Optional[_dt.date] = None,
                        prepared_by: str = "") -> str:
    """A printable run sheet: one section per region, a tick box per order.

    Built to be carried on a clipboard and written on — big rows, a signature
    column, and the due date on every line so a driver can see what is late
    without asking.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors as _c
    from reportlab.lib.units import mm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, HRFlowable)
    from pathlib import Path

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    run_date = run_date or _dt.date.today()

    navy = _c.HexColor("#1A4F8A")
    dark = _c.HexColor("#2D3748")
    muted = _c.HexColor("#718096")
    rule = _c.HexColor("#D5DDE5")
    late = _c.HexColor("#B03A2E")

    # Explicit leading everywhere: ReportLab defaults to 12pt whatever the
    # font size, so a large heading draws over the line beneath it.
    s_h1 = ParagraphStyle("h1", fontSize=18, leading=22, textColor=navy,
                          fontName="Helvetica-Bold")
    s_meta = ParagraphStyle("meta", fontSize=9, leading=12, textColor=muted)
    s_region = ParagraphStyle("region", fontSize=12, leading=15, textColor=navy,
                              fontName="Helvetica-Bold")
    s_cell = ParagraphStyle("cell", fontSize=9, leading=12, textColor=dark)
    s_late = ParagraphStyle("late", parent=s_cell, textColor=late,
                            fontName="Helvetica-Bold")
    s_head = ParagraphStyle("head", parent=s_cell, textColor=_c.white,
                            fontName="Helvetica-Bold")

    doc = SimpleDocTemplate(str(out_path), pagesize=A4,
                            leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"Run sheet {run_date:%d/%m/%Y}")

    story: List[Any] = [
        Paragraph("DELIVERY RUN SHEET", s_h1),
        Paragraph(f"Total Air Filtration · {run_date:%A %d %B %Y}"
                  + (f" · prepared by {prepared_by}" if prepared_by else ""),
                  s_meta),
        HRFlowable(width="100%", thickness=1, color=navy,
                   spaceBefore=6, spaceAfter=10),
    ]

    if not grouped:
        story.append(Paragraph(
            "Nothing is marked Complete, so there is nothing to load. Mark "
            "orders Complete in Previous Orders and print this again.", s_cell))
        doc.build(story)
        return str(out_path)

    # ASCII only. ReportLab's built-in Helvetica is Latin-1, so a tick or a
    # warning triangle prints as a black box — which on a run sheet reads as
    # a printing fault rather than as "this one is late".
    head = ["Done", "Order #", "Customer", "Items", "Due", "Received by"]
    widths = [15 * mm, 26 * mm, None, 13 * mm, 26 * mm, 42 * mm]

    for region, rows in grouped:
        story.append(Paragraph(
            f"{region} &nbsp;&nbsp;<font size=9 color='#718096'>"
            f"{len(rows)} order{'s' if len(rows) != 1 else ''}</font>", s_region))
        story.append(Spacer(1, 4))

        body = [[Paragraph(h, s_head) for h in head]]
        late_rows = []
        for n, order in enumerate(rows, start=1):
            overdue = is_overdue(order)
            if overdue:
                late_rows.append(n)
            due = (order.get("date_due") or "").strip() or "-"
            # "ASAP" already says it is urgent; "LATE ASAP" says nothing more.
            if overdue and due.lower() != "asap":
                due = "LATE " + due
            body.append([
                Paragraph("", s_cell),                 # tick box, drawn as a grid cell
                Paragraph(order.get("order_no") or "—", s_cell),
                Paragraph(order.get("customer") or "—", s_cell),
                Paragraph(str(item_count(order)), s_cell),
                Paragraph(due, s_late if overdue else s_cell),
                Paragraph("", s_cell),                 # signed for on delivery
            ])

        table = Table(body, colWidths=widths, repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), navy),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.4, rule),
            ("ALIGN", (3, 0), (3, -1), "CENTER"),
            ("TOPPADDING", (0, 1), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 7),
        ]
        for r in range(1, len(body)):
            if r % 2 == 0:
                style.append(("BACKGROUND", (0, r), (-1, r),
                              _c.HexColor("#F5F8FB")))
        for r in late_rows:
            style.append(("BACKGROUND", (0, r), (-1, r), _c.HexColor("#FADBD8")))
        table.setStyle(TableStyle(style))
        story.append(table)
        story.append(Spacer(1, 12))

    story.append(HRFlowable(width="100%", thickness=0.6, color=rule,
                            spaceBefore=2, spaceAfter=6))
    story.append(Paragraph(
        "Tick each order as it is loaded and have the customer sign on "
        "delivery. Mark them Dispatched in the app when the run is done.",
        s_meta))

    doc.build(story)
    return str(out_path)
