"""
Start the real app, build every tab, and open every dialog.

The unit tests check the rules. Nothing checked the window until this: the
bugs that actually reached a release were a method that was called but never
written, and two cards placed in the same grid cell so one drew on top of the
other. Neither is visible in a diff, and both are obvious the instant the
screen is built.

So this builds it — every tab, every dialog, on a real Tk — against a stand-in
database rather than the live one. It runs on Windows in CI, where there is a
desktop; anywhere without one it says so and stops, rather than failing for a
reason that has nothing to do with the code.

    python tests/smoke_gui.py
"""
from __future__ import annotations

import faulthandler
import inspect
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Two things that only matter when this hangs, which is exactly when there is
# no one at the keyboard to ask.
#
# Windows block-buffers stdout when it is a pipe, so a run that CI kills on a
# timeout produces no output at all — not even the banner — and the log says
# nothing about where it stopped. Line buffering means whatever it reached is
# already on disk when it dies.
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

# And if it is still going after five minutes, print every thread's stack and
# exit non-zero. A step that blocks runs inside the Tk event loop, so the
# harness's own watchdog below cannot fire — this is the only thing that
# still can.
faulthandler.enable()
faulthandler.dump_traceback_later(300, exit=True)

# Each step's own limit (see _drive), and each role's (see run_all).
STEP_LIMIT = 90
ROLE_LIMIT = 240

# Point the app's storage at a throwaway folder before anything reads it:
# APP_DIR is decided at import time and a smoke test must not touch, or
# inherit, a real installation's settings and orders.
_TEMP = tempfile.mkdtemp(prefix="taf-smoke-")
os.environ["APPDATA"] = _TEMP
os.environ["HOME"] = os.environ.get("HOME", _TEMP)

FAILURES: list[tuple[str, str]] = []


def _fail(what: str, exc: BaseException) -> None:
    FAILURES.append((what, "".join(traceback.format_exception(
        type(exc), exc, exc.__traceback__))))


# ── A database that answers without a network ────────────────────────────────

ORDERS = [
    {
        "id": "o1", "order_type": "filter", "customer_name": "Bells Creek",
        "order_number": "PO-8842", "date_ordered": "01/09/2026",
        "date_due": "15/09/2026", "created_at": "2026-09-01T02:00:00Z",
        "user_email": "smoke@taf.local", "full_name": "Smoke Test",
        "created_by_role": "Employee", "archived": False, "n_items": 2,
        "header": {"Customer Name": "Bells Creek", "Order Number": "PO-8842",
                   "Date Ordered": "01/09/2026", "Date Due": "15/09/2026",
                   "Location": "Sunshine Coast", "Job": "AHU 3",
                   "status": "Complete", "priority": True, "printed": False},
        "items": [
            {"item_kind": "filter", "Filter Type": "V-form", "Media Type": "G4",
             "Short": 595, "Long": 595, "Channel": 50, "Quantity": "12",
             "Part Number": "PPF50-1.8-G4"},
            {"item_kind": "filter", "Filter Type": "Flat Panel",
             "Media Type": "F7", "Short": 495, "Long": 495, "Channel": 48,
             "Quantity": "4", "Part Number": "FPF48-0.24-F7"},
        ],
    },
    {
        "id": "o2", "order_type": "filter", "customer_name": "CAS - Tweed",
        "order_number": "TAF-ON-0002", "date_ordered": "02/09/2026",
        "date_due": "ASAP", "created_at": "2026-09-02T02:00:00Z",
        "user_email": "smoke@taf.local", "full_name": "Smoke Test",
        "created_by_role": "Manager", "archived": False, "n_items": 0,
        "header": {"Customer Name": "CAS - Tweed", "Order Number": "TAF-ON-0002",
                   "status": "Dispatched", "Location": "Local"},
        "items": [],
    },
]

# Something still to be made. Without it half the new screens have nothing
# to show and would pass by being empty, which is not passing.
ORDERS.append({
    "id": "o3", "order_type": "filter", "customer_name": "Pelican Waters",
    "order_number": "PO-9100", "date_ordered": "03/09/2026",
    "date_due": "30/09/2026", "created_at": "2026-09-03T02:00:00Z",
    "user_email": "smoke@taf.local", "full_name": "Smoke Test",
    "created_by_role": "Employee", "archived": False, "n_items": 2,
    "header": {"Customer Name": "Pelican Waters", "Order Number": "PO-9100",
               "status": "Pending", "Location": "Sunshine Coast",
               "stages": {"cut": True}},
    "items": [
        {"item_kind": "filter", "Filter Type": "V-form", "Media Type": "G4",
         "Short": 295, "Long": 310, "Channel": 50, "Quantity": "12",
         "Square Metres": 0.3, "Part Number": "PPFG450-030"},
        {"item_kind": "filter", "Filter Type": "Flat Panel",
         "Media Type": "F7", "Short": 495, "Long": 495, "Channel": 48,
         "Quantity": "4", "Square Metres": 0.24,
         "Part Number": "FPF48-0.24-F7"},
    ],
})

CUSTOMERS = [
    {"id": "c1", "name": "Bells Creek", "legal_name": "Bells Creek Pty Ltd",
     "email": "orders@bellscreek.example", "phone": "07 5555 0000",
     "region": "Sunshine Coast", "active": True,
     "delivery_address1": "1 Filter Rd", "delivery_city": "Caloundra",
     "delivery_state": "QLD", "delivery_postcode": "4551"},
    {"id": "c2", "name": "CAS - Tweed", "email": "po@cas.example",
     "region": "Local", "active": True},
]

# Winning the work (step 46).
CHASED: list = []
LOST: list = []
PRICE_CHANGES: list = []

# Planning (step 45).
SAVED_ROSTER: list = []
SAVED_LEAVE: list = []

# The factory floor (step 44).
SAVED_QC: list = []
ADDED_FAULTS: list = []
LINE_QC: list = []

OVERRIDES = {
    "job_rates":           lambda *a, **k: [
        {"filter_type": "V-Form", "timings": 4, "filters": 20,
         "minutes_each": 12.0}],
    "recent_job_times":    lambda *a, **k: [
        {"user_name": "Dave Floor", "order_number": "PO-8842",
         "filter_type": "V-Form", "quantity": 5, "minutes": 61,
         "stopped_at": "x", "started_at": "2026-10-16T01:00:00Z"}],
    "qc_checklists":       lambda *a, **k: {"*": ["Size checked"],
                                            "V-Form": ["Pleats even", "Brace in"]},
    "save_qc_checklist":   lambda t, c: SAVED_QC.append((t, list(c))),
    "remove_qc_checklist": lambda t: SAVED_QC.append((t, [])),
    "set_line_qc":         lambda o, l, qc: LINE_QC.append((o, l, qc)),
    "list_faults":         lambda *a, **k: [
        {"reason": "Wrong size", "filter_type": "V-Form", "made_by": "Dave",
         "found": "qc", "quantity": 2, "created_at": "2026-10-10T00:00:00Z"}],
    "add_fault":           lambda row, photo="": ADDED_FAULTS.append(dict(row))
                                                 or row,
    "orders_with_finished_photo": lambda ids: set(),
    "supplier_prices":     lambda *a, **k: [
        {"bought_at": "2026-06-01T00:00:00Z", "supplier": "FD Greenwood",
         "item_code": "FDG-G4", "stock_item_id": None, "unit_price": 80,
         "quantity": 10, "po_number": "PO-0003"},
        {"bought_at": "2026-09-01T00:00:00Z", "supplier": "FD Greenwood",
         "item_code": "FDG-G4", "stock_item_id": "s1", "unit_price": 88,
         "quantity": 10, "po_number": "PO-0007"},
        {"bought_at": "2026-09-02T00:00:00Z", "supplier": "Vulcan",
         "item_code": "VUL-BF592", "stock_item_id": "s2", "unit_price": 3,
         "quantity": 6, "po_number": "PO-0008"}],
    "supplier_lead_times": lambda *a, **k: [
        {"supplier_id": "s-fdg", "supplier": "FD Greenwood", "orders": 4,
         "avg_days": 5, "median_days": 5, "longest_days": 9},
        {"supplier_id": "s-vul", "supplier": "Vulcan", "orders": 2,
         "avg_days": 12, "median_days": 12, "longest_days": 14}],
    "stock_transactions_since": lambda *a, **k: [
        {"stock_item_id": "s1", "transaction_type": "use",
         "quantity_change": -60,
         "created_at": __import__("datetime").datetime.now().isoformat()}],
    "stock_reserved":      lambda *a, **k: {"s1": {"reserved": 28, "orders": 2}},
    "set_stock_reserved":  lambda *a, **k: 0,
    "staff_roster":        lambda *a, **k: [
        {"person": "Dave Floor", "days": [1, 2, 3, 4, 5], "hours": 1,
         "makes": True, "active": True}],
    "staff_leave":         lambda *a, **k: [
        {"id": "lv1", "person": "Dave Floor", "first_day": "2026-12-24",
         "last_day": "2027-01-05", "kind": "annual", "note": "Christmas"}],
    "shutdown_days":       lambda *a, **k: [],
    "planning_settings":   lambda *a, **k: {"minutes_per_filter": 15,
                                            "making_share": 1},
    "save_roster":         lambda *a, **k: SAVED_ROSTER.append((a, k)),
    "remove_roster":       lambda *a, **k: None,
    "add_leave":           lambda *a, **k: SAVED_LEAVE.append(a) or {},
    "remove_leave":        lambda *a, **k: None,
    "quotes_for_report":   lambda *a, **k: [
        {"id": "q9", "quote_number": "Q-0009", "customer_name": "Bells Creek",
         "status": "sent", "total": 450, "sent_at": "2026-01-02T00:00:00Z",
         "public_token": "tok", "chase_count": 1},
        {"id": "q8", "quote_number": "Q-0008", "customer_name": "Tweed",
         "status": "declined", "total": 300, "responded_at":
         __import__("datetime").date.today().isoformat(), "lost_reason": ""}],
    "quote_chased":        lambda qid: CHASED.append(qid) or 2,
    "set_quote_lost":      lambda qid, reason, note="": LOST.append((qid, reason)),
    "customers_on_service": lambda *a, **k: [
        {"id": "c-svc", "name": "Bells Creek", "short_name": "Bells",
         "service_weeks": 4}],
    "orders_since":        lambda *a, **k: [
        {"customer_name": "Bells", "date_ordered": "01/01/2026"}],
    "snooze_service":      lambda *a, **k: None,
    "set_service_weeks":   lambda *a, **k: None,
    "price_changes":       lambda *a, **k: [
        {"id": "pc1", "percent": 5, "scope": "rates", "match_text": "",
         "starts_on": "2099-01-01", "applied_at": None}],
    "add_price_change":    lambda c: PRICE_CHANGES.append(dict(c)) or "pc2",
    "apply_price_change":  lambda cid: 3,
    "apply_due_price_changes": lambda: 0,
    "cancel_price_change": lambda cid: None,
    "customer_orders":     lambda cust, limit=20: [
        {"id": "o-again", "order_number": "PO-7000", "date_ordered": "01/09/2026",
         "header": {"Job": "AHU 3"},
         "items": [{"Filter Type": "V-Form", "Quantity": 4, "made": True,
                    "line_id": "L9", "Short": 500, "Long": 600, "Channel": 45}]}],
    "is_ready":            lambda *a, **k: True,
    "is_configured":       lambda *a, **k: True,
    "current_user":        lambda *a, **k: {"id": "u1", "email": "smoke@taf.local",
                                            "full_name": "Smoke Test"},
    "current_role":        lambda *a, **k: "Manager",
    "get_all_orders":      lambda *a, **k: [dict(o) for o in ORDERS],
    "get_order_list":      lambda *a, **k: [dict(o, items=None) for o in ORDERS],
    "get_order_items":     lambda oid="", *a, **k: next(
        (list(o["items"]) for o in ORDERS if o["id"] == oid), []),
    "get_customers":       lambda *a, **k: [dict(c) for c in CUSTOMERS],
    "get_customer":        lambda *a, **k: dict(CUSTOMERS[0]),
    "match_customer":      lambda *a, **k: dict(CUSTOMERS[0]),
    "get_known_customers": lambda *a, **k: [c["name"] for c in CUSTOMERS],
    "get_price_list":      lambda *a, **k: {"PPF50-1.8-G4": 48.5,
                                            "FPF48-0.24-F7": 12.0},
    "get_price_rows":      lambda *a, **k: [
        {"part_number": "PPF50-1.8-G4", "name": "V-form G4 595x595x50",
         "unit_price": 48.5, "updated_at": "2026-09-01T00:00:00Z"}],
    "count_prices":        lambda *a, **k: 1,
    "get_price_rate_rows": lambda *a, **k: [
        {"filter_type": "V-form", "media_type": "G4", "rate_per_sqm": 26.0}],
    "get_stock_items":     lambda *a, **k: [
        {"id": "s1", "name": "G4 media roll", "product_type": "media",
         "sku": "TAF-G4-ROLL", "location": "Rack A1", "unit": "m2",
         "stock_on_hand": 40, "minimum_on_hand": 10},
        {"id": "s2", "name": "Bag frame 592", "product_type": "Other",
         "sku": "", "location": "Rack C3", "unit": "each",
         "stock_on_hand": 4, "minimum_on_hand": 10}],
    "get_quotes":          lambda *a, **k: [
        {"id": "q1", "customer_name": "Bells Creek", "status": "sent",
         "total": 1234.5, "created_at": "2026-09-01T00:00:00Z",
         "header": {"Customer Name": "Bells Creek"}, "lines": []}],
    "get_media_codes":     lambda *a, **k: {"G4": "G4", "F7": "F7"},
    "get_catalog_map":     lambda *a, **k: {},
    "get_audit_log":       lambda *a, **k: [
        {"action": "order_created", "detail": "PO-8842",
         "user_email": "smoke@taf.local", "created_at": "2026-09-01T02:00:00Z"}],
    "media_usage_since":   lambda *a, **k: {"G4": 12},
    "list_po_inbox_batches": lambda *a, **k: [],
    "log_action":          lambda *a, **k: None,
    "current_avatar_url":  lambda *a, **k: "",
    "get_order":           lambda oid="", *a, **k: next(
        (dict(o) for o in ORDERS if o["id"] == oid), None),
    "resolve_scan":        lambda code="", *a, **k: [
        {"kind": "stock", "ref": "s1", "label": "G4 media roll",
         "detail": "Rack A1", "extra": {"sku": "TAF-G4-ROLL"}}],
    "adjust_stock":        lambda *a, **k: 12.0,
    "list_offcuts":        lambda *a, **k: [
        {"id": "of1", "length_mm": 1300, "profile": "50mm",
         "created_by": "Smoke Test", "created_at": "2026-09-01T00:00:00Z"}],
    "offcut_lengths":      lambda *a, **k: [1300.0],
    "add_offcut":          lambda *a, **k: {"id": "of2"},
    "use_offcut":          lambda *a, **k: None,
    "frame_preference":    lambda *a, **k: "",
    "set_frame_preference": lambda *a, **k: None,
    "made_sizes":          lambda *a, **k: [
        {"short": 295, "long": 310, "seen": 7}],
    "set_order_stage":     lambda *a, **k: "o3",
    "set_line_sent":       lambda *a, **k: "o3",
    "get_order_items":     lambda oid="", *a, **k: next(
        (list(o["items"]) for o in ORDERS if o["id"] == oid), []),
    "get_cost_list":       lambda *a, **k: {"TAF-G4-ROLL": 8.0},
    "get_stock_transactions": lambda *a, **k: [
        {"quantity_change": -4.0, "notes": "Order PO-8842"}],
    "merge_order_header":  lambda *a, **k: "o3",
    "customer_for_order":  lambda *a, **k: dict(CUSTOMERS[0]),
    "set_line_fields":     lambda oid="", line_id="", fields=None, *a, **k:
        _set_line_fields(oid, line_id, fields or {}),
    "former_customer_names": lambda *a, **k: [],
    "resolve_customer_id": lambda cid="", *a, **k: cid,
    "SUPABASE_URL":        "https://example.supabase.co",
}


def _set_line_fields(order_id, line_id, fields):
    """Changes one line's fields the way db.set_line_fields does, on the
    stand-in orders, so a saved packing plan is there when it is read back."""
    from taf_order_app.db import with_line_ids
    for o in ORDERS:
        if o["id"] != order_id:
            continue
        o["items"] = with_line_ids([dict(i) for i in o["items"]])
        for line in o["items"]:
            if str(line.get("line_id")) == str(line_id):
                for k, v in fields.items():
                    if v is None:
                        line.pop(k, None)
                    else:
                        line[k] = v
                return [dict(i) for i in o["items"]]
    raise RuntimeError("That line was not found on the order.")

# Rights are a real fork in what gets built: a manager sees the stock-alert
# card and live buttons, everyone else sees the same buttons disabled. Those
# are different code paths and both have shipped broken, so the test runs the
# whole thing once as each.
PERMISSIONS = ("can_manage_stock_alerts", "can_manage_prices",
               "can_manage_customers", "can_manage_stock", "can_manage_staff",
               "can_edit_catalog", "can_view_audit_log", "is_approved",
               "is_manager", "is_admin")

# Functions in db.py that work something out rather than fetch it. They touch
# no client, so replacing them with a canned answer tests nothing and hides
# what the screen really does — line_progress stubbed to an empty tuple made
# "3 of 8 made" unpack a pair from nothing.
PURE = ("line_progress", "with_line_ids", "item_signature",
        "progress_cell", "as_date", "add_months", "customer_wants_labels")

ROLES = ("manager", "employee")

# Anything not named above answers from its own return annotation, so a new
# database call doesn't need a new stub before the screen can be built.
BY_ANNOTATION = {"list": list, "dict": dict, "int": int, "float": float,
                 "str": str, "bool": bool, "set": set, "tuple": tuple}


def _default_for(fn):
    try:
        ann = inspect.signature(fn).return_annotation
    except (TypeError, ValueError):
        return None
    text = (ann if isinstance(ann, str) else getattr(ann, "__name__", "")).strip()
    text = text.strip('"\'')
    if "None" in text and "|" in text:      # "dict | None" — None is a real answer
        return None
    base = text.split("[")[0]
    maker = BY_ANNOTATION.get(base)
    return maker() if maker else None


class StubDB:
    """Stands in for taf_order_app.db for the length of the smoke test."""

    def __init__(self, real, manager: bool = True):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_manager", manager)
        object.__setattr__(self, "_cache", {})

    def __getattr__(self, name):
        cache = object.__getattribute__(self, "_cache")
        if name in cache:
            return cache[name]
        if name in OVERRIDES:
            cache[name] = OVERRIDES[name]
            return cache[name]
        if name == "tables_exist":
            cache[name] = lambda *a, **k: (True, True)
            return cache[name]
        if name in PERMISSIONS or name.startswith("can_"):
            allow = object.__getattribute__(self, "_manager")
            cache[name] = lambda *a, _v=allow, **k: _v
            return cache[name]
        value = getattr(object.__getattribute__(self, "_real"), name)
        if name in PURE:
            cache[name] = value            # the real one — it only computes
            return value
        if inspect.isfunction(value) or inspect.isbuiltin(value):
            default = _default_for(value)
            def stub(*a, _d=default, **k):
                return _d() if callable(_d) else _d
            stub.__name__ = name
            cache[name] = stub
            return stub
        return value        # constants, classes, exception types


# Something asked for, something urgent, and something already on order, so
# the Supplies list is drawn with every kind of row rather than as an empty
# table that would pass by being empty.
SUPPLY_REQUESTS = [
    {"id": "r1", "item": "Tape", "detail": "50mm foil", "quantity": "3 rolls",
     "urgent": True, "note": "Out on bench 2", "status": "open",
     "requested_by_name": "Dave Floor", "handled_by_name": "",
     "created_at": "2026-09-24T01:00:00Z"},
    {"id": "r2", "item": "Rivets", "detail": "4mm pop", "quantity": "1 box",
     "urgent": False, "note": "", "status": "open",
     "requested_by_name": "Amy Admin", "handled_by_name": "",
     "created_at": "2026-09-24T00:30:00Z"},
    {"id": "r3", "item": "Channel", "detail": "45mm", "quantity": "20 lengths",
     "urgent": False, "note": "", "status": "ordered",
     "requested_by_name": "Dave Floor", "handled_by_name": "Sarah Boss",
     "created_at": "2026-09-23T03:00:00Z"},
    # Three things in one New order: one ordered already, two waiting.
    {"id": "r4", "batch_id": "b1", "client_ref": "w-1", "item": "Media",
     "detail": "G4 media roll", "quantity": "2 m²", "urgent": False,
     "note": "", "status": "open", "requested_by": "u-dave",
     "requested_by_name": "Dave Floor", "handled_by_name": "",
     "created_at": "2026-09-22T03:00:00Z"},
    {"id": "r5", "batch_id": "b1", "client_ref": "w-2", "item": "Other",
     "detail": "Bag frame 592", "quantity": "6 pieces", "urgent": False,
     "note": "", "status": "ordered", "requested_by": "u-dave",
     "requested_by_name": "Dave Floor", "handled_by_name": "Sarah Boss",
     "created_at": "2026-09-22T03:00:00Z"},
    {"id": "r6", "batch_id": "b1", "client_ref": "w-3", "item": "Other",
     "detail": "Spray paint", "quantity": "2 cans", "urgent": False,
     "note": "", "status": "open", "requested_by": "u-dave",
     "requested_by_name": "Dave Floor", "handled_by_name": "",
     "created_at": "2026-09-22T03:00:00Z"},
]
MOVED: list = []


def _stub_supplies():
    """The supply calls answer from the list above instead of the network."""
    from taf_order_app import supplies
    supplies.list_requests = lambda include_done=False, limit=200: \
        supplies.sort_requests([dict(r) for r in SUPPLY_REQUESTS])
    supplies.unread_count = lambda: 3
    supplies.my_notifications = lambda limit=40: [
        {"id": "n1", "title": "URGENT: Tape - 50mm foil",
         "body": "Dave Floor asked for 3 rolls. Out on bench 2",
         "created_at": "2026-09-24T01:00:00Z", "read_at": None}]
    supplies.request_supply = lambda *a, **k: dict(SUPPLY_REQUESTS[0])
    supplies.set_status = lambda rid, status: MOVED.append((rid, status))
    supplies.mark_read = lambda *a, **k: 0

    # Buying: two suppliers, FD Greenwood's channel in two sizes, and one
    # purchase order on its way.
    from taf_order_app import purchasing
    purchasing.ready = lambda: True
    purchasing.list_suppliers = lambda active_only=True: [dict(r) for r in SUPPLIERS]
    purchasing.list_items = lambda limit=0: [dict(r) for r in XERO_ITEMS]
    purchasing.list_orders = lambda open_only=False: [
        {**r, "lines": [dict(l) for l in r["lines"]]} for r in PURCHASE_ORDERS]
    purchasing.request_supplies = lambda lines, urgent=False, note="", \
        client_ref=None: SENT_SUPPLIES.append(list(lines)) or []
    purchasing.save_order = lambda order: SAVED_POS.append(dict(order)) or \
        {**order, "id": order.get("id") or "po-new"}
    purchasing.receive = lambda po_id, got: RECEIVED.append((po_id, list(got))) \
        or {"status": "part_received"}
    purchasing.save_supplier = lambda *a, **k: None
    purchasing.link_item = lambda *a, **k: None
    purchasing.cancel_order = lambda *a, **k: None
    purchasing.stock_links_ready = lambda: True
    purchasing.list_stock_links = lambda: [dict(r) for r in STOCK_LINKS]
    purchasing.save_stock_link = lambda *a, **k: SAVED_LINKS.append(a) or None
    purchasing.remove_stock_link = lambda *a, **k: None


SUPPLIERS = [
    {"id": "s-fdg", "name": "FD Greenwood", "email": "orders@fdg.example",
     "code_prefix": "FDG", "xero_contact_id": "C-FDG", "active": True},
    {"id": "s-vul", "name": "Vulcan", "email": "", "code_prefix": "",
     "xero_contact_id": "C-VUL", "active": True},
]
XERO_ITEMS = [
    {"code": "FDG-C45-2440", "name": "C channel 45", "purchase_price": 18.50,
     "supplier_id": "s-fdg", "stock_item_id": "st-45"},
    {"code": "FDG-C50-2440", "name": "C channel 50", "purchase_price": 20.90,
     "supplier_id": "s-fdg", "stock_item_id": None},
    {"code": "VUL-FLY-9", "name": "Flyscreen 9mm", "purchase_price": 4.10,
     "supplier_id": "s-vul", "stock_item_id": None},
]
PURCHASE_ORDERS = [
    {"id": "po-1", "po_number": "PO-0007", "supplier": "FD Greenwood",
     "supplier_id": "s-fdg", "status": "sent", "created_at": "2026-10-10T00:00:00Z",
     "emailed_to": "orders@fdg.example",
     "lines": [{"item_code": "FDG-C45-2440", "description": "C channel 45",
                "quantity": 20, "unit_price": 18.5, "received": 5},
               {"item_code": "FDG-C50-2440", "description": "C channel 50",
                "quantity": 10, "unit_price": 20.9, "received": 10}]},
]
# The media roll comes from FD Greenwood; the bag frame, low on stock, from
# Vulcan at an agreed price.
STOCK_LINKS = [
    {"id": "k1", "stock_item_id": "s1", "supplier_id": "s-fdg",
     "supplier_code": "FDG-G4", "unit_price": None, "preferred": True},
    {"id": "k2", "stock_item_id": "s2", "supplier_id": "s-vul",
     "supplier_code": "VUL-BF592", "unit_price": 3.0, "preferred": True},
]
SAVED_LINKS: list = []
SENT_SUPPLIES: list = []
SAVED_POS: list = []
RECEIVED: list = []


def install_stubs(manager: bool = True):
    """Swap in the stand-in database and silence anything that would block."""
    import taf_order_app
    from taf_order_app import db as real_db
    stub = StubDB(real_db, manager=manager)
    sys.modules["taf_order_app.db"] = stub
    taf_order_app.db = stub
    _stub_supplies()

    # A message box or a file chooser opened during a build would wait for a
    # click that is never coming.
    from tkinter import messagebox, filedialog
    for name in ("showinfo", "showwarning", "showerror"):
        setattr(messagebox, name, lambda *a, **k: "ok")
    for name in ("askyesno", "askokcancel", "askretrycancel"):
        setattr(messagebox, name, lambda *a, **k: False)
    messagebox.askquestion = lambda *a, **k: "no"
    for name in ("askopenfilename", "asksaveasfilename", "askdirectory"):
        setattr(filedialog, name, lambda *a, **k: "")
    filedialog.askopenfilenames = lambda *a, **k: ()

    # A dropdown is the same trap, and a worse one because of where it bites.
    # On Windows tk_popup goes through TrackPopupMenu, which does not return
    # until the menu is dismissed — so a menu opened with nobody there hangs
    # the event loop, and hangs it from *inside*, where the harness's own
    # watchdog cannot fire. On X11 it returns straight away, so this only
    # ever showed up on the build machine, as a ten-minute timeout with no
    # output. Building the menu is what these tests are for; displaying one
    # is Tk's business.
    import tkinter as _tk
    _tk.Menu.tk_popup = lambda self, *a, **k: None

    from taf_order_app import updater
    updater.fetch_latest = lambda *a, **k: {"tag_name": "v0.0.0", "assets": []}
    updater.latest_release = lambda *a, **k: ("0.0.0", "", "")
    return stub


# ── The test itself ──────────────────────────────────────────────────────────

def run(role: str = "manager") -> int:
    try:
        import tkinter as tk
    except Exception as exc:                       # a Python built without Tk
        print(f"SKIP: tkinter is not available ({exc})")
        return 0

    install_stubs(manager=(role == "manager"))

    try:
        root = tk.Tk()
    except Exception as exc:                       # no desktop to draw on
        print(f"SKIP: no display available ({exc})")
        return 0

    root.withdraw()
    print(f"Signed in as: {role}")
    import modern_order_gui as gui

    # Tk's own callback errors go to a handler that prints and carries on, so
    # a broken idle task would otherwise scroll past and the test still pass.
    def _tk_error(exc, val, tb):
        _fail("Tk callback", val if isinstance(val, BaseException) else exc(val))
    root.report_callback_exception = _tk_error

    print("Building the window…")
    try:
        app = gui.ModernOrderApp(root)
    except Exception as exc:
        _fail("ModernOrderApp(root)", exc)
        print_failures()
        return 1

    # Everything below runs as scheduled steps with the event loop actually
    # running. The app posts background results back with master.after(), and
    # Tk refuses that from another thread unless it is inside mainloop — so a
    # harness that spun update() by hand would fail for its own reasons.
    steps = _steps(app, gui, root)

    def _drive():
        if not steps:
            root.quit()
            return
        label, step = steps.pop(0)
        # Said before it runs, not after. A step that blocks runs inside the
        # event loop, so nothing else gets to report it — the last line in the
        # log has to be the answer to "which one?".
        if not label.startswith("banner:"):
            print(f"  · {label}", flush=True)
        # Each step gets ninety seconds. One that sticks - inside a modal
        # loop where nothing else here can fire - prints every thread's
        # stack, naming what it was doing, and ends this role's run.
        faulthandler.dump_traceback_later(STEP_LIMIT, exit=True)
        started = time.monotonic()
        try:
            step()
        except Exception as exc:
            _fail(label, exc)
        faulthandler.cancel_dump_traceback_later()
        took = time.monotonic() - started
        if took > 2.0:
            print(f"    ^ took {took:.1f}s")
        root.after(80, _drive)

    root.after(50, _drive)
    root.after(180000, root.quit)          # never hang a CI job
    root.mainloop()

    try:
        root.destroy()
    except Exception:
        pass
    print_failures()
    return 1 if FAILURES else 0


def _steps(app, gui, root):
    def _settle(seconds=0.4):
        """Let debounced work (a search box waits for typing to pause) run."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            root.update()
            time.sleep(0.02)

    """Everything the smoke test does, in order, one event-loop tick apart."""
    import tkinter as tk

    steps: list[tuple[str, object]] = []

    def add(label, fn):
        steps.append((label, fn))

    def _walk(widget):
        """Every widget under one, so a step can read what a dialog says
        without knowing how it was laid out."""
        yield widget
        for kid in widget.winfo_children():
            yield from _walk(kid)

    def _topmost_tab():
        """Which tab a person is actually looking at.

        Every tab is gridded into the same cell, so the visible one is
        whichever is top of the stacking order — not whichever the app has
        recorded as active. winfo_children() is in stacking order, lowest
        first, so the last tab frame in it is the one on screen.
        """
        by_path = {str(f): k for k, f in app._tab_frames.items()}
        stack = [by_path[str(w)] for w in app.content.winfo_children()
                 if str(w) in by_path]
        return stack[-1] if stack else None

    def _sign_in_lands_on_the_dashboard():
        """The tabs are built one at a time in the background after start-up,
        and gridding a frame puts it on top of the one already there. So the
        last tab built covered the Dashboard, and signing in showed Settings.

        This has to run first and drain the builders the way the background
        does. Every step after this one shows tabs by hand, which hides it.
        """
        if _topmost_tab() != "dashboard":
            raise AssertionError(
                f"before any tab is built, the screen already shows "
                f"{_topmost_tab()!r}")
        builders = getattr(app, "_lazy_tab_builders", {})
        while builders:
            app._ensure_tab_built(next(iter(builders)))
            on_screen = _topmost_tab()
            if on_screen != "dashboard":
                raise AssertionError(
                    f"building the tabs in the background left {on_screen!r} "
                    f"on screen; the person chose 'dashboard'")
        if app._active_tab != "dashboard":
            raise AssertionError(
                f"the app thinks it is on {app._active_tab!r}")
    add("sign-in lands on the Dashboard", _sign_in_lands_on_the_dashboard)

    def _switching_tabs_sticks():
        """And a tab chosen by hand must survive the next background build."""
        for key in list(app._tab_frames):
            app._show_tab(key)
            if _topmost_tab() != key:
                raise AssertionError(
                    f"chose {key!r}, screen shows {_topmost_tab()!r}")
    add("every tab shows when chosen", _switching_tabs_sticks)

    add("banner: tabs", lambda: print("Building every tab…"))
    for key in list(getattr(app, "_lazy_tab_builders", {})):
        add(f"build tab: {key}", lambda k=key: app._ensure_tab_built(k))
    for key in ["dashboard"] + list(getattr(app, "_lazy_tab_builders", {})):
        add(f"show tab: {key}", lambda k=key: app._show_tab(k))

    add("banner: refresh", lambda: print("Refreshing every screen…"))
    for name in sorted(n for n in dir(app)
                       if n.startswith("_refresh_") and callable(getattr(app, n))):
        fn = getattr(app, name)
        try:
            takes_args = len(inspect.signature(fn).parameters) > 0
        except (TypeError, ValueError):
            takes_args = True
        if not takes_args:
            add(f"{name}()", fn)

    def _quote_with_lines():
        """The refresh above runs on an empty quote, which returns before the
        totals and the margin. v2.27.0 went out calling a method that did not
        exist in exactly that part, and it only ran for a manager with lines
        on the quote - so put some on."""
        was = list(getattr(app, "quote_items", []) or [])
        app.quote_items = [dict(i) for i in ORDERS[0]["items"]]
        try:
            app._refresh_quote_lines()
            if not app._quote_totals_var.get():
                raise AssertionError("a quote with lines shows no totals")
        finally:
            app.quote_items = was
            app._refresh_quote_lines()
    add("quote with lines on it", _quote_with_lines)

    add("banner: dialogs", lambda: print("Opening every dialog…"))
    for label, make in _dialogs(gui, root):
        add(f"dialog: {label}", _open_and_close(make))

    # Built inline rather than as a class, so it is opened through the button
    # it actually hangs off — with a row selected, which is the path a person
    # takes. Selecting nothing prompts, and the prompt answers "no".
    def _labels_dialog():
        tree = getattr(app, "_stock_tree", None)
        if tree is None:
            raise AssertionError("the Stock tab has no table")
        kids = tree.get_children()
        if kids:
            tree.selection_set(kids[0])
        before = set(root.winfo_children())
        app._print_stock_labels()
        for w in set(root.winfo_children()) - before:
            w.update_idletasks()
            w.destroy()
    add("dialog: Print Barcode Labels", _labels_dialog)

    def _web_link_dialog():
        before = set(root.winfo_children())
        app._web_app_link()
        for w in set(root.winfo_children()) - before:
            w.update_idletasks()
            w.destroy()
    add("dialog: Open on a phone", _web_link_dialog)

    def _product_types_dialog():
        before = set(root.winfo_children())
        app._manage_product_types()
        for w in set(root.winfo_children()) - before:
            w.update_idletasks()
            w.destroy()
    add("dialog: Manage Product Types", _product_types_dialog)

    def _order_view():
        app._show_tab("prev_orders")
        root.update()
        kids = app.orders_tree.get_children()
        if not kids:
            raise AssertionError("no orders to open")
        app.orders_tree.selection_set(kids[0])
        before = set(root.winfo_children())
        app._view_order()
        opened = set(root.winfo_children()) - before
        if not opened:
            raise AssertionError("View Order opened nothing")
        for w in opened:
            w.update_idletasks()
            w.destroy()
    add("dialog: View Order", _order_view)

    def _delivery_labels():
        """Packing saved on the line, then labels made from the saved order -
        the path the office takes - and the PDF actually written."""
        from taf_order_app import order_packing
        opened = []
        was = gui._open_path
        gui._open_path = lambda path: opened.append(path)
        try:
            items = [dict(i) for i in ORDERS[0]["items"]]
            for it in items:
                it["Packing"] = order_packing.set_manual(
                    it, [int(it["Quantity"])])
            path = gui.print_delivery_labels(
                root, {"order_number": "PO-8842", "customer_name":
                       "Bells Creek", "header": dict(ORDERS[0]["header"])},
                items, settings=_calc_settings())
        finally:
            gui._open_path = was
        if not path or not Path(path).exists() or opened != [path]:
            raise AssertionError(f"no label PDF was made ({path})")
    add("delivery labels for an order", _delivery_labels)

    def _add_address_on_the_order_form():
        """Picking a customer whose account has no delivery address asks for
        one - "Add Address for ..." - saves it to the account, and does not
        ask again; a customer with an address is not asked at all."""
        saved = []
        gui._db.update_customer = lambda cid, data: saved.append((cid, data))
        app._address_asked = set()
        was_loc = app.hvars["Location"].get()
        app.hvars["Location"].set("")

        def _dialogs(expect=False):
            """The Add Address windows open now. When one is expected, wait
            up to five seconds for it - a slow build machine is slow - and
            when none is, give a stray one long enough to appear."""
            deadline = time.monotonic() + (5.0 if expect else 0.8)
            while True:
                root.update()
                found = [w for w in root.winfo_children()
                         if isinstance(w, gui.AddAddressDialog)
                         and w.winfo_exists()]
                if (expect and found) or time.monotonic() > deadline:
                    return found
                time.sleep(0.02)
        try:
            app._pick_customer(dict(CUSTOMERS[0]))         # has an address
            if _dialogs():
                raise AssertionError("asked for an address it already has")
            app.hvars["Location"].set("")
            app._pick_customer(dict(CUSTOMERS[1]))         # has none
            found = _dialogs(expect=True)
            if len(found) != 1:
                raise AssertionError(f"expected one Add Address window, "
                                     f"got {len(found)}")
            dlg = found[0]
            if dlg.title() != 'Add Address for "CAS - Tweed"':
                raise AssertionError(f"titled {dlg.title()!r}")
            dlg.vars["delivery_address1"].set("3A/38 Enterprise Avenue")
            dlg.vars["delivery_city"].set("Tweed Heads")
            dlg.vars["delivery_state"].set("NSW")
            dlg.vars["delivery_postcode"].set("248")
            dlg._save()
            if saved or "postcode" not in dlg.err.cget("text"):
                raise AssertionError("a three-digit postcode was saved")
            dlg.vars["delivery_postcode"].set("2486")
            dlg._save()
            if len(saved) != 1 or saved[0][0] != "c2" or \
                    saved[0][1]["delivery_postcode"] != "2486" or \
                    saved[0][1]["billing_city"] != "Tweed Heads":
                raise AssertionError(f"saved {saved}")
            # The Location is the account's region - never the suburb.
            if app.hvars["Location"].get() != "Local":
                raise AssertionError(
                    f"Location {app.hvars['Location'].get()!r}, not Local")
            app._pick_customer(dict(CUSTOMERS[1]))
            if _dialogs():
                raise AssertionError("asked twice for the same customer")
            # Typed out in full rather than picked: asked on leaving the box.
            app._address_asked = set()
            app._customer_records = [dict(c) for c in CUSTOMERS]
            app.hvars["Customer Name"].set("cas - tweed")
            app._customer_left()
            found = _dialogs(expect=True)
            if len(found) != 1:
                raise AssertionError("a typed name was not checked")
            found[0].destroy()
        finally:
            del gui._db.update_customer
            app.hvars["Location"].set(was_loc)
            app.hvars["Customer Name"].set("")
            app._close_ac_popup()
    add("order form: Add Address for a customer without one",
        _add_address_on_the_order_form)

    def _customer_must_be_an_account():
        """The list under Customer Name: Create first, then the accounts
        that match; Enter picks the first; a name that is no account is
        refused at Generate; an account with no Location is asked for one."""
        records = [dict(c) for c in CUSTOMERS] + [
            {"id": "c3", "name": "Access Towing", "region": "Logan",
             "contact_person": "Acme Contact", "email": "ac@tow.example",
             "delivery_address1": "2 Tow St", "delivery_city": "Logan",
             "delivery_state": "QLD", "delivery_postcode": "4114"},
            {"id": "c4", "name": "No Region Co", "region": "Hillcrest, QLD",
             "delivery_address1": "3 Rd", "delivery_city": "Hillcrest",
             "delivery_state": "QLD", "delivery_postcode": "4118"}]
        saved = []
        gui._db.update_customer = lambda cid, data: saved.append((cid, data))
        was_records = app._customer_records
        app._customer_records = records
        app._address_asked = set()
        ent = app._customer_entry
        try:
            app._show_tab("new_order")
            root.update()
            # The list only opens while the box has the focus; a display
            # with no window manager hands focus out unreliably, so say so.
            root.focus_get = lambda: ent
            app.hvars["Customer Name"].set("")
            app.hvars["Location"].set("")
            ent.insert(0, "ac")
            deadline = time.monotonic() + 3
            while not app._ac_popup and time.monotonic() < deadline:
                root.update()
                time.sleep(0.02)
            if not app._ac_popup:
                raise AssertionError("no list under Customer Name")
            # Create row + Access Towing (name) + c3 matched by contact too
            if len(app._ac_rows) != 2:
                raise AssertionError(f"{len(app._ac_rows)} rows listed")
            # Another letter redraws inside the same window: no flash.
            shown = app._ac_popup
            ent.insert("end", "c")
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and \
                    app._ac_key_shown and app._ac_key_shown[0] != "acc":
                root.update()
                time.sleep(0.02)
            if app._ac_popup is not shown or len(app._ac_rows) != 2:
                raise AssertionError("the list window was rebuilt, not "
                                     "reused")
            app._ac_key("Return")              # the first account
            root.update()
            if app.hvars["Customer Name"].get() != "Access Towing" or \
                    app._selected_customer_id != "c3" or \
                    app.hvars["Location"].get() != "Logan":
                raise AssertionError(
                    f"picked {app.hvars['Customer Name'].get()!r} "
                    f"{app._selected_customer_id!r} "
                    f"{app.hvars['Location'].get()!r}")
            if app._ac_popup:
                raise AssertionError("the list stayed open after a pick")
            # Typing over it unlinks; a made-up name is refused.
            app.hvars["Customer Name"].set("Somebody New")
            if app._selected_customer_id:
                raise AssertionError("still linked after typing over it")
            asked = []
            app._ask_to_create = lambda t: asked.append(t)
            app.hvars["Order Number"].set("PO-1")
            app.hvars["Date Ordered"].set("14/10/26")
            if app._validate_header():
                raise AssertionError("a name that is no account passed")
            deadline = time.monotonic() + 2
            while not asked and time.monotonic() < deadline:
                root.update()
                time.sleep(0.02)
            if asked != ["Somebody New"]:
                raise AssertionError(f"not offered to create it: {asked}")
            # Typed out in full, in any case: linked, and passes.
            app.hvars["Customer Name"].set("bells creek")
            if app._selected_customer_id != "c1" or \
                    app.hvars["Location"].get() != "Sunshine Coast":
                raise AssertionError("a typed account name was not linked")
            if not app._validate_header():
                raise AssertionError("an account's name was refused")
            # An account with no Location is asked for one.
            app._pick_customer(dict(records[3]))
            deadline = time.monotonic() + 5
            found = []
            while not found and time.monotonic() < deadline:
                root.update()
                found = [w for w in root.winfo_children()
                         if isinstance(w, gui.AddAddressDialog)
                         and w.winfo_exists()]
                time.sleep(0.02)
            if not found:
                raise AssertionError("not asked for a Location")
            dlg = found[0]
            if dlg.title() != 'Choose Location for "No Region Co"' or \
                    "delivery_address1" in dlg.vars:
                raise AssertionError(f"asked {dlg.title()!r} {list(dlg.vars)}")
            dlg._save()
            if saved:
                raise AssertionError("saved with no Location chosen")
            dlg.vars["region"].set("Ipswich")
            dlg._save()
            if saved != [("c4", {"region": "Ipswich"})] or \
                    app.hvars["Location"].get() != "Ipswich":
                raise AssertionError(f"saved {saved}, Location "
                                     f"{app.hvars['Location'].get()!r}")
        finally:
            del gui._db.update_customer
            root.__dict__.pop("focus_get", None)
            app.__dict__.pop("_ask_to_create", None)
            app._customer_records = was_records
            app._close_ac_popup()
            for k in ("Customer Name", "Order Number", "Date Ordered",
                      "Location"):
                app.hvars[k].set("")
            app._clear_all_field_errors()
    add("order form: the customer is always an account",
        _customer_must_be_an_account)

    def _bad_dates_are_caught_before_printing():
        """A due date the worksheet would refuse is flagged on the form,
        before anything prints; a saved order with one opens the fix window
        and is not printed until it is right."""
        app._customer_records = [dict(c) for c in CUSTOMERS]
        try:
            app.hvars["Customer Name"].set("Bells Creek")
            app.hvars["Order Number"].set("PO-1")
            app.hvars["Date Ordered"].set("14/10/26")
            app.hvars["Location"].set("Local")
            app.hvars["Date Due"].set("31/09/26")
            if app._validate_header():
                raise AssertionError("31/09/26 passed as a due date")
            said = app._validation_banner_lbl.cget("text")
            if '"31/09/26" is not a real date' not in said:
                raise AssertionError(f"banner said {said!r}")
            app.hvars["Date Due"].set("16/10/26")
            if not app._validate_header():
                raise AssertionError("a good date was refused")
        finally:
            for k in ("Customer Name", "Order Number", "Date Ordered",
                      "Location"):
                app.hvars[k].set("")
            app.hvars["Date Due"].set("ASAP")
            app._clear_all_field_errors()

        saved = []
        gui._db.merge_order_header = lambda oid, patch: saved.append(
            (oid, patch))
        row = {"source": "db", "db_id": "o9", "customer": "Bells Creek",
               "order_no": "PO-9", "db_header": {}}
        header = {"Customer Name": "Bells Creek", "Order Number": "PO-9",
                  "Date Ordered": "14/10/26", "Date Due": "31/09/26",
                  "Location": "Local"}
        try:
            def _answer():
                found = [w for w in root.winfo_children()
                         if isinstance(w, gui.FixOrderHeaderDialog)]
                if not found:
                    root.after(50, _answer)
                    return
                dlg = found[0]
                dlg._save()                        # still wrong: stays open
                if not dlg.winfo_exists() or "Still to fix" not in \
                        dlg.err.cget("text"):
                    raise AssertionError("saved a bad date")
                dlg.vars["Date Due"].set("16/10/26")
                dlg._save()
            root.after(50, _answer)
            fixed = app._header_ready_to_print(row, dict(header))
            if not fixed or fixed["Date Due"] != "16/10/26" or \
                    saved != [("o9", {"Date Due": "16/10/26"})]:
                raise AssertionError(f"fixed {fixed}, saved {saved}")
            if app._header_ready_to_print(row, fixed) is not fixed:
                raise AssertionError("a good order was stopped")
        finally:
            del gui._db.merge_order_header
    add("printing: a bad date is fixed before anything prints",
        _bad_dates_are_caught_before_printing)

    def _background_threads_never_touch_the_window():
        """A background thread's .after() and StringVar.set() are run by the
        window's own thread, not from the background one - Tk on Windows can
        crash when touched from another thread."""
        import threading as _th
        ran_on = []
        var = gui.tk.StringVar(master=root)

        def _worker():
            root.after(0, lambda: ran_on.append(_th.current_thread()))
            var.set("from a thread")
        t = _th.Thread(target=_worker)
        t.start()
        t.join(5)
        _settle(0.3)
        if ran_on != [_th.main_thread()] or var.get() != "from a thread":
            raise AssertionError(f"ran on {ran_on}, var {var.get()!r}")
    add("threads: background work is handed to the window's thread",
        _background_threads_never_touch_the_window)

    def _tidied_up_on_the_window_thread():
        """A StringVar tidied away on a background thread (Python's memory
        clean-up runs wherever it runs) is deleted by the window's thread.
        Deleting it from the background one waited on the window's thread
        while that waited on the background one: the Windows build froze
        there, Thread.start() against Variable.__del__."""
        import threading as _th
        var = gui.tk.StringVar(master=root, value="x")
        unset_on = []
        interp = var._tk
        real = interp.globalunsetvar
        name = str(var)

        class _Spy:
            def __getattr__(self, attr):
                return getattr(interp, attr)

            def globalunsetvar(self, *a):
                unset_on.append(_th.current_thread())
                return real(*a)
        var._tk = _Spy()
        t = _th.Thread(target=var.__del__)
        t.start()
        t.join(5)
        if unset_on:
            raise AssertionError("deleted from the background thread")
        _settle(0.3)
        if unset_on != [_th.main_thread()]:
            raise AssertionError(f"deleted on {unset_on}")
        if root.getboolean(root.tk.call("info", "exists", name)):
            raise AssertionError("the Tcl variable is still there")
    add("threads: Tk objects are tidied on the window's thread",
        _tidied_up_on_the_window_thread)

    def _deleting_an_order():
        """Delete from Previous Orders: the order leaves the list at once,
        without the list being emptied and reloaded, and nothing errors."""
        app._show_tab("prev_orders")
        _settle(0.5)
        tree = app.orders_tree
        kids = tree.get_children()
        if not kids:
            raise AssertionError("no orders listed to delete")
        tree.selection_set(kids[0])
        target = app._get_selected_order()
        deleted = []
        gui._db.delete_order = lambda oid: deleted.append(oid)
        gui._db.can_delete_order = lambda row: True
        was_ask = gui.messagebox.askyesno
        gui.messagebox.askyesno = lambda *a, **k: True
        before = len(app._all_orders_data)
        try:
            app._delete_prev_order()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and \
                    len(app._all_orders_data) == before:
                root.update()
                time.sleep(0.02)
        finally:
            gui.messagebox.askyesno = was_ask
            del gui._db.delete_order
            del gui._db.can_delete_order
        if deleted != [target.get("db_id")]:
            raise AssertionError(f"deleted {deleted}")
        if len(app._all_orders_data) != before - 1 or any(
                r is target for r in app._all_orders_data):
            raise AssertionError("the order is still in the list")
        app._refresh_orders_list()          # put the stand-in orders back
        _settle(0.5)
    add("previous orders: deleting an order", _deleting_an_order)

    def _customer_name_onto_orders():
        """Customers > Customer > Put this name on their past orders: asks,
        runs step 36's function for that account, and Previous Orders is
        shown fresh."""
        calls = []
        was = gui._merge.sync_order_names
        gui._merge.sync_order_names = lambda cid: calls.append(cid) or 4
        was_ask = gui.messagebox.askyesno
        gui.messagebox.askyesno = lambda *a, **k: True
        refreshed = []
        app._refresh_orders_list = lambda: refreshed.append(1)
        try:
            app._sync_customer_order_names(dict(CUSTOMERS[0]), ask=True)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not refreshed:
                root.update()
                time.sleep(0.02)
            said = app.status_var.get()
        finally:
            gui._merge.sync_order_names = was
            gui.messagebox.askyesno = was_ask
            del app._refresh_orders_list       # the real one again
            app._refresh_orders_list()         # and the stand-in orders back
            _settle(0.6)
            app._tab_loaded["prev_orders"] = time.monotonic()
        if calls != ["c1"] or not refreshed:
            raise AssertionError(f"synced {calls}, refreshed {refreshed}")
        if "4 more past orders" not in said:
            raise AssertionError(said)
    add("customers: their new name onto past orders",
        _customer_name_onto_orders)

    def _bag_header_in_the_dialog():
        """Header on a bag: follows the bag (bag - 15) until edited, then
        keeps its own size; a Custom Bag Filter starts at the size ordered
        and asks for its pockets."""
        dlg = gui.BagLineItemDialog(root, title="Bag")
        try:
            root.update()
            dlg.var_pt.set("3-Peak")
            dlg._on_type_change()
            dlg.var_w.set("610"); dlg.var_h.set("610"); dlg.var_d.set("570")
            dlg.var_bhdr.set(True); dlg.var_wire.set(True)
            dlg._option_changed()
            root.update()
            if not dlg.hdr_frame.winfo_ismapped():
                raise AssertionError("no Header section with Header ticked")
            if (dlg.var_hw.get(), dlg.var_hh.get(), dlg.var_hd.get()) != \
                    ("595", "595", "25"):
                raise AssertionError("header did not follow the bag: "
                                     f"{dlg.var_hw.get()}x{dlg.var_hh.get()}")
            if not dlg.wire_frame.winfo_ismapped() or \
                    (dlg.var_ww.get(), dlg.var_wh.get()) != ("580", "580"):
                raise AssertionError("no wire section, or not header - 15: "
                                     f"{dlg.var_ww.get()}x{dlg.var_wh.get()}")
            dlg.var_hw.set("597")              # nudged by hand
            if dlg.var_ww.get() != "582":
                raise AssertionError("the wire did not follow the header")
            dlg.var_w.set("612")               # the bag changes afterwards
            if dlg.var_hw.get() != "597" or dlg.var_hh.get() != "595":
                raise AssertionError("a hand-set header was overwritten")
            dlg.var_wh.set("578")              # the wire nudged by hand
            dlg.var_hh.set("596")
            if dlg.var_wh.get() != "578":
                raise AssertionError("a hand-set wire was overwritten")
            dlg.var_qty.set("4")
            dlg._save()
            res = dlg.result
            if not res or (res["header_width"], res["header_height"],
                           res["width"], res["header_custom"],
                           res["wire_width"], res["wire_height"],
                           res["wire_custom"]) != \
                    (597, 596, 612, True, 582, 578, True):
                raise AssertionError(f"saved {res}")
        finally:
            if dlg.winfo_exists():
                dlg.destroy()
        dlg = gui.BagLineItemDialog(root, title="Bag")
        try:
            dlg.var_pt.set("Custom Bag Filter")
            dlg._on_type_change()
            root.update()
            if dlg.var_bhdr.get() or \
                    not dlg._dim_labels["Pockets"].winfo_ismapped():
                raise AssertionError("custom bag: header ticked by default, "
                                     "or no pockets")
            dlg.var_w.set("855"); dlg.var_h.set("570"); dlg.var_d.set("480")
            dlg.var_wire.set(True); dlg.var_bhdr.set(True)
            dlg._option_changed()
            if (dlg.var_hw.get(), dlg.var_hh.get()) != ("855", "570"):
                raise AssertionError("custom header is not the size ordered")
            dlg.var_hd.set("20")
            dlg.var_qty.set("2")
            was = gui.messagebox.showerror
            said = []
            gui.messagebox.showerror = lambda *a, **k: said.append(a)
            try:
                dlg._save()                    # no pockets yet
            finally:
                gui.messagebox.showerror = was
            if dlg.result or not said:
                raise AssertionError("saved without pockets")
            dlg.var_pockets.set("5")
            dlg._save()
            res = dlg.result
            if not res or res["pockets"] != 5 or \
                    (res["header_width"], res["header_height"],
                     res["header_depth"]) != (855, 570, 20):
                raise AssertionError(f"saved {res}")
        finally:
            if dlg.winfo_exists():
                dlg.destroy()
    add("bag dialog: header sizes and Custom Bag Filter",
        _bag_header_in_the_dialog)

    def _closed_before_its_list_arrives():
        """A list window worked out on another thread, closed before the
        answer comes back. On a slow Windows build machine this happened by
        itself, and filling the vanished list was a Tk error."""
        import threading as _th
        go = _th.Event()

        def _slow_build():
            go.wait(5)
            return ([(("a", "b"), None, None)], "done")
        before = len(FAILURES)
        app._table_window("Closed early", "", [("a", "A", 80, "w"),
                                               ("b", "B", 80, "w")],
                          _slow_build)
        root.update()
        for w in root.winfo_children():
            if isinstance(w, gui.tk.Toplevel) and w.title() == "Closed early":
                w.destroy()
        go.set()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)
        if len(FAILURES) != before:
            raise AssertionError("filling a closed window raised")
    add("list window closed before its list arrives",
        _closed_before_its_list_arrives)

    def _c_channel_table():
        """Every depth listed, searched, filtered, a custom stack added,
        copied and exported - and every weight says kg."""
        dlg = gui.CChannelTableDialog(root)
        try:
            root.update()
            if len(dlg.rows) != 49:
                raise AssertionError(f"{len(dlg.rows)} depths, not 49")
            row45 = [r for r in dlg.rows if r[0] == "45 mm"][0]
            if row45[1] != "23 x 44 x 23 x 2440 mm" or \
                    list(row45[4:8]) != ["1.0 kg", "1.9 kg", "4.8 kg",
                                         "9.5 kg"]:
                raise AssertionError(f"45mm row is {row45}")
            dlg.search.set("4")
            root.update()
            if [r[0] for r in dlg.rows] != ["40 mm", "45 mm"]:
                raise AssertionError(f"search gave {[r[0] for r in dlg.rows]}")
            dlg.search.set("")
            dlg.status.set("Estimated")
            dlg.custom.set("7")
            root.update()
            if len(dlg.rows) != 30 or not all(
                    r[2] == "Estimated" and r[8].endswith(" kg")
                    for r in dlg.rows):
                raise AssertionError("the estimated filter or the custom "
                                     "stack is wrong")
            dlg._copy()
            copied = root.clipboard_get()
            if "Stack of 7" not in copied or "150 mm" not in copied:
                raise AssertionError("copy left things out")
            out = Path(tempfile.mkdtemp()) / "cc.csv"
            was = gui.filedialog.asksaveasfilename
            gui.filedialog.asksaveasfilename = lambda **k: str(out)
            try:
                dlg._export()
            finally:
                gui.filedialog.asksaveasfilename = was
            text = out.read_text(encoding="utf-8-sig")
            if text.count("\n") != 31 or "kg" not in text:
                raise AssertionError("the CSV export is not the table")
        finally:
            dlg.destroy()
    add("C-channel weight table", _c_channel_table)

    def _dropdown_rules():
        """A pick from a dropdown does not also click what is behind it; a
        pill button acts once, on release; the mouse wheel leaves a
        dropdown's value alone."""
        import tkinter as tk
        from tkinter import ttk
        top = tk.Toplevel(root)
        try:
            opened = []
            tree = ttk.Treeview(top)
            tree.pack()
            tree.bind("<Double-1>", lambda _e: opened.append("row"))
            combo = ttk.Combobox(top, values=["A", "B", "C"], state="readonly")
            combo.pack()
            combo.set("B")
            top.update()
            def _double():
                for _ in range(2):
                    tree.event_generate("<ButtonPress-1>", x=5, y=5)
                    tree.event_generate("<ButtonRelease-1>", x=5, y=5)
                top.update()
            combo.event_generate("<<ComboboxSelected>>")
            _double()
            if opened:
                raise AssertionError("a pick also opened the row behind it")
            time.sleep(gui.CLICK_GUARD_SECONDS + 0.05)
            _double()
            if not opened:
                raise AssertionError("an ordinary double-click was blocked")
            for seq, extra in (("<MouseWheel>", {"delta": -120}),
                               ("<Button-4>", {}), ("<Button-5>", {})):
                try:
                    combo.event_generate(seq, x=3, y=3, **extra)
                except tk.TclError:
                    pass
            top.update()
            if combo.get() != "B":
                raise AssertionError("the mouse wheel changed a dropdown")
            fired = []
            btn = gui.flat_btn(top, "Go", lambda: fired.append(1))
            btn.pack()
            top.update()
            btn.event_generate("<ButtonPress-1>", x=3, y=3)
            if fired:
                raise AssertionError("a pill acted on the press")
            btn.event_generate("<ButtonRelease-1>", x=3, y=3)
            btn.event_generate("<ButtonPress-1>", x=3, y=3)
            btn.event_generate("<ButtonRelease-1>", x=3, y=3)
            if fired != [1]:
                raise AssertionError(f"a double click acted {len(fired)} times")
            btn.event_generate("<ButtonRelease-1>", x=3, y=3)
            if fired != [1]:
                raise AssertionError("a release with no press acted")
        finally:
            top.destroy()
    add("dropdowns: no click-through, one action per click",
        _dropdown_rules)

    def _pallet_labels():
        """Pick an order, say two pallets, spread the lines, print: two
        sheets, every line on a pallet."""
        items = [dict(i) for i in ORDERS[0]["items"]]
        opened = []
        was = gui._open_path
        gui._open_path = lambda path: opened.append(path)
        dlg = gui.PalletLabelsDialog(root, {"order_number": "PO-8842",
                                            "header": dict(ORDERS[0]["header"])},
                                     items, dict(CUSTOMERS[0]))
        try:
            root.update()
            dlg.count.set("2")
            root.update()
            dlg._rebuild()
            dlg._spread()
            root.update()
            if len(dlg.cells) != len(items) or \
                    any(len(r) != 2 for r in dlg.cells):
                raise AssertionError("the grid is not lines x 2 pallets")
            totals = [sum(int(v.get() or 0) for v in r) for r in dlg.cells]
            want = [gui._pallets.ordered(i) for i in items]
            if totals != want:
                raise AssertionError(f"spread gave {totals}, not {want}")
            dlg._print()
            if len(opened) != 1 or not Path(opened[0]).exists():
                raise AssertionError("no pallet label PDF was made")
        finally:
            gui._open_path = was
            dlg.destroy()
    add("pallet labels for an order", _pallet_labels)

    def _pallet_labels_two_orders():
        """A second order added to the same pallets: its lines join the
        grid under its own order number, one PDF covers both, and an order
        for somewhere else is refused."""
        items = [dict(i) for i in ORDERS[0]["items"]]
        other = [dict(i) for i in ORDERS[0]["items"]][:1]
        opened = []
        was = gui._open_path
        gui._open_path = lambda path: opened.append(path)
        second = {"order": {"order_number": "PO-9001",
                            "header": {"Job": "J-77"}},
                  "items": other, "customer": dict(CUSTOMERS[0])}
        elsewhere = {"order": {"order_number": "PO-9002", "header": {}},
                     "items": other,
                     "customer": dict(CUSTOMERS[0],
                                      delivery_address1="9 Other St")}
        queue = [second, second, elsewhere]
        was_info, was_warn = gui.messagebox.showinfo, gui.messagebox.showwarning
        said = []
        gui.messagebox.showinfo = lambda *a, **k: said.append(a)
        gui.messagebox.showwarning = lambda *a, **k: said.append(a)
        dlg = gui.PalletLabelsDialog(
            root, {"order_number": "PO-8842",
                   "header": dict(ORDERS[0]["header"])},
            items, dict(CUSTOMERS[0]),
            add_order=lambda parent: dict(queue.pop(0)))
        try:
            root.update()
            dlg._add()
            root.update()
            if len(dlg.entries) != 2 or len(dlg.cells) != len(items) + 1:
                raise AssertionError("the second order's lines were not "
                                     "added")
            if [r[0].get() for r in dlg.cells][-1] != \
                    str(gui._pallets.ordered(other[0])):
                raise AssertionError("the added order did not start on "
                                     "pallet 1")
            dlg._add()                         # the same order again
            dlg._add()                         # somewhere else
            if len(dlg.entries) != 2 or len(said) != 2:
                raise AssertionError(f"a duplicate or another address was "
                                     f"let in: {said}")
            dlg._print()
            if len(opened) != 1 or "PO-8842_PO-9001" not in opened[0]:
                raise AssertionError(f"no shared PDF: {opened}")
            dlg._remove(1)
            if len(dlg.entries) != 1 or len(dlg.cells) != len(items):
                raise AssertionError("removing the order left its lines")
        finally:
            gui._open_path = was
            gui.messagebox.showinfo, gui.messagebox.showwarning = \
                was_info, was_warn
            dlg.destroy()
    add("pallet labels: several orders on the same pallets",
        _pallet_labels_two_orders)

    def _preset_with_bags():
        """A dedicated filter preset with bag filters: the bags come out as
        bag lines, times the sets, halved for a replacement order."""
        pack = {"frames": [{"qty": 1, "short": 455, "long": 510}],
                "filters": [{"qty": 2, "short": 440, "long": 495,
                             "channel": 95}],
                "bags": [{"product_type": "Bag Filter", "media": "F7",
                          "width": 592, "height": 592, "depth": 600,
                          "quantity": 4, "part_number": "BAG-TEST"}]}
        gui.DEDICATED_FILTER_PACKS["SMOKE-BAGS"] = pack
        try:
            ed = gui._GDModelEditor(root, name="SMOKE-BAGS", pack=pack)
            root.update()
            if len(ed._bags_tree.get_children()) != 1:
                raise AssertionError("the preset's bag is not listed")
            ed.destroy()
            for kind, sets, want in (("housing", 3, 12), ("rep", 3, 6)):
                dlg = gui.CompressorFilterDialog(root)
                root.update()
                dlg._gd_model.set("SMOKE-BAGS")
                dlg._gd_order_type.set(kind)
                dlg._gd_qty.set(str(sets))
                dlg._confirm_gd()
                bags = [i for i in dlg.result["items"]
                        if i.get("item_kind") == "bag"]
                if len(bags) != 1 or bags[0]["quantity"] != want or \
                        bags[0]["part_number"] != "BAG-TEST":
                    raise AssertionError(f"{kind}: {bags}")
                if pack["bags"][0]["quantity"] != 4:
                    raise AssertionError("the preset itself was changed")
        finally:
            gui.DEDICATED_FILTER_PACKS.pop("SMOKE-BAGS", None)
    add("dedicated presets with bag filters", _preset_with_bags)

    def _customer_label_switch():
        """The Customer menu turns a customer's labels off and on."""
        saved = []
        gui._db.customers_have_label_switch = lambda: True
        gui._db.set_customer_labels = lambda cid, on: saved.append((cid, on))
        cust = dict(CUSTOMERS[0])
        was = app._get_selected_customer
        app._get_selected_customer = lambda: cust
        try:
            app._toggle_customer_labels()
            app._toggle_customer_labels()
            if saved != [("c1", False), ("c1", True)]:
                raise AssertionError(f"saved {saved}")
        finally:
            app._get_selected_customer = was
            del gui._db.customers_have_label_switch
            del gui._db.set_customer_labels
    add("customers: delivery labels off and on", _customer_label_switch)

    def _generate_case(name, expect_labels, patch=None):
        """Generate Output with the printer stood in for. With labels on,
        the worksheet prints and then the labels; switched off - for
        everyone, or for this customer - the worksheet alone."""
        generated: dict = {}

        def _start():
            from taf_order_app import order_packing
            sheet = Path(tempfile.mkdtemp()) / "sheet.pdf"
            sheet.write_bytes(b"%PDF-1.4\n%%EOF\n")
            items = [dict(i) for i in ORDERS[0]["items"]]
            for it in items:
                it["Packing"] = order_packing.set_manual(
                    it, [int(it["Quantity"])])
            printed = generated.setdefault("printed", [])
            stubs = {
                "_validate_header": lambda: True,
                "_collect_header": lambda: dict(ORDERS[0]["header"]),
                "_print_file": lambda path: printed.append(path) or "",
                "_flag_printed": lambda **k: generated.update(flagged=True),
                "_deduct_stock_for_order": lambda *a: "",
                "_email_order_received": lambda *a: "",
                "_clear_draft": lambda: None,
            }
            # A finished order makes the lists reload; later steps want them
            # as they were.
            generated["state"] = (list(getattr(app, "_all_orders_data", [])
                                       or []),
                                  dict(app._tab_loaded), list(app.items))
            app.items = items
            generated["was"] = {k: getattr(app, k) for k in stubs}
            for k, v in stubs.items():
                setattr(app, k, v)
            generated["svc"] = (app.service.create_order,
                                app.service.save_order_json)
            app.service.create_order = lambda *a, **k: {
                "output_path": str(sheet)}
            app.service.save_order_json = lambda *a, **k: str(sheet) + ".json"
            generated["sheet"] = str(sheet)
            generated["undo"] = patch() if patch else None
            app._generate(on_done=lambda ok: generated.update(done=ok),
                          quiet=True)

        def _finished():
            deadline = time.monotonic() + 60
            # Finished means the print thread has flagged the order printed
            # - the last thing it does - so nothing of it is still running
            # when the stand-ins are put back.
            while time.monotonic() < deadline and not (
                    "done" in generated and generated.get("flagged")):
                root.update()
                time.sleep(0.05)
            if generated.get("undo"):
                generated["undo"]()
            for k, v in generated.get("was", {}).items():
                setattr(app, k, v)
            if "svc" in generated:
                app.service.create_order, app.service.save_order_json = \
                    generated["svc"]
            if "state" in generated:
                orders, loaded, items = generated["state"]
                app._all_orders_data = orders
                app._tab_loaded.clear()
                app._tab_loaded.update(loaded)
                app.items = items
            printed = generated.get("printed", [])
            if not generated.get("done"):
                raise AssertionError(f"the order did not finish ({generated})")
            if not printed or printed[0] != generated["sheet"]:
                raise AssertionError(f"the worksheet did not print: {printed}")
            if expect_labels:
                if len(printed) != 2 or \
                        "delivery_labels_" not in Path(printed[1]).name or \
                        not Path(printed[1]).exists():
                    raise AssertionError(f"expected the worksheet then the "
                                         f"labels to print, got {printed}")
            elif len(printed) != 1:
                raise AssertionError(f"labels printed although switched "
                                     f"off: {printed}")
        add(f"generate output ({name}): start", _start)
        add(f"generate output ({name}): what printed", _finished)

    _generate_case("labels on", True)

    def _everyone_off():
        from taf_order_app import calc_settings as cs
        was = cs.load

        def _off(force=False):
            out = was(force)
            out["delivery_labels"] = {"enabled": False}
            return out
        cs.load = _off
        return lambda: setattr(cs, "load", was)
    _generate_case("labels off for everyone", False, _everyone_off)

    def _customer_off():
        gui._db.customer_for_order = lambda *a, **k: dict(
            CUSTOMERS[0], delivery_labels=False)
        return lambda: delattr(gui._db, "customer_for_order")
    _generate_case("labels off for this customer", False, _customer_off)

    def _account():
        # A menu, so nothing new is packed — this checks it builds at all.
        app._account_menu()
    add("menu: account", _account)

    def _feature_switches():
        """Off means gone, on means there. A feature switch that leaves its
        menu item behind is not a switch."""
        from taf_order_app import features as _feat
        _feat._switches = {}
        app._show_tab("settings")
        root.update()
        if "channel_calculator" not in getattr(app, "_feature_vars", {}):
            raise AssertionError("the features list was not built")
        if app._feature_vars["channel_calculator"].get():
            raise AssertionError("a feature is ticked before anyone turned "
                                 "it on")
        for key, var in app._feature_vars.items():
            if var.get():
                raise AssertionError(f"{key} is on by default")
        # Everything in the catalogue is built now, so every switch is one
        # somebody can actually flip. A locked one would mean a screen that
        # is listed and does not exist.
        for f in _feat.CATALOGUE:
            box = app._feature_boxes[f.key]
            if not f.built and str(box.cget("state")) != "disabled":
                raise AssertionError(f"{f.key} is not built and not locked")
    add("settings: features start off", _feature_switches)

    def _calculator():
        from taf_order_app import features as _feat
        _feat._switches = {"channel_calculator": True}
        before = set(root.winfo_children())
        app._filter_calculator()
        opened = set(root.winfo_children()) - before
        if not opened:
            raise AssertionError("the calculator opened nothing")
        dlg = list(opened)[0]
        entries = [w for w in _walk(dlg) if isinstance(w, tk.Entry)]
        if len(entries) < 3:
            raise AssertionError("the calculator has no boxes to type in")
        entries[0].insert(0, "295")
        entries[1].insert(0, "310")
        # Press it the way a person does. The pills are Canvas-drawn, so
        # there is no invoke() — the command is what the click runs.
        pressed = [w for w in _walk(dlg)
                   if isinstance(w, gui.PillButton)
                   and "Work it out" in str(getattr(w, "_text", ""))]
        if not pressed:
            raise AssertionError("there is no button to work it out with")
        pressed[0]._cmd()
        dlg.update_idletasks()
        said = " ".join(str(w.cget("text")) for w in _walk(dlg)
                        if isinstance(w, tk.Label))
        # Whichever way it decided, those are the marks that have to be on
        # the screen — and for a 295 x 310 they are the worksheet's own, so a
        # wrong answer is caught here rather than at the saw.
        from taf_order_app import cutting as _cut
        from taf_order_app import features as _f2
        won = _cut.best(295, 310, 1, _f2.workshop())["best"]
        for mark in won["frame_sticks"][0]["marks"]:
            if str(mark) not in said:
                raise AssertionError(f"{mark} is missing: {said[-400:]}")
        for w in opened:
            w.destroy()
        _feat._switches = {}
    add("dialog: filter calculator", _calculator)

    def _testable_menu():
        """The one place everything new lives. It must build whether the
        features are on or off, and say which are which."""
        from taf_order_app import features as _feat
        _feat._switches = {}
        items = app._testable_features()
        if not items:
            raise AssertionError("Testable Features is empty")
        named = [i for i in items if i]
        if not any("(off)" in i[0] for i in named):
            raise AssertionError("a feature that is off does not say so")
        if any(i[2] for i in named[:-1]):
            raise AssertionError("something is enabled with every switch off")
        _feat._switches = {"channel_calculator": True}
        items = [i for i in app._testable_features() if i]
        calc = [i for i in items if "Filter calculator" in i[0]][0]
        if not calc[2] or "(off)" in calc[0]:
            raise AssertionError("switched on and still greyed out")
        app._account_menu()          # it has to build with a submenu in it
        _feat._switches = {}
    add("menu: Testable Features", _testable_menu)

    def _offcut_rack():
        from taf_order_app import features as _feat
        _feat._switches = {"offcut_register": True}
        before = set(root.winfo_children())
        app._offcut_rack()
        opened = set(root.winfo_children()) - before
        if not opened:
            raise AssertionError("the offcut rack opened nothing")
        for w in opened:
            w.update_idletasks()
            w.destroy()
        _feat._switches = {}
    add("dialog: the offcut rack", _offcut_rack)

    def _frame_prefs():
        from taf_order_app import features as _feat
        _feat._switches = {"frame_preference": True}
        before = set(root.winfo_children())
        app._frame_preferences()
        opened = set(root.winfo_children()) - before
        if not opened:
            raise AssertionError("frame preferences opened nothing")
        for w in opened:
            w.update_idletasks()
            w.destroy()
        _feat._switches = {}
    add("dialog: frame preferences", _frame_prefs)

    def _floor_windows():
        """The factory floor's desktop screens: the TV link, how long things
        take, the QC checklists, QC before a line is made, and faults."""
        from taf_order_app import features as _feat
        _feat._switches = {k: True for k in ("tv_board", "job_timer",
                                             "qc_checklist", "fault_log")}
        try:
            dlg = app._tv_board()
            assert dlg.tv_url.endswith("/app/?board=tv"), dlg.tv_url
            dlg.destroy()

            dlg, tree, _foot = app._job_rates_window()
            for _ in range(60):
                root.update()
                if tree.get_children():
                    break
                time.sleep(0.05)
            rows = [tree.item(i, "values") for i in tree.get_children()]
            assert any("V-Form" in r[0] and r[1] == "12 min" for r in rows), rows
            assert any(r[1] == "1 h 01 min" for r in rows), rows
            dlg.destroy()

            dlg = app._qc_checklists()
            for _ in range(60):
                root.update()
                if dlg.qc_types.size():
                    break
                time.sleep(0.05)
            assert dlg.qc_types.get(0).startswith("Every type"), dlg.qc_types.get(0)
            assert dlg.qc_text.get("1.0", "end").strip() == "Size checked"
            if gui._db.can_handle_supplies():
                dlg.qc_text.delete("1.0", "end")
                dlg.qc_text.insert("1.0", "- Size checked\nLabel on\n")
                SAVED_QC.clear()
                dlg.qc_save()
                assert SAVED_QC == [("*", ["Size checked", "Label on"])], SAVED_QC
            else:
                # Read, not written, below a manager.
                assert str(dlg.qc_text.cget("state")) == "disabled"
            dlg.destroy()

            # QC before a line is made: every check ticked, or not made.
            app._qc_lists = None

            def _tick_all():
                d = getattr(app, "_qc_dialog", None)
                if d is None or not d.winfo_exists():
                    root.after(50, _tick_all)
                    return
                d.qc_pass()                 # not all ticked: refused
                assert d.winfo_exists()
                for v in d.qc_ticks:
                    v.set(True)
                d.qc_pass()
            app._qc_dialog = None
            root.after(100, _tick_all)
            got = app._qc_before_made({"Filter Type": "V-Form"}, root)
            assert got and got["passed"] and got["checks"] == \
                ["Pleats even", "Brace in"], got
            _feat._switches["qc_checklist"] = False
            assert app._qc_before_made({"Filter Type": "V-Form"}, root) == {}
            _feat._switches["qc_checklist"] = True

            dlg, tree, _foot = app._fault_log()
            for _ in range(60):
                root.update()
                if tree.get_children():
                    break
                time.sleep(0.05)
            rows = [tree.item(i, "values") for i in tree.get_children()]
            assert ("    Wrong size", "2") in [tuple(r) for r in rows], rows
            f = app._record_fault(dlg, {"order_number": "PO-8842",
                                        "filter_type": "V-Form", "found": "qc"})
            f.fault_vars["reason"].set("Media damaged")
            f.fault_vars["made_by"].set("Dave")
            ADDED_FAULTS.clear()
            f.fault_save()
            assert ADDED_FAULTS and ADDED_FAULTS[0]["reason"] == "Media damaged" \
                and ADDED_FAULTS[0]["found"] == "qc" \
                and ADDED_FAULTS[0]["made_by"] == "Dave", ADDED_FAULTS
            dlg.destroy()
        finally:
            _feat._switches = {}
    add("dialogs: the factory floor", _floor_windows)

    def _planning_windows():
        """The roster window, the full-day warning, and Order again."""
        from taf_order_app import features as _feat
        _feat._switches = {k: True for k in ("roster", "capacity_check",
                                             "order_again")}
        try:
            dlg = app._roster_window()
            ahead, roster_t, leave_t = dlg.roster_trees
            for _ in range(80):
                root.update()
                if ahead.get_children():
                    break
                time.sleep(0.05)
            assert len(ahead.get_children()) == 10, len(ahead.get_children())
            assert roster_t.item(roster_t.get_children()[0], "values")[:3] == \
                ("Dave Floor", "Mon-Fri", "1"), roster_t.item(roster_t.get_children()[0], "values")
            assert leave_t.get_children()
            if gui._db.can_handle_supplies():
                p = dlg.add_person()
                name, days, hrs, makes, active = p.person_vars
                name.set("  Amy   Admin ")
                days.set("mon wed fri")
                hrs.set("6")
                SAVED_ROSTER.clear()
                p.person_save()
                assert SAVED_ROSTER and SAVED_ROSTER[0][0][:3] == \
                    ("Amy Admin", [1, 3, 5], 6.0), SAVED_ROSTER
                lv = dlg.add_leave()
                who, first, last, kind, note = lv.leave_vars
                who.set("Dave Floor")
                first.set("20/10/2026")
                last.set("19/10/2026")        # before the first: refused
                SAVED_LEAVE.clear()
                lv.leave_save()
                assert not SAVED_LEAVE and lv.winfo_exists()
                last.set("21/10/2026")
                lv.leave_save()
                assert SAVED_LEAVE and SAVED_LEAVE[0][0] == "Dave Floor", SAVED_LEAVE
            dlg.destroy()

            import datetime as _d
            day = _d.date.today()
            while day.isoweekday() > 5:
                day += _d.timedelta(days=1)
            warn = app._capacity_warning(day.strftime("%d/%m/%Y"),
                                         [{"Filter Type": "V-Form", "Quantity": 40}])
            assert "is already full" in warn, warn
            assert app._capacity_warning("ASAP", [{"Quantity": 40}]) == ""

            dlg, tree, _foot = app._order_again(
                {"name": "Bells Creek", "short_name": "Bells"})
            for _ in range(60):
                root.update()
                if tree.get_children():
                    break
                time.sleep(0.05)
            iid = tree.get_children()[0]
            app._order_again_pick({"name": "Bells Creek", "short_name": "Bells"},
                                  iid, dlg)
            root.update()
            assert len(app.items) == 1 and not app.items[0].get("made") \
                and app.items[0].get("line_id") != "L9", app.items
            assert app.hvars["Job"].get() == "AHU 3", app.hvars["Job"].get()
            app.items = []
            app._refresh_items_tree()
        finally:
            _feat._switches = {}
    add("dialogs: roster, a full day, and order again", _planning_windows)

    def _sales_windows():
        """Quotes to chase, why quotes are lost, filter changes due, changing
        prices and who owes what."""
        import webbrowser
        from taf_order_app import features as _feat
        _feat._switches = {k: True for k in (
            "quote_chase", "lost_reasons", "service_reminders", "price_change",
            "owing_view", "order_again")}
        opened, real = [], webbrowser.open
        webbrowser.open = lambda url, *a, **k: opened.append(url)
        real_open_path = gui._open_path
        gui._open_path = lambda path: opened.append(str(path))
        real_owing = gui._xero.owing
        real_app_dir = gui.APP_DIR
        gui.APP_DIR = Path(tempfile.mkdtemp(prefix="taf-statements-"))
        gui._xero.owing = lambda: {"rows": [
            {"customer": "Bells Creek", "number": "INV-1", "due": "2026-08-01",
             "total": 100, "owing": 100, "days_late": 70},
            {"customer": "Tweed", "number": "INV-2", "due": "2026-12-01",
             "total": 50, "owing": 50, "days_late": 0}], "owed": 150, "error": ""}

        def _wait(tree):
            for _ in range(80):
                root.update()
                if tree.get_children():
                    return
                time.sleep(0.05)

        try:
            dlg, tree, _f = app._quotes_to_chase()
            _wait(tree)
            assert tree.get_children() == ("q9",), tree.get_children()
            CHASED.clear()
            link = app._chase_quote(dlg.chase_cache["q9"], dlg)
            assert link.startswith("mailto:") and "Q-0009" in link and CHASED == ["q9"], link
            dlg.destroy()

            dlg, tree, foot = app._lost_report()
            _wait(tree)
            assert "q8" in tree.get_children(), tree.get_children()
            LOST.clear()
            d = app._mark_quote_lost({"id": "q8", "quote_number": "Q-0008"}, dlg)
            d.lost_vars[0].set("Price")
            d.lost_save()
            assert LOST == [("q8", "Price")], LOST
            dlg.destroy()

            dlg, tree, _f = app._service_due_window()
            _wait(tree)
            assert tree.get_children() == ("c-svc",), tree.get_children()
            dlg.destroy()

            if gui._db.can_manage_prices():
                dlg = app._price_change_tool()
                v = dlg.price_vars
                v["pct"].set("10")
                dlg.price_preview()
                assert dlg.price_tree.get_children(), "the preview is empty"
                assert "would change, now" in dlg.price_said.cget("text"), \
                    dlg.price_said.cget("text")
                PRICE_CHANGES.clear()
                was = gui.messagebox.askyesno
                gui.messagebox.askyesno = lambda *a, **k: True
                try:
                    dlg.price_go()
                finally:
                    gui.messagebox.askyesno = was
                assert PRICE_CHANGES and PRICE_CHANGES[0]["percent"] == 10.0, PRICE_CHANGES
                assert dlg.price_said.cget("text").startswith("Done: 3 prices"), \
                    dlg.price_said.cget("text")
                dlg.destroy()

            dlg, tree, foot = app._owing_window()
            _wait(tree)
            rows = [tree.item(i, "values") for i in tree.get_children()]
            assert rows[0][0] == "Bells Creek" and rows[0][1] == "$100.00", rows
            tree.focus(tree.get_children()[0])
            dlg.owing_statement()
            assert os.path.exists(dlg.last_statement), dlg.last_statement
            dlg.destroy()
        finally:
            webbrowser.open = real
            gui._open_path = real_open_path
            gui._xero.owing = real_owing
            gui.APP_DIR = real_app_dir
            _feat._switches = {}
    add("dialogs: winning the work", _sales_windows)

    def _answer_waiting_dialogs(before):
        """Say yes to a dialog that has stopped and asked something.

        Most feature screens open a window and return. One asks first —
        which monitor the customer display goes on — and wait_window does
        not come back until that is answered, so without this the whole run
        stops there with no output and no failure.

        It presses the dialog's own confirm button rather than closing it,
        because cancelling would mean the screen behind it never opens and
        the check would report that as the feature being broken.

        It only ever presses a confirm button, and never closes anything.
        Plenty of feature screens are modal in their own right, and a sweep
        that destroyed every modal window it found would destroy those —
        which showed up as "_media_nesting opened nothing", a screen that
        was working perfectly.
        """
        state = {"stop": False}

        def tick(n=0):
            if state["stop"]:
                return
            for w in list(root.winfo_children()):
                if w in before or not isinstance(w, tk.Toplevel):
                    continue
                go = getattr(w, "_go", None)
                if not callable(go):
                    continue          # not a dialog that is asking anything
                try:
                    go()
                except Exception:
                    pass
            if n < 60:
                root.after(25, lambda: tick(n + 1))

        root.after(25, tick)
        return lambda: state.update(stop=True)

    def _new_screens():
        """Every feature with a screen of its own has to open, and none of
        them may open when its switch is off."""
        from taf_order_app import features as _feat
        for key, _label, method in gui.ModernOrderApp.FEATURE_SCREENS:
            _feat._switches = {key: True}
            before = set(root.winfo_children())
            stop = _answer_waiting_dialogs(before)
            try:
                getattr(app, method)()
            finally:
                stop()
            root.update()
            opened = set(root.winfo_children()) - before
            if not opened:
                raise AssertionError(f"{method} opened nothing")
            for _ in range(6):
                root.update()          # the table windows fill in a thread
            for w in opened:
                w.update_idletasks()
                w.destroy()
        _feat._switches = {}
    add("dialogs: every feature screen", _new_screens)

    def _xero_screen():
        """Where every order's invoice is up to, with what stopped one."""
        from tkinter import ttk
        from taf_order_app import xero as _x
        saved = (_x.status, _x.invoices, _x.owing)
        _x.status = lambda: {"connected": True, "organisation": "TAF",
                             "drafts_from": "2026-10-16T00:00:00Z"}
        _x.invoices = lambda: {"rows": [
            {"order_id": "o1", "order_number": "21692",
             "customer_name": "BATARE", "order_status": "Complete",
             "state": "sent", "invoice_number": "21692", "total": 418.0,
             "emailed_to": "accounts@batare.example"},
            {"order_id": "o2", "order_number": "21700",
             "customer_name": "Nobody", "order_status": "Pending",
             "state": "waiting",
             "error": 'Xero has no contact called "Nobody".'}]}
        _x.owing = lambda: {"rows": [], "owed": 0.0, "error": ""}
        before = set(root.winfo_children())
        try:
            app._xero()
            dlg = None
            for _ in range(80):
                root.update()
                opened = set(root.winfo_children()) - before
                dlg = next(iter(opened), None)
                trees = [w for w in _walk(dlg) if isinstance(w, ttk.Treeview)] \
                    if dlg else []
                if trees and trees[0].get_children():
                    break
                time.sleep(0.05)
            assert dlg is not None, "the Xero screen did not open"
            orders = trees[0]
            assert set(orders.get_children()) == {"o1", "o2"}, \
                orders.get_children()
            assert "Approved and emailed" in orders.item("o1", "values")
            assert "problem" in orders.item("o2", "tags")
            words = " ".join(str(w.cget("text")) for w in _walk(dlg)
                             if isinstance(w, tk.Label))
            assert "Connected to TAF" in words and "1 needs attention" in words, \
                words
            dlg.destroy()
        finally:
            _x.status, _x.invoices, _x.owing = saved
    add("dialogs: the Xero screen lists every order's invoice", _xero_screen)

    def _line_price_section():
        """A price typed on a line is kept as set by hand; left empty, the
        line waits for the customer's tier price."""
        for typed, want in (("27.5", (27.5, "manual")), ("", (None, None))):
            dlg = gui.LineItemDialog(root, title="Price",
                                     initial={"Quantity": 2, "Short": 595,
                                              "Long": 595, "Channel": 45})
            dlg._price.var.set(typed)
            dlg._price.txt.insert("1.0", "Special wording")
            dlg._save()
            got = dlg.result or {}
            assert (got.get("Unit Price"), got.get("Price Source")) == want, got
            assert got.get("Xero Description") == "Special wording", got
        # Not a number: refused, the dialog stays open.
        said = []
        was = gui.messagebox.showerror
        gui.messagebox.showerror = lambda *a, **k: said.append(a)
        try:
            dlg = gui.LineItemDialog(root, title="Price",
                                     initial={"Quantity": 2, "Short": 595,
                                              "Long": 595, "Channel": 45})
            dlg._price.var.set("lots")
            dlg._save()
            assert dlg.result is None and said, said
            dlg.destroy()
        finally:
            gui.messagebox.showerror = was
    add("dialogs: a line's price and Xero description", _line_price_section)

    def _order_prices():
        """The work order shows each line's price and the order's total,
        priced from the customer's tier."""
        app._show_tab("new_order")
        root.update()
        saved = list(app.items)
        try:
            app.items = [
                {"item_kind": "filter", "Filter Type": "V-form",
                 "Media Type": "G4", "Short": 595, "Long": 595, "Channel": 45,
                 "Quantity": 4, "Part Number": "PPFG445-030"},
                {"item_kind": "filter", "Filter Type": "V-form",
                 "Media Type": "G4", "Short": 595, "Long": 595, "Channel": 45,
                 "Quantity": 1, "Part Number": "PPFG445-030",
                 "Unit Price": 20.0, "Price Source": "manual"},
                {"item_kind": "bag", "product_type": "3-Peak", "quantity": 2,
                 "media": "F7", "width": 592, "height": 592, "depth": 600,
                 "part_number": "NO-PRICE"}]
            app._apply_prices({"PPFG445-030": 27.0}, {}, 2)
            vals = [app.tree.item(i, "values") for i in app.tree.get_children()]
            cols = list(app.tree["columns"])
            unit = [v[cols.index("price")] for v in vals]
            line = [v[cols.index("total")] for v in vals]
            assert unit == ["27.00", "✎ 20.00", "—"], unit
            assert line == ["108.00", "20.00", "—"], line
            right = app._items_card._hdr_right_var.get() \
                if hasattr(app._items_card, "_hdr_right_var") else ""
            assert app.items[0]["Price Source"] == "tier 2"
            total, missing = gui._order_money(app.items)
            assert (total, missing) == (128.0, 1), (total, missing)
            del right
        finally:
            app.items = saved
            app._refresh_items_tree()
    add("new order: prices from the customer's tier, and the total",
        _order_prices)

    def _wording_screen():
        before = set(root.winfo_children())
        dlg = app._xero_wording()
        root.update()
        trees = [w for w in _walk(dlg) if isinstance(w, gui.ttk.Treeview)]
        rows = trees[0].get_children()
        assert len(rows) == 3, rows
        example = trees[0].item(rows[2], "values")[3]
        assert example.startswith("Galvanised Pleated Panel Filter in G4"), example
        for w in set(root.winfo_children()) - before:
            w.destroy()
    add("dialogs: invoice wording", _wording_screen)

    def _send_to_xero():
        """The trial's button: priced, confirmed, sent, and the order marked
        Complete - with nothing sent for an order that has an unpriced line."""
        from taf_order_app import features as _feat
        from taf_order_app import xero as _x
        sent, completed, said, opened = [], [], [], []
        saved = (_x.push_draft, gui._db.set_order_status,
                 gui.messagebox.askyesno, gui.messagebox.showinfo,
                 gui.messagebox.showwarning, dict(_feat._switches),
                 _x.invoice_pdf)
        # A one-page PDF standing in for Xero's invoice.
        import io
        from reportlab.pdfgen import canvas as _canvas
        buf = io.BytesIO()
        _c = _canvas.Canvas(buf)
        _c.drawString(72, 720, "TAX INVOICE INV-1")
        _c.showPage()
        _c.save()
        _x.invoice_pdf = lambda oid, timeout=60: {"pdf": buf.getvalue(),
                                                  "number": "INV-1"}
        app._output_invoice_paperwork = lambda path: opened.append(path)
        _x.push_draft = lambda oid, built, md5="", invoice_now=False: (
            sent.append((oid, built, invoice_now))
            or {"state": "sent", "number": "INV-1", "emailed_to": "a@b.example"})
        gui._db.set_order_status = lambda oid, st: completed.append((oid, st))
        gui.messagebox.askyesno = lambda *a, **k: said.append(a) or True
        gui.messagebox.showinfo = lambda *a, **k: said.append(a)
        gui.messagebox.showwarning = lambda *a, **k: said.append(a)
        _feat._switches = {"xero_live": True}
        loaded = dict(app._tab_loaded)
        app._refresh_orders_list = lambda: None   # the list stays as it is
        try:
            priced = {"source": "db", "db_id": "o-1", "order_no": "21692",
                      "customer": "BATARE", "status": "Pending",
                      "db_header": {"Order Number": "21692",
                                    "Customer Name": "BATARE",
                                    "Date Ordered": "16/10/26"},
                      "db_items": [{"item_kind": "filter",
                                    "Filter Type": "V-form",
                                    "Media Type": "G4", "Short": 595,
                                    "Long": 595, "Channel": 45, "Quantity": 2,
                                    "Unit Price": 30.0,
                                    "Price Source": "tier 1"}]}
            # A bag with no part number and no price on the order.
            unpriced = dict(priced, db_id="o-2", order_no="21693",
                            db_header=dict(priced["db_header"],
                                           **{"Order Number": "21693"}),
                            db_items=[{"item_kind": "bag",
                                       "product_type": "3-Peak",
                                       "quantity": 1, "media": "F7",
                                       "width": 592, "height": 592,
                                       "depth": 600}])
            app._xero_send_orders([priced, unpriced], True)
            for _ in range(200):
                root.update()
                if len(said) >= 2 and opened:   # asked, said, and opened
                    break
                time.sleep(0.05)
            assert [s[0] for s in sent] == ["o-1"] and sent[0][2] is True, sent
            assert sent[0][1]["invoice"]["lines"][0]["unit_amount"] == 30.0
            assert completed == [("o-1", "Complete")], completed
            ask = str(said[0])
            assert "$60.00 ex GST" in ask and "21693" in ask and \
                "no price" in ask, ask
            # The invoice and its packing slip, in one PDF, opened.
            from pypdf import PdfReader
            assert len(opened) == 1 and opened[0].endswith(
                "Invoice INV-1 - 21692.pdf"), opened
            pages = PdfReader(opened[0]).pages
            # Xero's invoice, then the delivery docket (two copies).
            assert len(pages) >= 3, len(pages)
            assert "TAX INVOICE" in pages[0].extract_text()
            rest = "".join(pg.extract_text() for pg in pages[1:])
            assert "DELIVERY DOCKET" in rest and "CUSTOMER COPY" in rest, rest[:200]
        finally:
            (_x.push_draft, gui._db.set_order_status, gui.messagebox.askyesno,
             gui.messagebox.showinfo, gui.messagebox.showwarning,
             _feat._switches, _x.invoice_pdf) = saved
            del app._refresh_orders_list
            del app._output_invoice_paperwork
            app._tab_loaded.clear()
            app._tab_loaded.update(loaded)
    add("orders: Send to Xero & invoice customer", _send_to_xero)

    def _press(win, text):
        for w in _walk(win):
            if isinstance(w, gui.PillButton) and w.cget("text") == text:
                w._cmd()
                return
        raise AssertionError(f"no {text!r} button")

    def _correct_saved_order():
        """A saved order's prices, dates, job and delivery fee are corrected
        from View Order, and written back to the order."""
        saved_lines, saved_details, refills = [], [], []
        stubs = {"xero_invoice_for": lambda oid: {},
                 "replace_order_line": lambda oid, lid, line: (
                     saved_lines.append((oid, lid, line)) or [line]),
                 "update_order_details": lambda oid, patch: saved_details.append(
                     (oid, patch))}
        was = {k: getattr(gui._db, k) for k in stubs}
        was_reread = app._reread_order
        for k, v in stubs.items():
            setattr(gui._db, k, v)
        app._reread_order = lambda row: {}
        loaded = dict(app._tab_loaded)
        dlg = gui.tk.Toplevel(root)
        try:
            line = {"item_kind": "filter", "Filter Type": "V-form",
                    "Media Type": "G4", "Short": 595, "Long": 595,
                    "Channel": 45, "Quantity": 3, "_line_id": "L1",
                    gui._db.LINE_ID: "L1", "Unit Price": 30.0,
                    "Price Source": "tier 1"}
            row = {"source": "db", "db_id": "o-9", "order_no": "21692",
                   "customer": "BATARE", "db_items": [line],
                   "db_header": {"Date Ordered": "16/10/26", "Date Due": "ASAP",
                                 "Job": "AHU 3"}}
            app._save_saved_line_money(row, [line], 0, "total", "100",
                                       dlg, lambda: refills.append(1))
            got = saved_lines[-1][2]
            assert saved_lines[-1][:2] == ("o-9", "L1"), saved_lines
            assert (got["Unit Price"], got["Price Source"]) == (33.3333, "manual"), got
            assert refills, "the window was not redrawn"
            ed = app._edit_saved_details(row, dlg, lambda: refills.append(2))
            entries = [w for w in _walk(ed) if isinstance(w, gui.tk.Entry)]
            for ent, value in zip(entries, ("17/10/26", "24/10/26", "AHU 4")):
                ent.delete(0, "end")
                ent.insert(0, value)
            _press(ed, "Save")
            oid, patch = saved_details[-1]
            assert oid == "o-9" and patch.get("Date Ordered") == "17/10/26" \
                and patch.get("Date Due") == "24/10/26" \
                and patch.get("Job") == "AHU 4", saved_details
            # A date that is not one is refused, and nothing saved.
            said, was_err = [], gui.messagebox.showerror
            gui.messagebox.showerror = lambda *a, **k: said.append(a)
            try:
                n = len(saved_details)
                ed = app._edit_saved_details(row, dlg, lambda: None)
                entries = [w for w in _walk(ed) if isinstance(w, gui.tk.Entry)]
                entries[1].delete(0, "end")
                entries[1].insert(0, "next tuesday")
                _press(ed, "Save")
                assert len(saved_details) == n and said, said
                ed.destroy()
            finally:
                gui.messagebox.showerror = was_err
        finally:
            for k, v in was.items():
                setattr(gui._db, k, v)
            app._reread_order = was_reread
            app._tab_loaded.clear()
            app._tab_loaded.update(loaded)
            dlg.destroy()
    add("previous orders: correct a saved order's prices, dates and job",
        _correct_saved_order)

    def _type_a_price_in():
        """Unit $ and Line $ can be typed straight into the order's table."""
        app._show_tab("new_order")
        root.update()
        saved = list(app.items)
        try:
            app.items = [{"item_kind": "filter", "Filter Type": "V-form",
                          "Media Type": "G4", "Short": 595, "Long": 595,
                          "Channel": 45, "Quantity": 4}]
            app._refresh_items_tree()
            root.update()
            cols = list(app.tree["columns"])
            col_id = f"#{cols.index('total') + 1}"
            app.tree.see("0")
            root.update()
            typed = []
            ent = gui._inline_money_edit(
                app.tree, "0", col_id, "",
                lambda text: (typed.append(text),
                              gui._set_line_money(app.items[0], "total", text),
                              app._refresh_items_tree()))
            assert ent is not None, "the cell could not be typed into"
            ent.delete(0, "end")
            ent.insert(0, "200")
            ent.commit()                    # as pressing Enter does
            root.update()
            assert app.items[0].get("Unit Price") == 50.0, (typed, app.items[0])
            assert app.tree.set("0", "price") == "✎ 50.00", app.tree.set("0", "price")
        finally:
            app.items = saved
            app._refresh_items_tree()
    add("new order: type a price into Unit $ / Line $", _type_a_price_in)

    def _xero_contact_picker():
        linked = []
        dlg = app._xero_contact_picker(
            {"id": "c1", "name": "BATARE"}, "batare",
            [{"id": "x-1", "name": "Batare Pty Ltd", "email": "a@b.example"}],
            lambda c: linked.append(c) or True)
        root.update()
        trees = [w for w in _walk(dlg) if isinstance(w, gui.ttk.Treeview)]
        trees[0].selection_set("x-1")
        _press(dlg, "Link")
        assert linked and linked[0]["id"] == "x-1", linked
    add("customers: link to a Xero contact", _xero_contact_picker)

    def _supplies_as_orders():
        """One row an order: three things sent together are one row,
        opened to see them, and moved along together."""
        app._show_tab("supplies")
        for _ in range(60):
            root.update()
            if app._suppliers is not None and app.supply_tree.get_children():
                break
            time.sleep(0.05)
        tree = app.supply_tree
        tops = tree.get_children()
        assert len(tops) == 4, [tree.item(i, "values") for i in tops]
        batch = next(i for i in tops if app._supply_orders[i]["key"] == "b1")
        vals = tree.item(batch, "values")
        assert vals[0].startswith("3 items: Media - G4 media roll"), vals
        assert vals[5] == "Waiting - 1 of 3 dealt with", vals
        assert len(tree.get_children(batch)) == 3
        assert not tree.item(batch, "open")
        bbox = None
        tree.see(batch)
        root.update()
        bbox = tree.bbox(batch)
        app._toggle_supply_order(type("E", (), {"y": bbox[1] + 2})())
        assert tree.item(batch, "open"), "double-click opens an order"
        if gui._db.can_handle_supplies():
            MOVED.clear()
            tree.selection_set(batch)
            app._move_supply("ordered")
            for _ in range(60):
                root.update()
                if MOVED:
                    break
                time.sleep(0.05)
            _settle(0.2)
            assert MOVED == [("r4", "ordered"), ("r6", "ordered")], MOVED
            # A line on its own.
            MOVED.clear()
            tree.selection_set(tree.get_children(batch)[0])
            app._move_supply("received")
            for _ in range(60):
                root.update()
                if MOVED:
                    break
                time.sleep(0.05)
            assert MOVED == [("r4", "received")], MOVED
    add("supplies: requests sent together are one order", _supplies_as_orders)

    def _po_from_a_request():
        """A request for 47mm channel from FD Greenwood becomes a purchase
        order line, priced between the 45 and the 50."""
        SAVED_POS.clear()
        dlg = app._po_editor(supplier_id="s-fdg", requests=[
            {"id": "r9", "item": "Channel", "detail": "47mm",
             "quantity": "20 lengths", "supplier_id": "s-fdg"}])
        tree = None
        for _ in range(60):
            root.update()
            trees = [w for w in _walk(dlg) if isinstance(w, gui.ttk.Treeview)]
            if trees and trees[0].get_children():
                tree = trees[0]
                break
            time.sleep(0.05)
        assert tree is not None, "no lines on the purchase order"
        values = tree.item("0", "values")
        assert values[0] == "FDG-C47-2440" and values[3] == "$19.46", values
        assert "estimated" in values[5], values
        words = " ".join(str(w.cget("text")) for w in _walk(dlg)
                         if isinstance(w, tk.Label))
        assert "estimated from the sizes either side" in words, words
        _press(dlg, "Save draft")
        for _ in range(60):
            root.update()
            if SAVED_POS:
                break
            time.sleep(0.05)
        _settle(0.2)
        po = SAVED_POS[0]
        assert (po["supplier"], po["supplier_id"], po["supplier_email"]) == \
            ("FD Greenwood", "s-fdg", "orders@fdg.example"), po
        assert po["lines"][0]["request_ids"] == ["r9"], po["lines"]
        assert not dlg.winfo_exists()
    add("buying: a purchase order from a request, with a size estimated",
        _po_from_a_request)

    def _po_line():
        """Typing a code Xero has fills it in; one it hasn't is estimated."""
        got = []
        win = app._po_line_dialog(root, {"quantity": 1}, XERO_ITEMS, got.append)
        root.update()
        combo = [w for w in _walk(win) if isinstance(w, gui.ttk.Combobox)][0]
        combo.set("FDG-C55-2440")
        combo.event_generate("<<ComboboxSelected>>")
        root.update()
        _press(win, "OK")
        assert got and got[0]["unit_price"] == 23.3, got
        assert got[0]["estimated"].startswith("estimated from"), got
    add("buying: a line's price estimated from the sizes either side", _po_line)

    def _po_receive():
        """Five of the fifteen still to come arrive."""
        RECEIVED.clear()
        win = app._po_receive(dict(PURCHASE_ORDERS[0]))
        root.update()
        boxes = [w for w in _walk(win) if isinstance(w, tk.Entry)]
        assert boxes[0].get() == "15" and str(boxes[1].cget("state")) == "disabled"
        boxes[0].delete(0, "end")
        boxes[0].insert(0, "5")
        _press(win, "Book it in")
        for _ in range(60):
            root.update()
            if RECEIVED:
                break
            time.sleep(0.05)
        _settle(0.2)
        assert RECEIVED == [("po-1", [{"line": 0, "qty": 5.0}])], RECEIVED
    add("buying: tick off what arrived", _po_receive)

    def _po_window():
        win = app._purchase_orders()
        trees = []
        for _ in range(60):
            root.update()
            trees = [w for w in _walk(win) if isinstance(w, gui.ttk.Treeview)]
            if trees and trees[0].get_children():
                break
            time.sleep(0.05)
        orders, suppliers, stock, items = trees[:4]
        assert orders.item("po-1", "values")[0] == "PO-0007"
        assert orders.item("po-1", "values")[4] == "Sent"
        assert set(suppliers.get_children()) == {"s-fdg", "s-vul"}
        assert len(items.get_children()) == 3
        assert "★ Vulcan (VUL-BF592) $3.00" in stock.item("s2", "values")[3], \
            stock.item("s2", "values")
        assert "bad" in stock.item("s2", "tags")        # below its minimum
        win.destroy()
    add("buying: the purchase orders window", _po_window)

    def _po_sent_in_xero():
        """Xero cannot email a purchase order through its API, so it is
        opened in Xero to be emailed from there."""
        import webbrowser
        opened, real = [], webbrowser.open
        webbrowser.open = lambda url, *a, **k: opened.append(url)
        try:
            text = app._po_in_xero({"po_number": "PO-0008", "send_in_xero": True,
                                    "xero_po_id": "x-po-8"})
        finally:
            webbrowser.open = real
        assert opened == ["https://go.xero.com/Accounts/Payable/PurchaseOrders/View/x-po-8"], opened
        assert "PO-0008" in text and "Email" in text, text
    add("buying: a purchase order is opened in Xero to email", _po_sent_in_xero)

    def _something_not_in_stock():
        """New order takes something typed that is not a stock item."""
        app._show_tab("supplies")
        app._new_supply_order()
        win = app._supply_order_win
        root.update()
        win.other.set("pop rivets 4mm")
        win.add_other()
        root.update()
        assert [(l["stock"], l["text"]) for l in win.lines] == \
            [(None, "pop rivets 4mm")], win.lines
        win.lines[0]["qty"].set("2 boxes")
        win.lines[0]["sup"].set("Vulcan")
        SENT_SUPPLIES.clear()
        win.send()
        for _ in range(60):
            root.update()
            if SENT_SUPPLIES:
                break
            time.sleep(0.05)
        _settle(0.2)
        assert SENT_SUPPLIES == [[
            {"item": "Rivets", "detail": "pop rivets 4mm", "quantity": "2 boxes",
             "supplier_id": "s-vul", "item_code": "", "stock_item_id": ""}]], \
            SENT_SUPPLIES
    add("supplies: New order takes what is not on the stock list",
        _something_not_in_stock)

    def _order_what_is_low():
        """The bag frame is short: a purchase order to Vulcan, at the agreed
        price, for what gets it back to its minimum."""
        if not gui._db.can_manage_prices():
            return          # a manager's button; the floor is not offered it
        win = app._purchase_orders()
        for _ in range(60):
            root.update()
            trees = [w for w in _walk(win) if isinstance(w, gui.ttk.Treeview)]
            if trees and trees[0].get_children():
                break
            time.sleep(0.05)
        before = set(root.winfo_children())
        _press(win, "Order what is low…")
        editor, tree = None, None
        for _ in range(60):
            root.update()
            opened = [w for w in set(root.winfo_children()) - before
                      if isinstance(w, tk.Toplevel)]
            if opened:
                editor = opened[0]
                ts = [w for w in _walk(editor) if isinstance(w, gui.ttk.Treeview)]
                combos = [w for w in _walk(editor)
                          if isinstance(w, gui.ttk.Combobox)]
                # Its lines are there at once; the supplier once loaded.
                if ts and ts[0].get_children() and combos and combos[0].get():
                    tree = ts[0]
                    break
            time.sleep(0.05)
        assert tree is not None, "no purchase order made from low stock"
        values = tree.item("0", "values")
        assert values[0] == "VUL-BF592" and values[2] == "6" and \
            values[3] == "$3.00", values
        combo = [w for w in _walk(editor) if isinstance(w, gui.ttk.Combobox)][0]
        assert combo.get() == "Vulcan", combo.get()
        editor.destroy()
        win.destroy()
    add("buying: order what is low, from where it comes from", _order_what_is_low)

    def _stock_cards():
        """Stock is square cards; a card clicked is the item the buttons
        under it act on, and double-clicked it opens."""
        app._show_tab("stock")
        app._refresh_stock_list()
        for _ in range(80):
            root.update()
            if len(app._stock_cards) == 2 and app._stock_layout:
                break
            time.sleep(0.05)
        _settle(0.3)
        assert len(app._stock_cards) == 2, len(app._stock_cards)
        sizes = {(c.winfo_width(), c.winfo_height()) for c, _p, _i in app._stock_cards}
        assert len(sizes) == 1 and all(w == h and w > 50 for w, h in sizes), sizes
        card, parts, item = app._stock_cards[1]
        assert "MOQ 10" in parts["moq"].cget("text"), parts["moq"].cget("text")
        assert parts["state"] == "low"
        card.event_generate("<Button-1>", x=5, y=5)
        root.update()
        assert app._get_selected_stock()["id"] == item["id"]
        assert str(card.cget("highlightbackground")) == gui.CA
        before = set(root.winfo_children())
        # Tk cannot be sent a double-click, so the card's own double-click
        # action is run - the one bound to <Double-1> on it.
        assert "<Double-Button-1>" in card.bind(), card.bind()
        card.open_item(None)
        root.update()
        opened = set(root.winfo_children()) - before
        assert opened, "double-clicking a card opened nothing"
        for w in opened:
            w.destroy()
        app._stock_search_var.set("bag frame")
        _settle(0.4)
        assert len(app._stock_cards) == 1, "search no longer narrows the cards"
        app._stock_search_var.set("")
        _settle(0.4)
    add("stock: square cards, picked and opened", _stock_cards)

    def _stock_insight_windows():
        """What we have paid for an item, and what to order before it runs
        out."""
        from taf_order_app import features as _feat
        _feat._switches = {k: True for k in ("stock_reserve", "price_history",
                                             "lead_times")}

        def _wait(tree):
            for _ in range(80):
                root.update()
                if tree.get_children():
                    return
                time.sleep(0.05)

        try:
            app._show_tab("stock")
            app._refresh_stock_list()
            for _ in range(80):
                root.update()
                if len(app._stock_cards) == 2:
                    break
                time.sleep(0.05)
            card = next(c for c, _p, i in app._stock_cards if i["id"] == "s1")
            card.event_generate("<Button-1>", x=5, y=5)
            root.update()
            dlg, tree, foot = app._stock_price_history()
            _wait(tree)
            rows = [tree.item(c, "values") for c in tree.get_children()]
            # The older price was bought under the supplier's code, not the id.
            assert len(rows) == 2, rows
            assert rows[0][3] == "$88.00" and rows[0][4] == "+10.0%", rows[0]
            assert rows[1][5] == "PO-0003", rows[1]
            dlg.destroy()

            dlg, tree, foot = app._order_soon_window()
            _wait(tree)
            rows = [tree.item(c, "values") for c in tree.get_children()]
            names = [str(r[0]).strip() for r in rows]
            assert names[:3] == ["Order soon", "Bag frame 592", "G4 media roll"], names
            # 40 on hand, 28 on jobs: 12 free, used 1 a day, 2 days from the
            # minimum and FD Greenwood takes 5 - order 3.
            g4 = rows[2]
            assert g4[1].startswith("12") and g4[2] == "2 days" and \
                g4[3].startswith("5 days (FD Greenwood)") and g4[4].startswith("3"), g4
            assert rows[1][2] == "now" and "Vulcan" in rows[1][3], rows[1]
            assert "How long each supplier takes" in names, names
            dlg.destroy()
        finally:
            _feat._switches = {}
    add("stock: what we have paid, and order before it runs out",
        _stock_insight_windows)

    def _badge_and_loading():
        """The header's badge turns once when clicked and lands upright; the
        loading screen turns it until loading is done, then goes. Neither
        moves for somebody who has asked their computer for less motion."""
        saved = gui._REDUCED_MOTION
        try:
            gui._REDUCED_MOTION = False
            assert app._badge.ok, "TAF_logo_badge.png did not load"
            app._spin_badge(duration=0.3)
            seen = set()
            for _ in range(40):
                root.update()
                time.sleep(0.01)
                seen.add(str(app._badge_label.cget("image")))
            _settle(0.4)
            assert app._badge_spin is None, "the turn never finished"
            assert str(app._badge_label.cget("image")) == str(app._badge.frame(0)), \
                "it did not land upright"
            assert len(seen) > 3, f"it never turned ({len(seen)} positions)"

            ready = {"v": False}
            screen = gui.LoadingScreen(root, ready=lambda: ready["v"],
                                       shortest=0.1, longest=10)
            _settle(0.3)
            assert screen.winfo_exists() and screen._angle > 0, "not turning"
            ready["v"] = True
            _settle(0.8)
            assert not screen.winfo_exists(), "it stayed after loading"
            screen = gui.LoadingScreen(root, ready=lambda: False, longest=30)
            _settle(0.1)
            screen.event_generate("<Escape>")
            _settle(0.1)
            assert not screen.winfo_exists(), "Escape did not put it away"

            gui._REDUCED_MOTION = True
            app._spin_badge()
            assert app._badge_spin is None, "it spun with reduced motion"
            screen = gui.LoadingScreen(root, ready=lambda: False, longest=0.3)
            _settle(0.15)
            assert screen._angle == 0, "the loading badge turned with reduced motion"
            _settle(0.4)
            assert not screen.winfo_exists(), "it outstayed its longest wait"
        finally:
            gui._REDUCED_MOTION = saved
    add("header: the badge turns, and the loading screen", _badge_and_loading)

    def _smooth_scrolling():
        """A list scrolled by the wheel glides to where it is going - past
        positions in between - and lands exactly there; with reduced motion
        it goes straight there."""
        saved = gui._REDUCED_MOTION
        win = tk.Toplevel(root)
        try:
            cv = tk.Canvas(win, height=200, highlightthickness=0, bd=0)
            cv.pack()
            cv.create_rectangle(0, 0, 100, 1000)
            cv.configure(scrollregion=(0, 0, 100, 1000))
            root.update()
            gui._REDUCED_MOTION = False
            glide = gui.SmoothScroller(cv, 46)
            glide.by(300)
            seen = set()
            for _ in range(60):
                root.update()
                time.sleep(0.01)
                seen.add(round(cv.canvasy(0)))
            assert round(cv.canvasy(0)) == 300, cv.canvasy(0)
            assert len([y for y in seen if 0 < y < 300]) >= 4, sorted(seen)
            class Notch:
                num = 5
                delta = 0
            glide.wheel(Notch())
            glide.wheel(Notch())          # two notches add up
            _settle(0.6)
            assert round(cv.canvasy(0)) == 300 + round(2 * 46 * 0.9), cv.canvasy(0)
            glide.to(5000)                # never past the end
            _settle(0.8)
            assert round(cv.canvasy(0)) == 800, cv.canvasy(0)
            gui._REDUCED_MOTION = True
            glide.to(100)
            assert round(cv.canvasy(0)) == 100, "reduced motion should jump"
        finally:
            gui._REDUCED_MOTION = saved
            win.destroy()
    add("lists: smooth scrolling", _smooth_scrolling)

    def _cut_list():
        from taf_order_app import features as _feat
        _feat._switches = {"channel_calculator": True}
        before = set(root.winfo_children())
        app._cut_list_window([{"short": 295, "long": 310, "qty": 4}], "12576")
        opened = set(root.winfo_children()) - before
        if not opened:
            raise AssertionError("the cut list opened nothing")
        dlg = list(opened)[0]
        body = "".join(w.get("1.0", "end") for w in _walk(dlg)
                       if isinstance(w, tk.Text))
        # Whichever way it decided to make them, those are the marks that
        # have to be on the sheet. Asserting one method's numbers would break
        # the day the calculator correctly changed its mind.
        from taf_order_app import cutting as _cut
        won = _cut.best(295, 310, 4, _feat.workshop())["best"]
        for mark in won["shape"]["marks"]:
            if str(mark) not in body:
                raise AssertionError(
                    f"{mark} is missing from the cut list: {body[:300]}")
        if "length" not in body:
            raise AssertionError("the cut list never says how much channel")
        for w in opened:
            w.destroy()
        _feat._switches = {}
    add("dialog: cut list", _cut_list)

    def _ticking():
        """A tick has to survive the list being filtered and redrawn, or you
        tick four orders, clear the search, and mark the wrong ones."""
        app._show_tab("prev_orders")
        root.update()
        tree, shown = app.orders_tree, app._displayed_orders
        if not shown:
            raise AssertionError("no orders to tick")
        app._clear_ticks()
        if app._tick_bar.grid_info():
            raise AssertionError("the bulk bar is showing with nothing ticked")

        app._toggle_tick(tree.get_children()[0])
        if tree.set(tree.get_children()[0], "pick") != gui.TICK_FULL:
            raise AssertionError("ticking a row did not fill its box")
        if not app._tick_bar.grid_info():
            raise AssertionError("the bulk bar did not appear")
        picked = app._get_selected_orders()
        if len(picked) != 1 or picked[0] is not shown[0]:
            raise AssertionError(f"a tick did not decide the action: {picked}")

        # Highlighting something else must not quietly win.
        if len(tree.get_children()) > 1:
            tree.selection_set(tree.get_children()[1])
            if app._get_selected_orders() != [shown[0]]:
                raise AssertionError("a highlight overrode the ticks")

        # Filter it off screen and back.
        key = app._order_key(shown[0])
        app.search_var.set("zzz no order is called this")
        _settle()                      # the search waits for typing to pause
        if key not in app._ticked:
            raise AssertionError("the tick was lost when the row was filtered out")
        if "not shown" not in app._tick_lbl.cget("text"):
            raise AssertionError("it did not say the ticked order is out of view")
        app.search_var.set("")
        _settle()
        back = [i for i in tree.get_children()
                if tree.set(i, "pick") == gui.TICK_FULL]
        if len(back) != 1:
            raise AssertionError(f"the tick came back on {len(back)} rows")

        app._toggle_all_ticks()
        if len(app._ticked) != len(app._displayed_orders):
            raise AssertionError("the heading did not tick everything shown")
        app._toggle_all_ticks()
        if app._ticked or app._tick_bar.grid_info():
            raise AssertionError("clicking the heading again did not clear")
    add("previous orders: ticking", _ticking)

    # The bug: every write was wrapped in `except Exception: pass`, so a
    # refused one was reported as saved and the list came back unchanged.
    #
    # The writes run off the main thread and report back with after(), so
    # this is a step to start it and a step to check it. Waiting inside one
    # step cannot work: steps run *in* the event loop, so a step that sits
    # there is a step that stops the callback it is waiting for from ever
    # arriving. The gap between two steps is where the loop actually runs.
    told: list = []
    saved: dict = {}

    def _refuse_every_write():
        app._show_tab("prev_orders")
        rows = [r for r in app._displayed_orders
                if r.get("source") == "db" and r.get("db_id")]
        if not rows:
            raise AssertionError("no database orders to change")

        def refuse(_oid, _status):
            raise RuntimeError("new row violates row-level security policy")

        saved["set"] = gui._db.set_order_status
        saved["err"] = gui.messagebox.showerror
        gui._db.set_order_status = refuse
        gui.messagebox.showerror = lambda _t, m: told.append(m)
        app._apply_status_to(rows, "Complete")
    add("previous orders: refuse every write", _refuse_every_write)

    def _the_refusal_is_reported():
        try:
            if not told:
                raise AssertionError(
                    "the database refused every write and the app said nothing")
            if "row-level security" not in told[0]:
                raise AssertionError(f"it did not say why: {told[0]!r}")
            if "0 of" not in app.status_var.get():
                raise AssertionError(
                    f"the status line claims work that did not happen: "
                    f"{app.status_var.get()!r}")
        finally:
            gui._db.set_order_status = saved.get("set", gui._db.set_order_status)
            gui.messagebox.showerror = saved.get("err", gui.messagebox.showerror)
            app._clear_ticks()
    add("previous orders: a refused bulk change is reported",
        _the_refusal_is_reported)

    def _pills(widget, found):
        if isinstance(widget, gui.PillButton):
            found.append((widget.cget("text"), str(widget.cget("bg")).upper()))
        for child in widget.winfo_children():
            _pills(child, found)
        return found

    def _settings_rows_are_one_per_widget():
        """The rows in Settings are written out by hand, so inserting a group
        in the middle is how two cards end up stacked in one cell with one of
        them invisible. Only a real window can tell a card gridded into the
        settings frame from one nested inside another card, which is why this
        lives here rather than in a source check."""
        frame = app._tab_frames.get("settings")
        if frame is None:
            raise AssertionError("Settings was never built")
        # The scrolling frame everything is gridded into.
        holder = None
        for kid in frame.winfo_children():
            for inner in [kid] + list(kid.winfo_children()):
                if [w for w in inner.winfo_children() if w.grid_info()]:
                    holder = inner
        if holder is None:
            raise AssertionError("could not find the settings frame")
        seen = {}
        for w in holder.winfo_children():
            info = w.grid_info()
            if not info:
                continue
            row = int(info.get("row", -1))
            if row in seen:
                raise AssertionError(
                    f"two things share row {row} of Settings: "
                    f"{seen[row]} and {w.winfo_class()} — one is invisible")
            seen[row] = w.winfo_class()
        if len(seen) < 10:
            raise AssertionError(
                f"only found {len(seen)} rows in Settings; the check is "
                f"looking at the wrong frame")
    add("settings: nothing is hidden under anything else",
        _settings_rows_are_one_per_widget)

    def _button_weights():
        """Supporting actions are quiet, and each row of buttons has a point.

        Slate was the colour a button got when it wasn't the main action.
        There were over a hundred of them, so "not the main action" was as
        loud as "the main action" and no screen had any shape.

        Counting per row rather than per tab is the honest measure: Settings
        is six sections and each may fairly have its own Save, but a single
        row of six saturated buttons tells you nothing about what to press.
        """
        slate = gui.CNE.upper()
        loud = {gui.CA.upper(), gui.CGR.upper(), gui.CRD.upper(),
                gui.CA2.upper(), gui.CMU.upper()}
        left_slate, crowded = [], []
        frames = getattr(app, "_tab_frames", {})
        if not frames:
            raise AssertionError("no tabs to look at")

        def rows(widget, tab):
            here = [(str(c.cget("text")), str(c.cget("bg")).upper())
                    for c in widget.winfo_children()
                    if isinstance(c, gui.PillButton)]
            shouting = [t for t, bg in here if bg in loud]
            if len(shouting) > 2:
                crowded.append(f"{tab}: {shouting}")
            for child in widget.winfo_children():
                rows(child, tab)

        for key, frame in frames.items():
            left_slate += [t for t, bg in _pills(frame, []) if bg == slate]
            rows(frame, key)
        if left_slate:
            raise AssertionError(f"still slate: {left_slate}")
        if crowded:
            raise AssertionError("too many loud buttons in one row:\n  "
                                 + "\n  ".join(crowded))
    add("button weights", _button_weights)

    def _dark_mode_keeps_up():
        """The quiet weights are mixed from two palette colours, so they are
        not palette colours themselves and the theme walk used to skip them —
        a pale blue button stayed pale blue on a dark card."""
        light = gui._button_variants()["secondary"][0].upper()
        # Toggling writes the preference to the settings file. Don't touch a
        # real one just to look at some colours.
        saved, gui._save_settings = gui._save_settings, lambda *a, **k: None
        app._settings["dark_mode"] = False
        try:
            app._toggle_dark_mode()
            stranded = [t for t, bg in _pills(root, []) if bg == light]
            if stranded:
                raise AssertionError(
                    f"still on the light-mode colour after the switch: {stranded}")
        finally:
            app._toggle_dark_mode()          # put it back for the steps after
            gui._save_settings = saved
    add("dark mode: every button follows", _dark_mode_keeps_up)

    add("banner: exports", lambda: print("Exporting…"))
    for label, call in _exports(app, gui):
        add(label, call)
    return steps


def _open_and_close(make):
    def go():
        dlg = make()
        try:
            dlg.update_idletasks()
        finally:
            dlg.destroy()
    return go


def _dialogs(gui, root):
    import tkinter as tk
    var = tk.StringVar(master=root, value="01/09/2026")
    item = dict(ORDERS[0]["items"][0])
    return [
        ("CalendarPicker",   lambda: gui.CalendarPicker(root, var)),
        ("_PresetRowDialog", lambda: gui._PresetRowDialog(
            root, "Preset", [("Name", "name", ""), ("Code", "code", "")])),
        ("_GDModelEditor",   lambda: gui._GDModelEditor(root, "GD-100")),
        ("CompressorFilterDialog", lambda: gui.CompressorFilterDialog(root)),
        ("_ProgressDialog",  lambda: gui._ProgressDialog(root, "filter")),
        ("LineItemDialog",   lambda: gui.LineItemDialog(
            root, "Line Item", item, ["G4", "F7"], ["V-form", "Flat Panel"])),
        ("BagLineItemDialog", lambda: gui.BagLineItemDialog(
            root, "Bag Item", {"pockets": 6, "width": 592}, ["G4"])),
        ("CatalogueLineDialog", lambda: gui.CatalogueLineDialog(
            root, "Add Product",
            {"Product Type": "Bag Filter", "Description": "Bag 592 6P",
             "Quantity": 8, "Unit Price": 47.25},
            gui.product_type_names(),
            lambda term: [{"part_number": "BAG-592-6P",
                           "name": "Bag filter 592x592 6 pocket",
                           "unit_price": 47.25}])),
        ("JobNumberHighlighter", lambda: gui.JobNumberHighlighter(root)),
        ("CustomerNameHighlighter",
         lambda: gui.CustomerNameHighlighter(root)),
        # An order that matched nobody, which is the state the picker exists
        # for. The suggestions are built the way the app builds them, so the
        # divider between "likely" and "everybody else" gets drawn for real.
        ("CustomerPicker", lambda: gui.CustomerPicker(
            root, CUSTOMERS, "Bells Creek Pty Ltd",
            "1 Filter Rd, Caloundra QLD 4551",
            _suggestions("Bells Creek Pty Ltd", "1 Filter Rd, Caloundra"))),
        ("_UnknownMediaDialog", lambda: gui._UnknownMediaDialog(
            root, "Mystery Media", ["G4", "F7"])),
        ("POReviewDialog",   lambda: gui.POReviewDialog(
            root, [{"header": dict(ORDERS[0]["header"]),
                    "items": [dict(i) for i in ORDERS[0]["items"]],
                    "source": "phone", "sent_by": "smoke@taf.local"}],
            ["G4", "F7"], ["V-form", "Flat Panel"])),
        # Drawn with a real quote on it, delivery included, so the totals
        # block and an unpriced row are both actually laid out.
        ("CounterDisplay", lambda: _counter_with_a_quote(gui, root)),
        # The bell at every count that draws differently: nothing, one
        # digit, two digits, and past 99 where it has to say "99+".
        ("NotificationBell", lambda: _bells(gui, root)),
        ("NotificationsPanel", lambda: gui.NotificationsPanel(
            root, [{"id": "n1", "title": "URGENT: Tape - 50mm foil",
                    "body": "Dave asked for 3 rolls. Out on bench 2",
                    "created_at": "2026-09-24T01:00:00Z", "read_at": None},
                   {"id": "n2", "title": "Rivets", "body": "Amy asked for "
                    "1 box", "created_at": "2026-09-23T01:00:00Z",
                    "read_at": "2026-09-23T02:00:00Z"}])),
        ("NotificationsPanel (empty)",
         lambda: gui.NotificationsPanel(root, [])),
        # Two screens found, so the radio list, the fill box and the
        # drag-it-yourself option are all laid out for real.
        ("ScreenChooser", lambda: gui.ScreenChooser(root, _two_screens())),
        # And the case that actually happens on most PCs: one screen, which
        # is the branch that has to still offer a way through.
        ("ScreenChooser (one screen)",
         lambda: gui.ScreenChooser(root, _two_screens()[:1], guessed=True)),
        ("QuoteDialog",      lambda: gui.QuoteDialog(
            root, dict(ORDERS[0]["header"]), _quote_lines(), CUSTOMERS[0],
            "Smoke Test")),
        # An order with one line planned by hand into areas, and one left
        # to the automatic plan, so both halves of the window are drawn.
        ("PackingDialog", lambda: _packing_window(gui, root)),
        ("FilterCalculatorDialog", lambda: gui.FilterCalculatorDialog(
            root, dict(ORDERS[0]["items"][0], Calculator={
                "wire": {"pieces": [{"cut_width_mm": 585,
                                     "cut_length_mm": 1062,
                                     "pieces_per_filter": 2}],
                         "installed": "full_blank"},
                "components": [{"name": "clips", "kg_per_filter": 0.05}]}),
            _calc_settings(), on_save=lambda inputs: None)),
        ("WeightsSettingsDialog", lambda: gui.WeightsSettingsDialog(
            root, editable=True)),
        ("WeightsSettingsDialog (read only)",
         lambda: gui.WeightsSettingsDialog(root, editable=False)),
        ("CChannelTableDialog", lambda: gui.CChannelTableDialog(root)),
        ("MergeCustomersDialog", lambda: _merge_window(gui, root)),
    ]


def _calc_settings():
    from taf_order_app import calc_settings
    return calc_settings.defaults()


def _packing_window(gui, root):
    from taf_order_app import order_packing
    items = [dict(i) for i in ORDERS[0]["items"]]
    items[0]["Packing"] = order_packing.set_manual(
        items[0], [6, 6], groups=[{"name": "Area A", "quantity": 6},
                                  {"name": "Area B", "quantity": 6}],
        group_of_wrap=["Area A", "Area B"])
    row = {"db_id": "o1", "source": "db", "order_no": "PO-8842",
           "customer": "Bells Creek", "db_header": dict(ORDERS[0]["header"])}
    dlg = gui.PackingDialog(root, row, dict(ORDERS[0]["header"]), items)
    dlg.lines.selection_set("1")
    dlg._show_line()
    return dlg


def _merge_window(gui, root):
    dlg = gui.MergeCustomersDialog(root)
    dlg.chosen = [CUSTOMERS[0]["id"], CUSTOMERS[1]["id"]]
    dlg._draw_compare()
    return dlg


def _bells(gui, root):
    """A window holding four bells, one per way the badge can be drawn."""
    win = gui.tk.Toplevel(root)
    for n, want in ((0, ""), (1, "1"), (12, "12"), (150, "99+")):
        bell = gui.NotificationBell(win)
        bell.pack(side="left", padx=4)
        bell.set_count(n)
        assert bell.badge == want, f"{n} unread drew {bell.badge!r}"
        # Nothing unread is a quiet bell; anything unread is a red one.
        drawn = []
        for i in bell.find_all():
            for opt in ("outline", "fill"):
                try:
                    drawn.append(str(bell.itemcget(i, opt)))
                except Exception:
                    pass            # a line has no outline, text no outline
        red = any(c.upper() == gui.NotificationBell.RED for c in drawn)
        assert red == bool(n), f"{n} unread: red={red}"
        # The number has to sit inside its badge, and the badge inside the
        # bell's own box. Guessed widths once let "99+" spill out of both
        # ends - it looked fine to the count check and wrong to anyone who
        # looked at it.
        box = bell._badge_box
        if n:
            left, _top, right, _bottom = box
            assert bell._badge_text_width < right - left, \
                f"{want!r} is wider than its badge"
            assert left >= 0 and right <= int(bell.cget("width")), \
                f"the badge for {want!r} runs off the edge"
        else:
            assert box is None, "a badge was drawn with nothing unread"
    return win


def _two_screens():
    from taf_order_app import monitors
    return monitors.parse_xrandr(
        "eDP-1 connected primary 1920x1080+0+0 (normal) 1mm x 1mm\n"
        "HDMI-1 connected 1920x1080+1920+0 (normal) 1mm x 1mm\n")


def _counter_with_a_quote(gui, root):
    win = gui.CounterDisplay(root)
    lines = _quote_lines()
    # One line nothing could price, because that row is drawn differently
    # and is the one a customer is most likely to ask about.
    lines.append({"part_number": "", "description": "Special frame - to spec",
                  "quantity": 1, "unit_price": 0, "line_total": 0,
                  "source": ""})
    win.show(lines, 45.0, "Bells Creek")
    return win


def _suggestions(po_name, po_address):
    from taf_order_app import db
    return db.suggest_customers(po_name, po_address,
                                [dict(c) for c in CUSTOMERS])


def _quote_lines():
    from taf_order_app import pricing
    return pricing.quote_lines(ORDERS[0]["items"],
                               {"PPF50-1.8-G4": 48.5, "FPF48-0.24-F7": 12.0})


def _exports(app, gui):
    """The file-writing paths, run for real into the throwaway folder."""
    from taf_order_app import backup, pricing, delivery
    out = Path(_TEMP) / "exports"
    out.mkdir(parents=True, exist_ok=True)

    def _backup():
        path, problems = backup.build_backup(out)
        assert Path(path).exists(), "the backup zip was not written"

    def _invoice():
        rows, missing = pricing.invoice_for_order(
            dict(ORDERS[0]["header"]), ORDERS[0]["items"], CUSTOMERS[0],
            {"PPF50-1.8-G4": 48.5, "FPF48-0.24-F7": 12.0})
        assert rows, "an order that is fully priced produced no invoice lines"
        pricing.write_xero_csv(out / "xero.csv", rows)

    def _labels():
        from taf_order_app import labels
        path, problems = labels.build_label_sheet(
            out / "labels.pdf",
            [{"name": "G4 media roll", "sku": "TAF-G4-ROLL",
              "location": "Rack A1", "unit": "m2"},
             {"name": "No code", "sku": "", "location": "", "unit": "each"}],
            start_at=3)
        assert Path(path).exists(), "the label sheet was not written"
        assert any("no SKU" in p for p in problems), \
            "an item with no SKU should be reported, not silently blank"

    def _delivery_dockets():
        from taf_order_app import dockets
        # One customer collecting two orders, which is the case the docket
        # exists for — and it has to come out as one docket, not two.
        rows = [dict(ORDERS[0], customer="Bells Creek", order_no="PO-8842",
                     location="Pick Up"),
                dict(ORDERS[2], customer="Bells Creek", order_no="PO-9100",
                     location="Pick Up")]
        built = dockets.build_dockets(
            dockets.group_by_customer(rows),
            lambda o: next((list(x["items"]) for x in ORDERS
                            if x.get("order_no") == o["order_no"]), []))
        assert len(built) == 1, f"{len(built)} dockets for one customer"
        assert built[0]["order_count"] == 2
        path = dockets.build_dockets_pdf(out / "dockets.pdf", built)
        assert Path(path).exists(), "the dockets were not written"

    def _worksheet_barcode():
        import pdf_generator
        from reportlab.pdfgen import canvas as rc
        from reportlab.lib.pagesizes import A4, landscape
        c = rc.Canvas(str(out / "bc.pdf"), pagesize=landscape(A4))
        assert pdf_generator.draw_order_barcode(c, "PO-8842") is True
        assert pdf_generator.draw_order_barcode(c, "") is False
        c.save()

    def _run_sheet():
        orders = [{"order_no": o["order_number"], "customer": o["customer_name"],
                   "date_due": o["date_due"], "status": o["header"].get("status"),
                   "db_header": o["header"], "n_items": o["n_items"]}
                  for o in ORDERS]
        delivery.build_run_sheet_pdf(
            str(out / "run.pdf"), delivery.group_by_region(
                delivery.ready_for_delivery(orders)))

    return [("backup.build_backup", _backup),
            ("pricing.invoice_for_order", _invoice),
            ("labels.build_label_sheet", _labels),
            ("pdf_generator.draw_order_barcode", _worksheet_barcode),
            ("delivery.build_run_sheet_pdf", _run_sheet),
            ("dockets.build_dockets_pdf", _delivery_dockets)]


def print_failures():
    if not FAILURES:
        print("\nSmoke test passed — every tab built, every dialog opened.")
        return
    print(f"\n{len(FAILURES)} smoke failure(s):\n")
    for what, tb in FAILURES:
        print(f"── {what} " + "─" * max(0, 60 - len(what)))
        print(tb)


def run_all() -> int:
    """Run one pass per role, each in its own process.

    A Tk application is not something you can cleanly build twice in one
    interpreter — the toolkit, the imported module and the settings file all
    keep state — so each role gets a fresh one.
    """
    import subprocess
    # The five-minute watchdog is for one role's run. This process only
    # waits on them, each with its own limit, so it must not be the one
    # that gives up first - it would end the run before the stuck role
    # could say where it was stuck.
    faulthandler.cancel_dump_traceback_later()
    worst = 0
    for role in ROLES:
        print(f"\n{'=' * 62}\n  smoke test — {role}\n{'=' * 62}",
              flush=True)
        try:
            result = subprocess.run([sys.executable, __file__, role],
                                    timeout=ROLE_LIMIT)
            code = result.returncode
        except subprocess.TimeoutExpired:
            print(f"FAIL: the {role} run did not finish in {ROLE_LIMIT}s",
                  flush=True)
            code = 1
        worst = max(worst, code)
    print("\nSmoke test failed." if worst else "\nSmoke test passed for every role.")
    return worst


if __name__ == "__main__":
    # A Windows console is cp1252, which has no box-drawing characters: the
    # report of a failure must never be the thing that fails.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg in ROLES:
        sys.exit(run(arg))
    if arg:
        print(f"Unknown role {arg!r} — expected one of {', '.join(ROLES)}.")
        sys.exit(2)
    sys.exit(run_all())
