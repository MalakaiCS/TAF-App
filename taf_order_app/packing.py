"""How an order line is split into wrapped bundles, and what each is called.

Limits
------
A wrapped bundle may weigh 10 kg at most, wrapping included. Exactly 10 kg
is fine; anything over it is split, and every bundle that comes out of the
split is checked again. Weights are compared raw - a 10.004 kg bundle that
would display as "10.00" is still over.

The weight is not the only limit. Some filters are too big or awkward to
wrap many of together however light they are, so a handling profile can cap
a size (412 x 412 x 90: five at most, as supplied). Staff can also set a
lower number for a line or flag it as awkward. Each of those can only make
bundles smaller - nothing here lets a known overweight bundle through.

A bundle size is the largest whole number of filters that satisfies every
limit that applies. The line is then split into as many full bundles as fit
and a remainder, and the remainder is weighed on its own - its own wrapping,
its own count - not as a share of the line.

When the weight cannot be known (a filter part nobody has weighed, or a
wrapping weight nobody has confirmed), a handling limit can still propose
bundles, but the plan says needs_weight_check and the labels leave the
weight blank to be written in. A large order with no weight and no handling
limit at all gets no plan rather than one huge bundle.

One filter that is over the limit on its own cannot be split. That is a
single_item_exception: somebody has to decide how it is handled, and the
plan says so rather than pretending.

Wrap pages
----------
Every line on the order is one "page", in order, even when two lines are the
same size. One line on its own: 1 of 2, 2 of 2. Several lines: the line
number, a letter when that line has more than one wrap, and the number of
lines - 1A/2, 1B/2, 2/2. After Z comes AA, AB.

Codes are worked out from the whole order before anything is chosen to
print, so reprinting wrap 1B prints 1B.

Saved plans
-----------
A plan is saved on its order line with a stable id per wrap, so a measured
weight belongs to that physical bundle. Changing the quantities makes new
wraps with new ids; the old ones, with whatever was measured against them,
move to the plan's history rather than being copied onto bundles they were
never weighed as.
"""
from __future__ import annotations

import math
import re
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from .numbers import finite, non_negative, positive, positive_int

RULE_VERSION = "TAF-PACKING-2026-10"
MAX_BUNDLE_KG = 10.0
_EPS = 1e-9


class PackingError(ValueError):
    """A packing plan that cannot be right as entered."""


# ── Splitting and checking quantities ───────────────────────────────────────

def split(quantity: int, capacity: int) -> List[int]:
    """12 at 5 a wrap -> [5, 5, 2]."""
    q, c = positive_int(quantity), positive_int(capacity)
    if q is None:
        raise PackingError("The quantity has to be a whole number of 1 or more.")
    if c is None:
        raise PackingError("Filters per wrap has to be a whole number of 1 or more.")
    full, rest = divmod(q, c)
    return [c] * full + ([rest] if rest else [])


def check_quantities(wrap_quantities: Sequence[Any], quantity: int) -> List[int]:
    """Explicit wrap sizes: each a whole number, adding up to the line."""
    if not isinstance(wrap_quantities, (list, tuple)) or not wrap_quantities:
        raise PackingError("Give at least one wrap.")
    out = []
    for i, q in enumerate(wrap_quantities, start=1):
        n = positive_int(q) if not isinstance(q, str) else None
        if n is None:
            raise PackingError(f"Wrap {i} has to hold a whole number of 1 or "
                               f"more filters (it says {q!r}).")
        out.append(n)
    if sum(out) != quantity:
        raise PackingError(f"The wraps hold {sum(out)} filters but the line is "
                           f"for {quantity}.")
    return out


def resolve_quantities(quantity: Any, wrap_quantities: Any = None,
                       max_per_wrap: Any = None) -> Optional[List[int]]:
    """Explicit wraps, or a split by a maximum, or None to plan automatically.
    Giving both is refused: two answers to one question."""
    q = positive_int(quantity)
    if q is None:
        raise PackingError("The quantity has to be a whole number of 1 or more.")
    if wrap_quantities is not None and max_per_wrap is not None:
        raise PackingError("Give the wrap quantities or a maximum per wrap, "
                           "not both.")
    if wrap_quantities is not None:
        return check_quantities(wrap_quantities, q)
    if max_per_wrap is not None:
        cap = positive_int(max_per_wrap) if not isinstance(
            max_per_wrap, str) else None
        if cap is None:
            raise PackingError("The maximum per wrap has to be a whole number "
                               "of 1 or more.")
        return split(q, cap)
    return None


# ── Wrap pages ──────────────────────────────────────────────────────────────

def letters(n: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA, 28 -> AB, 702 -> ZZ, 703 -> AAA."""
    if n < 1:
        raise ValueError("letters start at 1")
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def wrap_codes(wraps_per_line: Sequence[int]) -> List[List[str]]:
    """The wrap-page code for every wrap of every line, in order."""
    lines = len(wraps_per_line)
    if lines == 1:
        n = wraps_per_line[0]
        return [[f"{i} of {n}" for i in range(1, n + 1)]]
    out = []
    for line_no, n in enumerate(wraps_per_line, start=1):
        if n == 1:
            out.append([f"{line_no}/{lines}"])
        else:
            out.append([f"{line_no}{letters(i)}/{lines}"
                        for i in range(1, n + 1)])
    return out


# ── What the wrapping weighs ────────────────────────────────────────────────

def packaging_kg(spec: Any, quantity: int) -> Optional[float]:
    """The wrapping's weight for a bundle of `quantity`, or None if unknown.

    Unconfirmed is unknown, never zero. Zero is fine once somebody has
    confirmed it. Accepted shapes:
        {"confirmed": True, "base_kg": a, "per_filter_kg": b}   a + b x qty
        {"confirmed": True, "by_quantity": {"1": x, "2": y}}    a table
        a function of the quantity
    """
    if callable(spec):
        value = spec(quantity)
        return non_negative(value)
    if not isinstance(spec, dict) or not spec.get("confirmed"):
        return None
    table = spec.get("by_quantity")
    if isinstance(table, dict):
        return non_negative(table.get(str(quantity), table.get(quantity)))
    base = non_negative(spec.get("base_kg", 0))
    per = non_negative(spec.get("per_filter_kg", 0))
    if base is None or per is None:
        return None
    return base + per * quantity


def bundle_kg(unit_kg: Optional[float], quantity: int, packaging: Any
              ) -> Optional[float]:
    if unit_kg is None:
        return None
    pack = packaging_kg(packaging, quantity)
    if pack is None:
        return None
    return unit_kg * quantity + pack


def weight_capacity(unit_kg: Optional[float], packaging: Any, upto: int,
                    max_kg: float = MAX_BUNDLE_KG) -> Optional[int]:
    """The most filters one bundle can hold by weight: 0 if even one is over,
    None if the weight cannot be known."""
    if unit_kg is None or unit_kg < 0:
        return None
    if packaging_kg(packaging, 1) is None:
        return None
    # A fixed wrapping weight has a closed form; anything that changes with
    # the count is tried count by count.
    fixed = isinstance(packaging, dict) and "by_quantity" not in packaging \
        and not non_negative(packaging.get("per_filter_kg", 0))
    if fixed and unit_kg > 0:
        base = packaging_kg(packaging, 0) or 0.0
        n = math.floor((max_kg - base) / unit_kg + _EPS)
        return max(0, min(n, upto))
    best = 0
    for q in range(1, upto + 1):
        kg = bundle_kg(unit_kg, q, packaging)
        if kg is None:
            return None
        if kg <= max_kg + _EPS:
            best = q
    return best


def handling_limit(width_mm: Any, height_mm: Any, depth_mm: Any,
                   construction: str,
                   profiles: Iterable[Dict[str, Any]]
                   ) -> Optional[Dict[str, Any]]:
    """The handling profile for this size, if one has been set. Width and
    height either way round; depth exactly."""
    w, h, d = positive(width_mm), positive(height_mm), positive(depth_mm)
    if w is None or h is None:
        return None
    for p in profiles or []:
        if not p.get("verified"):
            continue
        match = p.get("match") or {}
        mw, mh = positive(match.get("width_mm")), positive(match.get("height_mm"))
        if mw is None or mh is None:
            continue
        if (min(mw, mh), max(mw, mh)) != (min(w, h), max(w, h)):
            continue
        md = positive(match.get("depth_mm"))
        if md is not None and md != d:
            continue
        if match.get("construction") and match["construction"] != construction:
            continue
        if positive_int(p.get("max_per_wrap")):
            return p
    return None


# ── Proposing and checking plans ────────────────────────────────────────────

def _wrap_rows(quantities: Sequence[int], group: Optional[str], unit_kg,
               packaging, max_kg) -> List[Dict[str, Any]]:
    rows = []
    for q in quantities:
        pack = packaging_kg(packaging, q)
        raw = bundle_kg(unit_kg, q, packaging)
        rows.append({"quantity": q, "group": group,
                     "packaging_kg": pack, "raw_kg": raw,
                     "over_limit": raw is not None and raw > max_kg + _EPS})
    return rows


# Filters per wrap when nothing else sets it: no weight to work from and no
# handling limit for the size. Settings can change it.
FALLBACK_MAX_PER_WRAP = 5


def propose(quantity: Any, unit_kg: Optional[float] = None,
            packaging: Any = None, handling_max: Any = None,
            staff_max: Any = None, groups: Optional[Sequence[Dict]] = None,
            max_kg: float = MAX_BUNDLE_KG,
            fallback_max: Any = None) -> Dict[str, Any]:
    """The automatic plan for a line. Always a plan: a line with no weight
    and no handling limit is wrapped `fallback_max` at a time (five unless
    set), and flagged for its wraps to be weighed."""
    q = positive_int(quantity)
    if q is None:
        raise PackingError("The quantity has to be a whole number of 1 or more.")
    unit = finite(unit_kg)
    limits = {"max_kg": max_kg, "weight": weight_capacity(unit, packaging, q,
                                                           max_kg),
              "handling": positive_int(handling_max),
              "staff": positive_int(staff_max)}
    out: Dict[str, Any] = {"rule_version": RULE_VERSION, "quantity": q,
                           "limits": limits, "capacity": None, "wraps": [],
                           "issues": [], "status": "ok", "compliant": False}
    group_list = _check_groups(groups, q)

    if limits["weight"] == 0:
        # One filter alone is over. It cannot be split, and it cannot be
        # put with another, so each goes on its own and somebody decides.
        out["status"] = "single_item_exception"
        out["capacity"] = 1
        one = bundle_kg(unit, 1, packaging)
        out["issues"].append(
            f"One filter with its wrapping weighs {one:.3f} kg, over the "
            f"{max_kg:g} kg limit on its own. It cannot be split - decide how "
            "it is handled.")
        for g in group_list:
            out["wraps"] += _wrap_rows([1] * g["quantity"], g["name"], unit,
                                       packaging, max_kg)
        return out

    caps = [c for c in (limits["weight"], limits["handling"], limits["staff"])
            if c is not None]
    weight_known = limits["weight"] is not None
    if not caps:
        caps = [1 if q == 1 else
                (positive_int(fallback_max) or FALLBACK_MAX_PER_WRAP)]
    cap = min(caps)
    out["capacity"] = cap
    for g in group_list:
        out["wraps"] += _wrap_rows(split(g["quantity"], cap), g["name"], unit,
                                   packaging, max_kg)
    if not weight_known:
        out["status"] = "needs_weight_check"
        out["issues"].append(
            "The bundle weight is not known yet - weigh the wrapped bundles "
            "before calling this packing done.")
    out["compliant"] = weight_known and not any(w["over_limit"]
                                                for w in out["wraps"])
    return out


def _check_groups(groups: Optional[Sequence[Dict]], quantity: int
                  ) -> List[Dict[str, Any]]:
    """Customer area groups, adding up to the line. None means one group."""
    if not groups:
        return [{"name": None, "quantity": quantity}]
    out, seen = [], set()
    for i, g in enumerate(groups, start=1):
        name = str((g or {}).get("name") or "").strip()
        n = positive_int((g or {}).get("quantity"))
        if not name:
            raise PackingError(f"Area {i} needs a name.")
        if name.lower() in seen:
            raise PackingError(f"There are two areas called {name}.")
        if n is None:
            raise PackingError(f"{name} has to be a whole number of 1 or more "
                               "filters.")
        seen.add(name.lower())
        out.append({"name": name, "quantity": n})
    total = sum(g["quantity"] for g in out)
    if total != quantity:
        raise PackingError(f"The areas add up to {total} filters but the line "
                           f"is for {quantity}.")
    return out


def check_plan(wraps: Sequence[Dict[str, Any]], quantity: Any,
               unit_kg: Optional[float] = None, packaging: Any = None,
               handling_max: Any = None, staff_max: Any = None,
               groups: Optional[Sequence[Dict]] = None,
               max_kg: float = MAX_BUNDLE_KG) -> Dict[str, Any]:
    """Check a plan somebody set by hand against the same limits.

    The plan is never changed here. Anything over a limit is listed, and a
    revised proposal is offered alongside it for staff to accept or not.
    """
    q = positive_int(quantity)
    if q is None:
        raise PackingError("The quantity has to be a whole number of 1 or more.")
    quantities = check_quantities([w.get("quantity") for w in wraps], q)
    group_list = _check_groups(groups, q)
    names = {g["name"] for g in group_list}
    if groups:
        for g in group_list:
            held = sum(w["quantity"] for w in wraps
                       if w.get("group") == g["name"])
            if held != g["quantity"]:
                raise PackingError(f"The wraps for {g['name']} hold {held} "
                                   f"filters; it asked for {g['quantity']}.")
        stray = [w for w in wraps if w.get("group") not in names]
        if stray:
            raise PackingError("Every wrap has to belong to one of the areas.")

    unit = finite(unit_kg)
    hmax, smax = positive_int(handling_max), positive_int(staff_max)
    issues: List[str] = []
    rows = []
    for i, w in enumerate(wraps, start=1):
        n = quantities[i - 1]
        raw = bundle_kg(unit, n, packaging)
        measured = positive(w.get("measured_weight_kg"))
        over = (raw is not None and raw > max_kg + _EPS) or \
            (measured is not None and measured > max_kg + _EPS)
        if hmax and n > hmax:
            issues.append(f"Wrap {i} holds {n}; this size is handled {hmax} "
                          "at most.")
        if smax and n > smax:
            issues.append(f"Wrap {i} holds {n}; the limit set for this line "
                          f"is {smax}.")
        if raw is not None and raw > max_kg + _EPS:
            issues.append(f"Wrap {i} would weigh {raw:.3f} kg, over "
                          f"{max_kg:g} kg.")
        if measured is not None and measured > max_kg + _EPS:
            issues.append(f"Wrap {i} was weighed at {measured:g} kg, over "
                          f"{max_kg:g} kg - repack and reweigh it.")
        rows.append({"quantity": n, "group": w.get("group"), "raw_kg": raw,
                     "packaging_kg": packaging_kg(packaging, n),
                     "over_limit": over})
    out = {"ok": not issues, "issues": issues, "wraps": rows,
           "weight_known": all(r["raw_kg"] is not None for r in rows),
           "proposal": None}
    if issues:
        try:
            out["proposal"] = propose(q, unit, packaging, hmax, smax,
                                      groups, max_kg)
        except PackingError:
            out["proposal"] = None
    return out


# ── Saved plans ─────────────────────────────────────────────────────────────

def new_wrap_id() -> str:
    return "W" + uuid.uuid4().hex[:10].upper()


def _same_layout(a: Sequence[Dict], b: Sequence[Dict]) -> bool:
    return [(w.get("quantity"), w.get("group")) for w in a] == \
        [(w.get("quantity"), w.get("group")) for w in b]


def make_plan(rows: Sequence[Dict[str, Any]], mode: str,
              previous: Optional[Dict[str, Any]] = None, by: str = "",
              at: str = "", groups: Optional[Sequence[Dict]] = None,
              max_per_wrap: Any = None, reason: str = "") -> Dict[str, Any]:
    """The plan to save on the line.

    If the wraps are the same as before - same quantities, same areas, same
    order - the old wraps are kept with their ids and measurements. If not,
    the old ones go into the history and the new ones start with nothing
    measured: a weight belongs to the bundle it was taken from.
    """
    if mode not in ("automatic", "manual"):
        raise PackingError("Packing is either automatic or manual.")
    prev = previous or {}
    history = list(prev.get("history") or [])
    old = list(prev.get("wraps") or [])
    if old and _same_layout(old, rows):
        wraps = [dict(o) for o in old]
    else:
        if old:
            history.append({"at": at, "by": by,
                            "reason": reason or "the wraps changed",
                            "wraps": old})
        wraps = [{"id": new_wrap_id(), "quantity": r["quantity"],
                  "group": r.get("group"), "measured_weight_kg": None,
                  "measured_weight_text": None, "measured_at": None,
                  "measured_by": None, "packaging_weight_kg": None,
                  "awkward": False}
                 for r in rows]
    return {"rule_version": RULE_VERSION, "mode": mode,
            "max_per_wrap": positive_int(max_per_wrap),
            "groups": [dict(g) for g in (groups or [])],
            "wraps": wraps, "history": history,
            "updated_at": at, "updated_by": by}


def record_weight(plan: Dict[str, Any], wrap_id: str, text: str,
                  by: str = "", at: str = "") -> Dict[str, Any]:
    """A weighed bundle. The text is kept as typed so "3.20" prints 3.2 and
    "3.25" prints 3.25 - its precision is the scale's, not ours."""
    text = str(text or "").strip()
    value = positive(text) if text else None
    if text and value is None:
        raise PackingError("A weight has to be a number above zero.")
    out = dict(plan)
    out["wraps"] = []
    found = False
    for w in plan.get("wraps") or []:
        w = dict(w)
        if w.get("id") == wrap_id:
            found = True
            w.update(measured_weight_kg=value,
                     measured_weight_text=text or None,
                     measured_at=at if text else None,
                     measured_by=by if text else None)
        out["wraps"].append(w)
    if not found:
        raise PackingError("That wrap is not on this plan any more.")
    return out


# ── The worksheet's wording ─────────────────────────────────────────────────

def instruction(quantities: Sequence[int]) -> str:
    """[3, 3, 3] -> (Wrap 3 Filters x 3); [5, 5, 2] ->
    (Wrap 5 Filters x 2 + Wrap 2 Filters x 1)."""
    counts: Dict[int, int] = {}
    for q in quantities:
        counts[q] = counts.get(q, 0) + 1
    parts = [f"Wrap {q} Filter{'' if q == 1 else 's'} x {n}"
             for q, n in counts.items()]
    return "(" + " + ".join(parts) + ")" if parts else ""


def plan_instructions(plan: Dict[str, Any]) -> List[str]:
    """One line per area, or one line for the whole filter line."""
    wraps = plan.get("wraps") or []
    groups = plan.get("groups") or []
    if not groups:
        return [instruction([w["quantity"] for w in wraps])]
    out = []
    for g in groups:
        mine = [w["quantity"] for w in wraps if w.get("group") == g["name"]]
        out.append(f"{g['name']}: {g['quantity']} filters "
                   f"{instruction(mine)}")
    return out


# ── Reading what the office typed ───────────────────────────────────────────

def parse_quantities(text: str) -> List[int]:
    """ "5, 5, 2" or "5 5 2" -> [5, 5, 2]. Refuses anything that is not a
    list of whole numbers."""
    parts = [p for p in str(text or "").replace(",", " ").split() if p]
    out = []
    for p in parts:
        n = positive_int(p)
        if n is None:
            raise PackingError(f"{p!r} is not a whole number of filters.")
        out.append(n)
    if not out:
        raise PackingError("Type the number of filters in each wrap, e.g. 5, 5, 2.")
    return out


def quantities_from_form(quantity: int, per_wrap: Any = None,
                         wraps: Any = None, explicit: str = "") -> List[int]:
    """The wraps the office asked for, from whichever boxes were filled in.

        explicit "5, 5, 2"          exactly those
        per_wrap 3, wraps 3         [3, 3, 3] - and it must add up
        per_wrap 5 alone            12 -> [5, 5, 2]
        wraps 3 alone               10 -> [4, 3, 3], as even as it goes
    """
    q = positive_int(quantity)
    if q is None:
        raise PackingError("The line has no quantity.")
    if str(explicit or "").strip():
        return check_quantities(parse_quantities(explicit), q)
    per = positive_int(per_wrap) if str(per_wrap or "").strip() else None
    count = positive_int(wraps) if str(wraps or "").strip() else None
    if str(per_wrap or "").strip() and per is None:
        raise PackingError("Filters per wrap has to be a whole number.")
    if str(wraps or "").strip() and count is None:
        raise PackingError("The number of wraps has to be a whole number.")
    if per and count:
        if per * count != q:
            raise PackingError(f"{count} wraps of {per} is {per * count} "
                               f"filters; the line is for {q}.")
        return [per] * count
    if per:
        return split(q, per)
    if count:
        if count > q:
            raise PackingError(f"{count} wraps is more than the {q} filters.")
        base, extra = divmod(q, count)
        return [base + 1] * extra + [base] * (count - extra)
    raise PackingError("Fill in filters per wrap, the number of wraps, or "
                       "the quantity in each wrap.")


def parse_groups(text: str) -> List[Dict[str, Any]]:
    """ "Area A = 10; Area B = 10" -> [{"name": "Area A", "quantity": 10}, ...].
    Blank means no areas."""
    out = []
    for chunk in re.split(r"[;\n]+", str(text or "")):
        chunk = chunk.strip().strip(",")
        if not chunk:
            continue
        m = re.match(r"^(.*?)[=:]\s*(\d+)\s*$", chunk)
        if not m or not m.group(1).strip():
            raise PackingError(f"Write each area as a name and a number, like "
                               f"\"Area A = 10\" (not {chunk!r}).")
        out.append({"name": m.group(1).strip(), "quantity": int(m.group(2))})
    return out


def grouped_rows(groups: Sequence[Dict[str, Any]], per_wrap: Any
                 ) -> List[Dict[str, Any]]:
    """Wraps for each area: each area split by `per_wrap`, or kept whole.
    An area's wraps all stay that area's."""
    per = positive_int(per_wrap) if str(per_wrap or "").strip() else None
    rows = []
    for g in groups:
        sizes = split(g["quantity"], per) if per else [g["quantity"]]
        rows += [{"quantity": n, "group": g["name"]} for n in sizes]
    return rows
