
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

def validate_header(header: dict) -> None:
    required = ["Customer Name", "Order Number", "Date Ordered", "Location"]
    for k in required:
        if not (header.get(k, "") or "").strip():
            raise ValueError(f"Header field '{k}' is required.")

    if not parse_date(header.get("Date Ordered", "")):
        raise ValueError("Date Ordered must be a valid date (dd/mm/yy or dd-mm-yy).")

    due = (header.get("Date Due", "") or "").strip()
    if due and due.lower() != "asap" and not parse_date(due):
        raise ValueError("Date Due must be a valid date, 'ASAP', or left empty.")

def validate_items(items: Iterable[dict], extra_media_types: list = None) -> None:
    valid_media = VALID_MEDIA_TYPES + [m for m in (extra_media_types or []) if m not in VALID_MEDIA_TYPES]
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
        if ft not in VALID_FILTER_TYPES:
            raise ValueError(f"Line item {idx}: 'Filter Type' is invalid.")

        mt = (item.get("Media Type") or "").strip()
        if mt not in valid_media:
            raise ValueError(f"Line item {idx}: 'Media Type' is invalid.")
