"""What the customer standing at the counter is shown.

A second monitor turned to face them while a quote is put together, so they
can see what has been added and what it comes to instead of watching
somebody's back and waiting for a number at the end.

This module exists as its own file for one reason. The quote screen knows
what every line COST as well as what it sells for - it prints the margin
along the bottom for the people who set prices - and that is the one figure
in this building that must never be visible from the customer side of the
counter. Working out what goes on the display here, from prices alone, means
there is no path from a cost to that screen: nothing in this file is ever
handed a cost, so nothing in it can leak one. A display built by reading the
quote screen's own labels would be one careless change away from showing it.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

from . import pricing as _pricing

# A line nobody could price. It has to appear - a customer who asked for it
# is entitled to see it on the list - but with no number beside it and no
# pretence that the total covers it.
TO_CONFIRM = "to confirm"


def display_lines(lines: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
    """The quote as rows of text for the customer's screen.

    Strings, not numbers, and only the four fields a customer reads. Anything
    else a quote line carries - what it cost, what it was priced from, which
    item it came from - is dropped here rather than filtered out further
    down where somebody could stop filtering.
    """
    out: List[Dict[str, str]] = []
    for line in lines:
        priced = bool(line.get("source"))
        qty = line.get("quantity", 0)
        out.append({
            "description": str(line.get("description") or "").strip() or "—",
            "part":        str(line.get("part_number") or "").strip(),
            "quantity":    f"{qty:,}" if isinstance(qty, (int, float)) else str(qty),
            "unit_price":  f'{line.get("unit_price", 0):,.2f}' if priced else TO_CONFIRM,
            "line_total":  f'{line.get("line_total", 0):,.2f}' if priced else TO_CONFIRM,
            "priced":      "yes" if priced else "no",
        })
    return out


def display_totals(lines: Iterable[Dict[str, Any]], shipping: float = 0.0,
                   gst_rate: float = 0.10) -> List[tuple]:
    """The rows down the bottom, as (label, amount, emphasis) tuples.

    Delivery is only listed when there is one to list: a line reading
    "Delivery 0.00" invites the question of what it would have been.
    """
    lines = list(lines)
    t = _pricing.quote_totals(lines, gst_rate, shipping)
    rows = []
    if t["shipping"]:
        rows.append(("Goods", f'${t["goods"]:,.2f}', False))
        rows.append(("Delivery", f'${t["shipping"]:,.2f}', False))
    rows.append(("Subtotal", f'${t["subtotal"]:,.2f}', False))
    rows.append((f"GST ({gst_rate * 100:.0f}%)", f'${t["gst"]:,.2f}', False))
    rows.append(("Total", f'${t["total"]:,.2f}', True))
    return rows


def caveat(lines: Iterable[Dict[str, Any]]) -> str:
    """What to say under the total when the total does not cover everything.

    A customer reading a total that silently excludes two of their lines is
    being given a number that is wrong for them, and they will hold us to it.
    """
    missing = _pricing.unpriced(lines)
    if not missing:
        return ""
    n = len(missing)
    return (f"{n} line{'s' if n != 1 else ''} still to be priced — "
            f"{'they are' if n != 1 else 'it is'} not included in the total.")
