"""What a line says on the customer's invoice in Xero.

The worksheet is written for the workshop; the invoice is written for the
customer, and they want to read what they bought:

    Galvanised Pleated Panel Filter in G4
    Size: 595 x 595 x 45mm

So each kind of filter has a standard wording with blanks filled in from
the line. The wording is the company's - a manager changes it on the Xero
screen (Invoice wording) and every PC uses it - and any one line can say
something else instead (its "Xero description" on the work order). Neither
is printed on the worksheets.

A rule applies to a filter type (or a bag/roll product type) from a depth
upwards, so "V-form from 30mm" can read differently from a thinner one. The
deepest rule a line reaches wins. A line no rule covers keeps the plain
description the CSV export has always used.

Nothing here touches Tk or the database.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

CATALOG_KEY = "xero_wording"

PLACEHOLDERS = ("{Media}", "{Size}", "{Width}", "{Height}", "{Depth}",
                "{Filter Type}", "{Part Number}")

DEFAULT_RULES: List[Dict[str, Any]] = [
    {"filter_type": "Flyscreen", "min_depth": 0,
     "wording": "Flat Panel Flyscreen Filter in {Media}\nSize: {Size}"},
    {"filter_type": "Flat Panel", "min_depth": 0,
     "wording": "Galvanised Flat Panel Filters in {Media}\nSize: {Size}"},
    {"filter_type": "V-form", "min_depth": 30,
     "wording": "Galvanised Pleated Panel Filter in {Media}\nSize: {Size}"},
]

_current: Optional[List[Dict[str, Any]]] = None


def _key(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def _int(value: Any) -> int:
    try:
        return int(round(float(str(value).strip())))
    except (TypeError, ValueError):
        return 0


def clean(rules: Any) -> List[Dict[str, Any]]:
    """Rules as stored, made safe: each has a filter type and some wording.
    Anything else is dropped rather than trusted."""
    out: List[Dict[str, Any]] = []
    for r in rules if isinstance(rules, list) else []:
        if not isinstance(r, dict):
            continue
        ft = str(r.get("filter_type") or "").strip()
        wording = str(r.get("wording") or "").strip()
        if ft and wording:
            out.append({"filter_type": ft[:60],
                        "min_depth": max(0, _int(r.get("min_depth"))),
                        "wording": wording[:1000]})
    return out


def set_rules(value: Any) -> None:
    """What every PC uses, from the shared setting (None = the standard)."""
    global _current
    _current = clean(value) if isinstance(value, list) else None


def current() -> List[Dict[str, Any]]:
    return list(_current) if _current is not None else [dict(r) for r in DEFAULT_RULES]


def _dims(item: Dict[str, Any]):
    if (item.get("item_kind") or "filter") == "bag":
        return item.get("width"), item.get("height"), item.get("depth")
    return item.get("Short"), item.get("Long"), item.get("Channel")


def size_text(item: Dict[str, Any]) -> str:
    """"595 x 595 x 45mm" - as many of the sizes as the line has."""
    parts = [str(_int(v)) for v in _dims(item) if _int(v) > 0]
    return " x ".join(parts) + "mm" if parts else ""


def _type_of(item: Dict[str, Any]) -> str:
    return str(item.get("Filter Type") or item.get("product_type") or "").strip()


def rule_for(item: Dict[str, Any], rules: Optional[List[Dict[str, Any]]] = None):
    """The rule this line falls under: its type, the deepest one it reaches."""
    kind = _key(_type_of(item))
    depth = _int(_dims(item)[2])
    best = None
    for r in clean(rules if rules is not None else current()):
        if _key(r["filter_type"]) != kind or depth < r["min_depth"]:
            continue
        if best is None or r["min_depth"] > best["min_depth"]:
            best = r
    return best


def fill(wording: str, item: Dict[str, Any]) -> str:
    w, h, d = (_int(v) for v in _dims(item))
    values = {
        "Media": str(item.get("Media Type") or item.get("media") or "").strip(),
        "Size": size_text(item),
        "Width": str(w or ""), "Height": str(h or ""), "Depth": str(d or ""),
        "Filter Type": _type_of(item),
        "Part Number": str(item.get("Part Number") or item.get("part_number")
                           or "").strip(),
    }
    by_name = {k.lower(): v for k, v in values.items()}
    # {media} and {Media} alike; a blank nobody knows is left as typed, so a
    # mistake shows on the draft rather than vanishing.
    out = re.sub(r"\{([A-Za-z ]+)\}",
                 lambda m: by_name.get(m.group(1).strip().lower(), m.group(0)),
                 wording)
    # Tidy what an empty blank leaves behind ("in \n" -> "in").
    return "\n".join(line.rstrip() for line in out.splitlines()).strip()


def describe(item: Dict[str, Any],
             rules: Optional[List[Dict[str, Any]]] = None) -> str:
    """What this line says on the invoice."""
    own = str(item.get("Xero Description") or "").strip()
    if own:
        return own
    rule = rule_for(item, rules)
    if rule:
        return fill(rule["wording"], item)
    from .pricing import describe_item
    return describe_item(item)
