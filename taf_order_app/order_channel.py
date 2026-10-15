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


def order_plan(lines: Sequence[Dict[str, Any]],
               workshop: Optional[Dict[str, float]] = None,
               prefer: str = "") -> Dict[str, Any]:
    """The channel for a whole order.

    `lines` are the worksheet's lines, each with "page" (its page number)
    and the order line's fields (Short, Long, Channel, Quantity ...).
    """
    w = _cutting._settings(workshop)
    stick, kerf = w["stick_length_mm"], w["kerf_mm"]
    by_depth: Dict[int, Dict[str, Any]] = {}
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
        won = answer["best"]
        g = by_depth.setdefault(depth, {"bins": [], "caps": [],
                                        "alone": 0, "pages": []})
        g["pages"].append(page)
        g["alone"] += won["sticks"]
        for b in won["frame_sticks"]:
            piece = {"page": page, "kind": "strip", "name": won["name"],
                     "length": float(b["pieces"][0])}
            nb = {"length": stick, "pieces": [], "used": 0.0}
            for _ in b["pieces"]:
                _put(nb, dict(piece), kerf)
            g["bins"].append(nb)
        cap = won["full"].get("cap") or 0
        if cap:
            g["caps"] += [{"page": page, "kind": "cap", "name": "cap",
                           "length": float(cap)}] * qty

    depths = []
    shares: Dict[Any, List[Dict[str, Any]]] = {}
    for depth in sorted(by_depth):
        g = by_depth[depth]
        bins = g["bins"]
        _consolidate(bins, kerf)
        for cap in sorted(g["caps"], key=lambda p: -p["length"]):
            room = [b for b in bins if _fits(b, cap["length"], kerf)]
            if room:
                _put(max(room, key=lambda b: b["used"]), dict(cap), kerf)
            else:
                nb = {"length": stick, "pieces": [], "used": 0.0}
                _put(nb, dict(cap), kerf)
                bins.append(nb)
        cut = sum(p["length"] for b in bins for p in b["pieces"])
        shared = 0
        for b in bins:
            pages = []
            for p in b["pieces"]:
                if p["page"] not in pages:
                    pages.append(p["page"])
            if len(pages) < 2:
                continue
            shared += 1
            for page in pages:
                mine = [p for p in b["pieces"] if p["page"] == page]
                theirs = [p for p in b["pieces"] if p["page"] != page]
                shares.setdefault(page, []).append({
                    "depth": depth, "mine": mine, "theirs": theirs})
        depths.append({
            "depth": depth,
            "lengths": len(bins),
            "alone": g["alone"],
            "saved": max(0, g["alone"] - len(bins)),
            "cut_mm": _cutting._tidy(cut),
            "bought_mm": _cutting._tidy(len(bins) * stick),
            "shared_lengths": shared,
            "pages": g["pages"],
            "sticks": bins,
        })
    return {"depths": depths, "shares": shares, "problems": problems,
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
