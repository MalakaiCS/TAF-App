"""Talking to Xero, through the function that holds the keys.

Nothing in this file is a secret. The client secret and the refresh token
live as Edge Function secrets and never come down to a PC - an installer
anybody can download and unzip must not carry the keys to somebody's
accounts, and these are the keys that move money.

So this asks the function to do things and reports what it said. Every
ordinary reason something did not happen - not connected yet, no Xero app set
up on the project - comes back as a sentence a person can act on rather than
as an exception, because none of them are faults.

The CSV export is not going anywhere. A connection that depends on somebody
else's service being up is a connection that will be down on the afternoon an
invoice has to go out, and the file that has always worked is what you fall
back to.
"""
from __future__ import annotations

import json as _json
import urllib.error
import urllib.request
from typing import Any, Dict, List

from . import db as _db


def _url(action: str) -> str:
    return f"{_db.SUPABASE_URL.rstrip('/')}/functions/v1/xero?do={action}"


def _call(action: str, body: Dict[str, Any] | None = None,
          timeout: int = 30) -> Dict[str, Any]:
    try:
        session = _db.get_client().auth.get_session()
        token = getattr(session, "access_token", "") if session else ""
    except Exception:
        token = ""
    if not token:
        return {"error": "Not signed in."}

    data = _json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(
        _url(action), data=data, method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "apikey": _db.current_anon_key(),
            "Content-Type": "application/json",
        })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = _json.loads(exc.read().decode("utf-8") or "{}").get("error", "")
        except Exception:
            pass
        if exc.code == 404:
            detail = detail or ("The 'xero' function is not deployed to this "
                                "Supabase project yet.")
        return {"error": detail or f"Xero said {exc.code}."}
    except Exception as exc:
        return {"error": str(exc)}


def status() -> Dict[str, Any]:
    """Is it connected, and to which organisation?"""
    return _call("status")


def connect_url() -> str:
    """Where a person signs in to Xero. Empty if it cannot be started."""
    out = _call("start")
    return str(out.get("url") or "")


def push_invoice(invoice: Dict[str, Any]) -> Dict[str, Any]:
    """Write one sales invoice to Xero.

    Returns {"sent": bool, "number": str, "error": str}. The invoice is built
    from the same priced lines the CSV export uses, so what Xero receives and
    what the file would have contained are the same thing.
    """
    out = _call("push", {"invoice": invoice})
    if out.get("error"):
        return {"sent": False, "error": str(out["error"])}
    return {"sent": bool(out.get("sent")),
            "number": str(out.get("number") or ""),
            "id": str(out.get("id") or ""), "error": ""}


def owing() -> Dict[str, Any]:
    """What customers owe, oldest first.

    The point of connecting at all: knowing a customer is ninety days behind
    before making them more filters, rather than after.
    """
    out = _call("owing")
    if out.get("error"):
        return {"rows": [], "owed": 0.0, "error": str(out["error"])}
    rows = list(out.get("rows") or [])
    rows.sort(key=lambda r: -int(r.get("days_late") or 0))
    return {"rows": rows, "owed": float(out.get("owed") or 0), "error": ""}


def invoice_from(order: Dict[str, Any], lines: List[Dict[str, Any]],
                 account_code: str = "200") -> Dict[str, Any]:
    """One order, in the shape Xero wants.

    Only lines that have a price go on it. A line Xero would take at zero is
    a line that quietly invoices a customer nothing for something they are
    getting, and the export has always listed those before writing the file
    rather than dropping them.
    """
    items = []
    skipped = []
    for line in lines or []:
        try:
            price = float(line.get("unit_price") or 0)
            qty = float(line.get("quantity") or line.get("Quantity") or 0)
        except (TypeError, ValueError):
            skipped.append(line)
            continue
        if price <= 0 or qty <= 0:
            skipped.append(line)
            continue
        items.append({
            "Description": str(line.get("description")
                               or line.get("Description") or "Filter"),
            "Quantity": qty,
            "UnitAmount": round(price, 2),
            "ItemCode": str(line.get("part_number")
                            or line.get("Part Number") or "") or None,
            "AccountCode": account_code,
        })
    header = order.get("header") or {}
    return {
        "invoice": {
            "Type": "ACCREC",
            "Contact": {"Name": str(order.get("customer_name")
                                    or header.get("Customer Name") or "")},
            "Date": str(order.get("date_ordered")
                        or header.get("Date Ordered") or ""),
            "Reference": str(order.get("order_number")
                             or header.get("Order Number") or ""),
            "Status": "DRAFT",
            "LineItems": items,
        },
        "skipped": skipped,
    }
