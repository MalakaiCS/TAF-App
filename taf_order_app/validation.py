
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime
from typing import Iterable, Tuple, Optional

VALID_FILTER_TYPES = ["V-form", "Flat Panel", "Stepped Filter", "Flyscreen", "Header"]
VALID_MEDIA_TYPES = ["G4", "180", "WASH", "F5", "GREY", "E-MESH"]

def parse_date(date_str: str) -> Optional[datetime]:
    """Return datetime if valid date format; otherwise None."""
    date_str = (date_str or "").strip()
    for fmt in ("%d/%m/%y", "%d-%m-%y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None

# What the worksheet cannot be printed without. Location is on every sheet.
HEADER_REQUIRED = ("Customer Name", "Order Number", "Date Ordered",
                   "Location")
DATE_HINT = "Use dd/mm/yy, like 16/10/26"


def header_problems(header: dict) -> list:
    """Everything wrong with an order's header that would stop its
    worksheets printing, as (field, message) - all of them, in words that
    say what to change. Empty when it will print.

    Checked before anything is printed, so a bad date is caught before the
    delivery labels go out without their worksheets."""
    out = []
    for k in HEADER_REQUIRED:
        if not str(header.get(k, "") or "").strip():
            out.append((k, f"{k} is empty."))
    ordered = str(header.get("Date Ordered", "") or "").strip()
    if ordered and not parse_date(ordered):
        out.append(("Date Ordered", f'Date Ordered "{ordered}" is not a '
                                    f"real date. {DATE_HINT}."))
    due = str(header.get("Date Due", "") or "").strip()
    if due and due.lower() != "asap" and not parse_date(due):
        out.append(("Date Due", f'Date Due "{due}" is not a real date. '
                                f"{DATE_HINT}, or ASAP."))
    return out


def validate_header(header: dict) -> None:
    problems = header_problems(header)
    if problems:
        raise ValueError(problems[0][1])

def validate_items(items: Iterable[dict], extra_media_types: list = None,
                   extra_filter_types: list = None) -> None:
    valid_media = VALID_MEDIA_TYPES + [m for m in (extra_media_types or []) if m not in VALID_MEDIA_TYPES]
    valid_filter = VALID_FILTER_TYPES + [f for f in (extra_filter_types or []) if f not in VALID_FILTER_TYPES]
    items = list(items)
    if not items:
        raise ValueError("At least one line item is required.")

    for idx, item in enumerate(items, start=1):
        # Numeric
        for key in ["Quantity", "Short", "Long", "Channel"]:
            try:
                int(str(item.get(key, "")).strip())
            except Exception:
                raise ValueError(f"Line item {idx}: '{key}' must be a whole number.")

        # Lists
        ft = (item.get("Filter Type") or "").strip()
        if ft not in valid_filter:
            raise ValueError(f"Line item {idx}: 'Filter Type' is invalid.")

        mt = (item.get("Media Type") or "").strip()
        # A bag's header page has no media of its own: the bag is the media.
        if item.get("Bag Header") and not mt:
            continue
        if mt not in valid_media:
            raise ValueError(f"Line item {idx}: 'Media Type' is invalid.")
