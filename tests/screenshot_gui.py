"""
Photograph the real app, tab by tab.

Redesigning a window you cannot see is guesswork. This starts the actual
application against the smoke test's stand-in database, opens each tab, and
saves a PNG of it — so a change to spacing, colour or type can be looked at
instead of imagined.

    python tests/screenshot_gui.py [outdir] [--scale 1.5] [--tabs a,b]

Needs a display. On a build machine: xvfb-run python tests/screenshot_gui.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

WIDTH, HEIGHT = 1600, 950


def _grab(path: Path) -> bool:
    """Save the whole X display. import(1) is part of ImageMagick."""
    for cmd in (["import", "-window", "root", str(path)],
                ["xwd", "-root", "-silent", "-out", str(path) + ".xwd"]):
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=30)
            return True
        except Exception:
            continue
    return False


def main() -> int:
    args = [a for a in sys.argv[1:]]
    out = Path(args[0]) if args and not args[0].startswith("-") else ROOT / "screenshots"
    scale = 0.0
    if "--scale" in args:
        scale = float(args[args.index("--scale") + 1])
    only = None
    if "--tabs" in args:
        only = args[args.index("--tabs") + 1].split(",")
    out.mkdir(parents=True, exist_ok=True)

    import smoke_gui                      # the stand-in database and stubs
    smoke_gui.install_stubs(manager=True)

    import tkinter as tk
    try:
        root = tk.Tk()
    except Exception as exc:
        print(f"SKIP: no display ({exc})")
        return 0

    import modern_order_gui as gui
    if scale:
        # Pretend the screen is this much denser than 96 DPI, so a high-DPI
        # layout can be looked at without a high-DPI screen.
        gui.UI_SCALE = scale
        root.tk.call("tk", "scaling", scale * 96.0 / 72.0)
    else:
        gui._apply_ui_scale(root)
    print(f"  UI_SCALE={gui.UI_SCALE:.2f}  "
          f"tk scaling={float(root.tk.call('tk', 'scaling')):.2f}")
    root.geometry(f"{WIDTH}x{HEIGHT}+0+0")
    root.update()

    app = gui.ModernOrderApp(root)
    tabs = only or (["dashboard"] + list(getattr(app, "_lazy_tab_builders", {})))

    shots = []

    def _drive(queue):
        if not queue:
            root.quit()
            return
        key = queue.pop(0)
        try:
            app._ensure_tab_built(key)
            app._show_tab(key)
        except Exception as exc:
            print(f"  {key}: could not open ({exc})")
            root.after(50, lambda: _drive(queue))
            return

        def _shoot():
            root.update_idletasks()
            png = out / f"{key}.png"
            if _grab(png):
                shots.append(png)
                print(f"  saved {png.name}")
            else:
                print("  no screenshot tool (install ImageMagick)")
            root.after(50, lambda: _drive(queue))

        # Let the tab's background load land before photographing it.
        root.after(1200, _shoot)

    root.after(600, lambda: _drive(list(tabs)))
    root.after(120000, root.quit)
    root.mainloop()
    try:
        root.destroy()
    except Exception:
        pass
    print(f"\n{len(shots)} screenshot(s) in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
