"""
TAF Order Entry — application package.

The worksheet builders reach for Excel and Word through COM, so importing
them costs a lot and only works on a Windows box with Office installed.
Importing them eagerly here meant that `taf_order_app.part_numbers` — a
module of arithmetic with no dependencies at all — could not be imported
without them, which put the rules that most need testing out of reach of a
test. So the heavy names are resolved on first use instead.

Every existing `from taf_order_app import OrderService` still works; it just
doesn't happen until something asks.
"""
from __future__ import annotations

_LAZY = {
    "OrderService":          ".order_service",
    "BAG_PRODUCT_TYPES":     ".bag_filler",
    "BAG_MEDIA_TYPES":       ".bag_filler",
    "ROLL_MEDIA_TYPES":      ".bag_filler",
    "ROLL_WIDTHS":           ".bag_filler",
    "ROLL_LENGTHS":          ".bag_filler",
    "MPHE_EFFICIENCIES":     ".bag_filler",
    "STANDARD_SIZES":        ".bag_filler",
    "generate_part_number":  ".bag_filler",
    "build_label_line":      ".bag_filler",
    "build_dims_line":       ".bag_filler",
    "item_summary_short":    ".bag_filler",
    "generate_bag_docket":   ".bag_filler",
    "generate_unified_docket": ".bag_filler",
}

__all__ = list(_LAZY)


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    value = getattr(importlib.import_module(module, __name__), name)
    globals()[name] = value      # only imported once
    return value


def __dir__():
    return sorted(set(globals()) | set(_LAZY))
