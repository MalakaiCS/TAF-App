"""How to make a filter out of the least channel.

There are three ways to bend a frame, and which is cheapest is not the same
question as which uses less material. The three:

    U               Three sides off one strip, with a lip folded at each end,
                    and a separate cap for the fourth side. Two of the short
                    side, one of the long.
    Sideways U      The same, the other way round: two of the long side, one
                    of the short, and a cap the short size.
    G               All four sides off one strip with a single lip where it
                    closes. No cap.

Every side is cut at its size less 2mm. Confirmed against worksheet
O/N 12576 - a 295 x 310 - which prints all three and whose fifteen marks this
reproduces exactly:

    U           20, 313, 621, 914, 934      cap 308
    sideways U  20, 328, 621, 929, 949      cap 293
    G          308, 601, 909, 1202, 1222

A U is 20mm longer than a G once its cap is counted, because a U has two
lips and a G has one.

The frame is not cut into pieces at those marks. Two 45 degree cuts take a
triangle out of the side so the channel folds there, and the lip has its
sides cut away so it can fold down and close - all of which comes off the
flanges, not off the running length. So nothing is lost between one mark and
the next, and the only cut through the channel is the one separating one
strip from the next on the stick. That is why kerf here defaults to nothing
at all: set it only if your saw really does eat into the next piece.

Two things then make this worth a program rather than a tape.

A G uses less channel per filter than a U plus its cap, and still loses
whenever it wastes the end of every stick, because channel arrives in 2440mm
lengths and what matters is how many whole frames come off one. The two
answers disagree, and which wins changes with the size and again with the
quantity. At 100 x 100 the U gets seven frames from a stick where the G gets
five; at 300 x 300 the G lands almost exactly on 2440 twice over.

And the lip is not fixed. It is nominally 20mm but anything down to 10mm
closes the filter, so a frame can be shortened by 10mm per lip when that is
what stands between one more filter and an offcut. Two G frames of a 295 x
310 come to 2444 against a 2440 stick - four millimetres over. Take two off
each lip and they are 2440 exactly, with nothing left on the floor.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence

# What the workshop uses. These are the fallbacks; the real ones live in
# workshop_settings and are shared, so two PCs cannot print two cut lists.
DEFAULTS: Dict[str, float] = {
    "stick_length_mm":   2440.0,
    "kerf_mm":              0.0,
    "keep_offcut_mm":     400.0,
    "lip_mm":              20.0,
    "min_lip_mm":          10.0,
    "side_allowance_mm":    2.0,
    "minutes_u_frame":      9.0,
    "minutes_g_frame":      7.0,
    "labour_per_hour":     55.0,
}

METHODS = ("u", "sideways_u", "g")

NAMES = {
    "u":          "U",
    "sideways_u": "Sideways U",
    "g":          "G",
}

# How many lips each way of making it has. It is the whole of the difference
# between a U with its cap and a G: two lips against one.
LIPS = {"u": 2, "sideways_u": 2, "g": 1}


def _settings(overrides: Dict[str, float] | None = None) -> Dict[str, float]:
    out = dict(DEFAULTS)
    for key, value in (overrides or {}).items():
        if key in DEFAULTS and value is not None:
            out[key] = float(value)
    if out["min_lip_mm"] > out["lip_mm"]:
        out["min_lip_mm"] = out["lip_mm"]
    return out


# ── One filter, one method ───────────────────────────────────────────────────

def layout(short: float, long: float, method: str,
           settings: Dict[str, float] | None = None,
           lip: float | None = None) -> Dict[str, Any]:
    """The strip for one filter: its segments, its marks and its cap.

    Marks are cumulative, because that is how they are used - a tape is
    pulled out once along the channel and every mark struck off it, rather
    than measured segment by segment from the last pencil line, which is how
    a 1mm error becomes a 4mm one by the far end.

    `lip` overrides the nominal 20mm, for when shortening it is what fits one
    more filter on the stick.
    """
    if method not in METHODS:
        raise ValueError(f"There is no method called {method!r}.")
    w = _settings(settings)
    short, long = float(short), float(long)
    if short <= 0 or long <= 0:
        raise ValueError("A filter needs a short side and a long side.")

    lip_len = w["lip_mm"] if lip is None else float(lip)
    if lip_len < w["min_lip_mm"]:
        raise ValueError(f"A lip shorter than {_tidy(w['min_lip_mm'])}mm will "
                         f"not fold down and close.")
    if lip_len > w["lip_mm"]:
        raise ValueError("A lip longer than the nominal one is not a saving.")

    s = short - w["side_allowance_mm"]
    l = long - w["side_allowance_mm"]
    if s <= 0 or l <= 0:
        raise ValueError("That filter is smaller than the allowance taken "
                         "off each side.")

    if method == "u":
        segments = [lip_len, s, l, s, lip_len]
        cap = l
    elif method == "sideways_u":
        segments = [lip_len, l, s, l, lip_len]
        cap = s
    else:
        segments = [l, s, l, s, lip_len]
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
        "lip":      _tidy(lip_len),
        "lips":     LIPS[method],
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


# ── How many come off one stick ──────────────────────────────────────────────

def frames_per_stick(short: float, long: float, method: str,
                     settings: Dict[str, float] | None = None) -> Dict[str, Any]:
    """The most frames one length will give up, and the lip that does it.

    The lip is only ever shortened when shortening it wins a whole extra
    frame. Trimming it for nothing would be a smaller lip on every filter we
    make in exchange for an offcut that was going in the bin anyway.
    """
    w = _settings(settings)
    stick, kerf = w["stick_length_mm"], w["kerf_mm"]
    full = layout(short, long, method, w)
    lips = full["lips"]
    give = lips * (w["lip_mm"] - w["min_lip_mm"])      # per frame, at most

    def room(n: int) -> float:
        """What each frame may be, for n of them to fit on one stick."""
        return (stick - kerf * (n - 1)) / n if n else 0.0

    best_n, best_lip = 0, w["lip_mm"]
    n = 1
    while True:
        if full["frame"] - give > room(n) + 1e-9:
            break                       # not even with the lips at their
        n += 1                          # shortest; nothing more to try
    # n is now one past the last that could possibly fit.
    for trial in range(n - 1, 0, -1):
        allow = room(trial)
        if full["frame"] <= allow + 1e-9:
            best_n, best_lip = trial, w["lip_mm"]
            break
        # Shorten each lip by as little as it takes, in whole millimetres,
        # because nobody marks out 19.33.
        short_by = math.ceil((full["frame"] - allow) / lips - 1e-9)
        if short_by <= (w["lip_mm"] - w["min_lip_mm"]) + 1e-9:
            best_n, best_lip = trial, w["lip_mm"] - short_by
            break

    if not best_n:
        return {"n": 0, "lip": w["lip_mm"], "frame": full["frame"],
                "shortened": False, "full": full}

    made = layout(short, long, method, w, best_lip)
    return {
        "n":         best_n,
        "lip":       made["lip"],
        "frame":     made["frame"],
        "shortened": made["lip"] != full["lip"],
        "saved":     _tidy(full["frame"] - made["frame"]),
        "full":      full,
        "shape":     made,
    }


def per_stick(length: float, settings: Dict[str, float] | None = None) -> int:
    """How many of one plain piece - a cap, say - come off a fresh stick."""
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


# ── Getting them out of a stick ──────────────────────────────────────────────

def pack(lengths: Sequence[float], settings: Dict[str, float] | None = None,
         offcuts: Sequence[float] | None = None) -> Dict[str, Any]:
    """Fit a pile of plain pieces into as few lengths of channel as possible.

    Longest first into the first length it fits - which is not guaranteed to
    be the very best packing possible, but is within a few per cent of it,
    takes no time at all, and produces a cut list in an order a person can
    actually follow. An optimal packing that tells somebody to cut the short
    ones first and come back to the long ones is not worth the one stick it
    saved.

    Existing offcuts are offered first, longest first, because a 900mm piece
    on the rack that nobody reaches for is a 900mm piece that gets thrown out.
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
        _settle(b, kerf, keep)

    return {
        "sticks":      fresh,
        "lengths":     used_bins,
        "from_rack":   sum(1 for b in used_bins if b["from_offcut"]),
        "too_long":    [_tidy(x) for x in too_long],
        "cut":         _tidy(sum(sum(b["pieces"]) for b in used_bins)),
        "offcuts_kept": [b["offcut"] for b in used_bins if b["keep"]],
    }


def _settle(b: Dict[str, Any], kerf: float, keep: float) -> None:
    """What is left on a length once it has been cut, and whether it is worth
    walking back to the rack with."""
    left = b["length"] - b["used"]
    # Whatever is left still has to be cut free of the last piece, so the
    # blade takes its width off the offcut too.
    b["offcut"] = _tidy(max(0.0, left - kerf)) if left > kerf else 0
    b["keep"] = bool(b["offcut"] >= keep)
    b["used"] = _tidy(b["used"])
    b["length"] = _tidy(b["length"])


# ── Which way to make it ─────────────────────────────────────────────────────

def _run(short, long, method, qty, w, offcuts):
    """One method, worked all the way through: frames onto sticks with the
    lip shortened where that wins one, then the caps into what is left."""
    fit = frames_per_stick(short, long, method, w)
    if not fit["n"]:
        return None
    full = fit["full"]
    stick, kerf, keep = (w["stick_length_mm"], w["kerf_mm"],
                         w["keep_offcut_mm"])

    lengths: List[Dict[str, Any]] = []
    left = int(qty)
    while left > 0:
        # A part-full stick has nothing to gain from a shortened lip, so it
        # gets the full 20mm. Only shorten what actually buys a frame.
        n = min(left, fit["n"])
        shape = fit["shape"] if n == fit["n"] else full
        # The marks ride with the stick, not with the answer as a whole. A
        # part-full length keeps the full lip, and printing the shortened
        # marks against it would have somebody cut it 2mm short for nothing.
        b = {"length": stick, "from_offcut": False,
             "pieces": [shape["frame"]] * n,
             "used": shape["frame"] * n + kerf * (n - 1),
             "lip": shape["lip"], "marks": list(shape["marks"]),
             "shape": shape}
        _settle(b, kerf, keep)
        lengths.append(b)
        left -= n

    caps = []
    if full["cap"]:
        # Into whatever is left on the frame sticks first, then the rack,
        # then new channel.
        spare = [b["offcut"] for b in lengths if b["offcut"] > 0]
        caps = pack([full["cap"]] * int(qty), w,
                    list(spare) + list(offcuts or []))

    fresh = len(lengths) + (caps["sticks"] if caps else 0)
    keepable = sum(b["offcut"] for b in lengths if b["keep"])
    if caps:
        keepable += sum(b["offcut"] for b in caps["lengths"]
                        if b["keep"] and not b["from_offcut"])

    return {
        "method":       method,
        "name":         NAMES[method],
        "shape":        fit["shape"],
        "full":         full,
        "lip":          fit["lip"],
        "shortened":    fit["shortened"],
        "frames_per_stick": fit["n"],
        "frame_sticks": lengths,
        "caps":         caps,
        "sticks":       fresh,
        "channel_each": _tidy(fit["frame"] + full["cap"]),
        "keepable":     _tidy(keepable),
        "pieces_each":  2 if full["cap"] else 1,
    }


def best(short: float, long: float, qty: int = 1,
         settings: Dict[str, float] | None = None,
         offcuts: Sequence[float] | None = None,
         prefer: str = "") -> Dict[str, Any]:
    """Work out all three ways and say which wins, and by how much.

    `prefer` names a way that has been decided elsewhere - a customer whose
    spec says G, say. It still works out all three, so the screen can show
    what the preference is costing, but it does not overrule it: a filter
    made the cheap way and sent back is not a saving.

    Fewest lengths of channel first. Where two ways need the same number -
    which happens more often than you would think - the one that leaves the
    most channel worth keeping wins, then the one with fewer separate pieces
    to handle, which is the G, because a cap is a second thing to cut, store
    and not lose.
    """
    qty = max(1, int(qty))
    w = _settings(settings)
    options, refused = [], []

    for method in METHODS:
        try:
            out = _run(short, long, method, qty, w, offcuts)
        except ValueError as exc:
            refused.append(str(exc))
            continue
        if out is None:
            refused.append(
                f"{NAMES[method]}: a "
                f"{_tidy(layout(short, long, method, w)['frame'])}mm strip "
                f"will not come off a {_tidy(w['stick_length_mm'])}mm length")
            continue
        options.append(out)

    if not options:
        return {"ok": False, "options": [],
                "why": refused[0] if refused else "That cannot be made."}

    options.sort(key=lambda o: (o["sticks"], -o["keepable"],
                                o["pieces_each"], o["channel_each"]))
    cheapest = options[0]["method"] if options else ""
    if prefer:
        # Asked for, so first - whatever it costs. The cost is reported
        # rather than quietly taken out of somebody's hands.
        options.sort(key=lambda o: 0 if o["method"] == prefer else 1)

    # On a square the U and the sideways U are the same strip cut the same
    # way, and offering both is how you get "U - same as Sideways U", which
    # tells nobody anything. Two ways that cut identically are one way.
    seen, unique = set(), []
    for option in options:
        mark = (option["shape"]["frame"], option["full"]["cap"])
        if mark in seen:
            continue
        seen.add(mark)
        unique.append(option)

    won, others = unique[0], unique[1:]
    forced = bool(prefer) and won["method"] == prefer and prefer != cheapest
    out = {
        "ok":       True,
        "qty":      qty,
        "short":    _tidy(short),
        "long":     _tidy(long),
        "best":     won,
        "others":   others,
        "options":  options,
        "refused":  refused,
        "cheapest": cheapest,
        "forced":   forced,
        "why":      _why(won, others, qty),
    }
    if forced:
        saving = next((o for o in others if o["method"] == cheapest), None)
        out["why"] = (f"{won['name']}, because that is what this customer "
                      f"has asked for: {won['sticks']} length"
                      f"{'' if won['sticks'] == 1 else 's'} for {qty}")
        if saving and saving["sticks"] < won["sticks"]:
            out["why"] += (f" - {saving['name']} would have been "
                           f"{saving['sticks']}.")
        else:
            out["why"] += " - and it costs nothing extra."
    return out


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
    if won["shortened"]:
        head += (f" with the lip at {_tidy(won['lip'])}mm instead of "
                 f"{_tidy(won['full']['lip'])}")
    if not others:
        return head + "."
    rival = others[0]
    if rival["sticks"] != won["sticks"]:
        return head + f" - {rival['name']} would be {rival['sticks']}."
    if won["keepable"] != rival["keepable"]:
        return (head + f" - {rival['name']} takes the same, but this leaves "
                f"{won['keepable']}mm worth keeping against "
                f"{rival['keepable']}mm.")
    if won["pieces_each"] != rival["pieces_each"]:
        return (head + f" - {rival['name']} takes the same channel, but it "
                f"is two pieces a filter instead of one.")
    return head + f" - nothing in it against {rival['name']}."


# ── A whole job ──────────────────────────────────────────────────────────────

def plan(lines: Sequence[Dict[str, Any]],
         settings: Dict[str, float] | None = None,
         offcuts: Sequence[float] | None = None,
         prefer: str = "") -> Dict[str, Any]:
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
            answer = best(short, long, qty, w, offcuts,
                          str(line.get("prefer") or prefer or ""))
        except ValueError as exc:
            out.append({"line": line, "ok": False, "why": str(exc)})
            continue
        if not answer.get("ok"):
            out.append({"line": line, "ok": False, "why": answer["why"]})
            continue
        won = answer["best"]
        sticks += won["sticks"]
        channel += won["channel_each"] * qty
        kept += [b["offcut"] for b in won["frame_sticks"] if b["keep"]]
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


# ── A size we already make ───────────────────────────────────────────────────

def near_standard(short: float, long: float, known: Sequence[Any],
                  within: float = 5.0) -> List[Dict[str, Any]]:
    """Sizes already made that are within a few millimetres of this one.

    A 597 x 497 two millimetres off a 595 x 495 you run every week is worth a
    phone call, and the moment to make it is while somebody is still typing
    the order rather than after the channel is cut. It never changes anything
    on its own - what a customer asked for is what they asked for - it only
    says so while it is still cheap to ask.
    """
    short, long = float(short), float(long)
    out = []
    for row in known or []:
        try:
            if isinstance(row, dict):
                ks, kl = float(row.get("short")), float(row.get("long"))
                seen = int(row.get("seen") or 0)
            else:
                ks, kl, seen = float(row[0]), float(row[1]), int(row[2])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        ds, dl = abs(ks - short), abs(kl - long)
        if ds == 0 and dl == 0:
            continue                       # it is that size; nothing to say
        if ds <= within and dl <= within:
            out.append({"short": _tidy(ks), "long": _tidy(kl), "seen": seen,
                        "off_by": _tidy(max(ds, dl))})
    # Closest first, then whichever is made most often - the one most likely
    # to already be on a shelf.
    out.sort(key=lambda r: (r["off_by"], -r["seen"]))
    return out[:5]


# ── The media, across the roll ───────────────────────────────────────────────

def media_across_roll(cut_w: float, cut_l: float, qty: int,
                      roll_width: float, rotatable: bool = False,
                      settings: Dict[str, float] | None = None) -> Dict[str, Any]:
    """How much roll a batch of media pieces takes, and how many fit across.

    The media cut size is taken as given - it is already worked out and
    printed on the worksheet (345 x 593 against a 295 x 310 filter), and it
    depends on the pleat, which is not something to be reinvented here from
    the filter's face. This only answers the part nobody works out: with a
    roll this wide, how many go side by side, and what does the batch cost in
    metres.

    `rotatable` is off by default. Most media has a direction - the pleat
    runs one way - and a nesting that quietly turns half the pieces ninety
    degrees to save a metre would be a very expensive saving.
    """
    cut_w, cut_l = float(cut_w), float(cut_l)
    roll_width = float(roll_width)
    qty = max(1, int(qty))
    if cut_w <= 0 or cut_l <= 0:
        raise ValueError("A media piece needs both its sides.")
    if roll_width <= 0:
        raise ValueError("The roll has to have a width.")

    def one_way(across_side: float, along_side: float) -> Dict[str, Any] | None:
        across = int(roll_width // across_side)
        if across < 1:
            return None
        rows = math.ceil(qty / across)
        return {
            "across":     across,
            "rows":       rows,
            "run_mm":     _tidy(rows * along_side),
            "waste_mm":   _tidy(roll_width - across * across_side),
            "turned":     False,
        }

    straight = one_way(cut_w, cut_l)
    options = [o for o in (straight,) if o]
    if rotatable:
        turned = one_way(cut_l, cut_w)
        if turned:
            turned["turned"] = True
            options.append(turned)

    if not options:
        return {"ok": False,
                "why": f"a {_tidy(min(cut_w, cut_l))}mm piece will not fit "
                       f"across a {_tidy(roll_width)}mm roll"}

    options.sort(key=lambda o: (o["run_mm"], o["waste_mm"]))
    won = options[0]
    used = qty * cut_w * cut_l
    laid = won["run_mm"] * roll_width
    return {
        "ok":        True,
        "qty":       qty,
        "cut":       f"{_tidy(cut_w)} x {_tidy(cut_l)}",
        "across":    won["across"],
        "rows":      won["rows"],
        "run_mm":    won["run_mm"],
        "run_m":     round(won["run_mm"] / 1000.0, 2),
        "turned":    won["turned"],
        "edge_mm":   won["waste_mm"],
        "waste_pct": round(100.0 * (laid - used) / laid, 1) if laid else 0.0,
        "others":    options[1:],
        "why":       (f"{won['across']} across a {_tidy(roll_width)}mm roll, "
                      f"{won['rows']} row{'' if won['rows'] == 1 else 's'}, "
                      f"{round(won['run_mm'] / 1000.0, 2)}m of roll"
                      + (f" - {_tidy(won['waste_mm'])}mm wasted down the edge"
                         if won["waste_mm"] else " with nothing down the edge")),
    }


# ── What the making of it costs ──────────────────────────────────────────────

# Minutes at the bench, per frame, by the way it is made. A U is a strip and
# a cap: two pieces to cut, handle, and not lose, and one more fold. A G is
# one piece. These start as the workshop's best guess and are meant to be
# corrected - the point is that the difference exists and is currently
# nowhere in the figure a quote is priced off.
LABOUR_DEFAULTS: Dict[str, float] = {
    "minutes_u_frame":   9.0,
    "minutes_g_frame":   7.0,
    "labour_per_hour":  55.0,
}


def labour(method: str, qty: int,
           settings: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Minutes and money for making `qty` frames a given way.

    Reported separately from the material rather than folded into it. A job
    where the cheap channel costs ten more minutes a filter is a job somebody
    should be able to see both halves of before deciding.
    """
    s = dict(LABOUR_DEFAULTS)
    for key, value in (settings or {}).items():
        if key in LABOUR_DEFAULTS and value is not None:
            s[key] = float(value)
    qty = max(0, int(qty))
    each = s["minutes_g_frame"] if method == "g" else s["minutes_u_frame"]
    minutes = each * qty
    return {
        "minutes_each": _tidy(each),
        "minutes":      _tidy(minutes),
        "hours":        round(minutes / 60.0, 2),
        "cost":         round(minutes / 60.0 * s["labour_per_hour"], 2),
        "per_hour":     _tidy(s["labour_per_hour"]),
    }


def with_labour(answer: Dict[str, Any],
                settings: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Add the bench time to an answer from best(), and say what the way it
    chose is costing in minutes against the way it turned down."""
    if not answer.get("ok"):
        return answer
    qty = answer["qty"]
    won = answer["best"]
    won["labour"] = labour(won["method"], qty, settings)
    for other in answer["others"]:
        other["labour"] = labour(other["method"], qty, settings)
    cheapest_time = min([won] + answer["others"],
                        key=lambda o: o["labour"]["minutes"])
    answer["quickest"] = cheapest_time["method"]
    answer["labour_note"] = (
        f"{won['labour']['hours']}h at the bench "
        f"(${won['labour']['cost']:.2f})")
    if cheapest_time["method"] != won["method"]:
        saved = _tidy(won["labour"]["minutes"]
                      - cheapest_time["labour"]["minutes"])
        extra = cheapest_time["sticks"] - won["sticks"]
        if extra <= 0:
            # Quicker and no dearer. Material picked the winner and material
            # has nothing to say here, so say so plainly rather than dressing
            # a free saving up as a trade-off.
            answer["labour_note"] += (
                f" - {cheapest_time['name']} is {saved} minutes less and "
                f"takes no more channel. Make them that way.")
            answer["labour_beats_material"] = True
        else:
            answer["labour_note"] += (
                f" - {cheapest_time['name']} is {saved} minutes less, for "
                f"{extra} more length{'' if extra == 1 else 's'} of channel")
    return answer


def worksheet_note(short: float, long: float, qty: int,
                   settings: Dict[str, float] | None = None,
                   prefer: str = "") -> str:
    """One line for the printed worksheet: which way, and the lip.

    The sheet already prints all three sets of marks - Forward, Flipped and
    Reversed - and has done for years. What it has never said is which of
    them to use for this quantity, or that the lip wants trimming to fit two
    on a length. That is the whole of what this adds.
    """
    try:
        answer = best(short, long, qty, settings, None, prefer)
    except ValueError:
        return ""
    if not answer.get("ok"):
        return ""
    won = answer["best"]
    note = f"CUT AS {won['name'].upper()}"
    # The rate only means something when more than one is being made. "2 a
    # length" on a sheet for a single filter is noise on a page that is
    # already busy.
    if qty > 1 and won["frames_per_stick"] > 1:
        note += f", {won['frames_per_stick']} a length"
    if won["shortened"]:
        note += f", LIP {_tidy(won['lip'])}mm"
    return note
