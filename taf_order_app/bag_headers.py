"""Headers on bag filters, and the worksheet page each one gets.

A header is the frame a bag filter hangs from, made in the workshop like any
other framed filter, so it gets its own worksheet page alongside the
order's filters.

The sizes, as the workshop makes them:

  * header = bag - 15 each way, 25 mm deep. A 610 x 610 bag takes a
    595 x 595 x 25 header.
  * A Custom Bag Filter is ordered by its header size - "855mm x 570mm x 5
    pockets" is an 855 x 570 header - so its header starts at the size given.
  * wire = header - 15 each way, and only on a wire header (the bag is on
    wire). 595 x 595 takes 580 x 580; 855 x 570 takes 840 x 555.

The header and the wire are both editable on the line: the office can nudge
either a few millimetres without touching the bag, and the edited size is
what is kept.

Nothing here touches Tk or the database.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

BAG_TO_HEADER = 15          # header is this much smaller than the bag
HEADER_TO_WIRE = 15         # wire is this much smaller than the header
HEADER_DEPTH = 25           # mm, unless the line says otherwise

CUSTOM_BAG = "Custom Bag Filter"

# Bag types a header can go on: every bag filter, not frames, rolls or pads.
HEADER_BAG_TYPES = ("3-Peak", "2-Wedge", "4-Point", "MPHE 8-Pocket",
                    "MPHE 4-Pocket", "HEPA", CUSTOM_BAG)


def _int(value) -> int:
    try:
        return int(round(float(str(value).strip())))
    except (TypeError, ValueError):
        return 0


def default_header(product_type: str, width, height,
                   depth=None) -> Optional[Tuple[int, int, int]]:
    """The header the workshop makes for a bag of this size, or None when
    the bag has no size yet. `depth` is the header's own depth (25 unless
    said)."""
    w, h = _int(width), _int(height)
    d = _int(depth) or HEADER_DEPTH
    if w <= 0 or h <= 0:
        return None
    if product_type != CUSTOM_BAG:
        w, h = w - BAG_TO_HEADER, h - BAG_TO_HEADER
    if w <= 0 or h <= 0:
        return None
    return (w, h, d)


def header_size(bag: Dict[str, Any]) -> Optional[Tuple[int, int, int]]:
    """(width, height, depth) of a bag line's header, or None when it has
    none. A size edited on the line wins over the worked-out one."""
    if not bag.get("header"):
        return None
    w, h = _int(bag.get("header_width")), _int(bag.get("header_height"))
    d = _int(bag.get("header_depth")) or HEADER_DEPTH
    if w > 0 and h > 0:
        return (w, h, d)
    return default_header(bag.get("product_type", ""), bag.get("width"),
                          bag.get("height"), d)


def wire_size(header: Tuple[int, int, int]) -> Tuple[int, int]:
    w, h = header[0], header[1]
    return (max(0, w - HEADER_TO_WIRE), max(0, h - HEADER_TO_WIRE))


def has_wire(bag: Dict[str, Any]) -> bool:
    """A wire header filter: the bag is on wire."""
    return bool(bag.get("on_wire"))


def default_wire(bag: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    """The wire the workshop cuts for a bag on wire: its header less 15
    each way - the header it has, or the one it would have."""
    size = header_size(bag) if bag.get("header") else default_header(
        bag.get("product_type", ""), bag.get("width"), bag.get("height"))
    return wire_size(size) if size else None


def bag_wire(bag: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    """(width, height) of a bag's wire, or None when it is not on wire. A
    size set on the line wins over the worked-out one."""
    if not has_wire(bag):
        return None
    w, h = _int(bag.get("wire_width")), _int(bag.get("wire_height"))
    if w > 0 and h > 0:
        return (w, h)
    return default_wire(bag)


def wire_text(bag: Dict[str, Any]) -> str:
    """"Wire 580x580" for a bag on wire; "" otherwise."""
    size = bag_wire(bag)
    return f"Wire {size[0]}x{size[1]}" if size else ""


def extras_text(bag: Dict[str, Any]) -> str:
    """Header and wire, for a bag line: "Header 595x595x25mm, wire 580x580",
    or just "Wire 580x580" for a bag on wire with no header."""
    if bag.get("header"):
        return header_text(bag)
    return wire_text(bag)


def is_edited(bag: Dict[str, Any]) -> bool:
    """True when the line's header is not the worked-out size."""
    size = header_size(bag)
    if size is None:
        return False
    auto = default_header(bag.get("product_type", ""), bag.get("width"),
                          bag.get("height"), size[2])
    return auto is None or tuple(auto[:2]) != tuple(size[:2]) \
        or size[2] != HEADER_DEPTH


def header_text(bag: Dict[str, Any]) -> str:
    """"Header 595x595x25mm, wire 580x580" for dockets and the items list;
    "" with no header."""
    size = header_size(bag)
    if size is None:
        return "Header" if bag.get("header") else ""
    text = f"Header {size[0]}x{size[1]}x{size[2]}mm"
    wire = bag_wire(bag)
    if wire:
        text += f", wire {wire[0]}x{wire[1]}"
    return text


def bag_words(bag: Dict[str, Any]) -> str:
    """What the bag is, short: "2 x 610x610x570 3-Peak F7"."""
    qty = _int(bag.get("quantity")) or 1
    pt = bag.get("product_type", "") or "bag"
    media = (bag.get("media") or "").upper()
    w, h, d = (_int(bag.get(k)) for k in ("width", "height", "depth"))
    size = "x".join(str(v) for v in (w, h, d) if v)
    pockets = _int(bag.get("pockets"))
    extra = f" {pockets} pockets" if pockets else ""
    return " ".join(p for p in (f"{qty} x", size, pt + extra, media) if p)


def header_line(bag: Dict[str, Any], page: int = 0) -> Optional[Dict[str, Any]]:
    """The worksheet line that makes this bag's headers, or None.

    It is drawn like a framed filter - marks, channel, calculator - with the
    wire cut the header takes and no media. `page` is the bag's own page,
    for the note that ties the two together.
    """
    size = header_size(bag)
    if size is None:
        return None
    w, h, d = size
    qty = _int(bag.get("quantity")) or 1
    line: Dict[str, Any] = {
        "item_kind":    "filter",
        "Filter Type":  "Header",
        "Media Type":   "",
        "Quantity":     qty,
        "Short":        min(w, h),
        "Long":         max(w, h),
        "Channel":      d,
        "Bag Header":   True,
        "Notes":        (f"HEADER FOR {bag_words(bag).upper()}"
                         + (f" (PAGE {page})" if page else "")),
    }
    wire = bag_wire(bag)
    if wire:
        ww, wh = wire
        line["Header Wire Cut"] = f"{min(ww, wh)}*{max(ww, wh)}"
        line["Header Wire Qty"] = qty
    else:
        line["Header Wire Cut"] = ""
        line["Header Wire Qty"] = ""
    if bag.get("item_job"):
        line["item_job"] = bag["item_job"]
    return line


def is_header_line(item: Dict[str, Any]) -> bool:
    return bool(item.get("Bag Header"))


def worksheet_split(items: List[Dict[str, Any]]):
    """(filter pages, bag lines, total pages) for printing an order.

    The filter worksheet gets a header page after the filters for each bag
    that has a header; the bag docket follows them. Header pages count in
    the page total ("page 4 of 9").
    """
    filters = [i for i in items if i.get("item_kind", "filter") != "bag"]
    bags = [i for i in items if i.get("item_kind") == "bag"]
    with_header = [b for b in bags if header_size(b) is not None]
    first_bag_page = len(filters) + len(with_header) + 1
    headers = []
    for idx, bag in enumerate(bags):
        line = header_line(bag, first_bag_page + idx)
        if line is not None:
            headers.append(line)
    return filters + headers, bags, len(items) + len(headers)
