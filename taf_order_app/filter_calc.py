"""Cut sizes and weights for a filter, from verified rules only.

The one function that matters is calculate(request, settings). It answers
for one order line: what each piece of wire and media is cut to, what those
blanks weigh, what stays in the finished filter, and - only when every part
of the filter is known - what the whole filter weighs.

Where the cut sizes come from
-----------------------------
A filter's finished width, height and depth do not on their own say how big
a sheet of wire has to be before it is folded into a V. Something has to
supply that, and there are exactly three things allowed to:

  1. The worksheet's own formulas. These are what the floor has cut to for
     years (pdf_generator._wire_media), so they are TAF's verified rules and
     are built in here as profiles - a flat panel's wire is 10mm under each
     side, a 65-80mm V-form's wire is 10mm under the short side by 1.55 times
     the long side, and so on. Where the worksheet itself does not have a
     rule (a 62mm V, or anything over 100mm, where it prints "CHECK WIRE &
     MEDIA") there is no profile, and the answer is needs_cut_rule.
  2. A profile staff have entered: a confirmed cross-section (so many Vs of
     such a depth across such a span, or a list of segments), allowances and
     a cut increment. Geometry is only applied when a profile confirms it.
  3. Pieces somebody has actually measured. Those are the final blanks and
     have nothing added to them or rounded.

Nothing here invents a pleat count, a clearance or an allowance.

Blank, installed and complete
-----------------------------
A blank's weight is its flat area times the material's rate. Folding does
not change it. Whether all of the blank stays in the filter is a separate
question that has to be answered by the profile ("full blank stays in", or
"this much area is kept") - until it is, the installed weight is unknown,
though the blank weight is still reported.

The complete weight of a filter is only given when every part the filter is
made of has a known installed weight: wire, media, frame, braces and
whatever else the construction lists. A part confirmed as not applicable
counts as zero; a part nobody has weighed does not count as anything, and
the total stays empty. Known parts are still added up and reported, clearly
marked as a subtotal.

Weights are returned as plain kg numbers at full precision. Rounding is for
display only and happens once, at the end.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import bracing as _bracing
from . import cchannel as _cch
from . import calc_settings as _settings
from . import materials as _mat
from . import mounting_frames as _frames
from .numbers import ceil_to, finite, positive, positive_int

CALC_VERSION = "TAF-FILTER-CALC-2026-10"

CONSTRUCTIONS = ("Flat Panel", "V-form", "Flyscreen", "Stepped Filter",
                 "Header")

WIRE_ROLL_FALLBACK = (1200.0, 30000.0)

# ── The worksheet's rules, as profiles ──────────────────────────────────────
# Lifted from pdf_generator._wire_media, which is what prints on every
# worksheet. _wire_media now asks these for its numbers, so the sheet and the
# calculator cannot drift apart. "nearest" is Python's round(), half to even,
# exactly as the worksheet has always done it.

_WS_SOURCE = "TAF production worksheet (pdf_generator._wire_media)"


def _ws_v(pid: str, low: float, high: float, short_add: float,
          multiply: float) -> List[Dict[str, Any]]:
    wire = {
        "id": pid, "version": 1, "kind": "wire", "verified": True,
        "constructions": ["V-form"], "depth_min_mm": low, "depth_max_mm": high,
        "basis": "taf_worksheet_formula", "source": _WS_SOURCE,
        "method": "linear",
        "across_pleats": "long",
        "width": {"from": "short", "add": short_add},
        "length": {"from": "long", "multiply": multiply, "round": "nearest"},
        "pieces_per_filter": 2,
        "rotation_allowed": True,
        "installed": "full_blank",
    }
    media = {
        "id": pid + "-MEDIA", "version": 1, "kind": "media", "verified": True,
        "constructions": ["V-form"], "depth_min_mm": low, "depth_max_mm": high,
        "basis": "taf_worksheet_formula", "source": _WS_SOURCE,
        "method": "from_wire_blank", "wire_profile": pid,
        "width_add": 60, "length_add": 40,
        "pieces_per_filter": 1,
        "installed": "full_blank",
    }
    return [wire, media]


BUILTIN_PROFILES: List[Dict[str, Any]] = [
    {
        "id": "TAF-WS-FLAT", "version": 1, "kind": "wire", "verified": True,
        "constructions": ["Flat Panel", "Header"],
        "basis": "taf_worksheet_formula", "source": _WS_SOURCE,
        "method": "linear",
        "width": {"from": "short", "add": -10},
        "length": {"from": "long", "add": -10},
        "pieces_per_filter": 2, "rotation_allowed": True, "installed": "full_blank",
    },
    {
        "id": "TAF-WS-FLAT-MEDIA", "version": 1, "kind": "media",
        "verified": True, "constructions": ["Flat Panel", "Header"],
        "basis": "taf_worksheet_formula", "source": _WS_SOURCE,
        "method": "linear", "flat": True,
        "width": {"from": "short"}, "length": {"from": "long"},
        "pieces_per_filter": 1, "installed": "full_blank",
    },
    *_ws_v("TAF-WS-V30-60", 30, 60, -15, 1.36),
    *_ws_v("TAF-WS-V65-80", 65, 80, -10, 1.55),
    *_ws_v("TAF-WS-V85-100", 85, 100, -10, 1.785),
    {
        "id": "TAF-WS-FLYSCREEN-MEDIA", "version": 1, "kind": "media",
        "verified": True, "constructions": ["Flyscreen"],
        "basis": "taf_worksheet_formula",
        "source": "TAF production worksheet (pdf_generator._draw_fs)",
        "method": "linear", "flat": True,
        "width": {"from": "short", "add": 20},
        "length": {"from": "long", "add": 20},
        "pieces_per_filter": 1, "installed": "full_blank",
    },
]


def construction_of(text: Any) -> str:
    """The construction a filter type means, using the aliases already in
    part_numbers. "" for anything it does not recognise."""
    from . import part_numbers as _pn
    name = _pn.canonical_filter_type(str(text or ""))
    return name if name in CONSTRUCTIONS else ""


def all_profiles(settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Profiles staff have entered, then the built-in worksheet ones."""
    return list(settings.get("cut_profiles") or []) + BUILTIN_PROFILES


def find_profile(profiles: Iterable[Dict[str, Any]], pid: str,
                 version: Any = None) -> Optional[Dict[str, Any]]:
    best = None
    for p in profiles:
        if str(p.get("id")) != str(pid):
            continue
        if version not in (None, ""):
            if str(p.get("version")) == str(version):
                return p
            continue
        if best is None or (positive_int(p.get("version")) or 0) > \
                (positive_int(best.get("version")) or 0):
            best = p
    return best


def match_profile(profiles: Iterable[Dict[str, Any]], kind: str,
                  construction: str, depth: Optional[float]
                  ) -> Optional[Dict[str, Any]]:
    """The first verified profile of this kind for this filter and depth.
    Staff-entered profiles come first, so a confirmed profile replaces the
    worksheet formula for the depths it covers. A depth no profile covers
    takes the nearest depth band's profile (the first, on a tie), so every
    depth has a cut."""
    nearest, gap = None, None
    for p in profiles:
        if p.get("kind") != kind or not p.get("verified"):
            continue
        if construction not in (p.get("constructions") or []):
            continue
        low, high = finite(p.get("depth_min_mm")), finite(p.get("depth_max_mm"))
        if low is not None or high is not None:
            if depth is None:
                continue
            off = 0.0
            if low is not None and depth < low:
                off = low - depth
            elif high is not None and depth > high:
                off = depth - high
            if off > 0:
                if gap is None or off < gap:
                    nearest, gap = p, off
                continue
        return p
    return nearest


# ── Dimensions from a profile ───────────────────────────────────────────────

def _round(value: float, how: Any) -> float:
    if how == "nearest":
        return float(int(round(value)))      # Python: half to even
    if how == "up":
        return float(math.ceil(round(value, 9)))
    if how == "down":
        return float(math.floor(round(value, 9)))
    return value


def _dim(spec: Any, dims: Dict[str, float]) -> Optional[float]:
    """A number given outright, or {"from": side, "multiply", "add", "round"}."""
    if isinstance(spec, dict):
        base = dims.get(str(spec.get("from", "")))
        if base is None:
            return None
        mult = finite(spec.get("multiply", 1))
        add = finite(spec.get("add", 0))
        if mult is None or add is None:
            return None
        return _round(base * mult + add, spec.get("round"))
    return finite(spec)


def _sum_allowances(value: Any) -> Optional[float]:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (list, tuple)):
        total = 0.0
        for v in value:
            n = finite(v)
            if n is None:
                return None
            total += n
        return total
    return finite(value)


def _apply_increment(value: float, profile: Dict[str, Any], which: str
                     ) -> float:
    inc = profile.get("cut_increment_mm")
    if isinstance(inc, dict):
        inc = inc.get(which)
    step = positive(inc)
    return ceil_to(value, step) if step else value


def developed_triangular(span_mm: float, depth_mm: float, v_count: int
                         ) -> float:
    """Path length across N uniform triangular Vs: 2N x sqrt((P/2)^2 + D^2)."""
    pitch = span_mm / v_count
    return 2 * v_count * math.sqrt((pitch / 2.0) ** 2 + depth_mm ** 2)


def developed_segments(segments: Iterable[Any]) -> Optional[float]:
    total = 0.0
    for seg in segments or []:
        try:
            dx, dz = float(seg[0]), float(seg[1])
        except (TypeError, ValueError, IndexError):
            return None
        if not (math.isfinite(dx) and math.isfinite(dz)):
            return None
        total += math.hypot(dx, dz)
    return total


def profile_cut(profile: Dict[str, Any], dims: Dict[str, float],
                wire_cut: Optional[Tuple[float, float]] = None
                ) -> Tuple[Optional[Tuple[float, float]], List[str]]:
    """(cut width, cut length) from a profile, or None and what is missing."""
    method = profile.get("method")
    missing: List[str] = []
    width = length = None
    if method == "linear":
        width = _dim(profile.get("width"), dims)
        length = _dim(profile.get("length"), dims)
        if width is None:
            missing.append("cut width rule")
        if length is None:
            missing.append("cut length rule")
    elif method == "from_wire_blank":
        if not wire_cut:
            missing.append("the wire blank this media is cut from")
        else:
            width = wire_cut[0] + (finite(profile.get("width_add")) or 0.0)
            length = wire_cut[1] + (finite(profile.get("length_add")) or 0.0)
    elif method in ("triangular_v", "segments"):
        straight = _dim(profile.get("straight_dimension_mm"), dims)
        if straight is None:
            missing.append("straight cage dimension")
        if method == "triangular_v":
            n = positive_int(profile.get("v_count"))
            span = _dim(profile.get("usable_span_mm"), dims)
            depth = _dim(profile.get("peak_to_trough_mm"), dims)
            if not n:
                missing.append("number of Vs")
            if span is None or span <= 0:
                missing.append("usable span across the Vs")
            if depth is None or depth <= 0:
                missing.append("peak-to-trough depth")
            developed = None
            if n and span and span > 0 and depth and depth > 0:
                developed = developed_triangular(span, depth, n)
        else:
            developed = developed_segments(profile.get("segments"))
            if not developed:
                missing.append("cross-section segments")
        if straight is not None and developed:
            lw = _sum_allowances(profile.get("width_allowances_mm"))
            ll = _sum_allowances(profile.get("length_allowances_mm"))
            bend = finite(profile.get("bend_correction_mm") or 0)
            if lw is None or ll is None or bend is None:
                missing.append("allowances")
            else:
                width = straight + lw
                length = developed + ll + bend
    elif method == "flat":
        uw = _dim(profile.get("usable_width_mm"), dims)
        ul = _dim(profile.get("usable_length_mm"), dims)
        lw = _sum_allowances(profile.get("width_allowances_mm"))
        ll = _sum_allowances(profile.get("length_allowances_mm"))
        if uw is None or ul is None:
            missing.append("confirmed usable media width and length")
        elif lw is None or ll is None:
            missing.append("allowances")
        else:
            width, length = uw + lw, ul + ll
    else:
        missing.append(f"a cut method (profile says {method!r})")
    if missing or width is None or length is None:
        return None, missing
    if width <= 0 or length <= 0:
        return None, ["a cut size above zero (the profile gives "
                      f"{width:g} x {length:g})"]
    width = _apply_increment(width, profile, "width")
    length = _apply_increment(length, profile, "length")
    return (width, length), []


# ── Pieces, areas, weights, roll fit ────────────────────────────────────────

def _roll_fit(width: float, length: float, roll_w: Optional[float],
              roll_l: Optional[float], rotation_allowed: bool) -> str:
    if not roll_w or not roll_l:
        return "not_configured"
    if width <= roll_w and length <= roll_l:
        return "fits"
    if rotation_allowed and length <= roll_w and width <= roll_l:
        return "fits_rotated"
    return "cut_does_not_fit_roll"


def _pieces(pieces: Iterable[Dict[str, Any]], rate: Optional[float],
            roll_w: Optional[float], roll_l: Optional[float],
            rotation_default: bool, errors: List[str], label: str
            ) -> List[Dict[str, Any]]:
    out = []
    for i, p in enumerate(pieces or [], start=1):
        w = positive(p.get("cut_width_mm"))
        l = positive(p.get("cut_length_mm"))
        n = positive_int(p.get("pieces_per_filter"))
        if w is None or l is None:
            errors.append(f"{label} piece {i}: cut width and length must be "
                          "more than zero")
            continue
        if n is None:
            errors.append(f"{label} piece {i}: pieces per filter must be a "
                          "whole number of 1 or more")
            continue
        rot = p.get("rotation_allowed")
        rot = rotation_default if rot is None else bool(rot)
        area = w * l / 1_000_000.0
        kg = area * rate if rate is not None else None
        out.append({
            "cut_width_mm": w, "cut_length_mm": l, "pieces_per_filter": n,
            "area_m2_per_piece": area,
            "kg_per_piece": kg,
            "area_m2_per_filter": area * n,
            "kg_contribution_per_filter": None if kg is None else kg * n,
            "rotation_allowed": rot,
            "roll_fit": _roll_fit(w, l, roll_w, roll_l, rot),
        })
    return out


def _installed(rule: Any, blank_kg: Optional[float], rate: Optional[float],
               missing: List[str], label: str) -> Optional[float]:
    """What stays in the filter, per filter, or None if nobody has said."""
    if isinstance(rule, str):
        rule = {"rule": rule}
    if not rule or not rule.get("rule"):
        missing.append(f"{label}: whether the whole blank stays in the filter, "
                       "or the area that is kept")
        return None
    if rule["rule"] == "full_blank":
        return blank_kg
    if rule["rule"] == "retained_area":
        area = positive(rule.get("retained_area_mm2_per_filter"))
        if area is None or rate is None:
            missing.append(f"{label}: retained area per filter")
            return None
        return area / 1_000_000.0 * rate
    missing.append(f"{label}: unknown retention rule {rule.get('rule')!r}")
    return None


def _component(name: str, required: bool, status: str,
               kg: Optional[float], **extra) -> Dict[str, Any]:
    row = {"name": name, "required": required, "status": status,
           "installed_kg_per_filter": kg}
    row.update(extra)
    return row


# ── The calculation ─────────────────────────────────────────────────────────

def _blank_result(request: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": "incomplete", "calc_version": CALC_VERSION,
        "errors": [], "missing": [], "notes": [],
        "construction": "", "filter_type": request.get("filter_type"),
        "width_mm": None, "height_mm": None, "nominal_depth_mm": None,
        "order_quantity": None,
        "wire": None, "media_components": [],
        "cut_mesh_area_m2_per_filter": None,
        "wire_blank_weight_kg_per_filter": None,
        "wire_blank_weight_kg_order": None,
        "installed_wire_weight_kg_per_filter": None,
        "installed_wire_weight_kg_order": None,
        "media_blank_weight_kg_per_filter": None,
        "media_blank_weight_kg_order": None,
        "installed_media_weight_kg_per_filter": None,
        "installed_media_weight_kg_order": None,
        "known_media_blank_subtotal_kg_per_filter": None,
        "known_media_installed_subtotal_kg_per_filter": None,
        "bracing": None, "components": [],
        "known_material_weight_kg_per_filter": None,
        "known_material_weight_kg_order": None,
        "included_components": [], "excluded_components": [],
        "complete_filter_weight_kg_per_filter": None,
        "complete_filter_weight_kg_order": None,
        "weight_complete": False,
        "provenance": {},
    }


def calculate(request: Dict[str, Any],
              settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Cut sizes and weights for one order line. See the module notes.

    request keys (all optional unless the part needs them):
      filter_type, width_mm, height_mm, nominal_depth_mm, order_quantity
      pleat_insert, header_only            as on the order line
      parts                                ["wire"], ["media"] or both
      wire: {profile_id, profile_version}  or  {pieces: [...], installed}
      wire_material_override               "LARGE_WIRE" / "SMALL_WIRE"
      media_code                           shorthand for one media component
      media_components: [{media_code, profile_id?, profile_version?,
                          pieces?, installed?}]
      components: [{name, kg_per_filter | not_applicable: true, required}]
      includes_mounting_frame, mounting_frame: {width_mm, height_mm}
    """
    s = settings if settings is not None else _settings.defaults()
    out = _blank_result(request)
    errors, missing = out["errors"], out["missing"]
    mats = s.get("materials") or _mat.default_settings()

    # Inputs ------------------------------------------------------------------
    construction = construction_of(request.get("filter_type"))
    out["construction"] = construction
    if request.get("filter_type") and not construction:
        errors.append(f"filter type {request.get('filter_type')!r} is not one "
                      "this calculator knows")

    def _req_dim(key: str, label: str) -> Optional[float]:
        if key not in request or request.get(key) in (None, ""):
            return None
        v = positive(request.get(key))
        if v is None:
            errors.append(f"{label} must be a number more than zero")
        return v

    w = _req_dim("width_mm", "width")
    h = _req_dim("height_mm", "height")
    d = _req_dim("nominal_depth_mm", "nominal depth")
    qty_raw = request.get("order_quantity", 1)
    qty = positive_int(1 if qty_raw in (None, "") else qty_raw)
    if qty is None:
        errors.append("order quantity must be a whole number of 1 or more")
    out.update(width_mm=w, height_mm=h, nominal_depth_mm=d,
               order_quantity=qty)
    dims: Dict[str, float] = {}
    if w is not None and h is not None:
        dims = {"width": w, "height": h, "short": min(w, h),
                "long": max(w, h)}
    if d is not None:
        dims["depth"] = d

    parts = request.get("parts") or ["wire", "media"]
    pleat = bool(request.get("pleat_insert"))
    header_only = bool(request.get("header_only"))
    profiles = all_profiles(s)
    required = list((s.get("required_components") or {}).get(construction)
                    or [])
    if pleat:
        required = [c for c in required if c not in ("filter_frame",)]
    if header_only:
        required = [c for c in required if c not in ("wire", "media")]
    if errors:
        out["status"] = "invalid_input"
        return out

    # Wire -------------------------------------------------------------------
    wire_cut: Optional[Tuple[float, float]] = None
    wire_needed = "wire" in parts and (
        "wire" in required or request.get("wire") is not None
        or request.get("wire_material_override"))
    if wire_needed and not header_only:
        wire_cut = _calc_wire(request, out, s, mats, profiles, construction,
                              dims, d, qty)

    # Media ------------------------------------------------------------------
    # The worksheet cuts V-form media from the wire blank's size. When only
    # the media was asked for, work out that blank's size (not its weight -
    # the wire's material does not matter to the media).
    if wire_cut is None and out["wire"] is None and dims and construction:
        wire_cut = _wire_geometry(request.get("wire") or {}, profiles,
                                  construction, dims, d)
    if "media" in parts and not header_only:
        comps = request.get("media_components")
        if comps is None and request.get("media_code") not in (None, ""):
            comps = [{"media_code": request.get("media_code")}]
        if comps is None and "media" in required:
            missing.append("which media this filter is made of")
        for comp in comps or []:
            out["media_components"].append(
                _calc_media(comp, s, mats, profiles, construction, dims, d,
                            qty, wire_cut))
        _sum_media(out, qty)

    # Bracing and the rest of the filter ---------------------------------------
    if construction and dims:
        brace_profile = (s.get("brace_profiles") or {}).get(construction)
        out["bracing"] = _bracing.evaluate(construction, dims["width"],
                                           dims["height"], brace_profile)
    _components(request, out, s, construction, required, dims, qty)

    # Status -----------------------------------------------------------------
    if out["errors"]:
        out["status"] = "invalid_input"
    elif out["weight_complete"]:
        out["status"] = "complete"
    elif out["known_material_weight_kg_per_filter"] is not None:
        out["status"] = "partial"
    else:
        out["status"] = "incomplete"
    out["provenance"] = {
        "calc_version": CALC_VERSION,
        "materials_version": mats.get("version"),
        "bracing_rule": _bracing.RULE_VERSION,
        "wire_rule": _mat.WIRE_RULE_VERSION,
        "settings": _settings.provenance(
            s, "materials", "cut_profiles", "component_profiles",
            "brace_profiles", "steel", "mounting_frame_profiles",
            "required_components"),
    }
    return out


def _calc_wire(request, out, s, mats, profiles, construction, dims, depth,
               qty) -> Optional[Tuple[float, float]]:
    wire_in = request.get("wire") or {}
    res: Dict[str, Any] = {
        "status": "complete", "code": None, "overridden": False,
        "selection": None, "profile_id": None, "profile_version": None,
        "measured_cut_pieces": False, "material": None, "pieces": [],
        "roll_fit_status": None, "missing": [], "basis": None,
    }
    out["wire"] = res

    # The material: an explicit choice, else the depth rule, else unknown.
    try:
        sel = _mat.select_wire(construction, depth,
                               override=request.get("wire_material_override"),
                               rules=s.get("wire_rules"))
    except _mat.MaterialError as exc:
        out["errors"].append(str(exc))
        res["status"] = "invalid_input"
        return None
    res["selection"] = sel
    res.update(code=sel["code"], overridden=sel["overridden"])
    material = None
    if sel["code"]:
        material = _mat.wire_material(sel["code"], mats)
        res["material"] = material
    else:
        res["missing"].append(sel["reason"])

    # The cut: measured pieces, a named profile, or the matching profile.
    profile = None
    cut = None
    pieces_in = wire_in.get("pieces")
    if pieces_in:
        res["measured_cut_pieces"] = True
        res["basis"] = "measured_cut_pieces"
    else:
        if wire_in.get("profile_id"):
            profile = find_profile(profiles, wire_in["profile_id"],
                                   wire_in.get("profile_version"))
            if profile is None:
                res["missing"].append(
                    f"wire profile {wire_in['profile_id']} "
                    f"v{wire_in.get('profile_version') or 'latest'} "
                    "does not exist")
            elif not profile.get("verified"):
                res["missing"].append(
                    f"wire profile {profile.get('id')} is not verified yet")
                profile = None
        elif construction:
            profile = match_profile(profiles, "wire", construction, depth)
            if profile is None:
                res["missing"].append(
                    f"a verified wire cut profile for "
                    f"{construction} at {f'{depth:g}' if depth else '?'}mm "
                    "deep")
        else:
            res["missing"].append("the filter type, to find its cut profile")
        if profile is not None:
            if not dims:
                res["missing"].append("the filter's width and height")
            else:
                cut, why = profile_cut(profile, dims)
                res["missing"].extend(f"wire profile {profile['id']}: {m}"
                                      for m in why)
                if cut:
                    res.update(profile_id=profile["id"],
                               profile_version=profile.get("version"),
                               basis=profile.get("basis"))
                    pieces_in = [{
                        "cut_width_mm": cut[0], "cut_length_mm": cut[1],
                        "pieces_per_filter": profile.get(
                            "pieces_per_filter", 1),
                        "rotation_allowed": profile.get("rotation_allowed"),
                    }]

    if not pieces_in:
        res["status"] = "needs_cut_rule"
        res["cut_width_mm"] = res["cut_length_mm"] = None
        out["missing"].extend(f"wire: {m}" for m in res["missing"])
        return None

    roll_w, roll_l = (material["roll_width_mm"], material["roll_length_mm"]) \
        if material else WIRE_ROLL_FALLBACK
    rate = material["kg_per_m2"] if material else None
    res["pieces"] = _pieces(pieces_in, rate, roll_w, roll_l, True,
                            out["errors"], "wire")
    if out["errors"]:
        res["status"] = "invalid_input"
        return None
    fits = [p["roll_fit"] for p in res["pieces"]]
    res["roll_fit_status"] = ("cut_does_not_fit_roll"
                              if "cut_does_not_fit_roll" in fits else
                              "fits")
    area = sum(p["area_m2_per_filter"] for p in res["pieces"])
    out["cut_mesh_area_m2_per_filter"] = area
    first = res["pieces"][0]
    wire_cut = (first["cut_width_mm"], first["cut_length_mm"])

    if res["roll_fit_status"] == "cut_does_not_fit_roll":
        res["status"] = "cut_does_not_fit_roll"
        msg = ("wire: a blank is wider than the 1200mm roll every way it may "
               "be cut - it needs a verified multi-piece or spliced profile")
        res["missing"].append(msg)
        out["missing"].append(msg)
        return wire_cut
    if rate is None:
        res["status"] = "needs_wire_rule"
        out["missing"].extend(f"wire: {m}" for m in res["missing"])
        return wire_cut

    blank = sum(p["kg_contribution_per_filter"] for p in res["pieces"])
    out["wire_blank_weight_kg_per_filter"] = blank
    out["wire_blank_weight_kg_order"] = blank * qty
    # Retention as confirmed on the line wins; otherwise the profile's.
    rule = wire_in.get("installed") or (profile or {}).get("installed")
    miss: List[str] = []
    installed = _installed(rule, blank, rate, miss, "wire")
    res["missing"].extend(miss)
    out["missing"].extend(miss)
    if installed is None:
        res["status"] = "blank_only"
    else:
        out["installed_wire_weight_kg_per_filter"] = installed
        out["installed_wire_weight_kg_order"] = installed * qty
    return wire_cut


def _wire_geometry(wire_in, profiles, construction, dims, depth
                   ) -> Optional[Tuple[float, float]]:
    """The first wire blank's size alone, for media cut from it."""
    pieces = wire_in.get("pieces")
    if pieces:
        w = positive(pieces[0].get("cut_width_mm"))
        l = positive(pieces[0].get("cut_length_mm"))
        return (w, l) if w and l else None
    if wire_in.get("profile_id"):
        profile = find_profile(profiles, wire_in["profile_id"],
                               wire_in.get("profile_version"))
        if profile is None or not profile.get("verified"):
            return None
    else:
        profile = match_profile(profiles, "wire", construction, depth)
    if profile is None:
        return None
    cut, _ = profile_cut(profile, dims)
    return cut


def _calc_media(comp, s, mats, profiles, construction, dims, depth, qty,
                wire_cut) -> Dict[str, Any]:
    res: Dict[str, Any] = {
        "status": "complete", "media_code": None, "material": None,
        "rate_kg_per_m2": None, "basis": None, "profile_id": None,
        "profile_version": None, "measured_cut_pieces": False,
        "pieces": [], "cut_area_m2_per_filter": None,
        "blank_weight_kg_per_filter": None, "blank_weight_kg_order": None,
        "installed_weight_kg_per_filter": None,
        "installed_weight_kg_order": None,
        "media_roll_fit_status": None, "missing": [], "errors": [],
    }
    try:
        code = _mat.normalise_media_code(comp.get("media_code"))
    except _mat.MaterialError as exc:
        res["status"] = "unsupported_media_code"
        res["errors"].append(str(exc))
        res["media_code"] = comp.get("media_code")
        return res
    material = _mat.media_material(code, mats)
    res.update(media_code=code, material=material,
               rate_kg_per_m2=material["kg_per_m2"], basis=material["basis"])

    pieces_in = comp.get("pieces")
    profile = None
    if pieces_in:
        res["measured_cut_pieces"] = True
    else:
        if comp.get("profile_id"):
            profile = find_profile(profiles, comp["profile_id"],
                                   comp.get("profile_version"))
            if profile is None or not profile.get("verified"):
                res["missing"].append(
                    f"media profile {comp['profile_id']} is missing or not "
                    "verified")
                profile = None
        elif construction:
            profile = match_profile(profiles, "media", construction, depth)
            if profile is None:
                res["missing"].append(
                    f"a verified media cut profile for {construction}"
                    + (f" at {depth:g}mm deep" if depth else ""))
        else:
            res["missing"].append("the filter type, to find its cut profile")
        if profile is not None:
            if not dims:
                res["missing"].append("the filter's width and height")
            else:
                cut, why = profile_cut(profile, dims, wire_cut)
                res["missing"].extend(f"media profile {profile['id']}: {m}"
                                      for m in why)
                if cut:
                    res.update(profile_id=profile["id"],
                               profile_version=profile.get("version"))
                    pieces_in = [{
                        "cut_width_mm": cut[0], "cut_length_mm": cut[1],
                        "pieces_per_filter": profile.get(
                            "pieces_per_filter", 1),
                        "rotation_allowed": profile.get("rotation_allowed"),
                    }]
    if not pieces_in:
        res["status"] = "needs_media_cut_rule"
        return res

    res["pieces"] = _pieces(pieces_in, material["kg_per_m2"],
                            positive(material.get("roll_width_mm")),
                            positive(material.get("roll_length_mm")),
                            False, res["errors"], f"media {code}")
    if res["errors"]:
        res["status"] = "invalid_input"
        return res
    fits = [p["roll_fit"] for p in res["pieces"]]
    if "not_configured" in fits:
        res["media_roll_fit_status"] = "not_configured"
    elif "cut_does_not_fit_roll" in fits:
        res["media_roll_fit_status"] = "cut_does_not_fit_roll"
    else:
        res["media_roll_fit_status"] = "fits"
    res["cut_area_m2_per_filter"] = sum(p["area_m2_per_filter"]
                                        for p in res["pieces"])
    if res["media_roll_fit_status"] == "cut_does_not_fit_roll":
        res["status"] = "cut_does_not_fit_roll"
        res["missing"].append(f"media {code}: a piece does not fit the roll")
        return res
    blank = sum(p["kg_contribution_per_filter"] for p in res["pieces"])
    res["blank_weight_kg_per_filter"] = blank
    res["blank_weight_kg_order"] = blank * qty
    rule = comp.get("installed") or (profile or {}).get("installed")
    installed = _installed(rule, blank, material["kg_per_m2"], res["missing"],
                           f"media {code}")
    if installed is None:
        res["status"] = "blank_only"
    else:
        res["installed_weight_kg_per_filter"] = installed
        res["installed_weight_kg_order"] = installed * qty
    return res


def _sum_media(out: Dict[str, Any], qty: int) -> None:
    comps = out["media_components"]
    if not comps:
        return
    for c in comps:
        out["missing"].extend(f"media: {m}" for m in c["missing"])
        if c["status"] in ("invalid_input", "unsupported_media_code"):
            out["errors"].extend(f"media: {e}" for e in c["errors"])
    blanks = [c["blank_weight_kg_per_filter"] for c in comps]
    known_blank = [b for b in blanks if b is not None]
    if known_blank:
        out["known_media_blank_subtotal_kg_per_filter"] = sum(known_blank)
    if known_blank and len(known_blank) == len(blanks):
        out["media_blank_weight_kg_per_filter"] = sum(known_blank)
        out["media_blank_weight_kg_order"] = sum(known_blank) * qty
    inst = [c["installed_weight_kg_per_filter"] for c in comps]
    known_inst = [i for i in inst if i is not None]
    if known_inst:
        out["known_media_installed_subtotal_kg_per_filter"] = sum(known_inst)
    if known_inst and len(known_inst) == len(inst):
        out["installed_media_weight_kg_per_filter"] = sum(known_inst)
        out["installed_media_weight_kg_order"] = sum(known_inst) * qty


def channel_length_mm(dims: Dict[str, float],
                      profile: Optional[Dict[str, Any]] = None) -> float:
    """Channel in one frame: every side cut 2mm under its size, plus the two
    20mm lips of a U with its cap (cutting.py). A G is one lip, 20mm less;
    the U is used so the weight never comes out light."""
    p = profile or {}
    allow = finite(p.get("side_allowance_mm"))
    allow = 2.0 if allow is None else allow
    lip = finite(p.get("lip_mm"))
    lip = 20.0 if lip is None else lip
    lips = positive_int(p.get("lips")) or 2
    return (2 * (dims["width"] - allow) + 2 * (dims["height"] - allow)
            + lips * lip)


def _depth_key(depth: Any) -> str:
    d = finite(depth)
    return "" if d is None else f"{d:g}"


def _channel_kg(p: Dict[str, Any], dims: Dict[str, float]) -> Optional[float]:
    """kg per metre of this depth's channel x the channel in one frame."""
    rates = p.get("kg_per_m_by_depth") or {}
    rate = positive(rates.get(_depth_key(dims.get("depth"))))
    if rate is None:
        return None
    return rate * channel_length_mm(dims, p) / 1000.0


def _profile_component(name: str, construction: str,
                       profiles: Iterable[Dict[str, Any]],
                       dims: Dict[str, float]
                       ) -> Tuple[Optional[float], str, Dict[str, Any]]:
    """A frame or similar part from a verified component profile."""
    for p in profiles or []:
        if p.get("name") != name or not p.get("verified"):
            continue
        if construction not in (p.get("constructions") or [construction]):
            continue
        method = p.get("method")
        if method == "measured_each":
            kg = positive(p.get("kg_each"))
        elif method == "channel_per_m" and dims:
            kg = _channel_kg(p, dims)
        elif method == "per_perimeter_m" and dims:
            rate = positive(p.get("kg_per_m"))
            kg = None if rate is None else \
                rate * 2 * (dims["width"] + dims["height"]) / 1000.0
        elif method == "per_face_m2" and dims:
            rate = positive(p.get("kg_per_m2"))
            kg = None if rate is None else \
                rate * dims["width"] * dims["height"] / 1_000_000.0
        else:
            kg = None
        if kg is not None:
            return kg, "known", {"profile_id": p.get("id"),
                                 "profile_version": p.get("version"),
                                 "basis": p.get("basis")}
    return None, "unknown", {}


FRAMED_IN_CHANNEL = ("Flat Panel", "Header", "V-form")


def _cchannel_frame(request: Dict[str, Any], construction: str,
                    dims: Dict[str, float], s: Dict[str, Any]
                    ) -> Tuple[Optional[float], Dict[str, Any]]:
    """The frame's steel channel, from the cut list the filter calculator
    makes it with (a U unless the line says otherwise) and the C-channel
    for its depth."""
    if construction not in FRAMED_IN_CHANNEL or request.get("pleat_insert") \
            or "width" not in dims or dims.get("depth") is None:
        return None, {}
    method = str(request.get("frame_method") or "u")
    cut = _cch.frame_cut_list(dims["width"], dims["height"], method,
                              dims["depth"])
    r = _cch.frame_weight(cut, 1, s)
    extra = {"basis": "c_channel", "frame_method": method,
             "sections": r["sections"],
             "c_channel_version": r["settings_version"],
             "warnings": r["calculation_warnings"]}
    return r["frame_weight_kg"], extra


def _frame_missing(name: str, dims: Dict[str, float]) -> str:
    if name == "filter_frame" and dims.get("depth") is not None:
        return (f"filter frame: kg per metre of {_depth_key(dims['depth'])}mm "
                "channel")
    if name == "flyscreen_frame":
        return "flyscreen frame: kg per metre of flyscreen frame"
    return f"{name.replace('_', ' ')}: a verified weight profile"


def _components(request, out, s, construction, required, dims, qty) -> None:
    comps: List[Dict[str, Any]] = []
    missing = out["missing"]

    if "wire" in required or out.get("wire"):
        kg = out["installed_wire_weight_kg_per_filter"]
        comps.append(_component("wire", "wire" in required,
                                "known" if kg is not None else "unknown", kg))
    if "media" in required or out["media_components"]:
        kg = out["installed_media_weight_kg_per_filter"]
        comps.append(_component("media", "media" in required,
                                "known" if kg is not None else "unknown", kg))

    optional = [c for c in ((s.get("counted_if_known") or {}).get(construction)
                            or []) if c not in required]
    if request.get("pleat_insert"):
        optional = [c for c in optional if c != "filter_frame"]
    for name in ("filter_frame", "flyscreen_frame", "flyscreen_part"):
        if name not in required and name not in optional:
            continue
        kg, status, extra = _profile_component(
            name, construction, s.get("component_profiles"), dims)
        if kg is None and name == "filter_frame":
            kg, extra = _cchannel_frame(request, construction, dims, s)
            status = "known" if kg is not None else "unknown"
        if name in required:
            if kg is None:
                missing.append(_frame_missing(name, dims))
            comps.append(_component(name, True, status, kg, **extra))
        elif kg is not None:
            comps.append(_component(name, False, status, kg, **extra))

    if "braces" in optional:
        # Counted when one is needed and its weight is known; otherwise left
        # out rather than holding up the weight.
        b = out.get("bracing") or {}
        prof = (s.get("brace_profiles") or {}).get(construction) or {}
        each = positive(prof.get("kg_each_including_fixings"))
        count = b.get("count")
        if b.get("status") == "ok" and b.get("required") and each is not None \
                and count:
            comps.append(_component(
                "braces", False, "known", each * count, count=count,
                kg_each=each, profile_version=prof.get("version")))

    if "braces" in required:
        b = out.get("bracing")
        if not b or b.get("status") != "ok":
            comps.append(_component("braces", True, "unknown", None))
            missing.append("braces: bracing could not be checked")
        elif not b["required"]:
            comps.append(_component("braces", True, "not_applicable", 0.0,
                                    reason="no brace required"))
        else:
            prof = (s.get("brace_profiles") or {}).get(construction) or {}
            each = positive(prof.get("kg_each_including_fixings"))
            count = b.get("count")
            if each is None or not count:
                need = []
                if not count:
                    need.append("how many braces")
                if each is None:
                    need.append("brace weight with its fixings")
                missing.append("braces: " + " and ".join(need))
                comps.append(_component("braces", True, "unknown", None,
                                        count=count))
            else:
                comps.append(_component(
                    "braces", True, "known", each * count, count=count,
                    kg_each=each, profile_version=prof.get("version")))

    if request.get("includes_mounting_frame"):
        mf = request.get("mounting_frame") or {}
        mw = mf.get("width_mm", dims.get("width"))
        mh = mf.get("height_mm", dims.get("height"))
        prof = _frames.profile_for(positive(mw) or 0, positive(mh) or 0,
                                   s.get("mounting_frame_profiles"))
        r = _frames.calculate(mw, mh, 1, prof, s.get("steel"))
        kg = r["mounting_frame_weight_kg_each"]
        if kg is None:
            missing.extend(f"mounting frame: {m}" for m in r["missing"])
        comps.append(_component("mounting_frame", True,
                                "known" if kg is not None else "unknown", kg,
                                detail=r))

    for extra in request.get("components") or []:
        name = str(extra.get("name") or "component")
        req = bool(extra.get("required", True))
        if extra.get("not_applicable"):
            comps.append(_component(name, req, "not_applicable", 0.0))
            continue
        kg = finite(extra.get("kg_per_filter"))
        if kg is None or kg < 0:
            comps.append(_component(name, req, "unknown", None))
            if req:
                missing.append(f"{name}: its weight")
        else:
            comps.append(_component(name, req, "known", kg,
                                    basis=extra.get("basis")))

    out["components"] = comps
    known = [c for c in comps if c["status"] in ("known", "not_applicable")]
    unknown_required = [c for c in comps
                        if c["required"] and c["status"] == "unknown"]
    out["included_components"] = [c["name"] for c in known]
    out["excluded_components"] = [c["name"] for c in comps
                                  if c["status"] == "unknown"]
    if known and any(c["status"] == "known" for c in known):
        total = sum(c["installed_kg_per_filter"] or 0.0 for c in known)
        out["known_material_weight_kg_per_filter"] = total
        out["known_material_weight_kg_order"] = total * qty
    # Complete only when the construction is known (so we know what it is
    # made of) and nothing it is made of is unknown.
    if construction and comps and not unknown_required \
            and all(n in [c["name"] for c in comps] for n in required):
        total = sum(c["installed_kg_per_filter"] or 0.0 for c in comps
                    if c["status"] in ("known", "not_applicable"))
        out["complete_filter_weight_kg_per_filter"] = total
        out["complete_filter_weight_kg_order"] = total * qty
        out["weight_complete"] = True


# ── The worksheet's columns ─────────────────────────────────────────────────

def worksheet_cuts(short: int, long_: int, channel: int, label: str
                   ) -> Tuple[int, int, int, int]:
    """(wire width, wire length, media width, media length) as the worksheet
    prints them in its WIRE CUT and MEDIA CUT columns.

    In-band sizes come from the built-in profiles above, so the sheet and
    the calculator share one formula. Out of band the sheet keeps printing
    what it always printed - a V deeper than 100 uses the 85-100 formula, a
    depth with no band prints the filter's own size - because changing a
    printed cut size is not this function's call to make. The calculator
    block underneath says plainly that those sizes have no verified rule.
    """
    lbl = str(label).upper()
    dims = {"short": float(short), "long": float(long_),
            "width": float(short), "height": float(long_)}

    def _cut(pid: str, wire=None):
        prof = find_profile(BUILTIN_PROFILES, pid)
        cut, _ = profile_cut(prof, dims, wire)
        return cut

    if lbl.startswith("F"):
        wc = _cut("TAF-WS-FLAT")
        mc = _cut("TAF-WS-FLAT-MEDIA")
        return int(wc[0]), int(wc[1]), int(mc[0]), int(mc[1])
    if lbl.startswith("V"):
        prof = match_profile(BUILTIN_PROFILES, "wire", "V-form",
                             float(min(channel, 100)))
        if prof is None:
            return short, long_, short + 60, long_ + 40
        wc = _cut(prof["id"])
        mc = _cut(prof["id"] + "-MEDIA", wc)
        return int(wc[0]), int(wc[1]), int(mc[0]), int(mc[1])
    return short, long_, short, long_


# ── Working from an order line ──────────────────────────────────────────────

def request_from_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """A calculator request for a saved filter line, using what it records.

    The order stores Short, Long and Channel. Any measured cuts, chosen
    profiles or overrides staff have saved on the line ride along under
    "Calculator", so the worksheet, the packing plan and the labels all
    calculate from the same inputs.
    """
    saved = dict(item.get("Calculator") or {})
    req: Dict[str, Any] = {
        "filter_type": item.get("Filter Type"),
        "width_mm": item.get("Short"),
        "height_mm": item.get("Long"),
        "nominal_depth_mm": item.get("Channel"),
        "order_quantity": item.get("Quantity"),
        "pleat_insert": bool(item.get("Pleat Insert")),
        "header_only": bool(item.get("Header")),
    }
    media = str(item.get("Media Type") or "").strip()
    if media and "media_components" not in saved:
        comp = {"media_code": media}
        for key in ("media_profile_id", "media_profile_version"):
            if saved.get(key):
                comp[key.replace("media_", "")] = saved[key]
        req["media_components"] = [comp]
    for key in ("wire", "wire_material_override", "media_components",
                "components", "includes_mounting_frame", "mounting_frame"):
        if key in saved:
            req[key] = saved[key]
    if item.get("Frame Method"):
        req["frame_method"] = str(item["Frame Method"])
    return req


def calculate_item(item: Dict[str, Any],
                   settings: Optional[Dict[str, Any]] = None,
                   prefer: str = "") -> Dict[str, Any]:
    """A saved line, with its frame weighed the way the worksheet says to
    make it (the filter calculator's choice, or the customer's)."""
    req = request_from_item(item)
    if "frame_method" not in req:
        req["frame_method"] = frame_method_for(item, prefer)
    return calculate(req, settings)


def frame_method_for(item: Dict[str, Any], prefer: str = "") -> str:
    """U, Sideways U, G or L - what the worksheet prints for this line."""
    from . import cutting as _cut
    try:
        from . import features as _features
        workshop = _features.workshop()
    except Exception:
        workshop = None
    try:
        qty = max(1, int(float(item.get("Quantity") or 1)))
        answer = _cut.best(float(item.get("Short") or 0),
                           float(item.get("Long") or 0), qty, workshop, None,
                           prefer or "")
        if answer.get("ok"):
            return answer["best"]["method"]
    except (TypeError, ValueError):
        pass
    return "u"


def parse_pieces(text: str) -> List[Dict[str, Any]]:
    """ "600 x 1000 x 2; 300x400" -> measured pieces (the last number is how
    many per filter, 1 if left off). Raises ValueError with the bad part."""
    out = []
    for chunk in str(text or "").replace("×", "x").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = [p.strip() for p in chunk.lower().split("x")]
        if len(parts) not in (2, 3):
            raise ValueError(f"Write a piece as width x length x how many "
                             f"(not {chunk!r}).")
        w, l = positive(parts[0]), positive(parts[1])
        n = positive_int(parts[2]) if len(parts) == 3 else 1
        if w is None or l is None or n is None:
            raise ValueError(f"{chunk!r} needs sizes above zero and a whole "
                             "number of pieces.")
        out.append({"cut_width_mm": w, "cut_length_mm": l,
                    "pieces_per_filter": n})
    return out
