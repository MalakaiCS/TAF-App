"""Make the Mac app icon out of the logo the app already ships.

    python make_mac_icon.py          # writes icon_master.png
    python make_mac_icon.py --icns   # and TAF_logo.icns, on a Mac

Two separate steps on purpose. The square master is plain Pillow and runs
anywhere, so it can be checked; the .icns itself is made with iconutil, which
is Apple's own and is the only thing that reliably produces a file every
version of macOS is happy with.

Why not the icon already in the repo: TAF_logo.ico holds one 16x16 frame, and
a Dock icon is drawn at 1024. Blown up from 16 it is a smear. The circular
logo is 3508x2481 of real artwork, which is where this starts instead.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "TAF_logo_circular.png"
MASTER = ROOT / "icon_master.png"
ICNS = ROOT / "TAF_logo.icns"

# macOS expects the artwork to sit inside its square with a little air around
# it, the way every icon in the Dock does. Filling the square edge to edge
# makes it look bigger than its neighbours and slightly wrong.
PADDING = 0.08


def master(source: Path = SOURCE, out: Path = MASTER) -> Path:
    """A square 1024x1024 PNG of the logo, centred, on nothing."""
    art = Image.open(source).convert("RGBA")
    # The file is a wide canvas with the round logo in the middle of it. Crop
    # to what is actually drawn, or the icon comes out as a small circle
    # marooned in a lot of empty space.
    box = art.getchannel("A").getbbox() or art.getbbox()
    logo = art.crop(box)

    side = max(logo.size)
    pad = int(side * PADDING)
    canvas = Image.new("RGBA", (side + 2 * pad, side + 2 * pad), (0, 0, 0, 0))
    canvas.paste(logo, ((canvas.width - logo.width) // 2,
                        (canvas.height - logo.height) // 2), logo)
    canvas.resize((1024, 1024), Image.LANCZOS).save(out)
    return out


def icns(src: Path = MASTER, out: Path = ICNS) -> Path:
    """Every size macOS asks for, packed into one .icns. Needs a Mac."""
    if sys.platform != "darwin":
        raise RuntimeError("iconutil is macOS only - run the build on a Mac")
    art = Image.open(src)
    folder = out.parent / "icon.iconset"
    folder.mkdir(exist_ok=True)
    try:
        for size in (16, 32, 128, 256, 512):
            art.resize((size, size), Image.LANCZOS).save(
                folder / f"icon_{size}x{size}.png")
            art.resize((size * 2, size * 2), Image.LANCZOS).save(
                folder / f"icon_{size}x{size}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(folder), "-o", str(out)],
                       check=True)
    finally:
        for f in folder.glob("*.png"):
            f.unlink()
        folder.rmdir()
    return out


if __name__ == "__main__":
    print(master())
    if "--icns" in sys.argv:
        print(icns())
