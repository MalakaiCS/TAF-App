"""Who is in, and whether a day is already full.

Pure, so it is tested on its own. docs/app/screens.js has the same rules
for a new order raised on the phone - a test holds the two together - and
migrate_planning.sql (step 45) is where the roster and leave are kept.

A day's capacity is the hours of everybody rostered to make filters that
day, less anybody on leave, times the share of a day actually spent making;
nothing on a shutdown day. What is booked on a day is every filter still to
make on the orders due that day, at the minutes the job timer says that
type takes (or the workshop's default until it has been timed).
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .insights import parse_date

DONE = ("Complete", "Dispatched", "Delivered", "Collected")

# Kept in workshop_settings (step 45) next to the calculator's numbers.
SETTINGS = {"minutes_per_filter": 15.0, "making_share": 0.8}
LEAVE_KINDS = [("annual", "Annual leave"), ("sick", "Sick"),
               ("training", "Training"), ("other", "Other")]
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _day(value: Any) -> Optional[_dt.date]:
    if isinstance(value, _dt.date):
        return value
    return parse_date(value)


def rate_map(rates: Iterable[Dict[str, Any]]) -> Dict[str, float]:
    """{filter type, lower case: minutes a filter} from job_rates."""
    out: Dict[str, float] = {}
    for r in rates or []:
        m = _num(r.get("minutes_each"))
        if m > 0:
            out[str(r.get("filter_type") or "").strip().lower()] = m
    return out


def line_minutes(item: Dict[str, Any], rates: Dict[str, float],
                 default: float) -> float:
    """A line's minutes: how many, at the minutes its type takes. A line
    already made takes none; a bought-in (catalogue) line takes none."""
    if item.get("made"):
        return 0.0
    if str(item.get("item_kind") or "filter") == "catalogue":
        return 0.0
    qty = _num(item.get("Quantity", item.get("quantity")))
    kind = str(item.get("Filter Type") or item.get("product_type") or "").strip().lower()
    return max(0.0, qty) * rates.get(kind, default)


def order_minutes(items: Iterable[Dict[str, Any]], rates: Dict[str, float],
                  default: float) -> float:
    return sum(line_minutes(i, rates, default) for i in items or []
               if isinstance(i, dict))


def booked_minutes(orders: Iterable[Dict[str, Any]], day: _dt.date,
                   rates: Dict[str, float], default: float,
                   skip_id: Any = None) -> float:
    """What is still to make on the orders due on `day`."""
    total = 0.0
    for o in orders or []:
        head = o.get("header") if isinstance(o.get("header"), dict) else {}
        status = str(head.get("status") or o.get("status") or "Pending")
        if status in DONE or o.get("archived"):
            continue
        if skip_id is not None and str(o.get("id")) == str(skip_id):
            continue
        if _day(o.get("date_due")) != day:
            continue
        total += order_minutes(o.get("items") or [], rates, default)
    return total


def on_leave(person: str, day: _dt.date, leave: Iterable[Dict[str, Any]]) -> bool:
    for l in leave or []:
        if str(l.get("person") or "").strip().lower() != str(person).strip().lower():
            continue
        first, last = _day(l.get("first_day")), _day(l.get("last_day"))
        if first and last and first <= day <= last:
            return True
    return False


def shut_on(day: _dt.date, shutdowns: Iterable[Dict[str, Any]]) -> str:
    """The name of the shutdown on `day` ("Christmas"), or ""."""
    for s in shutdowns or []:
        if _day(s.get("day")) == day:
            return str(s.get("name") or "Shut")
    return ""


def available(day: _dt.date, roster: Iterable[Dict[str, Any]],
              leave: Iterable[Dict[str, Any]], shutdowns: Iterable[Dict[str, Any]],
              share: float) -> Dict[str, Any]:
    """{"minutes", "in": [names], "away": [names], "shut": ""} for a day."""
    shut = shut_on(day, shutdowns)
    people_in, away, minutes = [], [], 0.0
    iso = day.isoweekday()
    for r in roster or []:
        if not r.get("makes", True) or not r.get("active", True):
            continue
        days = [int(d) for d in (r.get("days") or [])]
        if iso not in days:
            continue
        name = str(r.get("person") or "")
        if on_leave(name, day, leave):
            away.append(name)
            continue
        people_in.append(name)
        minutes += _num(r.get("hours")) * 60.0 * share
    if shut:
        minutes = 0.0
    return {"minutes": minutes, "in": people_in, "away": away, "shut": shut}


def check_due(day: Any, items: Iterable[Dict[str, Any]],
              orders: Iterable[Dict[str, Any]], rates: Iterable[Dict[str, Any]],
              roster: Iterable[Dict[str, Any]], leave: Iterable[Dict[str, Any]],
              shutdowns: Iterable[Dict[str, Any]], workshop: Dict[str, Any],
              skip_id: Any = None, look_ahead: int = 15) -> Optional[Dict[str, Any]]:
    """Whether a new order due on `day` fits. None when there is nothing to
    say: no date (ASAP), or no roster to measure against."""
    due = _day(day)
    roster = [r for r in roster or [] if r.get("makes", True) and r.get("active", True)]
    if due is None or not roster:
        return None
    by_type = rate_map(rates)
    default = _num(workshop.get("minutes_per_filter"), 15.0) or 15.0
    share = _num(workshop.get("making_share"), 0.8) or 0.8
    orders = list(orders or [])
    need = order_minutes(items, by_type, default)

    def _on(d):
        room = available(d, roster, leave, shutdowns, share)
        room["booked"] = booked_minutes(orders, d, by_type, default, skip_id)
        return room

    here = _on(due)
    full = here["booked"] + need > here["minutes"]
    nxt = None
    if full:
        d = due
        for _ in range(look_ahead):
            d += _dt.timedelta(days=1)
            room = _on(d)
            if room["minutes"] and room["booked"] + need <= room["minutes"]:
                nxt = d
                break
    return {"day": due, "need": need, "booked": here["booked"],
            "minutes": here["minutes"], "in": here["in"], "away": here["away"],
            "shut": here["shut"], "full": full, "next_free": nxt}


def hours(minutes: float) -> str:
    """"7.5 h", "12 h"."""
    h = round(float(minutes) / 60.0, 1)
    return f"{h:g} h"


def describe(result: Dict[str, Any]) -> str:
    """What to say about a day that is full."""
    day = result["day"]
    name = day.strftime("%A %d/%m")
    if result["shut"]:
        head = f"{name} is a shutdown day ({result['shut']})."
    elif not result["minutes"]:
        head = f"Nobody is rostered to make filters on {name}."
    else:
        head = (f"{name} is already full: {hours(result['booked'])} booked, and "
                f"this order adds {hours(result['need'])}, against "
                f"{hours(result['minutes'])} with {len(result['in'])} in")
        head += (f" ({', '.join(result['away'])} away)." if result["away"] else ".")
    if result["next_free"]:
        head += f" {result['next_free'].strftime('%A %d/%m')} has room."
    return head


def week_view(start: _dt.date, orders, rates, roster, leave, shutdowns,
              workshop, days: int = 10) -> List[Dict[str, Any]]:
    """Each working day ahead: who is in and away, hours available and
    booked - the roster window's "how the next fortnight looks"."""
    by_type = rate_map(rates)
    default = _num(workshop.get("minutes_per_filter"), 15.0) or 15.0
    share = _num(workshop.get("making_share"), 0.8) or 0.8
    out = []
    d = start
    while len(out) < days:
        if d.isoweekday() <= 5 or any(d.isoweekday() in (r.get("days") or [])
                                      for r in roster or []):
            room = available(d, roster, leave, shutdowns, share)
            room["day"] = d
            room["booked"] = booked_minutes(orders, d, by_type, default)
            out.append(room)
        d += _dt.timedelta(days=1)
    return out


def parse_days(text: str) -> List[int]:
    """"Mon-Fri", "Mon Wed Fri", "1,2,3" -> ISO weekday numbers."""
    s = str(text or "").strip().lower()
    names = [n.lower() for n in DAY_NAMES]
    out: List[int] = []
    for part in s.replace(",", " ").split():
        if "-" in part:
            a, b = part.split("-", 1)
            ia = names.index(a[:3]) + 1 if a[:3] in names else int(a or 0)
            ib = names.index(b[:3]) + 1 if b[:3] in names else int(b or 0)
            out.extend(range(ia, ib + 1))
        elif part[:3] in names:
            out.append(names.index(part[:3]) + 1)
        elif part.isdigit():
            out.append(int(part))
    return sorted({d for d in out if 1 <= d <= 7})


def days_text(days: Sequence[int]) -> str:
    """[1,2,3,4,5] -> "Mon-Fri"; [1,3,5] -> "Mon Wed Fri"."""
    ds = sorted({int(d) for d in days or [] if 1 <= int(d) <= 7})
    if not ds:
        return ""
    if len(ds) > 2 and ds == list(range(ds[0], ds[-1] + 1)):
        return f"{DAY_NAMES[ds[0] - 1]}-{DAY_NAMES[ds[-1] - 1]}"
    return " ".join(DAY_NAMES[d - 1] for d in ds)


def repeat_items(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """An order's lines, ready to go on a new order: nothing made or
    checked, and no old line id (the new order gives each its own)."""
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        fresh = {k: v for k, v in it.items()
                 if not (k.startswith("made") or k in ("qc", "line_id"))}
        out.append(fresh)
    return out
