"""Telling a customer we have their order.

The sending itself is done by the `send-order-email` Supabase Edge Function
(see supabase/functions/send-order-email/index.ts), which holds the mail
provider's API key as a function secret. It is never shipped inside the
Windows installer, where anyone could pull it back out and send mail as
Total Air Filtration.

Nothing here ever stops an order being raised. An order that could not be
confirmed by email is an order, and a customer who has to be rung instead is
a much smaller problem than a job that did not get made.
"""
from __future__ import annotations

from typing import Any, Dict

from . import db as _db

SETTINGS_KEY = "email_settings"

DEFAULTS: Dict[str, Any] = {
    # Off. Nobody wants a system that starts writing to their customers the
    # moment it is installed.
    "order_received": False,
    "reply_to": "",
}


def _really_on(value: Any) -> bool:
    """Only an unambiguous yes counts as on.

    bool("no") is True in Python, and bool("false") is True. Someone editing
    the row by hand in Supabase and typing "false" would have switched
    customer emails on. For a switch that decides whether mail leaves the
    building, anything that is not clearly a yes is a no.
    """
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "on", "1")
    return False


def settings() -> Dict[str, Any]:
    """What is switched on, shared by every PC.

    Kept in the database rather than in each machine's settings file: "do we
    email customers" is a decision for the company, and one PC quietly
    disagreeing with the others is the kind of thing nobody notices for a
    month.
    """
    out = dict(DEFAULTS)
    try:
        stored = _db.get_catalog_map().get(SETTINGS_KEY) or {}
        if isinstance(stored, dict):
            out.update(stored)
    except Exception:
        pass          # no connection, or the catalogue table is missing
    out["order_received"] = _really_on(out.get("order_received"))
    return out


def is_on() -> bool:
    return settings().get("order_received", False)


def set_on(enabled: bool) -> None:
    """Turn customer emails on or off for everyone."""
    current = settings()
    current["order_received"] = bool(enabled)
    _db.set_catalog_value(SETTINGS_KEY, current)


def can_change() -> bool:
    """Who may flip it: the same people who manage the shared catalogue."""
    try:
        return bool(_db.can_manage_catalog())
    except Exception:
        return False


def _function_url() -> str:
    return f"{_db.SUPABASE_URL.rstrip('/')}/functions/v1/send-order-email"


def send_order_received(order_id: str, timeout: int = 20) -> Dict[str, Any]:
    """Ask the function to send the slip for one order.

    Returns {"sent": bool, "reason": str}. It does not raise for the ordinary
    reasons an email does not go — switched off, no address on file — because
    those are not faults and the caller should not have to tell them apart
    from a failure.
    """
    import json as _json
    import urllib.error
    import urllib.request

    if not order_id:
        return {"sent": False, "reason": "No order to send."}

    try:
        session = _db.get_client().auth.get_session()
        token = getattr(session, "access_token", "") if session else ""
    except Exception:
        token = ""
    if not token:
        return {"sent": False, "reason": "Not signed in."}

    body = _json.dumps({"order_id": str(order_id)}).encode("utf-8")
    req = urllib.request.Request(
        _function_url(), data=body, method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "apikey": _db.current_anon_key(),
            "Content-Type": "application/json",
        })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out = _json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = _json.loads(exc.read().decode("utf-8") or "{}").get("error", "")
        except Exception:
            pass
        if exc.code == 404:
            detail = detail or ("The 'send-order-email' function is not "
                                "deployed to this Supabase project yet.")
        return {"sent": False, "reason": detail or f"Mail server said {exc.code}."}
    except Exception as exc:
        return {"sent": False, "reason": str(exc)}

    if out.get("error"):
        return {"sent": False, "reason": str(out["error"])}
    return {"sent": bool(out.get("sent")),
            "reason": str(out.get("reason") or ""),
            "to": str(out.get("to") or "")}
