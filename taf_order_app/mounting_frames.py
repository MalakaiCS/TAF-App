"""What a galvanised steel mounting frame weighs.

A mounting frame is cut from 2.0mm steel, the same material as the rest of
the steel stock. Its weight is the steel that stays in the finished frame:

    steel kg = retained flat area (mm2) x 2.0 mm x density (kg/m3) / 1e9

which, for a strip folded up into a side, is

    piece kg = developed flat width x retained length x 2.0 x density / 1e9

and for a piece described by its solid cross-section instead,

    piece kg = cross-section area (mm2) x length (mm) x density / 1e9

What is NOT known yet, and so is not filled in:

  * The cross-section. Nothing in the program records how wide the strip is
    before it is folded, so there is no developed width to multiply. The
    frames are a different, heavier section from the filter-frame channel,
    so the channel's numbers are no substitute.
  * The density of the steel stock as TAF has confirmed it.

The sizes ARE known - 610 x 610 is a catalogue size, and the compressor
packs list theirs - so each of those has a profile waiting to be completed.
Until a profile and a density are entered, a mounting frame answers
"needs_mounting_frame_profile" with what is missing, and anything that adds
weights up treats it as unknown rather than as nothing.

Offcuts and stock waste are never in here. They are what buying the steel
costs, not what the frame weighs on a scale.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional

from .numbers import positive, positive_int

THICKNESS_MM = 2.0
RULE_VERSION = "TAF-MOUNTING-FRAME-2026-10"


def known_sizes() -> List[Dict[str, Any]]:
    """Every mounting-frame size the program already lists, without duplicates.

    Read from the catalogue and the compressor packs rather than copied, so a
    size added there shows up here too.
    """
    sizes: Dict[tuple, Dict[str, Any]] = {}
    try:
        from .bag_filler import STANDARD_SIZES
        for label, w, h, _d in STANDARD_SIZES.get("Mounting Frame", []):
            if w and h:
                key = (min(w, h), max(w, h))
                sizes.setdefault(key, {"width_mm": w, "height_mm": h,
                                       "source": f"catalogue: {label.strip()}"})
    except Exception:
        pass
    # The compressor packs live in the window's module. Read them only when
    # the window is already running: a calculation must never start one.
    import sys
    gui = sys.modules.get("modern_order_gui") or sys.modules.get("__main__")
    packs = getattr(gui, "DEDICATED_FILTER_PACKS", {}) or {}
    for model, pack in packs.items():
        for frame in pack.get("frames") or []:
            s, l = frame.get("short"), frame.get("long")
            if s and l:
                sizes.setdefault((min(s, l), max(s, l)),
                                 {"width_mm": s, "height_mm": l,
                                  "source": f"compressor pack {model}"})
    return [sizes[k] for k in sorted(sizes)]


def _num(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _length(spec: Any, width: float, height: float) -> Optional[float]:
    """A length given outright, or as a side plus or minus something."""
    if isinstance(spec, dict):
        base = {"width": width, "height": height,
                "short": min(width, height), "long": max(width, height)
                }.get(str(spec.get("from", "")))
        if base is None:
            return None
        mult = _num(spec.get("multiply", 1)) or 0.0
        add = _num(spec.get("add", 0)) or 0.0
        return base * mult + add
    return _num(spec)


def profile_for(width_mm: float, height_mm: float,
                profiles: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The verified profile for a size: an exact size first, then a rule that
    covers custom sizes. Width and height may be either way round."""
    key = (min(width_mm, height_mm), max(width_mm, height_mm))
    rule = None
    for p in profiles or []:
        if not p.get("verified"):
            continue
        for size in p.get("sizes") or []:
            try:
                if (min(size), max(size)) == key:
                    return p
            except (TypeError, ValueError):
                continue
        if p.get("custom_sizes") and rule is None:
            rule = p
    return rule


def calculate(width_mm: Any, height_mm: Any, quantity: Any = 1,
              profile: Optional[Dict[str, Any]] = None,
              steel: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Weigh one mounting-frame line. Never guesses a missing number."""
    out: Dict[str, Any] = {
        "status": "complete", "errors": [], "missing": [],
        "thickness_mm": THICKNESS_MM, "rule_version": RULE_VERSION,
        "width_mm": None, "height_mm": None, "quantity": None,
        "profile_id": None, "profile_version": None,
        "steel": None, "pieces": [], "hardware": [],
        "mounting_frame_weight_kg_each": None,
        "mounting_frame_weight_kg_order": None,
        "basis": None,
    }
    w, h = positive(width_mm), positive(height_mm)
    if w is None or h is None:
        out["errors"].append("width and height must both be more than zero")
    qty = positive_int(1 if quantity is None else quantity)
    if qty is None:
        out["errors"].append("quantity must be a whole number of 1 or more")
    out.update(width_mm=w, height_mm=h, quantity=qty)
    if out["errors"]:
        out["status"] = "invalid_input"
        return out

    density = _num((steel or {}).get("density_kg_m3"))
    out["steel"] = {
        "density_kg_m3": density if density and density > 0 else None,
        "basis": (steel or {}).get("basis"),
        "version": (steel or {}).get("version"),
        "material": (steel or {}).get("material") or "galvanised steel stock",
    }
    if not density or density <= 0:
        out["missing"].append("steel density (kg/m3) for the steel stock")
    if not profile:
        out["missing"].append(
            f"a verified mounting-frame profile for {w:g} x {h:g} "
            "(strip width before folding, side lengths, corners, holes, "
            "hardware)")
    if out["missing"]:
        out["status"] = "needs_mounting_frame_profile"
        return out

    out.update(profile_id=profile.get("id"),
               profile_version=profile.get("version"),
               basis=profile.get("basis") or "verified_profile")
    t = _num(profile.get("thickness_mm")) or THICKNESS_MM
    if abs(t - THICKNESS_MM) > 1e-9:
        out["errors"].append(
            f"profile {profile.get('id')} is {t:g}mm; mounting frames are "
            f"{THICKNESS_MM:g}mm")
        out["status"] = "invalid_input"
        return out

    steel_each = 0.0
    for piece in profile.get("pieces") or []:
        name = str(piece.get("name") or "piece")
        try:
            count = int(piece.get("qty", 1))
        except (TypeError, ValueError):
            count = 0
        length = _length(piece.get("retained_length_mm"), w, h)
        dev = _num(piece.get("developed_flat_width_mm"))
        section = _num(piece.get("cross_section_area_mm2"))
        if count < 1 or length is None or length <= 0 or (
                (dev is None or dev <= 0) and (section is None or section <= 0)):
            out["missing"].append(f"{name}: length, quantity and either strip "
                                  "width or cross-section")
            continue
        if dev and dev > 0:
            area = dev * length
            kg = area * t * density / 1e9
            how = "developed_flat_width"
        else:
            area = None
            kg = section * length * density / 1e9
            how = "cross_section"
        out["pieces"].append({"name": name, "qty": count,
                              "retained_length_mm": length,
                              "developed_flat_width_mm": dev,
                              "cross_section_area_mm2": section,
                              "retained_flat_area_mm2": area,
                              "kg_each_piece": kg, "kg_per_frame": kg * count,
                              "method": how})
        steel_each += kg * count

    # Holes and notches come out; overlaps that stay in go in. Both are
    # areas of 2mm plate, as the profile records them.
    removed = _num(profile.get("removed_area_mm2")) or 0.0
    overlap = _num(profile.get("retained_overlap_area_mm2")) or 0.0
    steel_each += (overlap - removed) * t * density / 1e9

    hardware_each = 0.0
    for item in profile.get("hardware") or []:
        kg = _num(item.get("kg_each"))
        try:
            count = int(item.get("qty", 1))
        except (TypeError, ValueError):
            count = 0
        if kg is None or kg < 0 or count < 0:
            out["missing"].append(f"hardware {item.get('name')}: weight")
            continue
        out["hardware"].append({"name": item.get("name"), "qty": count,
                                "kg_each": kg, "kg_per_frame": kg * count})
        hardware_each += kg * count

    if not out["pieces"]:
        out["missing"].append("the profile lists no steel pieces")
    if out["missing"]:
        out["status"] = "needs_mounting_frame_profile"
        return out
    each = steel_each + hardware_each
    out["mounting_frame_weight_kg_each"] = each
    out["mounting_frame_weight_kg_order"] = each * qty
    return out


def order_total(lines: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Several sizes on one order: each unrounded unit weight times its own
    quantity, then added. Unknown if any line is unknown."""
    total, known, unknown = 0.0, [], []
    for r in lines:
        kg = r.get("mounting_frame_weight_kg_order")
        if kg is None:
            unknown.append(r)
        else:
            known.append(r)
            total += kg
    return {"mounting_frame_weight_kg_order": None if unknown else total,
            "known_kg": total, "known_lines": len(known),
            "unknown_lines": len(unknown)}
