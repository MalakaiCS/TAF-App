"""Which screens this PC has, and where each one is.

Tk cannot answer this. It reports one desktop the width of every monitor
side by side, so "is there a second screen" was a guess from how wide that
came out — and a guess is no good when somebody is about to put a window in
front of a customer and needs it to land on the right monitor.

Each platform is asked properly where it can be:

    Windows   EnumDisplayMonitors, which is the actual answer
    Linux     xrandr --query
    macOS     system_profiler, and the Tk guess if that is not there

Everything returns the same shape, and every route falls back rather than
raising. A PC that will not say what screens it has is not a reason to stop
quoting - the chooser just offers to open a window somebody drags themselves,
which works no matter what any of this returns.
"""
from __future__ import annotations

import re
import subprocess
import sys
from typing import Any, Dict, List

Monitor = Dict[str, Any]       # {name, x, y, width, height, primary}


def _monitor(name: str, x: int, y: int, w: int, h: int,
             primary: bool = False) -> Monitor:
    return {"name": name, "x": int(x), "y": int(y),
            "width": int(w), "height": int(h), "primary": bool(primary)}


# ── Windows ──────────────────────────────────────────────────────────────────

def _windows_monitors() -> List[Monitor]:
    import ctypes

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", RECT),
                    ("rcWork", RECT), ("dwFlags", ctypes.c_ulong)]

    MONITORINFOF_PRIMARY = 1
    user32 = ctypes.windll.user32
    proc_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p,
                                   ctypes.c_void_p, ctypes.POINTER(RECT),
                                   ctypes.c_ssize_t)
    found: List[Monitor] = []

    def _each(handle, _hdc, _rect, _data):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(ctypes.c_void_p(handle), ctypes.byref(info)):
            r = info.rcMonitor
            found.append(_monitor(
                "", r.left, r.top, r.right - r.left, r.bottom - r.top,
                bool(info.dwFlags & MONITORINFOF_PRIMARY)))
        return 1

    user32.EnumDisplayMonitors(None, None, proc_type(_each), 0)
    return found


# ── Linux ────────────────────────────────────────────────────────────────────

XRANDR = re.compile(
    r"^(?P<name>\S+)\s+connected\s+(?P<primary>primary\s+)?"
    r"(?P<w>\d+)x(?P<h>\d+)\+(?P<x>-?\d+)\+(?P<y>-?\d+)")


def parse_xrandr(text: str) -> List[Monitor]:
    """Read `xrandr --query` output.

    Only lines for a screen that is connected AND has a mode set count: a
    monitor that is plugged in but switched off has no geometry, and putting
    a window on it would put it nowhere.
    """
    out = []
    for line in (text or "").split("\n"):
        m = XRANDR.match(line.strip())
        if m:
            out.append(_monitor(m.group("name"), m.group("x"), m.group("y"),
                                m.group("w"), m.group("h"),
                                bool(m.group("primary"))))
    return out


def _linux_monitors() -> List[Monitor]:
    result = subprocess.run(["xrandr", "--query"], capture_output=True,
                            text=True, timeout=10)
    return parse_xrandr(result.stdout)


# ── macOS ────────────────────────────────────────────────────────────────────

def parse_system_profiler(data: Any) -> List[Monitor]:
    """Read the displays out of `system_profiler SPDisplaysDataType -json`.

    It reports each screen's resolution and which one is the main one, but
    not where they sit relative to each other - so the positions here are
    laid out left to right in the order given, with the main one first. That
    is a guess about the arrangement, which is why the chooser always also
    offers a window to drag.
    """
    screens = []
    for card in (data or {}).get("SPDisplaysDataType", []) or []:
        for disp in (card.get("spdisplays_ndrvs") or []):
            res = str(disp.get("_spdisplays_resolution")
                      or disp.get("spdisplays_resolution") or "")
            m = re.search(r"(\d+)\s*x\s*(\d+)", res)
            if not m:
                continue
            main = str(disp.get("spdisplays_main") or "").lower() in (
                "spdisplays_yes", "yes", "true")
            screens.append((disp.get("_name") or "Display",
                            int(m.group(1)), int(m.group(2)), main))
    screens.sort(key=lambda s: not s[3])      # the main one first
    out, x = [], 0
    for name, w, h, main in screens:
        out.append(_monitor(name, x, 0, w, h, main))
        x += w
    return out


def _macos_monitors() -> List[Monitor]:
    import json
    result = subprocess.run(
        ["system_profiler", "-json", "SPDisplaysDataType"],
        capture_output=True, text=True, timeout=30)
    return parse_system_profiler(json.loads(result.stdout or "{}"))


# ── The guess, for when none of the above answered ───────────────────────────

def from_tk(virtual_width: int, virtual_height: int,
            main_width: int, main_height: int) -> List[Monitor]:
    """What can be worked out from Tk alone.

    Tk reports the whole desktop as one screen. A desktop appreciably wider
    than the screen the app is on means monitors side by side, and the
    remainder is the second one. It cannot see a screen stacked above or
    below, or one to the left, and it is wrong about the split whenever the
    two are different sizes - so this is the last resort, and the chooser
    says it is a guess.
    """
    main = _monitor("Main screen", 0, 0, main_width, main_height, True)
    spare = int(virtual_width) - int(main_width)
    if spare > 200:
        return [main, _monitor("Second screen", main_width, 0, spare,
                               virtual_height)]
    return [main]


# ── What the app asks ────────────────────────────────────────────────────────

def list_monitors(virtual_width: int = 0, virtual_height: int = 0,
                  main_width: int = 0, main_height: int = 0) -> List[Monitor]:
    """Every screen on this PC, the primary one first where that is known.

    The Tk measurements are passed in rather than taken here so this module
    never needs a window to exist - it is asked before one is opened, and
    from tests that have no display at all.
    """
    ways = {"win32": _windows_monitors,
            "darwin": _macos_monitors}.get(sys.platform, _linux_monitors)
    try:
        found = ways()
    except Exception:
        found = []
    if found:
        found.sort(key=lambda m: (not m["primary"], m["x"], m["y"]))
        for i, m in enumerate(found, 1):
            m["name"] = m["name"] or (f"Screen {i}" + (" (main)" if m["primary"]
                                                       else ""))
        return found
    if main_width and virtual_width:
        return from_tk(virtual_width, virtual_height, main_width, main_height)
    return []


def second_screen(monitors: List[Monitor]) -> Monitor | None:
    """The one to put a customer display on, if there is an obvious one.

    Obvious means exactly one screen that is not the primary. With three
    screens there is no obvious answer and somebody has to say which.
    """
    others = [m for m in (monitors or []) if not m["primary"]]
    return others[0] if len(others) == 1 else None


def describe(mon: Monitor, monitors: List[Monitor] | None = None) -> str:
    """One line about a screen, for a list somebody is choosing from."""
    where = "main screen" if mon["primary"] else _side(mon, monitors)
    return f'{mon["name"]} — {mon["width"]}×{mon["height"]}, {where}'


def _side(mon: Monitor, monitors: List[Monitor] | None = None) -> str:
    """Where this screen is in relation to the main one.

    Coordinates are absolute across the whole desktop, not measured from the
    main screen - so a monitor to the LEFT of the main one sits at x=0 while
    the main one sits at x=1920, and reading the sign of x alone calls it
    "to the right". It has to be compared against where the main screen
    actually is.
    """
    primary = next((m for m in (monitors or []) if m["primary"]), None)
    base_x = primary["x"] + primary["width"] // 2 if primary else 0
    base_y = primary["y"] + primary["height"] // 2 if primary else 0
    cx = mon["x"] + mon["width"] // 2
    cy = mon["y"] + mon["height"] // 2
    if cx > base_x:
        return "to the right"
    if cx < base_x:
        return "to the left"
    if cy < base_y:
        return "above"
    if cy > base_y:
        return "below"
    return "second screen"


def geometry(mon: Monitor, fill: bool = True) -> str:
    """A Tk geometry string that lands a window on that screen.

    Inset slightly when not filling it, so a window that is meant to be
    dragged or resized is not flush against the corner with no title bar to
    grab.
    """
    if fill:
        return f'{mon["width"]}x{mon["height"]}+{mon["x"]}+{mon["y"]}'
    w = max(600, int(mon["width"] * 0.8))
    h = max(400, int(mon["height"] * 0.8))
    return f'{w}x{h}+{mon["x"] + 40}+{mon["y"] + 40}'
