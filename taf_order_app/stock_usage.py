"""
What an order takes out of stock.

Deduction is deliberately literal. Guessing at a bill of materials — so many
metres of channel, so much spline, a corner per corner — would quietly drift
away from the real count, and a stock figure nobody trusts is worse than no
stock figure at all. So only two things are deducted, both of them things the
order states outright:

    1. A finished item whose SKU is the line's part number.
       FPFG425-040 on the order takes one FPFG425-040 off the shelf.

    2. The media a line is made from, by area, when the media is kept in
       square metres.

Anything without a matching stock item is left alone and reported, so the gaps
are visible rather than silent.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from . import part_numbers as _pn

# The unit a media roll has to be kept in for an area to be deducted from it.
# A roll kept in metres can't be reduced by an area without knowing its width,
# so those are reported as unmatched instead of being guessed at.
AREA_UNITS = {"m2", "m²", "sqm", "square metre", "square metres"}

MEDIA_PRODUCT_TYPE = "Media Roll"


def _key(text: str) -> str:
    return _pn.wording_key(text)


def _index(stock_items: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Stock items by SKU, then by name for anything without one."""
    by_key: Dict[str, Dict[str, Any]] = {}
    for it in stock_items or []:
        for field in ("sku", "name"):
            k = _key(it.get(field) or "")
            if k and k not in by_key:
                by_key[k] = it
    return by_key


def _media_index(stock_items: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Media rolls by grade — matched on SKU or name, e.g. 'G4', '180'."""
    rolls: Dict[str, Dict[str, Any]] = {}
    for it in stock_items or []:
        if (it.get("product_type") or "") != MEDIA_PRODUCT_TYPE:
            continue
        for field in ("sku", "name"):
            k = _key(it.get(field) or "")
            if k and k not in rolls:
                rolls[k] = it
    return rolls


def _quantity(item: Dict[str, Any]) -> int:
    try:
        return max(0, int(str(item.get("Quantity") or 0).strip()))
    except (TypeError, ValueError):
        return 0


def plan_deductions(items: Iterable[Dict[str, Any]],
                    stock_items: Iterable[Dict[str, Any]],
                    order_number: str = "") -> Dict[str, List[Dict[str, Any]]]:
    """Work out what an order would take out of stock, without taking it.

    Returns ``{"deduct": [...], "unmatched": [...]}``. Each deduction carries
    the stock item, how much, and the wording that goes on the stock
    transaction so the movement can be traced back to the order.
    """
    stock_items = list(stock_items or [])
    by_key   = _index(stock_items)
    by_media = _media_index(stock_items)

    deductions: Dict[str, Dict[str, Any]] = {}
    unmatched: List[Dict[str, Any]] = []
    ref = f"Order {order_number}".strip() if order_number else "Order"

    def _add(stock_item, qty, why):
        if qty <= 0:
            return
        row = deductions.setdefault(stock_item["id"], {
            "item": stock_item, "quantity": 0.0, "reasons": [],
        })
        row["quantity"] += qty
        if why not in row["reasons"]:
            row["reasons"].append(why)

    for it in items or []:
        qty = _quantity(it)
        if qty <= 0:
            continue

        part = (it.get("Part Number") or "").strip()
        if part:
            hit = by_key.get(_key(part))
            if hit:
                _add(hit, qty, f"{qty} x {part} ({ref})")
                continue        # a finished item doesn't also consume media

        media = (it.get("Media Type") or "").strip()
        area  = _pn.nominal_square_metres(_pn.effective_area(it)) * qty
        roll  = by_media.get(_key(media)) if media else None
        if roll and area > 0:
            if (roll.get("unit") or "").strip().lower() in AREA_UNITS:
                _add(roll, round(area, 3),
                     f"{round(area, 2)} m2 of {media} ({ref})")
                continue
            unmatched.append({
                "description": f"{media} media, {round(area, 2)} m2",
                "why": f'"{roll.get("name")}" is kept in '
                       f'{roll.get("unit") or "unknown units"}, not m2',
            })
            continue

        label = part or f"{media or 'filter'} line"
        unmatched.append({
            "description": f"{qty} x {label}",
            "why": "nothing in stock has that part number or media grade",
        })

    return {"deduct": list(deductions.values()), "unmatched": unmatched}


def describe(plan: Dict[str, List[Dict[str, Any]]]) -> str:
    """A one-line summary of a plan, for the status bar and the audit log."""
    n = len(plan.get("deduct") or [])
    u = len(plan.get("unmatched") or [])
    if not n and not u:
        return "Nothing to deduct from stock."
    parts = []
    if n:
        parts.append(f"{n} stock item{'s' if n != 1 else ''} deducted")
    if u:
        parts.append(f"{u} line{'s' if u != 1 else ''} not matched to stock")
    return " · ".join(parts) + "."


def apply_plan(plan: Dict[str, List[Dict[str, Any]]], adjust) -> int:
    """Run a plan through ``adjust(item_id, 'use', qty, notes)``.

    Returns how many stock items were actually moved. A failure on one item
    does not stop the rest: a stock figure that is short by one line is still
    better than one that is short by a whole order.
    """
    done = 0
    for row in (plan.get("deduct") or []):
        try:
            adjust(row["item"]["id"], "use", round(float(row["quantity"]), 3),
                   "; ".join(row["reasons"])[:400])
            done += 1
        except Exception:
            continue
    return done


def find_unit_problem(stock_items: Iterable[Dict[str, Any]]) -> Optional[str]:
    """Warn once about media rolls that can never be deducted from.

    Returns a sentence naming them, or None when every roll is in m2.
    """
    bad = [i.get("name") or "(unnamed)" for i in (stock_items or [])
           if (i.get("product_type") or "") == MEDIA_PRODUCT_TYPE
           and (i.get("unit") or "").strip().lower() not in AREA_UNITS]
    if not bad:
        return None
    listed = ", ".join(bad[:4]) + (f" and {len(bad) - 4} more" if len(bad) > 4 else "")
    return (f"Media kept in units other than m2 can't be deducted by area: "
            f"{listed}. Set those items' unit to m2 in Stock to include them.")
