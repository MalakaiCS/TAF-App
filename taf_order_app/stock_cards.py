"""The Stock page as a grid of square cards: how many across, the units,
and the price on each.

Pure, so it is tested on its own; the desktop draws the cards and
docs/app/screens.js has the same rules for the phone and the browser.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

# How many cards across, by the width there is to put them in (in screen
# pixels at 100%): five on a wide screen, four on a medium one, three on a
# small desktop or tablet, two on a wide phone and one on a phone held
# upright, where two square cards would leave the photo a sliver. The same steps are in
# the web app's stylesheet.
STEPS = ((1100, 5), (860, 4), (600, 3), (420, 2))
GAP = 14                    # between cards, at 100%


def columns_for(width: float, scale: float = 1.0) -> int:
    """Cards across for `width` pixels of room (scaled for the display)."""
    plain = width / (scale or 1.0)
    for least, cols in STEPS:
        if plain >= least:
            return cols
    return 1


def card_size(width: float, cols: int, gap: float) -> int:
    """Each card's side: the room shared out, gaps taken off - the same
    for every card, so they line up and stay square."""
    cols = max(1, cols)
    return max(40, int((width - gap * (cols + 1)) // cols))


_UNITS = {
    "each": ("piece", "pieces"), "ea": ("piece", "pieces"),
    "pc": ("piece", "pieces"), "pcs": ("piece", "pieces"),
    "piece": ("piece", "pieces"), "pieces": ("piece", "pieces"),
    "m2": ("m²", "m²"), "sqm": ("m²", "m²"), "m²": ("m²", "m²"),
    "square metre": ("m²", "m²"), "square metres": ("m²", "m²"),
    "roll": ("roll", "rolls"), "rolls": ("roll", "rolls"),
    "length": ("length", "lengths"), "lengths": ("length", "lengths"),
    "box": ("box", "boxes"), "boxes": ("box", "boxes"),
    "m": ("m", "m"), "metre": ("m", "m"), "metres": ("m", "m"),
    "kg": ("kg", "kg"), "sheet": ("sheet", "sheets"),
    "sheets": ("sheet", "sheets"), "bag": ("bag", "bags"),
    "bags": ("bag", "bags"), "pack": ("pack", "packs"),
    "packs": ("pack", "packs"),
}


def unit_label(unit: Any, qty: Any = 2) -> str:
    """"rolls", "lengths", "pieces", "m²" - the stock item's own unit, said
    for the quantity it goes with."""
    raw = str(unit or "").strip()
    one, many = _UNITS.get(raw.lower(), (raw or "piece", raw or "pieces"))
    try:
        return one if float(qty) == 1 else many
    except (TypeError, ValueError):
        return many


def qty_text(qty: Any) -> str:
    try:
        n = float(qty or 0)
    except (TypeError, ValueError):
        return "0"
    return str(int(n)) if n == int(n) else f"{n:.2f}".rstrip("0").rstrip(".")


def price_for(stock: Dict[str, Any], links: Sequence[Dict[str, Any]] = (),
              items: Sequence[Dict[str, Any]] = ()) -> Optional[float]:
    """What we pay for one, ex GST: the preferred supplier's agreed price,
    else what Xero says we pay for their code for it, else for the Xero
    item linked to this stock item. None when nothing says."""
    sid = str(stock.get("id") or "")
    mine = sorted((l for l in links or [] if str(l.get("stock_item_id")) == sid),
                  key=lambda l: not l.get("preferred"))
    by_code = {str(it.get("code") or "").upper(): it for it in items or []}
    for link in mine:
        if link.get("unit_price") not in (None, ""):
            return float(link["unit_price"])
    for link in mine:
        it = by_code.get(str(link.get("supplier_code") or "").upper())
        if it and it.get("purchase_price") not in (None, ""):
            return float(it["purchase_price"])
    for it in items or []:
        if str(it.get("stock_item_id") or "") == sid and \
                it.get("purchase_price") not in (None, ""):
            return float(it["purchase_price"])
    return None


def price_text(price: Optional[float], unit: Any) -> str:
    """"$18.50 ex GST / roll", or that there is no price yet."""
    if price is None:
        return "No price yet"
    return f"${price:,.2f} ex GST / {unit_label(unit, 1)}"


def stock_state(stock: Dict[str, Any]) -> str:
    """"out", "low" or "ok" - the same test as the list it replaces."""
    try:
        held = float(stock.get("stock_on_hand") or 0)
        least = float(stock.get("minimum_on_hand") or 0)
    except (TypeError, ValueError):
        return "ok"
    if held <= 0:
        return "out"
    if least > 0 and held < least:
        return "low"
    return "ok"
