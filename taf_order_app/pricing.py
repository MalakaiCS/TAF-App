"""
Prices, quotes and the Xero hand-off.

A price is looked up in this order, and the first answer wins:

    1. The part number, in the imported price list. FPFG425-040 has a price;
       that is the price, whatever anything else says.
    2. A rate per square metre for that filter type and media, if one is set.
       0.20 m2 of G4 flat panel at $34/m2 is $6.80.
    3. Nothing. The line is quoted at zero and flagged, never guessed at —
       a made-up price on a quote goes out to a customer under TAF's name.

Reading price spreadsheets is deliberately forgiving about column names,
because the files come from several places and none of them agree on
"Part No" vs "Code" vs "SKU".
"""
from __future__ import annotations

import csv
import datetime as _dt
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import part_numbers as _pn

# ── Reading a price file ─────────────────────────────────────────────────────

CODE_HEADINGS = ("part number", "part no", "partno", "part", "code",
                 "item code", "itemcode", "sku", "product code", "item",
                 "product", "stock code", "catalogue number")
PRICE_HEADINGS = ("price", "unit price", "sell", "sell price", "rate",
                  "amount", "each", "unit amount", "list price", "ex gst",
                  "unit cost", "cost")
DESC_HEADINGS = ("description", "desc", "details", "name", "product name")


def _norm_heading(text: Any) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(text or "").lower()).strip()


def _money(value: Any) -> Optional[float]:
    """A number from a cell that may be '$12.50', '12.50 ea' or 12.5."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[^0-9.\-]", "", str(value))
    if not text or text in ("-", "."):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _pick_columns(row: Iterable[Any]) -> Optional[Dict[str, int]]:
    """Which columns of a header row hold the code, price and description."""
    cells = [_norm_heading(c) for c in row]
    found: Dict[str, int] = {}
    for idx, cell in enumerate(cells):
        if not cell:
            continue
        if "code" not in found and cell in CODE_HEADINGS:
            found["code"] = idx
        elif "price" not in found and cell in PRICE_HEADINGS:
            found["price"] = idx
        elif "desc" not in found and cell in DESC_HEADINGS:
            found["desc"] = idx
    # Fall back to a looser match so "Sell Price (ex GST)" still lands.
    if "code" not in found or "price" not in found:
        for idx, cell in enumerate(cells):
            if not cell:
                continue
            if "code" not in found and any(h in cell for h in CODE_HEADINGS):
                found["code"] = idx
            if "price" not in found and any(h in cell for h in PRICE_HEADINGS):
                found["price"] = idx
            if "desc" not in found and any(h in cell for h in DESC_HEADINGS):
                found["desc"] = idx
    if "code" in found and "price" in found:
        return found
    return None


def _rows_from_csv(path: Path) -> List[List[Any]]:
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        return [row for row in csv.reader(f)]


def _rows_from_excel(path: Path) -> List[List[Any]]:
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True, read_only=True)
    rows: List[List[Any]] = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            rows.append(list(row))
    wb.close()
    return rows


def read_price_file(path) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Read one price spreadsheet. Returns (rows, problems).

    Every sheet in a workbook is read, and the header row is found rather
    than assumed to be the first — these files usually open with a title and
    a blank line or two.
    """
    path = Path(path)
    problems: List[str] = []
    try:
        raw = (_rows_from_csv(path) if path.suffix.lower() in (".csv", ".txt")
               else _rows_from_excel(path))
    except Exception as exc:
        return [], [f"{path.name}: could not be opened ({exc})"]

    out: List[Dict[str, Any]] = []
    cols: Optional[Dict[str, int]] = None
    for row in raw:
        if not row or all(c in (None, "") for c in row):
            continue
        maybe = _pick_columns(row)
        if maybe:
            cols = maybe          # a new sheet or section starts here
            continue
        if not cols:
            continue
        def _cell(name):
            i = cols.get(name)
            return row[i] if i is not None and i < len(row) else None
        code = str(_cell("code") or "").strip()
        price = _money(_cell("price"))
        if not code or price is None:
            continue
        if not re.search(r"[0-9]", code):
            continue              # a section heading, not a part number
        out.append({
            "part_number": code.upper(),
            "description": str(_cell("desc") or "").strip(),
            "unit_price":  round(price, 4),
        })

    if not out and not problems:
        problems.append(
            f"{path.name}: no priced rows found — the sheet needs a heading "
            "row with a part-number column and a price column.")
    # Later rows win, so a corrected price further down the file is the one kept.
    deduped: Dict[str, Dict[str, Any]] = {}
    for row in out:
        deduped[row["part_number"]] = row
    return list(deduped.values()), problems


def read_price_files(paths) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Read several price files into one list, later files winning."""
    merged: Dict[str, Dict[str, Any]] = {}
    problems: List[str] = []
    for p in paths:
        rows, probs = read_price_file(p)
        problems.extend(probs)
        for row in rows:
            merged[row["part_number"]] = row
    return list(merged.values()), problems


# ── Pricing a line ───────────────────────────────────────────────────────────

def _rate_key(filter_type: str, media: str) -> str:
    return f"{_pn.wording_key(filter_type)}|{_pn.wording_key(media)}"


def price_for_item(item: Dict[str, Any],
                   prices: Optional[Dict[str, float]] = None,
                   rates: Optional[Dict[str, float]] = None) -> Tuple[float, str]:
    """The unit price for one line, and where it came from.

    Returns ``(unit_price, source)`` where source is "list", "rate" or "" —
    an empty source means nothing priced it and the line needs a human.
    """
    part = (item.get("Part Number") or "").strip().upper()
    if part and prices:
        listed = prices.get(part)
        if listed is not None:
            return (round(float(listed), 4), "list")

    if rates:
        ftype = (item.get("Filter Type") or "").strip()
        media = (item.get("Media Type") or "").strip()
        rate = rates.get(_rate_key(ftype, media))
        if rate is None:
            rate = rates.get(_rate_key(ftype, ""))   # any media
        if rate is not None:
            area = _pn.nominal_square_metres(_pn.effective_area(item))
            if area > 0:
                return (round(float(rate) * area, 4), "rate")
    return (0.0, "")


def quote_lines(items: Iterable[Dict[str, Any]],
                prices: Optional[Dict[str, float]] = None,
                rates: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
    """Price every line of an order. Unpriced lines are kept, marked."""
    out: List[Dict[str, Any]] = []
    for it in items or []:
        try:
            qty = max(0, int(str(it.get("Quantity") or 0).strip()))
        except (TypeError, ValueError):
            qty = 0
        unit, source = price_for_item(it, prices, rates)
        out.append({
            "part_number": (it.get("Part Number") or "").strip().upper(),
            "description": describe_item(it),
            "quantity":    qty,
            "unit_price":  unit,
            "line_total":  round(unit * qty, 2),
            "source":      source,
            "item":        it,
        })
    return out


def describe_item(item: Dict[str, Any]) -> str:
    """The line as it should read on a quote or an invoice.

    Plain ASCII throughout: this text goes into a Xero import as well as onto
    a quote, and an accounting import is the wrong place to find out how a
    piece of punctuation is decoded.
    """
    if (item.get("item_kind") or "filter") == "bag":
        bits = [str(item.get("Filter Type") or "Bag Filter")]
        dims = " x ".join(str(item.get(k)) for k in ("width", "height")
                          if item.get(k))
        if dims:
            bits.append(dims + "mm")
        pockets = item.get("pockets")
        if pockets:
            bits.append(f"{pockets} pocket")
        return " - ".join(bits)

    bits = [str(item.get("Filter Type") or "Filter")]
    media = str(item.get("Media Type") or "").strip()
    if media:
        bits.append(media)
    s, l, c = item.get("Short"), item.get("Long"), item.get("Channel")
    if s and l:
        bits.append(f"{s} x {l} x {c or '?'}mm")
    area = _pn.nominal_square_metres(_pn.effective_area(item))
    if area > 0:
        bits.append(f"{area:.2f} m2")
    return " - ".join(bits)


def quote_totals(lines: Iterable[Dict[str, Any]],
                 gst_rate: float = 0.10) -> Dict[str, float]:
    """Subtotal, GST and total for a set of quote lines."""
    subtotal = round(sum(l.get("line_total", 0) for l in lines), 2)
    gst = round(subtotal * gst_rate, 2)
    return {"subtotal": subtotal, "gst": gst,
            "total": round(subtotal + gst, 2)}


def unpriced(lines: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The lines nothing could price — what a quote must not go out with."""
    return [l for l in lines if not l.get("source")]


# ── Xero ─────────────────────────────────────────────────────────────────────
# Xero's own sales-invoice import format. Its column names and order are what
# Xero expects; changing them breaks the import, so they are written verbatim.

XERO_COLUMNS = [
    "*ContactName", "EmailAddress", "POAddressLine1", "POAddressLine2",
    "POAddressLine3", "POAddressLine4", "POCity", "PORegion", "POPostalCode",
    "POCountry", "*InvoiceNumber", "Reference", "*InvoiceDate", "*DueDate",
    "InventoryItemCode", "*Description", "*Quantity", "*UnitAmount",
    "Discount", "*AccountCode", "*TaxType", "TrackingName1", "TrackingOption1",
    "TrackingName2", "TrackingOption2", "Currency", "BrandingTheme",
]

# Xero rejects an import outright if a date is in the wrong shape.
XERO_DATE = "%d/%m/%Y"


def _xero_date(value: str, fallback: Optional[_dt.date] = None) -> str:
    from .validation import parse_date
    dt = parse_date(value or "")
    if dt:
        return dt.strftime(XERO_DATE)
    return (fallback or _dt.date.today()).strftime(XERO_DATE)


def xero_rows(header: Dict[str, Any], lines: Iterable[Dict[str, Any]],
              customer: Optional[Dict[str, Any]] = None,
              account_code: str = "200",
              tax_type: str = "GST on Income",
              due_days: int = 30) -> List[Dict[str, str]]:
    """One row per priced line, in Xero's sales-invoice import shape.

    Xero repeats the invoice-level fields on every line of the same invoice,
    which is why the contact and dates appear on each row.
    """
    customer = customer or {}
    invoice_no = (header.get("Order Number") or "").strip()
    issued = _xero_date(header.get("Date Ordered") or "")
    due_raw = (header.get("Date Due") or "").strip()
    if due_raw and due_raw.lower() != "asap":
        due = _xero_date(due_raw)
    else:
        issued_dt = _dt.datetime.strptime(issued, XERO_DATE).date()
        due = (issued_dt + _dt.timedelta(days=due_days)).strftime(XERO_DATE)

    contact = ((customer.get("legal_name") or "").strip()
               or (customer.get("name") or "").strip()
               or (header.get("Customer Name") or "").strip())

    rows: List[Dict[str, str]] = []
    for line in lines:
        if line.get("quantity", 0) <= 0:
            continue
        rows.append({
            "*ContactName":      contact,
            "EmailAddress":      (customer.get("email") or "").strip(),
            "POAddressLine1":    (customer.get("delivery_address1") or "").strip(),
            "POAddressLine2":    (customer.get("delivery_address2") or "").strip(),
            "POAddressLine3":    "",
            "POAddressLine4":    "",
            "POCity":            (customer.get("delivery_city") or "").strip(),
            "PORegion":          (customer.get("delivery_state") or "").strip(),
            "POPostalCode":      (customer.get("delivery_postcode") or "").strip(),
            "POCountry":         (customer.get("delivery_country") or "").strip(),
            "*InvoiceNumber":    invoice_no,
            "Reference":         (header.get("Job") or "").strip(),
            "*InvoiceDate":      issued,
            "*DueDate":          due,
            "InventoryItemCode": line.get("part_number", ""),
            "*Description":      line.get("description", ""),
            "*Quantity":         str(line.get("quantity", 0)),
            "*UnitAmount":       f'{line.get("unit_price", 0):.2f}',
            "Discount":          "",
            "*AccountCode":      account_code,
            "*TaxType":          tax_type,
            "TrackingName1":     "Region" if (header.get("Location") or "").strip() else "",
            "TrackingOption1":   (header.get("Location") or "").strip(),
            "TrackingName2":     "",
            "TrackingOption2":   "",
            "Currency":          "AUD",
            "BrandingTheme":     "",
        })
    return rows


def write_xero_csv(path, rows: Iterable[Dict[str, str]]) -> str:
    """Write Xero import rows to a CSV. Returns the path written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=XERO_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)
    return str(path)
