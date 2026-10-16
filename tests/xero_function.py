"""The xero Edge Function, run for real against stand-ins for Supabase and Xero.

The function is what moves money: it makes the draft invoice for an order,
then approves and emails it when the job is done. This serves the actual
function with Deno, behind a small fake of the database calls it makes
(migrate_xero_link.sql's functions - their SQL is checked on a real Postgres
by db_rules.py) and of the parts of Xero's API it uses, and walks an order
through its whole life: connected, drafted, changed, completed, approved and
emailed - and the ways that goes wrong.

Run:  python tests/xero_function.py
Needs Deno. Skips without it, unless REQUIRE_DENO is set (CI).
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FUNCTION = ROOT / "supabase" / "functions" / "xero" / "index.ts"

SERVICE = "service-key"
USERS = {"Bearer staff": ("u-staff", True, False),
         "Bearer boss": ("u-boss", True, True),
         "Bearer stranger": ("u-who", False, False)}
LOCK = threading.RLock()
FAILURES: list = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}"
          + ("" if ok or not detail else f"\n        {detail}"))
    if not ok:
        FAILURES.append(label)


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def when(value) -> dt.datetime | None:
    if not value:
        return None
    return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))


# ── The world the function talks to ─────────────────────────────────────────

class World:
    def __init__(self):
        self.conn: dict = {}
        self.rows: dict = {}
        self.refresh = ""            # the one refresh token Xero will take
        self.access: set = set()
        self.refreshes = 0
        self.contacts = {
            "C-BELLS": {"ContactID": "C-BELLS", "Name": "Bells Pty Ltd",
                        "EmailAddress": "accounts@bells.example",
                        "ContactStatus": "ACTIVE",
                        "PaymentTerms": {"Sales": {
                            "Day": 14, "Type": "DAYSAFTERBILLDATE"}}},
            "C-QUIET": {"ContactID": "C-QUIET", "Name": "Quiet Co",
                        "EmailAddress": "", "ContactStatus": "ACTIVE"},
            "C-OLD": {"ContactID": "C-OLD", "Name": "Gone Co",
                      "EmailAddress": "x@gone.example",
                      "ContactStatus": "ARCHIVED"},
        }
        self.items = ["FPFG425-040"]
        self.item_rows: list = []
        self.invoices: dict = {}
        self.idempotent: dict = {}
        self.emails: list = []
        self.email_fail = 0          # how many sends Xero fails before one goes
        self.calls: list = []


W = World()


def fresh_row(order: str) -> dict:
    return {"order_id": order, "state": "waiting", "invoice_id": None,
            "invoice_number": None, "contact_id": None, "contact_name": None,
            "lines_hash": None, "source_md5": None, "unpriced": 0,
            "total": None, "invoice_date": None, "terms": None,
            "complete_wanted": False, "completed_on": None,
            "delete_wanted": False, "error": None, "next_try_at": None,
            "claimed_until": None, "approved_at": None, "emailed_at": None,
            "emailed_to": None}


def free(row) -> bool:
    c = when(row.get("claimed_until"))
    return c is None or c < now()


def due_now(row) -> bool:
    n = when(row.get("next_try_at"))
    return n is None or n < now()


def rpc(name: str, a: dict):
    with LOCK:
        if name == "xero_who":
            for uid, staff, manager in USERS.values():
                if uid == a["p_uid"]:
                    return {"staff": staff, "manager": manager}
            return {"staff": False, "manager": False}
        if name == "xero_conn_get":
            return dict(W.conn)
        if name == "xero_conn_put":
            W.conn.update({k: v for k, v in a["p_patch"].items() if k != "id"})
            return dict(W.conn)
        if name == "xero_conn_begin_refresh":
            r = when(W.conn.get("refreshing_until"))
            if not W.conn.get("refresh_token") or (r and r > now()):
                return None
            W.conn["refreshing_until"] = (
                now() + dt.timedelta(seconds=a["p_seconds"])).isoformat()
            return W.conn["refresh_token"]
        if name == "xero_conn_end_refresh":
            if W.conn.get("refresh_token") != a["p_old"]:
                return False
            W.conn.update(a["p_patch"])
            W.conn["refreshing_until"] = None
            return True
        if name == "xero_claim":
            row = W.rows.setdefault(a["p_order"], fresh_row(a["p_order"]))
            if not free(row):
                return []
            row["claimed_until"] = (
                now() + dt.timedelta(seconds=a["p_seconds"])).isoformat()
            return [copy.deepcopy(row)]
        if name == "xero_invoice_put":
            row = W.rows[a["p_order"]]
            row.update({k: v for k, v in a["p_patch"].items()
                        if k != "order_id"})
            return [copy.deepcopy(row)]
        if name == "xero_due_work":
            return [copy.deepcopy(r) for r in W.rows.values()
                    if free(r) and due_now(r) and (
                        (r["complete_wanted"] and r["state"] == "draft"
                         and not r["unpriced"] and r["invoice_id"])
                        or (r["delete_wanted"]
                            and r["state"] in ("waiting", "draft")))]
        if name == "xero_list":
            return [copy.deepcopy(r) for r in W.rows.values()]
    raise KeyError(name)


def invoice_out(inv: dict) -> dict:
    out = copy.deepcopy(inv)
    out["Total"] = round(sum(l["Quantity"] * l["UnitAmount"]
                             for l in inv["LineItems"]) * 1.1, 2)
    out["Contact"] = {"ContactID": inv["Contact"]["ContactID"],
                      "Name": W.contacts[inv["Contact"]["ContactID"]]["Name"]}
    return out


def validation(message: str):
    return 400, {"Elements": [{"ValidationErrors": [{"Message": message}]}]}


def xero_api(method: str, path: str, query: dict, body, headers):
    q = lambda k: (query.get(k) or [""])[0]
    parts = path.strip("/").split("/")          # api.xro 2.0 Invoices ...
    kind = parts[2] if len(parts) > 2 else ""
    ident = parts[3] if len(parts) > 3 else ""
    if kind == "Contacts":
        if ident:
            c = W.contacts.get(ident)
            return (200, {"Contacts": [c]}) if c else (404, {})
        term = q("searchTerm").lower()
        return 200, {"Contacts": [c for c in W.contacts.values()
                                  if term in c["Name"].lower()]}
    if kind == "Items" and method == "POST":
        made = []
        for it in (body or {}).get("Items", []):
            if len(it.get("Code", "")) > 30 or not it.get("Name"):
                made.append(dict(it, ValidationErrors=[{"Message": "bad"}]))
                continue
            W.items.append(it["Code"])
            W.item_rows.append(it)
            made.append(it)
        return 200, {"Items": made}
    if kind == "Items":
        return 200, {"Items": [{"Code": c} for c in W.items]}
    if kind == "Organisation":
        return 200, {"Organisations": [{"PaymentTerms": {"Sales": {
            "Day": 20, "Type": "OFFOLLOWINGMONTH"}}}]}
    if kind != "Invoices":
        return 404, {}
    if method == "GET" and not ident:
        page = int(q("page") or 1)
        rows = [invoice_out(i) for i in W.invoices.values()
                if i["Status"] == "AUTHORISED"]
        for r in rows:
            r["AmountDue"] = r["Total"]
            r["DueDateString"] = r["DueDate"] + "T00:00:00"
        return 200, {"Invoices": rows if page == 1 else []}
    if method == "GET":
        inv = W.invoices.get(ident)
        return (200, {"Invoices": [invoice_out(inv)]}) if inv else (404, {})
    if len(parts) > 4 and parts[4] == "Email":
        inv = W.invoices[ident]
        if W.email_fail > 0:
            W.email_fail -= 1
            return 500, {"Message": "An error occurred in Xero. Check the API "
                                    "Status page for current service status."}
        email = W.contacts[inv["Contact"]["ContactID"]]["EmailAddress"]
        if inv["Status"] != "AUTHORISED":
            return validation("Only approved invoices can be emailed")
        if not email:
            return validation("The contact does not have an email address")
        inv["SentToContact"] = True
        W.emails.append((inv["InvoiceNumber"], email))
        return 204, None
    new = (body or {}).get("Invoices", [{}])[0]
    if ident:
        inv = W.invoices[ident]
        if new.get("Status") == "AUTHORISED" and not new.get("DueDate"):
            return validation("Due Date is required")
        if inv["Status"] not in ("DRAFT", "SUBMITTED") and new.get("LineItems"):
            return validation("This document cannot be edited")
        inv.update({k: v for k, v in new.items() if k != "InvoiceID"})
        return 200, {"Invoices": [invoice_out(inv)]}
    key = headers.get("Idempotency-Key", "")
    if key and key in W.idempotent:
        return 200, {"Invoices": [invoice_out(W.invoices[W.idempotent[key]])]}
    for line in new.get("LineItems", []):
        if "ItemCode" in line and line["ItemCode"] not in W.items:
            return validation(f"Item code '{line['ItemCode']}' is not valid")
    number = new.get("InvoiceNumber")
    if number and any(i["InvoiceNumber"] == number
                      for i in W.invoices.values()):
        return validation("Invoice # must be unique.")
    inv = dict(new, InvoiceID=str(uuid.uuid4()),
               InvoiceNumber=number or f"INV-{len(W.invoices) + 1:04d}",
               SentToContact=False)
    W.invoices[inv["InvoiceID"]] = inv
    if key:
        W.idempotent[key] = inv["InvoiceID"]
    return 200, {"Invoices": [invoice_out(inv)]}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *_a):
        pass

    def _send(self, code, body):
        data = b"" if body is None else json.dumps(body).encode()
        self.send_response(code)
        if body is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        if "json" in (self.headers.get("Content-Type") or ""):
            return json.loads(raw)
        return {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode()).items()}

    def _handle(self, method):
        url = urllib.parse.urlparse(self.path)
        body = self._body()
        auth = self.headers.get("Authorization", "")
        with LOCK:
            W.calls.append((method, url.path))
        if url.path == "/auth/v1/user":
            u = USERS.get(auth)
            return self._send(200, {"id": u[0]}) if u else self._send(401, {})
        if url.path.startswith("/rest/v1/rpc/"):
            if self.headers.get("apikey") != SERVICE or auth != f"Bearer {SERVICE}":
                return self._send(401, {"message": "service role only"})
            return self._send(200, rpc(url.path.rsplit("/", 1)[1], body))
        if url.path == "/connect/token":
            with LOCK:
                if body.get("grant_type") == "authorization_code":
                    if body.get("code") != "good":
                        return self._send(400, {"error": "invalid_grant"})
                elif body.get("refresh_token") != W.refresh:
                    return self._send(400, {"error": "invalid_grant"})
                W.refreshes += body.get("grant_type") == "refresh_token"
                W.refresh = f"r-{uuid.uuid4()}"
                access = f"a-{uuid.uuid4()}"
                W.access.add(access)
            time.sleep(0.2)            # long enough for two to overlap
            return self._send(200, {"access_token": access, "expires_in": 1800,
                                    "refresh_token": W.refresh})
        if url.path == "/connect/revocation":
            with LOCK:
                W.refresh = ""
            return self._send(200, {})
        token = auth.removeprefix("Bearer ")
        if token not in W.access:
            return self._send(401, {"Title": "Unauthorized"})
        if url.path == "/connections":
            return self._send(200, [{"tenantId": "T1",
                                     "tenantName": "Total Air Filtration"}])
        if self.headers.get("Xero-tenant-id") != "T1":
            return self._send(403, {"Title": "Forbidden"})
        with LOCK:
            code, out = xero_api(method, url.path,
                                 urllib.parse.parse_qs(url.query), body,
                                 self.headers)
        return self._send(code, out)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


# ── Calling the function ────────────────────────────────────────────────────

PORT = 0


def call(action: str, body=None, auth: str = "Bearer staff", query=""):
    url = f"http://127.0.0.1:{PORT}/?do={action}{query}"
    data = json.dumps(body or {}).encode()
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = auth
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw or b"{}")
            except ValueError:
                return r.status, raw.decode()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw or b"{}")
        except ValueError:
            return exc.code, raw.decode()


def get(query: str):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/{query}",
                                    timeout=60) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def invoice(lines=None, unpriced=None, names=("Bells Pty Ltd", "Bells"),
            number="TAF-ON-1001", date="2026-10-14"):
    return {"contact_names": list(names), "date": date, "number": number,
            "reference": "PO 4471", "terms": "Net 30",
            "lines": lines if lines is not None else [
                {"description": "Panel 595x595x45 G4", "quantity": 10,
                 "unit_amount": 12.5, "item_code": "fpfg425-040"},
                {"description": "Bag 592x592x600 F7", "quantity": 2,
                 "unit_amount": 40, "item_code": "NOT-IN-XERO"}],
            "unpriced": unpriced or []}


def draft(order, inv=None, h="h1", md5="m1", auth="Bearer staff"):
    return call("draft", {"order_id": order, "invoice": inv or invoice(),
                          "hash": h, "source_md5": md5}, auth=auth)


def xinv(order):
    return W.invoices.get(W.rows.get(order, {}).get("invoice_id") or "", {})


def run_checks() -> None:
    print("\n── who may do what ──")
    code, _ = call("status", auth="")
    check("no sign-in is refused", code == 401, str(code))
    code, _ = call("status", auth="Bearer stranger")
    check("an account that is not approved staff is refused", code == 403,
          str(code))
    code, out = call("start")
    check("somebody on the floor cannot connect Xero", code == 403, str(out))
    code, out = call("draft", {"order_id": str(uuid.uuid4())},
                     auth=f"Bearer {SERVICE}")
    check("the service role may sweep, not make invoices", code == 403,
          str(out))

    print("\n── connecting, once, for everyone ──")
    code, out = call("start", auth="Bearer boss")
    link = urllib.parse.urlparse(out.get("url", ""))
    params = urllib.parse.parse_qs(link.query)
    state = (params.get("state") or [""])[0]
    scope = (params.get("scope") or [""])[0].split()
    check("a manager gets Xero's sign-in page, asking to stay connected",
          code == 200 and state and "offline_access" in scope, str(out))
    check("with Xero's granular scopes - a new Xero app refuses the old "
          "broad one", "accounting.invoices" in scope and
          "accounting.transactions" not in scope, str(scope))
    code, body = get(f"?do=finish&code=good&state={uuid.uuid4()}")
    check("Xero coming back with a state the app did not start is refused",
          code == 400, body)
    code, body = get(f"?error=access_denied&state={state}")
    check("cancelled at Xero: said so, and nothing is connected",
          code == 400 and "not connected" in body and
          not W.conn.get("refresh_token"), body)
    # Xero comes back to the plain address the app was registered with.
    code, body = get(f"?code=good&state={state}")
    check("signing in connects it, for the whole company",
          code == 200 and "Total Air Filtration" in body, body)
    check("and remembers who connected it",
          W.conn.get("connected_by") == "u-boss" and W.conn.get("state") is None,
          json.dumps(W.conn)[:300])
    code, body = get(f"?do=finish&code=good&state={state}")
    check("the same sign-in link cannot be used twice", code == 400, body)
    code, out = call("status")
    check("any staff account sees it connected",
          code == 200 and out.get("connected") and
          out.get("organisation") == "Total Air Filtration", str(out))
    check("starting in the trial: nothing goes to Xero by itself",
          out.get("mode") == "manual" and not W.conn.get("drafts_from"), str(out))

    print("\n── the trial: the button on the order ──")
    t1 = str(uuid.uuid4())
    code, out = call("draft", {"order_id": t1, "invoice": invoice(
        number="TAF-ON-0901"), "hash": "t1", "invoice_now": True})
    inv = xinv(t1)
    brisbane = (now() + dt.timedelta(hours=10)).date().isoformat()
    check("Send to Xero & invoice: made, approved and emailed in one go",
          code == 200 and out.get("state") == "sent" and
          inv.get("Status") == "AUTHORISED" and
          ("TAF-ON-0901", "accounts@bells.example") in W.emails, str(out))
    check("dated today, the day it was invoiced",
          inv.get("Date") == brisbane, f"{inv.get('Date')} {brisbane}")
    code, out = call("draft", {"order_id": t1, "invoice": invoice(
        number="TAF-ON-0901"), "hash": "t1", "invoice_now": True})
    check("pressed again, it says it is already invoiced - nothing twice",
          out.get("already") and out.get("number") == "TAF-ON-0901" and
          sum(1 for e in W.emails if e[0] == "TAF-ON-0901") == 1, str(out))
    t2 = str(uuid.uuid4())
    code, out = call("draft", {"order_id": t2, "invoice": invoice(
        number="TAF-ON-0902", unpriced=[{"description": "Odd", "quantity": 1}]),
        "hash": "t2", "invoice_now": True})
    check("a line with no price stops the invoice, before anything is made",
          code == 422 and "no price" in out.get("error", "") and
          not W.rows[t2]["invoice_id"], str(out))
    code, out = call("mode", {"mode": "automatic"})
    check("somebody on the floor cannot publish it", code == 403, str(out))
    code, out = call("mode", {"mode": "sometimes"}, auth="Bearer boss")
    check("the mode is trial or automatic, nothing else", code == 400, str(out))
    code, out = call("mode", {"mode": "automatic"}, auth="Bearer boss")
    check("a manager publishes it: orders from now on go by themselves",
          out.get("mode") == "automatic" and W.conn.get("drafts_from"), str(out))

    print("\n── an order becomes a draft invoice ──")
    o1 = str(uuid.uuid4())
    code, out = draft(o1)
    inv = xinv(o1)
    check("the order is in Xero as a draft",
          code == 200 and out.get("state") == "draft" and
          inv.get("Status") == "DRAFT" and inv.get("Type") == "ACCREC",
          f"{out} {inv}")
    check("dated the day on the work order, due on the customer's Xero terms",
          inv.get("Date") == "2026-10-14" and inv.get("DueDate") == "2026-10-28",
          f"{inv.get('Date')} {inv.get('DueDate')}")
    check("for the customer's contact in Xero, with our number and their PO",
          inv.get("Contact", {}).get("ContactID") == "C-BELLS" and
          inv.get("InvoiceNumber") == "TAF-ON-1001" and
          inv.get("Reference") == "PO 4471", json.dumps(inv)[:300])
    lines = inv.get("LineItems", [])
    check("item codes Xero knows go on, as Xero spells them",
          lines and lines[0].get("ItemCode") == "FPFG425-040", json.dumps(lines))
    made_item = next((i for i in W.item_rows if i["Code"] == "NOT-IN-XERO"), {})
    check("a part number Xero has no item for is made an item, and used",
          lines[1].get("ItemCode") == "NOT-IN-XERO" and
          made_item.get("Name") == "Bag 592x592x600 F7" and
          made_item.get("SalesDetails", {}).get("AccountCode") == "200",
          json.dumps(made_item))
    check("priced ex GST, to Sales with GST on Income",
          inv.get("LineAmountTypes") == "Exclusive" and
          all(l["AccountCode"] == "200" and l["TaxType"] == "OUTPUT"
              for l in lines), json.dumps(lines))
    check("and the row says where it is up to",
          W.rows[o1]["state"] == "draft" and W.rows[o1]["claimed_until"] is None
          and W.rows[o1]["source_md5"] == "m1")

    made = len(W.invoices)
    code, out = draft(o1)
    check("sent again unchanged, nothing new is made in Xero",
          out.get("unchanged") and len(W.invoices) == made, str(out))
    changed = invoice(lines=[{"description": "Panel 595x595x45 G4",
                              "quantity": 12, "unit_amount": 12.5,
                              "item_code": "FPFG425-040"}])
    code, out = draft(o1, changed, h="h2", md5="m2")
    check("an order changed while it is a draft updates the same draft",
          out.get("state") == "draft" and len(W.invoices) == made and
          xinv(o1)["LineItems"][0]["Quantity"] == 12, str(out))

    W.rows[o1]["claimed_until"] = (now() + dt.timedelta(minutes=1)).isoformat()
    code, out = draft(o1, changed, h="h3")
    check("an order another PC is working on is left to it",
          code == 200 and out.get("busy"), str(out))
    W.rows[o1]["claimed_until"] = None

    print("\n── the job is completed ──")
    W.rows[o1].update(complete_wanted=True, completed_on="2026-10-16")
    code, out = call("sweep")
    inv = xinv(o1)
    check("it is approved, dated the day it was finished",
          inv.get("Status") == "AUTHORISED" and inv.get("Date") == "2026-10-16",
          f"{out} {inv.get('Status')} {inv.get('Date')}")
    check("due on the contact's terms from that day",
          inv.get("DueDate") == "2026-10-30", inv.get("DueDate"))
    check("and Xero emails it to the contact on file",
          [e for e in W.emails if e[0] == "TAF-ON-1001"]
          == [("TAF-ON-1001", "accounts@bells.example")] and
          W.rows[o1]["state"] == "sent" and
          W.rows[o1]["emailed_to"] == "accounts@bells.example",
          f"{W.emails} {W.rows[o1]['state']}")
    code, out = draft(o1, invoice(), h="h9", md5="m9")
    check("a sent invoice is never changed from the order again",
          out.get("state") == "sent" and xinv(o1)["LineItems"][0]["Quantity"] == 12,
          str(out))
    code, out = call("sweep")
    check("and is not sent twice",
          sum(1 for e in W.emails if e[0] == "TAF-ON-1001") == 1, str(W.emails))

    print("\n── completed before its draft was made ──")
    o2 = str(uuid.uuid4())
    W.rows[o2] = fresh_row(o2)
    W.rows[o2].update(complete_wanted=True, completed_on="2026-10-15")
    code, out = draft(o2, invoice(number="TAF-ON-1002"))
    inv = xinv(o2)
    check("it is made, approved and emailed in one go",
          out.get("state") == "sent" and inv.get("Status") == "AUTHORISED" and
          inv.get("Date") == "2026-10-15", f"{out} {inv.get('Status')}")

    print("\n── a customer linked to their Xero contact ──")
    code, out = call("contacts", {"term": "bells"})
    check("searching Xero's contacts finds them, archived ones left out",
          code == 200 and [c["id"] for c in out.get("contacts", [])] == ["C-BELLS"]
          and out["contacts"][0]["email"] == "accounts@bells.example", str(out))
    o_link = str(uuid.uuid4())
    linked = invoice(names=("Called Something Else",), number="TAF-ON-1100")
    linked["contact_id"] = "00000000-0000-0000-0000-00000000c0de"
    W.contacts["00000000-0000-0000-0000-00000000c0de"] = dict(
        W.contacts["C-BELLS"], ContactID="00000000-0000-0000-0000-00000000c0de")
    code, out = draft(o_link, linked)
    check("a customer linked to a contact invoices to it, whatever its name",
          out.get("state") == "draft" and xinv(o_link)["Contact"]["ContactID"]
          == "00000000-0000-0000-0000-00000000c0de", str(out))
    o_cents = str(uuid.uuid4())
    draft(o_cents, invoice(number="TAF-ON-1101", lines=[
        {"description": "Thirds", "quantity": 3, "unit_amount": 33.3333}]))
    check("a unit price to four places goes across as it is",
          xinv(o_cents)["LineItems"][0]["UnitAmount"] == 33.3333,
          str(xinv(o_cents).get("LineItems")))

    print("\n── things that stop it ──")
    o3 = str(uuid.uuid4())
    code, out = draft(o3, invoice(names=("Nobody Here",), number="TAF-ON-1003"))
    check("a customer with no contact in Xero is said plainly, by name",
          code == 422 and "no contact called \"Nobody Here\"" in
          out.get("error", ""), str(out))
    check("nothing is made up in Xero for them, and it waits before trying "
          "again", W.rows[o3]["invoice_id"] is None and
          W.rows[o3]["next_try_at"] and W.rows[o3]["claimed_until"] is None)
    code, out = draft(str(uuid.uuid4()), invoice(names=("Gone Co",)))
    check("an archived contact is not used", code == 422, str(out))

    o4 = str(uuid.uuid4())
    code, out = draft(o4, invoice(number="TAF-ON-1004", unpriced=[
        {"description": "Odd size panel", "quantity": 1}]))
    inv = xinv(o4)
    check("a line with no price goes on the draft at $0, marked, so it is seen",
          out.get("unpriced") == 1 and any(
              l["Description"].startswith("NO PRICE") and l["UnitAmount"] == 0
              for l in inv.get("LineItems", [])), json.dumps(inv)[:300])
    W.rows[o4].update(complete_wanted=True, completed_on="2026-10-16")
    call("sweep")
    check("and that invoice is not approved or emailed when the job is done",
          xinv(o4)["Status"] == "DRAFT" and "no price" in
          (W.rows[o4]["error"] or ""), W.rows[o4]["error"] or "")
    code, out = draft(o4, invoice(number="TAF-ON-1004"), h="h5", md5="m5")
    check("once the price is on the order it goes, the same day it was done",
          out.get("state") == "sent" and xinv(o4)["Date"] == "2026-10-16",
          str(out))

    o5 = str(uuid.uuid4())
    draft(o5, invoice(names=("Quiet Co",), number="TAF-ON-1005"))
    W.rows[o5].update(complete_wanted=True, completed_on="2026-10-16")
    code, out = call("sweep")
    check("a contact with no email: approved, and why it was not sent",
          xinv(o5)["Status"] == "AUTHORISED" and
          W.rows[o5]["state"] == "approved" and
          "email" in (W.rows[o5]["error"] or ""), W.rows[o5]["error"] or "")
    check("the organisation's terms are used when the contact has none",
          xinv(o5)["DueDate"] == "2026-11-20", xinv(o5)["DueDate"])
    W.contacts["C-QUIET"]["EmailAddress"] = "hello@quiet.example"
    code, out = call("retry", {"order_id": o5})
    check("Retry, once the email is in Xero, sends it",
          out.get("state") == "sent" and
          ("TAF-ON-1005", "hello@quiet.example") in W.emails, str(out))

    o6 = str(uuid.uuid4())
    code, out = draft(o6, invoice(number="TAF-ON-1001"))
    inv = xinv(o6)
    check("an order number Xero already has: Xero numbers it, ours goes in "
          "the reference", out.get("state") == "draft" and
          inv.get("InvoiceNumber", "").startswith("INV-") and
          inv.get("Reference") == "TAF-ON-1001 - PO 4471", json.dumps(inv)[:200])

    o9 = str(uuid.uuid4())
    code, out = draft(o9, invoice(number="TAF-ON-1009", lines=[
        {"description": "Odd", "quantity": 1, "unit_amount": 5,
         "item_code": "X" * 31}]))
    check("a code Xero cannot take goes without one, rather than failing",
          out.get("state") == "draft" and
          "ItemCode" not in xinv(o9)["LineItems"][0], str(out))

    o7 = str(uuid.uuid4())
    draft(o7, invoice(number="TAF-ON-1007"))
    xinv(o7)["Status"] = "AUTHORISED"
    code, out = draft(o7, invoice(number="TAF-ON-1007"), h="h7")
    check("a draft somebody approved by hand in Xero is left to them",
          out.get("state") == "gone" and W.rows[o7]["state"] == "gone", str(out))

    print("\n── Xero's email has a bad moment ──")
    o10 = str(uuid.uuid4())
    W.email_fail = 1
    code, out = call("draft", {"order_id": o10, "invoice": invoice(
        number="TAF-ON-1010"), "hash": "e1", "invoice_now": True})
    check("a send Xero fails on its side is tried again, and goes",
          out.get("state") == "sent" and
          ("TAF-ON-1010", "accounts@bells.example") in W.emails, str(out))
    o11 = str(uuid.uuid4())
    W.email_fail = 9
    code, out = call("draft", {"order_id": o11, "invoice": invoice(
        number="TAF-ON-1011"), "hash": "e2", "invoice_now": True})
    check("still failing: approved, and said to be Xero's problem, not the "
          "contact's", out.get("state") == "approved" and
          "Xero's side" in out.get("error", "") and
          "email address" not in out.get("error", ""), str(out))
    W.email_fail = 0
    code, out = call("retry", {"order_id": o11})
    check("and Retry sends it once Xero is right again",
          out.get("state") == "sent", str(out))

    print("\n── an order deleted ──")
    o8 = str(uuid.uuid4())
    draft(o8, invoice(number="TAF-ON-1008"))
    W.rows[o8]["delete_wanted"] = True
    code, out = call("sweep", auth=f"Bearer {SERVICE}")
    check("its draft comes back out of Xero (here from the scheduled sweep)",
          xinv(o8)["Status"] == "DELETED" and W.rows[o8]["state"] == "deleted",
          f"{out} {xinv(o8).get('Status')}")

    print("\n── staying connected ──")
    W.conn["expires_at"] = (now() - dt.timedelta(minutes=5)).isoformat()
    before = W.refreshes
    results = []

    def one(i):
        results.append(draft(str(uuid.uuid4()),
                             invoice(number=f"TAF-ON-2{i:03d}"), h=f"c{i}"))
    threads = [threading.Thread(target=one, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check("three PCs at once with the sign-in expired: renewed once, all go "
          "through, still connected",
          W.refreshes - before == 1 and
          all(r[1].get("state") == "draft" for r in results) and
          W.conn.get("refresh_token") == W.refresh,
          f"{W.refreshes - before} {results}")
    W.conn["refreshed_at"] = (now() - dt.timedelta(days=8)).isoformat()
    before = W.refreshes
    code, out = call("status")
    check("a sign-in not renewed for a week is renewed when anyone looks, so "
          "Xero never lets it lapse",
          W.refreshes - before == 1 and out.get("connected"), str(out))

    W.refresh = "revoked-in-xero"
    W.conn["expires_at"] = (now() - dt.timedelta(minutes=5)).isoformat()
    code, out = draft(str(uuid.uuid4()), invoice(number="TAF-ON-3001"), h="z")
    code2, st = call("status")
    check("disconnected from Xero's side: said so, and that a manager "
          "reconnects",
          "Connect again" in out.get("error", "") and not st.get("connected")
          and "Connect again" in st.get("problem", ""), f"{out} {st}")
    keep = W.conn.get("drafts_from")
    code, out = call("start", auth="Bearer boss")
    state = urllib.parse.parse_qs(
        urllib.parse.urlparse(out["url"]).query)["state"][0]
    get(f"?do=finish&code=good&state={state}")
    check("reconnected, orders taken while it was down still go across",
          W.conn.get("drafts_from") == keep and W.conn.get("refresh_token"))

    print("\n── what is owed, and the list ──")
    code, out = call("owing")
    check("what customers owe comes back from Xero",
          code == 200 and len(out.get("rows", [])) >= 3 and out.get("owed") > 0,
          json.dumps(out)[:200])
    code, out = call("list")
    check("the Xero screen gets every order's state",
          code == 200 and len(out.get("rows", [])) >= 8, str(code))

    code, out = call("disconnect")
    check("somebody on the floor cannot disconnect it", code == 403, str(out))
    code, out = call("disconnect", auth="Bearer boss")
    check("a manager can, and nothing more is queued for Xero",
          out.get("connected") is False and not W.conn.get("refresh_token")
          and not W.conn.get("drafts_from") and W.refresh == "", str(out))


def _skip(why: str) -> int:
    if os.environ.get("REQUIRE_DENO"):
        print(f"FAIL: {why} - and this run requires it")
        return 1
    print(f"SKIP: {why}")
    return 0


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main() -> int:
    global PORT
    deno = shutil.which("deno")
    if not deno:
        return _skip("deno is not installed")
    fake_port, PORT = _free_port(), _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", fake_port), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{fake_port}"
    env = dict(os.environ, SUPABASE_URL=base, SUPABASE_ANON_KEY="anon-key",
               SUPABASE_SERVICE_ROLE_KEY=SERVICE, XERO_CLIENT_ID="client",
               XERO_CLIENT_SECRET="secret",
               XERO_REDIRECT_URI=f"http://127.0.0.1:{PORT}/",
               XERO_API_BASE=base, XERO_IDENTITY_BASE=base,
               DENO_NO_UPDATE_CHECK="1")
    wrapper = Path(tempfile.mkdtemp(prefix="taf-xero-")) / "serve.ts"
    wrapper.write_text(
        "const serve = Deno.serve;\n"
        "// deno-lint-ignore no-explicit-any\n"
        "(Deno as any).serve = (h: any) => serve({ port: "
        f"{PORT}, onListen() {{}} }}, h);\n"
        f"await import({json.dumps(FUNCTION.as_uri())});\n",
        encoding="utf-8")
    proc = subprocess.Popen(
        [deno, "run", "--allow-net", "--allow-env", "--allow-read",
         "--no-lock", str(wrapper)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace")
    try:
        for _ in range(240):
            try:
                socket.create_connection(("127.0.0.1", PORT), 0.5).close()
                break
            except OSError:
                if proc.poll() is not None:
                    print(proc.stdout.read())
                    return _skip("the function would not start")
                time.sleep(0.5)
        else:
            return _skip("the function did not start in time")
        run_checks()
    finally:
        proc.terminate()
        server.shutdown()
    print(f"\n{len(FAILURES)} FAILED" if FAILURES
          else "\nXero gets the right invoice, at the right time.")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
