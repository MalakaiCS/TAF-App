"""What the worksheet prints under Notes: wrapping, then the calculator.

Two blocks, each its own box below the Notes line - never text added to the
Notes field, which keeps exactly what somebody typed there.

    WRAPPING INSTRUCTIONS   every filter page. From the line's saved
                            packing plan - the same plan the delivery labels
                            print from - so the sheet, the bundles and the
                            labels cannot disagree.
    FILTER CALCULATOR       Flat Panel and Pleated Panel (V-form) pages.
                            Which way to make the frame - U, Sideways U or
                            G - from the filter calculator (cutting.py), and
                            which row of marks on the sheet that is. Weights
                            stay on screen; they are not the floor's question.

These functions only work out the words. pdf_generator draws them.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import bracing as _bracing
from . import calc_settings as _settings
from . import cutting as _cutting
from . import filter_calc as _calc
from . import order_packing as _op
from .numbers import kg_text

Line = Tuple[str, bool]          # (text, bold)


def order_context(items: Sequence[Dict[str, Any]],
                  settings: Optional[Dict[str, Any]] = None
                  ) -> List[Dict[str, Any]]:
    """Per line: its packing evaluation, wrap codes and calculation.

    Worked out across the whole order, so the codes printed on a sheet are
    the codes on the labels.
    """
    s = settings if settings is not None else _settings.cached()
    try:
        wraps = _op.order_wraps(items, s)
        lines = wraps["lines"]
    except Exception:
        lines = [{"eval": None, "wraps": []} for _ in items]
    out = []
    for item, line in zip(items, lines):
        # Codes worked out across the whole order (order_packing.stamp_codes)
        # win over ones worked out across just the lines on this worksheet.
        stamped = item.get("_wrap_codes")
        if stamped and len(stamped) == len(line.get("wraps") or []):
            for wrap, code in zip(line["wraps"], stamped):
                wrap["code"] = code
        calc = (line.get("eval") or {}).get("calc")
        if calc is None and item.get("Filter Type"):
            try:
                calc = _calc.calculate_item(item, s)
            except Exception:
                calc = None
        out.append({"eval": line.get("eval"), "wraps": line.get("wraps") or [],
                    "calc": calc})
    return out


def wrapping_lines(ctx: Dict[str, Any]) -> List[Line]:
    ev = ctx.get("eval") or {}
    plan = ev.get("plan") or {}
    wraps = ctx.get("wraps") or []
    if not plan or not wraps:
        issues = ev.get("issues") or ["No packing plan yet."]
        return [("SET BEFORE PACKING: " + issues[0], True)]
    out: List[Line] = []
    for text in ev.get("instructions") or []:
        out.append((text, True))
    mode = "Set by the office" if plan.get("mode") == "manual" else \
        "Automatic"
    codes = [w.get("code") for w in wraps if w.get("code")]
    span = f"{codes[0]} to {codes[-1]}" if len(codes) > 1 else \
        (codes[0] if codes else "")
    detail = f"{mode} - {len(wraps)} wrap{'' if len(wraps) == 1 else 's'}"
    if span:
        detail += f", labels {span}"
    weighed = [w for w in wraps if (w.get("weight") or {}).get("source")
               == "measured"]
    if weighed:
        detail += f", {len(weighed)} weighed"
    out.append((detail, False))
    status = ev.get("status")
    if status == "needs_weight_check":
        out.append(("WEIGH EACH WRAP - the bundle weight is not known yet "
                    "(10 kg max)", True))
    for issue in (ev.get("issues") or [])[:2]:
        if status != "needs_weight_check" or "weight is not known" not in issue:
            out.append(("CHECK: " + issue, True))
    return out


def _cut(p: Dict[str, Any]) -> str:
    return (f"{p['pieces_per_filter']} x {p['cut_width_mm']:g} x "
            f"{p['cut_length_mm']:g} mm")


def calculator_lines(ctx: Dict[str, Any], qty: Any = None) -> List[Line]:
    r = ctx.get("calc")
    if not r:
        return [("Not calculated for this line.", False)]
    if r.get("status") == "invalid_input":
        return [("CHECK INPUTS: " + "; ".join(r.get("errors") or []), True)]
    out: List[Line] = []
    w = r.get("wire")
    if w:
        code = w.get("code") or "wire not chosen"
        if w.get("overridden"):
            code += " (chosen)"
        if w.get("pieces"):
            p = w["pieces"][0]
            src = ("measured" if w.get("measured_cut_pieces") else
                   f"{w.get('profile_id')} v{w.get('profile_version')}")
            text = (f"Wire {code}: {_cut(p)} ({src}), "
                    f"{r['cut_mesh_area_m2_per_filter']:.3f} m2")
            if r.get("wire_blank_weight_kg_per_filter") is not None:
                text += (f", blank {kg_text(r['wire_blank_weight_kg_per_filter'])}"
                         " kg/filter")
            out.append((text, False))
        else:
            out.append((f"Wire {code}: no verified cut rule", True))
    for m in r.get("media_components") or []:
        code = m.get("media_code") or "?"
        if m.get("pieces"):
            p = m["pieces"][0]
            text = (f"Media {code} ({kg_text(m.get('rate_kg_per_m2'))} kg/m2): "
                    f"{_cut(p)}, {m['cut_area_m2_per_filter']:.3f} m2")
            if m.get("blank_weight_kg_per_filter") is not None:
                text += f", blank {kg_text(m['blank_weight_kg_per_filter'])} kg"
            if m.get("media_roll_fit_status") == "not_configured":
                text += ", roll size not set"
            out.append((text, False))
        else:
            label = {"unsupported_media_code": "no weight on file for it"}\
                .get(m.get("status"), "no verified cut rule")
            out.append((f"Media {code}: {label}", True))
    b = r.get("bracing")
    if b:
        out.append(("Bracing: " + (b.get("message") or ""),
                    bool(b.get("required") or b.get("advisory")
                         or b.get("status") != "ok")))
    q = r.get("order_quantity") or 1
    if r.get("weight_complete"):
        out.append((f"Complete weight {kg_text(r['complete_filter_weight_kg_per_filter'])}"
                    f" kg each, {kg_text(r['complete_filter_weight_kg_order'])}"
                    f" kg for {q}", True))
    else:
        known = r.get("known_material_weight_kg_per_filter")
        blanks = [v for v in (r.get("wire_blank_weight_kg_per_filter"),
                              r.get("media_blank_weight_kg_per_filter"))
                  if v is not None]
        if known is not None:
            out.append((f"Known so far {kg_text(known)} kg each "
                        "(subtotal - not the filter weight)", False))
        elif blanks:
            out.append((f"Blanks {kg_text(sum(blanks))} kg each, "
                        f"{kg_text(sum(blanks) * q)} kg for {q} "
                        "(cut sizes only - not the filter weight)", False))
        missing = list(dict.fromkeys(r.get("missing") or []))
        if missing:
            shown = missing[:3]
            more = len(missing) - len(shown)
            out.append(("Weight incomplete - needs: " + "; ".join(shown)
                        + (f"; +{more} more" if more > 0 else ""), True))
    return out


# Which row of marks on the sheet each way of making the frame is. The
# worksheet prints all three: the top row is a U, FLIPPED a Sideways U and
# REVERSED a G (cutting.py reproduces those marks exactly).
MARK_ROWS = {"u": "top row of marks", "sideways_u": "FLIPPED marks",
             "g": "REVERSED marks"}


def frame_lines(item: Dict[str, Any], prefer: str = "",
                workshop: Optional[Dict[str, float]] = None) -> List[Line]:
    """What to mark this filter as: U, Sideways U or G, and the lip when it
    has to be trimmed to fit one more on a length."""
    try:
        short = float(item.get("Short") or 0)
        long_ = float(item.get("Long") or 0)
        qty = max(1, int(float(item.get("Quantity") or 1)))
    except (TypeError, ValueError):
        return []
    if short <= 0 or long_ <= 0:
        return []
    try:
        answer = _cutting.best(short, long_, qty, workshop, None, prefer or "")
    except ValueError:
        return []
    if not answer.get("ok"):
        return [("CHECK: " + str(answer.get("why") or "cannot be made from "
                                 "one length"), True)]
    won = answer["best"]
    text = f"MARK AS {won['name'].upper()}"
    row = MARK_ROWS.get(won["method"])
    if row:
        text += f" - use the {row}"
    out: List[Line] = [(text, True)]
    if won["shortened"] and qty > 1:
        full = won["frames_per_stick"] * len(
            [b for b in won["frame_sticks"] if len(b["pieces"])
             == won["frames_per_stick"]])
        out.append((f"Lip {won['lip']:g}mm instead of "
                    f"{won['full']['lip']:g}mm on the full lengths "
                    f"({full} of {qty}) - fits {won['frames_per_stick']} "
                    "a length", True))
    if answer.get("forced"):
        out.append(("The customer asks for this way.", False))
    return out


def brace_cell(ctx: Dict[str, Any]) -> Tuple[str, str]:
    """(short label for the Y/N box, the exact notice) for BRACE REQ?."""
    r = ctx.get("calc") or {}
    b = r.get("bracing")
    if not b:
        return "", ""
    return _bracing.short_label(b), b.get("message") or ""


def shows_calculator(item: Dict[str, Any]) -> bool:
    """Flat Panel and Pleated Panel (V-form, which part_numbers already calls
    a pleated panel) worksheets - not flyscreens."""
    return _calc.construction_of(item.get("Filter Type")) in (
        "Flat Panel", "V-form", "Header", "Stepped Filter")
