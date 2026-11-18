"""Make the phone app's icons out of the logo the app already ships.

    python make_web_icons.py

Writes, from TAF_logo_circular.png (3508x2481 of real artwork):

    docs/app/icon-192.png            the app's icon (Android, the browser tab)
    docs/app/icon-512.png            the same, large (the install screen)
    docs/app/icon-maskable-512.png   Android's adaptive icon: the logo kept
                                     inside the middle 80%, which is all a
                                     round or squircle mask is sure to show
    docs/taf-icon-180.png            the iPhone home-screen icon, for every
                                     page (app, phone inbox, portal, quote)

Each is the round logo on white. White, not transparent: an iPhone fills a
transparent icon with black, which turns the logo's white circle into a
black square with a ring in it.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "TAF_logo_circular.png"

# How much of the square the round logo fills.
FULL = 0.94           # an ordinary icon: a little air around the circle
MASKED = 0.80         # a maskable one: inside the safe zone


def _logo() -> Image.Image:
    """The circle on its own, cropped from the wide artwork."""
    art = Image.open(SOURCE).convert("RGBA")
    box = art.getchannel("A").getbbox() or (0, 0, art.width, art.height)
    logo = art.crop(box)
    side = max(logo.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(logo, ((side - logo.width) // 2, (side - logo.height) // 2))
    return square


def icon(size: int, fill: float) -> Image.Image:
    logo = _logo()
    inner = round(size * fill)
    logo = logo.resize((inner, inner), Image.LANCZOS)
    out = Image.new("RGB", (size, size), (255, 255, 255))
    at = (size - inner) // 2
    out.paste(logo, (at, at), logo)
    return out


def main() -> None:
    targets = [
        (ROOT / "docs" / "app" / "icon-192.png", 192, FULL),
        (ROOT / "docs" / "app" / "icon-512.png", 512, FULL),
        (ROOT / "docs" / "app" / "icon-maskable-512.png", 512, MASKED),
        (ROOT / "docs" / "taf-icon-180.png", 180, FULL),
    ]
    for path, size, fill in targets:
        icon(size, fill).save(path, "PNG", optimize=True)
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
