"""Whether a filter needs a brace, from its finished face size.

Every rule here is "greater than", strictly. A 700mm side does not exceed
700, and a 1300mm side does not exceed 1300. The one inclusive band is the
narrow flyscreen, where 150mm and anything below it counts.

Width and height go in as given and are sorted into long and short first, so
600 x 1400 and 1400 x 600 always get the same answer.

What each construction gets:

    Flat Panel  both sides over 700        Brace Required, one brace
                long side over 1300        two braces, in Cross Format -
                                           this wins, even with a short side
                                           of 700 or less
    V-form      long over 1300 AND short   Brace Required. How many, and
                over 700                   how, comes from a verified
                                           profile, never from this rule
    Flyscreen   short side 150 or under,   "use brace in filter" - required
                or over 650
                long side over 1300        "consider bracing" - advice only;
                                           the required notice wins when both
                                           apply

A header is a flat panel made to sit on a bag (part_numbers says so and codes
it FPF), so it is braced as one. A construction with no rule - a stepped
filter, anything custom - comes back as needing a rule rather than as "no
brace": "nobody has decided" and "decided it doesn't need one" are different
answers and only one of them is safe to print.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional

RULE_VERSION = "TAF-BRACING-2026-10"

FLAT_BOTH_SIDES_OVER = 700.0
FLAT_LONG_OVER = 1300.0
VFORM_LONG_OVER = 1300.0
VFORM_SHORT_OVER = 700.0
FLYSCREEN_LONG_OVER = 1300.0
FLYSCREEN_NARROW_UP_TO = 150.0
FLYSCREEN_SHORT_OVER = 650.0

CROSS = "Cross Format"

# Constructions the rules above cover, under the names the app uses.
BRACED_AS = {
    "Flat Panel": "Flat Panel",
    "Header": "Flat Panel",
    "V-form": "V-form",
    "Flyscreen": "Flyscreen",
}


def _side(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def evaluate(construction: str, width_mm: Any, height_mm: Any,
             profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The bracing answer for one filter.

    `profile` is the verified brace profile for this construction, if there
    is one: it supplies the count and arrangement for V-form and flyscreen,
    where the rule only says a brace is needed.
    """
    out: Dict[str, Any] = {
        "status": "ok", "required": False, "advisory": False,
        "count": None, "arrangement": None, "message": "", "reason": "",
        "rule_version": RULE_VERSION, "construction": construction or "",
        "long_side_mm": None, "short_side_mm": None,
    }
    w, h = _side(width_mm), _side(height_mm)
    if w is None or h is None:
        out.update(status="invalid_input",
                   message="Bracing not checked - the size is missing",
                   reason="width and height must both be more than zero")
        return out
    long_side, short_side = max(w, h), min(w, h)
    out.update(long_side_mm=long_side, short_side_mm=short_side)

    rule = BRACED_AS.get(construction or "")
    if not rule:
        out.update(status="needs_rule",
                   message="Bracing not checked - no rule for this filter",
                   reason=f"no bracing rule has been set for "
                          f"{construction or 'an unknown filter type'}")
        return out

    if rule == "Flat Panel":
        if long_side > FLAT_LONG_OVER:
            out.update(required=True, count=2,
                       reason=f"long side {long_side:g}mm is over "
                              f"{FLAT_LONG_OVER:g}mm")
        elif short_side > FLAT_BOTH_SIDES_OVER:
            out.update(required=True, count=1,
                       reason=f"both sides are over {FLAT_BOTH_SIDES_OVER:g}mm")
    elif rule == "V-form":
        if long_side > VFORM_LONG_OVER and short_side > VFORM_SHORT_OVER:
            out.update(required=True,
                       reason=f"long side over {VFORM_LONG_OVER:g}mm and short "
                              f"side over {VFORM_SHORT_OVER:g}mm")
    elif rule == "Flyscreen":
        narrow = short_side <= FLYSCREEN_NARROW_UP_TO
        wide = short_side > FLYSCREEN_SHORT_OVER
        if narrow or wide:
            out.update(required=True, message="use brace in filter",
                       reason=(f"short side {short_side:g}mm is "
                               + (f"{FLYSCREEN_NARROW_UP_TO:g}mm or less"
                                  if narrow else
                                  f"over {FLYSCREEN_SHORT_OVER:g}mm")))
        if long_side > FLYSCREEN_LONG_OVER:
            out["advisory"] = True
            if not out["required"]:
                out.update(message="consider bracing",
                           reason=f"long side {long_side:g}mm is over "
                                  f"{FLYSCREEN_LONG_OVER:g}mm")

    # A verified profile supplies what the rule does not: how many and how.
    # It never overrides a count the rule itself set.
    if out["required"] and profile:
        if out["count"] is None and profile.get("count"):
            try:
                out["count"] = int(profile["count"])
            except (TypeError, ValueError):
                pass
        if profile.get("arrangement") and out["count"] != 2:
            out["arrangement"] = str(profile["arrangement"])
    if out["count"] == 2:
        out["arrangement"] = CROSS

    if not out["required"] and not out["advisory"]:
        out["message"] = "No brace required"
    if out["required"] and not out["message"]:
        if out["count"] == 2:
            out["message"] = "Brace Required - 2 braces, Cross Format"
        elif out["count"] == 1:
            out["message"] = "Brace Required - 1 brace"
        else:
            out["message"] = "Brace Required"
    return out


def short_label(result: Dict[str, Any]) -> str:
    """A few words for a narrow cell: "YES x2", "NO", "CONSIDER". The full
    notice, Cross Format included, is printed beside it."""
    if result.get("status") != "ok":
        return "CHECK"
    if result.get("required"):
        n = result.get("count")
        return "YES" + (f" x{n}" if n else "")
    if result.get("advisory"):
        return "CONSIDER"
    return "NO"
