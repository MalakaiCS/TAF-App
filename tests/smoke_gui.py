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

import inspect
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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

CUSTOMERS = [
    {"id": "c1", "name": "Bells Creek", "legal_name": "Bells Creek Pty Ltd",
     "email": "orders@bellscreek.example", "phone": "07 5555 0000",
     "region": "Sunshine Coast", "active": True,
     "delivery_address1": "1 Filter Rd", "delivery_city": "Caloundra",
     "delivery_state": "QLD", "delivery_postcode": "4551"},
    {"id": "c2", "name": "CAS - Tweed", "email": "po@cas.example",
     "region": "Local", "active": True},
]

OVERRIDES = {
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
}

# Rights are a real fork in what gets built: a manager sees the stock-alert
# card and live buttons, everyone else sees the same buttons disabled. Those
# are different code paths and both have shipped broken, so the test runs the
# whole thing once as each.
PERMISSIONS = ("can_manage_stock_alerts", "can_manage_prices",
               "can_manage_customers", "can_manage_stock", "can_manage_staff",
               "can_edit_catalog", "can_view_audit_log", "is_approved",
               "is_manager", "is_admin")

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
        if inspect.isfunction(value) or inspect.isbuiltin(value):
            default = _default_for(value)
            def stub(*a, _d=default, **k):
                return _d() if callable(_d) else _d
            stub.__name__ = name
            cache[name] = stub
            return stub
        return value        # constants, classes, exception types


def install_stubs(manager: bool = True):
    """Swap in the stand-in database and silence anything that would block."""
    import taf_order_app
    from taf_order_app import db as real_db
    stub = StubDB(real_db, manager=manager)
    sys.modules["taf_order_app.db"] = stub
    taf_order_app.db = stub

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
        try:
            step()
        except Exception as exc:
            _fail(label, exc)
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
    """Everything the smoke test does, in order, one event-loop tick apart."""
    steps: list[tuple[str, object]] = []

    def add(label, fn):
        steps.append((label, fn))

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

    def _account():
        # A menu, so nothing new is packed — this checks it builds at all.
        app._account_menu()
    add("menu: account", _account)

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
        ("_UnknownMediaDialog", lambda: gui._UnknownMediaDialog(
            root, "Mystery Media", ["G4", "F7"])),
        ("POReviewDialog",   lambda: gui.POReviewDialog(
            root, [{"header": dict(ORDERS[0]["header"]),
                    "items": [dict(i) for i in ORDERS[0]["items"]],
                    "source": "phone", "sent_by": "smoke@taf.local"}],
            ["G4", "F7"], ["V-form", "Flat Panel"])),
        ("QuoteDialog",      lambda: gui.QuoteDialog(
            root, dict(ORDERS[0]["header"]), _quote_lines(), CUSTOMERS[0],
            "Smoke Test")),
    ]


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
            ("delivery.build_run_sheet_pdf", _run_sheet)]


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
    worst = 0
    for role in ROLES:
        print(f"\n{'=' * 62}\n  smoke test — {role}\n{'=' * 62}")
        result = subprocess.run([sys.executable, __file__, role])
        worst = max(worst, result.returncode)
    print("\nSmoke test failed." if worst else "\nSmoke test passed for every role.")
    return worst


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg in ROLES:
        sys.exit(run(arg))
    if arg:
        print(f"Unknown role {arg!r} — expected one of {', '.join(ROLES)}.")
        sys.exit(2)
    sys.exit(run_all())
