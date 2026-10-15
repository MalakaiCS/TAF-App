"""How much channel a whole order takes, and which pages can share a length.

Each worksheet page works out its own best way to make its frames (see
cutting.best). Taken one page at a time that leaves channel on the table: a
1300 G on page 1 and an 1100 G on page 2 each open a 2440 length, when the
two together come to 2400 and fit on one - page 1's from one end, page 2's
from the other.

So the order is looked at as a whole, one channel depth at a time (a 25mm
frame cannot come off 45mm channel):

  1. every page's frames go on lengths the way that page would cut them,
     lip shortening and all;
  2. the least-used length is emptied into the room left on the others, if
     every piece on it fits somewhere - and again, until nothing more moves;
  3. caps (a U's fourth side) go into whatever room is left, then onto new
     lengths.

What is reported: the lengths each depth needs, the channel actually cut,
how many lengths sharing saved, and for each page the pages it shares a
length with. Nothing here changes how a frame is marked.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from . import cutting as _cutting

# Frames made from C-channel; flyscreens are not.
FRAMED = ("flat panel", "v-form", "header", "stepped filter")


def _int(value) -> int:
    try:
        return int(round(float(str(value).strip())))
    except (TypeError, ValueError):
        return 0


def framed(item: Dict[str, Any]) -> bool:
    """A line whose frame is cut from channel on the bench."""
    if str(item.get("item_kind") or "filter") != "filter":
        return False
    if item.get("Use Stock V-form") or item.get("Pleat Insert"):
        return False
    if str(item.get("Filter Type") or "").strip().lower() not in FRAMED:
        return False
    return _int(item.get("Short")) > 0 and _int(item.get("Long")) > 0 \
        and _int(item.get("Channel")) > 0


def _fits(b: Dict[str, Any], piece: float, kerf: float) -> bool:
    need = piece + (kerf if b["pieces"] else 0.0)
    return b["used"] + need <= b["length"] + 1e-9


def _put(b: Dict[str, Any], piece: Dict[str, Any], kerf: float) -> None:
    b["used"] += piece["length"] + (kerf if b["pieces"] else 0.0)
    b["pieces"].append(piece)


def _consolidate(bins: List[Dict[str, Any]], kerf: float) -> int:
    """Empty the least-used lengths into the others while that works.
    Returns how many lengths it saved."""
    saved = 0
    moved = True
    while moved:
        moved = False
        for cand in sorted(bins, key=lambda b: b["used"]):
            others = [b for b in bins if b is not cand]
            # Try it on copies, so a length half-moved is never left behind.
            trial = [dict(b, pieces=list(b["pieces"])) for b in others]
            ok = True
            for piece in sorted(cand["pieces"], key=lambda p: -p["length"]):
                # The fullest length it fits on: the least left over.
                room = [b for b in trial if _fits(b, piece["length"], kerf)]
                if not room:
                    ok = False
                    break
                _put(max(room, key=lambda b: b["used"]), piece, kerf)
            if ok:
                for b, t in zip(others, trial):
                    b["pieces"], b["used"] = t["pieces"], t["used"]
                bins.remove(cand)
                saved += 1
                moved = True
                break
    return saved


# Trying every mix of methods is exact and quick for a few pages; past this
# many mixes each page's method is improved in turn instead.
EXHAUSTIVE_LIMIT = 256


def _pack(choices, stick: float, kerf: float) -> List[Dict[str, Any]]:
    """Lengths for one mix of methods: each page's frames as that page cuts
    them, consolidated, then every cap into the room left or a new length.
    `choices` are (page, option, qty), the option one of cutting.best's."""
    bins: List[Dict[str, Any]] = []
    caps: List[Dict[str, Any]] = []
    for page, opt, qty in choices:
        for b in opt["frame_sticks"]:
            piece = {"page": page, "kind": "strip", "name": opt["name"],
                     "length": float(b["pieces"][0])}
            nb = {"length": stick, "pieces": [], "used": 0.0}
            for _ in b["pieces"]:
                _put(nb, dict(piece), kerf)
            bins.append(nb)
        cap = opt["full"].get("cap") or 0
        if cap:
            caps += [{"page": page, "kind": "cap", "name": "cap",
                      "length": float(cap)} for _ in range(qty)]
    _consolidate(bins, kerf)
    for cap in sorted(caps, key=lambda p: -p["length"]):
        room = [b for b in bins if _fits(b, cap["length"], kerf)]
        if room:
            _put(max(room, key=lambda b: b["used"]), cap, kerf)
        else:
            nb = {"length": stick, "pieces": [], "used": 0.0}
            _put(nb, cap, kerf)
            bins.append(nb)
    return bins


def _shared(bins) -> int:
    return sum(1 for b in bins if len({p["page"] for p in b["pieces"]}) > 1)


def _score(bins, changed: int, keep: float):
    """Fewest lengths first. Then the plan that is simplest on the floor:
    fewest lengths shared between pages, then the fewest pages made another
    way than they would be on their own, then the most worth keeping."""
    keepable = sum(b["length"] - b["used"] for b in bins
                   if b["length"] - b["used"] >= keep)
    return (len(bins), _shared(bins), changed, -keepable)


def _options(answer: Dict[str, Any], prefer: str) -> List[Dict[str, Any]]:
    """The ways a page can be made, its own best first; the one asked for
    only, when the customer asks for one. Two ways that cut the same (U
    and Sideways U on a square) are one way."""
    opts = list(answer.get("options") or [])
    if prefer:
        asked = [o for o in opts if o["method"] == prefer]
        if asked:
            return asked
    best = answer["best"]
    out, seen = [best], {(best["shape"]["frame"], best["full"]["cap"])}
    for o in opts:
        mark = (o["shape"]["frame"], o["full"]["cap"])
        if mark not in seen:
            seen.add(mark)
            out.append(o)
    return out


def _choose(entries, stick, kerf, keep):
    """The mix of methods for one channel depth. Every mix when there are
    few; otherwise each page in turn takes whichever way makes the whole
    better, until none does."""
    import itertools
    count = 1
    for e in entries:
        count *= len(e["options"])

    def run(pick):
        bins = _pack([(e["page"], e["options"][i], e["qty"])
                      for e, i in zip(entries, pick)], stick, kerf)
        return _score(bins, sum(1 for i in pick if i), keep), bins

    if count <= EXHAUSTIVE_LIMIT:
        best = None
        for pick in itertools.product(*[range(len(e["options"]))
                                        for e in entries]):
            score, bins = run(pick)
            if best is None or score < best[0]:
                best = (score, bins, pick)
        return best[2], best[1]
    pick = [0] * len(entries)
    score, bins = run(pick)
    improved = True
    while improved:
        improved = False
        for k, e in enumerate(entries):
            for i in range(len(e["options"])):
                if i == pick[k]:
                    continue
                trial = list(pick)
                trial[k] = i
                t_score, t_bins = run(trial)
                if t_score < score:
                    pick, score, bins, improved = trial, t_score, t_bins, True
    return tuple(pick), bins


def order_plan(lines: Sequence[Dict[str, Any]],
               workshop: Optional[Dict[str, float]] = None,
               prefer: str = "") -> Dict[str, Any]:
    """The channel for a whole order.

    `lines` are the worksheet's lines, each with "page" (its page number)
    and the order line's fields (Short, Long, Channel, Quantity ...).

    The way each page is made is chosen for the order as a whole, not page
    by page: two pages that each tie between a U and a Sideways U on their
    own can come out a length cheaper both made Sideways U, when their
    short caps all fit on one length together.
    """
    w = _cutting._settings(workshop)
    stick, kerf, keep = (w["stick_length_mm"], w["kerf_mm"],
                         w["keep_offcut_mm"])
    by_depth: Dict[int, List[Dict[str, Any]]] = {}
    problems: List[str] = []
    for line in lines:
        if not framed(line):
            continue
        page = line.get("page")
        depth = _int(line.get("Channel"))
        qty = max(1, _int(line.get("Quantity")) or 1)
        try:
            answer = _cutting.best(_int(line["Short"]), _int(line["Long"]),
                                   qty, w, None, prefer or "")
        except ValueError as exc:
            problems.append(f"page {page}: {exc}")
            continue
        if not answer.get("ok"):
            problems.append(f"page {page}: {answer.get('why')}")
            continue
        by_depth.setdefault(depth, []).append({
            "page": page, "qty": qty, "options": _options(answer, prefer),
            "alone": answer["best"]["sticks"]})

    depths = []
    shares: Dict[Any, List[Dict[str, Any]]] = {}
    methods: Dict[Any, Dict[str, Any]] = {}
    own: Dict[Any, List[Dict[str, Any]]] = {}
    for depth in sorted(by_depth):
        entries = by_depth[depth]
        pick, bins = _choose(entries, stick, kerf, keep)
        for e, i in zip(entries, pick):
            opt = e["options"][i]
            methods[e["page"]] = {"method": opt["method"],
                                  "name": opt["name"],
                                  "own_best": e["options"][0]["method"],
                                  "changed": i != 0}
        cut = sum(p["length"] for b in bins for p in b["pieces"])
        shared = 0
        for b in bins:
            pages = []
            for p in b["pieces"]:
                if p["page"] not in pages:
                    pages.append(p["page"])
            if len(pages) < 2:
                if pages:
                    own.setdefault(pages[0], []).append(b)
                continue
            shared += 1
            for page in pages:
                mine = [p for p in b["pieces"] if p["page"] == page]
                theirs = [p for p in b["pieces"] if p["page"] != page]
                shares.setdefault(page, []).append({
                    "depth": depth, "mine": mine, "theirs": theirs})
        alone = sum(e["alone"] for e in entries)
        depths.append({
            "depth": depth,
            "lengths": len(bins),
            "alone": alone,
            "saved": max(0, alone - len(bins)),
            "cut_mm": _cutting._tidy(cut),
            "bought_mm": _cutting._tidy(len(bins) * stick),
            "shared_lengths": shared,
            "pages": [e["page"] for e in entries],
            "sticks": bins,
        })
    return {"depths": depths, "shares": shares, "methods": methods,
            "own": own, "problems": problems,
            "stick_mm": _cutting._tidy(stick)}


def _pieces_text(pieces: Sequence[Dict[str, Any]]) -> str:
    """"G 1100" / "2 x G 900" / "cap 480" - what the other page cuts."""
    groups: Dict[Any, int] = {}
    for p in pieces:
        key = (p["name"], _cutting._tidy(p["length"]))
        groups[key] = groups.get(key, 0) + 1
    out = []
    for (name, length), n in groups.items():
        out.append(f"{n} x {name} {length:g}" if n > 1
                   else f"{name} {length:g}")
    return ", ".join(out)


def summary_text(plan: Dict[str, Any]) -> str:
    """"25mm: 3 lengths (6,980mm cut) · 45mm: 2 lengths, 1 saved by
    sharing" - the whole order in one line."""
    parts = []
    for d in plan.get("depths") or []:
        n = d["lengths"]
        text = (f"{d['depth']}mm: {n} length{'' if n == 1 else 's'} "
                f"({d['cut_mm']:,.0f}mm cut)")
        if d["saved"]:
            text += f", {d['saved']} saved by sharing"
        parts.append(text)
    return "  ·  ".join(parts)


def short_text(plan: Dict[str, Any]) -> str:
    """"Channel 25mm x3, 45mm x2" - for a screen's corner."""
    parts = [f"{d['depth']}mm x{d['lengths']}"
             for d in plan.get("depths") or []]
    return ("Channel " + ", ".join(parts)) if parts else ""


def page_lines(plan: Dict[str, Any], page: Any) -> List[tuple]:
    """The lines a worksheet page's FILTER CALCULATOR gets: who it shares a
    length with, and the channel for the whole order."""
    out: List[tuple] = []
    mine = plan.get("own", {}).get(page, [])
    if mine:
        groups: Dict[str, int] = {}
        for b in mine:
            text = _pieces_text(b["pieces"])
            groups[text] = groups.get(text, 0) + 1
        parts = [f"{n} length{'' if n == 1 else 's'} of {text}"
                 for text, n in groups.items()]
        out.append(("CHANNEL: " + "; ".join(parts), True))
    for share in plan.get("shares", {}).get(page, []):
        others = sorted({p["page"] for p in share["theirs"]},
                        key=lambda x: (str(type(x)), x))
        mine = _pieces_text(share["mine"])
        theirs = _pieces_text(share["theirs"])
        if len(others) == 1:
            out.append((f"SHARE A LENGTH: cut {mine} from one end, then "
                        f"page {others[0]}'s {theirs} from the other end",
                        True))
        else:
            names = ", ".join(str(o) for o in others)
            out.append((f"SHARE A LENGTH with pages {names}: {mine} here, "
                        f"{theirs} on theirs - cut in turn from the ends",
                        True))
    total = summary_text(plan)
    if total:
        out.append(("ORDER CHANNEL: " + total, False))
    return out
