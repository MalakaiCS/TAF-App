"""What the work made, and how the month is going.

Two things, both pure so they are tested on their own:

  - a sales target: how far through the month's target the orders entered
    so far are, and what each working day left has to bring in;
  - a job's profit: what it sold for, less what went into it (the costs
    already kept for the margin on a quote) and the time spent making it
    (the job timer, at the workshop's labour rate).

What an order is worth comes from the order_values view (step 48), so the
PC, the phone and the owner's report add it up the one way.
"""
from __future__ import annotations

import calendar
import datetime as _dt
from typing import Any, Dict, Iterable, List, Optional

from . import pricing as _pricing


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def local_when(stamp: Any) -> str:
    """"17/10/2026 10:42" in this computer's time, from a database
    timestamp - or "" when it is not one."""
    try:
        when = _dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if when.tzinfo is not None:
        when = when.astimezone()
    return when.strftime("%d/%m/%Y %H:%M")


# ── A month's target ─────────────────────────────────────────────────────────

def month_start(day: _dt.date) -> _dt.date:
    return day.replace(day=1)


def month_end(day: _dt.date) -> _dt.date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def working_days(first: _dt.date, last: _dt.date) -> int:
    """Monday to Friday from `first` to `last`, both counted."""
    if last < first:
        return 0
    n, d = 0, first
    while d <= last:
        if d.weekday() < 5:
            n += 1
        d += _dt.timedelta(days=1)
    return n


def target_progress(sold: float, target: float, today: _dt.date) -> Optional[Dict[str, Any]]:
    """How the month is going against its target, or None with no target.

    `done` counts today as a day gone (the orders in today are in `sold`);
    `per_day` is what each working day after today has to bring in to make
    it. `ahead` is against a straight line through the month's working days -
    negative is behind."""
    target = _num(target)
    if target <= 0:
        return None
    sold = round(_num(sold), 2)
    first, last = month_start(today), month_end(today)
    total = working_days(first, last) or 1
    done = working_days(first, today)
    left = working_days(today + _dt.timedelta(days=1), last)
    short = max(0.0, round(target - sold, 2))
    expected = round(target * done / total, 2)
    return {"sold": sold, "target": round(target, 2),
            "percent": int(sold / target * 100),
            "short": short, "days_left": left,
            "per_day": round(short / left, 2) if left else short,
            "expected": expected, "ahead": round(sold - expected, 2),
            "made_it": sold >= target}


def target_text(p: Optional[Dict[str, Any]], month: _dt.date) -> str:
    """"October: $42,300 of $60,000 (70%). $1,475 a day for the 12 working
    days left." - or what to do when there is no target."""
    name = month.strftime("%B")
    if not p:
        return f"No target set for {name}."
    head = f"{name}: ${p['sold']:,.0f} of ${p['target']:,.0f} ({p['percent']}%)."
    if p["made_it"]:
        return head + " Target made."
    if not p["days_left"]:
        return head + f" ${p['short']:,.0f} short, and no working days left."
    return (head + f" ${p['per_day']:,.0f} a day for the {p['days_left']} "
            f"working day{'s' if p['days_left'] != 1 else ''} left.")


# ── A job's profit ───────────────────────────────────────────────────────────

def _line_type(item: Dict[str, Any]) -> str:
    if str(item.get("item_kind") or "") == "catalogue":
        return str(item.get("Description") or item.get("Part Number") or "Bought in")
    return str(item.get("Filter Type") or item.get("product_type") or "Other").strip() or "Other"


def job_profit(order: Dict[str, Any], costs: Optional[Dict[str, float]],
               cost_rates: Optional[Dict[str, float]],
               times: Iterable[Dict[str, Any]], rates: Dict[str, float],
               per_hour: float, default_minutes: float) -> Dict[str, Any]:
    """Sold, materials, labour and profit for one order, and by line.

    Labour is the job timer's minutes on each line when it was timed, and
    otherwise the minutes that type usually takes (job_rates) - marked as
    an estimate. Materials are the costs kept for quote margins; a line
    nobody has costed is counted in `uncosted` and left out of the profit
    rather than treated as free. A bought-in line takes no bench time."""
    items = [i for i in (order.get("items") or []) if isinstance(i, dict)]
    header = order.get("header") if isinstance(order.get("header"), dict) else {}
    oid = str(order.get("id") or "")
    timed: Dict[str, float] = {}
    for t in times or []:
        if str(t.get("order_id") or "") != oid or t.get("minutes") in (None, ""):
            continue
        key = str(t.get("line_id") or "")
        timed[key] = timed.get(key, 0.0) + _num(t.get("minutes"))
    lines = _pricing.with_margin(_pricing.quote_lines(items), costs, cost_rates)
    out_lines = []
    sold = materials = minutes = 0.0
    uncosted = unpriced = 0
    estimated = False
    for line in lines:
        item = line.get("item") or {}
        qty = line.get("quantity") or 0
        sell = float(line.get("line_total") or 0) if line.get("source") else 0.0
        if not line.get("source"):
            unpriced += 1
        cost = float(line.get("line_cost") or 0) if line.get("cost_source") else None
        if cost is None and line.get("source"):
            uncosted += 1
        lid = str(item.get("line_id") or "")
        if str(item.get("item_kind") or "") == "catalogue":
            mins, est = 0.0, False
        elif lid and lid in timed:
            mins, est = timed[lid], False
        else:
            kind = str(item.get("Filter Type") or item.get("product_type") or "").strip().lower()
            mins, est = qty * rates.get(kind, default_minutes), True
            estimated = estimated or (mins > 0)
        sold += sell
        materials += cost or 0.0
        minutes += mins
        out_lines.append({"type": _line_type(item), "quantity": qty, "sold": round(sell, 2),
                          "materials": None if cost is None else round(cost, 2),
                          "minutes": round(mins, 1), "estimated": est})
    # Minutes timed against the order but not a line still went into it.
    loose = sum(m for k, m in timed.items()
                if not any(str(i.get("line_id") or "") == k and k for i in items))
    minutes += loose
    fee = _pricing.delivery_fee(header)
    sold += fee
    labour = round(minutes / 60.0 * _num(per_hour), 2)
    profit = round(sold - materials - labour, 2)
    return {"id": oid, "order_number": str(order.get("order_number") or header.get("Order Number") or ""),
            "customer": str(order.get("customer_name") or header.get("Customer Name") or ""),
            "sold": round(sold, 2), "delivery": fee, "materials": round(materials, 2),
            "minutes": round(minutes, 1), "labour": labour, "profit": profit,
            "percent": round(profit / sold * 100, 1) if sold else None,
            "estimated": estimated, "uncosted": uncosted, "unpriced": unpriced,
            "lines": out_lines}


def profit_by(jobs: Iterable[Dict[str, Any]], key: str = "customer") -> List[Dict[str, Any]]:
    """Jobs added up by customer, or (key="type") their lines by filter type,
    most profit first. A type's delivery fees stay with the customer."""
    groups: Dict[str, Dict[str, Any]] = {}
    for job in jobs or []:
        if key == "type":
            parts = [(l["type"], l["sold"], l["materials"] or 0.0, l["minutes"])
                     for l in job["lines"]]
            rate = (job["labour"] / job["minutes"]) if job["minutes"] else 0.0
        else:
            parts = [(job["customer"] or "—", job["sold"], job["materials"], job["minutes"])]
            rate = None
        for name, sold, mats, mins in parts:
            g = groups.setdefault(name, {"name": name, "ids": set(), "sold": 0.0,
                                         "materials": 0.0, "labour": 0.0,
                                         "minutes": 0.0})
            g["ids"].add(job["id"])
            g["sold"] += sold
            g["materials"] += mats
            g["minutes"] += mins
            g["labour"] += (mins * rate) if rate is not None else job["labour"]
    out = []
    for g in groups.values():
        profit = g["sold"] - g["materials"] - g["labour"]
        out.append({"name": g["name"], "jobs": len(g["ids"]), "sold": round(g["sold"], 2),
                    "materials": round(g["materials"], 2),
                    "labour": round(g["labour"], 2), "minutes": round(g["minutes"], 1),
                    "profit": round(profit, 2),
                    "percent": round(profit / g["sold"] * 100, 1) if g["sold"] else None})
    return sorted(out, key=lambda g: (-g["profit"], g["name"]))
