"""Being told what needs doing, instead of going to look.

Everything in the morning summary is already on the Dashboard. The trouble
with a Dashboard is that it only says anything to somebody who opens it, and
the morning it mattered most is the morning nobody did.

Two switches, and both have to be on before anything is sent.

The company one, shared by every PC, sitting beside the customer-email switch
in the same row: whether this system sends staff email at all. The other is
each person's own, kept against their account, because whose inbox a thing
lands in is theirs to decide and nobody else's.

The sending is done by the `daily-summary` Supabase Edge Function, which
holds the mail provider's key as a function secret - never inside the Windows
installer, where anyone could pull it back out and send mail as Total Air
Filtration.
"""
from __future__ import annotations

from typing import Any, Dict

from . import db as _db
from . import emails as _emails

KEY = "daily_summary"


def settings() -> Dict[str, Any]:
    """The shared row, as emails.py reads it. One row, one decision."""
    return _emails.settings()


def is_on() -> bool:
    """Is the company sending morning summaries at all?"""
    return _emails._really_on(settings().get(KEY))


def set_on(enabled: bool) -> None:
    """Turn the morning summary on or off for the whole company."""
    current = dict(settings())
    current[KEY] = bool(enabled)
    _db.set_catalog_value(_emails.SETTINGS_KEY, current)


def can_change() -> bool:
    """Who may flip the company one: whoever manages the shared catalogue."""
    return _emails.can_change()


# ── One person's own ─────────────────────────────────────────────────────────

def mine() -> bool:
    """Does the person signed in on this PC want one?

    False on any error, deliberately. A database that will not answer must
    not be read as "yes, send it": nobody is harmed by a summary that did
    not arrive, and the reverse is how a system loses people's trust.
    """
    try:
        user = _db.current_user()
        if not user:
            return False
        resp = (_db.get_client().table("notify_settings")
                .select("daily_summary").eq("user_id", str(user.id))
                .limit(1).execute())
        rows = resp.data or []
        return bool(rows and rows[0].get("daily_summary"))
    except Exception:
        return False


def set_mine(enabled: bool) -> bool:
    """Turn your own on or off. Returns what it is now.

    Goes through set_my_daily_summary rather than an upsert from here: the
    account it writes against is taken from the session inside the database,
    so there is no argument to get wrong and none to pass on purpose.
    """
    resp = _db.get_client().rpc(
        "set_my_daily_summary", {"p_on": bool(enabled)}).execute()
    data = resp.data
    if isinstance(data, list):
        data = data[0] if data else None
    if isinstance(data, dict):
        data = data.get("set_my_daily_summary")
    return bool(data)


def _function_url() -> str:
    return f"{_db.SUPABASE_URL.rstrip('/')}/functions/v1/daily-summary"


def send_mine(timeout: int = 30) -> Dict[str, Any]:
    """Send yourself this morning's summary, now.

    This is what makes the whole thing usable before anybody sets up a
    schedule, and it is also how you find out whether the mail provider is
    configured without waiting until seven tomorrow morning.

    Returns {"sent": bool, "reason": str}. Ordinary reasons nothing was sent
    - switched off, nobody has it on - come back as sent=False with a reason
    rather than as an error, because they are not faults.
    """
    import json as _json
    import urllib.error
    import urllib.request

    try:
        session = _db.get_client().auth.get_session()
        token = getattr(session, "access_token", "") if session else ""
    except Exception:
        token = ""
    if not token:
        return {"sent": False, "reason": "Not signed in."}

    req = urllib.request.Request(
        _function_url(), data=b"{}", method="POST",
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
            detail = detail or ("The 'daily-summary' function is not deployed "
                                "to this Supabase project yet.")
        return {"sent": False, "reason": detail or f"Mail server said {exc.code}."}
    except Exception as exc:
        return {"sent": False, "reason": str(exc)}

    if out.get("error"):
        return {"sent": False, "reason": str(out["error"])}
    return {"sent": bool(out.get("sent")),
            "reason": str(out.get("reason") or "")}
