"""Asking for supplies, and the bell that tells a manager somebody has.

Somebody on the floor runs out of rivets. Until now that was a shout across
the factory, a note on the whiteboard, or nothing at all until the job
stopped. This is where they ask, and every manager is told.

Almost none of the rules live here, on purpose. Who asked is written by the
database, not by this file. Who gets told is decided by a trigger, not by this
file. Nobody can put a notification in somebody else's bell from any app,
this one included. What is here is the list of things you can ask for, the
wording, and the calls - see migrate_supply_requests.sql for everything that
actually has to hold.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional

from . import db as _db

# The things that run out. "Other" says what it is in the detail box.
# The same list is in docs/app/screens.js; a test holds the two together, so
# the phone and the desktop never offer different things.
ITEMS = ["Rivets", "Tape", "Media", "Mesh Wire", "Channel", "Other"]

# What to ask underneath each one. "Tape" on its own is not something a
# manager can order - there are four kinds on the shelf.
DETAIL_HINTS = {
    "Rivets":    "Which rivets? Size or type",
    "Tape":      "Which tape? Foil, duct, width",
    "Media":     "Which grade? G4, F7, carbon…",
    "Mesh Wire": "Which mesh? Gauge, galv or stainless",
    "Channel":   "Which depth? 25, 45, 50…",
    "Other":     "What do you need?",
}

STATUSES = ["open", "ordered", "received", "declined", "cancelled"]

# How each one reads on a screen.
STATUS_LABELS = {
    "open":      "Waiting",
    "ordered":   "Ordered",
    "received":  "Received",
    "declined":  "Declined",
    "cancelled": "Cancelled",
}

# What a manager can move a request to, from where it is. Received and
# declined are the end of the road; "ordered" can still arrive.
NEXT = {
    "open":    ["ordered", "received", "declined"],
    "ordered": ["received"],
}


class SupplyError(Exception):
    """Said to the person, so it is written for them."""


# ── The bell ─────────────────────────────────────────────────────────────────

def badge_text(count: Any) -> str:
    """What goes in the red circle on the bell.

    Nothing at all when there is nothing unread - a bell that always says 0
    is a bell nobody looks at. And never more than "99+": past that the
    number is not information any more, and a three-digit figure does not fit
    in a circle the size of a fingernail.
    """
    try:
        n = int(count)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    return "99+" if n > 99 else str(n)


def unread_count() -> int:
    """How many of mine are unread. 0 if the question could not be asked.

    Asked every half minute by every PC. A dropped connection must not turn
    into an error box every thirty seconds - it turns into an empty bell, and
    the next poll that gets through puts the number back.
    """
    try:
        resp = _db.get_client().rpc("my_unread_count", {}).execute()
        return int(resp.data or 0)
    except Exception:
        return 0


def my_notifications(limit: int = 40) -> List[Dict[str, Any]]:
    """Mine, newest first. Row-level security means there are no others."""
    resp = (_db.get_client().table("notifications")
            .select("*").order("created_at", desc=True).limit(limit)
            .execute())
    return list(resp.data or [])


def mark_read(ids: Optional[List[str]] = None) -> int:
    """Mark some, or with no ids all, of mine as read."""
    resp = (_db.get_client().rpc(
        "mark_notifications_read", {"p_ids": list(ids) if ids else None})
        .execute())
    try:
        return int(resp.data or 0)
    except (TypeError, ValueError):
        return 0


# ── Asking ───────────────────────────────────────────────────────────────────

def clean_request(item: str, detail: str = "", quantity: str = "",
                  urgent: bool = False, note: str = "") -> Dict[str, Any]:
    """Check a request before it is sent, and say plainly what is missing.

    The database refuses an "Other" that does not say what it is. Catching it
    here means the person is told while the form is still in front of them,
    rather than after it has gone.
    """
    item = (item or "").strip()
    detail = (detail or "").strip()
    if item not in ITEMS:
        raise SupplyError("Pick what you need from the list.")
    if item == "Other" and not detail:
        raise SupplyError("Say what you need - \"Other\" on its own does "
                          "not tell anybody what to order.")
    return {
        "item": item,
        "detail": detail[:200],
        "quantity": (quantity or "").strip()[:60],
        "urgent": bool(urgent),
        "note": (note or "").strip()[:500],
    }


def request_supply(item: str, detail: str = "", quantity: str = "",
                   urgent: bool = False, note: str = "",
                   client_ref: Optional[str] = None) -> Dict[str, Any]:
    """Ask for something. Every manager is told by the database, not by us.

    Who asked is not sent at all: the database writes the signed-in account,
    and would overwrite anything sent here anyway.

    Through request_supply() rather than an insert, with a reference made up
    here, so a retry after a dropped connection files it once - the same one
    way in the phone uses.
    """
    import uuid
    row = clean_request(item, detail, quantity, urgent, note)
    resp = _db.get_client().rpc("request_supply", {
        "p_item": row["item"], "p_detail": row["detail"],
        "p_quantity": row["quantity"], "p_urgent": row["urgent"],
        "p_note": row["note"],
        "p_client_ref": client_ref or f"desk-{uuid.uuid4()}",
    }).execute()
    data = resp.data
    if isinstance(data, list):
        data = data[0] if data else None
    return data or row


def list_requests(include_done: bool = False,
                  limit: int = 200) -> List[Dict[str, Any]]:
    """Everything asked for, still-waiting first then newest.

    Everybody on staff sees all of it, on purpose: the second person out of
    tape should find it already on its way.
    """
    q = (_db.get_client().table("supply_requests").select("*")
         .order("created_at", desc=True).limit(limit))
    if not include_done:
        q = q.in_("status", ["open", "ordered"])
    rows = list(q.execute().data or [])
    return sort_requests(rows)


def sort_requests(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Urgent and waiting at the top, then waiting, then on order, then done.

    Within each, newest first - except that waiting ones are oldest first,
    because the one that has been waiting longest is the one somebody is
    standing at a bench without.
    """
    rank = {"open": 0, "ordered": 1, "received": 2, "declined": 3,
            "cancelled": 4}

    def key(r):
        status = r.get("status") or "open"
        waiting = status == "open"
        stamp = str(r.get("created_at") or "")
        return (0 if (waiting and r.get("urgent")) else 1,
                rank.get(status, 9),
                stamp if waiting else _invert(stamp))
    return sorted(rows, key=key)


def _invert(stamp: str) -> str:
    """Newest-first ordering of an ISO timestamp inside an ascending sort."""
    return "".join(chr(0x10FFFF - ord(c)) for c in stamp)


def set_status(request_id: str, status: str) -> None:
    """Move a request along. Who did it and when is stamped by the database.

    Row-level security does not refuse an update it will not allow - it
    quietly matches no rows, and the request comes back as a success that
    changed nothing. So the answer is checked: no row back means nothing
    happened, and the person is told so rather than shown a request that
    looks cancelled on their screen and is still open for everyone else.
    """
    if status not in STATUSES:
        raise SupplyError(f"{status} is not a status a request can have.")
    resp = (_db.get_client().table("supply_requests")
            .update({"status": status}).eq("id", request_id).execute())
    if not (resp.data or []):
        raise SupplyError(
            "That didn't change anything - it may have been dealt with "
            "already, or it isn't yours to change. Refresh and look again.")


def cancel(request_id: str) -> None:
    """Take back a request you made, while nothing has been done about it."""
    set_status(request_id, "cancelled")


# ── Wording ──────────────────────────────────────────────────────────────────

def describe(row: Dict[str, Any]) -> str:
    """"Tape - 50mm foil, 3 rolls" as it reads in a list."""
    item = (row.get("item") or "").strip()
    detail = (row.get("detail") or "").strip()
    qty = (row.get("quantity") or "").strip()
    text = item + (f" - {detail}" if detail else "")
    return text + (f", {qty}" if qty else "")


def ago(stamp: Any, now: Optional[_dt.datetime] = None) -> str:
    """"5 min ago", "3 h ago", "2 d ago". Blank if it cannot be read."""
    if not stamp:
        return ""
    try:
        text = str(stamp).replace("Z", "+00:00")
        when = _dt.datetime.fromisoformat(text)
    except ValueError:
        return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=_dt.timezone.utc)
    now = now or _dt.datetime.now(_dt.timezone.utc)
    secs = max(0, int((now - when).total_seconds()))
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60} min ago"
    if secs < 86400:
        return f"{secs // 3600} h ago"
    return f"{secs // 86400} d ago"


def is_missing_table(exc: BaseException) -> bool:
    """True when the migration simply has not been run yet.

    That is a setup step, not a fault, and the screen should say which file
    to run rather than show a Postgres error.
    """
    text = str(exc).lower()
    return any(s in text for s in (
        "supply_requests", "notifications", "my_unread_count",
        "mark_notifications_read")) and any(s in text for s in (
        "does not exist", "not found", "could not find", "pgrst202",
        "pgrst205", "42p01", "42883"))
