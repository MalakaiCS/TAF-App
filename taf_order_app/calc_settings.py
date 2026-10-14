"""The numbers the weight calculator, the packing planner and the labels share.

One set, held in the database (migrate_packing_labels.sql) and read by every
PC, the web app and the API alike. Each section is stored on its own row
with a version that goes up on every change, and every result says which
versions produced it - so a weight printed in March can be reproduced in
June even after somebody has re-weighed a roll in between.

What ships filled in is only what has actually been supplied or is already
in use in the program:

    materials            the wire rolls and media stock, as supplied
    handling_profiles    412 x 412 x 90: five to a wrap, as supplied
    max_bundle_kg        10 kg, including the wrapping
    required_components  what each kind of filter is made of
    company              the base address labels print as "From"

and everything that has not been supplied starts empty, on purpose:

    steel                density of the steel stock
    component_profiles   filter-frame channel, flyscreen frame
    brace_profiles       brace weight (with its fixings) and count
    mounting_frame_profiles
    packaging            what the wrapping itself weighs
    cut_profiles         beyond the worksheet's own formulas (see filter_calc)

An empty section is reported as missing wherever it matters. It is never
read as zero.
"""
from __future__ import annotations

import copy
import datetime as _dt
from typing import Any, Dict, Optional

from . import materials as _mat

BASE_ADDRESS_DEFAULT = ("Unit 1/19 Tradelink Road, Hillcrest Queensland 4118 "
                        "Australia")

COMPANY = {
    "name": "Total Air Filtration",
    "abn": "45 667 800 893",
    "phone": "07 3800 3448",
}

MAX_BUNDLE_KG = 10.0

# What each kind of filter is made of, and so what has to be known before a
# complete weight can be given. A pleat insert has no frame and a header has
# no wire or media of its own; those are handled where the line says so.
DEFAULT_REQUIRED_COMPONENTS = {
    "Flat Panel":     ["wire", "media"],
    "Header":         ["wire", "media"],
    "V-form":         ["wire", "media"],
    "Flyscreen":      ["media"],
    "Stepped Filter": ["wire", "media"],
}

# Parts added to the weight once somebody has entered what they weigh, and
# left out until then: a filter weighs its wire and media from the supplied
# rates without anybody having to enter anything first.
DEFAULT_COUNTED_IF_KNOWN = {
    "Flat Panel":     ["filter_frame", "braces"],
    "Header":         ["filter_frame", "braces"],
    "V-form":         ["filter_frame", "braces"],
    "Flyscreen":      ["flyscreen_frame", "braces"],
    "Stepped Filter": ["filter_frame", "flyscreen_part"],
}

# The wrapping's own weight until it is weighed: counted as nothing, so a
# wrap's weight is its filters'.
DEFAULT_PACKAGING = {"confirmed": True, "base_kg": 0.0,
                     "basis": "default - wrapping counted as 0 kg until "
                              "it is weighed"}

# Filters per wrap for a line whose weight cannot be worked out (a bag, a
# catalogue item) and whose size has no handling limit.
DEFAULT_MAX_PER_WRAP = 5

# Which wire a filter other than a V-form is made with (V-forms go by depth).
# Supplied: flat panels take the large wire. A header panel is a flat panel.
DEFAULT_WIRE_RULES = {"Flat Panel": "LARGE_WIRE", "Header": "LARGE_WIRE"}

DEFAULT_HANDLING_PROFILES = [{
    "id": "HANDLING-412x412x90",
    "version": 1,
    "verified": True,
    "match": {"width_mm": 412, "height_mm": 412, "depth_mm": 90},
    "max_per_wrap": 5,
    "source": "supplied: 412 x 412 x 90 filters are wrapped five at most",
}]

SECTIONS = (
    "materials", "steel", "cut_profiles", "component_profiles",
    "brace_profiles", "mounting_frame_profiles", "wire_rules",
    "required_components", "packaging", "handling_profiles",
    "max_bundle_kg", "shipping_rounding", "company",
)


def defaults() -> Dict[str, Any]:
    return {
        "materials": _mat.default_settings(),
        "steel": {"density_kg_m3": None, "basis": None,
                  "material": "galvanised steel stock", "version": None},
        "cut_profiles": [],
        "component_profiles": [],
        "brace_profiles": {},
        "mounting_frame_profiles": [],
        "wire_rules": copy.deepcopy(DEFAULT_WIRE_RULES),
        "required_components": copy.deepcopy(DEFAULT_REQUIRED_COMPONENTS),
        "counted_if_known": copy.deepcopy(DEFAULT_COUNTED_IF_KNOWN),
        "packaging": copy.deepcopy(DEFAULT_PACKAGING),
        "default_max_per_wrap": DEFAULT_MAX_PER_WRAP,
        "handling_profiles": copy.deepcopy(DEFAULT_HANDLING_PROFILES),
        "max_bundle_kg": MAX_BUNDLE_KG,
        "shipping_rounding": "none",
        "company": {"base_address": BASE_ADDRESS_DEFAULT},
        "versions": {},
    }


def merge(stored: Optional[Dict[str, Dict[str, Any]]]) -> Dict[str, Any]:
    """Rows as stored ({section: {"value": ..., "version": n}}) over defaults."""
    out = defaults()
    for section, row in (stored or {}).items():
        if section not in SECTIONS or not isinstance(row, dict):
            continue
        value = row.get("value")
        if value is None:
            continue
        if section == "materials":
            out["materials"] = _mat.merged_settings(value)
        elif section == "company":
            company = dict(out["company"])
            company.update({k: v for k, v in (value or {}).items()
                            if isinstance(v, str)})
            out["company"] = company
        elif section == "max_bundle_kg":
            try:
                number = float(value)
                if number > 0:
                    out[section] = number
            except (TypeError, ValueError):
                pass
        else:
            out[section] = value
        out["versions"][section] = row.get("version")
    return out


def provenance(settings: Dict[str, Any], *sections: str) -> Dict[str, Any]:
    """Which version of each section a result was worked out from."""
    versions = settings.get("versions") or {}
    return {s: versions.get(s, "default") for s in sections}


# ── The database ────────────────────────────────────────────────────────────

_cache: Dict[str, Any] = {}


def load(force: bool = False) -> Dict[str, Any]:
    """Read every section. Falls back to the defaults if the database will
    not answer or the migration has not been run - which leaves exactly the
    supplied numbers in force and everything else unknown, as it should."""
    if _cache and not force:
        return copy.deepcopy(_cache)
    stored: Dict[str, Dict[str, Any]] = {}
    try:
        from . import db as _db
        resp = (_db.get_client().table("calc_settings")
                .select("key,value,version").execute())
        for row in resp.data or []:
            stored[str(row.get("key"))] = {"value": row.get("value"),
                                           "version": row.get("version")}
    except Exception:
        pass
    _cache.clear()
    _cache.update(merge(stored))
    return copy.deepcopy(_cache)


def cached() -> Dict[str, Any]:
    """What load() last read, or the defaults - never a network call.

    For things that must not wait on the database, like drawing a worksheet:
    the app loads the settings in the background when it starts and after
    every change, and printing uses whatever is in hand.
    """
    return copy.deepcopy(_cache) if _cache else defaults()


def save(section: str, value: Any) -> int:
    """Store one section for everyone. Returns its new version.

    Goes through set_calc_setting(), which bumps the version and keeps the
    old value in the history in the same statement, so a change can always
    be traced and two people saving at once cannot lose one of the saves
    without a version showing it.
    """
    if section not in SECTIONS:
        raise ValueError(f"There is no calculator setting called {section!r}.")
    from . import db as _db
    resp = _db.get_client().rpc("set_calc_setting", {
        "p_key": section, "p_value": value}).execute()
    _cache.clear()
    data = resp.data
    if isinstance(data, list):
        data = data[0] if data else None
    try:
        return int(data)
    except (TypeError, ValueError):
        return 0


def base_address(settings: Optional[Dict[str, Any]] = None) -> str:
    s = settings if settings is not None else load()
    text = str((s.get("company") or {}).get("base_address") or "").strip()
    return text or BASE_ADDRESS_DEFAULT


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
