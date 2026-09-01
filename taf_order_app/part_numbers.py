"""
Square metres, part numbers and delivery regions.

Every filter line carries a part number and its square metreage. Both are
derived here rather than typed, so the same panel always produces the same
code no matter who keys the order.

    Flat Panel     FPF{MEDIA}{thickness}-{SQM}
    V-form         PPF{MEDIA}{thickness}-{SQM}   (pleated panel)

    150 x 750 x 25mm Carbon
      -> 0.15m x 0.75m = 0.1125 m2
      -> rounded up to the next 0.1  = 0.20 m2
      -> FPFCARB25-020
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, Optional

# Filter types that get an automatic part number, and the prefix each uses.
# Stepped Filter, Flyscreen and Header have no agreed format yet, so they are
# left blank and flagged rather than given a guessed code.
PART_NUMBER_PREFIXES = {
    "flat panel": "FPF",
    "v-form":     "PPF",
}

# Thicknesses flat panels are normally made in. Anything else still produces a
# part number, but is worth a second look.
STANDARD_FLAT_THICKNESSES = (10, 15, 20, 25)

# Delivery regions. Location on an order is one of these, never a street
# address — the descriptions are what the reader is told to match against.
REGIONS = {
    "Sunshine Coast": "Anywhere in the Sunshine Coast area.",
    "North":          "Any suburb north of the Brisbane River.",
    "Local":          "Within a 15km radius of 19 Trade Link Road, Hillcrest.",
    "Gold Coast":     "Anywhere in the Gold Coast area.",
    "Logan":          "The Loganholme and Springwood area.",
    "Ipswich":        "The Ipswich area.",
    "Freight":        "Any suburb outside all of the regions above.",
    "Pick Up":        "The customer has said they will collect the order.",
}
REGION_NAMES = list(REGIONS)

DEFAULT_MEDIA = "G4"
STEPPED_MEDIA = "180"


def default_media_code(media: str) -> str:
    """A starting part-number code for a media type: letters and digits only,
    upper case, first four characters. 'Carbon' -> 'CARB', 'G4' -> 'G4'.

    Only a seed — the real code is whatever is set against the media type, so
    anything this gets wrong is corrected once in Settings.
    """
    cleaned = re.sub(r"[^A-Za-z0-9]", "", media or "").upper()
    return cleaned[:4]


def media_code(media: str, codes: Optional[Dict[str, str]] = None) -> str:
    """The part-number code for a media type, falling back to the default."""
    if codes:
        explicit = (codes.get(media) or codes.get((media or "").upper()) or "").strip()
        if explicit:
            return re.sub(r"[^A-Za-z0-9]", "", explicit).upper()
    return default_media_code(media)


def square_metres(short_mm, long_mm) -> float:
    """True face area in square metres. 0.0 when either side is unknown."""
    try:
        s = float(short_mm or 0)
        l = float(long_mm or 0)
    except (TypeError, ValueError):
        return 0.0
    if s <= 0 or l <= 0:
        return 0.0
    return (s / 1000.0) * (l / 1000.0)


def nominal_square_metres(area: float) -> float:
    """Area rounded UP to the next 0.1 m2 — how the panel is charged and coded.

    0.1125 -> 0.2, and an exact 0.2 stays 0.2. Rounded before the ceiling so
    floating-point noise on an exact multiple can't push it up a whole step.
    """
    try:
        a = float(area or 0)
    except (TypeError, ValueError):
        return 0.0
    if a <= 0:
        return 0.0
    return math.ceil(round(a * 10, 6)) / 10.0


def sqm_suffix(nominal: float) -> str:
    """The square-metre part of a part number: 0.20 -> '020', 1.5 -> '150'."""
    return f"{int(round((nominal or 0) * 100)):03d}"


def format_sqm(area: float) -> str:
    """Square metreage as shown on a line item."""
    return f"{(area or 0):.2f}"


def part_number(item: Dict[str, Any],
                codes: Optional[Dict[str, str]] = None) -> str:
    """The part number for a filter line item, or "" if its type has no format.

    Returns "" rather than a partial code when a dimension or the media is
    missing — a half-formed part number is worse than an obviously absent one.
    """
    if (item.get("item_kind") or "filter") == "bag":
        return ""          # bag/roll items have their own generator
    prefix = PART_NUMBER_PREFIXES.get((item.get("Filter Type") or "").strip().lower())
    if not prefix:
        return ""

    code = media_code(item.get("Media Type") or "", codes)
    if not code:
        return ""

    try:
        thickness = int(str(item.get("Channel") or "").strip())
    except (TypeError, ValueError):
        return ""
    if thickness <= 0:
        return ""

    nominal = nominal_square_metres(effective_area(item))
    if nominal <= 0:
        return ""

    return f"{prefix}{code}{thickness}-{sqm_suffix(nominal)}"


def effective_area(item: Dict[str, Any]) -> float:
    """The line's area: worked out from its dimensions, or taken from the
    document when it gave an area (0.20) instead of sizes."""
    area = square_metres(item.get("Short"), item.get("Long"))
    if area > 0:
        return area
    try:
        return max(0.0, float(item.get("Stated Square Metres") or 0))
    except (TypeError, ValueError):
        return 0.0


def apply_media_rules(item: Dict[str, Any], known_media) -> str:
    """Settle a line's media, and say whether a human still needs to decide.

    Returns "" when the media is settled, or the unrecognised grade as written
    when it is not on the list — the caller asks whether to add it or swap it
    for one that is, rather than quietly picking either.
    """
    if (item.get("item_kind") or "filter") == "bag":
        return ""
    ftype = (item.get("Filter Type") or "").strip().lower()
    media = (item.get("Media Type") or "").strip()

    if ftype == "stepped filter":
        item["Media Type"] = STEPPED_MEDIA      # always 180
        return ""
    if not media:
        item["Media Type"] = DEFAULT_MEDIA      # unstated means G4
        return ""

    allowed = {str(m).strip().lower() for m in (known_media or [])}
    if allowed and media.lower() not in allowed:
        return media                            # e.g. F9 — ask the user
    return ""


def apply_derived_fields(item: Dict[str, Any],
                         codes: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Stamp square metreage and part number onto a filter line item.

    Called wherever an item is created or edited so the two always agree with
    the dimensions actually on the line.
    """
    if (item.get("item_kind") or "filter") == "bag":
        return item
    area = effective_area(item)
    item["Square Metres"] = round(area, 4)
    item["Nominal Square Metres"] = nominal_square_metres(area)
    item["Part Number"] = part_number(item, codes)
    return item


def needs_part_number(item: Dict[str, Any]) -> bool:
    """True when this line should have a part number but doesn't."""
    if (item.get("item_kind") or "filter") == "bag":
        return False
    if not PART_NUMBER_PREFIXES.get((item.get("Filter Type") or "").strip().lower()):
        return False
    return not (item.get("Part Number") or "").strip()


def nonstandard_thickness(item: Dict[str, Any]) -> bool:
    """Flat panel in a thickness we don't normally make — worth a check."""
    if (item.get("Filter Type") or "").strip().lower() != "flat panel":
        return False
    try:
        return int(str(item.get("Channel") or "").strip()) not in STANDARD_FLAT_THICKNESSES
    except (TypeError, ValueError):
        return False
