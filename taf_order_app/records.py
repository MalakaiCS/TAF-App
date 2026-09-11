"""The seven things that needed a table of their own.

Kits, sites, returns, stocktakes, purchase orders, agreed prices and the
shutdown calendar. Kept out of db.py because db.py is already the biggest
file in the project and these are all the same shape: read a list, write a
row, mark something done.

Nothing here decides who may do what. Every one of these tables has
row-level security on it, and a helper that returned an empty list because
the database refused is telling the truth about what this account can see.
The one thing they all do is fail quietly on read and loudly on write: a
screen that cannot load is an inconvenience, and a write that silently did
not happen is a lie.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Sequence

from . import db as _db


def _who() -> str:
    try:
        return _db.current_full_name() or _db.current_username()
    except Exception:
        return ""


def _rows(table: str, shape=None, limit: int = 500) -> List[Dict[str, Any]]:
    try:
        q = _db.get_client().table(table).select("*").limit(limit)
        if shape:
            q = shape(q)
        return q.execute().data or []
    except Exception:
        return []


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# ── Kits ─────────────────────────────────────────────────────────────────────
# An AHU that takes four panels and two bags is six lines typed every time,
# and six chances to leave one out.

def list_kits(active_only: bool = True) -> List[Dict[str, Any]]:
    return _rows("kits", lambda q: (q.eq("active", True) if active_only else q)
                 .order("name"))


def save_kit(name: str, lines: Sequence[Dict[str, Any]], note: str = "",
             kit_id: str = "") -> Dict[str, Any]:
    name = str(name or "").strip()
    if not name:
        raise ValueError("A kit needs a name to be found by.")
    if not lines:
        raise ValueError("A kit with no lines in it would add nothing to an "
                         "order.")
    row = {"name": name, "note": str(note or "").strip(),
           "lines": list(lines)}
    client = _db.get_client()
    if kit_id:
        resp = client.table("kits").update(row).eq("id", str(kit_id)).execute()
    else:
        row["created_by"] = _who()
        resp = client.table("kits").insert(row).execute()
    out = resp.data or []
    return out[0] if out else {}


def retire_kit(kit_id: str) -> None:
    """Off the list without deleting it. An order raised from a kit last
    year should still be explainable."""
    _db.get_client().table("kits").update({"active": False}).eq(
        "id", str(kit_id)).execute()


# ── What is installed where ──────────────────────────────────────────────────

def list_sites(customer_name: str = "") -> List[Dict[str, Any]]:
    def shape(q):
        q = q.eq("active", True).order("customer_name").order("name")
        return q
    rows = _rows("sites", shape)
    if customer_name:
        wanted = str(customer_name).strip().lower()
        rows = [r for r in rows
                if str(r.get("customer_name") or "").strip().lower() == wanted]
    return rows


def save_site(name: str, customer_name: str = "", location: str = "",
              filters: Sequence[Dict[str, Any]] = (), note: str = "",
              every_months: int = 0, site_id: str = "") -> Dict[str, Any]:
    name = str(name or "").strip()
    if not name:
        raise ValueError("A site needs a name - the plant room, the roof, "
                         "whatever it is called on site.")
    row = {
        "name": name,
        "customer_name": str(customer_name or "").strip(),
        "location": str(location or "").strip(),
        "note": str(note or "").strip(),
        "filters": list(filters),
        "every_months": max(0, int(every_months or 0)),
    }
    client = _db.get_client()
    if site_id:
        resp = client.table("sites").update(row).eq("id", str(site_id)).execute()
    else:
        row["created_by"] = _who()
        resp = client.table("sites").insert(row).execute()
    out = resp.data or []
    return out[0] if out else {}


def site_done(site_id: str, when: _dt.date | None = None) -> None:
    _db.get_client().table("sites").update(
        {"last_done": (when or _dt.date.today()).isoformat()}
    ).eq("id", str(site_id)).execute()


def sites_due(rows: Sequence[Dict[str, Any]] = (),
              today: _dt.date | None = None) -> List[Dict[str, Any]]:
    """Sites whose cycle has come round.

    A site with no cycle set is never due: a blank interval means nobody has
    decided, and inventing one would put work on somebody's list that nobody
    agreed to.
    """
    today = today or _dt.date.today()
    out = []
    for row in (rows or list_sites()):
        months = int(row.get("every_months") or 0)
        if months <= 0:
            continue
        last = row.get("last_done")
        if not last:
            out.append(dict(row, due=None, overdue_days=None))
            continue
        try:
            when = _dt.date.fromisoformat(str(last)[:10])
        except ValueError:
            continue
        due = _db.add_months(when, months)
        if due <= today:
            out.append(dict(row, due=due, overdue_days=(today - due).days))
    out.sort(key=lambda r: (r["due"] is not None, r.get("due") or _dt.date.min))
    return out


# ── A filter that came back ──────────────────────────────────────────────────

REASONS = ["Wrong size", "Wrong media", "Damaged in transit",
           "Made wrong", "Customer changed their mind", "Failed early",
           "Other"]


def list_returns(open_only: bool = False) -> List[Dict[str, Any]]:
    def shape(q):
        q = q.order("created_at", desc=True)
        return q.eq("outcome", "open") if open_only else q
    return _rows("returns", shape)


def log_return(order_number: str, customer_name: str, quantity: float,
               reason: str, detail: str = "",
               order_id: str = "") -> Dict[str, Any]:
    if float(quantity) <= 0:
        raise ValueError("How many came back? It has to be more than none.")
    if not str(reason or "").strip():
        raise ValueError("Why it came back is the whole point of writing it "
                         "down.")
    row = {
        "order_number": str(order_number or "").strip(),
        "customer_name": str(customer_name or "").strip(),
        "quantity": float(quantity),
        "reason": str(reason).strip(),
        "detail": str(detail or "").strip(),
        "created_by": _who(),
    }
    if order_id:
        row["order_id"] = str(order_id)
    resp = _db.get_client().table("returns").insert(row).execute()
    out = resp.data or []
    return out[0] if out else {}


def close_return(return_id: str, outcome: str) -> None:
    outcome = str(outcome or "").strip().lower()
    if outcome not in ("remade", "credited", "no fault", "scrapped"):
        raise ValueError(f"{outcome!r} is not one of the ways a return ends.")
    _db.get_client().table("returns").update({
        "outcome": outcome,
        "closed_at": _now(),
        "closed_by": _who(),
    }).eq("id", str(return_id)).execute()


def returns_pattern(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """What comes back, and from where. One return is bad luck; the same
    reason from the same customer four times is something to go and look at."""
    per: Dict[Any, Dict[str, Any]] = {}
    for row in rows or []:
        key = (str(row.get("customer_name") or "—"),
               str(row.get("reason") or "—"))
        b = per.setdefault(key, {"customer": key[0], "reason": key[1],
                                 "times": 0, "filters": 0.0})
        b["times"] += 1
        try:
            b["filters"] += float(row.get("quantity") or 0)
        except (TypeError, ValueError):
            pass
    return sorted(per.values(), key=lambda b: (-b["times"], -b["filters"]))


# ── Counting a rack ──────────────────────────────────────────────────────────

def open_stocktake() -> Dict[str, Any]:
    """The session somebody is part way through, if there is one."""
    rows = _rows("stocktakes",
                 lambda q: q.is_("finished_at", "null")
                 .order("started_at", desc=True).limit(1))
    return rows[0] if rows else {}


def start_stocktake(name: str = "") -> Dict[str, Any]:
    already = open_stocktake()
    if already:
        raise ValueError(
            f"There is already a count going ({already.get('name') or 'unnamed'}"
            f"). Finish that one first, or two people will count the same "
            f"rack into two different sessions.")
    resp = _db.get_client().table("stocktakes").insert({
        "name": str(name or "").strip() or _dt.date.today().isoformat(),
        "started_by": _who(),
    }).execute()
    out = resp.data or []
    return out[0] if out else {}


def count_item(stocktake_id: str, item_id: str, counted: float,
               was: float = 0) -> None:
    """Write down what is on the shelf. Counting the same rack twice happens;
    the second count is the one that stands."""
    if float(counted) < 0:
        raise ValueError("A count cannot be less than nothing.")
    _db.get_client().table("stocktake_counts").upsert({
        "stocktake_id": str(stocktake_id),
        "item_id": str(item_id),
        "counted": float(counted),
        "was": float(was or 0),
        "counted_at": _now(),
        "counted_by": _who(),
    }, on_conflict="stocktake_id,item_id").execute()


def stocktake_counts(stocktake_id: str) -> List[Dict[str, Any]]:
    return _rows("stocktake_counts",
                 lambda q: q.eq("stocktake_id", str(stocktake_id))
                 .order("counted_at"), limit=2000)


def stocktake_progress(stocktake_id: str, items: Sequence[Dict[str, Any]]):
    """What has been counted, what has not, and where the figures disagree."""
    counts = {str(c.get("item_id")): c for c in stocktake_counts(stocktake_id)}
    done, todo, out_by = [], [], []
    for item in items or []:
        got = counts.get(str(item.get("id")))
        if not got:
            todo.append(item)
            continue
        try:
            counted = float(got.get("counted") or 0)
            was = float(got.get("was") or 0)
        except (TypeError, ValueError):
            continue
        row = dict(item, counted=counted, was=was, out_by=counted - was,
                   counted_by=got.get("counted_by") or "")
        done.append(row)
        if abs(counted - was) > 1e-9:
            out_by.append(row)
    out_by.sort(key=lambda r: -abs(r["out_by"]))
    return {"counted": done, "not_counted": todo, "out_by": out_by,
            "total": len(items or [])}


def finish_stocktake(stocktake_id: str, apply: bool = False) -> Dict[str, Any]:
    """Close it, and optionally turn every variance into a real movement.

    Applying goes through adjust_stock_atomic with a reference built from the
    session and the item, so a session applied twice by two people is applied
    once - the same guarantee a scanning gun gets.
    """
    moved = []
    if apply:
        resp = _db.get_client().rpc(
            "apply_stocktake", {"p_stocktake": str(stocktake_id)}).execute()
        moved = resp.data or []
    _db.get_client().table("stocktakes").update({
        "finished_at": _now(), "finished_by": _who(),
    }).eq("id", str(stocktake_id)).execute()
    return {"moved": moved,
            "applied": sum(1 for m in moved if m.get("applied"))}


# ── Buying ───────────────────────────────────────────────────────────────────

def list_purchases(open_only: bool = False) -> List[Dict[str, Any]]:
    def shape(q):
        q = q.order("created_at", desc=True)
        return q.neq("status", "received") if open_only else q
    return _rows("purchase_orders", shape)


def draft_purchase(supplier: str, lines: Sequence[Dict[str, Any]],
                   supplier_email: str = "", note: str = "",
                   reference: str = "") -> Dict[str, Any]:
    if not str(supplier or "").strip():
        raise ValueError("Who is it going to?")
    if not lines:
        raise ValueError("A purchase order with nothing on it is not an "
                         "order.")
    resp = _db.get_client().table("purchase_orders").insert({
        "supplier": str(supplier).strip(),
        "supplier_email": str(supplier_email or "").strip(),
        "reference": str(reference or "").strip(),
        "lines": list(lines),
        "note": str(note or "").strip(),
        "created_by": _who(),
    }).execute()
    out = resp.data or []
    return out[0] if out else {}


def purchase_from_low_stock(items: Sequence[Dict[str, Any]],
                            on_order: Dict[str, float] | None = None
                            ) -> List[Dict[str, Any]]:
    """Low-stock items grouped into one draft per supplier.

    What is already on order is taken off the shortfall. Without that, every
    look at the screen raises the same purchase order again, and the same
    roll gets bought three times.
    """
    on_order = on_order or {}
    per: Dict[str, Dict[str, Any]] = {}
    for item in items or []:
        try:
            held = float(item.get("stock_on_hand") or 0)
            want = float(item.get("minimum_on_hand") or 0)
        except (TypeError, ValueError):
            continue
        if want <= 0:
            continue
        coming = float(on_order.get(str(item.get("id")), 0))
        short = want - held - coming
        if short <= 0:
            continue
        supplier = str(item.get("supplier") or "").strip() or "Not set"
        draft = per.setdefault(supplier, {
            "supplier": supplier,
            "supplier_email": str(item.get("supplier_email") or "").strip(),
            "lines": []})
        draft["lines"].append({
            "item_id": str(item.get("id") or ""),
            "name": str(item.get("name") or ""),
            "sku": str(item.get("sku") or ""),
            "unit": str(item.get("unit") or ""),
            "on_hand": held,
            "minimum": want,
            "on_order": coming,
            "quantity": round(short, 3),
        })
    return sorted(per.values(), key=lambda d: d["supplier"].lower())


def quantities_on_order(rows: Sequence[Dict[str, Any]] = ()
                        ) -> Dict[str, float]:
    """{stock item id: how much is on a purchase order but not yet here}."""
    out: Dict[str, float] = {}
    for po in (rows if rows else list_purchases(open_only=True)):
        if str(po.get("status") or "") in ("received", "cancelled"):
            continue
        for line in (po.get("lines") or []):
            if not isinstance(line, dict):
                continue
            key = str(line.get("item_id") or "")
            if not key:
                continue
            try:
                out[key] = out.get(key, 0.0) + float(line.get("quantity") or 0)
            except (TypeError, ValueError):
                continue
    return out


def mark_purchase(po_id: str, status: str) -> None:
    status = str(status or "").strip().lower()
    if status not in ("draft", "sent", "received", "cancelled"):
        raise ValueError(f"{status!r} is not a state a purchase order is in.")
    patch: Dict[str, Any] = {"status": status}
    if status == "sent":
        patch["sent_at"] = _now()
    if status == "received":
        patch["received_at"] = _now()
    _db.get_client().table("purchase_orders").update(patch).eq(
        "id", str(po_id)).execute()


# ── What a particular customer pays ──────────────────────────────────────────

def list_customer_prices(customer_id: str = "") -> List[Dict[str, Any]]:
    def shape(q):
        q = q.order("part_number")
        return q.eq("customer_id", str(customer_id)) if customer_id else q
    return _rows("customer_prices", shape, limit=2000)


def set_customer_price(customer_id: str, part_number: str = "",
                       unit_price: float | None = None,
                       discount: float | None = None,
                       note: str = "") -> Dict[str, Any]:
    """A price, or a percentage off, for one customer.

    A blank part number is their across-the-board discount. One of the two
    has to be given: a row that is neither a price nor a discount says
    nothing and would quietly override the list price with nothing.
    """
    if unit_price is None and discount is None:
        raise ValueError("Give either a price or a discount.")
    if unit_price is not None and float(unit_price) < 0:
        raise ValueError("A price cannot be less than nothing.")
    if discount is not None and not (0 <= float(discount) < 100):
        raise ValueError("A discount is a percentage between 0 and 100.")
    row = {
        "customer_id": str(customer_id),
        "part_number": str(part_number or "").strip().upper(),
        "unit_price": None if unit_price is None else float(unit_price),
        "discount": None if discount is None else float(discount),
        "note": str(note or "").strip(),
        "created_by": _who(),
    }
    resp = _db.get_client().table("customer_prices").upsert(
        row, on_conflict="customer_id,part_number").execute()
    out = resp.data or []
    return out[0] if out else {}


def price_for(part_number: str, list_price: float,
              agreed: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """What this customer pays for this part.

    A price against the exact part number wins over an across-the-board
    discount, because the specific thing somebody agreed beats the general
    thing they agreed earlier. Nothing agreed means the list price, and that
    is said rather than left to be assumed.
    """
    part = str(part_number or "").strip().upper()
    exact = general = None
    for row in agreed or []:
        code = str(row.get("part_number") or "").strip().upper()
        if code == part and part:
            exact = row
        elif not code:
            general = row
    for row, why in ((exact, "agreed for this part"),
                     (general, "this customer's discount")):
        if not row:
            continue
        if row.get("unit_price") is not None:
            return {"price": round(float(row["unit_price"]), 2),
                    "why": why, "list": list_price}
        if row.get("discount") is not None:
            off = float(row["discount"])
            return {"price": round(float(list_price) * (1 - off / 100.0), 2),
                    "why": f"{off:g}% off, {why}", "list": list_price}
    return {"price": round(float(list_price), 2), "why": "list price",
            "list": list_price}


# ── Days that do not exist ───────────────────────────────────────────────────

def shutdown_days(year: int | None = None) -> List[Dict[str, Any]]:
    rows = _rows("shutdown_days", lambda q: q.order("day"), limit=2000)
    if year:
        rows = [r for r in rows if str(r.get("day", "")).startswith(str(year))]
    return rows


def add_shutdown(day: _dt.date, name: str = "") -> None:
    _db.get_client().table("shutdown_days").upsert({
        "day": day.isoformat(),
        "name": str(name or "").strip(),
        "created_by": _who(),
    }, on_conflict="day").execute()


def remove_shutdown(day: _dt.date) -> None:
    _db.get_client().table("shutdown_days").delete().eq(
        "day", day.isoformat()).execute()


def next_working_day(day: _dt.date, closed: Sequence[Any] = ()) -> _dt.date:
    """The first day on or after this one that the place is open.

    Weekends and anything on the shutdown calendar. A due date that lands on
    Boxing Day was never going to be met, and moving it forward quietly is
    worse than moving it and saying so - which is why this returns the day
    and the caller does the saying.
    """
    shut = set()
    for entry in closed or []:
        raw = entry.get("day") if isinstance(entry, dict) else entry
        if isinstance(raw, _dt.date):
            shut.add(raw)
            continue
        try:
            shut.add(_dt.date.fromisoformat(str(raw)[:10]))
        except (TypeError, ValueError):
            continue
    out = day
    for _ in range(400):           # a year and a bit is more than enough
        if out.weekday() < 5 and out not in shut:
            return out
        out += _dt.timedelta(days=1)
    return out


def working_days_between(start: _dt.date, end: _dt.date,
                         closed: Sequence[Any] = ()) -> int:
    """How many days there actually are to do it in."""
    if end < start:
        return 0
    days, cursor = 0, start
    while cursor <= end:
        if next_working_day(cursor, closed) == cursor:
            days += 1
        cursor += _dt.timedelta(days=1)
    return days
