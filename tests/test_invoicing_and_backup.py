"""Invoicing a finished order, backing everything up, and the speed changes.

These are the parts where a mistake is expensive rather than annoying: an
invoice that quietly drops a line bills the customer short, a backup that
quietly drops a table isn't a backup, and a paged query that stops at a
thousand rows loses the oldest orders without saying so.
"""
from __future__ import annotations

import datetime
import io
import tempfile
import zipfile
from pathlib import Path

from taf_order_app import backup, pricing


# ── Fixtures ─────────────────────────────────────────────────────────────────

HEADER = {
    "Customer Name": "Bells Creek", "Order Number": "PO-8842",
    "Date Ordered": "01/09/2026", "Date Due": "15/09/2026",
    "Location": "Sunshine Coast", "Job": "AHU 3", "status": "Dispatched",
}

ITEMS = [
    {"item_kind": "filter", "Filter Type": "V-form", "Media Type": "G4",
     "Short": 595, "Long": 595, "Channel": 50, "Quantity": "12",
     "Part Number": "PPF50-1.8-G4"},
    {"item_kind": "filter", "Filter Type": "Flat Panel", "Media Type": "F7",
     "Short": 495, "Long": 495, "Channel": 48, "Quantity": "4",
     "Part Number": "NOT-IN-THE-LIST"},
]

PRICES = {"PPF50-1.8-G4": 48.5}

CUSTOMER = {"legal_name": "Bells Creek Pty Ltd", "name": "Bells Creek",
            "email": "orders@bellscreek.example",
            "delivery_address1": "1 Filter Rd", "delivery_city": "Caloundra",
            "delivery_state": "QLD", "delivery_postcode": "4551"}


# ── Invoicing ────────────────────────────────────────────────────────────────

def test_an_unpriced_line_is_reported_not_dropped_silently():
    """The line has to come back to the caller, or the customer is billed
    short and nobody finds out until they compare it to the docket."""
    rows, missing = pricing.invoice_for_order(HEADER, ITEMS, CUSTOMER, PRICES)
    assert len(rows) == 1
    assert len(missing) == 1
    assert missing[0]["part_number"] == "NOT-IN-THE-LIST"


def test_the_invoice_carries_the_customers_billing_details():
    rows, _ = pricing.invoice_for_order(HEADER, ITEMS, CUSTOMER, PRICES)
    row = rows[0]
    assert row["*ContactName"] == "Bells Creek Pty Ltd"   # legal name, not trading
    assert row["EmailAddress"] == "orders@bellscreek.example"
    assert row["POCity"] == "Caloundra"
    assert row["*Quantity"] == "12"
    assert row["*UnitAmount"] == "48.50"


def test_dates_go_out_in_the_shape_xero_accepts():
    rows, _ = pricing.invoice_for_order(HEADER, ITEMS, CUSTOMER, PRICES)
    # Australian order, not American: 01/09/2026 is September, and Xero
    # rejects the import outright if the shape is wrong.
    assert rows[0]["*InvoiceDate"] == "01/09/2026"
    assert rows[0]["*DueDate"] == "15/09/2026"


def test_a_due_date_of_asap_becomes_a_real_date():
    header = dict(HEADER, **{"Date Due": "ASAP"})
    rows, _ = pricing.invoice_for_order(header, ITEMS, CUSTOMER, PRICES)
    assert rows[0]["*DueDate"] == "01/10/2026"           # 30 days on


def test_the_reference_does_not_repeat_the_invoice_number():
    # Default: the invoice is numbered with their PO, so repeating it in the
    # reference would just read "PO PO-8842".
    rows, _ = pricing.invoice_for_order(HEADER, ITEMS, CUSTOMER, PRICES)
    assert rows[0]["Reference"] == "AHU 3"
    # Given our own invoice number, their PO is what they will search for.
    rows, _ = pricing.invoice_for_order(HEADER, ITEMS, CUSTOMER, PRICES,
                                        invoice_number="INV-1001")
    assert rows[0]["*InvoiceNumber"] == "INV-1001"
    assert rows[0]["Reference"] == "PO PO-8842 - AHU 3"


def test_one_of_our_own_order_numbers_is_not_offered_as_their_reference():
    """TAF-ON-0007 means something to us and nothing to them."""
    header = dict(HEADER, **{"Order Number": "TAF-ON-0007"})
    rows, _ = pricing.invoice_for_order(header, ITEMS, CUSTOMER, PRICES)
    assert rows[0]["*InvoiceNumber"] == "TAF-ON-0007"
    assert rows[0]["Reference"] == "AHU 3"


def test_a_whole_run_writes_one_file_xero_splits_by_invoice_number():
    second = dict(HEADER, **{"Order Number": "PO-9001", "Job": "AHU 4"})
    rows = (pricing.invoice_for_order(HEADER, ITEMS, CUSTOMER, PRICES)[0]
            + pricing.invoice_for_order(second, ITEMS, CUSTOMER, PRICES)[0])
    with tempfile.TemporaryDirectory() as tmp:
        path = pricing.write_xero_csv(Path(tmp) / "run.csv", rows)
        text = Path(path).read_text(encoding="utf-8-sig")
    assert text.count("PO-8842") == 1 and text.count("PO-9001") == 1
    assert text.splitlines()[0].startswith("*ContactName")


def test_the_xero_columns_are_exactly_what_xero_asks_for():
    # Renaming or reordering these breaks the import with no useful message.
    assert pricing.XERO_COLUMNS[0] == "*ContactName"
    assert pricing.XERO_COLUMNS[10] == "*InvoiceNumber"
    assert len(pricing.XERO_COLUMNS) == 27


# ── Backup ───────────────────────────────────────────────────────────────────

ORDERS = [
    {"order_number": "PO-8842", "customer_name": "Bells Creek",
     "order_type": "filter", "date_ordered": "01/09/2026",
     "created_at": "2026-09-01T02:00:00Z", "full_name": "Kai",
     "header": {"status": "Dispatched", "Location": "Local", "Job": "AHU 3",
                "priority": True, "Notes": "call on arrival",
                "Contact": "Dave"},
     "items": [dict(ITEMS[0], _review_note="ignore me"), dict(ITEMS[1])]},
    {"order_number": "TAF-ON-0002", "customer_name": "CAS - Tweed",
     "header": {}, "items": []},
]


def _rows(text: str):
    import csv
    return list(csv.DictReader(io.StringIO(text)))


def test_every_order_and_every_line_survives_the_backup():
    columns, rows = backup.order_rows(ORDERS)
    assert len(rows) == 2
    assert rows[0]["order_number"] == "PO-8842"
    assert rows[0]["status"] == "Dispatched"
    assert rows[0]["line_count"] == "2"

    columns, lines = backup.line_rows(ORDERS)
    assert len(lines) == 2
    assert lines[0]["Part Number"] == "PPF50-1.8-G4"
    assert lines[0]["order_number"] == "PO-8842"        # traceable to its order
    assert "_review_note" not in columns                # review scratch, not data


def test_a_header_field_nobody_thought_of_still_makes_it_out():
    """A backup that only knows today's fields loses tomorrow's."""
    columns, rows = backup.order_rows(ORDERS)
    assert "Contact" in columns
    assert rows[0]["Contact"] == "Dave"


def test_booleans_read_as_words_not_python():
    _, rows = backup.order_rows(ORDERS)
    assert rows[0]["priority"] == "Yes"
    assert rows[0]["printed"] == "No"


def test_tokens_are_left_out_of_the_backup():
    """A portal token is a password. A backup gets emailed around."""
    columns, rows = backup.table_rows(
        [{"name": "Bells Creek", "email": "a@b.c", "portal_token": "SECRET"}],
        drop=("portal_token",))
    assert "portal_token" not in columns
    assert all("SECRET" not in v for v in rows[0].values())


def test_a_section_that_fails_is_named_rather_than_failing_the_backup(monkey=None):
    from taf_order_app import db as _db
    real = {}
    for name, value in (("get_all_orders", lambda *a, **k: ORDERS),
                        ("get_customers", lambda *a, **k: []),
                        ("get_quotes", lambda *a, **k: []),
                        ("get_stock_items", lambda *a, **k: []),
                        ("get_price_rows", lambda *a, **k: [])):
        real[name] = getattr(_db, name, None)
        setattr(_db, name, value)

    def boom(*a, **k):
        raise RuntimeError("relation audit_log does not exist")
    real["get_audit_log"] = getattr(_db, "get_audit_log", None)
    _db.get_audit_log = boom
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path, problems = backup.build_backup(
                tmp, when=datetime.datetime(2026, 9, 3, 14, 5))
            assert Path(path).name == "TAF-backup-2026-09-03_1405.zip"
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                readme = z.read("README.txt").decode("utf-8")
                orders_csv = z.read("orders.csv").decode("utf-8-sig")
        # The one that failed is missing, everything else is there, and the
        # README says which - a partial backup that lies is worse than none.
        assert "audit_log.csv" not in names
        assert "orders.csv" in names and "order_lines.csv" in names
        assert len(problems) == 1 and "Audit log" in problems[0]
        assert "NOT INCLUDED" in readme and "audit_log" in readme
        assert _rows(orders_csv)[0]["order_number"] == "PO-8842"
    finally:
        for name, value in real.items():
            if value is not None:
                setattr(_db, name, value)


def test_the_backup_opens_in_excel_without_mangling_names():
    # utf-8-sig: without the byte-order mark Excel reads UTF-8 as Latin-1 and
    # turns a name like Beneš into mojibake.
    data = backup._csv_bytes(["name"], [{"name": "Beneš"}])
    assert data.startswith(b"\xef\xbb\xbf")
    assert "Beneš" in data.decode("utf-8-sig")


# ── Speed ────────────────────────────────────────────────────────────────────

def _perf_sql():
    return (Path(__file__).resolve().parent.parent
            / "migrate_performance.sql").read_text(encoding="utf-8")


def test_the_order_list_view_keeps_row_level_security():
    """A view owned by postgres hands out every row regardless of policy."""
    sql = _perf_sql()
    assert "WITH (security_invoker = true)" in sql
    assert "GRANT SELECT ON public.orders_list TO authenticated;" in sql
    assert "TO anon" not in sql


def test_the_order_list_view_counts_the_lines_without_sending_them():
    sql = _perf_sql()
    assert "jsonb_array_length" in sql
    view = sql.split("CREATE OR REPLACE VIEW")[1].split("FROM public.orders")[0]
    assert " o.items" not in view          # the lines stay in the database


def test_the_indexes_match_the_expressions_the_app_actually_searches_on():
    # An index on order_number is not used by a query on
    # lower(btrim(order_number)); it has to be the same expression.
    sql = _perf_sql()
    assert "lower(btrim(COALESCE(order_number, '')))" in sql
    assert "lower(btrim(COALESCE(customer_name, '')))" in sql
    assert "lower(btrim(COALESCE(email, '')))" in sql


def test_the_media_usage_function_cannot_be_called_by_the_public():
    sql = _perf_sql()
    assert "SECURITY INVOKER" in sql
    assert "SET search_path = public, pg_temp" in sql
    assert "REVOKE ALL ON FUNCTION public.media_usage_since(date) FROM public;" in sql
    assert "TO authenticated;" in sql


def test_queries_page_past_the_thousand_row_limit():
    """PostgREST stops at 1000 rows. Past a thousand orders the oldest simply
    stopped appearing, with no error to notice."""
    from taf_order_app import db as _db
    import inspect
    source = inspect.getsource(_db)
    assert "def _page_through" in source
    for fn in ("get_all_orders", "get_order_list", "get_price_rows"):
        body = source.split(f"def {fn}(")[1].split("\ndef ")[0]
        assert "_page_through" in body, f"{fn} still fetches one unpaged page"


def test_the_phone_shrinks_a_photo_before_sending_it():
    page = (Path(__file__).resolve().parent.parent
            / "docs" / "phone" / "index.html").read_text(encoding="utf-8")
    assert "createImageBitmap" in page and "toBlob" in page
    assert "MAX_EDGE = 2000" in page
    # A PDF or anything that isn't an image must go up untouched.
    assert 'if (!/^image\\//.test(file.type || "")) { return fallback; }' in page
    # And several at once, rather than one after another.
    assert "worker(), worker(), worker()" in page
    # The marker the app waits for is still written last, after the photos.
    assert page.index("_complete.json") > page.index("await Promise.all")


def test_the_inbox_sweep_skips_batches_this_pc_already_read():
    from taf_order_app import db as _db, po_import
    import inspect
    assert "skip" in inspect.signature(_db.list_po_inbox_batches).parameters
    source = inspect.getsource(po_import.fetch_new_batches)
    assert "skip=already" in source
    assert "_download_photos" in source
    assert "ThreadPoolExecutor" in inspect.getsource(po_import._download_photos)
