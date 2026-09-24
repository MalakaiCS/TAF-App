"""
Export everything the business runs on into one dated zip of CSVs.

The point is not a second copy of the database — Supabase already keeps that.
The point is that the data is readable without the app, without an account,
and without Supabase still existing: spreadsheets, on a drive the business
owns, that anyone can open. A backup you cannot read on the worst day of the
year is not a backup.

CSV, not JSON, for the same reason: the person who needs it may be an
accountant with Excel, not a developer with a terminal.
"""
from __future__ import annotations

import csv
import datetime as _dt
import io
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from . import db as _db

# Order header fields worth a column of their own. Anything else in the header
# JSON still travels — see _extra_header_columns — it just isn't promoted.
ORDER_COLUMNS = [
    "order_number", "customer_name", "order_type", "date_ordered", "date_due",
    "status", "location", "job", "priority", "printed", "printed_at",
    "line_count", "created_at", "created_by", "created_by_role", "notes",
]

LINE_LEAD_COLUMNS = ["order_number", "customer_name", "date_ordered", "line_no"]


def _s(value: Any) -> str:
    """A cell. Lists and dicts are flattened rather than dumped as Python."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (list, tuple)):
        return " | ".join(_s(v) for v in value)
    if isinstance(value, dict):
        return " | ".join(f"{k}: {_s(v)}" for k, v in value.items())
    return str(value)


def order_rows(orders: Iterable[Dict[str, Any]]) -> Tuple[List[str],
                                                          List[Dict[str, str]]]:
    """One row per order, with the header JSON flattened into columns."""
    orders = list(orders or [])
    extra = _extra_header_columns(orders)
    columns = ORDER_COLUMNS + extra
    rows = []
    for o in orders:
        header = o.get("header") or {}
        notes = header.get("order_notes") or []
        row = {
            "order_number":    _s(o.get("order_number")),
            "customer_name":   _s(o.get("customer_name")),
            "order_type":      _s(o.get("order_type")),
            "date_ordered":    _s(o.get("date_ordered")),
            "date_due":        _s(o.get("date_due")),
            "status":          _s(header.get("status") or "Pending"),
            "location":        _s(header.get("Location")),
            "job":             _s(header.get("Job")),
            "priority":        _s(bool(header.get("priority"))),
            "printed":         _s(bool(header.get("printed"))),
            "printed_at":      _s(header.get("printed_at")),
            "line_count":      _s(o.get("n_items")
                                  if o.get("n_items") is not None
                                  else len(o.get("items") or [])),
            "created_at":      _s(o.get("created_at")),
            "created_by":      _s(o.get("full_name") or o.get("username")
                                  or o.get("user_email")),
            "created_by_role": _s(o.get("created_by_role")),
            "notes":           _s(header.get("Notes")),
        }
        if notes:
            row["notes"] = (row["notes"] + "\n" if row["notes"] else "") + _s(notes)
        for key in extra:
            row[key] = _s(header.get(key))
        rows.append(row)
    return columns, rows


def _extra_header_columns(orders: Sequence[Dict[str, Any]]) -> List[str]:
    """Header keys not already promoted, so nothing is silently dropped."""
    known = {"status", "Location", "Job", "priority", "printed", "printed_at",
             "Notes", "order_notes"}
    seen: List[str] = []
    for o in orders:
        for key in (o.get("header") or {}):
            if key not in known and key not in seen:
                seen.append(key)
    return sorted(seen)


def line_rows(orders: Iterable[Dict[str, Any]]) -> Tuple[List[str],
                                                         List[Dict[str, str]]]:
    """One row per line item. Filters and bag filters describe themselves with
    different fields, so the columns are the union of what is actually there —
    an empty cell beats a lost measurement."""
    orders = list(orders or [])
    keys: List[str] = []
    for o in orders:
        for item in (o.get("items") or []):
            for k in item:
                if k not in keys and not k.startswith("_"):
                    keys.append(k)
    columns = LINE_LEAD_COLUMNS + keys
    rows = []
    for o in orders:
        for i, item in enumerate(o.get("items") or [], start=1):
            row = {
                "order_number":  _s(o.get("order_number")),
                "customer_name": _s(o.get("customer_name")),
                "date_ordered":  _s(o.get("date_ordered")),
                "line_no":       str(i),
            }
            for k in keys:
                row[k] = _s(item.get(k))
            rows.append(row)
    return columns, rows


def table_rows(records: Iterable[Dict[str, Any]],
               drop: Sequence[str] = ()) -> Tuple[List[str],
                                                  List[Dict[str, str]]]:
    """Any list of records as a table, columns in first-seen order.

    `drop` is for things that must not leave the database — a portal token is
    a password in all but name, and a backup gets emailed around.
    """
    records = list(records or [])
    drop = set(drop)
    columns: List[str] = []
    for r in records:
        for k in r:
            if k not in columns and k not in drop:
                columns.append(k)
    return columns, [{k: _s(r.get(k)) for k in columns} for r in records]


def _csv_bytes(columns: Sequence[str], rows: Sequence[Dict[str, str]]) -> bytes:
    """A CSV as bytes. utf-8-sig so Excel opens accented names correctly."""
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=list(columns), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8-sig")


# Each section: (file name, label, source name, what to fetch, how to shape it).
# Fetching is separated from shaping so a section that fails — an older
# database missing a table — costs that one file and not the whole backup.
# The source name is what lets orders be downloaded once and written twice.

def _sections() -> List[Tuple[str, str, str, Callable[[], Any],
                              Callable[[Any], Tuple[List[str], List[Dict[str, str]]]]]]:
    return [
        ("orders.csv", "Orders", "orders",
         lambda: _db.get_all_orders(),
         order_rows),
        ("order_lines.csv", "Order lines", "orders",
         lambda: _db.get_all_orders(),
         line_rows),
        ("customers.csv", "Customers", "customers",
         lambda: _db.get_customers("", active_only=False),
         lambda d: table_rows(d, drop=("portal_token",))),
        ("quotes.csv", "Quotes", "quotes",
         lambda: _db.get_quotes(limit=100000),
         lambda d: table_rows(d, drop=("token",))),
        ("stock.csv", "Stock", "stock",
         lambda: _db.get_stock_items(),
         table_rows),
        ("prices.csv", "Price list", "prices",
         lambda: _db.get_price_rows("", limit=0),
         table_rows),
        ("audit_log.csv", "Audit log", "audit",
         lambda: _db.get_audit_log(limit=100000),
         table_rows),
    ]


README = """TAF Order Entry - backup taken {when}

Every file here is a plain CSV. Double-click one to open it in Excel, or
import it into anything else - nothing in this folder needs the app.

  orders.csv       one row per order, with its status, dates and who took it
  order_lines.csv  one row per line on an order - the actual filters
  customers.csv    the customer list, with delivery addresses and contacts
  quotes.csv       every quote and what became of it
  stock.csv        stock items and their levels at the time of the backup
  prices.csv       the price list
  audit_log.csv    who did what, and when

Sign-in details are NOT in here, and neither are the tokens that open a
customer's portal link - those stay in the database on purpose.

Keep this somewhere that is not the office PC. A backup that burns down with
the building has not backed anything up.
{problems}"""


def build_backup(dest_dir, when: Optional[_dt.datetime] = None,
                 progress: Optional[Callable[[str], None]] = None) -> Tuple[str, List[str]]:
    """Write a dated zip of CSVs into `dest_dir`.

    Returns (path, problems). A section that could not be read is named in
    `problems` and in the zip's README rather than failing the whole backup -
    a partial backup is worth having, but only if it says what it is missing.
    """
    when = when or _dt.datetime.now()
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"TAF-backup-{when.strftime('%Y-%m-%d_%H%M')}.zip"

    problems: List[str] = []
    # Orders are fetched once and shaped twice; they are the expensive read.
    cache: Dict[str, Any] = {}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, label, source, fetch, shape in _sections():
            if progress:
                progress(label)
            try:
                if source not in cache:
                    cache[source] = fetch()
                columns, rows = shape(cache[source])
                z.writestr(name, _csv_bytes(columns, rows))
            except Exception as exc:
                problems.append(f"{label}: {exc}")
        note = ("\nNOT INCLUDED - these could not be read:\n"
                + "\n".join(f"  {p}" for p in problems)) if problems else ""
        z.writestr("README.txt",
                   README.format(when=when.strftime("%d/%m/%Y %I:%M %p"),
                                 problems=note))
    return str(path), problems
