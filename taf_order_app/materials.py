"""What wire and media weigh, from the stock TAF actually buys.

Every rate here is worked out from a measurement of real stock - a roll put
on the scales and its size read off the label - and the measurement travels
with the rate. A rate on its own ("0.69 kg/m2") cannot be checked, and the
day somebody weighs a new roll there is nothing to compare it against.

    rate = what the stock weighs / how much area it is

Nothing is rounded on the way. 24.87 kg over 36 m2 is 0.690833... kg/m2,
and that is the number used: rounding a rate to three places and then
multiplying it by a hundred filters is how a total drifts by a kilogram.

Wire masses are averages over the roll as supplied, not steel density worked
out from the wire diameter and the mesh. The basis says so
("supplied_roll_mass"). A density figure would be a second, different answer
to the same question, and two answers is worse than one.

BLACK media has never been weighed. It is the same material as GREY in a
different colour, so it is taken to weigh the same per square metre, and its
basis says that too ("derived_from_GREY"). Its 9.45 kg stock mass is worked
out from that link, not measured - if GREY is re-weighed, BLACK follows. Once
somebody weighs a BLACK roll, entering that measurement replaces the link.

Media roll widths and lengths have not been supplied. They are left empty
rather than guessed from the area: 42 m2 could be 1 m x 42 m or 2 m x 21 m,
and the difference decides whether a piece fits across the roll at all.
"""
from __future__ import annotations

import copy
import math
import re
from typing import Any, Dict, Optional

# Changes whenever the supplied defaults below change, so a result can say
# which set of numbers produced it. Settings edited by staff carry their own
# version on top of this (see settings_version()).
DEFAULTS_VERSION = "TAF-MATERIALS-2026-10"

WIRE_CODES = ("LARGE_WIRE", "SMALL_WIRE")
MEDIA_CODES = ("WASHABLE", "F5", "G4", "180", "GREY", "BLACK")

# The rolls, as supplied. Mesh opening and wire diameter are recorded because
# they identify the product, not because the weight is worked out from them.
DEFAULT_WIRE: Dict[str, Dict[str, Any]] = {
    "LARGE_WIRE": {
        "mesh_opening_mm": [25, 25],
        "wire_diameter_mm": 1.24,
        "roll_width_mm": 1200.0,
        "roll_length_mm": 30000.0,
        "roll_weight_kg": 24.87,
        "basis": "supplied_roll_mass",
    },
    "SMALL_WIRE": {
        "mesh_opening_mm": [12, 12],
        "wire_diameter_mm": 0.80,
        "roll_width_mm": 1200.0,
        "roll_length_mm": 30000.0,
        "roll_weight_kg": 19.30,
        "basis": "supplied_roll_mass",
    },
}

DEFAULT_MEDIA: Dict[str, Dict[str, Any]] = {
    "WASHABLE": {"stock_weight_kg": 10.08, "stock_area_m2": 42.0,
                 "basis": "supplied_stock_mass"},
    "F5":       {"stock_weight_kg": 14.70, "stock_area_m2": 42.0,
                 "basis": "supplied_stock_mass"},
    "G4":       {"stock_weight_kg": 12.60, "stock_area_m2": 42.0,
                 "basis": "supplied_stock_mass"},
    "180":      {"stock_weight_kg": 15.12, "stock_area_m2": 84.0,
                 "basis": "supplied_stock_mass"},
    "GREY":     {"stock_weight_kg": 12.60, "stock_area_m2": 84.0,
                 "basis": "supplied_stock_mass"},
    # No weight of its own: see the module notes.
    "BLACK":    {"stock_weight_kg": None, "stock_area_m2": 63.0,
                 "basis": "derived_from_GREY", "derived_from": "GREY"},
}

# Media roll sizes are not known. None means "not configured", which is a
# different statement from zero and is reported as such.
for _row in DEFAULT_MEDIA.values():
    _row.setdefault("roll_width_mm", None)
    _row.setdefault("roll_length_mm", None)

# How the app and the people using it already write the media. Keys are the
# wording with punctuation and spaces stripped, as part_numbers does it. Only
# names already in use are here; an unknown name is refused, not guessed.
MEDIA_ALIASES = {
    "WASHABLE": "WASHABLE", "WASH": "WASHABLE",
    "F5": "F5",
    "G4": "G4",
    "180": "180",
    "GREY": "GREY", "GRAY": "GREY",
    "BLACK": "BLACK",
}

WIRE_ALIASES = {
    "LARGEWIRE": "LARGE_WIRE", "LARGE": "LARGE_WIRE",
    "SMALLWIRE": "SMALL_WIRE", "SMALL": "SMALL_WIRE",
}


class MaterialError(ValueError):
    """A material code nobody has given a weight to."""


def _shown(value: Any) -> str:
    """A value quoted the way JSON (and so the web app and the API) shows it."""
    import json
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return repr(value)


def _key(text: Any) -> str:
    # "180" stays a string throughout: 180 the number and "180" the media
    # code must land on the same entry, and neither may become 180.0.
    if isinstance(text, bool):
        return ""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        if isinstance(text, float) and not text.is_integer():
            return ""
        text = str(int(text))
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def normalise_media_code(text: Any) -> str:
    """The media code a name means. Raises MaterialError for one we can't weigh."""
    code = MEDIA_ALIASES.get(_key(text))
    if not code:
        raise MaterialError(
            f"There is no weight on file for media {_shown(text)}. The media with "
            f"weights are: {', '.join(MEDIA_CODES)}.")
    return code


def normalise_wire_code(text: Any) -> str:
    code = WIRE_ALIASES.get(_key(text))
    if not code:
        raise MaterialError(
            f"There is no wire called {_shown(text)}. The wire codes are "
            f"{', '.join(WIRE_CODES)}.")
    return code


# ── Settings ────────────────────────────────────────────────────────────────

def default_settings() -> Dict[str, Any]:
    """A fresh copy of the supplied numbers, shaped as stored settings."""
    return {
        "version": DEFAULTS_VERSION,
        "wire": copy.deepcopy(DEFAULT_WIRE),
        "media": copy.deepcopy(DEFAULT_MEDIA),
    }


def merged_settings(stored: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Stored overrides laid over the supplied defaults.

    Only known codes and known fields are taken, so a typo in a stored row
    cannot invent a material. Anything stored replaces the default whole
    field by field, and the stored version is kept for reproducibility.
    """
    out = default_settings()
    if not stored:
        return out
    for kind in ("wire", "media"):
        for code, row in (stored.get(kind) or {}).items():
            try:
                code = (normalise_wire_code(code) if kind == "wire"
                        else normalise_media_code(code))
            except MaterialError:
                continue
            for field, value in (row or {}).items():
                if field in out[kind][code] or field in (
                        "derived_from", "measured_at", "measured_by", "note"):
                    out[kind][code][field] = value
    if stored.get("version"):
        out["version"] = str(stored["version"])
    return out


def _positive(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise MaterialError(f"{label} is not a number.")
    if not math.isfinite(number) or number <= 0:
        raise MaterialError(f"{label} has to be more than zero.")
    return number


# ── Wire ───────────────────────────────────────────────────────────────────

def wire_material(code: Any, settings: Optional[Dict[str, Any]] = None
                  ) -> Dict[str, Any]:
    """A wire roll's rate in kg/m2, with the measurement it came from."""
    code = normalise_wire_code(code)
    s = settings or default_settings()
    row = dict(s["wire"][code])
    width = _positive(row["roll_width_mm"], f"{code} roll width")
    length = _positive(row["roll_length_mm"], f"{code} roll length")
    weight = _positive(row["roll_weight_kg"], f"{code} roll weight")
    area = width * length / 1_000_000.0
    return {
        "code": code,
        "kg_per_m2": weight / area,
        "roll_area_m2": area,
        "roll_width_mm": width,
        "roll_length_mm": length,
        "roll_weight_kg": weight,
        "basis": row.get("basis") or "supplied_roll_mass",
        "source": {
            "mesh_opening_mm": row.get("mesh_opening_mm"),
            "wire_diameter_mm": row.get("wire_diameter_mm"),
            "roll_width_mm": width, "roll_length_mm": length,
            "roll_weight_kg": weight,
        },
        "settings_version": s.get("version", DEFAULTS_VERSION),
    }


# ── Media ──────────────────────────────────────────────────────────────────

def media_material(code: Any, settings: Optional[Dict[str, Any]] = None
                   ) -> Dict[str, Any]:
    """A media's rate in kg/m2, with the measurement or link it came from."""
    code = normalise_media_code(code)
    s = settings or default_settings()
    row = dict(s["media"][code])
    area = _positive(row.get("stock_area_m2"), f"{code} stock area")
    basis = row.get("basis") or "supplied_stock_mass"
    derived_from = row.get("derived_from")
    if basis.startswith("derived_from_") and derived_from:
        parent = media_material(derived_from, s)
        rate = parent["kg_per_m2"]
        weight = area * rate
        source = {"derived_from": parent["code"],
                  "parent_rate_kg_per_m2": rate,
                  "parent_source": parent["source"],
                  "stock_area_m2": area,
                  "stock_weight_kg_derived": weight}
    else:
        weight = _positive(row.get("stock_weight_kg"), f"{code} stock weight")
        rate = weight / area
        source = {"stock_weight_kg": weight, "stock_area_m2": area}
    return {
        "code": code,
        "kg_per_m2": rate,
        "stock_weight_kg": weight,
        "stock_area_m2": area,
        "basis": basis,
        "source": source,
        "roll_width_mm": row.get("roll_width_mm"),
        "roll_length_mm": row.get("roll_length_mm"),
        "settings_version": s.get("version", DEFAULTS_VERSION),
    }


def replace_black_with_measurement(settings: Dict[str, Any], stock_weight_kg,
                                   stock_area_m2, measured_by: str = "",
                                   measured_at: str = "") -> Dict[str, Any]:
    """Settings with BLACK's derived rate replaced by a weighed roll."""
    weight = _positive(stock_weight_kg, "BLACK stock weight")
    area = _positive(stock_area_m2, "BLACK stock area")
    out = copy.deepcopy(settings)
    out["media"]["BLACK"].update({
        "stock_weight_kg": weight, "stock_area_m2": area,
        "basis": "measured", "derived_from": None,
        "measured_by": measured_by, "measured_at": measured_at,
    })
    return out


# ── Which wire a filter takes ───────────────────────────────────────────────
# V-form by nominal depth, before any cage clearance. Inclusive bands, as
# supplied. A depth between them (61-64, 111-114) or under 30 takes the
# nearest band's wire, so every V-form gets one without anybody choosing.
V_FORM_WIRE_BANDS = (
    (30.0, 60.0, "SMALL_WIRE"),
    (65.0, 110.0, "LARGE_WIRE"),
    (115.0, math.inf, "SMALL_WIRE"),
)

WIRE_RULE_VERSION = "TAF-WIRE-SELECT-2026-10"


def select_wire(construction: str, nominal_depth_mm: Any,
                override: Any = None,
                rules: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Which wire a filter is made with, and why.

    `override` is an explicit, recorded choice and always wins. `rules` maps
    a construction to a wire code for constructions other than V-form, as
    configured by staff; none are assumed.
    """
    out = {"code": None, "overridden": False, "status": "ok", "reason": "",
           "rule_version": WIRE_RULE_VERSION}
    if override not in (None, ""):
        out.update(code=normalise_wire_code(override), overridden=True,
                   reason="chosen on the order")
        return out
    if construction == "V-form":
        try:
            depth = float(nominal_depth_mm)
        except (TypeError, ValueError):
            depth = float("nan")
        if not math.isfinite(depth) or depth <= 0:
            out.update(status="invalid_input",
                       reason="the nominal depth is missing")
            return out
        for low, high, code in V_FORM_WIRE_BANDS:
            if low <= depth <= high:
                out.update(code=code,
                           reason=f"V-form at {depth:g}mm deep takes {code}")
                return out
        # Between bands: the nearest one (the first, on a tie).
        best = min(V_FORM_WIRE_BANDS,
                   key=lambda b: b[0] - depth if depth < b[0] else depth - b[1])
        out.update(code=best[2],
                   reason=(f"V-form at {depth:g}mm deep takes {best[2]}, "
                           "from the nearest depth rule"))
        return out
    configured = (rules or {}).get(construction)
    if configured:
        out.update(code=normalise_wire_code(configured),
                   reason=f"{construction} is set to {configured}")
        return out
    out.update(status="needs_wire_rule",
               reason=f"no wire has been set for {construction or 'this filter'}")
    return out
