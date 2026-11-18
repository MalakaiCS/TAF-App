"""Winning the work and keeping it: chasing quotes, why they are lost,
customers due for a filter change, price changes and who owes what.

Pure, so it is tested on its own. docs/app/screens.js has the same rules
for the phone's Today screen - a test holds the two together - and
migrate_sales.sql (step 46) is where it is all kept.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import quote as _q

from .insights import parse_date

# ── Chasing quotes ───────────────────────────────────────────────────────────

AWAITING = ("sent", "viewed")
CHASE_AFTER = 7          # days with no answer before a quote is worth chasing


def _day(value: Any) -> Optional[_dt.date]:
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    return parse_date(value)


def to_chase(quotes: Iterable[Dict[str, Any]], today: _dt.date,
             after: int = CHASE_AFTER) -> List[Dict[str, Any]]:
    """Quotes sent at least `after` days ago with no answer, and not chased
    in the last `after` days - longest waiting first."""
    out = []
    for q in quotes or []:
        if str(q.get("status") or "") not in AWAITING:
            continue
        sent = _day(q.get("sent_at"))
        if not sent or (today - sent).days < after:
            continue
        chased = _day(q.get("chased_at"))
        if chased and (today - chased).days < after:
            continue
        out.append(dict(q, waited=(today - sent).days))
    return sorted(out, key=lambda q: (-q["waited"], str(q.get("quote_number") or "")))


def chase_email(quote: Dict[str, Any], link: str, company: str = "Total Air Filtration",
                contact: str = "") -> Dict[str, str]:
    """The subject and words of a follow-up, ready to send."""
    number = str(quote.get("quote_number") or "").strip()
    hello = f"Hi {contact.split()[0]}," if contact.strip() else "Hi,"
    total = quote.get("total")
    worth = ""
    try:
        if float(total or 0) > 0:
            worth = f" (${float(total):,.2f} inc GST)"
    except (TypeError, ValueError):
        worth = ""
    subject = f"Quote {number} from {company}".replace("  ", " ").strip()
    body = (f"{hello}\n\n"
            f"Just following up on our quote {number}{worth}. You can read it "
            f"and accept it online here:\n\n{link}\n\n"
            "If anything needs changing - sizes, quantities or timing - reply "
            "to this email and we'll sort it out.\n\n"
            f"Thanks,\n{company}")
    return {"subject": subject, "body": body}


def mailto(to: str, subject: str, body: str) -> str:
    """A mailto: link that opens the email ready to send."""
    # Escaped as the phone's encodeURIComponent does, so both write the same.
    safe = "!*'()"
    return (f"mailto:{_q(str(to or '').strip(), safe='@,' + safe)}"
            f"?subject={_q(subject, safe=safe)}&body={_q(body, safe=safe)}")


# ── Why quotes are lost ──────────────────────────────────────────────────────

LOST_REASONS = ["Price", "Lead time", "Went elsewhere", "No longer needed",
                "No reply", "Other"]


def lost_report(quotes: Iterable[Dict[str, Any]],
                since: Optional[_dt.date] = None) -> Dict[str, Any]:
    """Quotes won and lost since a day, and the reasons lost ones went."""
    won = lost = 0
    won_value = lost_value = 0.0
    reasons: Dict[str, Dict[str, Any]] = {}
    for q in quotes or []:
        day = _day(q.get("responded_at") or q.get("updated_at") or q.get("created_at"))
        if since and day and day < since:
            continue
        status = str(q.get("status") or "")
        value = float(q.get("total") or 0)
        if status == "accepted":
            won += 1
            won_value += value
        elif status in ("declined", "expired"):
            lost += 1
            lost_value += value
            name = str(q.get("lost_reason") or "").strip() or "Not given"
            r = reasons.setdefault(name, {"name": name, "count": 0, "value": 0.0})
            r["count"] += 1
            r["value"] += value
    decided = won + lost
    return {"won": won, "lost": lost, "won_value": won_value,
            "lost_value": lost_value,
            "win_rate": (won / decided) if decided else None,
            "reasons": sorted(reasons.values(),
                              key=lambda r: (-r["count"], -r["value"], r["name"]))}


# ── Due for a filter change ──────────────────────────────────────────────────

def service_due(customers: Iterable[Dict[str, Any]],
                orders: Iterable[Dict[str, Any]], today: _dt.date,
                ahead: int = 14) -> List[Dict[str, Any]]:
    """Customers whose filters are changed every so many weeks, whose next
    change falls within `ahead` days (or has passed), and who are not
    snoozed - soonest (most overdue) first."""
    last: Dict[str, _dt.date] = {}
    for o in orders or []:
        name = str(o.get("customer_name") or o.get("customer") or "").strip().lower()
        d = _day(o.get("date_ordered")) or _day(o.get("created_at"))
        if name and d and (name not in last or d > last[name]):
            last[name] = d
    out = []
    for c in customers or []:
        try:
            weeks = int(c.get("service_weeks") or 0)
        except (TypeError, ValueError):
            weeks = 0
        if weeks <= 0:
            continue
        snoozed = _day(c.get("service_snoozed_until"))
        if snoozed and snoozed > today:
            continue
        names = {str(c.get(k) or "").strip().lower() for k in ("name", "short_name")}
        seen = [last[n] for n in names if n in last]
        if not seen:
            continue
        prev = max(seen)
        due = prev + _dt.timedelta(weeks=weeks)
        if due > today + _dt.timedelta(days=ahead):
            continue
        out.append({"customer": c, "last": prev, "due": due,
                    "late": (today - due).days if due < today else 0})
    return sorted(out, key=lambda r: (r["due"], str(r["customer"].get("name") or "")))


# ── Changing prices ──────────────────────────────────────────────────────────

TIER_COLS = {
    "list":  {1: "unit_price", 2: "unit_price_2", 3: "unit_price_3"},
    "rates": {1: "rate_per_sqm", 2: "rate_per_sqm_2", 3: "rate_per_sqm_3"},
}


def new_price(old: Any, percent: float) -> Optional[float]:
    """The price after the change, to the cent; None stays None (a tier
    with no price of its own falls back to tier 1)."""
    if old is None or old == "":
        return None
    v = float(old) * (1 + float(percent) / 100.0)
    return float(f"{v + (1e-9 if v >= 0 else -1e-9):.2f}")


def _matches(row: Dict[str, Any], kind: str, text: str) -> bool:
    t = str(text or "").strip().lower()
    if not t:
        return True
    keys = ("part_number", "name") if kind == "list" else ("filter_type", "media_type")
    return any(t in str(row.get(k) or "").lower() for k in keys)


def price_preview(list_rows: Iterable[Dict[str, Any]],
                  rate_rows: Iterable[Dict[str, Any]],
                  change: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every price the change would move: what, which tier, old and new.
    The same rules as apply_price_change in migrate_sales.sql."""
    scope = str(change.get("scope") or "all")
    tiers = [int(t) for t in change.get("tiers") or [1, 2, 3]]
    pct = float(change.get("percent") or 0)
    text = str(change.get("match_text") or "")
    out = []
    for kind, rows in (("list", list_rows), ("rates", rate_rows)):
        if scope not in ("all", kind):
            continue
        for row in rows or []:
            if not _matches(row, kind, text):
                continue
            what = (str(row.get("part_number") or "") if kind == "list" else
                    " ".join(x for x in (str(row.get("filter_type") or ""),
                                         str(row.get("media_type") or "")) if x)
                    + " /m²")
            for tier in tiers:
                old = row.get(TIER_COLS[kind][tier])
                new = new_price(old, pct)
                if new is None:
                    continue
                out.append({"kind": kind, "what": what, "tier": tier,
                            "old": float(old), "new": new})
    return out


# ── Who owes what ────────────────────────────────────────────────────────────

AGES = [("current", "Not due"), ("d30", "1-30 days"), ("d60", "31-60 days"),
        ("d90", "61-90 days"), ("over", "Over 90 days")]


def age_bucket(days_late: Any) -> str:
    try:
        d = int(days_late or 0)
    except (TypeError, ValueError):
        d = 0
    if d <= 0:
        return "current"
    if d <= 30:
        return "d30"
    if d <= 60:
        return "d60"
    if d <= 90:
        return "d90"
    return "over"


def owing_by_customer(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Unpaid invoices (from the Xero function's owing) added up by
    customer, aged - the most overdue money first."""
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows or []:
        name = str(r.get("customer") or "").strip() or "(no name)"
        c = out.setdefault(name, {"customer": name, "owing": 0.0,
                                  "oldest": 0, "invoices": [],
                                  **{k: 0.0 for k, _ in AGES}})
        owe = float(r.get("owing") or 0)
        c["owing"] += owe
        c[age_bucket(r.get("days_late"))] += owe
        c["oldest"] = max(c["oldest"], int(r.get("days_late") or 0))
        c["invoices"].append(r)
    for c in out.values():
        c["invoices"].sort(key=lambda r: str(r.get("due") or ""))
    return sorted(out.values(), key=lambda c: (-c["oldest"], -c["owing"], c["customer"]))


def statement_lines(customer: Dict[str, Any]) -> List[List[str]]:
    """The rows of a statement: invoice, due, total, still owing, days late."""
    rows = []
    for r in customer.get("invoices") or []:
        rows.append([str(r.get("number") or ""), str(r.get("due") or ""),
                     f"${float(r.get('total') or 0):,.2f}",
                     f"${float(r.get('owing') or 0):,.2f}",
                     str(int(r.get("days_late") or 0) or "")])
    return rows


def statement_pdf(out_path, customer: Dict[str, Any], company: str = "Total Air Filtration",
                  on: Optional[_dt.date] = None) -> str:
    """A statement of what one customer owes: every unpaid invoice, when it
    was due, and the total aged - to print or attach to an email."""
    from pathlib import Path
    from reportlab.lib import colors as _c
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (HRFlowable, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)
    on = on or _dt.date.today()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    navy = _c.HexColor("#1A4F8A")
    dark = _c.HexColor("#2D3748")
    muted = _c.HexColor("#718096")
    s_h1 = ParagraphStyle("h1", fontSize=18, leading=22, textColor=navy,
                          fontName="Helvetica-Bold")
    s_meta = ParagraphStyle("meta", fontSize=10, leading=13, textColor=muted)
    s_body = ParagraphStyle("body", fontSize=10, leading=13, textColor=dark)
    doc = SimpleDocTemplate(str(out_path), pagesize=A4, leftMargin=16 * mm,
                            rightMargin=16 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm,
                            title=f"Statement - {customer.get('customer', '')}")
    rows = [["Invoice", "Due", "Total", "Owing", "Days late"]]
    rows += statement_lines(customer)
    rows.append(["", "", "Total owing", f"${float(customer.get('owing') or 0):,.2f}", ""])
    table = Table(rows, colWidths=[38 * mm, 32 * mm, 34 * mm, 34 * mm, 26 * mm],
                  repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), navy),
        ("TEXTCOLOR", (0, 0), (-1, 0), _c.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 1, navy),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [_c.white, _c.HexColor("#F4F7FA")]),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    ages = Table([[label for _k, label in AGES],
                  [f"${float(customer.get(k) or 0):,.2f}" for k, _l in AGES]],
                 colWidths=[33 * mm] * len(AGES))
    ages.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (-1, 0), muted),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("BOX", (0, 0), (-1, -1), 0.5, _c.HexColor("#D5DDE5")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    doc.build([
        Paragraph("STATEMENT", s_h1),
        Paragraph(f"{company} · {on:%d %B %Y}", s_meta),
        HRFlowable(width="100%", thickness=1, color=navy, spaceBefore=6,
                   spaceAfter=10),
        Paragraph(f"<b>{customer.get('customer', '')}</b>", s_body),
        Spacer(1, 8),
        Paragraph("These invoices are still to be paid. If you have paid "
                  "since, thank you - please ignore this.", s_body),
        Spacer(1, 10), table, Spacer(1, 14), ages,
    ])
    return str(out_path)
