"""The staff web app, driven in a real browser.

Everything this page does, it does by talking to Supabase over HTTP — so the
way to test it is to answer those requests with known data and then use the
page the way a person would: sign in, find an order, tick a line off, change a
status.

Nothing here reaches the real database. Every request is served by the stub
below, which also lets a test say "now refuse that one" and check the page
says so instead of quietly carrying on.

Run:  python tests/web_app.py
Needs Playwright and Chromium, which the build machine has. Skips cleanly
where they are missing, the way the GUI smoke test does.
"""
from __future__ import annotations

import datetime as dt
import functools
import http.server
import json
import os
import socketserver
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "docs" / "app" / "index.html").as_uri() + "?k=test-anon-key"

FAILURES: list = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}" + (f"\n        {detail}" if detail else ""))
        FAILURES.append(label)


# ── What the stubbed database holds ─────────────────────────────────────────

PROFILE = {"id": "u1", "full_name": "Kai Brown", "username": "kai",
           "role": "Manager", "approved": True}

ORDERS = [
    {"id": "o1", "customer_name": "Bells Creek", "order_number": "PO-8842",
     "date_ordered": "01/09/2026", "date_due": "01/08/2026",
     "archived": False, "created_at": "2026-09-01T00:00:00Z",
     "n_items": 3, "n_made": 1, "full_name": "Kai Brown",
     "header": {"status": "In Production", "priority": True,
                "Job": "AHU 3",
                "order_notes": [{"ts": "01/09/2026 09:00", "author": "Kai",
                                 "text": "Ring the site before delivery"}]}},
    {"id": "o2", "customer_name": "CAS - Tweed", "order_number": "TAF-ON-0002",
     "date_ordered": "02/09/2026", "date_due": "ASAP",
     "archived": False, "created_at": "2026-09-02T00:00:00Z",
     "n_items": 2, "n_made": 2, "full_name": "Kai Brown",
     "header": {"status": "Complete"}},
    # Still being made. It must never appear on a delivery run, which is the
    # only thing keeping a driver from being sent out with an empty box.
    {"id": "o3", "customer_name": "Pelican Waters", "order_number": "PO-9100",
     "date_ordered": "03/09/2026", "date_due": "31/12/2026",
     "archived": False, "created_at": "2026-09-03T00:00:00Z",
     "n_items": 5, "n_made": 0, "full_name": "Kai Brown",
     "header": {"status": "Pending"}},
]

ITEMS = {
    "o1": [
        {"line_id": "L1", "Quantity": 2, "Filter Type": "V-form",
         "Short": 500, "Long": 600, "Channel": 45, "Media Type": "G4",
         "made": True,
         # Planned by the office: one area, two wraps of one.
         "Packing": {"mode": "manual", "groups": [],
                     "wraps": [{"id": "W1", "quantity": 1},
                               {"id": "W2", "quantity": 1}]}},
        {"line_id": "L2", "Quantity": 1, "Filter Type": "Flat Panel",
         "Short": 300, "Long": 400, "Channel": 50, "Media Type": "F5"},
        {"line_id": "L3", "Quantity": 4, "Filter Type": "Flyscreen",
         "Short": 200, "Long": 200, "Channel": 25, "Media Type": "WASH"},
    ],
    "o2": [],
}


CUSTOMERS = [
    {"id": "c1", "name": "Bells Creek Pty Ltd", "short_name": "Bells Creek",
     "phone": "07 5555 1234", "email": "jobs@bellscreek.com.au",
     "address": "12 Industrial Ave", "suburb": "Caloundra",
     "region": "Sunshine Coast", "payment_terms": "Net 30"},
    {"id": "c2", "name": "CAS - Tweed", "short_name": "CAS - Tweed",
     "phone": "", "email": "", "region": "Northern NSW"},
]

# minimum_on_hand, spelled the way stock_schema.sql spells it. It used to
# say minimum_level here, which is not a column the database has — so the
# page read undefined, nothing was ever low, and this test agreed with it.
STOCK = [
    {"id": "s1", "name": "G4 media roll 1m", "sku": "MED-G4-1M",
     "media_type": "G4", "unit": "m", "stock_on_hand": 42,
     "minimum_on_hand": 20,
     "description": "Pleatable G4 synthetic media on a 20 m roll, one metre "
                    "wide, grey both sides, for panel and pleated filters",
     "image_url": "https://example.supabase.co/storage/v1/object/public/"
                  "stock-images/s1.png"},
    {"id": "s2", "name": "F5 media roll 1m", "sku": "MED-F5-1M",
     "media_type": "F5", "unit": "m", "stock_on_hand": 6,
     "minimum_on_hand": 25},          # low
]

# Off until somebody says otherwise, and off unless the company switch is on
# as well — which is the whole point of there being two of them.
NOTIFY = {"on": False, "company": True}
SUMMARIES: list = []   # summaries the function was asked to send

LOGGED: list = []      # audit_log entries the web app wrote
AUDIT = [
    {"id": 1, "username": "kai", "action": "order_created",
     "details": "O/N: PO-8842 | Customer: Bells Creek | 3 lines",
     "created_at": "2026-09-01T09:00:00Z"},
    {"id": 2, "username": "dan", "action": "prices_imported",
     "details": "412 part numbers",
     "created_at": "2026-09-02T11:20:00Z"},
]

RAISED: list = []      # orders the web app raised
FILES: list = []       # photos and signatures kept against an order
UPLOADED: list = []    # what actually reached Storage

QUOTES = [
    {"id": "q1", "quote_number": "Q-1041", "customer_name": "Bells Creek",
     "reference": "PO-9001", "status": "sent", "total": 1287.5,
     "unpriced_count": 1, "valid_until": "2026-10-31",
     "created_at": "2026-09-01T00:00:00Z", "notes": "Site access via gate 3",
     "items": [
         {"quantity": 4, "description": "V-form G4 500 x 600 x 45",
          "unit_price": 88.5, "line_total": 354.0},
         {"quantity": 2, "description": "Stepped Filter WASH",
          "unit_price": 0, "line_total": 0},
     ]},
    {"id": "q2", "quote_number": "Q-1042", "customer_name": "CAS - Tweed",
     "reference": "", "status": "draft", "total": 210.0, "unpriced_count": 0,
     "created_at": "2026-09-02T00:00:00Z", "items": []},
]


# Supply requests and the bell. Seeded as if the floor had already asked for
# three things, so Kai - a manager - signs in to a red bell.
SUPPLY: list = [
    {"id": "sr1", "item": "Tape", "detail": "50mm foil", "quantity": "3 rolls",
     "urgent": False, "status": "open", "requested_by": "u9",
     "requested_by_name": "Dave Floor", "handled_by_name": "",
     "created_at": "2026-09-24T00:10:00Z"},
    {"id": "sr2", "item": "Rivets", "detail": "4mm pop", "quantity": "1 box",
     "urgent": True, "status": "open", "requested_by": "u9",
     "requested_by_name": "Dave Floor", "handled_by_name": "",
     "created_at": "2026-09-24T00:40:00Z"},
    {"id": "sr3", "item": "Channel", "detail": "45mm", "quantity": "20",
     "urgent": False, "status": "ordered", "requested_by": "u9",
     "requested_by_name": "Dave Floor", "handled_by_name": "Sarah Boss",
     "created_at": "2026-09-23T03:00:00Z"},
]
NOTES: list = [
    {"id": "n1", "kind": "supply_request", "ref_id": "sr2",
     "title": "URGENT: Rivets - 4mm pop", "body": "Dave Floor asked for 1 box",
     "read_at": None, "created_at": "2026-09-24T00:40:00Z"},
    {"id": "n2", "kind": "supply_request", "ref_id": "sr1",
     "title": "Tape - 50mm foil", "body": "Dave Floor asked for 3 rolls",
     "read_at": None, "created_at": "2026-09-24T00:10:00Z"},
    {"id": "n3", "kind": "supply_request", "ref_id": "sr0",
     "title": "Mesh Wire", "body": "Dave Floor asked for 1 roll",
     "read_at": None, "created_at": "2026-09-23T23:00:00Z"},
]
BELL = {"override": None}    # a count to report instead, e.g. 150
# The factory floor (step 44): which switches are on, the QC checks, and
# what the phone sent.
SWITCHES: list = []
QC_LISTS = [{"filter_type": "*", "checks": ["Size checked", "Label on"]}]
TIMERS: list = []
FAULTS: list = []
# Step 49: how-tos, sign-offs, chats and what was done in them.
SOPS = [{"id": "sop1", "title": "Making a V-form", "category": "Floor",
         "filter_type": "V-form", "body": "Cut the media.\nPleat it.",
         "video_url": "https://youtu.be/abc", "version": 2, "file_path": ""},
        {"id": "sop2", "title": "Bracing", "category": "Floor",
         "filter_type": "", "body": "Brace every 300mm.", "version": 1,
         "file_path": ""}]
SOP_READS: list = []
CHAT_RULES = [{"action": "post_board", "min_role": "Manager"},
              {"action": "pin", "min_role": "Admin"}]
CHATS = [{"id": "ch-board", "name": "Noticeboard", "kind": "board",
          "post_min_role": "Employee", "unread": 2, "can_post": True,
          "last_body": "Toolbox talk Friday", "last_author": "Amy"},
         {"id": "ch-g", "name": "Office only", "kind": "group",
          "post_min_role": "Manager", "unread": 0, "can_post": False}]
CHAT_MSGS = [{"id": "m1", "channel_id": "ch-board", "user_id": "u9",
              "author": "Amy Admin", "body": "Toolbox talk Friday", "pinned": True,
              "created_at": "2026-10-16T00:00:00Z"},
             {"id": "m2", "channel_id": "ch-board", "user_id": "u9",
              "author": "Amy Admin", "body": "Bins out", "pinned": False,
              "created_at": "2026-10-16T01:00:00Z"}]
CHAT_CALLS: list = []

# Out the door (step 48): the saved run, the target, and proofs asked for.
RUNS: dict = {}
POD_CALLS: list = []
TARGET = {"target": 60000, "sold": 30000}

# Stock (step 47): the count going on, what was counted, and what the phone
# was told about stock spoken for and prices paid.
TAKES: list = []
COUNTS: dict = {}
APPLIED: list = []

# Planning (step 45): one person in for a few minutes a day, so any order
# fills it.
ROSTER = [{"person": "Dave", "days": [1, 2, 3, 4, 5, 6, 7], "hours": 0.1,
           "makes": True, "active": True}]
REFUSE_MOVE = {"on": False}  # row-level security matching nothing



def _png(width: int, height: int) -> bytes:
    """A plain, wide photo - wider than a card, to show it is shrunk to fit
    rather than cropped."""
    import struct
    import zlib
    row = b"\x00" + b"\x1d\xa1\xe6" * width
    raw = zlib.compress(row * height)

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))

class Stub:
    """Answers what the page asks for, and remembers what it was asked."""

    def __init__(self):
        self.calls: list = []
        self.refuse: dict = {}      # rpc name -> message

    def route(self, route):  # noqa: C901
        req = route.request
        url = req.url
        # post_data itself throws on a binary body — an uploaded photo is not
        # text and asking Playwright to decode it as such raises.
        body = {}
        try:
            raw = req.post_data
        except Exception:
            raw = None
        if raw:
            try:
                body = json.loads(raw)
            except Exception:
                body = {}
        self.calls.append((url, body))

        def send(payload, status=200):
            route.fulfill(status=status, content_type="application/json",
                          headers={"Access-Control-Allow-Origin": "*"},
                          body=json.dumps(payload))

        if "/auth/v1/token" in url:
            if body.get("password") != "correct-horse":
                return send({"msg": "Invalid login credentials"}, 400)
            return send({"access_token": "tok", "refresh_token": "ref",
                         "user": {"id": "u1", "email": "kai@taf.local"}})
        if "/auth/v1/logout" in url:
            return send({})
        if "/rest/v1/profiles" in url and "approved=eq.true" in url:
            return send([PROFILE, {"id": "u2", "full_name": "Dave Floor",
                                   "role": "Employee", "approved": True}])
        if "/rest/v1/sops" in url:
            return send(SOPS)
        if "/rest/v1/sop_reads" in url:
            return send(SOP_READS)
        if "/rest/v1/chat_rules" in url:
            return send(CHAT_RULES)
        if "/rest/v1/chat_messages" in url and req.method == "POST":
            row = dict(body, id="m" + str(len(CHAT_MSGS) + 1), author="Kai Brown",
                       pinned=False, created_at="2026-10-17T00:00:00Z")
            CHAT_MSGS.append(row)
            return send([row], 201)
        if "/rest/v1/chat_messages" in url:
            cid = url.split("channel_id=eq.", 1)[1].split("&")[0]
            rows = [m for m in CHAT_MSGS if m["channel_id"] == cid]
            return send(sorted(rows, key=lambda m: m["created_at"], reverse=True))
        if "/rest/v1/profiles" in url:
            return send([PROFILE])
        if "/rest/v1/notify_settings" in url:
            return send([{"daily_summary": NOTIFY["on"]}])
        if "/functions/v1/proof-of-delivery" in url:
            POD_CALLS.append(dict(body))
            return send({"sent": True, "to": "jobs@bellscreek.com.au"})
        if "/rest/v1/delivery_runs" in url and req.method == "POST":
            if "merge-duplicates" not in (req.headers.get("prefer") or ""):
                return send({"message": "duplicate key"}, 409)
            RUNS[body["run_date"]] = list(body["stops"])
            return send(None, 201)
        if "/rest/v1/delivery_runs" in url:
            day = url.split("run_date=eq.", 1)[1].split("&")[0]
            return send([{"stops": RUNS[day]}] if day in RUNS else [])
        if "/rest/v1/sales_targets" in url:
            return send([{"target": TARGET["target"]}] if TARGET["target"] else [])
        if "/rest/v1/order_values" in url:
            return send([{"value": TARGET["sold"] / 2}, {"value": TARGET["sold"] / 2}])
        if "/functions/v1/daily-summary" in url:
            if not NOTIFY["company"]:
                return send({"sent": 0,
                             "reason": "The morning summary is switched off."})
            SUMMARIES.append(dict(body))
            return send({"sent": 1})
        if "/rest/v1/audit_log" in url and req.method == "POST":
            # audit_log lets everyone write and only managers read, so
            # asking for the row back on the way in is asking to read
            # something the writer may not read. PostgREST refuses the whole
            # statement, and the entry is never written at all.
            if "return=minimal" not in (req.headers.get("prefer") or ""):
                return send({"message": "permission denied for table"
                                        " audit_log"}, 401)
            LOGGED.append(dict(body))
            return route.fulfill(status=201, headers={
                "Access-Control-Allow-Origin": "*"}, body="")
        if "/rest/v1/audit_log" in url:
            if str(PROFILE.get("role", "")).lower() not in (
                    "manager", "admin", "director"):
                return send({"message": "permission denied for table"
                                        " audit_log"}, 401)
            return send(AUDIT + LOGGED)
        if "/rest/v1/notifications" in url:
            return send(NOTES)
        if "/rest/v1/feature_switches" in url:
            return send(SWITCHES)
        if "/rest/v1/qc_checklists" in url:
            return send(QC_LISTS)
        if "/rest/v1/stocktakes" in url and req.method == "POST":
            row = {"id": "tk" + str(len(TAKES)), "name": body.get("name", ""),
                   "finished_at": None}
            TAKES.append(row)
            return send([row])
        if "/rest/v1/stocktakes" in url and req.method == "PATCH":
            for t in TAKES:
                t.update(body)
            return send(TAKES)
        if "/rest/v1/stocktakes" in url:
            return send([t for t in TAKES if not t.get("finished_at")])
        if "/rest/v1/stocktake_counts" in url:
            return send(list(COUNTS.values()))
        if "/rest/v1/stock_reserved" in url:
            return send([{"reserved": 12, "orders": 2}] if "s1" in url else [])
        if "/rest/v1/supplier_prices" in url:
            return send([{"bought_at": "2026-09-01T00:00:00Z",
                          "supplier": "FD Greenwood", "unit_price": 82.5,
                          "po_number": "PO-0007"}] if "s1" in url else [])
        if "/rest/v1/staff_roster" in url:
            return send(ROSTER)
        if "/rest/v1/staff_leave" in url or "/rest/v1/shutdown_days" in url:
            return send([])
        if "/rest/v1/job_rates" in url:
            return send([{"filter_type": "V-form", "minutes_each": 20}])
        if "/rest/v1/workshop_settings" in url:
            return send([{"key": "minutes_per_filter", "value": 15},
                         {"key": "making_share", "value": 1}])
        if "/rest/v1/job_times" in url:
            return send([t for t in TIMERS if not t.get("stopped_at")])
        if "/rest/v1/returns" in url and req.method == "POST":
            FAULTS.append(dict(body))
            return route.fulfill(status=201, headers={
                "Access-Control-Allow-Origin": "*"}, body="")
        if "/rest/v1/stock_item_suppliers" in url:
            return send([{"stock_item_id": "s2", "supplier_id": "s-vul",
                          "supplier_code": "VUL-F5", "preferred": True}])
        if "/rest/v1/suppliers" in url:
            return send([{"id": "s-fdg", "name": "FD Greenwood"},
                         {"id": "s-vul", "name": "Vulcan"}])
        if "/rest/v1/supply_requests" in url and req.method == "PATCH":
            # Like the real policy: a change that is not allowed is not an
            # error, it matches nothing and hands back no rows.
            if REFUSE_MOVE["on"]:
                return send([])
            rid = url.split("id=eq.", 1)[1].split("&")[0]
            row = next((r for r in SUPPLY if r["id"] == rid), None)
            if row is None:
                return send([])
            was = row["status"]
            row["status"] = body.get("status", row["status"])
            row["handled_by_name"] = "Kai Brown"
            # The settle trigger (step 43): once nothing on the request is
            # waiting, its notification comes off every bell.
            key = row.get("batch_id") or row["id"]
            mates = [r for r in SUPPLY if (r.get("batch_id") or r["id"]) == key]
            if was == "open" and not any(r["status"] == "open" for r in mates):
                ids = {r["id"] for r in mates}
                NOTES[:] = [n for n in NOTES if n["ref_id"] not in ids]
            return send([row])
        if "/rest/v1/supply_requests" in url:
            rows = list(SUPPLY)
            if "status=in." in url:
                rows = [r for r in rows if r["status"] in ("open", "ordered")]
            return send(rows)
        if "/rest/v1/orders_list" in url:
            return send(ORDERS)
        if "/rest/v1/customers" in url:
            return send(CUSTOMERS)
        if "/rest/v1/stock_items" in url:
            return send(STOCK)
        if "/rest/v1/quotes" in url and req.method == "PATCH":
            qid = url.split("id=eq.", 1)[1].split("&")[0]
            row = next((x for x in QUOTES if x["id"] == qid), None)
            if row is None:
                return send([])
            row.update(body)
            return send([row])
        if "/rest/v1/quotes" in url:
            return send(QUOTES)
        if "/rest/v1/order_files" in url and req.method == "POST":
            row = dict(body)
            row["id"] = "f" + str(len(FILES))
            row["created_at"] = "2026-09-10T00:00:00Z"
            FILES.append(row)
            return send([row])
        if "/rest/v1/order_files" in url:
            oid = ""
            for part in url.replace("?", "&").split("&"):
                if part.startswith("order_id=eq."):
                    oid = part.split("eq.", 1)[1]
            kind = ""
            for part in url.replace("?", "&").split("&"):
                if part.startswith("kind=eq."):
                    kind = part.split("eq.", 1)[1]
            return send([f for f in FILES if f["order_id"] == oid
                         and (not kind or f.get("kind") == kind)])
        if "/storage/v1/object/public/stock-images/" in url:
            return route.fulfill(status=200, content_type="image/png",
                                 body=_png(400, 150))
        if "/storage/v1/object/sign/" in url:
            return send({"signedURL": "/object/signed/fake.png?token=x"})
        if "/storage/v1/object/" in url:
            UPLOADED.append(url.rsplit("/object/", 1)[1])
            return send({"Key": "ok"})
        if "/rest/v1/orders" in url and req.method == "POST":
            row = dict(body)
            row["id"] = "new-" + str(len(ORDERS))
            row["order_number"] = row.get("order_number") or "TAF-ON-0009"
            RAISED.append(row)
            return send([row])
        if "/rest/v1/orders" in url:
            oid = ""
            for part in url.split("&"):
                if "id=eq." in part:
                    oid = part.split("id=eq.")[1].split("&")[0]
            row = next((o for o in ORDERS if o["id"] == oid), None)
            if row is None:
                return send([])
            return send([{"items": ITEMS.get(oid, []),
                          "header": row.get("header", {})}])
        if "/rest/v1/rpc/" in url:
            name = url.rsplit("/rpc/", 1)[1].split("?")[0]
            if name in self.refuse:
                return send({"message": self.refuse[name]}, 400)
            if name == "set_order_line_made":
                for it in ITEMS.get(body.get("p_order_id"), []):
                    if it.get("line_id") == body.get("p_line_id"):
                        it["made"] = bool(body.get("p_made"))
                        return send("o1")
                return send(None)
            if name == "start_job_timer":
                for t in TIMERS:
                    t["stopped_at"] = t.get("stopped_at") or "now"
                row = {"id": "t" + str(len(TIMERS)), "order_id": body.get("p_order_id"),
                       "line_id": body.get("p_line_id"), "stopped_at": None}
                TIMERS.append(row)
                return send(row)
            if name == "stop_job_timer":
                out = []
                for t in TIMERS:
                    if not t.get("stopped_at"):
                        t["stopped_at"] = "now"
                        t["minutes"] = 3.5
                        out.append(t)
                return send(out)
            if name == "read_sop":
                sop = next(s for s in SOPS if s["id"] == body.get("p_id"))
                SOP_READS.append({"sop_id": sop["id"], "user_id": "u1",
                                  "version": sop["version"]})
                return send(sop["version"])
            if name == "my_chats":
                return send(CHATS)
            if name == "mark_chat_read":
                for c in CHATS:
                    if c["id"] == body.get("p_channel"):
                        c["unread"] = 0
                return send(None)
            if name == "open_direct":
                cid = "dm-" + body.get("p_user", "")
                if not any(c["id"] == cid for c in CHATS):
                    CHATS.append({"id": cid, "name": "Dave Floor", "kind": "direct",
                                  "post_min_role": "Employee", "unread": 0,
                                  "can_post": True})
                CHAT_CALLS.append((name, dict(body)))
                return send(cid)
            if name in ("pin_message", "remove_message", "make_group"):
                CHAT_CALLS.append((name, dict(body)))
                for m in CHAT_MSGS:
                    if m["id"] == body.get("p_id"):
                        if name == "pin_message":
                            m["pinned"] = body.get("p_on")
                        else:
                            m.update(body="", removed_at="2026-10-17T01:00:00Z",
                                     removed_by="Kai Brown")
                return send("g-new" if name == "make_group" else True)
            if name == "count_stock":
                take = next((t for t in TAKES if t["id"] == body.get("p_stocktake")
                             and not t.get("finished_at")), None)
                item = next((s for s in STOCK if s["id"] == body.get("p_item")), None)
                if not take or not item:
                    return send(None)
                COUNTS[item["id"]] = {"item_id": item["id"],
                                      "counted": body.get("p_counted"),
                                      "was": item.get("stock_on_hand")}
                return send("c-" + item["id"])
            if name == "apply_stocktake":
                APPLIED.append(body.get("p_stocktake"))
                return send([])
            if name == "set_order_line_qc":
                for it in ITEMS.get(body.get("p_order_id"), []):
                    if it.get("line_id") == body.get("p_line_id"):
                        it["qc"] = body.get("p_qc")
                        return send(body.get("p_order_id"))
                return send(None)
            if name == "adjust_stock_atomic":
                item = next((s for s in STOCK
                             if s["id"] == body.get("p_item_id")), None)
                if item is None:
                    return send(None)
                qty = float(body.get("p_quantity") or 0)
                kind = body.get("p_type")
                if kind == "count":
                    item["stock_on_hand"] = qty
                elif kind in ("use", "writeoff"):
                    item["stock_on_hand"] -= abs(qty)
                else:
                    item["stock_on_hand"] += abs(qty)
                return send([{"quantity_after": item["stock_on_hand"]}])
            if name == "set_my_daily_summary":
                NOTIFY["on"] = bool(body.get("p_on"))
                return send(NOTIFY["on"])
            if name == "my_unread_count":
                if BELL["override"] is not None:
                    return send(BELL["override"])
                return send(sum(1 for n in NOTES if not n["read_at"]))
            if name == "mark_notifications_read":
                ids = body.get("p_ids")
                n = 0
                for note in NOTES:
                    if not note["read_at"] and (ids is None or note["id"] in ids):
                        note["read_at"] = "2026-09-24T01:00:00Z"
                        n += 1
                return send(n)
            if name == "request_supply":
                # As the database does it: the same reference twice is the
                # same request, handed back rather than filed again.
                ref = body.get("p_client_ref")
                old = next((r for r in SUPPLY
                            if ref and r.get("client_ref") == ref), None)
                if old:
                    return send(old)
                row = {"id": "sr" + str(len(SUPPLY) + 10),
                       "item": body.get("p_item"),
                       "detail": body.get("p_detail", ""),
                       "quantity": body.get("p_quantity", ""),
                       "urgent": bool(body.get("p_urgent")),
                       "note": body.get("p_note", ""), "status": "open",
                       "client_ref": ref, "requested_by": "u1",
                       "requested_by_name": "Kai Brown",
                       "handled_by_name": "",
                       "created_at": "2026-09-24T01:30:00Z"}
                SUPPLY.append(row)
                return send(row)
            if name == "request_supplies":
                ref = body.get("p_client_ref")
                if any(r.get("client_ref", "").startswith(f"{ref}-")
                       for r in SUPPLY):
                    return send([])
                rows = []
                for i, line in enumerate(body.get("p_lines") or []):
                    rows.append({"id": f"sr{len(SUPPLY) + 10}",
                                 "item": line.get("item"),
                                 "detail": line.get("detail", ""),
                                 "quantity": line.get("quantity", ""),
                                 "supplier_id": line.get("supplier_id") or None,
                                 "urgent": bool(body.get("p_urgent")),
                                 "note": body.get("p_note", ""),
                                 "status": "open", "client_ref": f"{ref}-{i}",
                                 "batch_id": f"b-{ref}",
                                 "requested_by": "u1",
                                 "requested_by_name": "Kai Brown",
                                 "handled_by_name": "",
                                 "created_at": "2026-09-24T01:40:00Z"})
                    SUPPLY.append(rows[-1])
                return send(rows)
            if name == "resolve_scan":
                code = str(body.get("p_code") or "").strip().upper()
                hits = []
                for s in STOCK:
                    if str(s.get("sku") or "").upper() == code:
                        hits.append({"kind": "stock", "ref": s["id"],
                                     "label": s["name"], "detail": "Rack A",
                                     "extra": {}})
                for o in ORDERS:
                    if str(o.get("order_number") or "").upper() == code:
                        hits.append({"kind": "order", "ref": o["id"],
                                     "label": o["customer_name"],
                                     "detail": o["header"].get("status", ""),
                                     "extra": {}})
                return send(hits)
            if name == "merge_order_header":
                row = next((o for o in ORDERS
                            if o["id"] == body.get("p_order_id")), None)
                if row:
                    row.setdefault("header", {}).update(body.get("p_patch") or {})
                    return send(row["id"])
                return send(None)
            return send(None)
        return send([])


def wait_for_text(page, where: str, text: str, ms: int = 5000) -> None:
    """Wait until `text` is showing in `where`, and no longer.

    Not wait_for_selector(".ok"): a message from the step before is still on
    screen, so that returns at once with the old one and the check reads the
    wrong message - a test that passes or fails depending on how fast the
    machine is. Judged by check() afterwards either way; a timeout here is
    not the failure, the missing words are.
    """
    try:
        page.wait_for_function(
            "([w, t]) => (document.querySelector(w) || {}).innerText"
            " && document.querySelector(w).innerText.includes(t)",
            arg=[where, text], timeout=ms)
    except Exception:
        pass


def run() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print(f"SKIP: Playwright is not available ({exc})")
        return 0

    with sync_playwright() as pw:
        # The build machine pins a Chromium that may not be the revision this
        # Playwright would download. Use the one that is actually installed
        # rather than fetching another copy on every run.
        installed = Path("/opt/pw-browsers/chromium")
        launch = {"executable_path": str(installed)} if installed.exists() else {}
        try:
            browser = pw.chromium.launch(**launch)
        except Exception as exc:
            print(f"SKIP: no browser to drive ({exc})")
            return 0
        page = browser.new_page(viewport={"width": 900, "height": 900})
        stub = Stub()
        page.route("**/rest/v1/**", stub.route)
        page.route("**/auth/v1/**", stub.route)
        page.route("**/storage/v1/**", stub.route)
        page.route("**/functions/v1/**", stub.route)

        # A thrown exception is a bug. A 400 in the console is not — two of
        # them are this test's own doing, refusing a password and refusing an
        # RPC on purpose, and the page is judged on how it handles those
        # rather than on whether they happened.
        errors: list = []
        page.on("pageerror", lambda e: errors.append("uncaught: " + str(e)))
        page.on("console", lambda m: errors.append("console: " + m.text)
                if (m.type == "error"
                    and "Failed to load resource" not in m.text) else None)

        print("\n── opening it on a phone, with no PC ──")
        # config.js is written by the "Publish the web app key" workflow, so
        # a bare bookmark works on any phone. It is not in the repo, so this
        # writes and removes one to test both states.
        bare = (ROOT / "docs" / "app" / "index.html").as_uri()
        cfg = ROOT / "docs" / "app" / "config.js"
        had_cfg = cfg.exists()
        if had_cfg:
            keep = cfg.read_text(encoding="utf-8")
        try:
            if had_cfg:
                cfg.unlink()
            page.goto(bare)
            page.wait_for_selector("#signin .err")
            check("with no key it names who can fix it",
                  "Publish the web app key"
                  in page.locator("#signin .err").inner_text())
            check("and does not offer a form that cannot work",
                  page.locator("#signin-form").is_hidden())

            cfg.write_text('window.TAF_KEY = "test-anon-key";\n', encoding="utf-8")
            page.goto(bare)
            page.wait_for_selector("#signin-form:not(.hidden)")
            check("once published, a bare bookmark is enough",
                  page.locator("#signin-form").is_visible())
            check("and nothing warns about set-up",
                  page.locator("#signin .err").count() == 0)

            page.evaluate("localStorage.clear()")
            page.goto(bare + "?k=from-the-link")
            page.wait_for_selector("#signin-form:not(.hidden)")
            check("a key on the link still wins",
                  page.evaluate("localStorage.getItem('taf_staff_key')")
                  == "from-the-link")
        finally:
            if had_cfg:
                cfg.write_text(keep, encoding="utf-8")
            elif cfg.exists():
                cfg.unlink()

        print("\n── the contact footer ──")
        # It used to depend on the page defining .taf-contact as a flex row.
        # The page that forgot ran the phone number, the email and the website
        # together into one unreadable line — on a phone, which is where these
        # are read, and next to a sentence telling people to ring us.
        page.goto(PAGE)
        page.wait_for_selector(".taf-footer")
        shape = page.evaluate("""() => {
          const c = document.querySelector('.taf-contact');
          const kids = [...c.children].map(k => k.getBoundingClientRect());
          return {
            display: getComputedStyle(c).display,
            touching: kids.some((k, i) => i && Math.abs(k.left - kids[i-1].right) < 2)
          };
        }""")
        check("the contact details are laid out, not run together",
              shape["display"] == "flex" and not shape["touching"], str(shape))
        check("the phone number is there to ring",
              "3800 3448" in page.locator(".taf-footer").inner_text())

        print("\n── signing in ──")
        page.wait_for_selector("#signin-form")
        check("the app does not show before signing in",
              page.locator("#app").is_hidden())

        # A wrong password must say so, and must not let anyone in.
        page.fill("#email", "kai@taf.local")
        page.fill("#password", "wrong")
        page.click("#signin-go")
        page.wait_for_selector("#signin .err")
        check("a wrong password is refused",
              "did not match" in page.locator("#signin .err").inner_text())
        check("and the app is still hidden", page.locator("#app").is_hidden())

        page.fill("#password", "correct-horse")
        page.click("#signin-go")
        page.wait_for_selector("#app:not(.hidden)", timeout=8000)
        check("the right password gets in", page.locator("#app").is_visible())
        check("it says who is signed in",
              page.locator("#who-name").inner_text() == "Kai Brown")
        check("the password is not left in the box",
              page.input_value("#password") == "")
        check("the key is taken out of the address bar",
              "k=" not in page.url, page.url)

        print("\n── loading, and the badge ──")
        if os.environ.get("TAF_SHOTS"):
            page.screenshot(path=os.path.join(os.environ["TAF_SHOTS"],
                                              "web_boot.png"))
        check("signing in shows the loading screen, the badge turning",
              page.locator("#boot").is_visible()
              and page.eval_on_selector("#boot img",
                                        "i => getComputedStyle(i).animationName")
              == "taf-turn")
        page.wait_for_selector("#boot", state="hidden", timeout=14000)
        check("and it goes once the first screen has loaded",
              page.locator("#screen .card").count() > 0)
        page.wait_for_function(
            "() => document.querySelectorAll('#screen .card.reveal').length > 0",
            timeout=3000)
        rise = page.eval_on_selector(
            "#screen .card.reveal",
            "c => { const s = getComputedStyle(c); return {name: s.animationName,"
            " timeline: s.animationTimeline, opacity: s.opacity}; }")
        check("cards fade and rise into view, driven by the scroll itself",
              rise["name"] == "taf-rise" and "view" in str(rise["timeline"])
              and float(rise["opacity"]) > 0.9, str(rise))
        check("the badge is top left",
              page.eval_on_selector("#brand-badge",
                                    "b => { const r = b.getBoundingClientRect();"
                                    " return r.left < 40 && r.top < 60; }"))
        if os.environ.get("TAF_SHOTS"):
            page.screenshot(path=os.path.join(os.environ["TAF_SHOTS"],
                                              "web_header.png"))
        page.click("#brand-badge")
        check("clicking the badge gives it a full turn",
              page.eval_on_selector("#brand-badge img",
                                    "i => i.classList.contains('spin') && "
                                    "getComputedStyle(i).animationName") == "taf-turn")

        print("\n── today ──")
        page.wait_for_selector("#screen .card")
        text = page.locator("#screen").inner_text()
        check("an overdue order is counted", "Overdue" in text)
        check("the late one is named", "Bells Creek" in text)

        print("\n── raising an order ──")
        page.click('#tabs button[data-tab="new"]')
        page.wait_for_selector("#screen .card")

        # It must not save an order with no customer, and must not save one
        # with no lines — both are orders nobody can make.
        page.locator("#screen button", has_text="Save the order").click()
        page.wait_for_timeout(200)
        check("it refuses an order with no customer",
              "Which customer" in page.locator("#screen .err").inner_text())
        check("and saved nothing", len(RAISED) == 0)

        page.locator('#screen input').first.fill("Pelican Waters")
        page.locator("#screen button", has_text="Save the order").click()
        page.wait_for_timeout(200)
        check("it refuses an order with no lines",
              "no lines" in page.locator("#screen .err").inner_text())
        check("and still saved nothing", len(RAISED) == 0)

        page.locator("#screen button", has_text="Add a line").click()
        page.wait_for_selector("#sheet:not(.hidden)")
        lsheet = page.locator("#sheet-body")
        # A line with no measurements has nothing to derive a part number
        # from, so it must not be accepted.
        lsheet.locator('input[inputmode="numeric"]').first.fill("4")
        lsheet.locator("button", has_text="Add it").click()
        page.wait_for_timeout(200)
        check("a line with no measurements is refused",
              "measurements are needed" in lsheet.locator(".err").inner_text())

        nums = lsheet.locator('input[inputmode="numeric"]')
        lsheet.locator("select").first.select_option("Flat Panel")
        nums.nth(1).fill("700")
        nums.nth(2).fill("1301")
        page.wait_for_timeout(100)
        check("bracing is worked out while the size is typed",
              lsheet.locator("#brace-note").inner_text() ==
              "Bracing: Brace Required - 2 braces, Cross Format",
              lsheet.locator("#brace-note").inner_text())
        check("and flagged as required",
              "required" in lsheet.locator("#brace-note").get_attribute(
                  "class"))
        nums.nth(1).fill("500")
        nums.nth(2).fill("600")
        page.wait_for_timeout(100)
        check("and cleared when it no longer applies",
              lsheet.locator("#brace-note").inner_text() ==
              "Bracing: No brace required")
        nums.nth(3).fill("45")
        lsheet.locator("select").first.select_option("V-form")
        lsheet.locator("button", has_text="Add it").click()
        page.wait_for_selector("#sheet.hidden", state="attached")
        check("the line is added", "500 × 600 × 45"
              in page.locator("#screen").inner_text(),
              page.locator("#screen").inner_text()[:250])

        page.locator("#screen button", has_text="Save the order").click()
        page.wait_for_timeout(400)
        check("the order reaches the database", len(RAISED) == 1)
        if RAISED:
            saved = RAISED[0]
            check("with the customer on it",
                  saved.get("customer_name") == "Pelican Waters")
            check("and the line's real measurements",
                  saved["items"][0]["Short"] == 500
                  and saved["items"][0]["Long"] == 600
                  and saved["items"][0]["Channel"] == 45)
            # The whole point of the split: the web does not invent these.
            check("and no part number invented in the browser",
                  not saved["items"][0].get("Part Number"))
            check("it starts as Pending, not made",
                  saved["header"]["status"] == "Pending")
            check("and it says where to finish it",
                  "desktop" in page.locator("#screen .ok").inner_text(),
                  page.locator("#screen .ok").inner_text())
            check("the form is cleared for the next one",
                  page.locator('#screen input').first.input_value() == "")

        print("\n── the order list ──")
        page.click('#tabs button[data-tab="orders"]')
        page.wait_for_selector("#screen table")
        rows = page.locator("#screen tbody tr")
        check("every order is listed", rows.count() == 3, str(rows.count()))
        check("progress shows as a fraction",
              "1/3" in page.locator("#screen").inner_text())
        check("a finished order shows a tick",
              "✓ 2" in page.locator("#screen").inner_text())
        check("the overdue row is flagged",
              page.locator("#screen tbody tr.late").count() == 1)

        page.fill('#screen input[type="search"]', "tweed")
        page.wait_for_timeout(150)
        check("search narrows the list",
              page.locator("#screen tbody tr").count() == 1)
        page.fill('#screen input[type="search"]', "")
        page.wait_for_timeout(150)

        print("\n── dropdowns ──")
        # One choice in a dropdown is one action. The Orders filters used to
        # listen for both "input" and "change", and a <select> fires both,
        # so every choice rebuilt the list twice - with the rows being torn
        # down and redrawn under the pointer, which on a phone is where the
        # tap lands that opens an order nobody asked for.
        page.evaluate("""() => {
          window.__rebuilds = 0;
          new MutationObserver(recs => recs.forEach(r => r.removedNodes
            .forEach(n => { if (n.classList && n.classList.contains('card')
                                && n.querySelector('table')) {
                              window.__rebuilds++; } })))
            .observe(document.getElementById('screen'),
                     {childList: true, subtree: true});
        }""")
        due = page.locator("#screen select").nth(0)
        due.select_option("Overdue")
        page.wait_for_timeout(250)
        check("choosing from a dropdown redraws the list once",
              page.evaluate("window.__rebuilds") == 1,
              f"{page.evaluate('window.__rebuilds')} redraws")
        check("and opens nothing else", page.locator("#sheet").is_hidden())
        check("and the choice is applied",
              page.locator("#screen tbody tr.late").count() ==
              page.locator("#screen tbody tr").count() == 1)
        page.evaluate("window.__rebuilds = 0")
        due.click()                       # open it with the mouse
        page.keyboard.press("ArrowDown")  # move with the keyboard
        page.keyboard.press("Enter")
        page.wait_for_timeout(250)
        check("opening it with a click and choosing by keyboard is one "
              "action too", page.evaluate("window.__rebuilds") <= 1 and
              page.locator("#sheet").is_hidden(),
              f"{page.evaluate('window.__rebuilds')} redraws")
        page.evaluate("window.__rebuilds = 0")
        due.focus()
        page.keyboard.press("Home")
        page.wait_for_timeout(250)
        check("keyboard alone still works",
              page.locator("#screen tbody tr").count() == 3)
        status = page.locator("#screen select").nth(1)
        status.select_option("Complete")
        page.wait_for_timeout(250)
        status.select_option("All")
        page.wait_for_timeout(250)
        check("a second dropdown on the same screen behaves the same",
              page.evaluate("window.__rebuilds") <= 3 and
              page.locator("#sheet").is_hidden(),
              f"{page.evaluate('window.__rebuilds')} redraws for 3 choices")
        # A click that starts on a control inside a clickable row belongs to
        # the control, not the row.
        page.evaluate("""() => {
          const tr = document.querySelector('#screen tbody tr');
          const sel = document.createElement('select');
          sel.id = 'probe'; sel.innerHTML = '<option>a</option><option>b</option>';
          tr.firstElementChild.appendChild(sel);
        }""")
        page.click("#probe")
        page.select_option("#probe", "b")
        page.wait_for_timeout(250)
        check("a dropdown inside a row does not open the row",
              page.locator("#sheet").is_hidden())
        # A tap on a phone arrives as touch events and then a synthesized
        # click on the control under the finger.
        page.dispatch_event("#probe", "touchstart")
        page.dispatch_event("#probe", "touchend")
        page.dispatch_event("#probe", "click")
        page.wait_for_timeout(150)
        check("nor does tapping it", page.locator("#sheet").is_hidden())
        page.click('#tabs button[data-tab="orders"]')
        page.wait_for_selector("#screen table")

        print("\n── one order ──")
        page.locator("#screen tbody tr", has_text="Bells Creek").first.click()
        page.wait_for_selector("#sheet:not(.hidden)")
        # The sheet opens straight away and fills in when the lines arrive.
        # Counting rows before then is a race, and it loses about half the
        # time on a fast machine.
        page.wait_for_selector("#sheet-body button.tick")
        sheet = page.locator("#sheet-body")
        check("the lines are shown", sheet.locator("tbody tr").count() == 3)
        check("it says how many are made",
              "1 of 3 lines made" in sheet.inner_text(), sheet.inner_text()[:200])
        check("the note is there",
              "Ring the site before delivery" in sheet.inner_text())
        check("each line says how it is wrapped, as the office planned it",
              "Line 1: (Wrap 1 Filter x 2)" in sheet.inner_text(),
              sheet.inner_text()[-400:])
        check("and one not planned yet says so",
              "Wrapping not set yet" in sheet.inner_text())
        check("and its bracing",
              "No brace required" in sheet.inner_text())

        # Tick the second line off.
        ticks = sheet.locator("button.tick")
        check("a made line is already ticked",
              ticks.nth(0).get_attribute("aria-pressed") == "true")
        ticks.nth(1).click()
        page.wait_for_timeout(300)
        check("ticking a line writes it to the database",
              ITEMS["o1"][1]["made"] is True)
        check("the box fills",
              ticks.nth(1).get_attribute("aria-pressed") == "true")
        check("the count follows",
              "2 of 3 lines made" in sheet.inner_text())
        check("it recorded who made it",
              any(b.get("p_by") == "Kai Brown" for _u, b in stub.calls
                  if b.get("p_line_id") == "L2"))

        # Untick it again.
        ticks.nth(1).click()
        page.wait_for_timeout(300)
        check("unticking works too", ITEMS["o1"][1]["made"] is False)

        print("\n── photos and proof of delivery ──")
        check("it starts with nothing kept",
              "Nothing kept against this order" in sheet.inner_text())

        # A photo, the way a phone gives one: through the file input.
        sheet.locator('input[type="file"]').set_input_files({
            "name": "plantroom.jpg", "mimeType": "image/jpeg",
            "buffer": b"\xff\xd8\xff\xe0 not really a jpeg, but a file"})
        page.wait_for_timeout(600)
        check("the photo reaches Storage", len(UPLOADED) == 1, str(UPLOADED))
        check("filed under the order it belongs to",
              UPLOADED and UPLOADED[0].startswith("order-files/o1/"),
              str(UPLOADED))
        check("and a row says what it is",
              len(FILES) == 1 and FILES[0]["kind"] == "photo")
        check("with who took it",
              FILES and FILES[0]["taken_by"] == "Kai Brown")
        check("and it appears against the order",
              sheet.locator("button.filetile").count() == 1)

        # A signature, drawn on the pad.
        sheet.locator("button", has_text="Signed for").click()
        page.wait_for_selector("#sheet-body canvas")
        sign = page.locator("#sheet-body")
        sign.locator("button", has_text="Keep it").click()
        page.wait_for_timeout(250)
        check("an unsigned pad is refused",
              "Nothing has been signed" in sign.locator(".err").inner_text())

        pad = sign.locator("canvas")
        box = pad.bounding_box()
        page.mouse.move(box["x"] + 40, box["y"] + 90)
        page.mouse.down()
        page.mouse.move(box["x"] + 150, box["y"] + 130)
        page.mouse.move(box["x"] + 240, box["y"] + 70)
        page.mouse.up()
        sign.locator("button", has_text="Keep it").click()
        page.wait_for_timeout(250)
        check("a signature with no name is refused",
              "Whose signature" in sign.locator(".err").inner_text())
        check("and nothing was uploaded on a refusal", len(UPLOADED) == 1)

        sign.locator('input[type="text"]').first.fill("D. Nguyen")
        sign.locator("button", has_text="Keep it").click()
        page.wait_for_timeout(800)
        check("the signature is kept", len(FILES) == 2)
        if len(FILES) == 2:
            check("as a signature, with the name",
                  FILES[1]["kind"] == "signature"
                  and FILES[1]["signed_by"] == "D. Nguyen")
        # Closing the pad has to go back to the order, not shut everything.
        check("it steps back to the order underneath",
              "Bells Creek" in page.locator("#sheet-body").inner_text(),
              page.locator("#sheet-body").inner_text()[:120])
        check("and the order shows both",
              page.locator("#sheet-body button.filetile").count() == 2)

        print("\n── when the database says no ──")
        stub.refuse["set_order_line_made"] = (
            "new row violates row-level security policy for table \"orders\"")
        ticks.nth(2).click()
        page.wait_for_timeout(400)
        check("a refused tick is reported",
              sheet.locator(".err").count() == 1,
              sheet.inner_text()[:200])
        check("and says it was not allowed",
              "not allowed" in sheet.locator(".err").inner_text(),
              sheet.locator(".err").inner_text())
        check("the box does not fill on a refusal",
              ticks.nth(2).get_attribute("aria-pressed") == "false")
        check("and nothing was written",
              ITEMS["o1"][2].get("made") is not True)
        stub.refuse.clear()

        print("\n── changing status ──")
        page.locator("#sheet-body button", has_text="Complete").first.click()
        page.wait_for_timeout(300)
        check("the status is written",
              ORDERS[0]["header"]["status"] == "Complete")
        check("and confirmed on screen",
              sheet.locator(".ok").count() == 1)
        check("the heading shows the new status, not the old one",
              sheet.locator(".pill").first.inner_text() == "Complete",
              sheet.locator(".pill").first.inner_text())
        check("and Complete is no longer on offer",
              sheet.locator("button", has_text="Complete").count() == 0)
        page.locator("#sheet-body button", has_text="Close").first.click()
        page.wait_for_selector("#sheet.hidden", state="attached")

        print("\n── the factory floor ──")
        sys.path.insert(0, str(ROOT))
        import datetime as _dt
        from taf_order_app import floor as _floor
        check("the board is not offered while it is switched off",
              page.locator('#tabs button[data-tab="board"]').count() == 0)
        on = ("tv_board", "job_timer", "qc_checklist", "fault_log",
              "finished_photo")
        SWITCHES[:] = [{"key": k, "enabled": True} for k in on]
        page.evaluate("(on) => TAFAPP._floor.setFeatures("
                      "Object.fromEntries(on.map(k => [k, true])))", list(on))
        page.click('#tabs button[data-tab="orders"]')
        page.wait_for_selector("#screen table")
        check("switched on, it is",
              page.locator('#tabs button[data-tab="board"]').count() == 1)
        page.click('#tabs button[data-tab="board"]')
        page.wait_for_selector("#screen .board-col")
        shown = page.eval_on_selector_all(
            "#screen .board-col", "cs => cs.map(c => [c.dataset.col, "
            "Array.from(c.querySelectorAll('.board-card'))"
            ".map(x => x.dataset.order)])")
        want = [[c["key"], [card["id"] for card in c["cards"]]]
                for c in _floor.production_board(ORDERS, _dt.date.today())]
        check("the board shows the four columns, each job where the desktop "
              "would put it", shown == want, f"{shown} != {want}")
        page.locator("#screen button", has_text="Show on the TV").click()
        page.wait_for_timeout(200)
        check("on the TV it is the board and nothing else",
              page.evaluate("document.body.classList.contains('tv') && "
                            "getComputedStyle(document.querySelector('header'))"
                            ".display === 'none' && getComputedStyle("
                            "document.querySelector('nav')).display === 'none'"))
        if os.environ.get("TAF_SHOTS"):
            page.set_viewport_size({"width": 1600, "height": 900})
            page.wait_for_timeout(200)
            page.screenshot(path=os.path.join(os.environ["TAF_SHOTS"],
                                              "web_tv_board.png"))
            page.set_viewport_size({"width": 900, "height": 900})
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        check("and Escape puts a PC back to normal",
              not page.evaluate("document.body.classList.contains('tv')"))

        today = "2026-10-16"
        sample = [
            {"id": "a", "customer_name": "Zeta", "date_due": "16/10/2026",
             "n_items": 4, "n_made": 0, "header": {}},
            {"id": "b", "customer_name": "Alpha", "date_due": "19/10/2026",
             "n_items": 4, "n_made": 0, "header": {}},
            {"id": "c", "customer_name": "Bravo", "date_due": "20/10/2026",
             "n_items": 4, "n_made": 0, "header": {}},
            {"id": "d", "customer_name": "Late", "date_due": "14/10/2026",
             "n_items": 4, "n_made": 0, "header": {"stages": {"marked": True}}},
            {"id": "e", "customer_name": "Rush", "date_due": "16/10/2026",
             "n_items": 4, "n_made": 0, "header": {"priority": True}},
            {"id": "f", "customer_name": "Started", "date_due": "30/10/2026",
             "n_items": 4, "n_made": 2, "header": {}},
            {"id": "g", "customer_name": "Cut", "date_due": "30/10/2026",
             "n_items": 4, "n_made": 0, "header": {"stages": {"cut": True}}},
            {"id": "h", "customer_name": "Packed", "date_due": "01/10/2026",
             "n_items": 4, "n_made": 4, "header": {"stages": {"packed": True}}},
            {"id": "i", "customer_name": "Done", "date_due": "",
             "header": {"status": "Complete"}},
            {"id": "j", "customer_name": "Gone", "date_due": "",
             "header": {"status": "Dispatched", "status_at": "2026-10-16T03:00:00Z"}},
            {"id": "k", "customer_name": "Gone before", "date_due": "",
             "header": {"status": "Delivered", "status_at": "2026-10-15T03:00:00Z"}},
            {"id": "l", "customer_name": "Old", "archived": True,
             "date_due": "16/10/2026", "header": {}}]
        for ahead in (1, 2, 5):
            js = page.evaluate("""([rows, ahead]) => TAFAPP._floor.productionBoard(
                rows, new Date(2026, 9, 16), ahead).map(c => [c.key,
                c.cards.map(x => [x.id, x.late, x.today, x.priority])])""",
                [sample, ahead])
            py = [[c["key"], [[x["id"], x["late"], x["today"], x["priority"]]
                              for x in c["cards"]]]
                  for c in _floor.production_board(
                      sample, _dt.date.fromisoformat(today), ahead)]
            check(f"the phone's board is the desktop's ({ahead} ahead)",
                  js == py, f"{js} != {py}")
        lists = {"V-Form": ["Pleats even"], "*": ["Size checked"]}
        js = page.evaluate("(l) => ['v-form', 'Flat Panel', ''].map("
                           "t => TAFAPP._floor.checksFor(t, l))", lists)
        check("and its QC checks", js == [_floor.checks_for(t, lists)
                                         for t in ("v-form", "Flat Panel", "")],
              str(js))

        # On an order: the timer, QC before a line is made, and a fault.
        page.click('#tabs button[data-tab="orders"]')
        page.wait_for_selector("#screen table")
        page.locator("#screen tbody tr", has_text="Bells Creek").first.click()
        page.wait_for_selector("#sheet-body button.timer")
        sheet = page.locator("#sheet-body")
        sheet.locator("button.timer").first.click()
        page.wait_for_timeout(300)
        check("Start times the line",
              len(TIMERS) == 1 and TIMERS[0]["line_id"] == "L1"
              and sheet.locator("button.timer").first.inner_text() == "■ Stop",
              str(TIMERS))
        sheet.locator("button.timer").first.click()
        page.wait_for_timeout(300)
        check("and Stop stops it, saying how long it took",
              TIMERS[0]["stopped_at"] and "Took 3.5 min" in sheet.inner_text()
              and sheet.locator("button.timer").first.inner_text() == "▶ Start")

        before = sum(1 for _u, b in stub.calls if b.get("p_line_id") == "L3"
                     and "p_made" in b)
        sheet.locator("button.tick").nth(2).click()
        page.wait_for_selector("#qc-pass")
        check("ticking a line made asks for its checks first",
              page.locator("#sheet-body .qc-check").count() == 2)
        page.click("#qc-pass")
        page.wait_for_timeout(150)
        check("which all have to be ticked",
              "Tick every check" in page.locator("#sheet-body").inner_text())
        for box in page.locator("#sheet-body .qc-check input").all():
            box.check()
        page.click("#qc-pass")
        page.wait_for_timeout(500)
        qc = ITEMS["o1"][2].get("qc") or {}
        check("then the checks are kept on the line, and it is made",
              qc.get("checks") == ["Size checked", "Label on"]
              and qc.get("by") == "Kai Brown" and ITEMS["o1"][2].get("made"),
              str(ITEMS["o1"][2]))
        check("and nothing was marked made before the checks",
              sum(1 for _u, b in stub.calls if b.get("p_line_id") == "L3"
                  and "p_made" in b) == before + 1)

        page.wait_for_selector("#sheet-body button.fault")
        page.locator("#sheet-body button.fault").nth(1).click()
        page.wait_for_selector("#fault-save")
        page.select_option("#fault-reason", "Wrong size")
        page.fill("#fault-detail", "50mm short")
        page.click("#fault-save")
        page.wait_for_timeout(400)
        check("a fault is recorded against the line, as found in QC",
              FAULTS and FAULTS[-1]["reason"] == "Wrong size"
              and FAULTS[-1]["line_id"] == "L2" and FAULTS[-1]["found"] == "qc"
              and FAULTS[-1]["order_number"] == "PO-8842"
              and FAULTS[-1]["detail"] == "50mm short", str(FAULTS[-1:]))
        page.keyboard.press("Escape")
        page.wait_for_selector("#sheet.hidden", state="attached")

        # A photo of the finished job, before it can be Complete.
        page.locator("#screen tbody tr", has_text="Pelican Waters").first.click()
        page.wait_for_selector("#finished-photo")
        page.locator("#sheet-body button", has_text="Complete").first.click()
        page.wait_for_timeout(300)
        check("with no photo of the finished job it cannot be Complete",
              "Take a photo of the finished job first"
              in page.locator("#sheet-body").inner_text()
              and ORDERS[2]["header"]["status"] == "Pending")
        page.locator("#finished-pick").set_input_files({
            "name": "done.jpg", "mimeType": "image/jpeg",
            "buffer": b"\xff\xd8\xff\xe0 finished filters"})
        page.wait_for_timeout(600)
        done = [f for f in FILES if f.get("kind") == "finished"]
        check("the photo goes where the customer's portal can show it",
              done and done[-1]["bucket"] == "job-photos"
              and done[-1]["order_id"] == "o3"
              and any(u.startswith("job-photos/o3/") for u in UPLOADED),
              str(done[-1:]) + str(UPLOADED[-1:]))
        page.locator("#sheet-body button", has_text="Complete").first.click()
        page.wait_for_timeout(400)
        check("and with it, it can", ORDERS[2]["header"]["status"] == "Complete")
        ORDERS[2]["header"]["status"] = "Pending"       # for the rest
        page.keyboard.press("Escape")
        page.wait_for_selector("#sheet.hidden", state="attached")
        SWITCHES.clear()
        page.evaluate("TAFAPP._floor.setFeatures({})")
        # Line 3 back as it was, for what follows.
        ITEMS["o1"][2]["made"] = False
        ITEMS["o1"][2].pop("qc", None)

        print("\n── order again, and whether a day is full ──")
        on = ("order_again", "capacity_check")
        SWITCHES[:] = [{"key": k, "enabled": True} for k in on]
        page.evaluate("(on) => TAFAPP._floor.setFeatures("
                      "Object.fromEntries(on.map(k => [k, true])))", list(on))
        from taf_order_app import planning as _plan
        roster = [{"person": "Dave", "days": [1, 2, 3, 4, 5], "hours": 8},
                  {"person": "Amy", "days": [1, 2, 3, 4, 5], "hours": 8}]
        orders = [{"id": "x", "date_due": "16/10/2026", "header": {},
                   "items": [{"Filter Type": "V-Form", "Quantity": 22}]}]
        leave = [{"person": "Amy", "first_day": "2026-10-19",
                  "last_day": "2026-10-19"}]
        rates = [{"filter_type": "V-Form", "minutes_each": 20}]
        ws = {"minutes_per_filter": 15, "making_share": 0.5}
        for due, new in (("16/10/2026", [{"Filter Type": "Flat Panel", "Quantity": 4}]),
                         ("16/10/2026", [{"Filter Type": "V-Form", "Quantity": 2}]),
                         ("19/10/2026", [{"Filter Type": "V-Form", "Quantity": 13}]),
                         ("ASAP", [])):
            js = page.evaluate("""([d, n, o, r, ro, l, w]) =>
                TAFAPP._planning.checkDue(d, n, o, r, ro, l, [], w)""",
                [due, new, orders, rates, roster, leave, ws])
            py = _plan.check_due(due, new, orders, rates, roster, leave, [], ws)
            if py:
                py = dict(py, day=py["day"].isoformat(),
                          next_free=py["next_free"].isoformat()
                          if py["next_free"] else None)
                # 60 in JavaScript is 60.0 in Python.
                for k in ("need", "booked", "minutes"):
                    py[k], js[k] = float(py[k]), float(js[k])
            check(f"the phone and the desktop agree on {due} "
                  f"({'full' if py and py['full'] else 'room'})",
                  json.dumps(js, sort_keys=True) == json.dumps(py, sort_keys=True),
                  f"{js} != {py}")
            if py and py["full"]:
                said = page.evaluate("(r) => TAFAPP._planning.describeFull(r)", js)
                want = _plan.check_due(due, new, orders, rates, roster, leave, [], ws)
                check("and say it the same way", said == _plan.describe(want),
                      f"{said!r} != {_plan.describe(want)!r}")

        # Order again, from a past order.
        page.click('#tabs button[data-tab="orders"]')
        page.wait_for_selector("#screen table")
        page.locator("#screen tbody tr", has_text="Bells Creek").first.click()
        page.wait_for_selector("#order-again")
        page.click("#order-again")
        page.wait_for_selector('#tabs button[data-tab="new"][aria-selected="true"]')
        check("Order again puts the same lines on a new order",
              page.locator("#screen input").first.input_value() == "Bells Creek"
              and page.locator("#screen tbody tr").count() == 3,
              page.locator("#screen").inner_text()[:300])
        # Due on a day the one person in cannot make it all.
        import datetime as _dt2
        day = _dt2.date.today().strftime("%d/%m/%Y")
        page.locator("#screen input").nth(2).fill(day)
        asked = []
        page.once("dialog", lambda d: (asked.append(d.message), d.dismiss()))
        before = len(RAISED)
        page.locator("#screen button", has_text="Save the order").click()
        page.wait_for_timeout(600)
        check("a day that is already full says so before it is saved",
              asked and "is already full" in asked[0] and len(RAISED) == before,
              str(asked))
        page.once("dialog", lambda d: d.accept())
        page.locator("#screen button", has_text="Save the order").click()
        page.wait_for_timeout(600)
        check("and saying save anyway saves it", len(RAISED) == before + 1
              and not any("made" in (i or {}) or "line_id" in (i or {})
                          for i in RAISED[-1].get("items") or []),
              str(RAISED[-1:])[:300])
        SWITCHES.clear()
        page.evaluate("TAFAPP._floor.setFeatures({})")

        print("\n── winning the work ──")
        from taf_order_app import sales as _sales
        quotes = [
            {"id": "a", "status": "sent", "sent_at": "2026-10-01T00:00:00Z"},
            {"id": "b", "status": "viewed", "sent_at": "2026-10-08T00:00:00Z"},
            {"id": "c", "status": "sent", "sent_at": "2026-10-12T00:00:00Z"},
            {"id": "e", "status": "sent", "sent_at": "2026-09-20T00:00:00Z",
             "chased_at": "2026-10-14T00:00:00Z"},
            {"id": "f", "status": "sent", "sent_at": "2026-09-20T00:00:00Z",
             "chased_at": "2026-10-05T00:00:00Z"},
            {"id": "d", "status": "accepted", "sent_at": "2026-09-01"}]
        js = page.evaluate("(q) => TAFAPP._sales.toChase(q, '2026-10-16')", quotes)
        py = [{"id": q["id"], "waited": q["waited"]}
              for q in _sales.to_chase(quotes, _dt.date(2026, 10, 16))]
        check("the phone chases the same quotes as the desktop", js == py,
              f"{js} != {py}")
        mail_js = page.evaluate("""() => {
            const S = TAFAPP._sales;
            const m = S.chaseEmail({quote_number: 'Q-1041', total: 1287.5},
                                   'https://x/quote/?t=abc&k=1', null, 'Dave Nguyen');
            return [m.subject, m.body, S.mailto('dave@site.com', m.subject, m.body)];
        }""")
        m = _sales.chase_email({"quote_number": "Q-1041", "total": 1287.5},
                               "https://x/quote/?t=abc&k=1", contact="Dave Nguyen")
        check("and writes the same email, to the same link",
              mail_js == [m["subject"], m["body"],
                          _sales.mailto("dave@site.com", m["subject"], m["body"])],
              f"{mail_js[2][:120]} != "
              f"{_sales.mailto('dave@site.com', m['subject'], m['body'])[:120]}")
        custs = [{"name": "Bells Creek", "short_name": "Bells", "service_weeks": 12},
                 {"name": "Tweed", "service_weeks": 26},
                 {"name": "Snoozed", "service_weeks": 4,
                  "service_snoozed_until": "2026-11-01"}]
        olist = [{"customer_name": "Bells", "date_ordered": "20/07/2026"},
                 {"customer_name": "Bells Creek", "date_ordered": "01/06/2026"},
                 {"customer_name": "Tweed", "date_ordered": "01/09/2026"},
                 {"customer_name": "Snoozed", "date_ordered": "01/01/2026"}]
        for ahead in (14, 200):
            js = page.evaluate("([c, o, a]) => TAFAPP._sales.serviceDue(c, o, "
                               "'2026-10-16', a)", [custs, olist, ahead])
            py = [{"name": r["customer"]["name"], "last": r["last"].isoformat(),
                   "due": r["due"].isoformat(), "late": r["late"]}
                  for r in _sales.service_due(custs, olist, _dt.date(2026, 10, 16),
                                              ahead)]
            check(f"and is due the same filter changes ({ahead} days ahead)",
                  js == py, f"{js} != {py}")

        on = ("quote_chase", "service_reminders", "lost_reasons", "order_again")
        SWITCHES[:] = [{"key": k, "enabled": True} for k in on]
        page.evaluate("(on) => TAFAPP._floor.setFeatures("
                      "Object.fromEntries(on.map(k => [k, true])))", list(on))
        QUOTES[0].update({"status": "sent", "sent_at": "2026-09-01T00:00:00Z",
                          "public_token": "tok123", "customer_id": "c1"})
        CUSTOMERS[0]["service_weeks"] = 4
        page.evaluate("TAFAPP._sales.watchMail(l => { window.__mail = l; })")
        page.click('#tabs button[data-tab="dashboard"]')
        page.wait_for_selector("#chase-card .chase-row")
        check("Today lists the quotes to chase",
              "Q-1041" in page.locator("#chase-card").inner_text())
        page.locator("#chase-card button", has_text="Chase").first.click()
        page.wait_for_function("() => !!window.__mail")
        sent = page.evaluate("window.__mail")
        check("and Chase opens an email with their quote's link in it",
              sent.startswith("mailto:") and "tok123" in sent
              and "Q-1041" in sent, sent[:200])
        check("and counts the chase",
              any("rpc/quote_chased" in u for u, _b in stub.calls))
        page.wait_for_selector("#service-card .chase-row")
        check("and the customers due a filter change",
              CUSTOMERS[0]["name"] in page.locator("#service-card").inner_text(),
              page.locator("#service-card").inner_text())

        page.click('#tabs button[data-tab="quotes"]')
        page.wait_for_selector("#screen table")
        page.locator("#screen tbody tr", has_text="Q-1041").first.click()
        page.wait_for_selector("#mark-lost")
        page.select_option("#lost-reason", "Lead time")
        page.click("#mark-lost")
        page.wait_for_timeout(400)
        check("a quote marked lost says why",
              QUOTES[0]["lost_reason"] == "Lead time"
              and QUOTES[0]["status"] == "declined", str(QUOTES[0])[:200])
        page.keyboard.press("Escape")
        page.wait_for_selector("#sheet.hidden", state="attached")
        QUOTES[0].update({"status": "sent", "lost_reason": ""})
        CUSTOMERS[0].pop("service_weeks", None)
        SWITCHES.clear()
        page.evaluate("TAFAPP._floor.setFeatures({})")

        print("\n── stock you can trust ──")
        on = ("stocktake", "stock_reserve", "price_history")
        SWITCHES[:] = [{"key": k, "enabled": True} for k in on]
        page.evaluate("(on) => TAFAPP._floor.setFeatures("
                      "Object.fromEntries(on.map(k => [k, true])))", list(on))
        page.click('#tabs button[data-tab="orders"]')
        page.wait_for_selector("#screen table")
        page.click('#tabs button[data-tab="count"]')
        page.wait_for_selector("#count-start")
        page.fill("#count-name", "Back racks")
        page.click("#count-start")
        page.wait_for_selector("#count-list .count-row")
        check("a count is started from the phone, and lists every item",
              TAKES and TAKES[0]["name"] == "Back racks"
              and page.locator("#count-list .count-row").count() == len(STOCK))
        sku = STOCK[0]["sku"]
        page.fill("#count-find", sku)
        page.press("#count-find", "Enter")
        page.wait_for_selector("#count-qty")
        page.fill("#count-qty", "40")
        page.press("#count-qty", "Enter")
        page.wait_for_timeout(400)
        check("a gun that types the label goes straight to the item, and the "
              "count goes in with what the system said",
              COUNTS.get(STOCK[0]["id"], {}).get("counted") == 40
              and COUNTS[STOCK[0]["id"]]["was"] == STOCK[0]["stock_on_hand"],
              str(COUNTS))
        page.route("**/rest/v1/rpc/count_stock*",
                   lambda r: r.abort("internetdisconnected"))
        page.locator(f'#count-list .count-row[data-stock="{STOCK[1]["id"]}"]').click()
        page.wait_for_selector("#count-qty")
        page.fill("#count-qty", "5")
        page.click("#count-save")
        page.wait_for_timeout(400)
        check("out of signal the count is kept on the phone",
              STOCK[1]["id"] not in COUNTS
              and "1 change waiting" in page.locator("#state").inner_text()
              and "2 of" in page.locator("#screen").inner_text())
        page.unroute("**/rest/v1/rpc/count_stock*")
        page.evaluate("TAFSYNC.flush()")
        page.wait_for_timeout(600)
        check("and goes in when the signal is back",
              COUNTS.get(STOCK[1]["id"], {}).get("counted") == 5)
        page.click("#count-finish")
        page.wait_for_selector("#count-apply")
        check("finishing shows what is not what the system says",
              "not what the system says" in page.locator("#sheet-body").inner_text())
        page.click("#count-apply")
        page.wait_for_timeout(500)
        check("and a manager can set stock to what was counted",
              APPLIED == [TAKES[0]["id"]] and TAKES[0].get("finished_at"))

        page.click('#tabs button[data-tab="stock"]')
        page.wait_for_selector(f'#screen .stock-card[data-stock="{STOCK[0]["id"]}"]')
        page.locator(f'#screen .stock-card[data-stock="{STOCK[0]["id"]}"]').click()
        page.wait_for_selector("#stock-spoken")
        free = STOCK[0]["stock_on_hand"] - 12
        check("a stock item says what open jobs have spoken for, and what is free",
              page.locator("#stock-spoken").inner_text() == f"12 on 2 jobs · {free:g} free",
              page.locator("#stock-spoken").inner_text())
        check("and what we have paid for it",
              "What we've paid" in page.locator("#sheet-body").inner_text()
              and "$82.50" in page.locator("#sheet-body").inner_text())
        page.keyboard.press("Escape")
        page.wait_for_selector("#sheet.hidden", state="attached")
        COUNTS.clear()
        SWITCHES.clear()
        page.evaluate("TAFAPP._floor.setFeatures({})")

        print("\n── delivery ──")
        page.click('#tabs button[data-tab="delivery"]')
        page.wait_for_selector("#screen .card")
        text = page.locator("#screen").inner_text()
        # Only Complete work is ready to go — the same rule the run sheet is
        # built on, so the driver's sheet and this screen cannot disagree.
        check("completed work is on the run", "CAS - Tweed" in text)
        check("work still being made is not",
              "Pelican Waters" not in text, text[:250])

        print("\n── out the door, and what it made ──")
        from taf_order_app import calc_settings as _cs
        from taf_order_app import delivery as _dl
        from taf_order_app import money as _mn
        stops = [
            {"id": "1", "region": "Gold Coast", "address": "Southport QLD 4215", "customer": "B"},
            {"id": "2", "region": "Local", "address": "Loganholme QLD 4129", "customer": "a"},
            {"id": "3", "region": "Pick Up", "address": "", "customer": "C"},
            {"id": "4", "region": "Local", "address": "Hillcrest QLD 4118", "customer": "D"},
            {"id": "6", "region": "Local", "address": "Hillcrest QLD 4118", "customer": "Aa"},
            {"id": "5", "region": "Freight", "address": "", "customer": "E"},
            {"id": "7", "region": "Somewhere new", "address": "", "customer": "F"},
        ]
        check("the phone suggests the same route as the PC",
              page.evaluate("s => TAFAPP._route.suggest(s)", stops)
              == [s["id"] for s in _dl.suggest_route(stops)])
        check("and keeps a saved one the same way",
              page.evaluate("a => TAFAPP._route.apply(a[0], a[1])",
                            [stops, ["5", "gone", "1", "5"]])
              == [s["id"] for s in _dl.apply_route(stops, ["5", "gone", "1", "5"])])
        addrs = ["Unit 3 & 4/12 O'Neil St, Hillcrest QLD 4118", "",
                 "50 Smith Rd (rear), Logan #2"] + [f"S{i} St" for i in range(14)]
        same = all(page.evaluate("a => TAFAPP._route.mapsLinks(a[0], a[1])",
                                 [_cs.BASE_ADDRESS_DEFAULT, addrs[:n]])
                   == _dl.maps_links(_cs.BASE_ADDRESS_DEFAULT, addrs[:n])
                   for n in (0, 1, 3, 10, 12, 17))
        check("and the same Google Maps links, split the same way", same)
        cust = {"delivery_address1": "1 Smith St", "delivery_address2": "Unit 2",
                "delivery_city": "Hillcrest", "delivery_state": "QLD",
                "delivery_postcode": "4118"}
        check("and the same address",
              page.evaluate("c => TAFAPP._route.addressText(c)", cust)
              == _dl.address_text(cust))

        def _norm(p):
            return None if p is None else {k: (v if isinstance(v, bool) else float(v))
                                           for k, v in p.items()}
        cases = [(30000, 60000, "16/10/2026"), (61000, 60000, "16/10/2026"),
                 (50000, 60000, "30/10/2026"), (0, 1000, "01/11/2026"),
                 (12345.67, 50000, "03/02/2027"), (100, 0, "03/02/2027"),
                 (1000, 7000, "31/10/2026")]
        agree = True
        for sold, target, day in cases:
            d = dt.datetime.strptime(day, "%d/%m/%Y").date()
            js = page.evaluate("a => TAFAPP._money.progress(a[0], a[1], a[2])",
                               [sold, target, day])
            txt = page.evaluate("a => TAFAPP._money.text(a[0], a[1], a[2])",
                                [sold, target, day])
            py = _mn.target_progress(sold, target, d)
            if _norm(js) != _norm(py) or txt != _mn.target_text(py, d):
                agree = False
                print("        ", day, js, py, txt)
        check("the month's target is worked out the same on the phone", agree)

        on = ("route_order", "sales_targets", "pod_email")
        SWITCHES[:] = [{"key": k, "enabled": True} for k in on]
        page.evaluate("(on) => TAFAPP._floor.setFeatures("
                      "Object.fromEntries(on.map(k => [k, true])))", list(on))
        CUSTOMERS[0].update({"delivery_address1": "12 Industrial Ave",
                             "delivery_city": "Caloundra", "delivery_state": "QLD",
                             "delivery_postcode": "4551"})
        ORDERS.append({"id": "o4", "customer_name": "Bells Creek",
                       "order_number": "PO-7000", "date_ordered": "05/09/2026",
                       "date_due": "30/09/2026", "archived": False,
                       "created_at": "2026-09-05T00:00:00Z", "n_items": 1,
                       "n_made": 1, "full_name": "Kai Brown",
                       "header": {"status": "Complete", "Location": "Sunshine Coast"}})
        ITEMS["o4"] = [{"line_id": "L9", "Quantity": 1, "Filter Type": "Flat Panel",
                        "Short": 300, "Long": 300, "made": True}]
        # Only o2 and o4 ready, whatever the sections before left o1 at.
        o1_was = ORDERS[0]["header"].get("status")
        ORDERS[0]["header"]["status"] = "In Production"
        page.evaluate("TAFAPP._stale()")
        page.click('#tabs button[data-tab="dashboard"]')
        page.click('#tabs button[data-tab="delivery"]')
        page.wait_for_selector("#run-card .run-row")
        rows = page.locator("#run-card .run-row")
        firsts = [rows.nth(i).get_attribute("data-order") for i in range(rows.count())]
        check("today's run lists what is going out, in a suggested order",
              firsts == ["o4", "o2"], str(firsts))
        check("with the address from the customer, or a note there is none",
              "12 Industrial Ave, Caloundra QLD 4551" in rows.nth(0).inner_text()
              and "No address" in rows.nth(1).inner_text())
        href = page.locator("#run-card a.maps-link").first.get_attribute("href")
        check("one tap opens Google Maps from the base, round the stops and back",
              href == _dl.maps_links(_cs.BASE_ADDRESS_DEFAULT,
                                     ["12 Industrial Ave, Caloundra QLD 4551"])[0], href)
        rows.nth(1).locator("button", has_text="▲").click()
        page.click("#run-save")
        page.wait_for_timeout(300)
        today = dt.date.today().isoformat()
        check("the driver moves a stop up and saves the run",
              RUNS.get(today) == ["o2", "o4"], str(RUNS))
        page.click('#tabs button[data-tab="dashboard"]')
        page.click('#tabs button[data-tab="delivery"]')
        page.wait_for_selector("#run-card .run-row")
        check("and it comes back in that order",
              page.locator("#run-card .run-row").first.get_attribute("data-order") == "o2")

        page.locator('#run-card .run-row[data-order="o4"] button',
                     has_text="Open").click()
        page.wait_for_selector("#sheet:not(.hidden)")
        sheet = page.locator("#sheet-body")
        sheet.locator("button", has_text="Signed for").click()
        page.wait_for_selector("#sheet-body canvas")
        pad = page.locator("#sheet-body canvas")
        box = pad.bounding_box()
        page.mouse.move(box["x"] + 40, box["y"] + 90)
        page.mouse.down()
        page.mouse.move(box["x"] + 200, box["y"] + 120)
        page.mouse.up()
        page.locator('#sheet-body input[type="text"]').first.fill("Jo Smith")
        page.locator("#sheet-body button", has_text="Keep it").click()
        wait_for_text(page, "#sheet-body", "emailed to jobs@bellscreek.com.au")
        check("signed for: the order is Delivered",
              ORDERS[-1]["header"]["status"] == "Delivered")
        check("and the customer is emailed the proof of delivery",
              POD_CALLS == [{"order_id": "o4"}], str(POD_CALLS))
        page.keyboard.press("Escape")
        page.wait_for_selector("#sheet.hidden", state="attached")

        page.click('#tabs button[data-tab="dashboard"]')
        page.wait_for_selector("#target-card .target-n")
        p = _mn.target_progress(30000, 60000, dt.date.today())
        check("Today shows how far through the month's target the orders are",
              page.locator("#target-card .target-n").inner_text() == "50%"
              and _mn.target_text(p, dt.date.today())
              in page.locator("#target-card").inner_text(),
              page.locator("#target-card").inner_text())
        TARGET["target"] = 0
        page.click('#tabs button[data-tab="orders"]')
        page.click('#tabs button[data-tab="dashboard"]')
        page.wait_for_timeout(500)
        check("and says nothing when there is no target",
              page.locator("#target-card").count() == 0)

        ORDERS.pop()
        ORDERS[0]["header"]["status"] = o1_was
        ITEMS.pop("o4", None)
        for k in ("delivery_address1", "delivery_city", "delivery_state",
                  "delivery_postcode"):
            CUSTOMERS[0].pop(k, None)
        SWITCHES.clear()
        page.evaluate("TAFAPP._floor.setFeatures({})")
        page.evaluate("TAFAPP._stale()")

        print("\n── how we do things, and talking to each other ──")
        from taf_order_app import staff_board as _sb
        rule_sets = [{}, {"post_board": "Employee", "pin": "Manager"},
                     {"make_group": "Admin", "remove_any": "Employee"}]
        same = all(page.evaluate("a => TAFAPP._board.may(a[0], a[1], a[2])",
                                 [act, role, rules]) == _sb.may(act, role, rules)
                   for act in list(_sb.RULES) + ["nonsense"]
                   for role in ("Employee", "Manager", "Admin", "Director", "", "Owner")
                   for rules in rule_sets)
        rows = [{"action": "pin", "min_role": "Employee"},
                {"action": "pin", "min_role": "Director"}, {"action": "x", "min_role": "Admin"}]
        check("the phone and the PC agree on who may do what", same and page.evaluate(
            "r => TAFAPP._board.rulesWithDefaults(r)", rows) == _sb.rules_with_defaults(rows))
        now = "2026-10-16T15:00:00"
        stamps = ["2026-10-16T10:42:00", "2026-10-15T23:59:00", "2026-10-10T08:05:00",
                  "2026-10-09T08:05:00", "2026-09-01T00:00:00", "nonsense"]
        nowd = dt.datetime.fromisoformat(now)
        check("and say when a message was sent the same way",
              [page.evaluate("a => TAFAPP._board.messageTime(a[0], a[1])", [s, now])
               for s in stamps] == [_sb.message_time(s, nowd) for s in stamps])
        sops = SOPS + [{"id": "x", "title": "Old", "filter_type": "v-form", "archived": True},
                       {"id": "y", "title": "answer phone", "category": ""},
                       {"id": "z", "title": "Alpha", "category": "office"}]
        check("and on which how-tos go with a filter type, and how they are filed",
              page.evaluate("a => TAFAPP._board.sopsForType(a[0], a[1])", [sops, " V-FORM"])
              == [s["id"] for s in _sb.sops_for_type(sops, " V-FORM")]
              and page.evaluate("s => TAFAPP._board.byCategory(s)", sops)
              == [[c, [s["id"] for s in rows]] for c, rows in _sb.by_category(sops)]
              and all(page.evaluate("a => TAFAPP._board.readState(a[0], a[1])", [s, m])
                      == _sb.read_state(s, m)
                      for s in SOPS for m in (None, {"version": 1}, {"version": 2})))

        page.evaluate("TAFAPP._floor.setFeatures({})")
        page.evaluate("TAFAPP._board.pollChats()")
        page.wait_for_selector("#chat-badge:not(.hidden)")
        check("messages and how-tos need no switch: Messages sits beside the bell, "
              "with what is unread", page.locator("#chat-badge").inner_text() == "2"
              and page.locator('#tabs button[data-tab="howto"]').count() == 1)
        page.click('#tabs button[data-tab="howto"]')
        page.wait_for_selector("#screen .howto-row")
        check("the how-to library lists every how-to, saying which are not read",
              page.locator("#screen .howto-row.new").count() == 2)
        page.fill("#howto-find", "brace")
        check("and finds one by what it says",
              page.locator("#screen .howto-row").count() == 1)
        page.fill("#howto-find", "")
        page.locator('#screen .howto-row[data-sop="sop1"]').click()
        page.wait_for_selector("#sop-read")
        check("a how-to shows what to do and its video",
              "Pleat it." in page.locator("#sheet-body").inner_text()
              and page.locator('#sheet-body a[href="https://youtu.be/abc"]').count() == 1)
        page.click("#sop-read")
        wait_for_text(page, "#sheet-body", "version 2")
        check("and is signed off as read, at the version there now",
              SOP_READS == [{"sop_id": "sop1", "user_id": "u1", "version": 2}])
        page.keyboard.press("Escape")
        page.wait_for_selector("#sheet.hidden", state="attached")
        page.click('#tabs button[data-tab="orders"]')
        page.wait_for_selector("#screen table")
        page.locator("#screen tbody tr", has_text="PO-8842").first.click()
        page.wait_for_selector("#sheet-body button.howto")
        check("a V-form line on an order offers how to make it",
              page.locator("#sheet-body button.howto").count() == 1)
        page.locator("#sheet-body button.howto").click()
        wait_for_text(page, "#sheet-body", "Making a V-form")
        U_close = page.locator("#sheet-body button", has_text="Close")
        U_close.last.click()
        page.keyboard.press("Escape")
        page.wait_for_selector("#sheet.hidden", state="attached")

        page.click('#tabs button[data-tab="chat"]')
        page.wait_for_selector("#chat-list .chat-row")
        check("Messages lists the noticeboard and my groups, with what is new",
              page.locator("#chat-list .chat-row").count() == 2
              and page.locator('#tabs button[data-tab="chat"] .tab-count').inner_text() == "2")
        check("a manager is offered a new group, as the rules say",
              page.locator("#chat-new").count() == 1)
        page.locator('#chat-list .chat-row[data-chat="ch-board"]').click()
        page.wait_for_selector("#chat-msgs .chat-msg")
        check("the noticeboard shows its messages, the pinned one at the top",
              page.locator("#chat-pinned .chat-msg").count() == 1
              and page.locator("#chat-msgs .chat-msg").count() == 2)
        page.wait_for_timeout(400)
        check("opening it clears what is new",
              page.locator('#tabs button[data-tab="chat"] .tab-count').count() == 0)
        check("out of the box a manager cannot pin, or take down other people's",
              page.locator("#sheet-body .msg-pin").count() == 0
              and page.locator("#sheet-body .msg-remove").count() == 0)
        page.fill("#chat-text", "Forklift booked for 2pm")
        page.click("#chat-send")
        page.wait_for_selector('#chat-msgs .chat-msg.mine')
        check("a manager posts on the noticeboard, as themselves",
              CHAT_MSGS[-1]["body"] == "Forklift booked for 2pm"
              and CHAT_MSGS[-1]["user_id"] == "u1"
              and page.locator("#chat-msgs .chat-msg.mine .msg-remove").count() == 1)
        page.on("dialog", lambda d: d.accept())
        page.locator("#chat-msgs .chat-msg.mine .msg-remove").click()
        page.wait_for_timeout(400)
        check("and can take their own message down",
              CHAT_CALLS[-1] == ("remove_message", {"p_id": CHAT_MSGS[-1]["id"]})
              and "Taken down" in page.locator("#chat-msgs").inner_text())
        page.locator("#sheet-body button", has_text="Close").last.click()
        page.wait_for_selector("#sheet.hidden", state="attached")
        CHAT_RULES.append({"action": "pin", "min_role": "Manager"})
        page.click('#tabs button[data-tab="orders"]')
        page.click('#tabs button[data-tab="chat"]')
        page.wait_for_selector("#chat-list .chat-row")
        page.locator('#chat-list .chat-row[data-chat="ch-board"]').click()
        page.wait_for_selector("#chat-msgs .msg-pin")
        page.locator('#chat-msgs .chat-msg[data-msg="m2"] .msg-pin').click()
        page.wait_for_timeout(400)
        check("when an admin lets managers pin, a manager can",
              CHAT_CALLS[-1] == ("pin_message", {"p_id": "m2", "p_on": True})
              and page.locator("#chat-pinned .chat-msg").count() == 2)
        page.locator("#sheet-body button", has_text="Close").last.click()
        page.wait_for_selector("#sheet.hidden", state="attached")
        page.locator('#chat-list .chat-row[data-chat="ch-g"]').click()
        page.wait_for_selector("#chat-readonly")
        check("a group only managers post in says so to those who cannot",
              page.locator("#chat-readonly").inner_text()
              == "Only managers and above can post here."
              and page.locator("#chat-text").count() == 0)
        page.locator("#sheet-body button", has_text="Close").last.click()
        page.wait_for_selector("#sheet.hidden", state="attached")
        page.click("#chat-new")
        page.wait_for_selector("#group-make")
        page.fill("#group-name", "Night shift")
        page.locator("#sheet-body .group-people input").first.check()
        page.select_option("#group-who", "Manager")
        page.click("#group-make")
        page.wait_for_timeout(400)
        check("a new group is started with the people ticked",
              CHAT_CALLS[-1] == ("make_group", {"p_name": "Night shift",
                                                "p_members": ["u2"],
                                                "p_post_min_role": "Manager"}),
              str(CHAT_CALLS[-1:]))

        page.click('#tabs button[data-tab="chat"]')
        page.wait_for_selector("#chat-dm")
        page.click("#chat-dm")
        page.wait_for_selector('#dm-people .chat-row[data-person="u2"]')
        page.fill("#dm-find", "dav")
        check("anybody can message somebody privately, found by name",
              page.locator("#dm-people .chat-row").count() == 1)
        page.locator('#dm-people .chat-row[data-person="u2"]').click()
        page.wait_for_selector("#chat-text")
        check("which opens the conversation with them",
              CHAT_CALLS[-1] == ("open_direct", {"p_user": "u2"})
              and page.locator("#sheet-body h2").first.inner_text() == "Dave Floor")
        page.fill("#chat-text", "Can you grab the G4 roll?")
        page.click("#chat-send")
        page.wait_for_selector("#chat-msgs .chat-msg.mine")
        check("and the message goes to it",
              CHAT_MSGS[-1]["channel_id"] == "dm-u2"
              and CHAT_MSGS[-1]["body"] == "Can you grab the G4 roll?")
        page.locator("#sheet-body button", has_text="Close").last.click()
        page.wait_for_selector("#sheet.hidden", state="attached")

        page.click('#tabs button[data-tab="orders"]')
        CHATS[-1].update(unread=1, last_author="Dave Floor", last_body="On it")
        page.evaluate("TAFAPP._board.pollChats()")
        page.wait_for_selector("#toast")
        check("a message coming in pops up, whatever screen is open",
              "Dave Floor" in page.locator("#toast").inner_text()
              and "On it" in page.locator("#toast").inner_text()
              and page.locator("#chat-badge").inner_text() == "1")
        page.click("#toast")
        page.wait_for_selector("#chat-text")
        check("and tapping it opens the conversation",
              page.locator("#sheet-body h2").first.inner_text() == "Dave Floor")

        # Pulling the handle down closes the sheet.
        page.evaluate("""() => {
          const panel = document.querySelector('#sheet > div');
          const r = panel.getBoundingClientRect();
          const at = y => [new Touch({identifier: 1, target: panel,
                                      clientX: r.left + 50, clientY: y})];
          const fire = (type, y) => panel.dispatchEvent(new TouchEvent(type, {
            bubbles: true, cancelable: true,
            touches: type === 'touchend' ? [] : at(y),
            changedTouches: at(y)}));
          fire('touchstart', r.top + 10);
          fire('touchmove', r.top + 120);
          fire('touchmove', r.top + 320);
          fire('touchend', r.top + 320);
        }""")
        page.wait_for_selector("#sheet.hidden", state="attached", timeout=3000)
        check("pulling a sheet's handle down closes it",
              page.locator("#sheet.hidden").count() == 1)
        page.click('#tabs button[data-tab="orders"]')
        page.wait_for_selector("#screen table")
        page.locator("#screen tbody tr", has_text="PO-8842").first.click()
        page.wait_for_selector("#sheet:not(.hidden)")
        page.evaluate("""() => {
          const panel = document.querySelector('#sheet > div');
          const r = panel.getBoundingClientRect();
          const at = y => [new Touch({identifier: 1, target: panel,
                                      clientX: r.left + 50, clientY: y})];
          const fire = (type, y) => panel.dispatchEvent(new TouchEvent(type, {
            bubbles: true, cancelable: true,
            touches: type === 'touchend' ? [] : at(y), changedTouches: at(y)}));
          fire('touchstart', r.top + 10);
          fire('touchmove', r.top + 40);
          fire('touchend', r.top + 40);
        }""")
        page.wait_for_timeout(400)
        check("a small pull springs back rather than closing it",
              page.locator("#sheet:not(.hidden)").count() == 1)
        page.keyboard.press("Escape")
        page.wait_for_selector("#sheet.hidden", state="attached")

        meta = page.locator('meta[name="viewport"]').get_attribute("content")
        sizes = page.evaluate("""() => ['search', 'text', 'number'].map(t => {
          const i = document.createElement('input'); i.type = t;
          document.getElementById('screen').appendChild(i);
          const s = parseFloat(getComputedStyle(i).fontSize); i.remove(); return s; })""")
        check("the page does not zoom, and a box is big enough that tapping it "
              "does not zoom in either",
              "maximum-scale=1" in meta and "user-scalable=no" in meta
              and min(sizes) >= 16, f"{meta} {sizes}")
        SWITCHES.clear()
        page.evaluate("TAFAPP._floor.setFeatures({})")
        page.evaluate("TAFAPP._board.forgetSops()")

        print("\n── quotes ──")
        page.click('#tabs button[data-tab="quotes"]')
        page.wait_for_selector("#screen table")
        check("quotes are listed",
              page.locator("#screen tbody tr").count() == 2)
        page.locator("#screen tbody tr", has_text="Q-1041").first.click()
        page.wait_for_selector("#sheet:not(.hidden)")
        qsheet = page.locator("#sheet-body")
        check("its lines are shown", qsheet.locator("tbody tr").count() == 2)
        check("an unpriced line says so, rather than showing nothing",
              "to be confirmed" in qsheet.inner_text())
        check("and the quote warns how many were left out",
              "1 line has no price" in qsheet.inner_text(),
              qsheet.inner_text()[:300])
        page.locator("#sheet-body button", has_text="Close").first.click()
        page.wait_for_selector("#sheet.hidden", state="attached")

        print("\n── customers ──")
        page.click('#tabs button[data-tab="customers"]')
        page.wait_for_selector("#screen table")
        check("customers are listed",
              page.locator("#screen tbody tr").count() == 2)
        page.fill('#screen input[type="search"]', "caloundra")
        page.wait_for_timeout(150)
        check("search reaches the suburb, not just the name",
              page.locator("#screen tbody tr").count() == 1)
        page.locator("#screen tbody tr").first.click()
        page.wait_for_selector("#sheet:not(.hidden)")
        csheet = page.locator("#sheet-body")
        check("their details are shown",
              "jobs@bellscreek.com.au" in csheet.inner_text())
        check("and their orders", "PO-8842" in csheet.inner_text())
        page.locator("#sheet-body button", has_text="Close").first.click()
        page.wait_for_selector("#sheet.hidden", state="attached")

        print("\n── stock ──")
        page.click('#tabs button[data-tab="stock"]')
        page.wait_for_selector("#screen .stock-card")
        check("stock is shown as cards", page.locator("#screen .stock-card").count() == 2)
        check("what is low is flagged",
              page.locator("#screen .stock-card .nums b.low").count() == 1)
        g4 = page.locator('#screen .stock-card[data-stock="s1"]')
        check("each card has its name, stock and MOQ in its units",
              "G4 media roll 1m" in g4.inner_text()
              and "Stock 42 m" in g4.inner_text()
              and "MOQ 20 m" in g4.inner_text(), g4.inner_text())
        page.wait_for_function(
            "() => { const i = document.querySelector("
            "'.stock-card[data-stock=s1] img'); return i && i.complete "
            "&& i.naturalWidth > 0; }", timeout=5000)
        fit = page.eval_on_selector(
            ".stock-card[data-stock=s1] img",
            "i => getComputedStyle(i).objectFit")
        check("its photo loads, whole - shrunk to fit, not cropped",
              fit == "contain", fit)
        check("one with no photo says so",
              "No photo" in page.locator(
                  '#screen .stock-card[data-stock="s2"] .ph').inner_text())

        def _layout(width):
            page.set_viewport_size({"width": width, "height": 900})
            page.wait_for_timeout(150)
            return page.evaluate("""() => {
              const cards = [...document.querySelectorAll('.stock-card')];
              const boxes = cards.map(c => c.getBoundingClientRect());
              const tops = boxes.map(b => Math.round(b.top));
              const firstRow = boxes.filter(b => Math.round(b.top) === tops[0]);
              const overlaps = cards.some(c => [...c.querySelectorAll('.nm,.ds,.nums,.pr')]
                .some(el => el.getBoundingClientRect().bottom
                            > c.getBoundingClientRect().bottom + 0.5));
              const grid = document.querySelector('.stock-grid');
              const cols = getComputedStyle(grid).gridTemplateColumns.split(' ').length;
              const room = document.querySelector('.stock-wrap').clientWidth;
              return {room: room,
                      square: boxes.every(b => Math.abs(b.width - b.height) < 1.5),
                      same: new Set(boxes.map(b => Math.round(b.width))).size === 1,
                      perRow: firstRow.length, cols: cols, overlaps: overlaps,
                      sideways: document.documentElement.scrollWidth
                                > window.innerWidth};
            }""")
        def _across(room):
            # The same steps as the stylesheet and stock_cards.py, by the
            # room the grid has - the sidebar's share taken off already.
            for least, cols in ((1060, 5), (820, 4), (560, 3), (400, 2)):
                if room >= least:
                    return cols
            return 1
        for width, want in ((375, 1), (480, 2), (768, 2), (1024, 3), (1440, 5)):
            got = _layout(width)
            if os.environ.get("TAF_SHOTS"):
                page.screenshot(path=os.path.join(os.environ["TAF_SHOTS"],
                                                  f"web_{width}.png"))
            check(f"at {width}px: {want} across, square, same size, nothing "
                  "spilling, no sideways scrolling",
                  got["cols"] == want == _across(got["room"])
                  and got["square"] and got["same"]
                  and not got["overlaps"] and not got["sideways"], str(got))
        page.set_viewport_size({"width": 900, "height": 900})

        page.check('#screen input[type="checkbox"]')
        page.wait_for_timeout(150)
        check("what is low can be shown on its own",
              page.locator("#screen .stock-card").count() == 1)
        page.uncheck('#screen input[type="checkbox"]')
        page.fill('#screen input[type="search"]', "pleatable")
        page.wait_for_timeout(250)
        check("search finds by description too",
              page.locator("#screen .stock-card").count() == 1)
        page.fill('#screen input[type="search"]', "")
        page.wait_for_timeout(250)

        page.locator('#screen .stock-card[data-stock="s2"]').click()
        page.wait_for_selector("#sheet:not(.hidden)")
        ssheet = page.locator("#sheet-body")
        before = STOCK[1]["stock_on_hand"]
        page.select_option("#sheet-body select", "receive")
        page.fill('#sheet-body input[inputmode="decimal"]', "30")
        page.locator("#sheet-body button", has_text="Save the adjustment").click()
        page.wait_for_timeout(400)
        check("an adjustment reaches the database",
              STOCK[1]["stock_on_hand"] == before + 30,
              str(STOCK[1]["stock_on_hand"]))
        check("and the new figure is shown back",
              str(before + 30) in ssheet.inner_text())
        check("every adjustment carries a reference, so a double tap "
              "cannot double-count",
              all(b.get("p_client_ref") for _u, b in stub.calls
                  if "p_item_id" in b))
        page.locator("#sheet-body button", has_text="Close").first.click()
        page.wait_for_selector("#sheet.hidden", state="attached")

        print("\n── scanning a code ──")

        def newest():
            """The card for the code most recently scanned."""
            return page.locator("#scans .card").first

        page.click('#tabs button[data-tab="scan"]')
        page.wait_for_selector("#screen .code")
        page.fill("#screen input.code", "PO-8842")
        page.press("#screen input.code", "Enter")
        page.wait_for_selector("#screen button.hit")
        check("a scanned order number finds the order",
              "Bells Creek" in newest().inner_text())
        page.click("#screen button.hit")
        page.wait_for_selector("#sheet:not(.hidden)")
        check("and opens it, ready to tick off",
              "Bells Creek" in page.locator("#sheet-body h2").first.inner_text())
        page.locator("#sheet-body button", has_text="Close").first.click()
        page.wait_for_selector("#sheet.hidden", state="attached")

        page.fill("#screen input.code", "MED-G4-1M")
        page.press("#screen input.code", "Enter")
        page.wait_for_timeout(300)
        check("a scanned rack label finds the stock item",
              "G4 media roll" in newest().inner_text())

        page.fill("#screen input.code", "NOT-A-CODE")
        page.press("#screen input.code", "Enter")
        page.wait_for_timeout(300)
        check("a code that means nothing says so, rather than nothing at all",
              "Nothing here answers to that code" in newest().inner_text())

        # Every iPhone today, and Firefox. The camera button must not sit
        # there doing nothing with no explanation.
        page.evaluate("window.__BD = window.BarcodeDetector;"
                      "delete window.BarcodeDetector;")
        page.click('#tabs button[data-tab="orders"]')
        page.click('#tabs button[data-tab="scan"]')
        page.wait_for_selector("#screen .code")
        check("a browser that cannot read barcodes says what to do instead",
              "cannot read a barcode" in page.locator("#screen").inner_text())
        check("and does not offer a camera button that would do nothing",
              page.locator('#screen button:has-text("Use the camera")')
              .is_disabled())

        print("\n── the camera ──")
        # A stubbed detector and a canvas for a camera: the point being
        # tested is the loop around them, not Chromium's barcode support.
        page.evaluate("""() => {
          window.BarcodeDetector = function () {
            this.detect = function () {
              return Promise.resolve([{ rawValue: "TAF-ON-0002" }]);
            };
          };
          window.BarcodeDetector.getSupportedFormats =
            () => Promise.resolve(["code_128"]);
          // A fresh stream each time it is asked for, all of them kept, so
          // a camera left running on the second go cannot hide behind the
          // first one having been stopped.
          window.__streams = [];
          navigator.mediaDevices.getUserMedia = function () {
            const c = document.createElement("canvas");
            c.width = 320; c.height = 240;
            const s = c.captureStream(5);
            window.__streams.push(s);
            return Promise.resolve(s);
          };
        }""")
        ended = ("window.__streams.length === %d && window.__streams.every("
                 "s => s.getTracks().every(t => t.readyState === 'ended'))")
        page.click('#tabs button[data-tab="orders"]')
        page.click('#tabs button[data-tab="scan"]')
        page.wait_for_selector('#screen button:not([disabled]):has-text("Use the camera")')
        scans_before = len([1 for u, _b in stub.calls if "resolve_scan" in u])
        page.click('#screen button:has-text("Use the camera")')
        page.wait_for_selector('#scans .card:has-text("TAF-ON-0002")',
                               timeout=6000)
        check("the camera reads a code and looks it up",
              "CAS - Tweed" in newest().inner_text())
        # It sees the same label thirty times a second. Every frame must not
        # become a request.
        page.wait_for_timeout(1500)
        scans = len([1 for u, _b in stub.calls if "resolve_scan" in u]) - scans_before
        check("one label held in front of it is one lookup, not thirty",
              scans <= 2, f"{scans} lookups in 1.8 seconds")
        page.click('#screen button:has-text("Stop the camera")')
        page.wait_for_timeout(200)
        check("stopping it puts the camera down", page.evaluate(ended % 1))
        # Leaving the tab must do the same, or the light on the back of the
        # phone stays on for the rest of the day.
        page.click('#screen button:has-text("Use the camera")')
        page.wait_for_timeout(500)
        page.click('#tabs button[data-tab="orders"]')
        page.wait_for_timeout(300)
        check("and so does walking away from the tab",
              page.evaluate(ended % 2),
              page.evaluate("window.__streams.map(s =>"
                            " s.getTracks().map(t => t.readyState).join())"
                            ".join(' | ')"))

        print("\n── no signal ──")
        page.wait_for_selector("#screen table")
        page.locator("#screen tbody tr", has_text="Bells Creek").first.click()
        page.wait_for_selector("#sheet-body button.tick")
        ticks = page.locator("#sheet-body button.tick")
        was = ITEMS["o1"][1].get("made")

        # The wifi at the back of the factory, as the browser sees it: the
        # request never arrives anywhere.
        page.route("**/rest/v1/rpc/set_order_line_made*",
                   lambda r: r.abort("internetdisconnected"))
        ticks.nth(1).click()
        page.wait_for_timeout(400)
        check("a tick out of signal says it is kept, not that it failed",
              "Kept on this phone" in page.locator("#sheet-body").inner_text())
        check("the line shows as ticked all the same",
              ticks.nth(1).get_attribute("aria-pressed") == "true")
        check("and marked as not gone yet",
              "waiting" in (ticks.nth(1).get_attribute("class") or ""))
        check("nothing reached the database",
              ITEMS["o1"][1].get("made") == was)
        check("the bar under the tabs says one change is waiting",
              "1 change waiting" in page.locator("#state").inner_text())

        page.locator("#sheet-body button", has_text="Close").first.click()
        page.wait_for_selector("#sheet.hidden", state="attached")

        # The signal comes back, but nothing has been flushed yet. A change
        # made now must go behind what is already waiting, not overtake it —
        # a tick and the untick that followed it arriving the wrong way round
        # would leave the order saying the opposite of what happened.
        page.unroute("**/rest/v1/rpc/set_order_line_made*")
        page.locator("#screen tbody tr", has_text="Bells Creek").first.click()
        page.wait_for_selector("#sheet-body button.tick")
        page.locator("#sheet-body button.tick").nth(2).click()
        page.wait_for_timeout(400)
        check("with signal back, a new change still goes behind the queue",
              "2 changes waiting" in page.locator("#state").inner_text(),
              page.locator("#state").inner_text())
        check("and does not reach the database ahead of it",
              ITEMS["o1"][2].get("made") is not True)
        page.locator("#sheet-body button", has_text="Close").first.click()
        page.wait_for_selector("#sheet.hidden", state="attached")

        page.locator('#state button:has-text("Send now")').click()
        page.wait_for_timeout(600)
        check("back in signal, what was waiting goes through",
              ITEMS["o1"][1].get("made") is True
              and ITEMS["o1"][2].get("made") is True)
        check("and the bar goes away", page.locator("#state").is_hidden())

        print("\n── what the phone remembers ──")
        page.route("**/rest/v1/orders_list*",
                   lambda r: r.abort("internetdisconnected"))
        page.evaluate("TAFAPP._stale()")
        page.click('#tabs button[data-tab="dashboard"]')
        page.click('#tabs button[data-tab="orders"]')
        page.wait_for_selector("#screen table")
        check("with no signal the last list it saw is still there",
              page.locator("#screen tbody tr").count() >= 3)
        check("and it says so, rather than passing it off as today's",
              "what the phone last saw" in page.locator("#screen").inner_text())
        page.unroute("**/rest/v1/orders_list*")

        page.route("**/rest/v1/rpc/resolve_scan*",
                   lambda r: r.abort("internetdisconnected"))
        page.click('#tabs button[data-tab="scan"]')
        page.wait_for_selector("#screen .code")
        page.fill("#screen input.code", "MED-G4-1M")
        page.press("#screen input.code", "Enter")
        page.wait_for_timeout(300)
        check("a rack label still resolves with no signal at all",
              "G4 media roll" in page.locator("#scans .card").first.inner_text())
        page.unroute("**/rest/v1/rpc/resolve_scan*")

        print("\n── who did what ──")
        # Nothing was returned on the way in: audit_log lets everyone write
        # and only managers read, so asking for the row back would have the
        # database refuse the whole insert. The stub above enforces that, so
        # an entry being here at all is the proof.
        ticks = [e for e in LOGGED if e.get("action") in
                 ("line_made", "line_unmade")]
        check("ticking a line off is written down", bool(ticks),
              str(LOGGED[-3:]))
        check("with the order and the line on it",
              any("PO-8842" in (e.get("details") or "")
                  and "Line" in (e.get("details") or "") for e in ticks))
        check("a status change too",
              any(e.get("action") == "order_status" for e in LOGGED))
        # The two that were queued out of signal. Sent later, so the entry
        # has to say when they were actually done.
        check("and something done out of signal says when it was done",
              any("sent when the signal came back" in (e.get("details") or "")
                  for e in LOGGED), str([e.get("details") for e in ticks]))
        check("under the account that did it",
              all(e.get("user_id") == "u1" for e in LOGGED))

        page.click('#tabs button[data-tab="log"]')
        page.wait_for_selector("#screen table")
        who = page.locator("#screen select").nth(0)
        when = page.locator("#screen select").nth(1)
        check("it opens on today, not on everything ever",
              "Prices imported" not in page.locator("#screen").inner_text())
        check("the day's work is there, ticks and all",
              "Line made" in page.locator("#screen").inner_text()
              or "Line unmade" in page.locator("#screen").inner_text())
        when.select_option("Everything")
        page.wait_for_timeout(200)
        check("a manager can read back further",
              "Prices imported" in page.locator("#screen").inner_text())
        who.select_option("dan")
        page.wait_for_timeout(200)
        text = page.locator("#screen").inner_text()
        check("and it can be narrowed to one person",
              "Prices imported" in text and "Order created" not in text)
        who.select_option("Everyone")
        page.fill('#screen input[type="search"]', "PO-8842")
        page.wait_for_timeout(200)
        check("or to one order",
              "PO-8842" in page.locator("#screen").inner_text()
              and "Prices imported" not in page.locator("#screen").inner_text())

        print("\n── being told, rather than going to look ──")
        page.click("#who")
        page.wait_for_selector("#sheet:not(.hidden)")
        mine = page.locator('#sheet-body input[type="checkbox"]')
        page.wait_for_function(
            "() => { const b = document.querySelector"
            "('#sheet-body input[type=checkbox]'); return b && !b.disabled; }")
        check("your own name opens what is yours",
              "Kai Brown" in page.locator("#sheet-body").inner_text())
        check("and the summary starts off", not mine.is_checked())
        check("saying so plainly",
              "not on the list" in page.locator("#sheet-body").inner_text())
        mine.check()
        page.wait_for_timeout(300)
        check("ticking it puts you on the list", NOTIFY["on"] is True)
        check("and says the company switch still has to be on too",
              "on the list" in page.locator("#sheet-body").inner_text())

        page.locator("#sheet-body button", has_text="Send mine now").click()
        page.wait_for_timeout(400)
        check("you can send yourself one there and then", len(SUMMARIES) == 1)
        check("without asking to send everybody one",
              SUMMARIES[0].get("everyone") is None, str(SUMMARIES[0]))
        check("and it says it went", "Check your inbox"
              in page.locator("#sheet-body").inner_text())

        # Switched off for the company, nothing is sent, and it is not
        # reported as a failure — nothing is wrong, nobody has turned it on.
        NOTIFY["company"] = False
        page.locator("#sheet-body button", has_text="Send mine now").click()
        page.wait_for_timeout(400)
        check("with the company switch off it says so rather than failing",
              "switched off" in page.locator("#sheet-body").inner_text())
        NOTIFY["company"] = True
        page.locator("#sheet-body button", has_text="Close").first.click()
        page.wait_for_selector("#sheet.hidden", state="attached")

        print("\n── the bell ──")
        badge = page.locator("#bell-badge")
        page.wait_for_function(
            "() => document.getElementById('bell-badge').textContent !== ''")
        check("signing in as a manager with three unread shows a red 3",
              badge.inner_text() == "3" and badge.is_visible()
              and "has" in (page.get_attribute("#bell", "class") or ""),
              badge.inner_text())
        check("and says so to a screen reader",
              page.get_attribute("#bell", "aria-label")
              == "3 new notifications")

        rules = page.evaluate("""() => [0, 1, 9, 99, 100, 150, -2, 'x']
                                   .map(n => TAFAPP._badgeText(n))""")
        check("the badge reads nothing, then the number, then 99+",
              rules == ["", "1", "9", "99", "99+", "99+", "", ""], str(rules))

        BELL["override"] = 150
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        page.wait_for_function(
            "() => document.getElementById('bell-badge').textContent"
            " === '99+'")
        fits = page.evaluate("""() => {
          const b = document.getElementById('bell-badge');
          return b.scrollWidth <= b.clientWidth + 1; }""")
        check("150 unread reads 99+, and it fits in the badge",
              badge.inner_text() == "99+" and fits)
        BELL["override"] = None
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        page.wait_for_function(
            "() => document.getElementById('bell-badge').textContent === '3'")
        check("picking the phone back up asks again straight away",
              badge.inner_text() == "3")

        page.click("#bell")
        page.wait_for_selector("#sheet-body .note-row")
        rows = page.locator("#sheet-body .note-row")
        check("tapping the bell lists what is new",
              rows.count() == 3 and "Rivets" in rows.first.inner_text())
        check("unread ones look unread",
              page.locator("#sheet-body .note-row.new").count() == 3)
        rows.first.click()
        page.wait_for_selector('#tabs button[data-tab="supplies"]'
                               '[aria-selected="true"]')
        page.wait_for_function(
            "() => document.getElementById('bell-badge').textContent === '2'")
        check("tapping one opens Supplies and counts it read",
              badge.inner_text() == "2")

        print("\n── supplies, as orders ──")
        page.wait_for_selector("#screen .sup-order")
        check("there is no Ask for something form - New order is the way in",
              page.locator("#supply-item").count() == 0
              and "Ask for something" not in page.locator("#screen").inner_text()
              and page.locator("#supply-new-order").count() == 1)
        first = page.locator("#screen .sup-order").first.inner_text()
        check("the urgent one waiting is at the top",
              first.startswith("URGENT") and "Rivets" in first, first)
        check("what is already on order says who ordered it",
              "Sarah Boss" in page.locator("#screen").inner_text())
        check("a manager is offered Ordered, Received and Decline",
              page.locator("#screen button", has_text="Ordered").count() >= 1
              and page.locator("#screen button", has_text="Decline").count() >= 1)

        # Something not on the stock list, out of signal at the back of the
        # factory.
        page.route("**/rest/v1/rpc/request_supplies*",
                   lambda r: r.abort("internetdisconnected"))
        before = len(SUPPLY)
        page.click("#supply-new-order")
        page.wait_for_selector("#no-results .no-pick")
        page.fill("#no-other", "duct tape 48mm")
        page.click("#no-other-add")
        typed = '#no-lines [data-line="other-0"] input'
        check("something typed that is not on the stock list goes on, "
              "waiting for how many",
              page.locator("#no-lines .no-line.typed").count() == 1
              and page.evaluate("document.activeElement === "
                                f"document.querySelector('{typed}')"))
        page.fill(typed, "2 rolls")
        page.check("#no-urgent")
        page.click("#no-send")
        wait_for_text(page, "#screen", "Kept on this phone")
        check("with no signal it is kept on the phone, and says so",
              len(SUPPLY) == before)
        page.unroute("**/rest/v1/rpc/request_supplies*")
        page.evaluate("TAFSYNC.flush()")
        page.wait_for_timeout(500)
        sent = [b for u, b in stub.calls if "rpc/request_supplies" in u]
        check("when the signal is back it goes, as its kind, urgent, with a "
              "reference of its own",
              sent and sent[-1]["p_lines"] == [
                  {"item": "Tape", "detail": "duct tape 48mm",
                   "quantity": "2 rolls", "supplier_id": "", "item_code": "",
                   "stock_item_id": ""}]
              and sent[-1]["p_urgent"] is True and sent[-1].get("p_client_ref")
              and sum(1 for r in SUPPLY if r["detail"] == "duct tape 48mm") == 1,
              str(sent[-1:]))
        check("never who is asking - the database writes that",
              "requested_by" not in json.dumps(sent[-1]))
        page.evaluate("""(ref) => TAFDATA.rpc('request_supplies', {
            p_lines: [{item: 'Tape', detail: 'duct tape 48mm', quantity: '2 rolls'}],
            p_urgent: true, p_note: '', p_client_ref: ref })""",
                      sent[-1]["p_client_ref"])
        page.wait_for_timeout(300)
        check("sent again after a dropout, it is still filed once",
              sum(1 for r in SUPPLY if r["detail"] == "duct tape 48mm") == 1)
        check("and it is logged, without asking to read the log back",
              any(e.get("action") == "supply_requested" for e in LOGGED))

        print("\n── New order, from the stock list ──")
        STOCK[1]["stock_on_hand"] = 6          # the F5 roll, low again
        page.click('#tabs button[data-tab="supplies"]')
        page.wait_for_selector("#screen .sup-order")
        if os.environ.get("TAF_SHOTS"):
            page.set_viewport_size({"width": 390, "height": 860})
            page.wait_for_timeout(150)
            page.screenshot(path=os.path.join(os.environ["TAF_SHOTS"],
                                              "web_supplies_390.png"))
            page.set_viewport_size({"width": 900, "height": 900})
        page.click("#supply-new-order")
        page.wait_for_selector("#no-results .no-pick")
        picks = page.eval_on_selector_all("#no-results .no-pick",
                                          "bs => bs.map(b => b.dataset.stock)")
        check("New order lists the stock, the low one first", picks == ["s2", "s1"],
              str(picks))
        page.click("#no-low")
        line = '#no-lines [data-line="s2"]'
        check("Add everything low puts on what gets it back to its minimum, "
              "from where it comes from",
              page.locator("#no-lines .no-line").count() == 1
              and page.input_value(line + " input") == "19"
              and page.input_value(line + " select") == "s-vul",
              page.locator("#no-lines").inner_text())
        page.fill("#no-find", "g4")
        found = page.eval_on_selector_all("#no-results .no-pick",
                                          "bs => bs.map(b => b.dataset.stock)")
        check("searching narrows the list", found == ["s1"], str(found))
        page.click('#no-results .no-pick[data-stock="s1"]')
        check("tapping one puts it on, waiting for how many",
              page.locator("#no-lines .no-line").count() == 2
              and page.input_value('#no-lines [data-line="s1"] input') == ""
              and page.evaluate("document.activeElement.closest('[data-line]')"
                                " && document.activeElement.closest('[data-line]')"
                                ".dataset.line") == "s1")
        before = len([u for u, _b in stub.calls if "rpc/request_supplies" in u])
        page.click("#no-send")
        check("it is not sent while one says no number",
              "Say how many G4" in page.locator("#sheet-body").inner_text()
              and len([u for u, _b in stub.calls
                       if "rpc/request_supplies" in u]) == before)
        page.fill('#no-lines [data-line="s1"] input', "40")
        if os.environ.get("TAF_SHOTS"):
            page.fill("#no-find", "")
            for width in (390, 1200):
                page.set_viewport_size({"width": width, "height": 860})
                page.wait_for_timeout(150)
                page.screenshot(path=os.path.join(os.environ["TAF_SHOTS"],
                                                  f"web_new_order_{width}.png"))
            page.set_viewport_size({"width": 900, "height": 900})
        page.click("#no-send")
        wait_for_text(page, "#screen", "managers have been told")
        many = [b for u, b in stub.calls if "rpc/request_supplies" in u]
        check("the order goes as one request: each stock item, in its own "
              "units, with the supplier's code",
              len(many) == before + 1 and many[-1]["p_lines"] == [
                  {"item": "Media", "detail": "F5 media roll 1m",
                   "quantity": "19 m", "supplier_id": "s-vul",
                   "item_code": "VUL-F5", "stock_item_id": "s2"},
                  {"item": "Media", "detail": "G4 media roll 1m",
                   "quantity": "40 m", "supplier_id": "", "item_code": "",
                   "stock_item_id": "s1"}], str(many[-1:]))
        check("and the sheet closes", page.locator("#sheet.hidden").count() == 1)

        # The phone's rules are the desktop's (purchasing.py).
        sys.path.insert(0, str(ROOT))
        from taf_order_app import purchasing as _buy
        sample = [
            {"id": "a", "name": "C Channel 45mm", "product_type": "Channel",
             "stock_on_hand": 4, "minimum_on_hand": 20, "unit": "lengths"},
            {"id": "b", "name": "Foil tape 48mm", "product_type": "Tape",
             "stock_on_hand": 30, "minimum_on_hand": 10, "unit": "rolls"},
            {"id": "c", "name": "C Channel 25mm", "stock_on_hand": 0,
             "minimum_on_hand": 0, "unit": "lengths"},
            {"id": "d", "name": "G4 media", "description": "Pleated",
             "stock_on_hand": 2, "minimum_on_hand": 5.5, "unit": "rolls"},
            {"id": "e", "name": "Pop rivet 4mm", "stock_on_hand": 1,
             "minimum_on_hand": 3, "unit": "each"},
            {"id": "f", "name": "Galv mesh 6mm", "stock_on_hand": 9,
             "minimum_on_hand": 0, "unit": "m2"}]
        links = [{"stock_item_id": "a", "supplier_id": "s-vul", "supplier_code": "V45"},
                 {"stock_item_id": "a", "supplier_id": "s-fdg",
                  "supplier_code": "CC45", "preferred": True},
                 {"stock_item_id": "d", "supplier_id": "s-vul", "supplier_code": "G4"}]
        js = page.evaluate("""([rows, links]) => {
            const N = TAFAPP._newOrder;
            return {
              search: ['', 'chan', '45 chan', 'pleated', 'zzz'].map(
                t => N.searchStock(rows, t).map(r => r.id)),
              low: N.lowPicks(rows, links, {a: 3}).map(p => [p.stock.id, p.quantity, p.supplier_id]),
              kinds: rows.map(r => N.supplyItemFor(r)),
              lines: rows.map(r => N.stockRequestLine(r, '3', r.id === 'a' ? 's-fdg' : '', links)),
              onOrder: N.onOrderOf([{status: 'sent', lines: [
                  {stock_item_id: 'a', quantity: 10, received: 4},
                  {item_id: 'd', quantity: 2}]},
                {status: 'received', lines: [{stock_item_id: 'a', quantity: 9}]}])
            }; }""", [sample, links])
        from taf_order_app import records as _rec
        py = {
            "search": [[r["id"] for r in _buy.search_stock(sample, t)]
                       for t in ("", "chan", "45 chan", "pleated", "zzz")],
            "low": [[p["stock"]["id"], p["quantity"], p["supplier_id"]]
                    for p in _buy.low_picks(sample, links, {"a": 3})],
            "kinds": [_buy.supply_item_for(r) for r in sample],
            "lines": [_buy.stock_request_line(r, "3", "s-fdg" if r["id"] == "a" else "",
                                              links) for r in sample],
            "onOrder": _rec.quantities_on_order([
                {"status": "sent", "lines": [
                    {"stock_item_id": "a", "quantity": 10, "received": 4},
                    {"item_id": "d", "quantity": 2}]},
                {"status": "received", "lines": [{"stock_item_id": "a", "quantity": 9}]}]),
        }
        js["other"] = page.evaluate("TAFAPP._newOrder.otherRequestLine("
                                    "'  pop rivets  4mm ', '2 boxes', 's-x')")
        py["other"] = _buy.other_request_line("  pop rivets  4mm ", "2 boxes", "s-x")
        from taf_order_app import supplies as _sup
        rows = [
            {"id": "r1", "batch_id": "b1", "client_ref": "x-1", "item": "Tape",
             "detail": "foil", "quantity": "3", "status": "open",
             "requested_by": "dave", "requested_by_name": "Dave",
             "created_at": "2026-10-10T01:00:00Z", "note": "bench 2"},
            {"id": "r2", "batch_id": "b1", "client_ref": "x-2", "item": "Rivets",
             "detail": "4mm", "status": "ordered", "handled_by_name": "Sarah",
             "requested_by": "dave", "created_at": "2026-10-10T01:00:00Z"},
            {"id": "r3", "batch_id": "b1", "client_ref": "x-3", "item": "Media",
             "detail": "G4", "status": "open", "requested_by": "dave",
             "created_at": "2026-10-10T01:00:00Z"},
            {"id": "r4", "item": "Channel", "detail": "45mm", "status": "open",
             "urgent": True, "requested_by": "amy",
             "created_at": "2026-10-12T01:00:00Z"},
            {"id": "r5", "batch_id": "b2", "client_ref": "y-1", "item": "Tape",
             "status": "received", "handled_by_name": "Kai",
             "created_at": "2026-10-11T01:00:00Z"},
            {"id": "r6", "batch_id": "b3", "client_ref": "z-1", "item": "Tape",
             "status": "received", "created_at": "2026-10-09T01:00:00Z"},
            {"id": "r7", "batch_id": "b3", "client_ref": "z-2", "item": "Mesh Wire",
             "status": "ordered", "created_at": "2026-10-09T01:00:00Z"}]
        js_orders = page.evaluate("""(rows) => {
            const O = TAFAPP._supplyOrders;
            return O.group(rows).map(o => ({
              key: o.key, ids: o.lines.map(l => l.id), status: o.status,
              urgent: o.urgent, label: O.label(o), summary: O.summary(o),
              move: ['ordered', 'received', 'declined'].map(
                to => O.toMove(o.lines, to).map(l => l.id)),
              cancel: O.toCancel(o.lines, 'dave').map(l => l.id)})); }""", rows)
        js["orders"] = js_orders
        py["orders"] = [{
            "key": o["key"], "ids": [l["id"] for l in o["lines"]],
            "status": o["status"], "urgent": o["urgent"],
            "label": _sup.order_label(o), "summary": _sup.order_summary(o),
            "move": [[l["id"] for l in _sup.lines_to_move(o, to)]
                     for to in ("ordered", "received", "declined")],
            "cancel": [l["id"] for l in _sup.lines_to_cancel(o, "dave")]}
            for o in _sup.group_requests(rows)]
        # 6 in JavaScript is 6.0 in Python: the amounts, as numbers.
        js["onOrder"] = {k: float(v) for k, v in js["onOrder"].items()}
        py["onOrder"] = {k: float(v) for k, v in py["onOrder"].items()}
        for key in py:
            check(f"New order on the phone works out {key} as the desktop does",
                  json.dumps(js[key], sort_keys=True) == json.dumps(py[key], sort_keys=True),
                  f"{js[key]} != {py[key]}")

        page.click('#tabs button[data-tab="supplies"]')
        page.wait_for_selector("#screen .sup-order")
        batch = many[-1]["p_client_ref"]
        card = f'#screen .sup-order[data-order="b-{batch}"]'
        check("what was sent together is one order, its lines in it",
              page.locator(card).count() == 1
              and page.locator(card + " li").count() == 2
              and page.locator(card + " .hd b").inner_text() == "2 items",
              page.locator("#screen").inner_text()[:400])
        if os.environ.get("TAF_SHOTS"):
            page.set_viewport_size({"width": 390, "height": 860})
            page.locator(card).scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            page.screenshot(path=os.path.join(os.environ["TAF_SHOTS"],
                                              "web_supply_orders_390.png"))
            page.set_viewport_size({"width": 900, "height": 900})
        page.locator('#screen .sup-order[data-order="sr1"] button',
                     has_text="Ordered").click()
        page.wait_for_timeout(400)
        check("marking one ordered moves it along",
              next(r for r in SUPPLY if r["id"] == "sr1")["status"] == "ordered")
        check("and that clears it from the bell",
              page.locator("#bell-badge").inner_text() == "1",
              page.locator("#bell-badge").inner_text())

        # A New order on the bell: off it once the whole order is dealt with.
        first_line = next(r for r in SUPPLY if r.get("batch_id") == f"b-{batch}")
        NOTES.append({"id": "n9", "kind": "supply_request",
                      "ref_id": first_line["id"], "title": "2 supplies asked for",
                      "body": "Dave Floor asked for 2 things", "read_at": None,
                      "created_at": "2026-09-24T02:00:00Z"})
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        page.wait_for_function(
            "() => document.getElementById('bell-badge').textContent === '2'")
        page.locator(card + " button", has_text="Ordered").click()
        page.wait_for_function(
            "() => document.getElementById('bell-badge').textContent === '1'")
        check("Ordered on an order moves every line on it",
              {r["status"] for r in SUPPLY if r.get("batch_id") == f"b-{batch}"}
              == {"ordered"})
        page.click("#bell")
        page.wait_for_selector("#sheet-body .note-row", state="attached")
        check("and it is gone from the bell, not just marked read",
              "2 supplies asked for" not in page.locator("#sheet-body").inner_text())
        page.keyboard.press("Escape")
        page.wait_for_selector("#sheet.hidden", state="attached")

        REFUSE_MOVE["on"] = True
        page.locator('#screen .sup-order[data-order="sr2"] button',
                     has_text="Ordered").click()
        # Waited for briefly and then judged, rather than waited for forever:
        # if the page wrongly treats the refusal as done, there is no message
        # to wait for, and that should be a FAIL here, not a timeout that
        # takes every check after it down too.
        try:
            page.wait_for_selector("#screen .err", timeout=4000)
        except Exception:
            pass
        check("a change the database quietly refused is not shown as done",
              "didn't change anything" in page.locator("#screen").inner_text())
        REFUSE_MOVE["on"] = False

        page.click("#bell")
        page.wait_for_selector("#sheet-body button", state="attached")
        page.locator("#sheet-body button", has_text="Mark all read").click()
        page.wait_for_selector("#sheet.hidden", state="attached")
        page.wait_for_function(
            "() => document.getElementById('bell-badge').textContent === ''")
        check("mark all read and the bell goes quiet",
              page.locator("#bell-badge").is_hidden()
              and "has" not in (page.get_attribute("#bell", "class") or ""))

        print("\n── a phone left on the bench ──")
        page.evaluate("TAFAPP._stillThere()")
        page.wait_for_selector("#sheet:not(.hidden)")
        check("after a long time untouched it asks before signing out",
              "Still there?" in page.locator("#sheet-body").inner_text())
        page.locator("#sheet-body button", has_text="I am still here").click()
        page.wait_for_selector("#sheet.hidden", state="attached")
        check("and saying so keeps you in", page.locator("#app").is_visible())

        # It must not sign out over work that is still on the phone: nobody
        # else could ever send it.
        page.click('#tabs button[data-tab="orders"]')
        page.wait_for_selector("#screen table")
        page.route("**/rest/v1/rpc/set_order_line_made*",
                   lambda r: r.abort("internetdisconnected"))
        page.locator("#screen tbody tr", has_text="Bells Creek").first.click()
        page.wait_for_selector("#sheet-body button.tick")
        page.locator("#sheet-body button.tick").nth(1).click()
        page.wait_for_timeout(300)
        page.locator("#sheet-body button", has_text="Close").first.click()
        page.wait_for_selector("#sheet.hidden", state="attached")
        page.evaluate("TAFAPP._stillThere()")
        page.wait_for_selector("#sheet:not(.hidden)")
        page.locator("#sheet-body button", has_text="Sign me out").click()
        page.wait_for_timeout(500)
        check("it will not sign out over work that has not been sent",
              page.locator("#app").is_visible()
              and "cannot be sent" in page.locator("#sheet-body").inner_text(),
              page.locator("#sheet-body").inner_text()[:200])
        page.unroute("**/rest/v1/rpc/set_order_line_made*")
        page.evaluate("TAFSYNC.flush()")
        page.wait_for_timeout(500)
        page.keyboard.press("Escape")
        page.wait_for_selector("#sheet.hidden", state="attached")

        print("\n── signing out ──")
        check("nothing is left covering the app",
              page.locator("#sheet").is_hidden())
        page.click("#signout")
        page.wait_for_selector("#signin-form", timeout=8000)
        check("signing out returns to the login page",
              page.locator("#app").is_hidden())
        check("and the session is forgotten",
              page.evaluate("localStorage.getItem('taf_staff_session')") is None)

        print("\n── what an employee sees ──")
        # The database refuses them the log either way. This is about not
        # offering a tab whose only possible content is a refusal.
        PROFILE["role"] = "Employee"
        page.fill("#email", "kai@taf.local")
        page.fill("#password", "correct-horse")
        page.click("#signin-go")
        page.wait_for_selector("#app:not(.hidden)")
        check("an employee is not offered the log",
              page.locator('#tabs button[data-tab="log"]').count() == 0)
        check("but everything they do use is still there",
              page.locator('#tabs button[data-tab="orders"]').count() == 1
              and page.locator('#tabs button[data-tab="scan"]').count() == 1)

        # Somebody on the floor is who Supplies is for. They ask; they do not
        # mark things ordered - and the one thing they can change is taking
        # back their own request while nothing has been done about it.
        check("the floor can reach Supplies",
              page.locator('#tabs button[data-tab="supplies"]').count() == 1)
        SUPPLY.append({"id": "mine", "item": "Tape", "detail": "foil",
                       "quantity": "1", "urgent": False, "status": "open",
                       "requested_by": "u1", "requested_by_name": "Kai Brown",
                       "handled_by_name": "",
                       "created_at": "2026-09-24T02:00:00Z"})
        page.click('#tabs button[data-tab="supplies"]')
        page.wait_for_selector("#screen .sup-order")
        check("an employee is not offered Ordered, Received or Decline",
              page.locator("#screen button", has_text="Received").count() == 0
              and page.locator("#screen button", has_text="Decline").count() == 0)
        check("but can cancel a request of their own that is still waiting",
              page.locator('#screen .sup-order[data-order="mine"] button',
                           has_text="Cancel").count() == 1)
        check("and nobody else's",
              page.locator('#screen .sup-order[data-order="sr2"] button',
                           has_text="Cancel").count() == 0)
        PROFILE["role"] = "Manager"

        print("\n── kept on the phone ──")
        # A service worker needs a real origin, and file:// has none — so
        # this last part is served over http out of the same folder GitHub
        # Pages serves, which is the only way to prove the thing the whole
        # feature rests on: that the app opens with the network off.
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):    # noqa: D102 - a silent test server
                pass

        handler = functools.partial(Quiet, directory=str(ROOT / "docs"))
        httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        crashes: list = []
        try:
            ctx = browser.new_context()
            p2 = ctx.new_page()
            p2.on("pageerror", lambda e: crashes.append(str(e)))
            p2.route("**/rest/v1/**", stub.route)
            p2.route("**/auth/v1/**", stub.route)
            p2.goto(f"http://127.0.0.1:{port}/app/index.html?k=test-anon-key")
            p2.wait_for_function(
                "navigator.serviceWorker && navigator.serviceWorker.controller",
                timeout=20000)
            check("the app puts itself on the phone", True)

            paths = p2.evaluate("""async () => {
              const names = await caches.keys();
              const c = await caches.open(names[0]);
              return (await c.keys()).map(r => new URL(r.url).pathname);
            }""")
            need = ["/app/index.html", "/app/screens.js", "/app/offline.js",
                    "/app/data.js", "/app/ui.js", "/company.js",
                    "/taf-shared.js", "/app/manifest.webmanifest",
                    "/app/icon-192.png"]
            check("everything it is made of is kept there",
                  all(f in paths for f in need),
                  "missing " + str([f for f in need if f not in paths]))
            # The one thing that must never be cached. A stock figure served
            # from yesterday looks exactly like today's and is not.
            check("and nothing from the database is",
                  not any("/rest/" in p or "/auth/" in p or "/storage/" in p
                          for p in paths), str(paths))

            ctx.set_offline(True)
            # A plain reload proves nothing: Chromium would serve that out of
            # its own HTTP cache whether or not any of this works. An address
            # it has never fetched cannot come from there, so if this opens,
            # the worker is what opened it.
            opened, why = True, ""
            try:
                p2.goto(f"http://127.0.0.1:{port}/app/index.html?fresh=1")
                p2.wait_for_selector("#signin-form", timeout=20000)
            except Exception as exc:
                opened, why = False, str(exc).splitlines()[0]
            check("with the network off it still opens", opened, why)
            if opened:
                check("styled and working, not a page of raw text",
                      p2.evaluate("typeof TAFSYNC") == "object"
                      and p2.evaluate("typeof TAFAPP") == "object")
                check("and its scripts come from the phone, not the cupboard",
                      p2.evaluate("() => fetch('screens.js',"
                                  " {cache: 'no-store'}).then(r => r.ok)"
                                  ".catch(() => false)"))
            check("and the worker did not throw on the way", not crashes,
                  "; ".join(crashes[:3]))
            ctx.set_offline(False)
            ctx.close()
        finally:
            httpd.shutdown()
            httpd.server_close()

        real_errors = [e for e in errors if "favicon" not in e.lower()]
        print("\n── the frame: a sidebar, and a bottom bar on a phone ──")
        check("on a computer every tab is in the sidebar",
              page.eval_on_selector("#tabs", "n => getComputedStyle(n).position")
              == "sticky"
              and page.locator("#tabs button[data-tab]:visible").count()
              == page.locator("#tabs button[data-tab]").count()
              and page.locator("#tab-more").is_hidden())
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(200)
        bar = page.eval_on_selector("#tabs", "n => { const r = n.getBoundingClientRect();"
                                    " return {bottom: Math.round(r.bottom), h: innerHeight,"
                                    " pos: getComputedStyle(n).position}; }")
        check("on a phone the tabs are a bar along the bottom",
              bar["pos"] == "fixed" and bar["bottom"] == bar["h"], str(bar))
        check("four tabs and More, all with words under their icons",
              page.locator("#tabs button:visible").count() == 5
              and page.locator("#tabs button:visible svg").count() == 5
              and page.locator("#tab-more").inner_text().strip() == "More")
        check("the header says which screen this is, and leaves out Sign out",
              page.locator("#app-here").inner_text()
              == page.eval_on_selector('#tabs button[data-tab][aria-selected="true"]',
                                       "b => b.textContent.trim()")
              and page.locator("#signout").is_hidden(),
              page.locator("#app-here").inner_text())
        page.click("#tab-more")
        page.wait_for_selector("#sheet .more-grid")
        more = page.locator("#sheet .more-grid button")
        check("More holds the rest", more.count()
              == page.locator("#tabs button.extra").count(), str(more.count()))
        page.locator('#sheet .more-grid button[data-more="customers"]').click()
        page.wait_for_selector("#sheet", state="hidden")
        check("and opens them", page.locator("#app-here").inner_text() == "Customers"
              and page.locator("#tab-more").get_attribute("aria-selected") == "true")
        page.set_viewport_size({"width": 900, "height": 900})
        page.click('#tabs button[data-tab="stock"]')
        page.wait_for_selector("#screen .stock-card")

        print("\n── reduced motion ──")
        page.emulate_media(reduced_motion="reduce")
        page.click('#tabs button[data-tab="stock"]')
        page.wait_for_selector("#screen .stock-card")
        check("with reduced motion nothing fades in",
              page.locator("#screen .reveal").count() == 0
              and page.eval_on_selector("#screen .stock-card",
                                        "c => getComputedStyle(c).opacity") == "1")
        page.evaluate("document.querySelector('#brand-badge img')"
                      ".classList.remove('spin')")
        page.click("#brand-badge")
        check("and the badge does not spin",
              not page.eval_on_selector("#brand-badge img",
                                        "i => i.classList.contains('spin')"))
        check("nor does the loading screen's",
              page.eval_on_selector("#boot img",
                                    "i => getComputedStyle(i).animationName")
              == "none")
        page.emulate_media(reduced_motion="no-preference")

        check("no script errors anywhere", not real_errors,
              "\n        ".join(real_errors[:4]))
        browser.close()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: " + ", ".join(FAILURES))
        return 1
    print("Web app passed — signed in, listed, ticked and refused.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
