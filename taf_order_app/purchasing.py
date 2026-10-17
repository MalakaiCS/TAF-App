"""Buying: suppliers, their items, and purchase orders sent through Xero.

Suppliers and items come from Xero (pulled by the xero function into the
suppliers and xero_items tables, migrate_purchasing.sql). Somebody on the
floor asks for several things at once on Order Supplies, naming who it comes
from if they know; a manager turns the requests into a purchase order for a
supplier, which goes to Xero and is emailed to them; what arrives is ticked
off line by line and goes into stock.

Prices come from Xero - what we pay for an item. Channel is bought in many
sizes and not every size has a code, so a size with none is estimated from
the sizes either side of it (FDG-C45 and FDG-C50 price a FDG-C47), and says
so on the order.

The estimating is pure and tested on its own; the rest talks to the
database.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import db as _db

PO_STATUSES = {"draft": "Draft", "sent": "Sent", "part_received": "Part received",
               "received": "Received", "cancelled": "Cancelled"}


# ── Estimating a price from the sizes either side ────────────────────────────

_TOKENS = re.compile(r"\d+(?:\.\d+)?|[A-Za-z]+|[^A-Za-z\d]+")


def _split(code: str) -> Tuple[Tuple[str, ...], List[float]]:
    """("FDG", "-", "C", "#", "-", "#"), [45, 2440] for "FDG-C45-2440": the
    code's shape with its numbers taken out, and the numbers."""
    shape, nums = [], []
    for tok in _TOKENS.findall(str(code or "").strip().upper()):
        if tok[0].isdigit():
            shape.append("#")
            nums.append(float(tok))
        else:
            shape.append(tok)
    return tuple(shape), nums


def _number_text(x: float) -> str:
    return str(int(x)) if x == int(x) else f"{x:g}"


def estimate_price(code: str, prices: Dict[str, float]
                   ) -> Tuple[Optional[float], str]:
    """What `code` should cost, from codes that differ from it in one size.

    (price, how) - how says which codes it came from, for the order. A code
    that has a price is that price. Between two sizes the price is read off
    the line between them; past the end, off the last two; with only one
    neighbour, in proportion to the size. (None, "") when nothing is near
    enough to say.
    """
    code = str(code or "").strip().upper()
    known = {str(k).strip().upper(): float(v) for k, v in (prices or {}).items()
             if v not in (None, "")}
    if code in known:
        return known[code], ""
    shape, nums = _split(code)
    if not nums:
        return None, ""
    best: Optional[Tuple[int, List[Tuple[float, float, str]]]] = None
    for pos in range(len(nums)):
        points = []
        for other, price in known.items():
            o_shape, o_nums = _split(other)
            if o_shape != shape or len(o_nums) != len(nums):
                continue
            if all(o_nums[i] == nums[i] for i in range(len(nums)) if i != pos) \
                    and o_nums[pos] != nums[pos] and price > 0:
                points.append((o_nums[pos], price, other))
        if points and (best is None or len(points) > len(best[1])):
            best = (pos, points)
    if not best:
        return None, ""
    pos, points = best
    x = nums[pos]
    points.sort()
    below = [p for p in points if p[0] < x]
    above = [p for p in points if p[0] > x]
    if below and above:
        a, b = below[-1], above[0]
    elif len(points) >= 2:
        a, b = (points[-2], points[-1]) if below else (points[0], points[1])
    else:
        a = points[0]
        price = round(a[1] * x / a[0], 2) if a[0] else None
        return price, f"estimated from {a[2]}"
    price = a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0])
    return round(max(price, 0.0), 2), f"estimated from {a[2]} and {b[2]}"


def size_in(text: str) -> Optional[float]:
    """The first size in a request's wording: "45mm channel" -> 45."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:mm)?", str(text or ""))
    return float(m.group(1)) if m else None


def guess_line(detail: str, items: Sequence[Dict[str, Any]],
               supplier_id: str = "") -> Dict[str, Any]:
    """An item code and price for a request like "Channel 47mm" from a
    supplier: the item of theirs with that size in its code, or - with no
    such code - a code made from the sizes either side, priced between them.
    {"item_code", "unit_price", "estimated": how} or {} when nothing fits.

    Only with a supplier: without one there is no telling whose codes to
    use, and somebody picks."""
    size = size_in(detail)
    theirs = [it for it in items or []
              if supplier_id and str(it.get("supplier_id") or "") == str(supplier_id)]
    if size is None or not theirs:
        return {}
    for it in theirs:
        _shape, nums = _split(it.get("code") or "")
        if size in nums:
            price = it.get("purchase_price")
            return {"item_code": it["code"],
                    "unit_price": float(price) if price not in (None, "") else None,
                    "estimated": ""}
    prices = {it["code"]: it.get("purchase_price") for it in theirs
              if it.get("purchase_price") not in (None, "")}
    # The size goes where the neighbours' sizes are: the number in their
    # codes that brackets it (or is nearest to it).
    best = None
    for it in theirs:
        shape, nums = _split(it["code"])
        for pos, value in enumerate(nums):
            gap = abs(value - size)
            if best is None or gap < best[0]:
                best = (gap, it["code"], pos)
    # A 47 is made from a 45; a 47 is not made from a 9mm flyscreen.
    if best is None or best[0] > size * 0.5:
        return {}
    _gap, near, pos = best
    tokens = _TOKENS.findall(near.upper())
    count = -1
    for i, tok in enumerate(tokens):
        if tok[0].isdigit():
            count += 1
            if count == pos:
                tokens[i] = _number_text(size)
                break
    code = "".join(tokens)
    price, how = estimate_price(code, prices)
    if price is None:
        return {}
    return {"item_code": code, "unit_price": price, "estimated": how}


# ── Orders ───────────────────────────────────────────────────────────────────

def po_total(lines: Iterable[Dict[str, Any]]) -> float:
    total = 0.0
    for l in lines or []:
        try:
            total += float(l.get("quantity") or 0) * float(l.get("unit_price") or 0)
        except (TypeError, ValueError):
            continue
    return round(total, 2)


def outstanding(line: Dict[str, Any]) -> float:
    """How many of a line are still to come."""
    try:
        return max(0.0, float(line.get("quantity") or 0)
                   - float(line.get("received") or 0))
    except (TypeError, ValueError):
        return 0.0


def _quantity(text: Any) -> float:
    m = re.search(r"\d+(?:\.\d+)?", str(text or ""))
    return float(m.group(0)) if m else 1.0


# ── Where each stock item comes from ─────────────────────────────────────────

def stock_for(category: str, stock_items: Sequence[Dict[str, Any]]
              ) -> List[Dict[str, Any]]:
    """The stock items to offer under "Channel", "Tape" and so on: those of
    that product type, or with the word in their name. "Other" - and a word
    nothing matches - offers everything."""
    word = str(category or "").strip().lower()
    rows = sorted(stock_items or [], key=lambda r: str(r.get("name") or "").lower())
    if not word or word == "other":
        return rows
    hits = [r for r in rows
            if str(r.get("product_type") or "").strip().lower() == word
            or word in str(r.get("name") or "").lower()
            or word.rstrip("s") in str(r.get("name") or "").lower()]
    return hits or rows


def suppliers_for(stock_item_id: str, links: Sequence[Dict[str, Any]]
                  ) -> List[Dict[str, Any]]:
    """Who a stock item comes from, the preferred one first."""
    mine = [l for l in links or []
            if str(l.get("stock_item_id")) == str(stock_item_id)]
    return sorted(mine, key=lambda l: (not l.get("preferred"),
                                       str(l.get("supplier_code") or "")))


def link_for(stock_item_id: str, supplier_id: str,
             links: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The supplier's code and price for a stock item, if they sell it."""
    for l in links or []:
        if str(l.get("stock_item_id")) == str(stock_item_id) and \
                str(l.get("supplier_id")) == str(supplier_id):
            return l
    return None


def stock_line(stock: Dict[str, Any], link: Optional[Dict[str, Any]],
               items: Sequence[Dict[str, Any]], quantity: float) -> Dict[str, Any]:
    """A purchase order line for a stock item from one supplier: their code,
    the price agreed with them (or what Xero says we pay for that code), and
    the stock item it goes into when it arrives."""
    code = str((link or {}).get("supplier_code") or "").strip()
    xero = next((it for it in items or []
                 if code and str(it.get("code") or "").upper() == code.upper()), {})
    price = (link or {}).get("unit_price")
    if price in (None, ""):
        price = xero.get("purchase_price")
    return {
        "description": (xero.get("purchase_description") or xero.get("name")
                        or stock.get("name") or "Item"),
        "quantity": quantity, "item_code": code,
        "unit_price": None if price in (None, "") else float(price),
        "stock_item_id": stock.get("id"), "received": 0,
    }


def shortfall(stock: Dict[str, Any], on_order: float = 0.0) -> float:
    """How many to buy to get back to the minimum - what is already on order
    counted - in whole units. 0 when there is enough."""
    try:
        want = float(stock.get("minimum_on_hand") or 0)
        held = float(stock.get("stock_on_hand") or 0)
    except (TypeError, ValueError):
        return 0.0
    if want <= 0:
        return 0.0
    return float(max(0, math.ceil(want - held - (on_order or 0))))


def low_stock_orders(stock_items: Sequence[Dict[str, Any]],
                     links: Sequence[Dict[str, Any]],
                     items: Sequence[Dict[str, Any]] = (),
                     on_order: Optional[Dict[str, float]] = None
                     ) -> Dict[str, List[Dict[str, Any]]]:
    """{supplier id: [lines]} - everything below its minimum, from its
    preferred supplier (or the only one), ready to send. Stock with nowhere
    to buy it from is under ""."""
    on_order = on_order or {}
    out: Dict[str, List[Dict[str, Any]]] = {}
    for stock in stock_items or []:
        need = shortfall(stock, on_order.get(str(stock.get("id")), 0.0))
        if need <= 0:
            continue
        theirs = suppliers_for(str(stock.get("id")), links)
        link = theirs[0] if theirs else None
        out.setdefault(str((link or {}).get("supplier_id") or ""), []).append(
            stock_line(stock, link, items, need))
    return out


def lines_from_requests(requests: Sequence[Dict[str, Any]],
                        items: Sequence[Dict[str, Any]] = (),
                        links: Sequence[Dict[str, Any]] = (),
                        stock_items: Sequence[Dict[str, Any]] = ()
                        ) -> List[Dict[str, Any]]:
    """Purchase order lines for supply requests: what they asked for, how
    many, and - where it can be told - the item code and its price (or an
    estimate from the sizes either side). A request for a stock item takes
    the supplier's code and price for it."""
    by_code = {str(it.get("code") or "").upper(): it for it in items or []}
    stock_by_id = {str(s.get("id")): s for s in stock_items or []}
    out = []
    for r in requests:
        sid = str(r.get("stock_item_id") or "")
        link = link_for(sid, str(r.get("supplier_id") or ""), links) if sid else None
        if sid and (link or sid in stock_by_id):
            stock = stock_by_id.get(sid) or {"id": sid, "name": r.get("detail")}
            line = stock_line(stock, link, items, _quantity(r.get("quantity")))
            line["request_ids"] = [str(r.get("id"))] if r.get("id") else []
            out.append(line)
            continue
        words = " ".join(p for p in (r.get("item"), r.get("detail")) if p)
        line: Dict[str, Any] = {
            "description": words or "Item",
            "quantity": _quantity(r.get("quantity")),
            "unit_price": None, "item_code": str(r.get("item_code") or ""),
            "request_ids": [str(r.get("id"))] if r.get("id") else [],
            "received": 0,
        }
        it = by_code.get(line["item_code"].upper())
        if it:
            line["unit_price"] = it.get("purchase_price")
            line["stock_item_id"] = it.get("stock_item_id")
            line["description"] = (it.get("purchase_description") or it.get("name")
                                   or line["description"])
        else:
            guess = guess_line(r.get("detail") or words, items,
                               str(r.get("supplier_id") or ""))
            if guess:
                line.update(item_code=guess["item_code"],
                            unit_price=guess["unit_price"])
                if guess["estimated"]:
                    line["estimated"] = guess["estimated"]
                hit = by_code.get(guess["item_code"].upper())
                if hit and hit.get("stock_item_id"):
                    line["stock_item_id"] = hit["stock_item_id"]
        out.append(line)
    return out


def group_by_supplier(requests: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """{supplier id or "": [requests]} - one purchase order per supplier."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in requests:
        out.setdefault(str(r.get("supplier_id") or ""), []).append(r)
    return out


# ── The database ─────────────────────────────────────────────────────────────

def ready() -> bool:
    """Whether migrate_purchasing.sql (step 40) has been run."""
    try:
        _db.get_client().table("suppliers").select("id").limit(1).execute()
        return True
    except Exception:
        return False


def list_suppliers(active_only: bool = True) -> List[Dict[str, Any]]:
    q = _db.get_client().table("suppliers").select("*").order("name")
    if active_only:
        q = q.eq("active", True)
    return list(q.execute().data or [])


def save_supplier(supplier_id: str, patch: Dict[str, Any]) -> None:
    _db.get_client().table("suppliers").update(patch).eq("id", supplier_id).execute()


def add_supplier(name: str, email: str = "", code_prefix: str = "") -> Dict[str, Any]:
    resp = _db.get_client().table("suppliers").insert({
        "name": name.strip(), "email": email.strip(),
        "code_prefix": code_prefix.strip().upper()}).execute()
    return (resp.data or [{}])[0]


def list_items(limit: int = 0) -> List[Dict[str, Any]]:
    return _db._page_through(
        lambda: _db.get_client().table("xero_items").select("*").order("code"),
        limit=limit)


def link_item(code: str, **patch) -> None:
    """Which supplier (supplier_id) and stock item (stock_item_id) an item is."""
    _db.get_client().table("xero_items").update(patch).eq("code", code).execute()


def stock_links_ready() -> bool:
    """Whether migrate_stock_suppliers.sql (step 42) has been run."""
    try:
        _db.get_client().table("stock_item_suppliers").select("id").limit(1).execute()
        return True
    except Exception:
        return False


def list_stock_links() -> List[Dict[str, Any]]:
    return _db._page_through(
        lambda: _db.get_client().table("stock_item_suppliers").select("*")
        .order("stock_item_id"))


def save_stock_link(stock_item_id: str, supplier_id: str, supplier_code: str = "",
                    unit_price: Optional[float] = None,
                    preferred: bool = False) -> None:
    """Where a stock item comes from: added, or changed if already there.
    Only one supplier is preferred for each stock item."""
    client = _db.get_client()
    if preferred:
        (client.table("stock_item_suppliers").update({"preferred": False})
         .eq("stock_item_id", stock_item_id).neq("supplier_id", supplier_id)
         .execute())
    client.table("stock_item_suppliers").upsert({
        "stock_item_id": stock_item_id, "supplier_id": supplier_id,
        "supplier_code": (supplier_code or "").strip().upper(),
        "unit_price": unit_price, "preferred": bool(preferred)},
        on_conflict="stock_item_id,supplier_id").execute()


def remove_stock_link(link_id: str) -> None:
    _db.get_client().table("stock_item_suppliers").delete().eq("id", link_id).execute()


def request_supplies(lines: Sequence[Dict[str, Any]], urgent: bool = False,
                     note: str = "", client_ref: Optional[str] = None) -> List[Dict[str, Any]]:
    """Several things asked for at once; managers are told once."""
    import uuid
    from . import supplies as _supplies
    clean = []
    for line in lines:
        row = _supplies.clean_request(line.get("item", ""), line.get("detail", ""),
                                      line.get("quantity", ""))
        row["supplier_id"] = line.get("supplier_id") or ""
        row["item_code"] = line.get("item_code") or ""
        row["stock_item_id"] = line.get("stock_item_id") or ""
        clean.append({k: row[k] for k in ("item", "detail", "quantity",
                                          "supplier_id", "item_code",
                                          "stock_item_id")})
    resp = _db.get_client().rpc("request_supplies", {
        "p_lines": clean, "p_urgent": bool(urgent), "p_note": (note or "")[:500],
        "p_client_ref": client_ref or f"desk-{uuid.uuid4()}"}).execute()
    return list(resp.data or [])


def list_orders(open_only: bool = False) -> List[Dict[str, Any]]:
    q = (_db.get_client().table("purchase_orders").select("*")
         .order("created_at", desc=True).limit(300))
    if open_only:
        q = q.in_("status", ["draft", "sent", "part_received"])
    return list(q.execute().data or [])


def save_order(order: Dict[str, Any]) -> Dict[str, Any]:
    """Create or update a purchase order (a draft until it is sent)."""
    row = {k: order.get(k) for k in ("supplier", "supplier_id", "supplier_email",
                                      "reference", "lines", "note", "expected")
           if k in order}
    row["lines"] = list(order.get("lines") or [])
    if order.get("id"):
        resp = (_db.get_client().table("purchase_orders").update(row)
                .eq("id", order["id"]).execute())
    else:
        row["created_by"] = _db.current_full_name() or _db.current_username() or ""
        resp = _db.get_client().table("purchase_orders").insert(row).execute()
    saved = (resp.data or [{}])[0]
    ids = [rid for line in row["lines"] for rid in (line.get("request_ids") or [])]
    if ids and saved.get("id"):
        (_db.get_client().table("supply_requests")
         .update({"purchase_order_id": saved["id"], "status": "ordered"})
         .in_("id", ids).execute())
    return saved


def cancel_order(po_id: str) -> None:
    _db.get_client().table("purchase_orders").update(
        {"status": "cancelled"}).eq("id", po_id).execute()


def receive(po_id: str, received: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """[{"line": index, "qty": n}] - booked into stock by the database."""
    resp = _db.get_client().rpc("receive_purchase", {
        "p_po": str(po_id), "p_received": list(received)}).execute()
    data = resp.data
    if isinstance(data, list):
        data = data[0] if data else {}
    return data or {}
