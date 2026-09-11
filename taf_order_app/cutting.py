"""How to make a filter out of the least channel.

There are three ways to bend a frame, and which is cheapest is not the same
question as which uses less material. The three:

    U               Three sides off one strip, with a 20mm lip folded at each
                    end, and a separate cap for the fourth side. Two of the
                    short side, one of the long.
    Sideways U      The same, the other way round: two of the long side, one
                    of the short, and a cap the short size.
    G               All four sides off one strip with a single 20mm lip where
                    it closes. No cap.

Every side is cut at its size less 2mm. Confirmed against worksheet
O/N 12576 - a 295 x 310 - which prints all three and whose fifteen marks this
reproduces exactly:

    U           20, 313, 621, 914, 934      cap 308
    sideways U  20, 328, 621, 929, 949      cap 293
    G          308, 601, 909, 1202, 1222

Now the part that is worth a program. A G uses less channel per filter than a
U plus its cap. But channel arrives in sticks - 2440mm - and what matters is
how many whole frames come off one stick, which is a different sum, and one
that the saw blade takes part in. Cutting seven pieces takes six cuts, and at
3mm a cut that is 18mm gone; 18mm is routinely the difference between seven
frames and six.

So the two answers disagree, and which wins changes with the size and with
how many are wanted. At 100 x 100 the U gets seven frames from a stick where
the G gets five, and pulls ahead as the quantity rises. At 300 x 300 the G
lands almost exactly on 2440 twice over and the U is nowhere near. Nobody is
working that out at the saw with a tape.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence

# What the workshop uses. These are the fallbacks; the real ones live in
# workshop_settings and are shared, so two PCs cannot print two cut lists.
DEFAULTS: Dict[str, float] = {
    "stick_length_mm":   2440.0,
    "kerf_mm":              3.0,
    "keep_offcut_mm":     400.0,
    "lip_mm":              20.0,
    "side_allowance_mm":    2.0,
}

METHODS = ("u", "sideways_u", "g")

NAMES = {
    "u":          "U",
    "sideways_u": "Sideways U",
    "g":          "G",
}


def _settings(overrides: Dict[str, float] | None = None) -> Dict[str, float]:
    out = dict(DEFAULTS)
    for key, value in (overrides or {}).items():
        if key in DEFAULTS and value is not None:
            out[key] = float(value)
    return out


# ── One filter, one method ───────────────────────────────────────────────────

def layout(short: float, long: float, method: str,
           settings: Dict[str, float] | None = None) -> Dict[str, Any]:
    """The strip for one filter: its segments, its marks and its cap.

    Marks are cumulative, because that is how they are used - a tape is
    pulled out once along the channel and every mark struck off it, rather
    than measured segment by segment from the last pencil line, which is how
    a 1mm error becomes a 4mm one by the far end.
    """
    if method not in METHODS:
        raise ValueError(f"There is no method called {method!r}.")
    w = _settings(settings)
    short, long = float(short), float(long)
    if short <= 0 or long <= 0:
        raise ValueError("A filter needs a short side and a long side.")

    lip = w["lip_mm"]
    s = short - w["side_allowance_mm"]
    l = long - w["side_allowance_mm"]
    if s <= 0 or l <= 0:
        raise ValueError("That filter is smaller than the allowance taken "
                         "off each side.")

    if method == "u":
        segments = [lip, s, l, s, lip]
        cap = l
    elif method == "sideways_u":
        segments = [lip, l, s, l, lip]
        cap = s
    else:
        segments = [l, s, l, s, lip]
        cap = 0.0

    marks, run = [], 0.0
    for seg in segments:
        run += seg
        marks.append(_tidy(run))

    return {
        "method":   method,
        "name":     NAMES[method],
        "segments": [_tidy(x) for x in segments],
        "marks":    marks,
        "frame":    _tidy(sum(segments)),
        "cap":      _tidy(cap),
        "total":    _tidy(sum(segments) + cap),
    }


def _tidy(x: float) -> float:
    """Whole millimetres where they are whole. Nobody marks out 934.0000001,
    and a float that prints its own rounding error on a worksheet makes the
    whole sheet look wrong."""
    r = round(float(x), 3)
    return int(r) if abs(r - round(r)) < 1e-9 else r


# ── Getting them out of a stick ──────────────────────────────────────────────

def pack(lengths: Sequence[float], settings: Dict[str, float] | None = None,
         offcuts: Sequence[float] | None = None) -> Dict[str, Any]:
    """Fit a pile of pieces into as few lengths of channel as possible.

    Longest first into the first length it fits - which is not guaranteed to
    be the very best packing possible, but is within a few per cent of it,
    takes no time at all, and produces a cut list in an order a person can
    actually follow. An optimal packing that tells somebody to cut the short
    ones first and come back to the long ones is not worth the one stick it
    saved.

    Existing offcuts are offered first, longest first, because a 900mm piece
    on the rack that nobody uses is a 900mm piece that gets thrown out.
    """
    w = _settings(settings)
    stick, kerf = w["stick_length_mm"], w["kerf_mm"]
    keep = w["keep_offcut_mm"]

    todo = sorted((float(x) for x in lengths if float(x) > 0), reverse=True)
    too_long = [x for x in todo if x > stick]
    todo = [x for x in todo if x <= stick]

    bins: List[Dict[str, Any]] = []
    for spare in sorted((float(x) for x in (offcuts or []) if float(x) > 0),
                        reverse=True):
        bins.append({"length": spare, "from_offcut": True,
                     "pieces": [], "used": 0.0})

    fresh = 0
    for piece in todo:
        for b in bins:
            # One more piece means one more cut, unless it is the first.
            need = piece + (kerf if b["pieces"] else 0.0)
            if b["used"] + need <= b["length"] + 1e-9:
                b["used"] += need
                b["pieces"].append(_tidy(piece))
                break
        else:
            fresh += 1
            bins.append({"length": stick, "from_offcut": False,
                         "pieces": [_tidy(piece)], "used": piece})

    used_bins = [b for b in bins if b["pieces"]]
    for b in used_bins:
        left = b["length"] - b["used"]
        # Whatever is left still has to be cut free of the last piece, so the
        # blade takes its width off the offcut too. This is exactly where a
        # calculator that ignores kerf promises an offcut that is not there.
        b["offcut"] = _tidy(max(0.0, left - kerf)) if left > kerf else 0
        b["keep"] = bool(b["offcut"] >= keep)
        b["used"] = _tidy(b["used"])
        b["length"] = _tidy(b["length"])

    return {
        "sticks":      fresh,
        "lengths":     used_bins,
        "from_rack":   sum(1 for b in used_bins if b["from_offcut"]),
        "too_long":    [_tidy(x) for x in too_long],
        "cut":         _tidy(sum(sum(b["pieces"]) for b in used_bins)),
        "offcuts_kept": [b["offcut"] for b in used_bins if b["keep"]],
    }


def per_stick(length: float, settings: Dict[str, float] | None = None) -> int:
    """How many of one piece come off a fresh stick, blade included."""
    w = _settings(settings)
    stick, kerf = w["stick_length_mm"], w["kerf_mm"]
    length = float(length)
    if length <= 0 or length > stick:
        return 0
    n = 0
    used = 0.0
    while True:
        need = length + (kerf if n else 0.0)
        if used + need > stick + 1e-9:
            return n
        used += need
        n += 1


# ── Which way to make it ─────────────────────────────────────────────────────

def best(short: float, long: float, qty: int = 1,
         settings: Dict[str, float] | None = None,
         offcuts: Sequence[float] | None = None) -> Dict[str, Any]:
    """Work out all three ways and say which wins, and by how much.

    Fewest fresh sticks first. Where two ways need the same number - which
    happens more often than you would think - the one that leaves the most
    channel worth keeping wins, then the one with fewer separate pieces to
    handle, which is the G, because a cap is a second thing to cut, store and
    not lose.
    """
    qty = max(1, int(qty))
    w = _settings(settings)
    options = []

    for method in METHODS:
        try:
            shape = layout(short, long, method, w)
        except ValueError as exc:
            options.append({"method": method, "name": NAMES[method],
                            "impossible": str(exc)})
            continue

        pieces = [shape["frame"]] * qty
        if shape["cap"]:
            pieces += [shape["cap"]] * qty
        packed = pack(pieces, w, offcuts)

        if packed["too_long"]:
            options.append({
                "method": method, "name": NAMES[method], "shape": shape,
                "impossible": f"a {_tidy(packed['too_long'][0])}mm piece will "
                              f"not come off a "
                              f"{_tidy(w['stick_length_mm'])}mm length",
            })
            continue

        keepable = sum(b["offcut"] for b in packed["lengths"] if b["keep"])
        options.append({
            "method":       method,
            "name":         NAMES[method],
            "shape":        shape,
            "packed":       packed,
            "sticks":       packed["sticks"],
            "frames_per_stick": per_stick(shape["frame"], w),
            "channel_each": shape["total"],
            "keepable":     _tidy(keepable),
            "pieces_each":  2 if shape["cap"] else 1,
        })

    workable = [o for o in options if "impossible" not in o]
    if not workable:
        return {"ok": False, "options": options,
                "why": options[0].get("impossible", "That cannot be made.")}

    workable.sort(key=lambda o: (o["sticks"], -o["keepable"],
                                 o["pieces_each"], o["channel_each"]))

    # On a square the U and the sideways U are the same strip cut the same
    # way, and offering both is how you get "U - same as Sideways U", which
    # tells nobody anything. Two ways that cut identically are one way.
    seen, unique = set(), []
    for option in workable:
        mark = (option["shape"]["frame"], option["shape"]["cap"])
        if mark in seen:
            continue
        seen.add(mark)
        unique.append(option)

    won = unique[0]
    others = unique[1:]

    return {
        "ok":      True,
        "qty":     qty,
        "short":   _tidy(short),
        "long":    _tidy(long),
        "best":    won,
        "others":  others,
        "options": options,
        "why":     _why(won, others, qty),
    }


def _why(won: Dict[str, Any], others: List[Dict[str, Any]], qty: int) -> str:
    """One sentence, in the words somebody at the saw would use.

    It names the runner-up and the margin rather than only the winner. A
    person who can see it was close will overrule it when the rack says
    otherwise; a person told only the answer either follows it blindly or
    ignores it entirely.
    """
    n = won["frames_per_stick"]
    head = (f"{won['name']}: {n} frame{'' if n == 1 else 's'} a length, "
            f"{won['sticks']} length{'' if won['sticks'] == 1 else 's'} "
            f"for {qty}")
    if not others:
        return head + "."
    rival = others[0]
    if rival["sticks"] != won["sticks"]:
        return (head + f" - {rival['name']} would be {rival['sticks']}.")
    if won["keepable"] != rival["keepable"]:
        return (head + f" - {rival['name']} takes the same, but this leaves "
                f"{won['keepable']}mm worth keeping against "
                f"{rival['keepable']}mm.")
    # Same sticks, same usable offcut: the tie broke on handling, and saying
    # so is more use than inventing a difference that is not there.
    if won["pieces_each"] != rival["pieces_each"]:
        return (head + f" - {rival['name']} takes the same channel, but it "
                f"is two pieces a filter instead of one.")
    return head + f" - nothing in it against {rival['name']}."


# ── A whole job ──────────────────────────────────────────────────────────────

def plan(lines: Sequence[Dict[str, Any]],
         settings: Dict[str, float] | None = None,
         offcuts: Sequence[float] | None = None) -> Dict[str, Any]:
    """A cut list for a batch: every line, the way to make it, and the total.

    Each distinct size is decided on its own, not the batch as a whole. That
    is not the very cheapest arrangement - mixing two sizes onto one stick
    sometimes beats both - but it is the one that can be explained in a line
    on a worksheet, and a cut list nobody trusts gets ignored at the saw and
    saves nothing at all.
    """
    w = _settings(settings)
    out, sticks, channel, kept = [], 0, 0.0, []
    for line in lines or []:
        short = line.get("short") or line.get("Short") or 0
        long = line.get("long") or line.get("Long") or 0
        qty = int(line.get("qty") or line.get("Quantity") or 1)
        try:
            answer = best(short, long, qty, w, offcuts)
        except ValueError as exc:
            out.append({"line": line, "ok": False, "why": str(exc)})
            continue
        if not answer.get("ok"):
            out.append({"line": line, "ok": False, "why": answer["why"]})
            continue
        won = answer["best"]
        sticks += won["sticks"]
        channel += won["channel_each"] * qty
        kept += won["packed"]["offcuts_kept"]
        out.append({"line": line, "ok": True, "answer": answer})

    return {
        "lines":   out,
        "sticks":  sticks,
        "channel": _tidy(channel),
        "offcuts_kept": kept,
        "scrap_pct": _scrap(sticks, channel, w),
    }


def _scrap(sticks: int, channel: float,
           settings: Dict[str, float]) -> float:
    """What percentage of the channel opened did not become filter."""
    bought = sticks * settings["stick_length_mm"]
    if bought <= 0:
        return 0.0
    return round(100.0 * (bought - channel) / bought, 1)
