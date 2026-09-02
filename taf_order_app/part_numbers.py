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

# Filter types that build their code from media and thickness:
#     FPF{MEDIA}{thickness}-{SQM}   /   PPF{MEDIA}{thickness}-{SQM}
PART_NUMBER_PREFIXES = {
    "flat panel": "FPF",
    "v-form":     "PPF",
    # A header IS a flat panel — one made to sit on top of a bag filter — so
    # it is coded as one rather than left without a part number.
    "header":     "FPF",
}

# Types whose code is fixed — they are only ever made one way, so neither the
# media nor the thickness varies and the whole stem is a constant.
FIXED_PART_NUMBER_STEMS = {
    "stepped filter": "STPPFW50",   # always 50mm, always 180 media
    "flyscreen":      "FPF09",      # always the 9mm flyscreen channel
}

# The one media that changes a fixed-stem code. E-mesh is only ever used on a
# flyscreen, and a flyscreen made in it takes an -M on the end:
#     FPF09-040   ->   FPF09-040-M
# Keyed on the media name with punctuation stripped, so "E-MESH", "E-Mesh" and
# "EMESH" all match.
FIXED_STEM_MEDIA_SUFFIX = {
    ("flyscreen", "EMESH"): "-M",
}

# A header is a standard flat panel made to sit on top of a bag filter. The
# panel is larger than the bag face it covers:
HEADER_PANEL_FOR_BAG = {
    (595, 595): (610, 610),
    (610, 610): (630, 630),
}
HEADER_PANEL_THICKNESS = 25

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

# ── Filter types ─────────────────────────────────────────────────────────────
# A purchase order calls a V-form whatever the person writing it calls one:
# "V Filter", "Vee bank", "pleated panel". They all mean the same thing on the
# bench, so they are all read as the same thing here. Keys are the wording with
# punctuation and spaces stripped, so "V-Filter", "v filter" and "VFILTER" all
# land on the same entry.
FILTER_TYPE_WORDINGS = {
    # V-form / pleated panel
    "vform": "V-form",          "vfilter": "V-form",       "vfilters": "V-form",
    "veeform": "V-form",        "veefilter": "V-form",     "vbank": "V-form",
    "veebank": "V-form",        "vtype": "V-form",         "vpleat": "V-form",
    "vpanel": "V-form",         "vcell": "V-form",
    "pleatedpanel": "V-form",   "pleatedpanelfilter": "V-form",
    "pleatedfilter": "V-form",  "pleated": "V-form",       "pleat": "V-form",
    "ppf": "V-form",            "pleatpack": "V-form",
    # Flat panel
    "flatpanel": "Flat Panel",      "flatpanelfilter": "Flat Panel",
    "panel": "Flat Panel",          "panelfilter": "Flat Panel",
    "flatfilter": "Flat Panel",     "flat": "Flat Panel",
    "fpf": "Flat Panel",            "filterpad": "Flat Panel",
    "pad": "Flat Panel",            "padfilter": "Flat Panel",
    "washablepanel": "Flat Panel",
    # Stepped
    "stepped": "Stepped Filter",    "steppedfilter": "Stepped Filter",
    "stepfilter": "Stepped Filter", "step": "Stepped Filter",
    "stppf": "Stepped Filter",      "stppfw50": "Stepped Filter",
    # Flyscreen
    "flyscreen": "Flyscreen",       "flyscreens": "Flyscreen",
    "flyscren": "Flyscreen",        "insectscreen": "Flyscreen",
    "meshscreen": "Flyscreen",      "screen": "Flyscreen",
    "emesh": "Flyscreen",           "expandedmesh": "Flyscreen",
    # Header
    "header": "Header",             "headerpanel": "Header",
}

# A stepped filter is a 40mm V-form with a 9mm flyscreen fixed to it, and it is
# only ever made that way — so it is always 50mm overall, whatever a purchase
# order says. That 50 is the 50 in STPPFW50.
STEPPED_THICKNESS = 50

# Thicknesses that mean a V-form even when the document didn't say so. 45 and
# 50 are only ever V-form; anything thicker is too deep for a flat panel.
VFORM_THICKNESSES = (45, 50)


def wording_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def canonical_filter_type(written: str, extra_types=None, learned=None) -> str:
    """The filter type a document's wording means, or "" if it means nothing.

    Anything already spelled the way the app spells it — including a filter
    type someone added themselves — comes straight back. `learned` holds the
    wordings staff have corrected before, keyed the same way, and is consulted
    ahead of the built-in table so a correction always wins.
    """
    written = (written or "").strip()
    if not written:
        return ""
    for name in list(extra_types or []) + ["V-form", "Flat Panel",
                                           "Stepped Filter", "Flyscreen", "Header"]:
        if written.lower() == str(name).lower():
            return str(name)
    key = wording_key(written)
    if learned:
        taught = learned.get(key)
        if taught:
            return str(taught)
    hit = FILTER_TYPE_WORDINGS.get(key)
    if hit:
        return hit
    # A custom type someone added, written with different punctuation.
    for name in (extra_types or []):
        if wording_key(str(name)) == key:
            return str(name)
    return ""


def filter_type_for_thickness(channel) -> str:
    """The filter type a thickness on its own implies, or "".

        9-11 mm   Flyscreen
        12-29 mm  Flat Panel
        45, 50 mm V-form  — only ever made as a V-form
        30 mm +   V-form
    """
    try:
        ch = int(str(channel).strip())
    except (TypeError, ValueError):
        return ""
    if ch in VFORM_THICKNESSES:
        return "V-form"
    if 9 <= ch <= 11:
        return "Flyscreen"
    if 12 <= ch <= 29:
        return "Flat Panel"
    if ch >= 30:
        return "V-form"
    return ""


def resolve_filter_type(item: Dict[str, Any], extra_types=None,
                        learned=None) -> str:
    """Settle a line's filter type, in place. Returns the type, or "".

    The wording on the order is trusted first, then the thickness. A line that
    says nothing recognisable and gives no usable thickness is left blank for
    someone to fill in, rather than guessed at.
    """
    if (item.get("item_kind") or "filter") == "bag":
        return ""
    written = (item.get("Filter Type") or "").strip()
    ftype = canonical_filter_type(written, extra_types, learned)
    if not ftype:
        ftype = filter_type_for_thickness(item.get("Channel"))
    if ftype:
        item["Filter Type"] = ftype
    # A stepped filter is always 50mm overall — the 40mm V-form plus its 9mm
    # flyscreen. Orders quote it as 40, 45 or 50; the worksheet wants 50.
    if ftype == "Stepped Filter":
        item["Channel"] = STEPPED_THICKNESS
    return ftype


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
    ftype = (item.get("Filter Type") or "").strip().lower()

    nominal = nominal_square_metres(effective_area(item))
    if nominal <= 0:
        return ""

    # Fixed-stem types first: only made one way, so nothing varies but the area
    # (and, for a flyscreen in e-mesh, a trailing -M).
    stem = FIXED_PART_NUMBER_STEMS.get(ftype)
    if stem:
        media_key = re.sub(r"[^A-Za-z0-9]", "", item.get("Media Type") or "").upper()
        tail = FIXED_STEM_MEDIA_SUFFIX.get((ftype, media_key), "")
        return f"{stem}-{sqm_suffix(nominal)}{tail}"

    prefix = PART_NUMBER_PREFIXES.get(ftype)
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

    return f"{prefix}{code}{thickness}-{sqm_suffix(nominal)}"


def header_panel_for_bag(width, height, half_size: bool = False):
    """The flat panel a bag filter's header is made from.

    A 595 x 595 bag takes a 610 x 610 x 25 panel, a 610 x 610 bag takes
    630 x 630 x 25. A half-size bag takes half that panel.

    Returns (width, height, thickness) or None when the bag face isn't one of
    the sizes we have a header for — better to say nothing than to invent a
    size for something that gets cut.
    """
    try:
        w, h = int(width or 0), int(height or 0)
    except (TypeError, ValueError):
        return None
    panel = HEADER_PANEL_FOR_BAG.get((w, h)) or HEADER_PANEL_FOR_BAG.get((h, w))
    if not panel:
        return None
    pw, ph = panel
    if half_size:
        ph = int(round(ph / 2))
    return (pw, ph, HEADER_PANEL_THICKNESS)


def header_panel_item(bag: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The flat-panel line a bag's header corresponds to, or None.

    Used to show what the header is and to give it its own part number; the
    bag itself keeps its own code with the H suffix.
    """
    if not bag.get("header"):
        return None
    size = header_panel_for_bag(bag.get("width"), bag.get("height"),
                                half_size=bool(bag.get("half_size")))
    if not size:
        return None
    w, h, t = size
    return {
        "item_kind":   "filter",
        "Filter Type": "Flat Panel",
        "Media Type":  DEFAULT_MEDIA,
        "Quantity":    bag.get("quantity", 1),
        "Short":       min(w, h),
        "Long":        max(w, h),
        "Channel":     t,
    }


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


def apply_media_rules(item: Dict[str, Any], known_media, learned=None) -> str:
    """Settle a line's media, and say whether a human still needs to decide.

    Returns "" when the media is settled, or the unrecognised grade as written
    when it is not on the list — the caller asks whether to add it or swap it
    for one that is, rather than quietly picking either.

    `learned` holds grades staff have already swapped, keyed by wording. A
    grade that has been decided once is not asked about again.
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
        taught = (learned or {}).get(wording_key(media))
        if taught and str(taught).strip().lower() in allowed:
            item["Media Type"] = str(taught).strip()
            return ""
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
