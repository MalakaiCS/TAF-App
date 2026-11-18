"""Reading what is already there.

Four of the thirty need no new table and no new field: the answers are
already in the orders, and nobody has ever put them side by side. Everything
here is a pure function over rows so it can be tested without a database and
without a screen - the screens are thin, and the arithmetic is what has to be
right.

One rule throughout: a row that cannot be read is skipped and counted, never
guessed at. A capacity figure that quietly dropped the four orders it could
not parse is worse than one that says "and four I could not read".
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Sequence, Tuple

DONE = ("Complete", "Dispatched", "Delivered", "Collected")


# ── Dates people typed ───────────────────────────────────────────────────────

def parse_date(text: Any) -> _dt.date | None:
    """dd/mm/yyyy, dd/mm/yy, yyyy-mm-dd, or nothing.

    The same shapes the rest of the app accepts, because a due date is text
    somebody typed and "ASAP" is a perfectly normal thing to find in it.
    """
    s = str(text or "").strip()
    if not s or s.lower() == "asap":
        return None
    for pattern in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return _dt.datetime.strptime(s, pattern).date()
        except ValueError:
            continue
    # An ISO timestamp, which is what created_at is.
    try:
        return _dt.datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _status(row: Dict[str, Any]) -> str:
    header = row.get("header") or {}
    return str(row.get("status") or header.get("status") or "Pending")


def _outstanding(row: Dict[str, Any]) -> bool:
    return _status(row) not in DONE and not row.get("archived")


def _filters(row: Dict[str, Any]):
    """Every made-to-measure filter line on an order, with its numbers."""
    for item in (row.get("items") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("item_kind", "filter") or "filter") != "filter":
            continue
        try:
            qty = int(float(item.get("Quantity") or item.get("quantity") or 0))
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        try:
            area = float(item.get("Square Metres") or 0)
        except (TypeError, ValueError):
            area = 0.0
        yield item, qty, area


# ── What you can promise ─────────────────────────────────────────────────────

def capacity(rows: Sequence[Dict[str, Any]], weeks: int = 8,
             today: _dt.date | None = None) -> Dict[str, Any]:
    """What is already promised, week by week.

    "Can you do it by Friday" is currently answered from memory. This is the
    same answer with the work in front of you: how many filters and how many
    square metres are already due that week, next to what you have actually
    been getting through.

    Weeks start on Monday, because a promise for "next week" means the
    Monday, and anything overdue is its own bucket rather than being smeared
    across the weeks it was originally promised for.
    """
    today = today or _dt.date.today()
    monday = today - _dt.timedelta(days=today.weekday())
    buckets: Dict[Any, Dict[str, Any]] = {}
    for i in range(max(1, int(weeks))):
        start = monday + _dt.timedelta(weeks=i)
        buckets[start] = {"week": start, "orders": 0, "filters": 0,
                          "sqm": 0.0, "customers": set()}
    late = {"week": None, "orders": 0, "filters": 0, "sqm": 0.0,
            "customers": set()}
    undated = dict(late, week="none", customers=set())
    unreadable = 0

    for row in rows or []:
        if not _outstanding(row):
            continue
        due = parse_date(row.get("date_due"))
        if due is None:
            target = undated
        elif due < today:
            target = late
        else:
            start = due - _dt.timedelta(days=due.weekday())
            target = buckets.get(start)
            if target is None:
                continue            # further out than the window asked for
        counted = False
        for _item, qty, area in _filters(row):
            target["filters"] += qty
            target["sqm"] += area * qty
            counted = True
        if not counted and not (row.get("items") or []):
            unreadable += 1
        target["orders"] += 1
        target["customers"].add(str(row.get("customer_name")
                                   or row.get("customer") or ""))

    def tidy(b):
        out = dict(b)
        out["customers"] = len([c for c in b["customers"] if c])
        out["sqm"] = round(b["sqm"], 2)
        return out

    return {
        "weeks":      [tidy(buckets[k]) for k in sorted(buckets)],
        "overdue":    tidy(late),
        "no_date":    tidy(undated),
        "unreadable": unreadable,
        "from":       monday,
    }


def throughput(rows: Sequence[Dict[str, Any]], weeks: int = 12,
               today: _dt.date | None = None) -> Dict[str, Any]:
    """What has actually been finished per week lately.

    The other half of the promise. Without it a load of 400 square metres
    means nothing; with it, it is either two days or a fortnight.
    """
    today = today or _dt.date.today()
    monday = today - _dt.timedelta(days=today.weekday())
    first = monday - _dt.timedelta(weeks=max(1, int(weeks)))
    per_week: Dict[Any, Dict[str, float]] = {}

    for row in rows or []:
        if _status(row) not in DONE:
            continue
        when = parse_date(row.get("date_due")) or parse_date(row.get("created_at"))
        if when is None or when < first or when >= monday:
            continue
        start = when - _dt.timedelta(days=when.weekday())
        b = per_week.setdefault(start, {"orders": 0, "filters": 0, "sqm": 0.0})
        b["orders"] += 1
        for _item, qty, area in _filters(row):
            b["filters"] += qty
            b["sqm"] += area * qty

    weeks_seen = len(per_week) or 1
    return {
        "weeks":       weeks_seen,
        "orders_avg":  round(sum(b["orders"] for b in per_week.values()) / weeks_seen, 1),
        "filters_avg": round(sum(b["filters"] for b in per_week.values()) / weeks_seen, 1),
        "sqm_avg":     round(sum(b["sqm"] for b in per_week.values()) / weeks_seen, 1),
        "per_week":    {k: {"orders": v["orders"], "filters": v["filters"],
                            "sqm": round(v["sqm"], 2)}
                        for k, v in sorted(per_week.items())},
    }


# ── Batch by material ────────────────────────────────────────────────────────

def by_material(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Outstanding work grouped by what it is made of, not by whose it is.

    The run sheet is per customer because that is how it gets delivered. The
    saw and the pleater do not care: they want every 50mm G4 together, in one
    go, whoever it belongs to. Two screens of the same work, sorted for the
    two people who have to do it.
    """
    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for row in rows or []:
        if not _outstanding(row):
            continue
        who = str(row.get("customer_name") or row.get("customer") or "")
        ref = str(row.get("order_number") or row.get("order_no") or "")
        due = parse_date(row.get("date_due"))
        for item, qty, area in _filters(row):
            media = str(item.get("Media Type") or item.get("media") or "—")
            depth = str(item.get("Channel") or item.get("depth") or "—")
            key = (media, depth)
            g = groups.setdefault(key, {
                "media": media, "depth": depth, "filters": 0, "sqm": 0.0,
                "lines": [], "due": None, "customers": set()})
            g["filters"] += qty
            g["sqm"] += area * qty
            g["customers"].add(who)
            g["lines"].append({
                "customer": who, "order_no": ref, "qty": qty, "due": due,
                "short": item.get("Short"), "long": item.get("Long"),
                "type": item.get("Filter Type") or "",
            })
            if due and (g["due"] is None or due < g["due"]):
                g["due"] = due

    out = []
    for g in groups.values():
        # Oldest promise first inside the group, which is the order to work
        # it in once the machine is set up for that media.
        g["lines"].sort(key=lambda l: (l["due"] or _dt.date.max,
                                       l["customer"]))
        g["customers"] = len(g["customers"])
        g["sqm"] = round(g["sqm"], 2)
        out.append(g)
    # The group with the earliest promise first: that is the setup to do now.
    out.sort(key=lambda g: (g["due"] or _dt.date.max, -g["filters"]))
    return out


# ── End of month ─────────────────────────────────────────────────────────────

def month_end(rows: Sequence[Dict[str, Any]], months: int = 13,
              today: _dt.date | None = None) -> Dict[str, Any]:
    """Orders by month, by customer and by what they were made of.

    Counted on the date ordered rather than the date finished, because "how
    much came in last month" is the question, and an order that took six
    weeks belongs to the month it was promised in.
    """
    today = today or _dt.date.today()
    per_month: Dict[str, Dict[str, Any]] = {}
    per_customer: Dict[str, Dict[str, Any]] = {}
    per_type: Dict[str, Dict[str, Any]] = {}
    unreadable = 0

    cutoff_year = today.year - 1
    for row in rows or []:
        when = parse_date(row.get("date_ordered")) or parse_date(row.get("created_at"))
        if when is None:
            unreadable += 1
            continue
        if (today.year - when.year) * 12 + (today.month - when.month) >= months:
            continue
        tag = f"{when.year}-{when.month:02d}"
        m = per_month.setdefault(tag, {"month": tag, "orders": 0,
                                       "filters": 0, "sqm": 0.0})
        who = str(row.get("customer_name") or row.get("customer") or "—")
        c = per_customer.setdefault(who, {"customer": who, "orders": 0,
                                          "filters": 0, "sqm": 0.0})
        m["orders"] += 1
        c["orders"] += 1
        for item, qty, area in _filters(row):
            kind = str(item.get("Filter Type") or "—")
            t = per_type.setdefault(kind, {"type": kind, "filters": 0,
                                           "sqm": 0.0})
            for bucket in (m, c, t):
                bucket["filters"] += qty
                bucket["sqm"] += area * qty

    def tidy(d):
        for v in d.values():
            v["sqm"] = round(v["sqm"], 2)
        return d

    tidy(per_month), tidy(per_customer), tidy(per_type)
    this = f"{today.year}-{today.month:02d}"
    last_year = f"{today.year - 1}-{today.month:02d}"
    void = cutoff_year
    return {
        "months":    [per_month[k] for k in sorted(per_month)],
        "customers": sorted(per_customer.values(),
                            key=lambda r: -r["orders"])[:50],
        "types":     sorted(per_type.values(), key=lambda r: -r["filters"]),
        "this_month": per_month.get(this),
        "same_month_last_year": per_month.get(last_year),
        "unreadable": unreadable,
    }


# ── One search box ───────────────────────────────────────────────────────────

def search(term: str, orders: Sequence[Dict[str, Any]] = (),
           customers: Sequence[Dict[str, Any]] = (),
           stock: Sequence[Dict[str, Any]] = (),
           prices: Dict[str, Any] | None = None,
           limit: int = 40) -> List[Dict[str, Any]]:
    """Type anything and get what matches, from everywhere.

    Sounds small. It is four screens and a guess replaced by one box, many
    times a day. Ordered most specific first: an exact order number is almost
    certainly what somebody holding a piece of paper meant.
    """
    q = str(term or "").strip().lower()
    if len(q) < 2:
        return []
    hits: List[Dict[str, Any]] = []

    def add(kind, label, detail, rank, ref=None, row=None):
        hits.append({"kind": kind, "label": label, "detail": detail,
                     "rank": rank, "ref": ref, "row": row})

    for row in orders or []:
        ref = str(row.get("order_number") or row.get("order_no") or "")
        who = str(row.get("customer_name") or row.get("customer") or "")
        job = str((row.get("header") or {}).get("Job") or row.get("job") or "")
        blob = " ".join((ref, who, job)).lower()
        if q not in blob:
            continue
        exact = ref.lower() == q
        add("order", f"{who} — {ref}" if ref else who,
            " · ".join(x for x in (_status(row),
                                   f"due {row.get('date_due')}"
                                   if row.get("date_due") else "",
                                   f"job {job}" if job else "") if x),
            0 if exact else 2, ref, row)

    for row in customers or []:
        blob = " ".join(str(row.get(k) or "") for k in
                        ("name", "short_name", "email", "suburb", "address",
                         "phone")).lower()
        if q not in blob:
            continue
        add("customer", str(row.get("name") or row.get("short_name") or ""),
            " · ".join(x for x in (str(row.get("suburb") or ""),
                                   str(row.get("phone") or "")) if x),
            1, str(row.get("id") or ""), row)

    for row in stock or []:
        blob = " ".join(str(row.get(k) or "") for k in
                        ("name", "sku", "media_type", "location")).lower()
        if q not in blob:
            continue
        exact = str(row.get("sku") or "").strip().lower() == q
        add("stock", str(row.get("name") or ""),
            f"{row.get('stock_on_hand', 0)} on hand"
            + (f" · {row.get('location')}" if row.get("location") else ""),
            0 if exact else 3, str(row.get("id") or ""), row)

    for code, price in (prices or {}).items():
        text = str(code or "")
        if q not in text.lower():
            continue
        add("product", text,
            f"${float(price):.2f}" if isinstance(price, (int, float))
            else str(price), 4, text, None)

    hits.sort(key=lambda h: (h["rank"], str(h["label"]).lower()))
    return hits[:limit]


# ── Where everything has got to ──────────────────────────────────────────────

# The five boxes already printed down the side of every worksheet. Using the
# same five means the board matches what somebody is ticking with a pen
# rather than asking them to learn a second vocabulary for the same work.
STAGES = [
    ("",          "Not started"),
    ("marked",    "Marked"),
    ("cut",       "Cut"),
    ("drilled",   "Drilled"),
    ("assembled", "Assembled"),
    ("packed",    "Packed"),
]


def wip_board(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Every outstanding job, in the column it has reached.

    "Where is the Bells Creek job" is answered by walking the factory. This
    is the same walk, done sitting down, and it shows the jam: three columns
    with two jobs each and one with eleven is a bottleneck you can see from
    the doorway.
    """
    columns: Dict[str, Dict[str, Any]] = {
        key: {"key": key, "label": label, "orders": [], "filters": 0}
        for key, label in STAGES}
    for row in rows or []:
        if not _outstanding(row):
            continue
        header = row.get("header") or {}
        got = header.get("stages") or {}
        reached = ""
        if isinstance(got, dict):
            for key, _label in STAGES[1:]:
                if got.get(key):
                    reached = key
        count = sum(qty for _i, qty, _a in _filters(row))
        col = columns[reached]
        col["filters"] += count
        col["orders"].append({
            "customer": str(row.get("customer_name")
                            or row.get("customer") or ""),
            "order_no": str(row.get("order_number")
                            or row.get("order_no") or ""),
            "due":      parse_date(row.get("date_due")),
            "filters":  count,
            "id":       row.get("id"),
            "by":       str(got.get("by") or "") if isinstance(got, dict) else "",
            "at":       str(got.get("at") or "") if isinstance(got, dict) else "",
        })
    for col in columns.values():
        col["orders"].sort(key=lambda o: (o["due"] or _dt.date.max,
                                          o["customer"]))
    ordered = [columns[key] for key, _ in STAGES]
    busiest = max(ordered, key=lambda c: len(c["orders"]))
    return {
        "columns": ordered,
        "jam": (busiest["label"]
                if len(busiest["orders"]) >= 3
                and len(busiest["orders"]) >= 2 * (
                    sum(len(c["orders"]) for c in ordered)
                    - len(busiest["orders"])) / max(1, len(ordered) - 1)
                else ""),
    }


# ── What is still owed ───────────────────────────────────────────────────────

def backorders(rows: Sequence[Dict[str, Any]],
               sent_of=None) -> List[Dict[str, Any]]:
    """Orders with something still to go, and how much.

    Only orders where something has actually gone: a job nobody has started
    is not a backorder, it is a job. The distinction matters because a list
    that includes everything outstanding is the order book again, and nobody
    reads the order book looking for backorders.
    """
    out = []
    for row in rows or []:
        if not _outstanding(row):
            continue
        header = row.get("header") or {}
        sent = (sent_of or _sent_from_header)(header)
        if not sent:
            continue
        ordered = left = gone = 0
        for item, qty, _area in _filters(row):
            key = str(item.get("line_id") or "")
            been = min(int(sent.get(key, 0)), qty)
            ordered += qty
            gone += been
            left += qty - been
        if left <= 0 or gone <= 0:
            continue
        out.append({
            "customer": str(row.get("customer_name")
                            or row.get("customer") or ""),
            "order_no": str(row.get("order_number")
                            or row.get("order_no") or ""),
            "id":       row.get("id"),
            "due":      parse_date(row.get("date_due")),
            "ordered":  ordered,
            "sent":     gone,
            "left":     left,
            "when":     str(sent.get("at") or ""),
        })
    out.sort(key=lambda r: (r["due"] or _dt.date.max, r["customer"]))
    return out


def _sent_from_header(header: Dict[str, Any]) -> Dict[str, Any]:
    got = (header or {}).get("sent") or {}
    return got if isinstance(got, dict) else {}


# ── What was planned against what was used ───────────────────────────────────

def planned_vs_actual(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Channel the cut list said a job would take, against what it took.

    The plan is written onto the order when a cut list is produced, and the
    actual is typed in at the saw. Neither is worth much alone; together they
    say whether the allowances are right, and they say it within a week
    instead of within a quarter.
    """
    lines, planned, actual = [], 0, 0
    for row in rows or []:
        header = row.get("header") or {}
        plan = header.get("cut_plan")
        if not isinstance(plan, dict):
            continue
        try:
            said = int(float(plan.get("sticks") or 0))
        except (TypeError, ValueError):
            continue
        used_raw = plan.get("used")
        used = None
        if used_raw not in (None, ""):
            try:
                used = int(float(used_raw))
            except (TypeError, ValueError):
                used = None
        lines.append({
            "customer": str(row.get("customer_name")
                            or row.get("customer") or ""),
            "order_no": str(row.get("order_number")
                            or row.get("order_no") or ""),
            "id":       row.get("id"),
            "planned":  said,
            "used":     used,
            "out_by":   None if used is None else used - said,
            "method":   str(plan.get("method") or ""),
            "when":     str(plan.get("at") or ""),
        })
        if used is not None:
            planned += said
            actual += used
    lines.sort(key=lambda r: (r["used"] is None,
                              -(abs(r["out_by"]) if r["out_by"] else 0)))
    return {
        "lines":    lines,
        "planned":  planned,
        "actual":   actual,
        "out_by":   actual - planned,
        "answered": sum(1 for r in lines if r["used"] is not None),
        "waiting":  sum(1 for r in lines if r["used"] is None),
        "percent":  (round((actual - planned) / planned * 100, 1)
                     if planned else None),
    }


# ── Channel, counted the way it is stored ────────────────────────────────────

def as_sticks(item: Dict[str, Any], offcuts: Sequence[float] = (),
              stick_length: float = 2440.0) -> Dict[str, Any]:
    """Channel as whole lengths and offcuts, rather than as a number.

    A figure of "63" against channel means nothing until you know whether it
    is 63 lengths or 63 metres, and the low-stock alert means nothing either
    way. The unit on the stock item decides, and where it does not say, this
    says so rather than guessing - a guess here is a purchase order for the
    wrong amount.
    """
    unit = str(item.get("unit") or "").strip().lower()
    try:
        held = float(item.get("stock_on_hand") or 0)
    except (TypeError, ValueError):
        held = 0.0
    rack = sorted((float(x) for x in offcuts if float(x) > 0), reverse=True)
    rack_mm = sum(rack)

    if unit in ("each", "", "ea", "stick", "sticks", "length", "lengths"):
        sticks, guessed = held, unit == ""
        full_mm = sticks * stick_length
    elif unit in ("m", "metre", "metres", "meter", "meters", "lm"):
        full_mm, guessed = held * 1000.0, False
        sticks = full_mm / stick_length if stick_length else 0
    elif unit in ("mm", "millimetre", "millimetres"):
        full_mm, guessed = held, False
        sticks = full_mm / stick_length if stick_length else 0
    else:
        return {"ok": False, "unit": unit,
                "why": f"this is counted in {unit!r}, which is not a length "
                       f"or a count of lengths, so it cannot be shown as "
                       f"sticks"}

    return {
        "ok":        True,
        "unit":      unit or "each",
        "guessed":   guessed,
        "sticks":    round(sticks, 2),
        "whole":     int(sticks),
        "full_mm":   round(full_mm, 1),
        "rack":      rack,
        "rack_mm":   round(rack_mm, 1),
        "rack_sticks": round(rack_mm / stick_length, 2) if stick_length else 0,
        "total_mm":  round(full_mm + rack_mm, 1),
        "total_sticks": (round((full_mm + rack_mm) / stick_length, 2)
                         if stick_length else 0),
    }


# ── The week's work, channel and media together ──────────────────────────────

def due_between(rows: Sequence[Dict[str, Any]], start: _dt.date,
                end: _dt.date) -> List[Dict[str, Any]]:
    """Outstanding orders promised inside a window, plus everything late and
    everything with no date - both of which are work that has to happen in
    that window whether or not anybody wrote a date on them."""
    out = []
    for row in rows or []:
        if not _outstanding(row):
            continue
        due = parse_date(row.get("date_due"))
        if due is None or due <= end:
            out.append(row)
    return out


def media_needed(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """How much of each media a batch of orders wants, in square metres.

    The area is the filter's face, not the media cut - what the pleat adds
    is worked out on the worksheet and is not something to double-count
    here. So this is what to have on the shelf, not what to cut.
    """
    per: Dict[str, Dict[str, Any]] = {}
    for row in rows or []:
        for item, qty, area in _filters(row):
            media = str(item.get("Media Type") or "—")
            b = per.setdefault(media, {"media": media, "filters": 0,
                                       "sqm": 0.0})
            b["filters"] += qty
            b["sqm"] += area * qty
    for b in per.values():
        b["sqm"] = round(b["sqm"], 2)
    return sorted(per.values(), key=lambda b: -b["sqm"])
