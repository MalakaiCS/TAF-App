"""Talking to Xero, through the function that holds the keys.

Nothing in this file is a secret. The client secret is a function secret and
the sign-in to Xero is kept where no app account can read it
(migrate_xero_link.sql); neither comes down to a PC - an installer anybody
can download and unzip must not carry the keys to somebody's accounts, and
these are the keys that move money.

How an order reaches Xero. In the TRIAL (where a new link starts) nothing
goes by itself: the order's "Send to Xero & invoice customer" button makes
the invoice, approves it, has Xero email it and marks the order Complete;
"Send draft to Xero" makes the draft only. Once a manager publishes it
(AUTOMATIC):

  * Every order raised since then becomes a DRAFT sales invoice,
    dated the day on the work order. Pricing it needs the price list and the
    part-number rules, which are here, so a PC prices the order
    (`draft_from`) and hands the lines to the function (`push_draft`). While
    it is a draft, changing the order changes the draft.
  * Marking the job Complete (or Dispatched) - on any PC, phone or screen - is
    noted by the database. The function then dates the invoice that day,
    approves it, and has Xero email it to the contact on file (`sweep`).
  * An invoice with a line nothing could price is never approved on its own:
    the line goes on the draft at $0 marked NO PRICE, and it waits until the
    price is on the order.

Every ordinary reason something did not happen - not connected, no contact
in Xero, no Xero app set up on the project - comes back as a sentence a
person can act on rather than an exception, because none of them are faults.

The CSV export is not going anywhere. A connection that depends on somebody
else's service being up is a connection that will be down on the afternoon an
invoice has to go out, and the file that has always worked is what you fall
back to.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json as _json
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Optional

from . import db as _db

# What each state means, for the Xero screen.
STATES = {
    "waiting":  "Waiting to go to Xero",
    "draft":    "Draft in Xero",
    "approved": "Approved - not emailed",
    "sent":     "Approved and emailed",
    "deleted":  "Order deleted - draft removed",
    "gone":     "Changed in Xero by hand",
}


def _url(action: str) -> str:
    return f"{_db.SUPABASE_URL.rstrip('/')}/functions/v1/xero?do={action}"


def _call(action: str, body: Dict[str, Any] | None = None,
          timeout: int = 60) -> Dict[str, Any]:
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
        out: Dict[str, Any] = {}
        try:
            out = _json.loads(exc.read().decode("utf-8") or "{}")
        except Exception:
            pass
        if exc.code == 404 and not out.get("error"):
            out["error"] = ("The 'xero' function is not deployed to this "
                            "Supabase project yet.")
        out.setdefault("error", f"Xero said {exc.code}.")
        return out
    except Exception as exc:
        return {"error": str(exc)}


# ── Asking the function ──────────────────────────────────────────────────────

def status() -> Dict[str, Any]:
    """Is it connected, to which organisation, and since when? Asking also
    keeps the link alive: a sign-in Xero has not seen renewed for a week is
    renewed, so it never lapses."""
    return _call("status")


def connect_url() -> str:
    """Where a manager signs in to Xero. Empty if it cannot be started."""
    out = _call("start")
    return str(out.get("url") or "")


def connect_problem() -> str:
    """Why `connect_url` came back empty."""
    return str(_call("start").get("error") or "")


def disconnect() -> Dict[str, Any]:
    return _call("disconnect")


def push_draft(order_id: str, built: Dict[str, Any],
               source_md5: str = "", invoice_now: bool = False) -> Dict[str, Any]:
    """Make or update one order's draft invoice. `built` is `draft_from`'s.

    `invoice_now` is the order's "Send to Xero & invoice customer" button:
    the invoice is approved and emailed there and then, dated today. Refused,
    before anything is made, if a line has no price.
    """
    return _call("draft", {"order_id": str(order_id),
                           "invoice": built["invoice"],
                           "hash": built["hash"],
                           "source_md5": source_md5 or None,
                           "invoice_now": bool(invoice_now)}, timeout=120)


MODES = {"manual": "Trial - sent from the button on each order",
         "automatic": "Automatic - every order goes as a draft, invoiced "
                      "when the job is complete"}


def set_mode(mode: str) -> Dict[str, Any]:
    """Trial ('manual') or 'automatic'. Managers only."""
    return _call("mode", {"mode": mode})


def sweep() -> Dict[str, Any]:
    """Approve and email the completed jobs; take deleted orders' drafts out."""
    return _call("sweep", timeout=120)


def retry(order_id: str) -> Dict[str, Any]:
    return _call("retry", {"order_id": str(order_id)})


def _pdf(action: str, body: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
    """A PDF as Xero prints it: {"pdf": bytes, "number": str} or {"error"}."""
    try:
        session = _db.get_client().auth.get_session()
        token = getattr(session, "access_token", "") if session else ""
    except Exception:
        token = ""
    if not token:
        return {"error": "Not signed in."}
    req = urllib.request.Request(
        _url(action), data=_json.dumps(body).encode(),
        method="POST", headers={"Authorization": f"Bearer {token}",
                                "apikey": _db.current_anon_key(),
                                "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            if not data.startswith(b"%PDF"):
                return {"error": "Xero did not send back a PDF."}
            return {"pdf": data, "number": resp.headers.get("X-Invoice-Number", "")}
    except urllib.error.HTTPError as exc:
        try:
            msg = _json.loads(exc.read().decode("utf-8") or "{}").get("error", "")
        except Exception:
            msg = ""
        return {"error": msg or f"Xero said {exc.code}."}
    except Exception as exc:
        return {"error": str(exc)}


def invoice_pdf(order_id: str, timeout: int = 60) -> Dict[str, Any]:
    """An order's invoice as Xero prints it: {"pdf": bytes, "number": str}
    or {"error": str}."""
    return _pdf("pdf", {"order_id": str(order_id)}, timeout)


# ── Buying ───────────────────────────────────────────────────────────────────

def pull_suppliers() -> Dict[str, Any]:
    """Xero's supplier contacts into the app: {"suppliers": n}. Managers."""
    return _call("suppliers_pull", timeout=180)


def pull_items() -> Dict[str, Any]:
    """Every Xero item into the app: {"items": n, "matched": n} - matched
    being how many were put with a supplier by their code. Managers."""
    return _call("items_pull", timeout=180)


def send_po(po_id: str) -> Dict[str, Any]:
    """Make the purchase order in Xero and email it to the supplier:
    {"po_number", "emailed": bool, "emailed_to" | "error"}. Managers."""
    return _call("po_send", {"po_id": str(po_id)}, timeout=120)


def po_pdf(po_id: str, timeout: int = 60) -> Dict[str, Any]:
    """A purchase order as Xero prints it: {"pdf": bytes, "number": str}."""
    return _pdf("po_pdf", {"po_id": str(po_id)}, timeout)


def find_contacts(term: str) -> Dict[str, Any]:
    """Xero contacts matching a search: {"contacts": [{id, name, email}]}."""
    return _call("contacts", {"term": str(term or "")})


def contact_url(contact_id: str) -> str:
    """The contact's page in Xero, for whoever is signed in to Xero."""
    return f"https://go.xero.com/Contacts/View/{contact_id}"


def best_contact(contacts, names) -> Optional[Dict[str, Any]]:
    """The contact whose name is exactly one of the customer's (ignoring
    case), when there is exactly one such; otherwise None, and a person
    picks."""
    wanted = {str(n or "").strip().lower() for n in names if str(n or "").strip()}
    hits = [c for c in contacts or []
            if str(c.get("name") or "").strip().lower() in wanted]
    return hits[0] if len(hits) == 1 else None


def invoices() -> Dict[str, Any]:
    """Where each order's invoice is up to, newest first."""
    return _call("list")


def owing() -> Dict[str, Any]:
    """What customers owe, oldest first.

    Knowing a customer is ninety days behind before making them more
    filters, rather than after.
    """
    out = _call("owing")
    if out.get("error"):
        return {"rows": [], "owed": 0.0, "error": str(out["error"])}
    rows = list(out.get("rows") or [])
    rows.sort(key=lambda r: -int(r.get("days_late") or 0))
    return {"rows": rows, "owed": float(out.get("owed") or 0), "error": ""}


# ── Building the draft ───────────────────────────────────────────────────────

def iso_date(value: str, fallback: Optional[_dt.date] = None) -> str:
    """The work order's dd/mm/yy as Xero's YYYY-MM-DD."""
    from .validation import parse_date
    got = parse_date(value or "")
    return (got.date() if got else (fallback or _dt.date.today())).isoformat()


def contact_names(customer: Optional[Dict[str, Any]],
                  header: Dict[str, Any]) -> List[str]:
    """The names the customer could be under in Xero, most likely first: the
    legal name (what goes on an invoice), the account name, the short name,
    then the name on the order."""
    customer = customer or {}
    out: List[str] = []
    for value in (customer.get("legal_name"), customer.get("name"),
                  customer.get("short_name"), header.get("Customer Name")):
        value = str(value or "").strip()
        if value and value.lower() not in (n.lower() for n in out):
            out.append(value)
    return out


def _qty(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def draft_from(header: Dict[str, Any], items: Iterable[Dict[str, Any]],
               customer: Optional[Dict[str, Any]] = None,
               prices: Optional[Dict[str, float]] = None,
               rates: Optional[Dict[str, float]] = None,
               wording: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """One order, priced the way the CSV export prices it, as the draft the
    function sends to Xero.

    The price is the one on the work order line; a line without one (an
    order raised on a phone) is priced from `prices` / `rates`, which are the
    customer's tier's. The description is the invoice wording
    (invoice_wording.py), never the worksheet's.

    Returns {"invoice": ..., "hash": ..., "unpriced": n}. A line nothing can
    price is listed separately rather than dropped: it goes on the draft at
    $0 marked NO PRICE, so somebody sees it, and stops the invoice being
    approved until the price is on the order. The hash is of everything sent,
    so an unchanged order is not sent again.
    """
    from . import invoice_wording as _wording
    from . import pricing as _pricing
    lines = _pricing.quote_lines(list(items or []), prices, rates)
    priced, unpriced = [], []
    for line in lines:
        qty = _qty(line.get("quantity"))
        if qty <= 0:
            continue
        line["description"] = _wording.describe(line["item"], wording)
        price = _qty(line.get("unit_price"))
        if line.get("source") and price > 0:
            priced.append({"description": str(line.get("description") or "Filter"),
                           "quantity": qty,
                           "unit_amount": round(price, 4),
                           "item_code": str(line.get("part_number") or "")})
        else:
            unpriced.append({"description": str(line.get("description") or "Filter"),
                             "quantity": qty})
    fee = _pricing.delivery_fee(header, customer)
    if fee:
        priced.append({"description": "Delivery", "quantity": 1.0,
                       "unit_amount": fee, "item_code": _pricing.DELIVERY_CODE})
    # Xero numbers the invoice itself, carrying on from its own sequence; the
    # customer's purchase order number - the order number on the worksheet -
    # goes in the Reference, which is what they look for.
    po = str(header.get("Order Number") or "").strip()
    invoice = {
        "contact_id": str((customer or {}).get("xero_contact_id") or ""),
        "contact_names": contact_names(customer, header),
        "date": iso_date(header.get("Date Ordered") or ""),
        "number": "",
        "reference": po or str(header.get("Job") or "").strip(),
        "terms": str((customer or {}).get("payment_terms") or ""),
        "lines": priced,
        "unpriced": unpriced,
    }
    digest = hashlib.sha1(_json.dumps(invoice, sort_keys=True).encode("utf-8"))
    return {"invoice": invoice, "hash": digest.hexdigest(),
            "unpriced": len(unpriced)}


# ── Keeping Xero up to date, in the background ───────────────────────────────

class Sync:
    """Sends orders to Xero as drafts, and gets completed jobs approved and
    emailed, every few minutes and straight after an order changes.

    Every PC with Xero switched on runs one. They do not trip over each
    other: an order is held by one PC while it is worked on, and an order
    already in Xero as it stands is not sent again.

    Nothing here touches Tk. `prices(customer)` returns (prices, rates) for
    that customer's tier; `customer(name)` returns the customer's record or
    {}; `prepare(items)` fills in what a line needs to be priced (part
    numbers on web orders).
    """

    EVERY = 180          # seconds between rounds
    BATCH = 10           # orders priced per round; Xero allows 60 calls/min

    def __init__(self, prices, customer, prepare=None, is_on=None,
                 on_round=None):
        import threading
        self._prices = prices
        self._customer = customer
        self._prepare = prepare or (lambda items: items)
        self._is_on = is_on or (lambda: True)
        self._on_round = on_round
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self.last: Dict[str, Any] = {}
        self._status_at = 0.0

    def start(self):
        import threading
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="xero-sync")
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def nudge(self):
        """An order was saved or changed: go now rather than at the next
        round (a few seconds later, so a batch of changes is one round)."""
        self._wake.set()

    def _loop(self):
        import time
        self._stop.wait(20)                 # let the app finish starting
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception as exc:        # never take the app down
                self.last = {"error": str(exc)}
            self._wake.wait(self.EVERY)
            if self._wake.is_set():
                self._wake.clear()
                time.sleep(5)

    def run_once(self) -> Dict[str, Any]:
        import time
        if not (self._is_on() and _db.is_ready() and _db.current_user()):
            return {}
        # Once a day, ask: it keeps the sign-in from lapsing.
        if time.monotonic() - self._status_at > 6 * 3600 or not self._status_at:
            self._status_at = time.monotonic()
            status()
        made, problems = 0, []
        rows = _db.xero_orders_to_draft(self.BATCH)
        for row in rows:
            header = dict(row.get("header") or {})
            header.setdefault("Customer Name", row.get("customer_name") or "")
            items = self._prepare(list(row.get("items") or []))
            customer = self._customer(header.get("Customer Name") or "") or {}
            prices, rates = self._prices(customer)
            built = draft_from(header, items, customer, prices, rates)
            out = push_draft(row["order_id"], built, row.get("source_md5") or "")
            if out.get("error"):
                problems.append(out["error"])
                if "not connected" in out["error"].lower():
                    break
            elif not out.get("busy"):
                made += 1
        swept: Dict[str, Any] = {}
        if _db.xero_due_count() > 0:
            swept = sweep()
            problems.extend(swept.get("problems") or [])
            if swept.get("error"):
                problems.append(swept["error"])
        self.last = {"drafted": made, "sent": int(swept.get("done") or 0),
                     "problems": problems}
        if self._on_round:
            try:
                self._on_round(self.last)
            except Exception:
                pass
        return self.last
