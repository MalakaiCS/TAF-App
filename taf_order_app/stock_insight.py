"""Stock you can trust: what open orders have spoken for, what suppliers
have charged, and what to order before it runs out.

Pure, so it is tested on its own. migrate_stock_insight.sql (step 47) is
where the figures are kept.
"""
from __future__ import annotations

import datetime as _dt
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence

from . import stock_usage as _usage
from .insights import parse_date

DONE = ("Complete", "Dispatched", "Delivered", "Collected")


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _outstanding(order: Dict[str, Any]) -> bool:
    head = order.get("header") if isinstance(order.get("header"), dict) else {}
    status = str(head.get("status") or order.get("status") or "Pending")
    return status not in DONE and not order.get("archived")


def reserved_by_item(orders: Iterable[Dict[str, Any]],
                     stock_items: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """{stock item id: {"reserved", "orders"}} - what every order still to
    finish will take, by the same rules stock is deducted by (stock_usage).
    A line already made has been made: what it took is off the shelf, or
    should be, so it is not counted twice."""
    stock_items = list(stock_items or [])
    out: Dict[str, Dict[str, Any]] = {}
    for o in orders or []:
        if not _outstanding(o):
            continue
        items = [i for i in (o.get("items") or [])
                 if isinstance(i, dict) and not i.get("made")]
        if not items:
            continue
        plan = _usage.plan_deductions(items, stock_items, str(o.get("order_number") or ""))
        for d in plan["deduct"]:
            key = str(d["item"].get("id"))
            row = out.setdefault(key, {"reserved": 0.0, "orders": 0})
            row["reserved"] = round(row["reserved"] + float(d["quantity"]), 3)
            row["orders"] += 1
    return out


def free(stock: Dict[str, Any], reserved: Dict[str, Dict[str, Any]]) -> float:
    """On hand less what open orders have spoken for."""
    held = _num(stock.get("stock_on_hand"))
    return held - _num((reserved.get(str(stock.get("id"))) or {}).get("reserved"))


# ── What we have paid ────────────────────────────────────────────────────────

def price_history(rows: Iterable[Dict[str, Any]], stock_item_id: str = "",
                  codes: Sequence[str] = ()) -> List[Dict[str, Any]]:
    """Every price paid for a stock item (by its id, or any of its supplier
    codes), oldest first, each with the change from the one before from the
    same supplier."""
    want = {str(c).strip().upper() for c in codes if str(c).strip()}
    picked = []
    for r in rows or []:
        hit = (stock_item_id and str(r.get("stock_item_id") or "") == str(stock_item_id)) \
            or (want and str(r.get("item_code") or "").strip().upper() in want)
        if hit and r.get("unit_price") not in (None, ""):
            picked.append(r)
    picked.sort(key=lambda r: str(r.get("bought_at") or ""))
    last: Dict[str, float] = {}
    out = []
    for r in picked:
        who = str(r.get("supplier") or "")
        price = _num(r.get("unit_price"))
        before = last.get(who)
        out.append({"day": parse_date(r.get("bought_at")), "supplier": who,
                    "code": str(r.get("item_code") or ""), "price": price,
                    "quantity": _num(r.get("quantity")),
                    "po": str(r.get("po_number") or ""),
                    "change": (None if before in (None, 0)
                               else round((price - before) / before * 100, 1))})
        last[who] = price
    return out


# ── What to order before it runs out ─────────────────────────────────────────

def usage_per_day(transactions: Iterable[Dict[str, Any]], item_id: str,
                  today: _dt.date, days: int = 60) -> float:
    """How much of an item has been used a day, over the last `days`."""
    since = today - _dt.timedelta(days=days)
    used = 0.0
    for t in transactions or []:
        if str(t.get("stock_item_id")) != str(item_id):
            continue
        if str(t.get("transaction_type") or "") not in ("use", "writeoff"):
            continue
        day = parse_date(t.get("created_at"))
        if day is None or day < since:
            continue
        used += abs(_num(t.get("quantity_change")))
    return used / float(days)


def order_soon(stock_items: Iterable[Dict[str, Any]],
               transactions: Iterable[Dict[str, Any]],
               links: Iterable[Dict[str, Any]],
               lead_times: Iterable[Dict[str, Any]],
               today: _dt.date,
               reserved: Optional[Dict[str, Dict[str, Any]]] = None,
               default_days: float = 7.0) -> List[Dict[str, Any]]:
    """Stock that will be under its minimum before a new order could get
    here - at the rate it has been used, less what open orders have spoken
    for - with how many to order. Soonest first."""
    reserved = reserved or {}
    by_supplier = {str(l.get("supplier_id") or ""): _num(l.get("median_days") or
                                                         l.get("avg_days"), 0)
                   for l in lead_times or []}
    names = {str(l.get("supplier_id") or ""): str(l.get("supplier") or "")
             for l in lead_times or []}
    preferred: Dict[str, Dict[str, Any]] = {}
    for l in sorted(links or [], key=lambda l: not l.get("preferred")):
        preferred.setdefault(str(l.get("stock_item_id")), l)
    out = []
    for s in stock_items or []:
        least = _num(s.get("minimum_on_hand"))
        if least <= 0:
            continue
        sid = str(s.get("id"))
        have = free(s, reserved)
        rate = usage_per_day(transactions, sid, today)
        link = preferred.get(sid) or {}
        supplier = str(link.get("supplier_id") or "")
        lead = by_supplier.get(supplier) or default_days
        if have < least:
            days_left = 0.0
        elif rate <= 0:
            continue                       # not being used: nothing to beat
        else:
            days_left = (have - least) / rate
        if days_left > lead:
            continue
        # Enough to be back at the minimum when it arrives, and to cover
        # the wait.
        need = max(0.0, least - have + rate * lead)
        out.append({"item": s, "free": have, "per_day": round(rate, 3),
                    "days_left": round(days_left, 1), "lead_days": lead,
                    "supplier_id": supplier,
                    "supplier": names.get(supplier, ""),
                    "order": float(math.ceil(need)) if need > 0 else 0.0})
    return sorted(out, key=lambda r: (r["days_left"] - r["lead_days"],
                                      str(r["item"].get("name") or "")))
