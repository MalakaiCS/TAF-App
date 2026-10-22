"""C-channel: what a channel is, what it weighs, and what a frame takes.

One place for it. The filter calculator (frame weights), the packing planner
and delivery labels, the stock screen, the weight table and the API all call
these functions; docs/app/calc.js carries the same arithmetic for the web
app and the Edge Function, held to it by tests/test_calc_parity.py.

The channel
-----------
A standard channel is ``left flange x centre width x right flange`` - 23 x
centre x 23 mm - in G2 Z275 galvanised steel, 0.55 mm, 2440 mm lengths.

The centre width is not the filter's nominal depth. TAF measured eighteen
channels (13, 18 ... 98 mm); matched in order to the nominal depths 15-100
they read as depth less 1-3 mm. That matching is inferred from the sequence,
so those widths are "supplied - mapping unconfirmed" until somebody marks
them verified. Every other depth from 10 to 250 in 5s is estimated at depth
less 2 mm (10 mm provisionally 10 mm), and says so. A verified width always
wins; an estimate is never shown as verified.

The weight
----------
    developed width = left flange + centre + right flange (+ bend correction)
    kg              = developed width x length x thickness x density / 1e9

with the configured thickness and density, so 23 x 44 x 23 x 2440 at 0.55 mm
and 7850 kg/m3 is 0.948123 kg. That is base steel. Z275 is 275 g/m2 of zinc
over both faces; it is only added when the thickness is known to be base
metal (or the coated thickness has had the zinc taken out), never on top of a
nominal thickness that may already include it.

A measured, verified weight for a profile is used in preference to the
calculation, and the result says which it is.

Stacks and packages are rounded up to the next 0.1 kg once, at the end, from
the unrounded single-length weight - never a rounded weight multiplied.

Frames
------
A filter does not take a whole length. Its frame is the strips the existing
filter calculator (cutting.py) cuts: a U is a strip and a cap, a G one strip,
an L two strips. Their cut lengths times the channel's weight per mm is the
frame's installed weight; the rest of the length is offcut and is not in the
filter. The corner notches and the lip's trimmed flanges are not deducted -
their size has not been confirmed - so a frame weight errs heavy, and says so.
"""
from __future__ import annotations

import copy
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .numbers import finite, positive, positive_int

VERSION = "TAF-CCHANNEL-2026-10"
DEFAULT_MATERIAL = "C_CHANNEL_G2_Z275_055"
STACKS = (1, 2, 5, 10)
ZINC_DENSITY_KG_M3 = 7140.0

# What TAF measured, matched in order to the nominal depths 15-100.
SUPPLIED_WIDTHS = {15: 13, 20: 18, 25: 22, 30: 28, 35: 33, 40: 38, 45: 44,
                   50: 48, 55: 53, 60: 58, 65: 63, 70: 68, 75: 74, 80: 78,
                   85: 84, 90: 89, 95: 94, 100: 98}

# Verification status, strongest first.
VERIFIED = "verified"
SUPPLIED = "supplied_unconfirmed_mapping"
ESTIMATED = "estimated"
PROVISIONAL = "provisional_estimate"
CUSTOM = "custom"
STATUS_LABELS = {VERIFIED: "Verified", SUPPLIED: "Supplied, unconfirmed",
                 ESTIMATED: "Estimated", PROVISIONAL: "Provisional estimate",
                 CUSTOM: "Custom"}


def default_settings() -> Dict[str, Any]:
    """The editable C-channel settings, as supplied."""
    widths: Dict[str, Dict[str, Any]] = {
        "10": {"width_mm": 10, "status": PROVISIONAL,
               "source": "initial estimate - confirm"}}
    for depth, width in SUPPLIED_WIDTHS.items():
        widths[str(depth)] = {"width_mm": width, "status": SUPPLIED,
                              "source": "TAF measurement; nominal depth "
                                        "inferred from the sequence"}
    return {
        "version": VERSION,
        "default_material": DEFAULT_MATERIAL,
        "materials": {DEFAULT_MATERIAL: {
            "material_code": DEFAULT_MATERIAL,
            "material": "G2 Z275 galvanised steel",
            "steel_grade": "G2",
            "galvanising": "Z275",
            "nominal_thickness_mm": 0.55,
            # nominal_supplied: 0.55 as supplied, used as the steel's
            # thickness. base_metal / coated once the mill says which.
            "thickness_basis": "nominal_supplied",
            "base_metal_thickness_mm": None,
            "coating_mass_g_m2": 275,
            "include_coating_mass": False,
            "density_kg_m3": 7850,
            "stock_length_mm": 2440,
            "left_flange_mm": 23,
            "right_flange_mm": 23,
            "bend_correction_mm": 0,
            "mass_calibration_factor": None,
        }},
        "depth_range": {"min_mm": 10, "max_mm": 250, "step_mm": 5},
        "estimate_rule": {"subtract_mm": 2},
        "centre_widths": widths,
        "measured_weights": [],
        "stack_quantities": list(STACKS),
        "rounding": "up_0.1",
    }


def merged(stored: Any) -> Dict[str, Any]:
    """Stored settings over the defaults, section by section."""
    out = default_settings()
    if not isinstance(stored, dict):
        return out
    for key, value in stored.items():
        if key == "materials" and isinstance(value, dict):
            for code, mat in value.items():
                base = dict(out["materials"].get(code) or {})
                base.update(mat or {})
                base["material_code"] = code
                out["materials"][code] = base
        elif key == "centre_widths" and isinstance(value, dict):
            for depth, row in value.items():
                if isinstance(row, dict):
                    out["centre_widths"][str(_key(depth))] = dict(row)
        elif value is not None:
            out[key] = copy.deepcopy(value)
    return out


def _key(depth: Any) -> str:
    d = finite(depth)
    if d is None:
        return ""
    return str(int(d)) if d == int(d) else repr(d)


def _settings(settings: Any) -> Dict[str, Any]:
    if settings is None:
        return default_settings()
    if isinstance(settings, dict) and "c_channel" in settings:
        return merged(settings.get("c_channel"))
    return merged(settings)


def depths(settings: Any = None) -> List[int]:
    """Every standard nominal depth, 10 to 250 in 5s by default."""
    r = _settings(settings)["depth_range"]
    lo = positive(r.get("min_mm")) or 10
    hi = positive(r.get("max_mm")) or 250
    step = positive(r.get("step_mm")) or 5
    out, d = [], lo
    while d <= hi + 1e-9:
        out.append(int(d) if d == int(d) else d)
        d += step
    return out


def round_up(kg: Optional[float]) -> Optional[float]:
    """Up to the next 0.1 kg. Applied once, to a final total."""
    if kg is None:
        return None
    return math.ceil(round(kg * 10, 9)) / 10


def kg_text(kg: Optional[float]) -> str:
    """For people: '1.0 kg'. Numbers stay numbers everywhere else."""
    return "" if kg is None else f"{kg:.1f} kg"


# ── Dimensions ──────────────────────────────────────────────────────────────

def material(settings: Any = None, code: Any = None) -> Optional[Dict[str, Any]]:
    s = _settings(settings)
    code = str(code or s.get("default_material") or DEFAULT_MATERIAL)
    m = (s.get("materials") or {}).get(code)
    return dict(m, material_code=code) if m else None


def resolve_dimensions(nominal_depth_mm: Any = None,
                       centre_width_mm: Any = None, settings: Any = None,
                       material_code: Any = None, length_mm: Any = None,
                       left_flange_mm: Any = None,
                       right_flange_mm: Any = None) -> Dict[str, Any]:
    """The channel for a nominal depth (or a given centre width): its
    dimensions, where each came from and how sure it is."""
    s = _settings(settings)
    out: Dict[str, Any] = {
        "calculation_status": "ok", "material_code": None,
        "nominal_depth_mm": None, "actual_centre_width_mm": None,
        "left_flange_mm": None, "right_flange_mm": None,
        "channel_length_mm": None, "dimension_source": None,
        "verification_status": None, "missing_inputs": [],
        "validation_errors": [], "calculation_warnings": [],
    }
    errors, warnings = out["validation_errors"], out["calculation_warnings"]
    mat = material(s, material_code)
    if mat is None:
        errors.append(f"there is no C-channel material {material_code!r}")
        out["calculation_status"] = "invalid_input"
        return out
    out["material_code"] = mat["material_code"]

    def _pos(value, label):
        v = positive(value)
        if v is None:
            errors.append(f"{label} must be a number above zero")
        return v

    depth = None
    if nominal_depth_mm not in (None, ""):
        depth = _pos(nominal_depth_mm, "nominal depth")
    out["nominal_depth_mm"] = depth

    if centre_width_mm not in (None, ""):
        out["actual_centre_width_mm"] = _pos(centre_width_mm, "centre width")
        out["dimension_source"] = "custom"
        out["verification_status"] = CUSTOM
    elif depth is not None:
        row = (s.get("centre_widths") or {}).get(_key(depth))
        width = positive((row or {}).get("width_mm"))
        if row and width is not None:
            status = str(row.get("status") or ESTIMATED)
            if status not in STATUS_LABELS:
                status = ESTIMATED
            out["actual_centre_width_mm"] = width
            out["verification_status"] = status
            out["dimension_source"] = {
                VERIFIED: "verified_measurement",
                SUPPLIED: "supplied_measurement",
                CUSTOM: "custom"}.get(status, "estimated_rule")
        else:
            sub = finite((s.get("estimate_rule") or {}).get("subtract_mm"))
            sub = 2.0 if sub is None else sub
            width = depth - sub
            if width <= 0:
                errors.append(f"a {depth:g}mm depth less {sub:g}mm leaves no "
                              "centre width - enter one")
            else:
                out["actual_centre_width_mm"] = width
                out["dimension_source"] = "estimated_rule"
                out["verification_status"] = ESTIMATED
        if out["verification_status"] in (ESTIMATED, PROVISIONAL):
            warnings.append(f"the centre width for {depth:g}mm is an "
                            "estimate - confirm it")
        elif out["verification_status"] == SUPPLIED:
            warnings.append(f"the {out['actual_centre_width_mm']:g}mm centre "
                            f"width for {depth:g}mm is a supplied measurement "
                            "whose depth match is not yet confirmed")
    elif not errors:
        out["missing_inputs"].append("a nominal depth or a centre width")

    out["left_flange_mm"] = _pos(mat.get("left_flange_mm")
                                 if left_flange_mm in (None, "")
                                 else left_flange_mm, "left flange")
    out["right_flange_mm"] = _pos(mat.get("right_flange_mm")
                                  if right_flange_mm in (None, "")
                                  else right_flange_mm, "right flange")
    out["channel_length_mm"] = _pos(mat.get("stock_length_mm")
                                    if length_mm in (None, "") else length_mm,
                                    "channel length")
    if errors:
        out["calculation_status"] = "invalid_input"
    elif out["missing_inputs"]:
        out["calculation_status"] = "needs_input"
    return out


def size_text(dims: Dict[str, Any]) -> str:
    """'23 x 44 x 23 x 2440 mm'."""
    parts = [dims.get("left_flange_mm"), dims.get("actual_centre_width_mm"),
             dims.get("right_flange_mm"), dims.get("channel_length_mm")]
    if any(p is None for p in parts):
        return ""
    return " x ".join(f"{p:g}" for p in parts) + " mm"


# ── Weight ──────────────────────────────────────────────────────────────────

def _thickness(mat: Dict[str, Any], errors: List[str],
               warnings: List[str]) -> Optional[float]:
    """The steel's own thickness, and whether coating may be added on."""
    basis = str(mat.get("thickness_basis") or "nominal_supplied")
    base = positive(mat.get("base_metal_thickness_mm"))
    if base is not None:
        return base
    nominal = positive(mat.get("nominal_thickness_mm"))
    if nominal is None:
        errors.append("material thickness must be a number above zero")
        return None
    if basis == "coated":
        coat = non_negative_or_none(mat.get("coating_mass_g_m2"))
        if coat is None:
            errors.append("a coated thickness needs the coating mass")
            return None
        t = nominal - coat / ZINC_DENSITY_KG_M3
        if t <= 0:
            errors.append("the coating is thicker than the steel")
            return None
        return t
    return nominal


def non_negative_or_none(v: Any) -> Optional[float]:
    n = finite(v)
    return n if n is not None and n >= 0 else None


def _measured(s: Dict[str, Any], code: str, dims: Dict[str, Any]
              ) -> Optional[Dict[str, Any]]:
    """A verified measured weight for this exact profile, if there is one."""
    for m in s.get("measured_weights") or []:
        if not m.get("verified") or str(m.get("material_code") or code) != code:
            continue
        kg, length = positive(m.get("kg")), positive(m.get("length_mm"))
        if kg is None or length is None:
            continue
        width = positive(m.get("centre_width_mm"))
        depth = positive(m.get("nominal_depth_mm"))
        if width is not None:
            if abs(width - (dims["actual_centre_width_mm"] or -1)) > 1e-9:
                continue
        elif depth is None or dims.get("nominal_depth_mm") is None or \
                abs(depth - dims["nominal_depth_mm"]) > 1e-9:
            continue
        return dict(m, kg=kg, length_mm=length)
    return None


def channel_weight(nominal_depth_mm: Any = None, centre_width_mm: Any = None,
                   length_mm: Any = None, settings: Any = None,
                   material_code: Any = None, left_flange_mm: Any = None,
                   right_flange_mm: Any = None,
                   use_measured: bool = True) -> Dict[str, Any]:
    """One channel: its dimensions and weight, calculated or measured."""
    s = _settings(settings)
    out = resolve_dimensions(nominal_depth_mm, centre_width_mm, s,
                             material_code, length_mm, left_flange_mm,
                             right_flange_mm)
    out.update(material_thickness_mm=None, steel_density_kg_m3=None,
               developed_width_mm=None, weight_basis=None,
               weight_per_mm_kg=None, raw_weight_kg=None,
               display_weight_kg=None, settings_version=s.get("version"))
    if out["calculation_status"] != "ok":
        return out
    errors, warnings = out["validation_errors"], out["calculation_warnings"]
    mat = material(s, out["material_code"]) or {}
    t = _thickness(mat, errors, warnings)
    density = positive(mat.get("density_kg_m3"))
    if density is None:
        errors.append("steel density must be a number above zero")
    bend = finite(mat.get("bend_correction_mm"))
    if bend is None and mat.get("bend_correction_mm") not in (None, ""):
        errors.append("the bend correction must be a number")
    developed = (out["left_flange_mm"] + out["actual_centre_width_mm"]
                 + out["right_flange_mm"] + (bend or 0.0))
    if developed <= 0:
        errors.append("the developed width comes out at nothing")
    if errors:
        out["calculation_status"] = "invalid_input"
        return out
    out.update(material_thickness_mm=t, steel_density_kg_m3=density,
               developed_width_mm=developed)
    length = out["channel_length_mm"]

    measured = _measured(s, out["material_code"], out) if use_measured else None
    if measured is not None:
        per_mm = measured["kg"] / measured["length_mm"]
        out["weight_basis"] = "measured"
        if abs(measured["length_mm"] - length) > 1e-9:
            out["weight_basis"] = "measured_scaled_to_length"
            warnings.append(f"measured over {measured['length_mm']:g}mm, "
                            f"scaled to {length:g}mm")
    else:
        per_mm = developed * t * density / 1e9
        basis = "calculated_base_steel"
        coat = non_negative_or_none(mat.get("coating_mass_g_m2"))
        if mat.get("include_coating_mass"):
            confirmed = mat.get("base_metal_thickness_mm") not in (None, "") \
                or mat.get("thickness_basis") in ("base_metal", "coated")
            if confirmed and coat is not None:
                per_mm += developed * coat / 1e9
                basis = "calculated_steel_and_coating"
            else:
                warnings.append("coating not added: the 0.55mm may already "
                                "include it until the steel's base-metal "
                                "thickness is confirmed")
        cal = positive(mat.get("mass_calibration_factor"))
        if cal is not None:
            per_mm *= cal
            basis += "_calibrated"
        out["weight_basis"] = basis
    out["weight_per_mm_kg"] = per_mm
    out["raw_weight_kg"] = per_mm * length
    out["display_weight_kg"] = round_up(out["raw_weight_kg"])
    return out


def stack_weights(channel: Dict[str, Any],
                  quantities: Optional[Sequence[Any]] = None
                  ) -> List[Dict[str, Any]]:
    """A stack of n lengths, each from the unrounded single weight, rounded
    up once. Quantities must be whole numbers of 1 or more."""
    qs = list(quantities) if quantities is not None else list(STACKS)
    out = []
    raw = channel.get("raw_weight_kg")
    for q in qs:
        n = positive_int(q)
        if n is None:
            out.append({"stack_quantity": q, "stack_raw_weight_kg": None,
                        "stack_display_weight_kg": None,
                        "validation_errors": ["a stack is a whole number of "
                                              "1 or more lengths"]})
            continue
        total = None if raw is None else raw * n
        out.append({"stack_quantity": n, "stack_raw_weight_kg": total,
                    "stack_display_weight_kg": round_up(total),
                    "validation_errors": []})
    return out


def cut_section_weight(channel: Dict[str, Any], cut_length_mm: Any,
                       section_quantity: Any = 1,
                       measured_kg: Any = None) -> Dict[str, Any]:
    """Pieces cut from a channel: their weight, from the weight per mm (or a
    measured weight for the pieces, as given)."""
    out = {"cut_length_mm": positive(cut_length_mm),
           "section_quantity": positive_int(section_quantity),
           "section_weight_kg": None, "weight_basis": None,
           "validation_errors": []}
    if out["cut_length_mm"] is None:
        out["validation_errors"].append("a cut length must be above zero")
    if out["section_quantity"] is None:
        out["validation_errors"].append("a section count is a whole number "
                                        "of 1 or more")
    if out["validation_errors"]:
        return out
    m = positive(measured_kg)
    if m is not None:
        out.update(section_weight_kg=m, weight_basis="measured")
        return out
    per_mm = channel.get("weight_per_mm_kg")
    if per_mm is None:
        return out
    out["section_weight_kg"] = per_mm * out["cut_length_mm"] * \
        out["section_quantity"]
    out["weight_basis"] = channel.get("weight_basis")
    return out


def frame_cut_list(short_mm: Any, long_mm: Any, method: str = "u",
                   nominal_depth_mm: Any = None,
                   material_code: Any = None) -> Optional[List[Dict[str, Any]]]:
    """The channel pieces one filter's frame is cut into, from the existing
    filter calculator's verified rules (cutting.layout): a U or Sideways U
    is a strip and a cap, a G one strip, an L two strips. None when the
    rule does not cover it."""
    from . import cutting as _cut
    try:
        shape = _cut.layout(short_mm, long_mm, method)
    except (ValueError, TypeError):
        return None
    rows = [{"name": f"{shape['name']} strip", "cut_length_mm": shape["frame"],
             "section_quantity": shape["strips"]}]
    if shape["cap"]:
        rows.append({"name": "cap", "cut_length_mm": shape["cap"],
                     "section_quantity": 1})
    for r in rows:
        r.update(nominal_depth_mm=nominal_depth_mm,
                 material_code=material_code or DEFAULT_MATERIAL)
    return rows


def frame_weight(cut_list: Optional[Iterable[Dict[str, Any]]],
                 order_quantity: Any = 1,
                 settings: Any = None) -> Dict[str, Any]:
    """A filter frame's installed channel: the sum of its cut sections. The
    rest of each length is offcut - stock, not filter."""
    s = _settings(settings)
    out: Dict[str, Any] = {"calculation_status": "ok", "sections": [],
                           "frame_weight_kg": None,
                           "frame_weight_kg_order": None,
                           "order_quantity": positive_int(order_quantity),
                           "missing_inputs": [], "validation_errors": [],
                           "calculation_warnings": [],
                           "settings_version": s.get("version")}
    rows = list(cut_list or [])
    if not rows:
        out["calculation_status"] = "needs_frame_cut_rule"
        out["missing_inputs"].append("a verified frame cut list (cut lengths "
                                     "and how many of each per filter)")
        return out
    if out["order_quantity"] is None:
        out["validation_errors"].append("the order quantity is a whole number "
                                        "of 1 or more")
    total = 0.0
    for i, row in enumerate(rows, 1):
        ch = channel_weight(row.get("nominal_depth_mm"),
                            row.get("centre_width_mm"), None, s,
                            row.get("material_code"))
        sec = cut_section_weight(ch, row.get("cut_length_mm"),
                                 row.get("section_quantity", 1),
                                 row.get("measured_kg"))
        sec.update(name=row.get("name") or f"section {i}",
                   nominal_depth_mm=ch.get("nominal_depth_mm"),
                   actual_centre_width_mm=ch.get("actual_centre_width_mm"),
                   verification_status=ch.get("verification_status"),
                   material_code=ch.get("material_code"))
        out["sections"].append(sec)
        for e in ch["validation_errors"] + sec["validation_errors"]:
            out["validation_errors"].append(f"{sec['name']}: {e}")
        for m in ch["missing_inputs"]:
            out["missing_inputs"].append(f"{sec['name']}: {m}")
        for w in ch["calculation_warnings"]:
            if w not in out["calculation_warnings"]:
                out["calculation_warnings"].append(w)
        if sec["section_weight_kg"] is None:
            total = None
        elif total is not None:
            total += sec["section_weight_kg"]
    if out["validation_errors"]:
        out["calculation_status"] = "invalid_input"
        return out
    if total is None:
        out["calculation_status"] = "needs_input"
        return out
    out["calculation_warnings"].append(
        "corner notches and trimmed lip flanges are not deducted (their size "
        "is not confirmed), so this errs heavy")
    out["frame_weight_kg"] = total
    out["frame_weight_kg_order"] = total * out["order_quantity"]
    return out


def stock_weight(nominal_depth_mm: Any = None, lengths: Any = 1,
                 length_mm: Any = None, centre_width_mm: Any = None,
                 settings: Any = None, material_code: Any = None
                 ) -> Dict[str, Any]:
    """Whole lengths of channel in stock or in a delivery: their weight,
    raw and rounded up once."""
    ch = channel_weight(nominal_depth_mm, centre_width_mm, length_mm,
                        settings, material_code)
    out = dict(ch)
    n = positive_int(lengths)
    if n is None:
        out["validation_errors"] = list(ch["validation_errors"]) + [
            "a number of lengths is a whole number of 1 or more"]
        out["calculation_status"] = "invalid_input"
        n = None
    out["stack_quantity"] = n
    raw = ch["raw_weight_kg"]
    out["stack_raw_weight_kg"] = None if raw is None or n is None else raw * n
    out["stack_display_weight_kg"] = round_up(out["stack_raw_weight_kg"])
    return out


def table(settings: Any = None,
          quantities: Optional[Sequence[Any]] = None) -> List[Dict[str, Any]]:
    """Every standard depth: its channel and its stack weights, all worked
    out here - nothing in it is typed."""
    s = _settings(settings)
    qs = list(quantities) if quantities is not None else \
        list(s.get("stack_quantities") or STACKS)
    rows = []
    for d in depths(s):
        ch = channel_weight(d, settings=s)
        rows.append({
            "nominal_depth_mm": d,
            "actual_centre_width_mm": ch["actual_centre_width_mm"],
            "size": size_text(ch),
            "verification_status": ch["verification_status"],
            "dimension_source": ch["dimension_source"],
            "weight_basis": ch["weight_basis"],
            "raw_weight_kg": ch["raw_weight_kg"],
            "stacks": stack_weights(ch, qs),
            "calculation_status": ch["calculation_status"],
        })
    return rows


def depth_from_text(text: Any) -> Optional[float]:
    """A channel's nominal depth from a stock item's wording: 'Channel 45mm',
    '45mm channel', 'CH45', 'C-CHANNEL 45'. None when it does not say."""
    import re
    t = str(text or "").upper()
    m = (re.search(r"(\d+(?:\.\d+)?)\s*MM", t)
         or re.search(r"\bC?-?CH(?:ANNEL)?[\s\-_]*(\d+(?:\.\d+)?)\b", t))
    if not m:
        return None
    return positive(m.group(1))


def length_from_text(text: Any) -> Optional[float]:
    """A length of 1000-12000mm named in the wording ('2440', '3000mm')."""
    import re
    for n in re.findall(r"(\d{4,5})", str(text or "")):
        if 1000 <= int(n) <= 12000:
            return float(n)
    return None


def bundle_from_text(text: Any) -> Optional[int]:
    """'bundle of 10', 'pack of 5', '10/bundle', '10 per bundle'."""
    import re
    t = str(text or "").lower()
    m = (re.search(r"(?:bundle|pack|stack)\s+of\s+(\d+)", t)
         or re.search(r"(\d+)\s*(?:/|per)\s*(?:bundle|pack|stack)", t))
    return positive_int(m.group(1)) if m else None


def stock_item_weight(item: Dict[str, Any], settings: Any = None
                      ) -> Optional[Dict[str, Any]]:
    """What a C-channel stock item weighs: a length, a bundle and what is on
    hand. None for anything that is not channel. Read from the item's own
    name, SKU and description, so existing stock records are used as they
    are - no second product for the same channel."""
    words = " ".join(str(item.get(k) or "") for k in
                     ("name", "sku", "description"))
    is_channel = str(item.get("product_type") or "") == "Channel" or \
        "CHANNEL" in words.upper()
    if not is_channel:
        return None
    depth = depth_from_text(words)
    out: Dict[str, Any] = {"nominal_depth_mm": depth, "length": None,
                           "bundle_lengths": bundle_from_text(words),
                           "bundle_raw_weight_kg": None,
                           "bundle_display_weight_kg": None,
                           "on_hand": finite(item.get("stock_on_hand")),
                           "unit": str(item.get("unit") or "each"),
                           "on_hand_raw_weight_kg": None,
                           "on_hand_display_weight_kg": None,
                           "missing_inputs": []}
    if depth is None:
        out["missing_inputs"].append("the channel's depth in its name, e.g. "
                                     "'Channel 45mm'")
        return out
    ch = channel_weight(depth, None, length_from_text(words), settings)
    out["length"] = ch
    per_len = ch["raw_weight_kg"]
    if per_len is None:
        return out
    if out["bundle_lengths"]:
        out["bundle_raw_weight_kg"] = per_len * out["bundle_lengths"]
        out["bundle_display_weight_kg"] = round_up(out["bundle_raw_weight_kg"])
    on_hand = out["on_hand"]
    if on_hand is not None and on_hand >= 0:
        unit = out["unit"].lower()
        if unit in ("metre", "metres", "m"):
            raw = ch["weight_per_mm_kg"] * 1000 * on_hand
        elif unit in ("kg",):
            raw = on_hand
        else:                               # each / length / bundle
            per = per_len * ((out["bundle_lengths"] or 1)
                             if unit in ("bundle", "pack") else 1)
            raw = per * on_hand
        out["on_hand_raw_weight_kg"] = raw
        out["on_hand_display_weight_kg"] = round_up(raw)
    return out
