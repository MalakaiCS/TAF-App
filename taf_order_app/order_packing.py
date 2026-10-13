"""Packing plans for saved orders: the bridge between an order and its labels.

Each order line keeps its plan under item["Packing"] (see packing.make_plan),
saved with the order through the normal save, so the floor sees what the
office set and the labels, the worksheet and the packing screen all read the
same wraps.

A line's plan is either:

  manual     set by the office - kept exactly as entered and checked against
             the limits. A problem is shown with a revised proposal next to
             it; the plan itself is never quietly changed.
  automatic  worked out from the weight and the handling limit. Re-worked
             whenever the order is saved, and if the wraps come out
             differently the old ones go to history with anything measured
             against them.

Weights on a label, per wrap, in this order:

  1. what that wrap was weighed at, wrapping included, as it was typed;
  2. otherwise the complete filter weight x the wrap's own count, plus its
     wrapping, if both are known;
  3. otherwise blank, to be written in by hand.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import calc_settings as _settings
from . import filter_calc as _calc
from . import packing as _pk
from .numbers import positive, positive_int, trim_zeros


def _quantity(item: Dict[str, Any]) -> Optional[int]:
    return positive_int(item.get("Quantity", item.get("quantity")))


def line_dims(item: Dict[str, Any]) -> Tuple[Any, Any, Any]:
    """(width, height, depth) as printed: Short x Long x Channel for a filter
    line, width x height x depth for a bag-style line."""
    if "Short" in item or "Long" in item:
        return item.get("Short"), item.get("Long"), item.get("Channel")
    return item.get("width"), item.get("height"), item.get("depth")


def evaluate_line(item: Dict[str, Any], settings: Dict[str, Any],
                  calc: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Where this line's packing stands, without saving anything."""
    qty = _quantity(item)
    out: Dict[str, Any] = {"quantity": qty, "plan": None, "saved": False,
                           "changed": False, "status": "ok", "issues": [],
                           "proposal": None, "check": None, "unit_kg": None,
                           "handling_profile": None, "calc": calc,
                           "instructions": []}
    if qty is None:
        out.update(status="invalid_input",
                   issues=["The line has no quantity."])
        return out
    if calc is None and ("Filter Type" in item):
        try:
            calc = _calc.calculate_item(item, settings)
        except Exception:
            calc = None
        out["calc"] = calc
    unit = (calc or {}).get("complete_filter_weight_kg_per_filter")
    out["unit_kg"] = unit
    w, h, d = line_dims(item)
    construction = _calc.construction_of(item.get("Filter Type")) \
        if item.get("Filter Type") else ""
    hp = _pk.handling_limit(w, h, d, construction,
                            settings.get("handling_profiles"))
    out["handling_profile"] = hp
    hmax = hp.get("max_per_wrap") if hp else None
    saved = item.get("Packing") or None
    packaging = settings.get("packaging")
    max_kg = float(settings.get("max_bundle_kg") or _pk.MAX_BUNDLE_KG)
    staff_max = (saved or {}).get("max_per_wrap")
    groups = (saved or {}).get("groups") or None

    if saved and saved.get("mode") == "manual":
        out.update(plan=saved, saved=True)
        try:
            check = _pk.check_plan(saved.get("wraps") or [], qty, unit,
                                   packaging, hmax, staff_max, groups, max_kg)
        except _pk.PackingError as exc:
            out.update(status="invalid_plan", issues=[str(exc)])
            return out
        out["check"] = check
        out["issues"] = list(check["issues"])
        out["proposal"] = check["proposal"]
        if check["issues"]:
            out["status"] = "conflict"
        elif not check["weight_known"]:
            out["status"] = "needs_weight_check"
    else:
        try:
            prop = _pk.propose(qty, unit, packaging, hmax, staff_max, groups,
                               max_kg)
        except _pk.PackingError as exc:
            out.update(status="invalid_plan", issues=[str(exc)])
            return out
        out["proposal"] = prop
        out["status"] = prop["status"]
        out["issues"] = list(prop["issues"])
        if prop["wraps"]:
            plan = _pk.make_plan(prop["wraps"], "automatic", previous=saved,
                                 groups=groups, max_per_wrap=staff_max,
                                 reason="the automatic plan changed")
            if saved:
                plan["updated_at"] = saved.get("updated_at", "")
                plan["updated_by"] = saved.get("updated_by", "")
            out["plan"] = plan
            out["saved"] = bool(saved) and \
                [x.get("id") for x in plan["wraps"]] == \
                [x.get("id") for x in (saved.get("wraps") or [])]
            out["changed"] = not out["saved"]
        # Measured weights over the limit still flag the saved wraps.
        for i, wrap in enumerate((out["plan"] or {}).get("wraps") or [], 1):
            kg = positive(wrap.get("measured_weight_kg"))
            if kg is not None and kg > max_kg + 1e-9:
                out["issues"].append(f"Wrap {i} was weighed at {kg:g} kg, "
                                     f"over {max_kg:g} kg - repack and "
                                     "reweigh it.")
                out["status"] = "conflict"
    if out["plan"]:
        out["instructions"] = _pk.plan_instructions(out["plan"])
    return out


def refresh_items(items: Sequence[Dict[str, Any]], settings: Dict[str, Any],
                  by: str = "", at: str = "") -> Tuple[List[Dict], bool]:
    """Items with every automatic plan brought up to date, for saving.

    Manual plans are left exactly as they are. Returns (items, changed).
    """
    out, changed = [], False
    for item in items:
        item = dict(item)
        if _quantity(item) is None:
            out.append(item)
            continue
        ev = evaluate_line(item, settings)
        if ev["plan"] and ev["changed"]:
            plan = dict(ev["plan"])
            plan.update(updated_at=at, updated_by=by)
            item["Packing"] = plan
            changed = True
        out.append(item)
    return out, changed


def set_manual(item: Dict[str, Any], quantities: Sequence[Any],
               groups: Optional[Sequence[Dict]] = None,
               group_of_wrap: Optional[Sequence[Optional[str]]] = None,
               max_per_wrap: Any = None, by: str = "", at: str = ""
               ) -> Dict[str, Any]:
    """The office's own plan for a line. Raises PackingError if it does not
    add up; limits are checked separately (evaluate_line) and shown."""
    qty = _quantity(item)
    if qty is None:
        raise _pk.PackingError("The line has no quantity.")
    q = _pk.check_quantities(list(quantities), qty)
    rows = [{"quantity": n,
             "group": (group_of_wrap[i] if group_of_wrap else None)}
            for i, n in enumerate(q)]
    _pk.check_plan(rows, qty, groups=groups)          # sums and areas only
    return _pk.make_plan(rows, "manual", previous=item.get("Packing"),
                         groups=groups, max_per_wrap=max_per_wrap, by=by,
                         at=at, reason="the office changed the packing")


def set_automatic(item: Dict[str, Any], settings: Dict[str, Any],
                  max_per_wrap: Any = None,
                  groups: Optional[Sequence[Dict]] = None,
                  awkward: bool = False, by: str = "", at: str = ""
                  ) -> Optional[Dict[str, Any]]:
    """Hand a line back to automatic packing, optionally with a lower limit."""
    work = dict(item)
    prev = dict(item.get("Packing") or {})
    prev.update(mode="automatic", max_per_wrap=positive_int(max_per_wrap),
                groups=[dict(g) for g in (groups or [])])
    work["Packing"] = prev
    ev = evaluate_line(work, settings)
    if not ev["plan"]:
        return None
    plan = dict(ev["plan"])
    plan.update(updated_at=at, updated_by=by, awkward=bool(awkward))
    return plan


def stamp_codes(items: Sequence[Dict[str, Any]],
                settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Copies of the items, each carrying "_wrap_codes": its wraps' codes as
    numbered across the WHOLE order.

    A mixed order prints its filter worksheet from the filter lines alone,
    but its labels number every line. Stamping the codes first means the
    sheet prints the codes the labels will. Not saved: strip_codes() takes
    them off again, because the codes follow from the lines and are worked
    out afresh whenever the lines change.
    """
    out = [dict(i) for i in items]
    try:
        lines = order_wraps(out, settings)["lines"]
    except Exception:
        return out
    for item, line in zip(out, lines):
        item["_wrap_codes"] = [w.get("code") for w in line["wraps"]]
    return out


def strip_codes(items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{k: v for k, v in i.items() if k != "_wrap_codes"} for i in items]


# ── Weights on the labels ───────────────────────────────────────────────────

def round_package(raw: float, policy: str) -> str:
    """Display a calculated package weight. Rounding, if any, happens once,
    here, on the gross total."""
    if policy == "up_0.1":
        return f"{math.ceil(round(raw * 10, 9)) / 10:.1f}"
    return f"{raw:.3f}"


def resolve_wrap_weight(wrap: Dict[str, Any], unit_kg: Optional[float],
                        packaging: Any, policy: str = "none"
                        ) -> Dict[str, Any]:
    q = positive_int(wrap.get("quantity")) or 0
    measured = positive(wrap.get("measured_weight_kg"))
    if measured is not None:
        text = str(wrap.get("measured_weight_text") or "").strip() or \
            repr(measured)
        return {"raw_kg": measured, "display": trim_zeros(text),
                "source": "measured", "missing": []}
    missing = []
    if unit_kg is None:
        missing.append("a complete filter weight")
    per_wrap = wrap.get("packaging_weight_kg")
    if per_wrap is not None and wrap.get("packaging_confirmed"):
        pack = positive(per_wrap) if per_wrap else 0.0
    else:
        pack = _pk.packaging_kg(packaging, q)
    if pack is None:
        missing.append("the wrapping's weight")
    if missing:
        return {"raw_kg": None, "display": "", "source": "unknown",
                "missing": missing}
    raw = unit_kg * q + pack
    return {"raw_kg": raw, "display": round_package(raw, policy),
            "source": "calculated", "missing": []}


def order_wraps(items: Sequence[Dict[str, Any]],
                settings: Optional[Dict[str, Any]] = None
                ) -> Dict[str, Any]:
    """Every wrap of every line, with its code and weight.

    Codes are worked out across the whole order here, before anybody picks
    which labels to print, so a reprint of one wrap keeps its code.
    """
    s = settings if settings is not None else _settings.defaults()
    lines, problems = [], []
    for idx, item in enumerate(items, start=1):
        ev = evaluate_line(item, s)
        plan = ev["plan"]
        if not plan or not plan.get("wraps"):
            problems.append({"line": idx, "issues": ev["issues"] or
                             ["no packing plan"], "status": ev["status"]})
            lines.append({"line": idx, "item": item, "eval": ev, "wraps": []})
            continue
        wraps = []
        for w in plan["wraps"]:
            weight = resolve_wrap_weight(w, ev["unit_kg"], s.get("packaging"),
                                         s.get("shipping_rounding") or "none")
            wraps.append(dict(w, weight=weight))
        lines.append({"line": idx, "item": item, "eval": ev, "wraps": wraps})
    codes = _pk.wrap_codes([max(1, len(l["wraps"])) for l in lines])
    for line, line_codes in zip(lines, codes):
        for wrap, code in zip(line["wraps"], line_codes):
            wrap["code"] = code
    return {"lines": lines, "problems": problems}
