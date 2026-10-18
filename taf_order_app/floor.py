"""The factory floor: the TV board, quality checks and the fault log.

Pure, so it is tested on its own. docs/app/screens.js has the same rules
for the phone and the TV - a test holds the two together - and
migrate_floor.sql (step 44) is where the timer, the checklists and the
finished-job photos are kept.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .insights import parse_date

# ── The board on the TV ──────────────────────────────────────────────────────
# Four columns a person at the far end of the factory can read: what is
# waiting to be cut, what is being made, what is packed and waiting to go,
# and what has gone today.

COLUMNS = [
    ("to_cut", "To cut"),
    ("making", "Making"),
    ("packed", "Packed"),
    ("out",    "Out the door"),
]

OUT = ("Dispatched", "Delivered", "Collected")
_STARTED = ("cut", "drilled", "assembled")


def _header(row: Dict[str, Any]) -> Dict[str, Any]:
    head = row.get("header")
    return head if isinstance(head, dict) else {}


def _stamp_day(text: Any) -> Optional[_dt.date]:
    """The day, here, of an ISO time the database stamped in UTC."""
    s = str(text or "").strip()
    if not s:
        return None
    try:
        when = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is not None:
        when = when.astimezone()
    return when.date()


def _reached(header: Dict[str, Any]) -> str:
    """The furthest worksheet box ticked (see db.stage_reached)."""
    got = header.get("stages")
    reached = ""
    if isinstance(got, dict):
        for key in ("marked", "cut", "drilled", "assembled", "packed"):
            if got.get(key):
                reached = key
    return reached


def board_column(row: Dict[str, Any], today: _dt.date) -> str:
    """Which column an order is in on the TV, or "" when it is not on it
    (archived, or out the door on another day)."""
    if row.get("archived"):
        return ""
    head = _header(row)
    status = str(head.get("status") or row.get("status") or "Pending")
    if status in OUT:
        # When it went, stamped by the database (step 44); before that, the
        # day it was due is the best guess there is.
        went = _stamp_day(head.get("status_at")) or parse_date(row.get("date_due"))
        return "out" if went == today else ""
    if status == "Complete":
        return "packed"
    reached = _reached(head)
    if reached == "packed":
        return "packed"
    try:
        made = int(row.get("n_made") or 0)
    except (TypeError, ValueError):
        made = 0
    if reached in _STARTED or made > 0 or status == "In Production":
        return "making"
    return "to_cut"


def working_days_on(day: _dt.date, n: int) -> _dt.date:
    """`n` working days after `day` (Saturday and Sunday skipped)."""
    out = day
    left = max(0, int(n))
    while left:
        out += _dt.timedelta(days=1)
        if out.weekday() < 5:
            left -= 1
    return out


def production_board(rows: Iterable[Dict[str, Any]], today: _dt.date,
                     ahead: int = 1) -> List[Dict[str, Any]]:
    """The four columns, each with its cards in the order to work them:
    priority first, then the earliest due. What is waiting to be cut is
    only what is due within `ahead` working days (or late) - the TV shows
    today's work, not the order book. Everything started, packed or gone
    today is shown whenever it is due."""
    horizon = working_days_on(today, ahead)
    cols = {key: {"key": key, "label": label, "cards": []}
            for key, label in COLUMNS}
    for row in rows or []:
        col = board_column(row, today)
        if not col:
            continue
        due = parse_date(row.get("date_due"))
        if col == "to_cut" and (due is None or due > horizon):
            continue
        head = _header(row)
        cols[col]["cards"].append({
            "id": row.get("id"),
            "customer": str(row.get("customer_name") or row.get("customer") or ""),
            "order_no": str(row.get("order_number") or row.get("order_no") or ""),
            "due": due,
            "late": bool(due and due < today and col != "out"),
            "today": due == today,
            "priority": bool(head.get("priority")),
            "made": int(row.get("n_made") or 0),
            "lines": int(row.get("n_items") or 0),
        })
    for col in cols.values():
        col["cards"].sort(key=lambda c: (not c["priority"],
                                         c["due"] or _dt.date.max,
                                         c["customer"].lower()))
    return [cols[key] for key, _label in COLUMNS]


# ── Quality checks ───────────────────────────────────────────────────────────

def checks_for(filter_type: Any, lists: Dict[str, Sequence[str]]) -> List[str]:
    """The checks for a filter type: its own list, or the list for every
    type ('*'), or none."""
    want = str(filter_type or "").strip().lower()
    for key, checks in (lists or {}).items():
        if str(key).strip().lower() == want and want:
            return [str(c) for c in checks if str(c).strip()]
    return [str(c) for c in (lists or {}).get("*", []) if str(c).strip()]


def qc_record(checks: Sequence[str], by: str, at: str) -> Dict[str, Any]:
    """What is kept on the line once every check has been ticked."""
    return {"passed": True, "checks": [str(c) for c in checks],
            "by": str(by or ""), "at": str(at or "")}


def parse_checks(text: str) -> List[str]:
    """One check a line, as typed into the editor; blanks and repeats out."""
    out: List[str] = []
    for line in str(text or "").splitlines():
        line = " ".join(line.split()).lstrip("-•* ").strip()
        if line and line.lower() not in (c.lower() for c in out):
            out.append(line[:120])
    return out


# ── Faults ───────────────────────────────────────────────────────────────────

FAULT_REASONS = [
    "Wrong size",
    "Media damaged",
    "Frame or channel fault",
    "Gaps or poor seal",
    "Wrong media",
    "Brace missing",
    "Damaged in transit",
    "Other",
]

FOUND = {"qc": "Found in QC", "returned": "Came back", "site": "Found on site"}


def _count(rows: Iterable[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    tally: Dict[str, float] = {}
    for row in rows:
        name = str(row.get(key) or "").strip() or "Not recorded"
        try:
            qty = float(row.get("quantity") or 1)
        except (TypeError, ValueError):
            qty = 1.0
        tally[name] = tally.get(name, 0.0) + qty
    return [{"name": k, "count": v}
            for k, v in sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))]


def fault_patterns(rows: Iterable[Dict[str, Any]], since: Optional[_dt.date] = None
                   ) -> Dict[str, Any]:
    """Faults and returns added up by reason, filter type, who made it and
    where it was found - the patterns, not the list."""
    keep = []
    for row in rows or []:
        day = parse_date(row.get("created_at"))
        if since and day and day < since:
            continue
        keep.append(row)
    return {
        "total": sum(float(r.get("quantity") or 1) for r in keep),
        "by_reason": _count(keep, "reason"),
        "by_type": _count(keep, "filter_type"),
        "by_maker": _count(keep, "made_by"),
        "by_found": [{"name": FOUND.get(c["name"], c["name"]), "count": c["count"]}
                     for c in _count(keep, "found")],
    }


# ── How long things take ─────────────────────────────────────────────────────

def minutes_text(minutes: Any) -> str:
    """"12 min", "1 h 05 min"."""
    try:
        m = float(minutes or 0)
    except (TypeError, ValueError):
        return ""
    if m < 60:
        return f"{m:.0f} min" if m >= 10 else f"{m:.1f} min".replace(".0 ", " ")
    h, rest = divmod(int(round(m)), 60)
    return f"{h} h {rest:02d} min"
