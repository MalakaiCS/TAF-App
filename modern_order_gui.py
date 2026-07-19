
import sys
import datetime as _dt_module
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

try:
    from tkcalendar import DateEntry as _DateEntry
    _HAS_TKCALENDAR = True
except ImportError:
    _HAS_TKCALENDAR = False
from pathlib import Path
import json
import platform
import os
import calendar as _cal
import datetime
import threading
from concurrent.futures import ThreadPoolExecutor

from taf_order_app import OrderService
from taf_order_app.validation import VALID_FILTER_TYPES, VALID_MEDIA_TYPES
from taf_order_app import db as _db
from taf_order_app.bag_filler import (
    BAG_PRODUCT_TYPES, BAG_MEDIA_TYPES, ROLL_MEDIA_TYPES,
    ROLL_WIDTHS, ROLL_LENGTHS, STANDARD_SIZES,
    generate_part_number, build_label_line, build_dims_line,
    item_summary_short, generate_bag_docket, generate_unified_docket,
)

# ── App info ──────────────────────────────────────────────────────────────
APP_TITLE   = "Total Air Filtration  ·  Filter Order Entry"
from taf_order_app.updater import APP_VERSION

# When frozen by PyInstaller the exe lives in its own folder;
# Writable user data goes in %APPDATA%\TAF Order Entry when installed,
# or next to the script during development.
if getattr(sys, "frozen", False):
    RESOURCE_DIR = Path(sys._MEIPASS)
    APP_DIR      = Path(os.environ.get("APPDATA", Path.home())) / "TAF Order Entry"
else:
    APP_DIR      = Path(__file__).resolve().parent
    RESOURCE_DIR = APP_DIR

APP_DIR.mkdir(parents=True, exist_ok=True)
ORDERS_DIR    = APP_DIR / "orders"
DRAFT_FILE    = APP_DIR / "draft_order.json"
SETTINGS_FILE = APP_DIR / "settings.json"

# On first run after install, seed settings.json from bundled resources
if not SETTINGS_FILE.exists():
    _bundled = RESOURCE_DIR / "settings.json"
    if _bundled.exists():
        import shutil
        shutil.copy2(_bundled, SETTINGS_FILE)

# Built-in defaults (never deletable from Settings)
DEFAULT_MEDIA_TYPES = list(VALID_MEDIA_TYPES)

# Customer-facing note automatically stamped on every stepped-filter item.
STEPPED_FILTER_NOTE = "*STEPPED FILTER*"


def classify_by_channel(channel) -> "tuple[str | None, str | None]":
    """Map a channel thickness (mm) to an auto filter/media type.

    Returns ``(filter_type, media_type)`` where either element may be ``None``
    when that field should be left untouched:

      •  9–11 mm  → Flyscreen, GREY media
      • 12–29 mm  → Flat Panel  (media left as-is)
      • 30 mm +   → V-form / pleated panel filter (media left as-is)
    """
    try:
        ch = int(str(channel).strip())
    except (TypeError, ValueError):
        return (None, None)
    if 9 <= ch <= 11:
        return ("Flyscreen", "GREY")
    if 12 <= ch <= 29:
        return ("Flat Panel", None)
    if ch >= 30:
        return ("V-form", None)
    return (None, None)


def apply_stepped_filter_note(item: dict) -> dict:
    """Ensure stepped-filter items carry the *STEPPED FILTER* customer note.

    Mutates and returns ``item``. The note is prepended to any existing notes
    and is idempotent (never added twice).
    """
    if (item.get("Filter Type") or "").strip() != "Stepped Filter":
        return item
    notes = (item.get("Notes") or "").strip()
    if STEPPED_FILTER_NOTE.lower() not in notes.lower():
        item["Notes"] = f"{STEPPED_FILTER_NOTE}\n{notes}".strip() if notes else STEPPED_FILTER_NOTE
    return item


def _load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"custom_media_types": [], "supabase_anon_key": ""}


def _save_settings(data: dict) -> None:
    SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

# ── Colour palette ────────────────────────────────────────────────────────
CA   = "#1DA1E6"   # TAF brand blue (primary actions, active tab, links)
CAH  = "#1791CF"   # brand blue hover
CA2  = "#1187C9"   # deeper brand blue (secondary solid buttons)
CBG  = "#EDF1F4"   # window / page background
CCA  = "#FFFFFF"   # card / panel surface
CTX  = "#0F1A24"   # primary text
CMU  = "#5C6B78"   # muted / secondary text
CSP  = "#DCE4EA"   # separator / border
CGR  = "#09A659"   # TAF brand green (Generate Output, Save, success)
CGH  = "#08914E"   # green hover
CRD  = "#E5484D"   # danger red
CRH  = "#D23A3F"   # red hover
CNE  = "#546572"   # neutral slate (Archive)
CNH  = "#44525C"   # neutral hover (must differ from CTX so dark-mode swap works)
CRE  = "#FAFCFD"   # zebra / even row tint
CSL  = "#E5F4FC"   # selected row
CNV  = "#16384B"   # navy header (card / section / table headers, title bar)
CFD  = "#F4F8FA"   # field background


_LIGHT_COLORS = {
    "CA": "#1DA1E6", "CAH": "#1791CF", "CA2": "#1187C9",
    "CBG": "#EDF1F4", "CCA": "#FFFFFF",
    "CTX": "#0F1A24", "CMU": "#5C6B78", "CSP": "#DCE4EA",
    "CGR": "#09A659", "CGH": "#08914E",
    "CRD": "#E5484D", "CRH": "#D23A3F",
    "CNE": "#546572", "CNH": "#44525C",
    "CRE": "#FAFCFD", "CSL": "#E5F4FC",
    "CNV": "#16384B", "CFD": "#F4F8FA",
}
_DARK_COLORS = {
    "CA": "#1DA1E6", "CAH": "#38B0EE", "CA2": "#4FB4ED",
    "CBG": "#0C1A24", "CCA": "#13242F",
    "CTX": "#EAF1F6", "CMU": "#8FA0AC", "CSP": "#243540",
    "CGR": "#09A659", "CGH": "#0BB863",
    "CRD": "#E5484D", "CRH": "#F05A5F",
    "CNE": "#5C6B78", "CNH": "#6A7A86",
    "CRE": "#16242E", "CSL": "#143246",
    "CNV": "#0A1F2B", "CFD": "#0F2029",
}

def _set_dark_mode():
    """Reassign all module-level colour globals to the dark palette."""
    global CA, CAH, CA2, CBG, CCA, CTX, CMU, CSP
    global CGR, CGH, CRD, CRH, CNE, CNH, CRE, CSL, CNV, CFD
    CA  = "#1DA1E6";  CAH = "#38B0EE";  CA2 = "#4FB4ED"
    CBG = "#0C1A24";  CCA = "#13242F"
    CTX = "#EAF1F6";  CMU = "#8FA0AC";  CSP = "#243540"
    CGR = "#09A659";  CGH = "#0BB863"
    CRD = "#E5484D";  CRH = "#F05A5F"
    CNE = "#5C6B78";  CNH = "#6A7A86"
    CRE = "#16242E";  CSL = "#143246"
    CNV = "#0A1F2B";  CFD = "#0F2029"

def _set_light_mode():
    """Restore all module-level colour globals to the light palette."""
    global CA, CAH, CA2, CBG, CCA, CTX, CMU, CSP
    global CGR, CGH, CRD, CRH, CNE, CNH, CRE, CSL, CNV, CFD
    CA  = "#1DA1E6";  CAH = "#1791CF";  CA2 = "#1187C9"
    CBG = "#EDF1F4";  CCA = "#FFFFFF"
    CTX = "#0F1A24";  CMU = "#5C6B78";  CSP = "#DCE4EA"
    CGR = "#09A659";  CGH = "#08914E"
    CRD = "#E5484D";  CRH = "#D23A3F"
    CNE = "#546572";  CNH = "#44525C"
    CRE = "#FAFCFD";  CSL = "#E5F4FC"
    CNV = "#16384B";  CFD = "#F4F8FA"

def _restyle_widget_tree(widget, color_map: dict):
    """Recursively update widget colour properties using color_map {OLD_HEX: new_hex}."""
    _PROPS = (
        "bg", "fg", "background", "foreground",
        "activebackground", "activeforeground",
        "insertbackground", "selectbackground", "selectforeground",
        "highlightbackground", "highlightcolor",
        "disabledforeground", "troughcolor",
    )
    for prop in _PROPS:
        try:
            val = str(widget.cget(prop)).upper()
            if val in color_map:
                widget.configure(**{prop: color_map[val]})
        except Exception:
            pass
    try:
        for child in widget.winfo_children():
            _restyle_widget_tree(child, color_map)
    except Exception:
        pass

# ── Fonts ─────────────────────────────────────────────────────────────────
# Public Sans is the TAF brand font (bundled in fonts/). _load_app_fonts()
# registers the .ttf files at startup and falls back to Segoe UI if the
# family is unavailable, rebuilding the F_* globals to match.
FAM    = "Public Sans"
F_BODY = (FAM, 9)
F_BOLD = (FAM, 9,  "bold")
F_SEC  = (FAM, 10, "bold")
F_TTL  = (FAM, 15, "bold")
F_SM   = (FAM, 8)


def _load_app_fonts():
    """Register bundled Public Sans .ttf files and point the F_* globals at them.

    Must run after a Tk root exists (Tk font enumeration needs it) but before
    any widgets are built. Falls back to Segoe UI if Public Sans can't load.
    """
    global FAM, F_BODY, F_BOLD, F_SEC, F_TTL, F_SM
    fam = "Public Sans"
    try:
        if os.name == "nt":
            import ctypes
            FR_PRIVATE = 0x10
            font_dir = RESOURCE_DIR / "fonts"
            if font_dir.exists():
                for ttf in sorted(font_dir.glob("PublicSans-*.ttf")):
                    ctypes.windll.gdi32.AddFontResourceExW(str(ttf), FR_PRIVATE, 0)
        import tkinter.font as _tkf
        if "Public Sans" not in _tkf.families():
            fam = "Segoe UI"
    except Exception:
        fam = "Segoe UI"
    FAM    = fam
    F_BODY = (fam, 9)
    F_BOLD = (fam, 9,  "bold")
    F_SEC  = (fam, 10, "bold")
    F_TTL  = (fam, 15, "bold")
    F_SM   = (fam, 8)


# ── Compressor filter pack presets ───────────────────────────────────────────
# Source: COMP AIR / GARDNER DENVER dirty-environment filter pack spec sheet.
# "frames"  → Mounting Frame bag items  (short × long mm)
# "filters" → Pleated panel (V-form) filter items (short × long × channel mm)
# "label"   → optional suffix appended to item Notes for multi-size packs
# REP/FIL orders use the same filter specs at HALF quantity, no frames.

DEDICATED_FILTER_PACKS = {
    # ── Comp Air / Gardner Denver ─────────────────────────────────────────────
    "L11": {
        "frames":  [{"qty": 1, "short": 455,  "long": 510}],
        "filters": [{"qty": 2, "short": 440,  "long": 495,  "channel": 95}],
    },
    "L15-L22": {
        "frames":  [{"qty": 1, "short": 540,  "long": 540}],
        "filters": [{"qty": 2, "short": 525,  "long": 525,  "channel": 95}],
    },
    "L30-L50": {
        "frames":  [{"qty": 1, "short": 680,  "long": 770}],
        "filters": [{"qty": 2, "short": 665,  "long": 755,  "channel": 95}],
    },
    "L55-L80": {
        "frames":  [{"qty": 1, "short": 1020, "long": 1050}],
        "filters": [{"qty": 2, "short": 1005, "long": 1035, "channel": 95}],
    },
    "L90-L132": {
        "frames":  [{"qty": 2, "short": 710,  "long": 850}],
        "filters": [{"qty": 4, "short": 695,  "long": 835,  "channel": 95}],
    },
    "L160-250": {
        "frames":  [
            {"qty": 1, "short": 550, "long": 1400},
            {"qty": 2, "short": 250, "long": 600},
            {"qty": 1, "short": 350, "long": 700},
        ],
        "filters": [
            {"qty": 2, "short": 535, "long": 1385, "channel": 95},
            {"qty": 4, "short": 235, "long": 585,  "channel": 95},
            {"qty": 2, "short": 335, "long": 685,  "channel": 95},
        ],
    },
    "L160-250V2": {
        "frames":  [
            {"qty": 1, "short": 405, "long": 435,  "label": "F"},
            {"qty": 2, "short": 830, "long": 1560, "label": "C"},
            {"qty": 1, "short": 255, "long": 500,  "label": "B"},
        ],
        "filters": [
            {"qty": 2, "short": 390, "long": 420,  "channel": 95, "label": "F"},
            {"qty": 4, "short": 815, "long": 1545, "channel": 95, "label": "C"},
            {"qty": 2, "short": 240, "long": 485,  "channel": 95, "label": "B"},
        ],
    },
}

SIGRIST_PACK = {
    "filters": [{"qty": 1, "short": 412, "long": 412, "channel": 90,
                 "media": "F5", "filter_type": "V-form"}],
}

STEPPED_PACKS = {
    "535x535x50": {
        "filters": [{"qty": 1, "short": 535, "long": 535,  "channel": 50,
                     "filter_type": "Stepped Filter", "media": "180"}],
    },
    "535x1135x50": {
        "filters": [{"qty": 1, "short": 535, "long": 1135, "channel": 50,
                     "filter_type": "Stepped Filter", "media": "180"}],
    },
}

COMPRESSOR_PACKS = DEDICATED_FILTER_PACKS


# ── COM pre-warm ─────────────────────────────────────────────────────────────
# Called once on a background thread right after the window opens.
# By the time the user fills in the form and clicks Generate, Excel and Word
# are already running hidden → first order is as fast as subsequent ones.

def _prewarm_com():
    try:
        from template_filler import prewarm_excel
        prewarm_excel()
    except Exception:
        pass
    try:
        from taf_order_app.bag_filler import prewarm_word
        prewarm_word()
    except Exception:
        pass


# ── Utility helpers ───────────────────────────────────────────────────────────

def _dk(hex_color: str, n: int = 22) -> str:
    """Darken a hex colour by n points per channel."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"#{max(0, r-n):02X}{max(0, g-n):02X}{max(0, b-n):02X}"


def _initials(name: str) -> str:
    """Two-letter initials for the profile avatar (e.g. 'Kai Brown' -> 'KB')."""
    parts = [p for p in name.replace("_", " ").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _draw_bar_chart(canvas, values, labels, W, H, PAD=40,
                    bar_colour=None, horizontal=False):
    """Draw a simple bar chart on a tk.Canvas using only Tkinter primitives."""
    canvas.delete("all")
    if not values or max(values, default=0) == 0:
        canvas.create_text(W // 2, H // 2, text="No data",
                           fill=CMU, font=F_SM)
        return
    bar_colour = bar_colour or CA
    max_val = max(values)
    n = len(values)

    if not horizontal:
        chart_h = H - PAD - 24
        chart_w = W - PAD * 2
        bar_w   = max(6, chart_w // n - 6)
        for i, (val, lbl) in enumerate(zip(values, labels)):
            bh = int((val / max_val) * chart_h)
            x  = PAD + i * (chart_w // n) + 3
            y_top = H - PAD - bh
            canvas.create_rectangle(x, y_top, x + bar_w, H - PAD,
                                    fill=bar_colour, outline="")
            canvas.create_text(x + bar_w // 2, H - PAD + 5, text=str(lbl),
                               font=(FAM, 7), anchor="n", fill=CMU)
            if val > 0:
                canvas.create_text(x + bar_w // 2, y_top - 3, text=str(val),
                                   font=(FAM, 7), anchor="s", fill=CTX)
        canvas.create_line(PAD, PAD // 2, PAD, H - PAD, fill=CSP, width=1)
        canvas.create_line(PAD, H - PAD, W - PAD, H - PAD, fill=CSP, width=1)
    else:
        lbl_w   = 110
        chart_w = W - lbl_w - PAD - 30
        row_h   = max(18, (H - PAD) // max(n, 1))
        for i, (val, lbl) in enumerate(zip(values, labels)):
            bw = int((val / max_val) * chart_w) if chart_w > 0 else 0
            y  = PAD // 2 + i * row_h
            canvas.create_text(lbl_w - 6, y + row_h // 2,
                               text=str(lbl)[:22], font=(FAM, 8),
                               anchor="e", fill=CTX)
            canvas.create_rectangle(lbl_w, y + 3, lbl_w + bw, y + row_h - 3,
                                    fill=bar_colour, outline="")
            if val > 0:
                canvas.create_text(lbl_w + bw + 5, y + row_h // 2,
                                   text=str(val), font=(FAM, 7),
                                   anchor="w", fill=CMU)


def _rgb(c: str):
    h = c.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _blend(c1: str, c2: str, t: float) -> str:
    a, b = _rgb(c1), _rgb(c2)
    r = int(a[0] + (b[0]-a[0])*t)
    g = int(a[1] + (b[1]-a[1])*t)
    bl = int(a[2] + (b[2]-a[2])*t)
    return f"#{r:02X}{g:02X}{bl:02X}"


def _round_pts(x1, y1, x2, y2, r):
    return [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2,
            x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]


def _round_rect(cv, x1, y1, x2, y2, r, **kw):
    return cv.create_polygon(_round_pts(x1, y1, x2, y2, r), smooth=True, **kw)


# ── Type badges (Pillow-rendered pill images for treeview #0 columns) ────────
_BADGE_CACHE = {}
_TYPE_BADGE_COLORS = {
    "Filter":   ("#E5F1FB", "#1187C9"),
    "Bags":     ("#E6F6EC", "#0A7A43"),
    "Bag/Roll": ("#E6F6EC", "#0A7A43"),
    "Mixed":    ("#FBEFE0", "#B4791B"),
}


def _badge_image(text, bg, fg, h=22, pad_x=11):
    """Return a cached Tk PhotoImage of a rounded pill with `text`, or None."""
    key = (text, bg, fg, h)
    cached = _BADGE_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageTk
    except Exception:
        return None
    s = 3  # supersample for crisp corners + text
    try:
        fnt = ImageFont.truetype(str(RESOURCE_DIR / "fonts" / "PublicSans-Bold.ttf"),
                                 int(10.5 * s))
    except Exception:
        try:
            fnt = ImageFont.load_default()
        except Exception:
            return None
    d0 = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    bb = d0.textbbox((0, 0), text, font=fnt)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    W, H = tw + pad_x * 2 * s, h * s
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=H // 2, fill=bg)
    d.text(((W - tw) // 2 - bb[0], (H - th) // 2 - bb[1]), text, font=fnt, fill=fg)
    im = im.resize((max(1, W // s), max(1, H // s)), Image.LANCZOS)
    ph = ImageTk.PhotoImage(im)
    _BADGE_CACHE[key] = ph
    return ph


def _type_badge(label):
    bg, fg = _TYPE_BADGE_COLORS.get(label, ("#EEF1F4", "#5C6B78"))
    return _badge_image(label, bg, fg)


class PillButton(tk.Canvas):
    """Rounded (pill) button drawn on a Canvas, with hover + a config() shim
    so existing callers that do .config(text=/bg=/state=) keep working."""

    def __init__(self, parent, text, command=None, bg=None, fg="white",
                 hover=None, font=None, h=36, padx=16, radius=9, bgbase=None):
        bg = bg or CA
        try:
            base = bgbase or parent.cget("bg")
        except Exception:
            base = CBG
        import tkinter.font as _tkf
        self._fontobj = _tkf.Font(font=font or F_BOLD)
        w = self._fontobj.measure(text) + padx * 2
        super().__init__(parent, bg=base, highlightthickness=0, bd=0,
                         width=w, height=h)
        self._text = text; self._fg = fg; self._bg = bg
        self._hover = hover or _dk(bg, 16); self._cmd = command
        self._r = radius; self._cw = w; self._ch = h; self._padx = padx
        self._state = "normal"
        self._draw(bg)
        self.bind("<Enter>", lambda e: self._state == "normal" and self._draw(self._hover))
        self.bind("<Leave>", lambda e: self._state == "normal" and self._draw(self._bg))
        self.bind("<Button-1>", self._on_click)
        super().configure(cursor="hand2")

    def _draw(self, fill):
        self.delete("all")
        if self._state == "disabled":
            fill = _blend(self._bg, "#FFFFFF", 0.55)
            txt = _blend(self._fg, fill, 0.45)
        else:
            txt = self._fg
        _round_rect(self, 1, 1, self._cw - 1, self._ch - 1, self._r, fill=fill, outline="")
        self.create_text(self._cw // 2, self._ch // 2 + 1, text=self._text,
                         fill=txt, font=self._fontobj)

    def _on_click(self, e):
        if self._state == "normal" and self._cmd:
            self._cmd()

    def configure(self, **kw):
        redraw = False
        if "text" in kw:
            self._text = kw.pop("text"); redraw = True
        if "bg" in kw:
            self._bg = kw.pop("bg"); self._hover = _dk(self._bg, 16); redraw = True
        if "background" in kw:
            self._bg = kw.pop("background"); self._hover = _dk(self._bg, 16); redraw = True
        if "fg" in kw:
            self._fg = kw.pop("fg"); redraw = True
        if "state" in kw:
            self._state = kw.pop("state"); redraw = True
        if "command" in kw:
            self._cmd = kw.pop("command")
        if redraw:
            self._cw = self._fontobj.measure(self._text) + self._padx * 2
            super().configure(width=self._cw)
            self._draw(self._bg)
        if kw:
            super().configure(**kw)
    config = configure

    def cget(self, key):
        if key == "text":
            return self._text
        if key in ("bg", "background"):
            return self._bg
        if key == "state":
            return self._state
        return super().cget(key)


class RoundedCard(tk.Canvas):
    """White rounded card with an optional navy rounded-top header.
    `.body` is a Frame for content. Sizes to content, and fills extra space
    when packed/gridded with expand."""

    def __init__(self, parent, title="", bg_hdr=None, radius=12, hdr_h=44,
                 pad=16, bgbase=None):
        try:
            base = bgbase or parent.cget("bg")
        except Exception:
            base = CBG
        super().__init__(parent, bg=base, highlightthickness=0, bd=0)
        self._R = radius
        self._hdr_h = hdr_h if title else 0
        self._pad = pad
        self._title = title
        self._hdrbg = bg_hdr or CNV
        self._hdr_right = ""
        self._last_self = None      # (w,h) guard — avoid redundant redraws
        self._last_body = None
        self.body = tk.Frame(self, bg=CCA)
        self._win = self.create_window(pad, self._hdr_h + pad, anchor="nw",
                                       window=self.body)
        self.body.bind("<Configure>", self._on_body)
        self.bind("<Configure>", self._on_self)

    def _on_body(self, e):
        wh = (self.body.winfo_reqwidth() + self._pad * 2,
              self.body.winfo_reqheight() + self._hdr_h + self._pad * 2)
        if wh == self._last_body:
            return
        self._last_body = wh
        self.configure(width=wh[0], height=wh[1])
        self._redraw()

    def _on_self(self, e):
        if (e.width, e.height) == self._last_self:
            return
        self._last_self = (e.width, e.height)
        bw = max(1, e.width - self._pad * 2)
        bh = max(self.body.winfo_reqheight(), e.height - self._hdr_h - self._pad * 2)
        self.itemconfig(self._win, width=bw, height=bh)
        self._redraw()

    def _redraw(self):
        self.delete("carddeco")
        W, H = self.winfo_width(), self.winfo_height()
        if W < 8 or H < 8:
            return
        _round_rect(self, 1, 1, W - 1, H - 1, self._R,
                    fill=CCA, outline=CSP, width=1, tags="carddeco")
        if self._title:
            hb = self._hdr_h
            _round_rect(self, 1, 1, W - 1, hb + self._R, self._R,
                        fill=self._hdrbg, outline="", tags="carddeco")
            self.create_rectangle(1, hb, W - 1, hb + self._R,
                                  fill=self._hdrbg, outline="", tags="carddeco")
            self.create_text(self._pad, hb // 2, anchor="w", text=self._title,
                             fill="white", font=F_SEC, tags="carddeco")
            if self._hdr_right:
                self.create_text(W - self._pad, hb // 2, anchor="e",
                                 text=self._hdr_right, fill="#9AA9B3",
                                 font=F_SM, tags="carddeco")
        self.tag_lower("carddeco")

    def set_header_right(self, text):
        self._hdr_right = text
        self._redraw()


def flat_btn(parent, text, command, bg=CA, fg="white",
             width=None, font=F_BOLD, pady=6, padx=14) -> "PillButton":
    """Rounded pill button (Canvas-based). `width` (char count) is ignored —
    pills size to their text."""
    return PillButton(parent, text, command=command, bg=bg, fg=fg,
                      font=font, h=pady * 2 + 24, padx=padx)


def card_frame(parent, title="", bg_hdr=CNV, **inner_kw):
    """Returns (card, body). `card` is a RoundedCard; put content in `body`.
    Preserves the old (outer, inner) call contract."""
    card = RoundedCard(parent, title=title, bg_hdr=bg_hdr)
    return card, card.body


def field_entry(parent, textvariable=None, width=None, **kw) -> tk.Entry:
    """Brand input: field-bg fill, 1px border that turns brand-blue on focus."""
    e = tk.Entry(parent,
                 relief="flat", bd=8, highlightthickness=1,
                 highlightbackground=CSP, highlightcolor=CA,
                 font=F_BODY, bg=CFD, fg=CTX, insertbackground=CTX,
                 **kw)
    if textvariable is not None:
        e["textvariable"] = textvariable
    if width is not None:
        e["width"] = width
    return e


def _make_date_entry(parent, textvariable, **kw):
    """Return a DateEntry calendar picker if tkcalendar is available, else a plain Entry."""
    if _HAS_TKCALENDAR:
        try:
            de = _DateEntry(
                parent,
                textvariable=textvariable,
                date_pattern="dd/mm/yy",
                background=CCA, foreground=CTX,
                selectbackground=CA, selectforeground="white",
                normalforeground=CTX, weekendforeground=CTX,
                borderwidth=1, relief="solid",
                font=F_BODY,
                width=10,
                **kw,
            )
            return de
        except Exception:
            # babel locale-data missing or other tkcalendar init failure —
            # fall back to a plain entry so the app still opens.
            pass
    return field_entry(parent, textvariable=textvariable, width=10)


# ── Style helper (called once at startup) ─────────────────────────────────

def _configure_ttk_style():
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure("TAF.Treeview",
                    background=CCA,
                    fieldbackground=CCA,
                    foreground=CTX,
                    font=F_BODY,
                    rowheight=26,
                    borderwidth=0,
                    relief="flat")
    style.configure("TAF.Treeview.Heading",
                    background=CNV,
                    foreground="white",
                    font=F_BOLD,
                    relief="flat",
                    padding=(8, 5))
    style.map("TAF.Treeview",
              background=[("selected", CSL)],
              foreground=[("selected", CTX)])
    style.map("TAF.Treeview.Heading",
              background=[("active", _dk(CNV, 12))])

    style.configure("TCombobox",
                    fieldbackground=CFD, background=CFD, foreground=CTX,
                    bordercolor=CSP, lightcolor=CSP, darkcolor=CSP,
                    arrowcolor=CMU, arrowsize=13,
                    padding=(8, 5), relief="flat")
    style.map("TCombobox",
              fieldbackground=[("readonly", CFD), ("disabled", CBG)],
              foreground=[("readonly", CTX)],
              bordercolor=[("focus", CA), ("hover", CA)],
              lightcolor=[("focus", CA)], darkcolor=[("focus", CA)],
              arrowcolor=[("active", CA)],
              selectbackground=[("readonly", CFD)],
              selectforeground=[("readonly", CTX)])

    # Dropdown list (popdown) colours via the option database
    _root = tk._default_root
    if _root is not None:
        _root.option_add("*TCombobox*Listbox.background", CCA)
        _root.option_add("*TCombobox*Listbox.foreground", CTX)
        _root.option_add("*TCombobox*Listbox.selectBackground", CA)
        _root.option_add("*TCombobox*Listbox.selectForeground", "white")
        _root.option_add("*TCombobox*Listbox.font", F_BODY)
        _root.option_add("*TCombobox*Listbox.borderWidth", 0)

    style.configure("Vertical.TScrollbar",
                    background=CBG,
                    troughcolor=CBG,
                    borderwidth=0,
                    arrowsize=12)


# ═══════════════════════════════════════════════════════════════════════════
# Calendar Picker
# ═══════════════════════════════════════════════════════════════════════════

class CalendarPicker(tk.Toplevel):
    """
    Compact calendar popup.  Click a day to write dd/mm/yy into target_var.
    Pass anchor= (a widget) to position the popup beneath it.
    """

    def __init__(self, master, target_var: tk.StringVar, anchor=None):
        super().__init__(master)
        self.overrideredirect(True)          # no title bar / chrome
        self.configure(bg=CSP, bd=1, relief="solid")
        self.resizable(False, False)
        self.target_var = target_var

        today = datetime.date.today()
        parsed = self._parse(target_var.get())
        start  = parsed or today
        self.cur_year  = start.year
        self.cur_month = start.month
        self.today     = today

        self._build()
        self._render()

        # ── Position near anchor ──────────────────────────────────────────
        self.update_idletasks()
        if anchor:
            x = anchor.winfo_rootx()
            y = anchor.winfo_rooty() + anchor.winfo_height() + 3
            w = self.winfo_reqwidth()
            h = self.winfo_reqheight()
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            if x + w > sw: x = sw - w - 4
            if y + h > sh: y = anchor.winfo_rooty() - h - 3
            self.geometry(f"+{x}+{y}")

        self.lift()
        self.grab_set()
        self.focus_force()
        self.bind("<Escape>", lambda e: self.destroy())

    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse(s: str):
        for fmt in ("%d/%m/%y", "%d-%m-%y", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                return datetime.datetime.strptime((s or "").strip(), fmt).date()
            except ValueError:
                pass
        return None

    def _build(self):
        # ── Navigation row ────────────────────────────────────────────────
        nav = tk.Frame(self, bg=CA, pady=4)
        nav.pack(fill="x")

        def _nav_btn(text, cmd):
            b = tk.Button(nav, text=text, command=cmd,
                          bg=CA, fg="white", relief="flat", bd=0,
                          font=(FAM, 12, "bold"), padx=10,
                          cursor="hand2",
                          activebackground=_dk(CA), activeforeground="white")
            return b

        _nav_btn("‹", self._prev).pack(side="left")
        self.lbl_nav = tk.Label(nav, text="", bg=CA, fg="white",
                                 font=(FAM, 9, "bold"), width=14)
        self.lbl_nav.pack(side="left", expand=True)
        _nav_btn("›", self._next).pack(side="right")

        # ── Weekday header ────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=CCA, pady=4, padx=4)
        hdr.pack(fill="x")
        for i, d in enumerate(["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]):
            fg = CRD if i >= 5 else CMU
            tk.Label(hdr, text=d, width=4, bg=CCA, fg=fg,
                     font=(FAM, 8, "bold")).grid(row=0, column=i, padx=1)

        # ── Days grid ─────────────────────────────────────────────────────
        self.days_f = tk.Frame(self, bg=CCA, padx=4, pady=2)
        self.days_f.pack(fill="both", expand=True)

        # ── Today shortcut ────────────────────────────────────────────────
        foot = tk.Frame(self, bg=CBG, pady=3)
        foot.pack(fill="x")
        tk.Button(foot, text="Today", command=self._pick_today,
                  bg=CBG, fg=CA, relief="flat", bd=0,
                  font=(FAM, 8, "bold"), cursor="hand2",
                  activebackground=CBG, activeforeground=_dk(CA)
                  ).pack()

    def _render(self):
        for w in self.days_f.winfo_children():
            w.destroy()

        self.lbl_nav.config(
            text=datetime.date(self.cur_year, self.cur_month, 1).strftime("%B  %Y"))

        for r, week in enumerate(_cal.monthcalendar(self.cur_year, self.cur_month)):
            for c, day in enumerate(week):
                if day == 0:
                    tk.Label(self.days_f, text="", width=4, height=1,
                             bg=CCA).grid(row=r, column=c, padx=1, pady=1)
                    continue
                is_today = (datetime.date(self.cur_year, self.cur_month, day)
                            == self.today)
                is_wknd  = c >= 5
                bg_n = CA    if is_today else CCA
                fg_n = "white" if is_today else (CRD if is_wknd else CTX)
                bg_h = _dk(CA) if is_today else CRE

                b = tk.Button(
                    self.days_f, text=str(day),
                    width=4, height=1, relief="flat", bd=0,
                    font=(FAM, 9),
                    bg=bg_n, fg=fg_n, cursor="hand2",
                    activebackground=bg_h,
                    activeforeground="white" if is_today else CTX,
                    command=lambda d=day: self._pick(d),
                )
                b.grid(row=r, column=c, padx=1, pady=1)

    def _prev(self):
        self.cur_month -= 1
        if self.cur_month < 1:
            self.cur_month = 12
            self.cur_year -= 1
        self._render()

    def _next(self):
        self.cur_month += 1
        if self.cur_month > 12:
            self.cur_month = 1
            self.cur_year += 1
        self._render()

    def _pick(self, day: int):
        d = datetime.date(self.cur_year, self.cur_month, day)
        self.target_var.set(d.strftime("%d/%m/%y"))
        self.destroy()

    def _pick_today(self):
        t = self.today
        self.cur_year, self.cur_month = t.year, t.month
        self._pick(t.day)


# ═══════════════════════════════════════════════════════════════════════════
# Compressor Filter Preset Dialog
# ═══════════════════════════════════════════════════════════════════════════

class CompressorFilterDialog(tk.Toplevel):
    """
    Dedicated Filter Presets dialog — three tabs:
      1. Comp Air / Gardner Denver  (L11…L160-250V2)
      2. Sigrist                    (412×412×90, F5 media)
      3. Stepped Filters            (535×535×50 / 535×1135×50, 180 Media)

    result = None if cancelled, else {"items": [...], "job": str, "notes": str}
    """

    _GD_MODELS = list(DEDICATED_FILTER_PACKS.keys())

    def __init__(self, master):
        super().__init__(master)
        self.title("Dedicated Filter Presets")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.lift()
        self.focus_force()
        self.configure(bg=CBG)
        self.result = None

        # ── Header ────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=CA, padx=16, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Dedicated Filter Presets",
                 bg=CA, fg="white", font=(FAM, 11, "bold")).pack(anchor="w")
        tk.Label(hdr, text="Select a preset — filter items will be added to the current order",
                 bg=CA, fg="#A9CCE3", font=F_SM).pack(anchor="w")

        # ── Notebook (tabs) ────────────────────────────────────────────────
        style = ttk.Style(self)
        style.configure("DFP.TNotebook",        background=CBG, borderwidth=0)
        style.configure("DFP.TNotebook.Tab",    background=CBG, foreground=CMU,
                        font=F_BOLD, padding=(14, 7))
        style.map("DFP.TNotebook.Tab",
                  background=[("selected", CCA)],
                  foreground=[("selected", CA)])

        nb = ttk.Notebook(self, style="DFP.TNotebook")
        nb.pack(fill="both", expand=True, padx=0, pady=0)

        self._build_gd_tab(nb)
        self._build_sigrist_tab(nb)
        self._build_stepped_tab(nb)

        # ── Footer ────────────────────────────────────────────────────────
        foot = tk.Frame(self, bg=CBG, padx=16, pady=10)
        foot.pack(fill="x")
        flat_btn(foot, "Cancel",       self.destroy,  bg=CNE, pady=7).pack(side="right", padx=(8, 0))
        flat_btn(foot, "Add to Order", self._confirm, bg=CGR, pady=7).pack(side="right")

        self.update_idletasks()
        W, H = 600, 500
        px = master.winfo_rootx() + master.winfo_width()  // 2 - W // 2
        py = master.winfo_rooty() + master.winfo_height() // 2 - H // 2
        self.geometry(f"{W}x{H}+{px}+{py}")

    # ── Tab 1: Comp Air / Gardner Denver ──────────────────────────────────

    def _build_gd_tab(self, nb):
        frm = tk.Frame(nb, bg=CBG, padx=14, pady=12)
        nb.add(frm, text="  Comp Air / GD  ")

        # Quantity (sets)
        qty_row = tk.Frame(frm, bg=CBG)
        qty_row.pack(fill="x", pady=(0, 8))
        tk.Label(qty_row, text="Number of housings:", bg=CBG, fg=CTX,
                 font=F_BOLD).pack(side="left", padx=(0, 10))
        self._gd_qty = tk.StringVar(value="1")
        tk.Spinbox(qty_row, from_=1, to=50, textvariable=self._gd_qty,
                   width=5, font=F_BODY, relief="solid", bd=1,
                   command=self._gd_update_preview).pack(side="left")
        tk.Label(qty_row, text="  (multiplies filter quantities & updates job name)",
                 bg=CBG, fg=CMU, font=F_SM).pack(side="left")

        # Order type
        self._gd_order_type = tk.StringVar(value="housing")
        type_row = tk.Frame(frm, bg=CBG)
        type_row.pack(fill="x", pady=(0, 10))
        tk.Label(type_row, text="Order type:", bg=CBG, fg=CTX,
                 font=F_BOLD).pack(side="left", padx=(0, 10))

        def _type_btn(text, value, bg):
            def _cmd():
                self._gd_order_type.set(value)
                _refresh()
                self._gd_update_preview()
            b = tk.Button(type_row, text=text, command=_cmd,
                          font=F_BOLD, relief="flat", bd=0,
                          padx=12, pady=5, cursor="hand2")
            b._bg  = bg
            b._val = value
            b.pack(side="left", padx=(0, 6))
            return b

        self._gd_btn_h = _type_btn("Housing",   "housing", CA)
        self._gd_btn_r = _type_btn("REP / FIL", "rep",     CNE)

        def _refresh():
            sel = self._gd_order_type.get()
            for btn in (self._gd_btn_h, self._gd_btn_r):
                if btn._val == sel:
                    btn.config(bg=btn._bg, fg="white")
                else:
                    btn.config(bg=CSP, fg=CTX)
        _refresh()

        cols = tk.Frame(frm, bg=CBG)
        cols.pack(fill="both", expand=True)

        left = tk.Frame(cols, bg=CBG)
        left.pack(side="left", fill="y", padx=(0, 14))
        tk.Label(left, text="Model", bg=CBG, fg=CMU, font=F_SM).pack(anchor="w", pady=(0, 4))

        self._gd_model = tk.StringVar(value=self._GD_MODELS[0])
        for m in self._GD_MODELS:
            tk.Radiobutton(left, text=m, variable=self._gd_model, value=m,
                           bg=CBG, fg=CTX, font=F_BODY,
                           activebackground=CRE, selectcolor=CCA,
                           command=self._gd_update_preview, cursor="hand2"
                           ).pack(anchor="w", pady=1)

        right = tk.Frame(cols, bg=CBG)
        right.pack(side="left", fill="both", expand=True)
        tk.Label(right, text="Preview", bg=CBG, fg=CMU, font=F_SM).pack(anchor="w", pady=(0, 4))

        prev = tk.Frame(right, bg=CCA, bd=1, relief="solid", padx=10, pady=8)
        prev.pack(fill="both", expand=True)

        job_row = tk.Frame(prev, bg=CCA)
        job_row.pack(fill="x", pady=(0, 6))
        tk.Label(job_row, text="Job:", bg=CCA, fg=CMU,
                 font=F_BOLD, width=6, anchor="w").pack(side="left")
        self._gd_lbl_job = tk.Label(job_row, text="", bg=CCA, fg=CA,
                                     font=F_BOLD, anchor="w")
        self._gd_lbl_job.pack(side="left")
        tk.Frame(prev, bg=CSP, height=1).pack(fill="x", pady=(0, 6))

        self._gd_txt = tk.Text(prev, height=10, width=36, bg=CCA, fg=CTX,
                                font=F_BODY, bd=0, relief="flat",
                                state="disabled", wrap="none", cursor="arrow")
        self._gd_txt.pack(fill="both", expand=True)

        self._gd_update_preview()

    def _gd_update_preview(self):
        model   = self._gd_model.get()
        is_rep  = self._gd_order_type.get() == "rep"
        pack    = DEDICATED_FILTER_PACKS[model]
        try:
            sets = max(1, int(self._gd_qty.get()))
        except Exception:
            sets = 1
        job = f"Housing {model}" if not is_rep else f"REP/FIL/{model}"
        if sets > 1:
            job = f"{job}  ×{sets}"
        self._gd_lbl_job.config(text=job)
        lines   = []
        if not is_rep:
            for f in pack.get("frames", []):
                lbl  = f.get("label", "")
                desc = f"({f['short']}x{f['long']}mm)" + (f" [{lbl}]" if lbl else "")
                lines.append(f"  [Note] {f['qty'] * sets} x Mounting Frame {desc}")
        for fl in pack.get("filters", []):
            qty = max(1, fl["qty"] // 2) if is_rep else fl["qty"]
            qty *= sets
            lbl = f"  [{fl.get('label', '')}]" if fl.get("label") else ""
            lines.append(f"  V-form  {fl['short']}x{fl['long']}x{fl['channel']}mm  G4  x{qty}{lbl}")
        self._gd_txt.config(state="normal")
        self._gd_txt.delete("1.0", "end")
        self._gd_txt.insert("end", "\n".join(lines) or "(no items)")
        self._gd_txt.config(state="disabled")

    # ── Tab 2: Sigrist ────────────────────────────────────────────────────

    def _build_sigrist_tab(self, nb):
        frm = tk.Frame(nb, bg=CBG, padx=20, pady=16)
        nb.add(frm, text="  Sigrist  ")

        tk.Label(frm, text="Sigrist Filter",
                 bg=CBG, fg=CA, font=F_SEC, anchor="w").pack(anchor="w")
        tk.Frame(frm, bg=CSP, height=1).pack(fill="x", pady=(6, 10))

        specs = [
            ("Dimensions",  "412 x 412 x 90 mm"),
            ("Filter Type", "V-form"),
            ("Media",       "F5 Rated"),
            ("Note",        "BLANK F5 Labels should be used"),
        ]
        for label, value in specs:
            row = tk.Frame(frm, bg=CBG)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=f"{label}:", bg=CBG, fg=CMU,
                     font=F_BOLD, width=14, anchor="w").pack(side="left")
            fg = CRD if label == "Note" else CTX
            tk.Label(row, text=value, bg=CBG, fg=fg,
                     font=F_BODY, anchor="w").pack(side="left")

        tk.Frame(frm, bg=CSP, height=1).pack(fill="x", pady=(14, 8))

        qty_row = tk.Frame(frm, bg=CBG)
        qty_row.pack(anchor="w", pady=(0, 8))
        tk.Label(qty_row, text="Quantity:", bg=CBG, fg=CTX,
                 font=F_BOLD).pack(side="left", padx=(0, 10))
        self._sigrist_qty = tk.StringVar(value="1")
        tk.Spinbox(qty_row, from_=1, to=50, textvariable=self._sigrist_qty,
                   width=5, font=F_BODY, relief="solid", bd=1).pack(side="left")

        tk.Label(frm,
                 text="Clicking 'Add to Order' will add the selected quantity of\n"
                      "V-form 412x412x90mm filters with F5 media.",
                 bg=CBG, fg=CMU, font=F_SM, justify="left").pack(anchor="w")

    # ── Tab 3: Stepped Filters ────────────────────────────────────────────

    def _build_stepped_tab(self, nb):
        frm = tk.Frame(nb, bg=CBG, padx=20, pady=16)
        nb.add(frm, text="  Stepped Filters  ")

        tk.Label(frm, text="Stepped Filter Presets",
                 bg=CBG, fg=CA, font=F_SEC, anchor="w").pack(anchor="w")
        tk.Frame(frm, bg=CSP, height=1).pack(fill="x", pady=(6, 12))

        self._stepped_model = tk.StringVar(value="535x535x50")
        for key, label in [("535x535x50",  "535 x 535 x 50 mm"),
                            ("535x1135x50", "535 x 1135 x 50 mm")]:
            tk.Radiobutton(frm, text=label, variable=self._stepped_model, value=key,
                           bg=CBG, fg=CTX, font=F_BODY,
                           activebackground=CRE, selectcolor=CCA, cursor="hand2"
                           ).pack(anchor="w", pady=3)

        tk.Frame(frm, bg=CSP, height=1).pack(fill="x", pady=(12, 10))

        specs = [
            ("Filter Type", "Stepped Filter (40mm V-form + 10mm flyscreen)"),
            ("Media",       "G4  +  180 Media"),
            ("Note",        "180 Media included"),
        ]
        for label, value in specs:
            row = tk.Frame(frm, bg=CBG)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=f"{label}:", bg=CBG, fg=CMU,
                     font=F_BOLD, width=14, anchor="w").pack(side="left")
            fg = CRD if label == "Note" else CTX
            tk.Label(row, text=value, bg=CBG, fg=fg,
                     font=F_BODY, anchor="w").pack(side="left")

        tk.Frame(frm, bg=CSP, height=1).pack(fill="x", pady=(14, 8))

        qty_row = tk.Frame(frm, bg=CBG)
        qty_row.pack(anchor="w", pady=(0, 8))
        tk.Label(qty_row, text="Quantity:", bg=CBG, fg=CTX,
                 font=F_BOLD).pack(side="left", padx=(0, 10))
        self._stepped_qty = tk.StringVar(value="1")
        tk.Spinbox(qty_row, from_=1, to=50, textvariable=self._stepped_qty,
                   width=5, font=F_BODY, relief="solid", bd=1).pack(side="left")

        tk.Label(frm,
                 text="Clicking 'Add to Order' will add the selected quantity of\n"
                      "Stepped Filter items with 180 Media.",
                 bg=CBG, fg=CMU, font=F_SM, justify="left").pack(anchor="w")

    # ── Confirm — build result based on active tab ────────────────────────

    def _confirm(self):
        # Determine which tab is active by checking which notebook tab is selected
        # We check the tab text to figure out which preset to use
        nb = None
        for child in self.winfo_children():
            if isinstance(child, ttk.Notebook):
                nb = child
                break
        if nb is None:
            self.destroy()
            return

        tab_idx  = nb.index(nb.select())
        tab_name = nb.tab(tab_idx, "text").strip()

        if "Comp Air" in tab_name or "GD" in tab_name:
            self._confirm_gd()
        elif "Sigrist" in tab_name:
            self._confirm_sigrist()
        elif "Stepped" in tab_name:
            self._confirm_stepped()
        else:
            self.destroy()

    def _confirm_gd(self):
        model   = self._gd_model.get()
        is_rep  = self._gd_order_type.get() == "rep"
        pack    = DEDICATED_FILTER_PACKS[model]
        items   = []
        try:
            sets = max(1, int(self._gd_qty.get()))
        except Exception:
            sets = 1
        job = f"Housing {model}" if not is_rep else f"REP/FIL/{model}"
        if sets > 1:
            job = f"{job} ×{sets}"

        # Build the mounting-frame note for this model — stored per-item
        # so it only appears on that model's own PDF page, not every page.
        frame_parts = []
        if not is_rep:
            for f in pack.get("frames", []):
                lbl  = f.get("label", "")
                total_frames = f["qty"] * sets
                desc = f"({f['short']}x{f['long']}mm)" + (f" [{lbl}]" if lbl else "")
                frame_parts.append(f"{total_frames} x Mounting Frame {desc}")
        item_notes = "\n".join(frame_parts)

        for fl in pack.get("filters", []):
            qty = max(1, fl["qty"] // 2) if is_rep else fl["qty"]
            qty *= sets
            items.append({
                "item_kind": "filter", "Quantity": qty,
                "Filter Type": fl.get("filter_type", "V-form"), "Media Type": "G4",
                "Short": fl["short"], "Long": fl["long"], "Channel": fl["channel"],
                "Pleat Insert": False, "Header": False,
                "Use Stock V-form": False, "Use Stock Flyscreen": False,
                "Notes": fl.get("label", ""),
                "item_job":   job,        # per-item: goes on this page's JOB: field
                "item_notes": item_notes, # per-item: goes on this page's NOTES: field
            })

        # notes="" so the compressor frame info does NOT go into the global
        # order header (it lives on each item's own page instead).
        self.result = {"items": items, "job": job, "notes": ""}
        self.destroy()

    def _confirm_sigrist(self):
        try:
            qty = max(1, int(self._sigrist_qty.get()))
        except Exception:
            qty = 1
        self.result = {
            "items": [{
                "item_kind": "filter", "Quantity": qty,
                "Filter Type": "V-form", "Media Type": "F5",
                "Short": 412, "Long": 412, "Channel": 90,
                "Pleat Insert": False, "Header": False,
                "Use Stock V-form": False, "Use Stock Flyscreen": False,
                "Notes": "BLANK F5 Labels To be used!",
            }],
            "job":   "",
            "notes": "BLANK F5 Labels To be used!",
        }
        self.destroy()

    def _confirm_stepped(self):
        key  = self._stepped_model.get()
        pack = STEPPED_PACKS[key]
        fl   = pack["filters"][0]
        try:
            qty = max(1, int(self._stepped_qty.get()))
        except Exception:
            qty = 1
        self.result = {
            "items": [{
                "item_kind": "filter", "Quantity": fl["qty"] * qty,
                "Filter Type": fl["filter_type"], "Media Type": fl["media"],
                "Short": fl["short"], "Long": fl["long"], "Channel": fl["channel"],
                "Pleat Insert": False, "Header": False,
                "Use Stock V-form": False, "Use Stock Flyscreen": False,
                "Notes": STEPPED_FILTER_NOTE,
            }],
            "job":   "",
            "notes": "",
        }
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════════
# Progress Dialog
# ═══════════════════════════════════════════════════════════════════════════

class _ProgressDialog(tk.Toplevel):
    """
    Modal progress window shown while the order is being generated.
    All public methods are safe to call from any thread via .after().
    """

    _STEPS = {
        "filter":  ["Validating order…",
                    "Building filter worksheets…",
                    "Exporting to PDF…",
                    "Saving order…",
                    "Done!"],
        "bags":    ["Validating order…",
                    "Building bag / roll docket…",
                    "Exporting to PDF…",
                    "Saving order…",
                    "Done!"],
        "mixed":   ["Validating order…",
                    "Building worksheets & docket in parallel…",
                    "Exporting PDFs…",
                    "Merging PDFs…",
                    "Saving order…",
                    "Done!"],
    }

    def __init__(self, parent, order_type: str = "filter"):
        super().__init__(parent)
        self.title("Generating Order")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", lambda: None)   # block manual close

        self._steps     = self._STEPS.get(order_type, self._STEPS["filter"])
        self._n_steps   = len(self._steps)
        self._step_idx  = 0

        # ── Layout ──────────────────────────────────────────────────────────
        outer = tk.Frame(self, bg=CBG, padx=28, pady=22)
        outer.pack(fill="both", expand=True)

        # Title
        tk.Label(outer, text="Generating Order…", font=F_TTL,
                 bg=CBG, fg=CA).pack(anchor="w")

        tk.Frame(outer, bg=CSP, height=1).pack(fill="x", pady=(6, 14))

        # Status label
        self._status_var = tk.StringVar(value=self._steps[0])
        tk.Label(outer, textvariable=self._status_var,
                 font=F_BODY, bg=CBG, fg=CTX,
                 wraplength=340, justify="left").pack(anchor="w", pady=(0, 10))

        # Progress bar
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TAF.Horizontal.TProgressbar",
                        troughcolor=CSP,
                        background=CA,
                        bordercolor=CBG,
                        lightcolor=CA,
                        darkcolor=CA)
        self._bar = ttk.Progressbar(
            outer, style="TAF.Horizontal.TProgressbar",
            orient="horizontal", length=360,
            mode="determinate", maximum=100)
        self._bar.pack(fill="x", pady=(0, 6))
        self._bar["value"] = 0

        # Step counter  (e.g. "Step 1 of 5")
        self._step_var = tk.StringVar(value=f"Step 1 of {self._n_steps}")
        tk.Label(outer, textvariable=self._step_var,
                 font=F_SM, bg=CBG, fg=CMU).pack(anchor="e")

        # Size + centre over parent
        self.update_idletasks()
        W, H = 420, 175
        px = parent.winfo_rootx() + parent.winfo_width()  // 2 - W // 2
        py = parent.winfo_rooty() + parent.winfo_height() // 2 - H // 2
        self.geometry(f"{W}x{H}+{px}+{py}")
        self.lift()

    # ── Thread-safe helpers ─────────────────────────────────────────────────

    def advance(self, msg: str = ""):
        """Move to the next step. Safe to call from a worker thread."""
        self.after(0, self._do_advance, msg)

    def _do_advance(self, msg: str):
        self._step_idx = min(self._step_idx + 1, self._n_steps - 1)
        label = msg or self._steps[self._step_idx]
        self._status_var.set(label)
        pct = int(self._step_idx / max(self._n_steps - 1, 1) * 100)
        self._bar["value"] = pct
        self._step_var.set(f"Step {self._step_idx + 1} of {self._n_steps}")
        self.update_idletasks()

    def set_status(self, msg: str):
        """Update just the label without advancing step count."""
        self.after(0, lambda: self._status_var.set(msg))

    def close(self):
        """Destroy this dialog from the main thread."""
        self.after(0, self._do_close)

    def _do_close(self):
        try:
            self.grab_release()
            self.destroy()
        except Exception:
            pass

    @staticmethod
    def _merge(pdf_paths: list, out_path: str) -> bool:
        """Merge PDF files into one. Returns True on success."""
        try:
            from pypdf import PdfWriter, PdfReader
            writer = PdfWriter()
            for p in pdf_paths:
                if p and str(p).lower().endswith(".pdf") and os.path.exists(p):
                    for page in PdfReader(str(p)).pages:
                        writer.add_page(page)
            with open(out_path, "wb") as fh:
                writer.write(fh)
            return True
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════════════════════
# Line Item Dialog
# ═══════════════════════════════════════════════════════════════════════════

class LineItemDialog(tk.Toplevel):
    """Modal dialog for adding or editing a single line item."""

    def __init__(self, master, title="Line Item", initial=None, media_types=None):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.lift()
        self.focus_force()
        self.configure(bg=CBG)
        self.result = None
        initial = initial or {}
        _media_types = media_types if media_types is not None else DEFAULT_MEDIA_TYPES

        # ── Header strip (top) ────────────────────────────────────────────
        hdr = tk.Frame(self, bg=CA, padx=20, pady=14)
        hdr.pack(fill="x", side="top")
        tk.Label(hdr, text=title, bg=CA, fg="white",
                 font=(FAM, 12, "bold")).pack(anchor="w")
        tk.Label(hdr, text="Enter the panel size — the filter & media type are set "
                           "automatically from the channel thickness.",
                 bg=CA, fg="white", font=F_SM).pack(anchor="w", pady=(2, 0))

        # ── Footer buttons — packed BEFORE body so they always get space ──
        foot = tk.Frame(self, bg=CCA, padx=20, pady=12,
                        highlightbackground=CSP, highlightthickness=1)
        foot.pack(fill="x", side="bottom")
        flat_btn(foot, "Cancel",    self._cancel, bg=CNE, pady=8).pack(side="right", padx=(10, 0))
        flat_btn(foot, "Save Item", self._save,   bg=CGR, pady=8).pack(side="right")

        # ── Body (fills remaining space between header and footer) ────────
        body = tk.Frame(self, bg=CBG, padx=20, pady=16)
        body.pack(fill="both", expand=True, side="top")

        # ── Dimensions ────────────────────────────────────────────────────
        dim_f = tk.LabelFrame(body, text=" Dimensions (mm) ",
                               bg=CCA, fg=CA, font=F_SEC,
                               bd=1, relief="solid", padx=16, pady=14)
        dim_f.pack(fill="x", pady=(0, 12))

        self.vars = {}
        for col, key in enumerate(["Quantity", "Short", "Long", "Channel"]):
            dim_f.grid_columnconfigure(col, weight=1, uniform="dim")
            sub = tk.Frame(dim_f, bg=CCA)
            sub.grid(row=0, column=col, padx=(0, 14), sticky="ew")
            tk.Label(sub, text=key.upper(), bg=CCA, fg=CMU,
                     font=F_BOLD).pack(anchor="w")
            v = tk.StringVar(value=str(initial.get(key, "")))
            self.vars[key] = v
            e = field_entry(sub, textvariable=v, width=10)
            e.pack(fill="x", pady=(3, 0))
            if col == 0:
                e.focus_set()

        # Auto-classification hint under the dimensions
        self._auto_hint = tk.Label(
            dim_f,
            text="Channel 9–11 → Flyscreen (Grey)   ·   12–29 → Flat Panel   "
                 "·   30+ → V-form / Pleated",
            bg=CCA, fg=CMU, font=F_SM, anchor="w")
        self._auto_hint.grid(row=1, column=0, columnspan=4, sticky="w", pady=(10, 0))

        # ── Classification ────────────────────────────────────────────────
        cls_f = tk.LabelFrame(body, text=" Classification ",
                               bg=CCA, fg=CA, font=F_SEC,
                               bd=1, relief="solid", padx=16, pady=14)
        cls_f.pack(fill="x", pady=(0, 12))

        for col, (key, vals) in enumerate([
            ("Filter Type", VALID_FILTER_TYPES),
            ("Media Type",  _media_types),
        ]):
            cls_f.grid_columnconfigure(col, weight=1, uniform="cls")
            sub = tk.Frame(cls_f, bg=CCA)
            sub.grid(row=0, column=col, padx=(0, 20), sticky="ew")
            tk.Label(sub, text=key.upper(), bg=CCA, fg=CMU, font=F_BOLD).pack(anchor="w")
            v = tk.StringVar(value=str(initial.get(key, "")))
            self.vars[key] = v
            # Use tk.OptionMenu instead of ttk.Combobox — always renders cleanly
            v.set(v.get() or vals[0])
            om = tk.OptionMenu(sub, v, *vals)
            om.config(relief="solid", bd=1, bg=CBG, fg=CTX,
                      font=F_BODY, anchor="w",
                      activebackground=CRE, activeforeground=CTX,
                      highlightthickness=0, cursor="hand2", padx=8, pady=4)
            om["menu"].config(bg=CCA, fg=CTX, font=F_BODY,
                              activebackground=CA, activeforeground="white")
            om.pack(fill="x", pady=(3, 0))

        # Auto-set Filter/Media Type from the channel thickness as the user
        # types. Attached AFTER the initial values are set so editing an
        # existing item does not clobber its saved classification on open.
        self.vars["Channel"].trace_add("write", self._on_channel_change)

        # ── Options ───────────────────────────────────────────────────────
        opt_f = tk.LabelFrame(body, text=" Options ",
                               bg=CCA, fg=CA, font=F_SEC,
                               bd=1, relief="solid", padx=16, pady=14)
        opt_f.pack(fill="x", pady=(0, 12))

        self.var_pleat    = tk.BooleanVar(value=bool(initial.get("Pleat Insert", False)))
        self.var_header   = tk.BooleanVar(value=bool(initial.get("Header", False)))
        self.var_stock_v  = tk.BooleanVar(value=bool(initial.get("Use Stock V-form", False)))
        self.var_stock_fs = tk.BooleanVar(value=bool(initial.get("Use Stock Flyscreen", False)))

        flags = [
            ("Pleat Insert",        self.var_pleat,    0, 0),
            ("Header Only",         self.var_header,   0, 1),
            ("Use Stock V-form",    self.var_stock_v,  1, 0),
            ("Use Stock Flyscreen", self.var_stock_fs, 1, 1),
        ]
        for lbl_text, var, row, col in flags:
            tk.Checkbutton(opt_f, text=lbl_text, variable=var,
                           bg=CCA, fg=CTX, font=F_BODY,
                           activebackground=CCA, selectcolor=CBG,
                           cursor="hand2").grid(row=row, column=col,
                                                sticky="w", padx=(0, 24),
                                                pady=(0 if row == 0 else 6, 0))

        # ── Page Overrides ────────────────────────────────────────────────
        ov_f = tk.LabelFrame(body, text=" Page Overrides (optional) ",
                              bg=CCA, fg=CA, font=F_SEC,
                              bd=1, relief="solid", padx=16, pady=14)
        ov_f.pack(fill="x", pady=(0, 4))

        tk.Label(ov_f,
                 text="These appear on this item's PDF page only, below the global order notes.",
                 bg=CCA, fg=CMU, font=F_SM).pack(anchor="w", pady=(0, 8))

        job_row = tk.Frame(ov_f, bg=CCA)
        job_row.pack(fill="x", pady=(0, 8))
        tk.Label(job_row, text="Job:", bg=CCA, fg=CTX,
                 font=F_BOLD, width=8, anchor="w").pack(side="left")
        self.var_item_job = tk.StringVar(value=str(initial.get("item_job", "") or ""))
        field_entry(job_row, textvariable=self.var_item_job, width=36).pack(side="left", fill="x", expand=True)

        tk.Label(ov_f, text="Page Notes:", bg=CCA, fg=CTX,
                 font=F_BOLD).pack(anchor="w")
        self.txt_notes = tk.Text(ov_f, width=60, height=3, wrap="word",
                                  font=F_BODY, relief="solid", bd=1,
                                  bg=CBG, fg=CTX, insertbackground=CTX)
        self.txt_notes.pack(fill="x", pady=(3, 0))
        self.txt_notes.insert("1.0", initial.get("Notes", "") or "")

        self.bind("<Escape>", lambda e: self._cancel())

    # ─────────────────────────────────────────────────────────────────────

    def _on_channel_change(self, *_):
        """Auto-set Filter Type — and media — from the channel thickness.

        9–11 mm forces Grey media (flyscreen). If the channel is later changed
        out of that range, the auto-Grey is undone back to the default G4 so a
        mistaken 9 mm entry doesn't leave Grey stuck on a Flat Panel / V-form.
        A media type the user picked themselves (anything but Grey) is kept.
        """
        ft, mt = classify_by_channel(self.vars["Channel"].get())
        if ft:
            self.vars["Filter Type"].set(ft)
        if mt:
            self.vars["Media Type"].set(mt)
        elif ft and self.vars["Media Type"].get().strip().upper() == "GREY":
            self.vars["Media Type"].set("G4")

    def _cancel(self):
        self.result = None
        self.destroy()

    def _save(self):
        try:
            qty     = int(self.vars["Quantity"].get().strip())
            short   = int(self.vars["Short"].get().strip())
            long_   = int(self.vars["Long"].get().strip())
            channel = int(self.vars["Channel"].get().strip())
        except Exception:
            messagebox.showerror(
                "Invalid Input",
                "Quantity / Short / Long / Channel must be whole numbers.",
                parent=self)
            return

        ft = self.vars["Filter Type"].get().strip()
        mt = self.vars["Media Type"].get().strip()

        if ft not in VALID_FILTER_TYPES:
            messagebox.showerror("Invalid Input",
                                 "Please select a valid Filter Type.", parent=self)
            return
        if mt not in VALID_MEDIA_TYPES:
            messagebox.showerror("Invalid Input",
                                 "Please select a valid Media Type.", parent=self)
            return

        self.result = {
            "Quantity":            qty,
            "Short":               short,
            "Long":                long_,
            "Channel":             channel,
            "Filter Type":         ft,
            "Media Type":          mt,
            "Pleat Insert":        bool(self.var_pleat.get()),
            "Header":              bool(self.var_header.get()),
            "Use Stock V-form":    bool(self.var_stock_v.get()),
            "Use Stock Flyscreen": bool(self.var_stock_fs.get()),
            "Notes":               self.txt_notes.get("1.0", "end").strip(),
            "item_job":            self.var_item_job.get().strip(),
        }
        # Stepped filters always carry the *STEPPED FILTER* customer note.
        apply_stepped_filter_note(self.result)
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════════
# Bag / Roll Line Item Dialog
# ═══════════════════════════════════════════════════════════════════════════

# Product type groups
_BAG_TYPES   = {"3-Peak", "2-Wedge", "4-Point", "MPHE 8-Pocket", "MPHE 4-Pocket", "HEPA"}
_FRAME_TYPES = {"Mounting Frame"}
_ROLL_TYPES  = {"Media Roll"}
_PAD_TYPES   = {"Cut Pads", "Other"}


class BagLineItemDialog(tk.Toplevel):
    """
    Modal dialog for adding / editing a single bag-filter or media-roll line item.
    Dynamically shows/hides sections depending on product type.
    P/N is auto-generated as dimensions/options change but remains editable.
    """

    def __init__(self, master, title="Bag / Roll Item", initial=None, media_types=None):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.lift()
        self.focus_force()
        self.configure(bg=CBG)
        self.result = None
        self._pn_override = False   # True once user manually edits P/N
        # Full media-type list from Settings (used for Media Roll & Cut Pads)
        self._all_media = list(media_types) if media_types else list(BAG_MEDIA_TYPES)
        d = initial or {}

        # ── Header ────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=CA, padx=16, pady=10)
        hdr.pack(fill="x", side="top")
        tk.Label(hdr, text=title, bg=CA, fg="white",
                 font=(FAM, 11, "bold")).pack(anchor="w")

        # ── Footer — packed BEFORE body ────────────────────────────────────
        foot = tk.Frame(self, bg=CBG, padx=16, pady=10)
        foot.pack(fill="x", side="bottom")
        flat_btn(foot, "Cancel",    self._cancel, bg=CNE, pady=7).pack(side="right", padx=(8, 0))
        flat_btn(foot, "Save Item", self._save,   bg=CGR, pady=7).pack(side="right")

        # ── Scrollable body ────────────────────────────────────────────────
        body_wrap = tk.Frame(self, bg=CBG)
        body_wrap.pack(fill="both", expand=True, side="top")
        canvas = tk.Canvas(body_wrap, bg=CBG, highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(body_wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        body = tk.Frame(canvas, bg=CBG, padx=16, pady=10)
        body_win = canvas.create_window((0, 0), window=body, anchor="nw")

        def _on_frame_config(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_resize(e):
            canvas.itemconfig(body_win, width=e.width)
        body.bind("<Configure>", _on_frame_config)
        canvas.bind("<Configure>", _on_canvas_resize)
        self.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-1*(e.delta//120), "units"))

        # ── Product type + Quantity row ────────────────────────────────────
        top_row = tk.Frame(body, bg=CBG)
        top_row.pack(fill="x", pady=(0, 8))

        # Product Type
        pt_col = tk.Frame(top_row, bg=CBG)
        pt_col.pack(side="left", padx=(0, 28))
        tk.Label(pt_col, text="Product Type", bg=CBG, fg=CTX, font=F_BODY).pack(anchor="w")
        self.var_pt = tk.StringVar(value=d.get("product_type", BAG_PRODUCT_TYPES[0]))
        om_pt = tk.OptionMenu(pt_col, self.var_pt, *BAG_PRODUCT_TYPES,
                              command=lambda _: self._on_type_change())
        om_pt.config(relief="solid", bd=1, bg=CCA, fg=CTX, font=F_BODY,
                     width=16, anchor="w", activebackground=CRE,
                     activeforeground=CTX, highlightthickness=0, cursor="hand2")
        om_pt["menu"].config(bg=CCA, fg=CTX, font=F_BODY,
                             activebackground=CA, activeforeground="white")
        om_pt.pack()

        # Quantity
        qty_col = tk.Frame(top_row, bg=CBG)
        qty_col.pack(side="left", padx=(0, 28))
        tk.Label(qty_col, text="Quantity", bg=CBG, fg=CTX, font=F_BODY).pack(anchor="w")
        self.var_qty = tk.StringVar(value=str(d.get("quantity", "")))
        field_entry(qty_col, textvariable=self.var_qty, width=8).pack()

        # ── Size preset row ────────────────────────────────────────────────
        self.preset_frame = tk.LabelFrame(body, text=" Standard Sizes ",
                                          bg=CBG, fg=CA, font=F_BOLD,
                                          bd=1, relief="groove", padx=12, pady=8)
        self.preset_frame.pack(fill="x", pady=(0, 8))

        tk.Label(self.preset_frame, text="Preset:", bg=CBG, fg=CTX,
                 font=F_BODY).pack(side="left", padx=(0, 8))
        self.var_preset = tk.StringVar(value="Custom")
        self.om_preset  = tk.OptionMenu(self.preset_frame, self.var_preset, "Custom",
                                        command=lambda _: self._on_preset_change())
        self.om_preset.config(relief="solid", bd=1, bg=CCA, fg=CTX, font=F_BODY,
                              width=28, anchor="w", activebackground=CRE,
                              activeforeground=CTX, highlightthickness=0, cursor="hand2")
        self.om_preset["menu"].config(bg=CCA, fg=CTX, font=F_BODY,
                                       activebackground=CA, activeforeground="white")
        self.om_preset.pack(side="left")

        # ── Dimensions (W × H × D) ─────────────────────────────────────────
        self.dims_frame = tk.LabelFrame(body, text=" Dimensions (mm) ",
                                        bg=CBG, fg=CA, font=F_BOLD,
                                        bd=1, relief="groove", padx=12, pady=10)
        self.dims_frame.pack(fill="x", pady=(0, 8))

        self.var_w = tk.StringVar(value=str(d.get("width",  "") or ""))
        self.var_h = tk.StringVar(value=str(d.get("height", "") or ""))
        self.var_d = tk.StringVar(value=str(d.get("depth",  "") or ""))

        self._dim_labels = {}
        for col, (lbl, var) in enumerate([("Width", self.var_w),
                                           ("Height", self.var_h),
                                           ("Depth", self.var_d)]):
            sub = tk.Frame(self.dims_frame, bg=CBG)
            sub.grid(row=0, column=col, padx=(0, 20), sticky="w")
            l = tk.Label(sub, text=lbl, bg=CBG, fg=CTX, font=F_BODY)
            l.pack(anchor="w")
            self._dim_labels[lbl] = l
            e = field_entry(sub, textvariable=var, width=9)
            e.pack()
            var.trace_add("write", lambda *_: self._auto_pn())

        # ── Roll dimensions (Media Roll only) ─────────────────────────────
        self.roll_frame = tk.LabelFrame(body, text=" Roll Dimensions ",
                                        bg=CBG, fg=CA, font=F_BOLD,
                                        bd=1, relief="groove", padx=12, pady=10)

        rw_col = tk.Frame(self.roll_frame, bg=CBG)
        rw_col.grid(row=0, column=0, padx=(0, 20))
        tk.Label(rw_col, text="Width", bg=CBG, fg=CTX, font=F_BODY).pack(anchor="w")
        self.var_rw = tk.StringVar(value=d.get("roll_width", ROLL_WIDTHS[2]))
        cb_rw = ttk.Combobox(rw_col, textvariable=self.var_rw,
                             values=ROLL_WIDTHS, width=12, font=F_BODY)
        cb_rw.bind("<<ComboboxSelected>>", lambda _: self._auto_pn())
        cb_rw.bind("<KeyRelease>",         lambda _: self._auto_pn())
        cb_rw.pack()
        tk.Label(rw_col, text="preset or custom", bg=CBG, fg=CMU,
                 font=F_SM).pack(anchor="w")

        rl_col = tk.Frame(self.roll_frame, bg=CBG)
        rl_col.grid(row=0, column=1, padx=(0, 20))
        tk.Label(rl_col, text="Length", bg=CBG, fg=CTX, font=F_BODY).pack(anchor="w")
        self.var_rl = tk.StringVar(value=d.get("roll_length", ROLL_LENGTHS[1]))
        cb_rl = ttk.Combobox(rl_col, textvariable=self.var_rl,
                             values=ROLL_LENGTHS, width=12, font=F_BODY)
        cb_rl.bind("<<ComboboxSelected>>", lambda _: self._auto_pn())
        cb_rl.bind("<KeyRelease>",         lambda _: self._auto_pn())
        cb_rl.pack()
        tk.Label(rl_col, text="preset or custom", bg=CBG, fg=CMU,
                 font=F_SM).pack(anchor="w")

        # ── Media type ─────────────────────────────────────────────────────
        self.media_frame = tk.LabelFrame(body, text=" Media ",
                                         bg=CBG, fg=CA, font=F_BOLD,
                                         bd=1, relief="groove", padx=12, pady=10)

        m_col = tk.Frame(self.media_frame, bg=CBG)
        m_col.grid(row=0, column=0, padx=(0, 28))
        tk.Label(m_col, text="Media Type", bg=CBG, fg=CTX, font=F_BODY).pack(anchor="w")
        self.var_media = tk.StringVar(value=d.get("media", BAG_MEDIA_TYPES[0]))
        self.om_media  = tk.OptionMenu(m_col, self.var_media, *BAG_MEDIA_TYPES,
                                       command=lambda _: self._auto_pn())
        self.om_media.config(relief="solid", bd=1, bg=CCA, fg=CTX, font=F_BODY,
                             width=10, anchor="w", activebackground=CRE,
                             highlightthickness=0, cursor="hand2")
        self.om_media["menu"].config(bg=CCA, fg=CTX, font=F_BODY,
                                      activebackground=CA, activeforeground="white")
        self.om_media.pack()

        self.media_frame.pack(fill="x", pady=(0, 8))

        # ── Bag options ────────────────────────────────────────────────────
        self.opts_frame = tk.LabelFrame(body, text=" Options ",
                                        bg=CBG, fg=CA, font=F_BOLD,
                                        bd=1, relief="groove", padx=12, pady=8)

        self.var_wire    = tk.BooleanVar(value=bool(d.get("on_wire")))
        self.var_gelled  = tk.BooleanVar(value=bool(d.get("gelled")))
        self.var_special = tk.BooleanVar(value=bool(d.get("special_size")))

        chk_defs = [
            ("On Wire",      self.var_wire,    0, 0),
            ("Gelled",       self.var_gelled,  0, 1),
            ("Special Size", self.var_special, 0, 2),
        ]
        for lbl_t, var, row, col in chk_defs:
            tk.Checkbutton(self.opts_frame, text=lbl_t, variable=var,
                           bg=CBG, fg=CTX, font=F_BODY,
                           activebackground=CBG, selectcolor=CCA, cursor="hand2",
                           command=self._auto_pn
                           ).grid(row=row, column=col, sticky="w", padx=(0, 24), pady=(0, 4))

        # Label suffix  (Long / Short / empty)
        ls_col = tk.Frame(self.opts_frame, bg=CBG)
        ls_col.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        tk.Label(ls_col, text="Label suffix:", bg=CBG, fg=CTX, font=F_BODY).pack(side="left", padx=(0, 8))
        self.var_lsuffix = tk.StringVar(value=d.get("label_suffix", ""))
        for txt in ("", "LONG", "SHORT"):
            tk.Radiobutton(ls_col, text=(txt if txt else "None"), variable=self.var_lsuffix,
                           value=txt, bg=CBG, fg=CTX, font=F_BODY,
                           activebackground=CBG, selectcolor=CCA, cursor="hand2"
                           ).pack(side="left", padx=(0, 12))

        self.opts_frame.pack(fill="x", pady=(0, 8))

        # ── Description (Cut Pads / Other) ─────────────────────────────────
        self.desc_frame = tk.LabelFrame(body, text=" Description ",
                                        bg=CBG, fg=CA, font=F_BOLD,
                                        bd=1, relief="groove", padx=12, pady=8)
        tk.Label(self.desc_frame, text="Product description:",
                 bg=CBG, fg=CTX, font=F_BODY).pack(anchor="w")
        self.var_desc = tk.StringVar(value=d.get("description", ""))
        field_entry(self.desc_frame, textvariable=self.var_desc, width=44).pack(fill="x")

        # ── Part number ────────────────────────────────────────────────────
        pn_frame = tk.LabelFrame(body, text=" Part Number (auto-generated) ",
                                 bg=CBG, fg=CA, font=F_BOLD,
                                 bd=1, relief="groove", padx=12, pady=8)
        pn_frame.pack(fill="x", pady=(0, 8))

        pn_row = tk.Frame(pn_frame, bg=CBG)
        pn_row.pack(fill="x")
        self.var_pn = tk.StringVar(value=d.get("part_number", ""))
        self.ent_pn = field_entry(pn_row, textvariable=self.var_pn, width=36)
        self.ent_pn.pack(side="left", padx=(0, 8))
        flat_btn(pn_row, "↺ Regenerate", self._regen_pn,
                 bg=CNE, pady=4, padx=8, font=F_SM).pack(side="left")
        tk.Label(pn_frame, text="Edit the field above to override, or click ↺ to regenerate.",
                 bg=CBG, fg=CMU, font=F_SM).pack(anchor="w", pady=(4, 0))
        # mark as overridden when user edits manually
        self.var_pn.trace_add("write", lambda *_: self._mark_pn_override())
        self._pn_updating = False   # guard to suppress trace during auto-update

        # ── Notes ──────────────────────────────────────────────────────────
        nt_f = tk.LabelFrame(body, text=" Notes (optional) ",
                              bg=CBG, fg=CA, font=F_BOLD,
                              bd=1, relief="groove", padx=12, pady=8)
        nt_f.pack(fill="x", pady=(0, 4))
        self.txt_notes = tk.Text(nt_f, width=60, height=3, wrap="word",
                                  font=F_BODY, relief="solid", bd=1,
                                  bg=CCA, fg=CTX, insertbackground=CTX)
        self.txt_notes.pack(fill="x")
        self.txt_notes.insert("1.0", d.get("notes", "") or "")

        self.bind("<Escape>", lambda e: self._cancel())

        # ── Initialise dynamic state ───────────────────────────────────────
        self._on_type_change(restore=d)
        # If editing, set preset to "Custom" (dimensions already filled)

    # ── Dynamic visibility helpers ─────────────────────────────────────────

    def _on_type_change(self, restore: dict = None):
        pt = self.var_pt.get()

        # Rebuild preset menu for this product type
        presets = STANDARD_SIZES.get(pt, [])
        menu = self.om_preset["menu"]
        menu.delete(0, "end")
        for label, *_ in presets:
            menu.add_command(label=label,
                             command=lambda l=label: (self.var_preset.set(l),
                                                      self._on_preset_change()))
        if presets:
            # Default to first preset unless restoring an existing item
            first_label = presets[0][0]
            self.var_preset.set(first_label)
            if restore:
                self.var_preset.set("Custom")
            else:
                self._on_preset_change()
        else:
            self.var_preset.set("Custom")

        # Update media options based on product type
        if pt in ("MPHE 8-Pocket", "MPHE 4-Pocket"):
            # MPHE is media-grade specific
            media_list = ["F6", "F7", "F8"]
            default    = "F7"
        elif pt in _ROLL_TYPES | _PAD_TYPES:
            # Media Rolls and Cut Pads use the full Settings media list
            media_list = self._all_media
            default    = media_list[0] if media_list else "G4"
        else:
            # All other bag types use the standard bag media list
            media_list = BAG_MEDIA_TYPES
            default    = "G4"

        menu_m = self.om_media["menu"]
        menu_m.delete(0, "end")
        for m in media_list:
            menu_m.add_command(label=m, command=lambda v=m: (
                self.var_media.set(v), self._auto_pn()))
        if self.var_media.get() not in media_list:
            self.var_media.set(default)

        # Show/hide sections
        is_bag   = pt in _BAG_TYPES
        is_frame = pt in _FRAME_TYPES
        is_roll  = pt in _ROLL_TYPES
        is_misc  = pt in _PAD_TYPES

        # Preset row — only for bags and frames
        if is_bag or is_frame:
            self.preset_frame.pack(fill="x", pady=(0, 8))
        else:
            self.preset_frame.pack_forget()

        # Dims row
        if is_bag or is_frame:
            self.dims_frame.pack(fill="x", pady=(0, 8))
            # Show or hide depth column depending on type
            if is_frame:
                self._hide_depth()
            else:
                d_sub = self._dim_labels["Depth"].master
                d_sub.grid(row=0, column=2, padx=(0, 20), sticky="w")
        elif is_misc:
            self.dims_frame.pack(fill="x", pady=(0, 8))
        else:
            self.dims_frame.pack_forget()

        # Roll dims
        if is_roll:
            self.roll_frame.pack(fill="x", pady=(0, 8))
        else:
            self.roll_frame.pack_forget()

        # Media frame
        if is_bag or is_roll:
            self.media_frame.pack(fill="x", pady=(0, 8))
        else:
            self.media_frame.pack_forget()

        # Bag options
        if is_bag or is_frame:
            self.opts_frame.pack(fill="x", pady=(0, 8))
        else:
            self.opts_frame.pack_forget()

        # Description (misc only)
        if is_misc:
            self.desc_frame.pack(fill="x", pady=(0, 8))
        else:
            self.desc_frame.pack_forget()

        self._pn_override = False
        self._auto_pn()

    def _hide_depth(self):
        """Hide the depth field for Mounting Frame."""
        d_sub = self._dim_labels["Depth"].master
        d_sub.grid_remove()

    def _on_preset_change(self):
        pt      = self.var_pt.get()
        label   = self.var_preset.get()
        presets = STANDARD_SIZES.get(pt, [])
        for entry in presets:
            if entry[0] == label:
                _, w, h, d = entry
                if w is not None:
                    self.var_w.set(str(w))
                    self.var_h.set(str(h))
                    self.var_d.set(str(d) if d is not None else "")
                self._pn_override = False
                self._auto_pn()
                return

    def _build_item_dict(self) -> dict:
        """Assemble a raw dict from current dialog values (no validation)."""
        return {
            "product_type": self.var_pt.get(),
            "media":        self.var_media.get(),
            "on_wire":      bool(self.var_wire.get()),
            "gelled":       bool(self.var_gelled.get()),
            "special_size": bool(self.var_special.get()),
            "label_suffix": self.var_lsuffix.get(),
            "roll_width":   self.var_rw.get(),
            "roll_length":  self.var_rl.get(),
            "width":  _safe_int(self.var_w.get()),
            "height": _safe_int(self.var_h.get()),
            "depth":  _safe_int(self.var_d.get()),
        }

    def _auto_pn(self):
        """Regenerate P/N from current values unless user has overridden it."""
        if self._pn_override:
            return
        self._pn_updating = True
        try:
            item = self._build_item_dict()
            pn   = generate_part_number(item)
            self.var_pn.set(pn)
        finally:
            self._pn_updating = False

    def _regen_pn(self):
        self._pn_override = False
        self._auto_pn()

    def _mark_pn_override(self):
        if not self._pn_updating:
            self._pn_override = True

    # ── Save / Cancel ──────────────────────────────────────────────────────

    def _cancel(self):
        self.result = None
        self.destroy()

    def _save(self):
        pt = self.var_pt.get()
        try:
            qty = int(self.var_qty.get().strip())
            if qty < 1:
                raise ValueError
        except Exception:
            messagebox.showerror("Invalid", "Quantity must be a whole number ≥ 1.",
                                 parent=self)
            return

        item = self._build_item_dict()
        item["quantity"]    = qty
        item["part_number"] = self.var_pn.get().strip()
        item["description"] = self.var_desc.get().strip()
        item["notes"]       = self.txt_notes.get("1.0", "end").strip()

        # Basic validation for bags
        if pt in _BAG_TYPES:
            if not (item["width"] and item["height"]):
                messagebox.showerror("Invalid", "Width and Height are required.", parent=self)
                return
            if pt not in ("HEPA", "Mounting Frame") and not item["depth"]:
                messagebox.showerror("Invalid", "Depth is required.", parent=self)
                return

        self.result = item
        self.destroy()


def _safe_int(s) -> int:
    try:
        return int(str(s).strip())
    except Exception:
        return 0


# ═══════════════════════════════════════════════════════════════════════════
# Main Application
# ═══════════════════════════════════════════════════════════════════════════

class ModernOrderApp(tk.Frame):

    def __init__(self, master):
        super().__init__(master, bg=CBG)
        self.master = master
        self.service = OrderService()
        self.items: list = []
        self._all_orders_data: list = []
        self._tab_frames: dict = {}
        self._tab_buttons: dict = {}
        self._tab_loaded: dict = {}   # tab -> monotonic time of last data load (freshness cache)

        # Load persisted settings
        self._settings = _load_settings()
        self._custom_media: list = list(self._settings.get("custom_media_types", []))

        self._draft_save_id        = None   # debounce handle for auto-save
        self._tooltip_win          = None   # hover tooltip window ref
        self._selected_customer_id = ""    # customer_id of currently-picked customer
        self._customer_records: list = []  # full customer dicts for autocomplete
        self._inactive_banner      = None  # inactive-customer banner widget

        _configure_ttk_style()
        self._build_ui()
        self._refresh_items_tree()

        # Offer to restore any unsaved draft (after UI is fully built)
        self.master.after(600, self._check_restore_draft)

        # Clean up any leftover _old.exe from a previous auto-update
        try:
            from taf_order_app.updater import cleanup_old_exe
            cleanup_old_exe()
        except Exception:
            pass

        threading.Thread(target=_prewarm_com, daemon=True).start()
        threading.Thread(target=self._bg_check_update, daemon=True).start()

    def _bg_check_update(self):
        """Background update check — runs once after login."""
        import queue as _q
        q = _q.Queue()
        try:
            from taf_order_app.updater import check_for_update
            info = check_for_update()
            q.put(info)
        except Exception:
            q.put(None)

        def _handle():
            try:
                info = q.get_nowait()
                if info:
                    self._show_update_banner(info)
            except Exception:
                pass
        self.master.after(500, _handle)

    def _show_update_banner(self, info: dict):
        """Show a prominent update notification popup over the app."""
        # Avoid showing multiple banners
        if getattr(self, "_update_banner_shown", False):
            return
        self._update_banner_shown = True

        v     = info.get("version", "")
        notes = info.get("release_notes", "")

        # ── Outer overlay strip ───────────────────────────────────────────
        banner = tk.Frame(self, bg="#145A32", padx=0, pady=0)
        banner.place(relx=0, rely=0, relwidth=1, anchor="nw")

        inner = tk.Frame(banner, bg="#145A32", padx=18, pady=10)
        inner.pack(fill="x")

        # Left: icon + text
        left = tk.Frame(inner, bg="#145A32")
        left.pack(side="left", fill="y")

        tk.Label(left, text="UPDATE AVAILABLE",
                 bg="#145A32", fg="#A9DFBF",
                 font=(FAM, 7, "bold"), anchor="w").pack(anchor="w")

        tk.Label(left, text=f"Version {v} is ready to install",
                 bg="#145A32", fg="white",
                 font=(FAM, 11, "bold"), anchor="w").pack(anchor="w")

        # Show first line of notes inline; "Read More" if there's more
        note_lines = [l.strip() for l in notes.splitlines() if l.strip()] if notes else []
        if note_lines:
            preview = note_lines[0]
            if len(preview) > 80:
                preview = preview[:77] + "…"
            note_row = tk.Frame(left, bg="#145A32")
            note_row.pack(anchor="w")
            tk.Label(note_row, text=preview,
                     bg="#145A32", fg="#A9DFBF",
                     font=(FAM, 9), anchor="w").pack(side="left")
            if len(note_lines) > 1 or len(notes.strip()) > 80:
                def _show_notes():
                    popup = tk.Toplevel(self)
                    popup.title(f"What's new in v{v}")
                    popup.configure(bg="#1B2631")
                    popup.resizable(False, False)
                    popup.grab_set()
                    pw, ph = 520, 360
                    sx = self.winfo_rootx() + (self.winfo_width()  - pw) // 2
                    sy = self.winfo_rooty() + (self.winfo_height() - ph) // 2
                    popup.geometry(f"{pw}x{ph}+{sx}+{sy}")
                    tk.Label(popup, text=f"What's new in v{v}",
                             bg="#1B2631", fg="white",
                             font=(FAM, 13, "bold")).pack(anchor="w", padx=20, pady=(16, 6))
                    txt_frame = tk.Frame(popup, bg="#1B2631")
                    txt_frame.pack(fill="both", expand=True, padx=20, pady=(0, 10))
                    txt = tk.Text(txt_frame, bg="#212F3D", fg="#D5DBDB",
                                  font=(FAM, 10), relief="flat",
                                  wrap="word", padx=12, pady=10,
                                  state="normal", cursor="arrow",
                                  highlightthickness=0)
                    txt.insert("1.0", notes)
                    txt.config(state="disabled")
                    vsb = ttk.Scrollbar(txt_frame, command=txt.yview)
                    txt.configure(yscrollcommand=vsb.set)
                    vsb.pack(side="right", fill="y")
                    txt.pack(side="left", fill="both", expand=True)
                    tk.Button(popup, text="Close", command=popup.destroy,
                              bg="#27AE60", fg="white",
                              activebackground="#1E8449", activeforeground="white",
                              relief="flat", bd=0,
                              font=(FAM, 10, "bold"),
                              padx=20, pady=8, cursor="hand2").pack(pady=(0, 16))
                tk.Button(note_row, text="Read more ›",
                          command=_show_notes,
                          bg="#145A32", fg="#A9DFBF",
                          activebackground="#0E3D22", activeforeground="white",
                          relief="flat", bd=0,
                          font=(FAM, 9, "underline"),
                          padx=6, cursor="hand2").pack(side="left")

        # Right: buttons
        right = tk.Frame(inner, bg="#145A32")
        right.pack(side="right", fill="y")

        def _update_now():
            banner.destroy()
            self._update_banner_shown = False
            self._do_update(info)

        def _dismiss():
            banner.destroy()
            self._update_banner_shown = False

        tk.Button(right, text="UPDATE NOW",
                  command=_update_now,
                  bg="#27AE60", fg="white",
                  activebackground="#1E8449", activeforeground="white",
                  relief="flat", bd=0,
                  font=(FAM, 10, "bold"),
                  padx=20, pady=8, cursor="hand2").pack(side="left", padx=(0, 10))

        tk.Button(right, text="Later",
                  command=_dismiss,
                  bg="#145A32", fg="#A9DFBF",
                  activebackground="#0E3D22", activeforeground="white",
                  relief="flat", bd=0,
                  font=(FAM, 9),
                  padx=10, pady=8, cursor="hand2").pack(side="left")

    def _do_update(self, info: dict):
        from taf_order_app.updater import download_and_install
        import queue as _q

        if not info.get("download_url"):
            messagebox.showinfo("Update Available",
                f"Version {info.get('version','')} is available but no download link has been set yet.\n\n"
                "Ask your administrator to upload the new installer.")
            return

        if not getattr(sys, "frozen", False):
            messagebox.showinfo("Update",
                "Auto-update only works in the installed app.\n"
                "Download the latest version from the GitHub Releases page.")
            return

        dlg = tk.Toplevel(self.master)
        dlg.title("Updating…")
        dlg.resizable(False, False)
        dlg.transient(self.master)
        dlg.grab_set()
        dlg.configure(bg=CBG)

        tk.Label(dlg, text="Downloading update…",
                 bg=CBG, fg=CA, font=F_TTL, padx=24, pady=14).pack()

        status_var = tk.StringVar(value="Connecting…")
        tk.Label(dlg, textvariable=status_var,
                 bg=CBG, fg=CTX, font=F_BODY, padx=24).pack()

        bar = ttk.Progressbar(dlg, length=340, mode="determinate", maximum=100)
        bar.pack(padx=24, pady=(8, 20))

        dlg.update_idletasks()
        W, H = 400, 150
        dlg.geometry(f"{W}x{H}+{self.master.winfo_rootx() + self.master.winfo_width()//2 - W//2}"
                     f"+{self.master.winfo_rooty() + self.master.winfo_height()//2 - H//2}")

        q = _q.Queue()

        def _progress(pct, msg):
            q.put((pct, msg))

        def _work():
            try:
                download_and_install(info, progress_cb=_progress)
            except Exception as exc:
                q.put((-1, str(exc)))

        def _poll():
            try:
                while True:
                    pct, msg = q.get_nowait()
                    if pct == -1:
                        dlg.destroy()
                        messagebox.showerror("Update Failed", msg)
                        return
                    bar["value"] = pct
                    status_var.set(msg)
                    dlg.update_idletasks()
                    if pct >= 100:
                        # Give the PS1 script 1.5s to launch, then hard-exit
                        dlg.after(1500, lambda: os._exit(0))
                        return
            except _q.Empty:
                pass
            dlg.after(100, _poll)

        threading.Thread(target=_work, daemon=True).start()
        dlg.after(100, _poll)

    def _sign_out(self):
        if not messagebox.askyesno("Sign Out", "Sign out and return to the login screen?"):
            return
        _db.sign_out()
        self.master.destroy()
        _start_app()

    def _check_update_manual(self):
        from taf_order_app.updater import check_for_update, get_current_remote_version
        import queue as _q

        # Guard against re-entrancy. We keep the button ENABLED and just change
        # its label — the disabled pill renders light-on-light and looked like
        # the button had vanished. (No self.update() here either — calling it
        # inside a click handler is a re-entrancy hazard.)
        if getattr(self, "_upd_checking", False):
            return
        self._upd_checking = True
        self._check_upd_btn.config(text="Checking…")
        self._upd_status_var.set("Checking for updates…")
        q = _q.Queue()

        def _work():
            try:
                info   = check_for_update()
                remote = get_current_remote_version()
                q.put(("ok", (info, remote)))
            except Exception as exc:
                q.put(("error", str(exc)))

        def _poll():
            try:
                kind, data = q.get_nowait()
            except _q.Empty:
                self.master.after(150, _poll)
                return
            # Whatever happened, always restore the button so it can't get
            # stuck / invisible.
            self._upd_checking = False
            self._check_upd_btn.config(state="normal", text="Check for Updates")
            if kind == "ok":
                info, remote = data
                if info:
                    v = info.get("version", "")
                    self._upd_status_var.set(f"v{v} is available.")
                    self._pending_update = info
                    self._install_upd_btn.pack(side="left", padx=(8, 0))
                    self._update_banner_shown = False   # allow re-show
                    self._show_update_banner(info)
                else:
                    self._upd_status_var.set(f"You're up to date.  (v{remote})")
                    self._install_upd_btn.pack_forget()
            else:
                self._upd_status_var.set(f"Check failed: {data}")

        threading.Thread(target=_work, daemon=True).start()
        self.master.after(150, _poll)

    def _open_user_management(self):
        from taf_order_app.user_management import UserManagementDialog
        UserManagementDialog(self.master)

    @property
    def all_media_types(self) -> list:
        """Default built-in types followed by any user-added custom types."""
        seen = set(DEFAULT_MEDIA_TYPES)
        custom = [m for m in self._custom_media if m not in seen]
        return DEFAULT_MEDIA_TYPES + custom

    # ── Top-level layout ──────────────────────────────────────────────────

    def _build_ui(self):
        self.pack(fill="both", expand=True)
        self.master.rowconfigure(0, weight=1)
        self.master.columnconfigure(0, weight=1)

        self._build_header()
        self._build_tab_bar()

        # Content area – both tab frames sit at grid(0,0); tkraise() switches visibility
        self.content = tk.Frame(self, bg=CBG)
        self.content.pack(fill="both", expand=True)
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)

        # Build the landing tab + status bar now so "home" paints immediately.
        # The other six tabs are constructed lazily — a cold start shouldn't be
        # blocked building screens (and their date pickers / babel locale data)
        # the user hasn't opened yet. They warm up during idle time below, and
        # _show_tab builds any tab on demand if it's clicked first.
        self._lazy_tab_builders = {
            "prev_orders": self._build_prev_orders_tab,
            "customers":   self._build_customers_tab,
            "dashboard":   self._build_dashboard_tab,
            "stock":       self._build_stock_tab,
            "audit_log":   self._build_audit_log_tab,
            "settings":    self._build_settings_tab,
        }
        self._build_new_order_tab()
        self._build_status_bar()

        # Land on Settings at startup (per request), not New Order.
        self._show_tab("settings")

        # Warm the remaining tabs one-per-idle-tick so later switches are
        # instant, without delaying the first paint of the home screen.
        self.master.after_idle(self._prebuild_next_tab)

    def _ensure_tab_built(self, key: str):
        """Construct a tab's widgets on first access (lazy building)."""
        builder = getattr(self, "_lazy_tab_builders", {}).pop(key, None)
        if builder is not None:
            builder()

    def _prebuild_next_tab(self):
        """Build one not-yet-built tab per idle tick, then reschedule."""
        builders = getattr(self, "_lazy_tab_builders", None)
        if not builders:
            return
        self._ensure_tab_built(next(iter(builders)))
        self.master.after_idle(self._prebuild_next_tab)

    # ── Header bar ────────────────────────────────────────────────────────

    def _avatar(self, parent, initials, size=34):
        """Circular brand-blue avatar with white initials (drawn on a Canvas)."""
        c = tk.Canvas(parent, width=size, height=size, bg=CCA, highlightthickness=0)
        c.create_oval(1, 1, size - 1, size - 1, fill=CA, outline="")
        c.create_text(size // 2, size // 2 + 1, text=initials, fill="white",
                      font=(FAM, int(size * 0.36), "bold"))
        return c

    def _build_header(self):
        hdr = tk.Frame(self, bg=CCA, highlightbackground=CSP, highlightthickness=1)
        hdr.pack(fill="x")
        inner = tk.Frame(hdr, bg=CCA, padx=18, pady=8)
        inner.pack(fill="x")

        # Horizontal logo
        self._logo_img = None
        logo_path = RESOURCE_DIR / "TAF_logo_horizontal.png"
        if logo_path.exists():
            try:
                raw = tk.PhotoImage(file=str(logo_path))
                f = max(1, raw.height() // 46)
                self._logo_img = raw.subsample(f, f)
                tk.Label(inner, image=self._logo_img, bg=CCA).pack(side="left")
            except Exception:
                self._logo_img = None

        # Divider + subtitle
        tk.Frame(inner, bg=CSP, width=1, height=32).pack(side="left", padx=16)
        tk.Label(inner, text="Filter Order Entry\nWorksheet Generator",
                 bg=CCA, fg=CMU, font=(FAM, 9), justify="left",
                 anchor="w").pack(side="left")

        # Right: profile block (clickable → Settings) + Sign out outline button
        if _db.is_ready() and _db.current_user():
            role = _db.current_role()
            name = _db.current_full_name() or _db.current_username()

            so = tk.Label(inner, text="Sign out", bg=CCA, fg=CMU,
                          font=(FAM, 9, "bold"), padx=14, pady=7, cursor="hand2",
                          highlightbackground=CSP, highlightthickness=1)
            so.pack(side="right", padx=(14, 0))
            so.bind("<Button-1>", lambda e: self._sign_out())
            so.bind("<Enter>", lambda e: so.config(fg=CA, highlightbackground=CA))
            so.bind("<Leave>", lambda e: so.config(fg=CMU, highlightbackground=CSP))

            prof = tk.Frame(inner, bg=CCA, cursor="hand2")
            prof.pack(side="right")
            av = self._avatar(prof, _initials(name), size=36)
            av.pack(side="right", padx=(10, 0))
            tcol = tk.Frame(prof, bg=CCA)
            tcol.pack(side="right")
            tk.Label(tcol, text=role.upper(), bg=CCA, fg=CGR,
                     font=(FAM, 8, "bold"), anchor="e").pack(anchor="e")
            tk.Label(tcol, text=name, bg=CCA, fg=CTX,
                     font=(FAM, 10, "bold"), anchor="e").pack(anchor="e")
            for w in (prof, tcol, av):
                w.bind("<Button-1>", lambda e: self._show_tab("settings"))

    # ── Tab bar ───────────────────────────────────────────────────────────

    def _build_tab_bar(self):
        bar = tk.Frame(self, bg=CCA, highlightbackground=CSP, highlightthickness=1)
        bar.pack(fill="x")

        self._tab_bar_inner = tk.Frame(bar, bg=CCA, padx=8)
        self._tab_bar_inner.pack(fill="x")

        tabs = [
            ("new_order",   "＋  New Order"),
            ("prev_orders", "▤  Previous Orders"),
            ("customers",   "👥  Customers"),
            ("dashboard",   "▦  Dashboard"),
            ("stock",       "📦  Stock"),
            ("audit_log",   "☰  Audit Log"),
            ("settings",    "⚙  Settings"),
        ]
        self._tab_underlines = {}
        for key, label_text in tabs:
            cell = tk.Frame(self._tab_bar_inner, bg=CCA)
            cell.pack(side="left")
            btn = tk.Label(cell, text=label_text, bg=CCA, fg=CMU,
                           font=(FAM, 9, "bold"), padx=14, pady=11, cursor="hand2")
            btn.pack()
            btn.bind("<Button-1>", lambda e, k=key: self._show_tab(k))
            btn.bind("<Enter>",    lambda e, k=key: self._tab_hover(k, True))
            btn.bind("<Leave>",    lambda e, k=key: self._tab_hover(k, False))
            ul = tk.Frame(cell, bg=CCA, height=2)
            ul.pack(fill="x")
            self._tab_buttons[key]    = btn
            self._tab_underlines[key] = ul

    def _tab_hover(self, key: str, entering: bool):
        if getattr(self, "_active_tab", None) == key:
            return
        self._tab_buttons[key].config(fg=CTX if entering else CMU)

    def _show_tab(self, key: str):
        self._ensure_tab_built(key)   # lazily build the tab if not constructed yet
        self._active_tab = key
        for k, btn in self._tab_buttons.items():
            active = (k == key)
            btn.config(fg=CA if active else CMU)
            self._tab_underlines[k].config(bg=CA if active else CCA)

        self._tab_frames[key].tkraise()
        self._maybe_refresh(key)

    # Seconds a tab's data stays "fresh" — bouncing between tabs within this
    # window skips the re-fetch + treeview rebuild, so switching is instant.
    _TAB_TTL = 60

    def _maybe_refresh(self, key: str):
        """Load a tab's data on show, but skip if it was loaded recently.

        Manual Refresh buttons and data mutations call the _refresh_* methods
        directly (bypassing this gate), so they always run and re-stamp
        freshness. Order generation invalidates prev_orders + dashboard.
        """
        import time
        # Settings' local-storage line is cheap; always keep it current.
        if key == "settings" and hasattr(self, "_local_storage_lbl"):
            self._local_storage_lbl.set(self._local_storage_info())

        if time.monotonic() - self._tab_loaded.get(key, 0.0) < self._TAB_TTL:
            return  # still fresh — instant switch, no network / rebuild
        self._tab_loaded[key] = time.monotonic()

        if key == "new_order":
            self._load_known_customers()
        elif key == "prev_orders":
            self._refresh_orders_list()
        elif key == "dashboard":
            self._refresh_dashboard()
        elif key == "customers":
            self._refresh_customers_list()
        elif key == "stock":
            self._refresh_stock_list()
        elif key == "audit_log":
            self._refresh_audit_log()
        elif key == "settings":
            self._refresh_media_list()

    # ── New Order tab ─────────────────────────────────────────────────────

    def _build_new_order_tab(self):
        frm = tk.Frame(self.content, bg=CBG)
        frm.grid(row=0, column=0, sticky="nsew")
        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(0, weight=1)
        self._tab_frames["new_order"] = frm

        self._build_order_details_panel(frm)
        self._build_line_items_panel(frm)

    def _build_order_details_panel(self, parent):
        left = tk.Frame(parent, bg=CBG, padx=14, pady=12)
        left.grid(row=0, column=0, sticky="nsew")

        # Card: Order Details
        card_outer, card_body = card_frame(left, title="Order Details")
        card_outer.pack(fill="x")
        card_body.columnconfigure(1, weight=1)

        self.hvars = {
            "Customer Name": tk.StringVar(),
            "Order Number":  tk.StringVar(),
            "Date Ordered":  tk.StringVar(),
            "Date Due":      tk.StringVar(),
            "Attention":     tk.StringVar(),
            "Job":           tk.StringVar(),
            "Location":      tk.StringVar(),
        }

        # Auto-note rule: JAF or AES in customer name → add label/wrap note
        self.hvars["Customer Name"].trace_add(
            "write", lambda *_: self._check_customer_note()
        )
        # Customer autocomplete
        self._known_customers: list = []
        self._ac_popup: "tk.Toplevel | None" = None
        self.hvars["Customer Name"].trace_add(
            "write", lambda *_: self.master.after(50, self._customer_autocomplete)
        )

        DATE_FIELDS = {"Date Ordered", "Date Due"}
        REQUIRED    = {"Customer Name", "Order Number", "Date Ordered"}

        field_rows = [
            "Customer Name", "Order Number", "Date Ordered",
            "Date Due", "Attention", "Job", "Location",
        ]

        # Store widget refs for validation highlighting
        self._hentries: dict = {}       # key → entry widget
        self._hfield_labels: dict = {}  # key → label widget

        for row, key in enumerate(field_rows):
            lbl = tk.Label(card_body, text=key,
                           bg=CCA, fg=CTX, font=F_BODY, anchor="w")
            lbl.grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
            self._hfield_labels[key] = lbl

            if key in DATE_FIELDS:
                wrap = tk.Frame(card_body, bg=CCA)
                wrap.grid(row=row, column=1, sticky="we", pady=4)
                wrap.columnconfigure(0, weight=1)

                e = field_entry(wrap, textvariable=self.hvars[key])
                e.grid(row=0, column=0, sticky="we")
                self._hentries[key] = e

                var = self.hvars[key]
                cal_btn = tk.Button(
                    wrap, text="📅",
                    command=lambda v=var, b=None: None,
                    bg=CA, fg="white", relief="flat", bd=0,
                    font=(FAM, 9), padx=6, pady=2,
                    cursor="hand2",
                    activebackground=_dk(CA), activeforeground="white",
                )
                cal_btn.grid(row=0, column=1, padx=(3, 0))
                cal_btn.config(command=lambda v=var, b=cal_btn:
                               CalendarPicker(self.master, v, anchor=b))

                if key == "Date Due":
                    self.hvars[key].set("ASAP")
            else:
                e = field_entry(card_body, textvariable=self.hvars[key])
                e.grid(row=row, column=1, sticky="we", pady=4)
                self._hentries[key] = e
                if key == "Customer Name":
                    self._customer_entry = e

        # Clear individual field error as user types + trigger draft save
        for req_key in REQUIRED:
            self.hvars[req_key].trace_add(
                "write", lambda *_, k=req_key: self._clear_field_error(k))
        # Auto-save draft on any header field change
        for _hkey in self.hvars:
            self.hvars[_hkey].trace_add("write", lambda *_: self._schedule_draft_save())

        # Notes
        r = len(field_rows)
        tk.Label(card_body, text="Notes",
                 bg=CCA, fg=CTX, font=F_BODY,
                 anchor="nw").grid(row=r, column=0, sticky="nw",
                                   pady=(8, 4), padx=(0, 10))
        self.txt_header_notes = tk.Text(
            card_body, height=5, width=24, wrap="word",
            font=F_BODY, relief="solid", bd=1,
            bg=CCA, fg=CTX, insertbackground=CTX)
        self.txt_header_notes.grid(row=r, column=1, sticky="we", pady=(8, 4))
        self.txt_header_notes.bind("<<Modified>>",
            lambda e: (self.txt_header_notes.edit_modified(False),
                       self._schedule_draft_save()))

        # ── Validation error banner (hidden until needed) ─────────────────
        self._validation_banner = tk.Frame(left, bg="#FDECEA",
                                            highlightbackground=CRD,
                                            highlightthickness=1)
        # Not packed yet — shown by _validate_header() on failure
        self._validation_banner_lbl = tk.Label(
            self._validation_banner,
            text="", bg="#FDECEA", fg=CRD,
            font=F_SM, justify="left", anchor="w",
            padx=10, pady=6, wraplength=220)
        self._validation_banner_lbl.pack(fill="x")

        # Priority flag
        pri_row = tk.Frame(left, bg=CBG, pady=4)
        pri_row.pack(fill="x")
        self._priority_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            pri_row, text="🚨  High Priority Order",
            variable=self._priority_var,
            bg=CBG, fg=CRD, font=F_BOLD, activebackground=CBG,
            selectcolor=CCA, cursor="hand2",
        ).pack(anchor="w")

        # Action buttons below card
        act = tk.Frame(left, bg=CBG, pady=6)
        act.pack(fill="x")
        flat_btn(act, "New Order", self._new_order,
                 bg=CA, pady=7).pack(side="left", padx=(0, 6))
        flat_btn(act, "Load JSON", self._load_json,
                 bg=CNE, pady=7).pack(side="left")

    def _build_line_items_panel(self, parent):
        right = tk.Frame(parent, bg=CBG, pady=12)
        right.grid(row=0, column=1, sticky="nsew", padx=(0, 14))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        # One rounded navy-header card holding the toolbar + items table
        self._items_card, body = card_frame(right, title="Line Items")
        self._items_card.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)
        self._items_card.set_header_right("0 items")

        # Toolbar
        tb = tk.Frame(body, bg=CCA)
        tb.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        # Two "add" buttons — one for each item type
        flat_btn(tb, "+ Filter Item",  self._add_filter_item,
                 bg=CA,  pady=5, padx=10, font=F_BOLD).pack(side="left", padx=(0, 5))
        flat_btn(tb, "+ Bag / Roll",   self._add_bag_item,
                 bg=CA2, pady=5, padx=10, font=F_BOLD).pack(side="left", padx=(0, 5))
        flat_btn(tb, "⚙ Dedicated Filters", self._open_compressor_presets,
                 bg=CNE, pady=5, padx=10, font=F_BOLD).pack(side="left", padx=(0, 12))

        sep = tk.Frame(tb, bg=CSP, width=1)
        sep.pack(side="left", fill="y", padx=(0, 8), pady=2)

        for txt, cmd, bg, fnt in [
            ("Edit",      self._edit_item,             CNE, F_BODY),
            ("Delete",    self._delete_item,           CRD, F_BODY),
            ("Duplicate", self._duplicate_item,        CNE, F_BODY),
            ("↑ Up",      lambda: self._move_item(-1), CNE, F_BODY),
            ("↓ Down",    lambda: self._move_item(1),  CNE, F_BODY),
        ]:
            flat_btn(tb, txt, cmd, bg=bg,
                     pady=5, padx=10, font=fnt).pack(side="left", padx=(0, 5))

        # Treeview
        tree_wrap = tk.Frame(body, bg=CCA,
                             highlightbackground=CSP, highlightthickness=1)
        tree_wrap.grid(row=1, column=0, sticky="nsew")
        tree_wrap.rowconfigure(0, weight=1)
        tree_wrap.columnconfigure(0, weight=1)

        cols = ("qty", "type", "size", "media", "options", "notes")
        self.tree = ttk.Treeview(tree_wrap, columns=cols,
                                  show="tree headings",
                                  style="TAF.Treeview",
                                  selectmode="browse")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.heading("#0", text="Kind", anchor="center")
        self.tree.column("#0", width=92, minwidth=80, anchor="center", stretch=False)

        col_defs = {
            "qty":     ("Qty",          50, "center"),
            "type":    ("Type",        138, "w"),
            "size":    ("Dimensions",  148, "center"),
            "media":   ("Media",        72, "center"),
            "options": ("Options",     175, "w"),
            "notes":   ("Notes",       999, "w"),
        }
        for col, (hd, wd, anc) in col_defs.items():
            self.tree.heading(col, text=hd)
            self.tree.column(col, width=wd, anchor=anc, minwidth=40,
                             stretch=(col == "notes"))

        self.tree.tag_configure("even",   background=CRE)
        self.tree.tag_configure("odd",    background=CCA)
        self.tree.tag_configure("bag_e",  background="#EBF5FB")
        self.tree.tag_configure("bag_o",  background="#D6EAF8")

        vsb = ttk.Scrollbar(tree_wrap, orient="vertical",
                             command=self.tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.bind("<Double-1>", lambda e: self._edit_item())

        # Generate button
        gen_row = tk.Frame(right, bg=CBG, pady=8)
        gen_row.grid(row=1, column=0, sticky="ew")
        flat_btn(gen_row, "Generate Output",
                 self._generate, bg=CGR,
                 pady=10, padx=22, font=F_BOLD).pack(side="right")

    # ── Previous Orders tab ───────────────────────────────────────────────

    def _build_prev_orders_tab(self):
        frm = tk.Frame(self.content, bg=CBG, padx=14, pady=12)
        frm.grid(row=0, column=0, sticky="nsew")
        frm.rowconfigure(1, weight=1)
        frm.columnconfigure(0, weight=1)
        self._tab_frames["prev_orders"] = frm

        # ── Search / filter bar ───────────────────────────────────────────
        srch = tk.Frame(frm, bg=CBG)
        srch.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        # Search box
        tk.Label(srch, text="Search:", bg=CBG, fg=CTX,
                 font=F_BOLD).pack(side="left", padx=(0, 6))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._filter_orders_list())
        se = field_entry(srch, textvariable=self.search_var, width=28)
        se.pack(side="left", padx=(0, 14))

        # Order type dropdown
        tk.Label(srch, text="Type:", bg=CBG, fg=CTX,
                 font=F_BOLD).pack(side="left", padx=(0, 6))
        self.filter_type_var = tk.StringVar(value="All")
        type_cb = ttk.Combobox(srch, textvariable=self.filter_type_var,
                               values=["All", "Filter", "Bags", "Mixed"],
                               state="readonly", width=8)
        type_cb.pack(side="left", padx=(0, 14))
        self.filter_type_var.trace_add("write", lambda *_: self._filter_orders_list())

        # Status filter
        tk.Label(srch, text="Status:", bg=CBG, fg=CTX,
                 font=F_BOLD).pack(side="left", padx=(0, 6))
        self.filter_status_var = tk.StringVar(value="All")
        status_cb = ttk.Combobox(srch, textvariable=self.filter_status_var,
                                 values=["All", "Pending", "In Production", "Complete",
                                       "Dispatched"],
                                 state="readonly", width=12)
        status_cb.pack(side="left", padx=(0, 14))
        self.filter_status_var.trace_add("write", lambda *_: self._filter_orders_list())

        # Date from
        tk.Label(srch, text="From:", bg=CBG, fg=CTX,
                 font=F_BOLD).pack(side="left", padx=(0, 6))
        self.filter_date_from = tk.StringVar()
        df = _make_date_entry(srch, textvariable=self.filter_date_from)
        df.pack(side="left", padx=(0, 4))
        tk.Label(srch, text="To:", bg=CBG, fg=CTX,
                 font=F_BOLD).pack(side="left", padx=(0, 6))
        self.filter_date_to = tk.StringVar()
        dt = _make_date_entry(srch, textvariable=self.filter_date_to)
        dt.pack(side="left", padx=(0, 14))
        # DateEntry auto-sets today's date — clear both so no date filter by default
        self.filter_date_from.set("")
        self.filter_date_to.set("")
        # Now wire up the traces (after clearing so initial set doesn't over-filter)
        self.filter_date_from.trace_add("write", lambda *_: self._filter_orders_list())
        self.filter_date_to.trace_add("write", lambda *_: self._filter_orders_list())

        # Clear filters button
        def _clear_filters():
            self.search_var.set("")
            self.filter_type_var.set("All")
            self.filter_status_var.set("All")
            self.filter_date_from.set("")
            self.filter_date_to.set("")
        flat_btn(srch, "Clear", _clear_filters,
                 bg=CMU, pady=5, padx=8, font=F_BODY).pack(side="left", padx=(0, 8))

        flat_btn(srch, "Refresh", self._refresh_orders_list,
                 bg=CNE, pady=5, padx=10, font=F_BODY).pack(side="right")

        # ── Orders treeview ───────────────────────────────────────────────
        tbl_wrap = tk.Frame(frm, bg=CCA,
                            highlightbackground=CSP, highlightthickness=1)
        tbl_wrap.grid(row=1, column=0, sticky="nsew")
        tbl_wrap.rowconfigure(0, weight=1)
        tbl_wrap.columnconfigure(0, weight=1)

        ocols = ("customer", "order_no", "date_ordered", "date_due", "status", "n_items", "created_by", "file")
        self.orders_tree = ttk.Treeview(tbl_wrap, columns=ocols,
                                         show="tree headings",
                                         style="TAF.Treeview",
                                         selectmode="extended")
        self.orders_tree.grid(row=0, column=0, sticky="nsew")
        self.orders_tree.heading("#0", text="Type", anchor="center")
        self.orders_tree.column("#0", width=106, minwidth=92, anchor="center", stretch=False)

        o_col_defs = {
            "customer":     ("Customer Name",  200, "w"),
            "order_no":     ("Order #",        120, "w"),
            "date_ordered": ("Date Ordered",   110, "center"),
            "date_due":     ("Date Due",       100, "center"),
            "status":       ("Status",         120, "center"),
            "n_items":      ("# Items",         70, "center"),
            "created_by":   ("Created By",     180, "w"),
            "file":         ("Source",         130, "center"),
        }
        for col, (hd, wd, anc) in o_col_defs.items():
            self.orders_tree.heading(col, text=hd, anchor="center" if anc == "center" else "w")
            self.orders_tree.column(col, width=wd, anchor=anc, minwidth=40,
                                    stretch=(col in ("customer", "created_by")))

        self.orders_tree.tag_configure("even",        background=CRE)
        self.orders_tree.tag_configure("odd",         background=CCA)
        self.orders_tree.tag_configure("priority",    background="#FDECEC", foreground="#D33A3F")
        self.orders_tree.tag_configure("in_prod",     background="#FFF3CD", foreground="#856404")
        self.orders_tree.tag_configure("complete",    background="#D4EDDA", foreground="#155724")
        self.orders_tree.tag_configure("dispatched",  background="#CCE5FF", foreground="#004085")

        ovsb = ttk.Scrollbar(tbl_wrap, orient="vertical",
                              command=self.orders_tree.yview)
        ovsb.grid(row=0, column=1, sticky="ns")
        self.orders_tree.configure(yscrollcommand=ovsb.set)
        self.orders_tree.bind("<Double-1>", lambda e: self._load_prev_order())
        self.orders_tree.bind("<Motion>",   self._on_orders_tree_hover)
        self.orders_tree.bind("<Leave>",    lambda e: self._hide_order_tooltip())

        # ── Bottom actions ────────────────────────────────────────────────
        bot = tk.Frame(frm, bg=CBG, pady=8)
        bot.grid(row=2, column=0, sticky="ew")

        flat_btn(bot, "Load into New Order",   self._load_prev_order,
                 bg=CA,  pady=7).pack(side="left", padx=(0, 8))
        flat_btn(bot, "Duplicate Order",       self._duplicate_prev_order,
                 bg=CA2, pady=7).pack(side="left", padx=(0, 8))
        flat_btn(bot, "Regenerate Worksheets", self._regen_prev_order,
                 bg=CGR, pady=7).pack(side="left", padx=(0, 8))
        flat_btn(bot, "Open Orders Folder",    self._open_orders_folder,
                 bg=CNE, pady=7).pack(side="left", padx=(0, 8))
        flat_btn(bot, "📝 Add Note",           self._add_order_note,
                 bg=CA2, pady=7).pack(side="left", padx=(0, 8))
        flat_btn(bot, "🕐 View History",       self._view_order_history,
                 bg=CNE, pady=7).pack(side="left", padx=(0, 8))
        flat_btn(bot, "🚨 Toggle Priority",    self._toggle_order_priority,
                 bg=CRD, pady=7).pack(side="left", padx=(0, 8))
        flat_btn(bot, "⚙ Change Status",      self._change_order_status,
                 bg=CA2, pady=7).pack(side="left", padx=(0, 8))
        flat_btn(bot, "🖨 Print",             self._print_prev_order,
                 bg=CNE, pady=7).pack(side="left", padx=(0, 8))
        flat_btn(bot, "Delete Order",          self._delete_prev_order,
                 bg=CRD, pady=7).pack(side="right", padx=(8, 0))
        flat_btn(bot, "Archive Order",         self._archive_prev_order,
                 bg="#7D3C98", pady=7).pack(side="right")

    # ── Dashboard tab ─────────────────────────────────────────────────────

    def _build_dashboard_tab(self):
        frm = tk.Frame(self.content, bg=CBG, padx=16, pady=12)
        frm.grid(row=0, column=0, sticky="nsew")
        frm.columnconfigure(0, weight=1)
        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(1, weight=1)
        frm.rowconfigure(2, weight=1)
        self._tab_frames["dashboard"] = frm

        tk.Label(frm, text="Dashboard", bg=CBG, fg=CA,
                 font=F_TTL).grid(row=0, column=0, sticky="w", pady=(0, 10))

        # Alerts panel top-right
        alert_outer = tk.Frame(frm, bg=CCA, relief="flat", bd=1,
                               highlightbackground=CSP, highlightthickness=1)
        alert_outer.grid(row=0, column=1, sticky="ne", padx=(8, 0))
        tk.Label(alert_outer, text="⚠  Low Stock Alerts", bg=CCA, fg=CRD,
                 font=F_SEC).pack(anchor="w", padx=8, pady=(6, 2))
        self._alert_list_frame = tk.Frame(alert_outer, bg=CCA)
        self._alert_list_frame.pack(fill="x", padx=8, pady=(0, 6))

        def _make_chart_card(row, col, title, colspan=1):
            outer = tk.Frame(frm, bg=CCA, highlightbackground=CSP, highlightthickness=1)
            outer.grid(row=row, column=col, columnspan=colspan, sticky="nsew",
                       padx=(0 if col == 0 else 4, 0), pady=(0, 6))
            tk.Label(outer, text=title, bg=CCA, fg=CTX,
                     font=F_SEC).pack(anchor="w", padx=8, pady=(6, 2))
            cv = tk.Canvas(outer, bg=CCA, height=180, highlightthickness=0)
            cv.pack(fill="both", expand=True, padx=6, pady=(0, 6))
            return cv

        self._canvas_weekly    = _make_chart_card(1, 0, "Orders per Week  (Australian FY — last 12 weeks)")
        self._canvas_types     = _make_chart_card(1, 1, "Order Types")
        self._canvas_customers = _make_chart_card(2, 0, "Busiest Customers  (top 5)", colspan=2)

        # Redraw on resize
        for cv in (self._canvas_weekly, self._canvas_types, self._canvas_customers):
            cv.bind("<Configure>", lambda e: self.master.after(50, self._refresh_charts))

        # Monthly summary button row
        dash_btn_row = tk.Frame(frm, bg=CBG)
        dash_btn_row.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        flat_btn(dash_btn_row, "📊  Generate Monthly Summary Report",
                 self._generate_monthly_summary,
                 bg=CA, pady=7, padx=16, font=F_BOLD).pack(side="left")

    def _refresh_dashboard(self):
        """Called when the Dashboard tab is shown. Fetches order data off the
        main thread so opening the tab never blocks the UI."""
        data = getattr(self, "_all_orders_data", None)
        if data:
            self._refresh_charts()
            self._refresh_alerts(data)
            return

        import queue as _q
        q = _q.Queue()

        def _work():
            try:
                q.put(self._scan_orders())
            except Exception:
                q.put([])

        def _poll():
            try:
                data = q.get_nowait()
            except _q.Empty:
                self.master.after(60, _poll)
                return
            self._all_orders_data = data
            self._refresh_charts()
            self._refresh_alerts(data)

        threading.Thread(target=_work, daemon=True).start()
        self.master.after(60, _poll)

    def _refresh_charts(self):
        import collections
        data = getattr(self, "_all_orders_data", [])

        def _parse_d(s):
            for fmt in ("%d/%m/%y", "%d/%m/%Y", "%d-%m/%y", "%d-%m-%Y"):
                try:
                    return _dt_module.datetime.strptime(s, fmt).date()
                except Exception:
                    pass
            return None

        # ── Orders per week — Australian FY (July 1 start), last 12 weeks ──
        today = _dt_module.date.today()
        fy_start_year = today.year if today.month >= 7 else today.year - 1
        fy_start = _dt_module.date(fy_start_year, 7, 1)

        week_keys = []
        week_counts = {}
        MAX_SHOW = 12
        weeks_in_fy = max(1, (today - fy_start).days // 7 + 1)
        show_n = min(weeks_in_fy, MAX_SHOW)
        for i in range(show_n - 1, -1, -1):
            wdate = today - _dt_module.timedelta(weeks=i)
            if wdate < fy_start:
                continue
            iso = wdate.isocalendar()
            k   = (iso[0], iso[1])
            if k not in week_counts:
                week_keys.append(k)
                week_counts[k] = 0
        for row in data:
            d = _parse_d(row.get("date_ordered", ""))
            if d and d >= fy_start:
                k = (d.isocalendar()[0], d.isocalendar()[1])
                if k in week_counts:
                    week_counts[k] += 1
        # Label as FY week number (W1 = first week of July)
        def _fy_wk(year, iso_wk):
            try:
                mon = _dt_module.date.fromisocalendar(year, iso_wk, 1)
                return max(1, (mon - fy_start).days // 7 + 1)
            except Exception:
                return iso_wk
        wk_labels = [f"W{_fy_wk(k[0], k[1])}" for k in week_keys]
        wk_values = [week_counts[k] for k in week_keys]

        cv = self._canvas_weekly
        cv.update_idletasks()
        W, H = max(cv.winfo_width(), 200), max(cv.winfo_height(), 140)
        _draw_bar_chart(cv, wk_values, wk_labels, W, H, PAD=30, bar_colour=CA)

        # ── Order types ───────────────────────────────────────────────────
        type_map  = {"filter": "Filter", "bags": "Bags", "mixed": "Mixed"}
        type_cnt  = collections.Counter(
            type_map.get(r.get("order_type", "filter"), "Filter") for r in data)
        sorted_t  = type_cnt.most_common()
        cv2 = self._canvas_types
        cv2.update_idletasks()
        W2, H2 = max(cv2.winfo_width(), 200), max(cv2.winfo_height(), 140)
        _draw_bar_chart(cv2, [v for _, v in sorted_t], [k for k, _ in sorted_t],
                        W2, H2, PAD=30, bar_colour=CGR, horizontal=True)

        # ── Busiest customers (top 5) — truncate long names ──────────────
        cust_cnt = collections.Counter(
            r.get("customer", "Unknown") for r in data if r.get("customer"))
        top5 = cust_cnt.most_common(5)
        cv3 = self._canvas_customers
        cv3.update_idletasks()
        W3, H3 = max(cv3.winfo_width(), 400), max(cv3.winfo_height(), 140)
        # Truncate names to fit — max 20 chars, add ellipsis
        def _trunc(name, n=20):
            return name if len(name) <= n else name[:n-1] + "…"
        _draw_bar_chart(cv3, [v for _, v in top5],
                        [_trunc(k) for k, _ in top5],
                        W3, H3, PAD=20, bar_colour="#16608F", horizontal=True)

    def _generate_monthly_summary(self):
        """Open a month/year picker dialog and generate a summary PDF."""
        import calendar as _calendar

        dlg = tk.Toplevel(self.master)
        dlg.title("Monthly Order Summary")
        dlg.resizable(False, False)
        dlg.transient(self.master)
        dlg.grab_set()
        dlg.configure(bg=CBG)

        hdr = tk.Frame(dlg, bg=CA, padx=16, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Generate Monthly Summary Report",
                 bg=CA, fg="white", font=F_BOLD).pack(anchor="w")
        tk.Label(hdr,
                 text="Exports a PDF overview of all orders for the selected month.",
                 bg=CA, fg="#A9CCE3", font=F_SM).pack(anchor="w")

        body = tk.Frame(dlg, bg=CBG, padx=16, pady=14)
        body.pack(fill="both", expand=True)

        today = datetime.date.today()

        row_m = tk.Frame(body, bg=CBG)
        row_m.pack(fill="x", pady=4)
        tk.Label(row_m, text="Month:", bg=CBG, fg=CTX,
                 font=F_BODY, width=8, anchor="w").pack(side="left")
        month_cb = ttk.Combobox(
            row_m,
            values=[_calendar.month_name[m] for m in range(1, 13)],
            state="readonly", width=14)
        month_cb.current(today.month - 1)
        month_cb.pack(side="left", padx=(0, 12))

        row_y = tk.Frame(body, bg=CBG)
        row_y.pack(fill="x", pady=4)
        tk.Label(row_y, text="Year:", bg=CBG, fg=CTX,
                 font=F_BODY, width=8, anchor="w").pack(side="left")
        year_cb = ttk.Combobox(
            row_y,
            values=[str(y) for y in range(today.year - 4, today.year + 1)],
            state="readonly", width=8)
        year_cb.set(str(today.year))
        year_cb.pack(side="left")

        foot = tk.Frame(dlg, bg=CBG, padx=14, pady=10)
        foot.pack(fill="x")
        result = [None]

        def _ok():
            m = month_cb.current() + 1
            try:
                y = int(year_cb.get())
            except ValueError:
                y = today.year
            result[0] = (m, y)
            dlg.destroy()

        flat_btn(foot, "Cancel", dlg.destroy, bg=CNE, pady=6).pack(side="right", padx=(6, 0))
        flat_btn(foot, "Generate PDF", _ok, bg=CGR, pady=6).pack(side="right")
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        W, H = 340, 200
        dlg.geometry(
            f"{W}x{H}+"
            f"{self.master.winfo_rootx()+self.master.winfo_width()//2-W//2}+"
            f"{self.master.winfo_rooty()+self.master.winfo_height()//2-H//2}"
        )
        self.master.wait_window(dlg)

        if result[0]:
            self._do_generate_monthly_summary(*result[0])

    def _do_generate_monthly_summary(self, month: int, year: int):
        """Generate a ReportLab PDF summary for the given month/year and open it."""
        import calendar as _calendar
        import collections

        # Gather data
        data = getattr(self, "_all_orders_data", [])
        if not data:
            try:
                data = self._scan_orders()
                self._all_orders_data = data
            except Exception:
                data = []

        def _parse_d(s):
            for fmt in ("%d/%m/%y", "%d/%m/%Y", "%d-%m-%y", "%d-%m-%Y"):
                try:
                    return _dt_module.datetime.strptime(s, fmt).date()
                except Exception:
                    pass
            return None

        month_orders = [
            r for r in data
            if (lambda d: d and d.year == year and d.month == month)(_parse_d(r.get("date_ordered", "")))
        ]

        month_name  = _calendar.month_name[month]
        title_str   = f"{month_name} {year}"
        total_orders = len(month_orders)
        type_counts  = collections.Counter(
            {"bags": "Bags", "mixed": "Mixed", "filter": "Filter"}.get(
                r.get("order_type", "filter"), "Filter")
            for r in month_orders)
        cust_counts  = collections.Counter(
            r.get("customer", "Unknown") for r in month_orders if r.get("customer"))
        top_custs    = cust_counts.most_common(10)
        total_items  = sum(r.get("n_items", 0) for r in month_orders)

        # Week breakdown (week 1-4/5 within the month)
        week_map = {}
        for r in month_orders:
            d = _parse_d(r.get("date_ordered", ""))
            if d:
                wk = (d.day - 1) // 7 + 1
                week_map[wk] = week_map.get(wk, 0) + 1

        # Generate PDF
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib import colors as _rl_colors
            from reportlab.lib.units import mm
            from reportlab.platypus import (
                SimpleDocTemplate, Paragraph, Spacer,
                Table, TableStyle, HRFlowable,
            )
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        except ImportError:
            messagebox.showerror(
                "ReportLab Missing",
                "ReportLab is required for PDF generation but is not installed.")
            return

        ORDERS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = ORDERS_DIR / f"Monthly_Summary_{year}_{month:02d}.pdf"

        doc = SimpleDocTemplate(
            str(out_path), pagesize=A4,
            rightMargin=20*mm, leftMargin=20*mm,
            topMargin=20*mm, bottomMargin=20*mm)

        navy  = _rl_colors.HexColor("#1A4F8A")
        dark  = _rl_colors.HexColor("#2D3748")
        muted = _rl_colors.HexColor("#718096")

        s_title = ParagraphStyle("T", fontSize=20, textColor=navy,
                                  fontName="Helvetica-Bold", spaceAfter=4)
        s_sub   = ParagraphStyle("S", fontSize=11, textColor=muted,
                                  fontName="Helvetica",      spaceAfter=14)
        s_h2    = ParagraphStyle("H2", fontSize=13, textColor=navy,
                                  fontName="Helvetica-Bold", spaceBefore=14, spaceAfter=6)
        s_body  = ParagraphStyle("B", fontSize=10, textColor=dark,
                                  fontName="Helvetica",      spaceAfter=4)
        s_foot  = ParagraphStyle("F", fontSize=8,  textColor=muted,
                                  fontName="Helvetica")

        def _make_tbl(rows, col_widths):
            t = Table(rows, colWidths=col_widths)
            t.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, 0), navy),
                ("TEXTCOLOR",     (0, 0), (-1, 0), _rl_colors.white),
                ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",      (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                 [_rl_colors.HexColor("#EDF2F7"), _rl_colors.white]),
                ("GRID",          (0, 0), (-1, -1), 0.5,
                 _rl_colors.HexColor("#CBD5E0")),
                ("TOPPADDING",    (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING",   (0, 0), (-1, -1), 8),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
                ("ALIGN",         (1, 1), (-1, -1), "RIGHT"),
            ]))
            return t

        story = []

        # Header
        story.append(Paragraph("Total Air Filtration", s_title))
        story.append(Paragraph(f"Monthly Order Summary — {title_str}", s_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=navy, spaceAfter=12))

        # KPI summary table
        story.append(Paragraph("Summary", s_h2))
        kpi = [
            ["Metric",           "Value"],
            ["Total Orders",     str(total_orders)],
            ["Total Line Items", str(total_items)],
            ["Unique Customers", str(len(cust_counts))],
            ["Filter Orders",    str(type_counts.get("Filter", 0))],
            ["Bag Orders",       str(type_counts.get("Bags",   0))],
            ["Mixed Orders",     str(type_counts.get("Mixed",  0))],
        ]
        story.append(_make_tbl(kpi, [130*mm, 40*mm]))
        story.append(Spacer(1, 10))

        # Top customers
        story.append(Paragraph("Top Customers", s_h2))
        if top_custs:
            cust_rows = [["Customer", "Orders"]] + [
                [name[:45], str(cnt)] for name, cnt in top_custs
            ]
            story.append(_make_tbl(cust_rows, [130*mm, 40*mm]))
        else:
            story.append(Paragraph("No orders this month.", s_body))
        story.append(Spacer(1, 10))

        # Week breakdown
        story.append(Paragraph("Orders by Week", s_h2))
        if week_map:
            wk_rows = [["Week of Month", "Orders"]] + [
                [f"Week {w}", str(week_map[w])] for w in sorted(week_map)
            ]
            story.append(_make_tbl(wk_rows, [130*mm, 40*mm]))
        else:
            story.append(Paragraph("No orders this month.", s_body))
        story.append(Spacer(1, 10))

        # All orders list
        story.append(Paragraph("All Orders", s_h2))
        if month_orders:
            ord_rows = [["Customer", "Order #", "Date", "Type", "Items"]]
            for r in sorted(month_orders, key=lambda x: x.get("date_ordered", "")):
                ot = {"bags": "Bags", "mixed": "Mixed", "filter": "Filter"}.get(
                    r.get("order_type", "filter"), "Filter")
                status = r.get("status", "Pending") or "Pending"
                ord_rows.append([
                    r.get("customer", "")[:38],
                    r.get("order_no", ""),
                    r.get("date_ordered", ""),
                    f"{ot} · {status}",
                    str(r.get("n_items", 0)),
                ])
            story.append(_make_tbl(ord_rows, [70*mm, 33*mm, 28*mm, 30*mm, 16*mm]))
        else:
            story.append(Paragraph("No orders this month.", s_body))

        story.append(Spacer(1, 20))
        gen_date = datetime.date.today().strftime("%d/%m/%Y")
        story.append(Paragraph(
            f"Generated by TAF Order Entry v{APP_VERSION}  ·  {gen_date}",
            s_foot))

        try:
            doc.build(story)
        except Exception as exc:
            messagebox.showerror("PDF Error", f"Could not generate PDF:\n{exc}")
            return

        self.status_var.set(f"Monthly summary saved: {out_path.name}")
        os.startfile(str(out_path))

    def _refresh_alerts(self, data=None):
        for w in self._alert_list_frame.winfo_children():
            w.destroy()
        if not (_db.is_ready() and _db.current_user()):
            tk.Label(self._alert_list_frame, text="Offline — no alerts",
                     bg=CCA, fg=CMU, font=F_SM).pack(anchor="w")
            return
        if data is None:
            data = getattr(self, "_all_orders_data", [])

        # Count media usage this month from db_items
        today = _dt_module.date.today()
        month_start = today.replace(day=1)
        media_usage = {}
        for row in data:
            def _parse_d2(s):
                for fmt in ("%d/%m/%y", "%d/%m/%Y"):
                    try:
                        return _dt_module.datetime.strptime(s, fmt).date()
                    except Exception:
                        pass
                return None
            d = _parse_d2(row.get("date_ordered", ""))
            if d and d >= month_start:
                for item in (row.get("db_items") or []):
                    mt = item.get("Media Type") or item.get("media") or item.get("media_type")
                    if mt:
                        media_usage[mt] = media_usage.get(mt, 0) + 1

        try:
            alerts = _db.get_stock_alerts()
        except Exception:
            alerts = []

        triggered = [(a["media_type"], media_usage.get(a["media_type"], 0), a["threshold"])
                     for a in alerts if media_usage.get(a["media_type"], 0) > a["threshold"]]

        if not triggered:
            tk.Label(self._alert_list_frame, text="✔  No alerts this month",
                     bg=CCA, fg=CMU, font=F_SM).pack(anchor="w")
            return
        for mt, used, thr in triggered:
            tk.Label(self._alert_list_frame,
                     text=f"  {mt}:  {used} used  (threshold {thr})",
                     bg="#FDEDEC", fg=CRD, font=F_BODY).pack(fill="x", pady=1)

    # ── Customers tab ─────────────────────────────────────────────────────

    def _build_customers_tab(self):
        frm = tk.Frame(self.content, bg=CBG, padx=14, pady=12)
        frm.grid(row=0, column=0, sticky="nsew")
        frm.rowconfigure(1, weight=1)
        frm.columnconfigure(0, weight=1)
        self._tab_frames["customers"] = frm

        # ── Top bar ───────────────────────────────────────────────────────
        top = tk.Frame(frm, bg=CBG)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        tk.Label(top, text="Customers", bg=CBG, fg=CA,
                 font=F_TTL).pack(side="left", padx=(0, 20))

        tk.Label(top, text="Search:", bg=CBG, fg=CTX,
                 font=F_BOLD).pack(side="left", padx=(0, 6))
        self._cust_search_var = tk.StringVar()
        self._cust_search_var.trace_add("write", lambda *_: self._filter_customers_list())
        field_entry(top, textvariable=self._cust_search_var,
                    width=26).pack(side="left", padx=(0, 14))

        self._cust_inactive_var = tk.BooleanVar(value=False)
        tk.Checkbutton(top, text="Show inactive",
                       variable=self._cust_inactive_var,
                       bg=CBG, fg=CTX, font=F_SM,
                       selectcolor=CCA, activebackground=CBG,
                       command=self._refresh_customers_list).pack(side="left", padx=(0, 14))

        flat_btn(top, "↻ Refresh", self._refresh_customers_list,
                 bg=CNE, pady=5, padx=10, font=F_BODY).pack(side="right", padx=(8, 0))
        flat_btn(top, "+ Add Customer",
                 lambda: self._open_customer_dialog(),
                 bg=CA, pady=5, padx=12, font=F_BOLD).pack(side="right")

        # ── Treeview ──────────────────────────────────────────────────────
        tbl_wrap = tk.Frame(frm, bg=CCA,
                            highlightbackground=CSP, highlightthickness=1)
        tbl_wrap.grid(row=1, column=0, sticky="nsew")
        tbl_wrap.rowconfigure(0, weight=1)
        tbl_wrap.columnconfigure(0, weight=1)

        ccols = ("name", "short", "contact", "phone", "email", "abn", "city", "terms")
        self._cust_tree = ttk.Treeview(tbl_wrap, columns=ccols,
                                       show="headings",
                                       style="TAF.Treeview",
                                       selectmode="browse")
        self._cust_tree.grid(row=0, column=0, sticky="nsew")

        c_col_defs = {
            "name":    ("Customer Name",  200, "w"),
            "short":   ("Short Name",     110, "w"),
            "contact": ("Contact Person", 150, "w"),
            "phone":   ("Phone",          110, "w"),
            "email":   ("Email",          180, "w"),
            "abn":     ("ABN",            110, "center"),
            "city":    ("City / State",   130, "w"),
            "terms":   ("Terms",           80, "center"),
        }
        for col, (hd, wd, anc) in c_col_defs.items():
            self._cust_tree.heading(col, text=hd,
                                    anchor="center" if anc == "center" else "w")
            self._cust_tree.column(col, width=wd, anchor=anc, minwidth=40,
                                   stretch=(col in ("name", "email")))

        self._cust_tree.tag_configure("even",     background=CRE)
        self._cust_tree.tag_configure("odd",      background=CCA)
        self._cust_tree.tag_configure("inactive", background="#F0F0F0", foreground=CMU)

        cvsb = ttk.Scrollbar(tbl_wrap, orient="vertical",
                              command=self._cust_tree.yview)
        cvsb.grid(row=0, column=1, sticky="ns")
        self._cust_tree.configure(yscrollcommand=cvsb.set)
        self._cust_tree.bind("<Double-1>",
                             lambda e: self._open_customer_dialog(edit=True))

        # ── Bottom actions ────────────────────────────────────────────────
        bot = tk.Frame(frm, bg=CBG, pady=8)
        bot.grid(row=2, column=0, sticky="ew")
        flat_btn(bot, "✏ Edit Customer",
                 lambda: self._open_customer_dialog(edit=True),
                 bg=CA, pady=7).pack(side="left", padx=(0, 8))
        flat_btn(bot, "📋 View Orders",
                 self._view_customer_orders,
                 bg=CA2, pady=7).pack(side="left", padx=(0, 8))
        flat_btn(bot, "+ New Order for Customer",
                 self._new_order_for_customer,
                 bg=CGR, pady=7).pack(side="left", padx=(0, 8))

        flat_btn(bot, "🗑 Delete",
                 self._delete_customer,
                 bg=CRD, pady=7).pack(side="right")

        self._customers_data: list = []

    def _refresh_customers_list(self):
        import queue as _q
        q = _q.Queue()
        active_only = not self._cust_inactive_var.get()

        def _work():
            try:
                custs = _db.get_customers(active_only=active_only)
                q.put(("ok", custs))
            except Exception as exc:
                q.put(("err", str(exc)))

        def _poll():
            try:
                while True:
                    kind, data = q.get_nowait()
                    if kind == "ok":
                        self._customers_data  = data
                        self._customer_records = data
                        self._known_customers  = [c.get("name", "") for c in data]
                        self._filter_customers_list()
                        return
                    else:
                        self.status_var.set(f"Customer fetch error: {data}")
                        return
            except _q.Empty:
                pass
            self.master.after(60, _poll)

        threading.Thread(target=_work, daemon=True).start()
        self.master.after(60, _poll)

    def _filter_customers_list(self):
        q = self._cust_search_var.get().strip().lower()
        for iid in self._cust_tree.get_children():
            self._cust_tree.delete(iid)

        shown = []
        for c in self._customers_data:
            if q and not any(q in (c.get(f) or "").lower()
                             for f in ("name", "legal_name", "contact_person",
                                       "email", "phone", "abn", "delivery_city")):
                continue
            shown.append(c)

        for i, c in enumerate(shown):
            active = c.get("is_active", True)
            city   = c.get("delivery_city", "")
            state  = c.get("delivery_state", "")
            loc    = ", ".join(p for p in [city, state] if p)
            tag    = "inactive" if not active else ("even" if i % 2 == 0 else "odd")
            self._cust_tree.insert("", "end", iid=str(i), tags=(tag,), values=(
                c.get("name", ""),
                c.get("short_name", "") or "—",
                c.get("contact_person", "") or "—",
                c.get("phone", "") or "—",
                c.get("email", "") or "—",
                c.get("abn", "") or "—",
                loc or "—",
                c.get("payment_terms", "Net 30"),
            ))

        self.status_var.set(
            f"{len(shown)} customer{'s' if len(shown) != 1 else ''}")

    def _get_selected_customer(self) -> "dict | None":
        sel = self._cust_tree.selection()
        if not sel:
            return None
        idx = int(sel[0])
        q   = self._cust_search_var.get().strip().lower()
        shown = [c for c in self._customers_data
                 if not q or any(q in (c.get(f) or "").lower()
                                 for f in ("name", "legal_name", "contact_person",
                                           "email", "phone", "abn", "delivery_city"))]
        return shown[idx] if idx < len(shown) else None

    def _open_customer_dialog(self, edit: bool = False):
        cust      = self._get_selected_customer() if edit else None
        if edit and cust is None:
            messagebox.showinfo("Edit Customer", "Select a customer first.")
            return
        is_new = cust is None
        title  = "Add Customer" if is_new else "Edit Customer"

        dlg = tk.Toplevel(self.master)
        dlg.title(title)
        dlg.transient(self.master)
        dlg.grab_set()
        dlg.configure(bg=CBG)
        dlg.resizable(True, True)
        W, H = 700, 700
        dlg.geometry(
            f"{W}x{H}+"
            f"{self.master.winfo_rootx()+self.master.winfo_width()//2-W//2}+"
            f"{self.master.winfo_rooty()+self.master.winfo_height()//2-H//2}")

        # Header
        hdr = tk.Frame(dlg, bg=CA, padx=16, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text=title, bg=CA, fg="white", font=F_BOLD).pack(anchor="w")
        if cust:
            tk.Label(hdr, text=cust.get("name", ""),
                     bg=CA, fg="#A9CCE3", font=F_SM).pack(anchor="w")

        # Scrollable body
        bfrm   = tk.Frame(dlg, bg=CBG)
        bfrm.pack(fill="both", expand=True)
        bcan   = tk.Canvas(bfrm, bg=CBG, highlightthickness=0)
        bsb    = ttk.Scrollbar(bfrm, orient="vertical", command=bcan.yview)
        bcan.configure(yscrollcommand=bsb.set)
        bsb.pack(side="right", fill="y")
        bcan.pack(side="left", fill="both", expand=True)
        body   = tk.Frame(bcan, bg=CBG, padx=22, pady=14)
        _bw    = bcan.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: bcan.configure(scrollregion=bcan.bbox("all")))
        bcan.bind("<Configure>",  lambda e: bcan.itemconfig(_bw, width=e.width))
        def _mw(e): bcan.yview_scroll(-1*(e.delta//120), "units")
        bcan.bind("<Enter>", lambda e: bcan.bind_all("<MouseWheel>", _mw))
        bcan.bind("<Leave>", lambda e: bcan.unbind_all("<MouseWheel>"))
        body.columnconfigure(1, weight=1)

        g = cust or {}

        def _sec(text):
            """Section heading divider."""
            nonlocal _row
            tk.Label(body, text=text, bg=CBG, fg=CA,
                     font=F_SEC, anchor="w").grid(
                row=_row, column=0, columnspan=2, sticky="w",
                pady=(14, 4))
            _row += 1

        def _row_f(label, var=None, combo_vals=None, ro=False):
            nonlocal _row
            tk.Label(body, text=label, bg=CBG, fg=CTX,
                     font=F_BODY, width=18, anchor="w").grid(
                row=_row, column=0, sticky="w", pady=4)
            if combo_vals is not None:
                w = ttk.Combobox(body, textvariable=var,
                                 values=combo_vals, state="readonly", width=22)
                w.grid(row=_row, column=1, sticky="w", pady=4)
            elif var is not None:
                e = field_entry(body, textvariable=var)
                if ro:
                    e.config(state="disabled",
                             disabledforeground=CMU, disabledbackground=CCA)
                e.grid(row=_row, column=1, sticky="ew", pady=4)
            _row += 1
            return var

        _row = 0

        # ── Business ──────────────────────────────────────────────────────
        _sec("Business Details")
        v_name   = tk.StringVar(value=g.get("name", ""))
        v_short  = tk.StringVar(value=g.get("short_name", ""))
        v_legal  = tk.StringVar(value=g.get("legal_name", ""))
        v_abn    = tk.StringVar(value=g.get("abn", ""))
        v_web    = tk.StringVar(value=g.get("website", ""))
        _row_f("Name *",        v_name)
        _row_f("Short Name",    v_short)
        tk.Label(body, text="Used in dropdowns and short references.",
                 bg=CBG, fg=CMU, font=(FAM, 7)).grid(
            row=_row-1, column=2, sticky="w", padx=6)
        _row_f("Legal Name",    v_legal)
        _row_f("ABN",           v_abn)
        _row_f("Website",       v_web)

        # ── Contact ───────────────────────────────────────────────────────
        _sec("Primary Contact")
        v_contact = tk.StringVar(value=g.get("contact_person", ""))
        v_role    = tk.StringVar(value=g.get("contact_role", ""))
        v_phone   = tk.StringVar(value=g.get("phone", ""))
        v_email   = tk.StringVar(value=g.get("email", ""))
        _row_f("Contact Person", v_contact)
        _row_f("Role / Title",   v_role)
        _row_f("Phone",          v_phone)
        _row_f("Email",          v_email)

        # ── Delivery address ──────────────────────────────────────────────
        _sec("Delivery Address")
        v_d1   = tk.StringVar(value=g.get("delivery_address1", ""))
        v_d2   = tk.StringVar(value=g.get("delivery_address2", ""))
        v_dc   = tk.StringVar(value=g.get("delivery_city", ""))
        v_ds   = tk.StringVar(value=g.get("delivery_state", ""))
        v_dp   = tk.StringVar(value=g.get("delivery_postcode", ""))
        v_dco  = tk.StringVar(value=g.get("delivery_country", "Australia"))
        _row_f("Address Line 1", v_d1)
        _row_f("Address Line 2", v_d2)
        _row_f("City",           v_dc)
        _row_f("State",          v_ds, combo_vals=_db.AU_STATES + ["Other"])
        _row_f("Postcode",       v_dp)
        _row_f("Country",        v_dco)

        # ── Billing address ───────────────────────────────────────────────
        _sec("Billing Address")
        v_same = tk.BooleanVar(value=bool(g.get("billing_same", True)))
        billing_frame = tk.Frame(body, bg=CBG)
        billing_frame.grid(row=_row, column=0, columnspan=2, sticky="ew")
        _row += 1

        v_b1   = tk.StringVar(value=g.get("billing_address1", ""))
        v_b2   = tk.StringVar(value=g.get("billing_address2", ""))
        v_bc   = tk.StringVar(value=g.get("billing_city", ""))
        v_bs   = tk.StringVar(value=g.get("billing_state", ""))
        v_bp   = tk.StringVar(value=g.get("billing_postcode", ""))
        v_bco  = tk.StringVar(value=g.get("billing_country", "Australia"))

        billing_fields_frame = tk.Frame(body, bg=CBG)
        billing_fields_frame.grid(row=_row, column=0, columnspan=2, sticky="ew")
        _row += 1
        billing_fields_frame.columnconfigure(1, weight=1)
        _bf_row = [0]

        def _brow(label, var, combo_vals=None):
            tk.Label(billing_fields_frame, text=label, bg=CBG, fg=CTX,
                     font=F_BODY, width=18, anchor="w").grid(
                row=_bf_row[0], column=0, sticky="w", pady=3)
            if combo_vals:
                ttk.Combobox(billing_fields_frame, textvariable=var,
                             values=combo_vals, state="readonly", width=22).grid(
                    row=_bf_row[0], column=1, sticky="w", pady=3)
            else:
                field_entry(billing_fields_frame, textvariable=var).grid(
                    row=_bf_row[0], column=1, sticky="ew", pady=3)
            _bf_row[0] += 1

        _brow("Address Line 1", v_b1)
        _brow("Address Line 2", v_b2)
        _brow("City",           v_bc)
        _brow("State",          v_bs, _db.AU_STATES + ["Other"])
        _brow("Postcode",       v_bp)
        _brow("Country",        v_bco)

        def _toggle_billing(*_):
            same = v_same.get()
            billing_fields_frame.grid_remove() if same else billing_fields_frame.grid()

        tk.Checkbutton(billing_frame, text="Same as delivery address",
                       variable=v_same, bg=CBG, fg=CTX, font=F_BODY,
                       selectcolor=CCA, activebackground=CBG,
                       command=_toggle_billing).pack(anchor="w")
        _toggle_billing()

        # ── Financial ──────────────────────────────────────────────
        _sec("Financial")
        v_terms = tk.StringVar(value=g.get("payment_terms", "Net 30"))
        v_curr  = tk.StringVar(value=g.get("currency", "AUD"))
        v_act   = tk.BooleanVar(value=bool(g.get("is_active", True)))
        _row_f("Payment Terms", v_terms,
               combo_vals=_db.PAYMENT_TERMS)
        _row_f("Currency",      v_curr,
               combo_vals=["AUD", "USD", "NZD", "GBP", "EUR"])
        # Active toggle
        tk.Label(body, text="Status", bg=CBG, fg=CTX,
                 font=F_BODY, width=18, anchor="w").grid(
            row=_row, column=0, sticky="w", pady=4)
        tk.Checkbutton(body, text="Active customer",
                       variable=v_act, bg=CBG, fg=CTX, font=F_BODY,
                       selectcolor=CCA, activebackground=CBG).grid(
            row=_row, column=1, sticky="w", pady=4)
        _row += 1

        # ── Notes ─────────────────────────────────────────────────────────
        _sec("Notes")
        tk.Label(body, text="Notes", bg=CBG, fg=CTX,
                 font=F_BODY, width=18, anchor="nw").grid(
            row=_row, column=0, sticky="nw", pady=4)
        txt_notes = tk.Text(body, height=3, width=36, wrap="word",
                            font=F_BODY, relief="solid", bd=1,
                            bg=CCA, fg=CTX, insertbackground=CTX)
        txt_notes.grid(row=_row, column=1, sticky="ew", pady=4)
        if cust and cust.get("notes"):
            txt_notes.insert("1.0", cust["notes"])
        _row += 1

        # ── Footer ────────────────────────────────────────────────────────
        foot = tk.Frame(dlg, bg=CBG, padx=16, pady=10)
        foot.pack(fill="x", side="bottom")
        err_lbl = tk.Label(foot, text="", bg=CBG, fg=CRD, font=F_SM)
        err_lbl.pack(side="left")

        def _save():
            name = v_name.get().strip()
            if not name:
                err_lbl.config(text="Customer name is required.")
                return
            err_lbl.config(text="Saving…")
            dlg.update_idletasks()

            billing_same = v_same.get()
            data = {
                "name":             name,
                "short_name":       v_short.get().strip(),
                "legal_name":       v_legal.get().strip(),
                "abn":              v_abn.get().strip(),
                "website":          v_web.get().strip(),
                "contact_person":   v_contact.get().strip(),
                "contact_role":     v_role.get().strip(),
                "phone":            v_phone.get().strip(),
                "email":            v_email.get().strip(),
                "delivery_address1": v_d1.get().strip(),
                "delivery_address2": v_d2.get().strip(),
                "delivery_city":    v_dc.get().strip(),
                "delivery_state":   v_ds.get().strip(),
                "delivery_postcode": v_dp.get().strip(),
                "delivery_country": v_dco.get().strip(),
                "billing_same":     billing_same,
                "billing_address1": (v_d1.get() if billing_same else v_b1.get()).strip(),
                "billing_address2": (v_d2.get() if billing_same else v_b2.get()).strip(),
                "billing_city":     (v_dc.get() if billing_same else v_bc.get()).strip(),
                "billing_state":    (v_ds.get() if billing_same else v_bs.get()).strip(),
                "billing_postcode": (v_dp.get() if billing_same else v_bp.get()).strip(),
                "billing_country":  (v_dco.get() if billing_same else v_bco.get()).strip(),
                "payment_terms":    v_terms.get(),
                "currency":         v_curr.get(),
                "is_active":        v_act.get(),
                "notes":            txt_notes.get("1.0", "end").strip(),
            }
            try:
                if is_new:
                    _db.create_customer(data)
                    action = "customer_created"
                else:
                    _db.update_customer(cust["id"], data)
                    action = "customer_updated"
                _db.log_action(action, f"Customer: {name}  ABN: {v_abn.get().strip()}")
                self.status_var.set(f"{'Created' if is_new else 'Updated'}: {name}")
                dlg.destroy()
                self._refresh_customers_list()
            except Exception as exc:
                err_lbl.config(text=f"Error: {exc}")

        flat_btn(foot, "Cancel",        dlg.destroy, bg=CNE, pady=6).pack(side="right", padx=(8, 0))
        flat_btn(foot, "Save Customer", _save,       bg=CGR, pady=6).pack(side="right")
        dlg.bind("<Escape>", lambda e: dlg.destroy())

    def _view_customer_orders(self):
        """Switch to Previous Orders tab pre-filtered to the selected customer."""
        cust = self._get_selected_customer()
        if cust is None:
            messagebox.showinfo("View Orders", "Select a customer first.")
            return
        self.search_var.set(cust.get("name", ""))
        self._show_tab("prev_orders")

    def _new_order_for_customer(self):
        """Start a new order with the selected customer pre-filled."""
        cust = self._get_selected_customer()
        if cust is None:
            messagebox.showinfo("New Order", "Select a customer first.")
            return
        # Clear the form, then populate with customer data
        for v in self.hvars.values():
            v.set("")
        self.hvars["Date Due"].set("ASAP")
        self.txt_header_notes.delete("1.0", "end")
        self._priority_var.set(False) if hasattr(self, "_priority_var") else None
        self._clear_all_field_errors()
        self._selected_customer_id = ""
        self.items = []
        self._refresh_items_tree()
        self._clear_draft()
        # Now populate customer fields
        self._pick_customer(cust)
        self._show_tab("new_order")
        self.status_var.set(f"New order started for {cust.get('name', '')}.")

    def _delete_customer(self):
        cust = self._get_selected_customer()
        if cust is None:
            messagebox.showinfo("Delete", "Select a customer first.")
            return
        if not (_db.is_ready() and _db.can_manage_customers()):
            messagebox.showinfo("Delete", "Managers or above can delete customers.")
            return
        name = cust.get("name", "")
        choice = messagebox.askyesnocancel(
            "Delete Customer",
            f"What would you like to do with '{name}'?\n\n"
            "• Yes = Mark as Inactive (keeps history, hides from lists)\n"
            "• No  = Permanently delete (cannot be undone)\n"
            "• Cancel = Do nothing")
        if choice is None:
            return
        try:
            if choice:
                # Mark inactive
                _db.update_customer(cust["id"], {"is_active": False})
                _db.log_action("customer_deactivated", f"Customer: {name}")
                self.status_var.set(f"'{name}' marked as inactive.")
            else:
                _db.delete_customer(cust["id"])
                _db.log_action("customer_deleted", f"Customer: {name}")
                self.status_var.set(f"Deleted: {name}")
            self._refresh_customers_list()
        except Exception as exc:
            messagebox.showerror("Error", f"Could not complete action:\n{exc}")

    # ── Stock Management tab ─────────────────────────────────────────────

    def _build_stock_tab(self):
        frm = tk.Frame(self.content, bg=CBG, padx=14, pady=12)
        frm.grid(row=0, column=0, sticky="nsew")
        frm.rowconfigure(1, weight=1)
        frm.columnconfigure(0, weight=1)
        self._tab_frames["stock"] = frm

        # ── Search / filter bar ───────────────────────────────────────────
        top = tk.Frame(frm, bg=CBG)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        tk.Label(top, text="Stock Management", bg=CBG, fg=CA,
                 font=F_TTL).pack(side="left", padx=(0, 20))

        tk.Label(top, text="Search:", bg=CBG, fg=CTX,
                 font=F_BOLD).pack(side="left", padx=(0, 6))
        self._stock_search_var = tk.StringVar()
        self._stock_search_var.trace_add("write", lambda *_: self._filter_stock_list())
        field_entry(top, textvariable=self._stock_search_var,
                    width=22).pack(side="left", padx=(0, 14))

        tk.Label(top, text="Type:", bg=CBG, fg=CTX,
                 font=F_BOLD).pack(side="left", padx=(0, 6))
        self._stock_type_var = tk.StringVar(value="All")
        type_cb = ttk.Combobox(top, textvariable=self._stock_type_var,
                               values=["All"] + _db.STOCK_PRODUCT_TYPES,
                               state="readonly", width=16)
        type_cb.pack(side="left", padx=(0, 14))
        self._stock_type_var.trace_add("write", lambda *_: self._filter_stock_list())

        tk.Label(top, text="Show:", bg=CBG, fg=CTX,
                 font=F_BOLD).pack(side="left", padx=(0, 6))
        self._stock_show_var = tk.StringVar(value="All")
        show_cb = ttk.Combobox(top, textvariable=self._stock_show_var,
                               values=["All", "Low Stock", "Out of Stock"],
                               state="readonly", width=12)
        show_cb.pack(side="left", padx=(0, 14))
        self._stock_show_var.trace_add("write", lambda *_: self._filter_stock_list())

        flat_btn(top, "↻ Refresh", self._refresh_stock_list,
                 bg=CNE, pady=5, padx=10, font=F_BODY).pack(side="right", padx=(8, 0))
        if _db.is_ready() and _db.can_manage_stock():
            flat_btn(top, "+ Add Item", lambda: self._open_stock_item_dialog(),
                     bg=CA, pady=5, padx=12, font=F_BOLD).pack(side="right")

        # ── Treeview ──────────────────────────────────────────────────────
        tbl_wrap = tk.Frame(frm, bg=CCA,
                            highlightbackground=CSP, highlightthickness=1)
        tbl_wrap.grid(row=1, column=0, sticky="nsew")
        tbl_wrap.rowconfigure(0, weight=1)
        tbl_wrap.columnconfigure(0, weight=1)

        scols = ("img", "name", "sku", "type", "unit", "on_hand", "minimum", "status", "location")
        self._stock_tree = ttk.Treeview(tbl_wrap, columns=scols,
                                        show="headings",
                                        style="TAF.Treeview",
                                        selectmode="browse")
        self._stock_tree.grid(row=0, column=0, sticky="nsew")

        s_col_defs = {
            "img":      ("📷",         36,  "center"),
            "name":     ("Name",       200, "w"),
            "sku":      ("SKU",         90, "w"),
            "type":     ("Type",       130, "w"),
            "unit":     ("Unit",        60, "center"),
            "on_hand":  ("On Hand",     80, "center"),
            "minimum":  ("Minimum",     80, "center"),
            "status":   ("Status",      90, "center"),
            "location": ("Location",   999, "w"),
        }
        for col, (hd, wd, anc) in s_col_defs.items():
            self._stock_tree.heading(col, text=hd,
                                     anchor="center" if anc == "center" else "w")
            self._stock_tree.column(col, width=wd, anchor=anc, minwidth=30,
                                    stretch=(col == "location"))

        self._stock_tree.tag_configure("ok",    background="#D4EDDA", foreground="#155724")
        self._stock_tree.tag_configure("low",   background="#FFF3CD", foreground="#856404")
        self._stock_tree.tag_configure("out",   background="#FDECEA", foreground="#B71C1C")
        self._stock_tree.tag_configure("even",  background=CRE)
        self._stock_tree.tag_configure("odd",   background=CCA)

        svsb = ttk.Scrollbar(tbl_wrap, orient="vertical",
                              command=self._stock_tree.yview)
        svsb.grid(row=0, column=1, sticky="ns")
        self._stock_tree.configure(yscrollcommand=svsb.set)
        self._stock_tree.bind("<Double-1>",
                              lambda e: self._open_stock_item_dialog(edit=True))

        # ── Bottom actions ────────────────────────────────────────────────
        bot = tk.Frame(frm, bg=CBG, pady=8)
        bot.grid(row=2, column=0, sticky="ew")

        flat_btn(bot, "📋 View Details / Edit",
                 lambda: self._open_stock_item_dialog(edit=True),
                 bg=CA, pady=7).pack(side="left", padx=(0, 8))
        flat_btn(bot, "± Adjust Stock",
                 self._adjust_stock_dialog,
                 bg=CA2, pady=7).pack(side="left", padx=(0, 8))
        flat_btn(bot, "🕐 Transaction History",
                 self._view_stock_history,
                 bg=CNE, pady=7).pack(side="left", padx=(0, 8))
        if _db.is_ready() and _db.can_manage_stock():
            flat_btn(bot, "🗑 Delete Item",
                     self._delete_stock_item,
                     bg=CRD, pady=7).pack(side="right")

        # Cache for the full stock list
        self._stock_data: list = []

    def _refresh_stock_list(self):
        """Fetch all stock items from DB and rebuild the list."""
        import queue as _q
        q = _q.Queue()

        def _work():
            try:
                items = _db.get_stock_items()
                q.put(("ok", items))
            except Exception as exc:
                q.put(("err", str(exc)))

        def _poll():
            try:
                while True:
                    kind, data = q.get_nowait()
                    if kind == "ok":
                        self._stock_data = data
                        self._filter_stock_list()
                        self._update_stock_badge()
                        return
                    else:
                        self.status_var.set(f"Stock fetch error: {data}")
                        return
            except _q.Empty:
                pass
            self.master.after(60, _poll)

        threading.Thread(target=_work, daemon=True).start()
        self.master.after(60, _poll)

    def _filter_stock_list(self):
        q      = self._stock_search_var.get().strip().lower()
        t_filt = self._stock_type_var.get()
        s_filt = self._stock_show_var.get()

        for iid in self._stock_tree.get_children():
            self._stock_tree.delete(iid)

        shown = []
        for item in self._stock_data:
            if q and not (
                q in (item.get("name") or "").lower()
                or q in (item.get("sku") or "").lower()
                or q in (item.get("location") or "").lower()
                or q in (item.get("description") or "").lower()
            ):
                continue
            if t_filt != "All" and item.get("product_type") != t_filt:
                continue
            on_hand = float(item.get("stock_on_hand", 0) or 0)
            minimum = float(item.get("minimum_on_hand", 0) or 0)
            if s_filt == "Low Stock" and not (0 < on_hand < minimum):
                continue
            if s_filt == "Out of Stock" and on_hand > 0:
                continue
            shown.append(item)

        for i, item in enumerate(shown):
            on_hand = float(item.get("stock_on_hand", 0) or 0)
            minimum = float(item.get("minimum_on_hand", 0) or 0)
            has_img = bool(item.get("image_url", "").strip())

            if on_hand <= 0:
                tag, status = "out", "❌ Out"
            elif minimum > 0 and on_hand < minimum:
                tag, status = "low", "⚠ Low"
            else:
                tag, status = ("even" if i % 2 == 0 else "odd"), "✅ OK"

            def _fmt(n):
                return str(int(n)) if n == int(n) else f"{n:.2f}".rstrip("0").rstrip(".")

            self._stock_tree.insert("", "end", iid=str(i), tags=(tag,), values=(
                "📷" if has_img else "—",
                item.get("name", ""),
                item.get("sku", "") or "—",
                item.get("product_type", ""),
                item.get("unit", "each"),
                _fmt(on_hand),
                _fmt(minimum) if minimum > 0 else "—",
                status,
                item.get("location", "") or "—",
            ))

        n_low = sum(1 for it in self._stock_data
                    if float(it.get("minimum_on_hand", 0) or 0) > 0
                    and float(it.get("stock_on_hand", 0) or 0) <
                        float(it.get("minimum_on_hand", 0) or 0))
        self.status_var.set(
            f"{len(shown)} item{'s' if len(shown) != 1 else ''} shown"
            + (f"  ·  {n_low} low/out" if n_low else ""))

    def _get_selected_stock(self) -> "dict | None":
        sel = self._stock_tree.selection()
        if not sel:
            return None
        idx = int(sel[0])
        # Rebuild the same filtered list order
        q      = self._stock_search_var.get().strip().lower()
        t_filt = self._stock_type_var.get()
        s_filt = self._stock_show_var.get()
        shown  = []
        for item in self._stock_data:
            if q and not (
                q in (item.get("name") or "").lower()
                or q in (item.get("sku") or "").lower()
                or q in (item.get("location") or "").lower()
                or q in (item.get("description") or "").lower()
            ):
                continue
            if t_filt != "All" and item.get("product_type") != t_filt:
                continue
            on_hand = float(item.get("stock_on_hand", 0) or 0)
            minimum = float(item.get("minimum_on_hand", 0) or 0)
            if s_filt == "Low Stock" and not (0 < on_hand < minimum):
                continue
            if s_filt == "Out of Stock" and on_hand > 0:
                continue
            shown.append(item)
        return shown[idx] if idx < len(shown) else None

    def _update_stock_badge(self):
        """Update the Stock tab button label with a low-stock count if needed."""
        try:
            n_low = sum(1 for it in self._stock_data
                        if float(it.get("minimum_on_hand", 0) or 0) > 0
                        and float(it.get("stock_on_hand", 0) or 0) <
                            float(it.get("minimum_on_hand", 0) or 0))
            lbl = "  📦  Stock  " if not n_low else f"  📦  Stock ({n_low} low)  "
            if btn := self._tab_buttons.get("stock"):
                btn.config(text=lbl, fg=CRD if n_low else CMU)
        except Exception:
            pass

    def _open_stock_item_dialog(self, edit: bool = False):
        """Open the Add / Edit stock item dialog."""
        item = self._get_selected_stock() if edit else None
        if edit and item is None:
            messagebox.showinfo("Edit", "Select a stock item first.")
            return

        is_manager = _db.is_ready() and _db.can_manage_stock()
        is_new     = item is None
        title      = "Add Stock Item" if is_new else ("Edit Stock Item" if is_manager else "View Stock Item")

        dlg = tk.Toplevel(self.master)
        dlg.title(title)
        dlg.transient(self.master)
        dlg.grab_set()
        dlg.configure(bg=CBG)
        dlg.resizable(True, True)
        W, H = 680, 620
        dlg.geometry(
            f"{W}x{H}+"
            f"{self.master.winfo_rootx()+self.master.winfo_width()//2-W//2}+"
            f"{self.master.winfo_rooty()+self.master.winfo_height()//2-H//2}")

        # Header
        hdr = tk.Frame(dlg, bg=CA, padx=16, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text=title, bg=CA, fg="white", font=F_BOLD).pack(anchor="w")
        if not is_new:
            tk.Label(hdr, text=item.get("name", ""), bg=CA, fg="#A9CCE3",
                     font=F_SM).pack(anchor="w")

        # Scrollable body
        body_outer = tk.Frame(dlg, bg=CBG)
        body_outer.pack(fill="both", expand=True)
        body_cv = tk.Canvas(body_outer, bg=CBG, highlightthickness=0)
        body_sb = ttk.Scrollbar(body_outer, orient="vertical", command=body_cv.yview)
        body_cv.configure(yscrollcommand=body_sb.set)
        body_sb.pack(side="right", fill="y")
        body_cv.pack(side="left", fill="both", expand=True)
        body = tk.Frame(body_cv, bg=CBG, padx=20, pady=14)
        _bw  = body_cv.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: body_cv.configure(scrollregion=body_cv.bbox("all")))
        body_cv.bind("<Configure>", lambda e: body_cv.itemconfig(_bw, width=e.width))
        def _mw(e): body_cv.yview_scroll(-1*(e.delta//120), "units")
        body_cv.bind("<Enter>", lambda e: body_cv.bind_all("<MouseWheel>", _mw))
        body_cv.bind("<Leave>", lambda e: body_cv.unbind_all("<MouseWheel>"))

        body.columnconfigure(1, weight=1)

        # ── Field helpers ─────────────────────────────────────────────────
        def _lbl(row, text):
            tk.Label(body, text=text, bg=CBG, fg=CTX, font=F_BODY,
                     width=16, anchor="w").grid(row=row, column=0, sticky="nw", pady=5)

        def _entry(row, var, ro=False):
            state = "disabled" if ro or not is_manager else "normal"
            e = field_entry(body, textvariable=var)
            e.grid(row=row, column=1, sticky="ew", pady=5)
            if ro or not is_manager:
                e.config(state="disabled", disabledforeground=CMU, disabledbackground=CCA)
            return e

        # Variables
        v_name   = tk.StringVar(value=item.get("name", "") if item else "")
        v_sku    = tk.StringVar(value=item.get("sku", "") if item else "")
        v_type   = tk.StringVar(value=item.get("product_type", _db.STOCK_PRODUCT_TYPES[0]) if item else _db.STOCK_PRODUCT_TYPES[0])
        v_unit   = tk.StringVar(value=item.get("unit", "each") if item else "each")
        v_on     = tk.StringVar(value=str(item.get("stock_on_hand", 0)) if item else "0")
        v_min    = tk.StringVar(value=str(item.get("minimum_on_hand", 0)) if item else "0")
        v_loc    = tk.StringVar(value=item.get("location", "") if item else "")
        v_sup    = tk.StringVar(value=item.get("supplier", "") if item else "")
        v_sup_em = tk.StringVar(value=item.get("supplier_email", "") if item else "")
        v_img    = tk.StringVar(value=item.get("image_url", "") if item else "")
        _local_img_path = [None]
        _img_widget     = [None]

        r = 0
        _lbl(r, "Name *")
        _entry(r, v_name); r += 1

        _lbl(r, "SKU / Part No.")
        _entry(r, v_sku); r += 1

        _lbl(r, "Product Type *")
        if is_manager:
            type_cb2 = ttk.Combobox(body, textvariable=v_type,
                                    values=_db.STOCK_PRODUCT_TYPES,
                                    state="readonly", width=24)
            type_cb2.grid(row=r, column=1, sticky="w", pady=5)
        else:
            _entry(r, v_type, ro=True)
        r += 1

        _lbl(r, "Unit")
        if is_manager:
            unit_cb = ttk.Combobox(body, textvariable=v_unit,
                                   values=_db.STOCK_UNITS, width=12)
            unit_cb.grid(row=r, column=1, sticky="w", pady=5)
        else:
            _entry(r, v_unit, ro=True)
        r += 1

        _lbl(r, "Stock on Hand")
        _entry(r, v_on, ro=not is_new); r += 1
        if not is_new and is_manager:
            tk.Label(body, text="  Use '± Adjust Stock' to change quantity on existing items.",
                     bg=CBG, fg=CMU, font=F_SM).grid(row=r-1, column=1, sticky="w", padx=(0, 0))

        _lbl(r, "Minimum on Hand")
        _entry(r, v_min); r += 1

        _lbl(r, "Location")
        _entry(r, v_loc); r += 1

        _lbl(r, "Supplier")
        _entry(r, v_sup); r += 1
        _lbl(r, "Supplier Email")
        _entry(r, v_sup_em); r += 1

        # Description
        _lbl(r, "Description")
        txt_desc = tk.Text(body, height=3, width=36, wrap="word",
                           font=F_BODY, relief="solid", bd=1,
                           bg=CCA, fg=CTX, insertbackground=CTX,
                           state="normal" if is_manager else "disabled")
        txt_desc.grid(row=r, column=1, sticky="ew", pady=5)
        if item and item.get("description"):
            txt_desc.insert("1.0", item["description"])
        r += 1

        # Notes
        _lbl(r, "Notes")
        txt_notes = tk.Text(body, height=2, width=36, wrap="word",
                            font=F_BODY, relief="solid", bd=1,
                            bg=CCA, fg=CTX, insertbackground=CTX,
                            state="normal" if is_manager else "disabled")
        txt_notes.grid(row=r, column=1, sticky="ew", pady=5)
        if item and item.get("notes"):
            txt_notes.insert("1.0", item["notes"])
        r += 1

        # Image
        _lbl(r, "Product Image")
        img_frame = tk.Frame(body, bg=CBG)
        img_frame.grid(row=r, column=1, sticky="ew", pady=5)

        img_preview = tk.Label(img_frame, text="No image", bg=CBG, fg=CMU,
                               font=F_SM, width=20, height=6,
                               relief="solid", bd=1, anchor="center")
        img_preview.pack(side="left", padx=(0, 8))
        _img_widget[0] = img_preview

        def _load_preview(url_or_path: str):
            try:
                if url_or_path.startswith("http"):
                    import urllib.request as _ur
                    import tempfile, os as _os
                    tmp = tempfile.NamedTemporaryFile(
                        delete=False, suffix=".png")
                    _ur.urlretrieve(url_or_path, tmp.name)
                    tmp.close()
                    src = tmp.name
                else:
                    src = url_or_path
                try:
                    from PIL import Image as _PILImg, ImageTk as _PILITk
                    pil = _PILImg.open(src)
                    pil.thumbnail((140, 120))
                    photo = _PILITk.PhotoImage(pil)
                except Exception:
                    photo = tk.PhotoImage(file=src)
                img_preview.config(image=photo, text="", width=140, height=120)
                img_preview._photo = photo  # prevent GC
            except Exception:
                img_preview.config(text="Preview\nunavailable")

        if item and item.get("image_url"):
            dlg.after(300, lambda: _load_preview(item["image_url"]))

        if is_manager:
            def _browse_image():
                path = filedialog.askopenfilename(
                    title="Select Product Image",
                    filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                               ("All files", "*.*")])
                if path:
                    _local_img_path[0] = path
                    v_img.set(path)
                    _load_preview(path)

            def _clear_image():
                _local_img_path[0] = None
                v_img.set("")
                img_preview.config(image="", text="No image")
                if hasattr(img_preview, "_photo"):
                    del img_preview._photo

            btn_col = tk.Frame(img_frame, bg=CBG)
            btn_col.pack(side="left", fill="y")
            flat_btn(btn_col, "Browse…", _browse_image,
                     bg=CA, pady=5, padx=10, font=F_SM).pack(anchor="w", pady=(0, 4))
            flat_btn(btn_col, "Clear",   _clear_image,
                     bg=CNE, pady=5, padx=10, font=F_SM).pack(anchor="w")
        r += 1

        # ── Footer ────────────────────────────────────────────────────────
        foot = tk.Frame(dlg, bg=CBG, padx=16, pady=10)
        foot.pack(fill="x", side="bottom")

        if not is_manager:
            tk.Label(foot, text="Read-only — Managers can edit stock items.",
                     bg=CBG, fg=CMU, font=F_SM).pack(side="left")
            flat_btn(foot, "Close", dlg.destroy, bg=CNE, pady=6).pack(side="right")
            return

        status_lbl = tk.Label(foot, text="", bg=CBG, fg=CRD, font=F_SM)
        status_lbl.pack(side="left")

        def _save():
            name = v_name.get().strip()
            if not name:
                status_lbl.config(text="Name is required.")
                return
            try:
                on_h = float(v_on.get().strip() or 0)
                min_h = float(v_min.get().strip() or 0)
            except ValueError:
                status_lbl.config(text="On Hand and Minimum must be numbers.")
                return

            status_lbl.config(text="Saving…")
            dlg.update_idletasks()

            data = {
                "name":             name,
                "sku":              v_sku.get().strip(),
                "product_type":     v_type.get(),
                "unit":             v_unit.get().strip() or "each",
                "stock_on_hand":    on_h,
                "minimum_on_hand":  min_h,
                "location":         v_loc.get().strip(),
                "supplier":         v_sup.get().strip(),
                "supplier_email":   v_sup_em.get().strip(),
                "description":      txt_desc.get("1.0", "end").strip(),
                "notes":            txt_notes.get("1.0", "end").strip(),
                "image_url":        item.get("image_url", "") if item else "",
            }

            try:
                if is_new:
                    new_item = _db.create_stock_item(data)
                    item_id  = new_item.get("id", "")
                else:
                    item_id = item["id"]
                    _db.update_stock_item(item_id, data)

                # Upload image if one was selected
                if _local_img_path[0] and item_id:
                    try:
                        url = _db.upload_stock_image(item_id, _local_img_path[0])
                        _db.update_stock_item(item_id, {"image_url": url})
                    except Exception as img_exc:
                        messagebox.showwarning(
                            "Image Upload",
                            f"Item saved but image upload failed:\n{img_exc}")

                _db.log_action(
                    "stock_created" if is_new else "stock_updated",
                    f"Item: {name}  Type: {v_type.get()}")
                self.status_var.set(
                    f"{'Created' if is_new else 'Updated'}: {name}")
                dlg.destroy()
                self._refresh_stock_list()
            except Exception as exc:
                status_lbl.config(text=f"Error: {exc}")

        flat_btn(foot, "Cancel", dlg.destroy, bg=CNE, pady=6).pack(side="right", padx=(8, 0))
        flat_btn(foot, "Save Item", _save, bg=CGR, pady=6).pack(side="right")
        dlg.bind("<Escape>", lambda e: dlg.destroy())

    def _adjust_stock_dialog(self):
        """Quick dialog to receive / use / count stock."""
        item = self._get_selected_stock()
        if item is None:
            messagebox.showinfo("Adjust Stock", "Select a stock item first.")
            return
        if not (_db.is_ready() and _db.current_user()):
            messagebox.showinfo("Adjust Stock", "You must be logged in.")
            return

        on_hand = float(item.get("stock_on_hand", 0) or 0)
        unit    = item.get("unit", "each")
        name    = item.get("name", "")

        dlg = tk.Toplevel(self.master)
        dlg.title("Adjust Stock")
        dlg.resizable(False, False)
        dlg.transient(self.master)
        dlg.grab_set()
        dlg.configure(bg=CBG)

        hdr = tk.Frame(dlg, bg=CA, padx=14, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Adjust Stock", bg=CA, fg="white", font=F_BOLD).pack(anchor="w")
        tk.Label(hdr, text=name, bg=CA, fg="#A9CCE3", font=F_SM).pack(anchor="w")

        body = tk.Frame(dlg, bg=CBG, padx=16, pady=14)
        body.pack(fill="both", expand=True)

        # Current stock display
        cur_row = tk.Frame(body, bg=CBG)
        cur_row.pack(fill="x", pady=(0, 12))
        tk.Label(cur_row, text="Current stock:", bg=CBG, fg=CTX, font=F_BODY).pack(side="left")
        def _fmt(n): return str(int(n)) if n == int(n) else f"{n:.3f}".rstrip("0")
        tk.Label(cur_row, text=f"  {_fmt(on_hand)} {unit}",
                 bg=CBG, fg=CA, font=F_BOLD).pack(side="left")

        # Transaction type
        tk.Label(body, text="Action:", bg=CBG, fg=CTX, font=F_BODY).pack(anchor="w")
        tx_var = tk.StringVar(value="receive")
        _TX = [
            ("receive",  "🟢  Receive stock (add)"),
            ("use",      "🔵  Use / Issue stock (subtract)"),
            ("count",    "🟡  Manual count (set exact quantity)"),
            ("writeoff", "🔴  Write-off / Loss (subtract)"),
        ]
        for val, label in _TX:
            tk.Radiobutton(body, text=label, variable=tx_var, value=val,
                           bg=CBG, fg=CTX, font=F_BODY,
                           selectcolor=CCA, activebackground=CBG,
                           relief="flat").pack(anchor="w", pady=1)

        # Quantity
        qty_row = tk.Frame(body, bg=CBG)
        qty_row.pack(fill="x", pady=(10, 4))
        qty_lbl = tk.Label(qty_row, text="Quantity:", bg=CBG, fg=CTX, font=F_BODY, width=10, anchor="w")
        qty_lbl.pack(side="left")
        qty_var = tk.StringVar(value="1")
        field_entry(qty_row, textvariable=qty_var, width=12).pack(side="left")
        tk.Label(qty_row, text=f"  {unit}", bg=CBG, fg=CMU, font=F_SM).pack(side="left")

        def _update_qty_lbl(*_):
            if tx_var.get() == "count":
                qty_lbl.config(text="New total:")
            else:
                qty_lbl.config(text="Quantity:")
        tx_var.trace_add("write", _update_qty_lbl)

        # Notes
        tk.Label(body, text="Notes (optional):", bg=CBG, fg=CTX, font=F_BODY).pack(anchor="w", pady=(8, 2))
        notes_txt = tk.Text(body, height=3, width=40, wrap="word",
                            font=F_BODY, relief="solid", bd=1,
                            bg=CCA, fg=CTX, insertbackground=CTX)
        notes_txt.pack(fill="x")

        foot = tk.Frame(dlg, bg=CBG, padx=14, pady=10)
        foot.pack(fill="x")
        err_lbl = tk.Label(foot, text="", bg=CBG, fg=CRD, font=F_SM)
        err_lbl.pack(side="left")

        def _confirm():
            try:
                qty = float(qty_var.get().strip())
                if qty < 0:
                    raise ValueError
            except ValueError:
                err_lbl.config(text="Enter a valid positive number.")
                return
            try:
                new_qty = _db.adjust_stock(
                    item["id"], tx_var.get(), qty,
                    notes_txt.get("1.0", "end").strip())
                def _fmt2(n): return str(int(n)) if n == int(n) else f"{n:.3f}".rstrip("0")
                self.status_var.set(
                    f"{name}: stock adjusted → {_fmt2(new_qty)} {unit}")
                dlg.destroy()
                self._refresh_stock_list()
            except Exception as exc:
                err_lbl.config(text=f"Error: {exc}")

        flat_btn(foot, "Cancel",  dlg.destroy, bg=CNE, pady=6).pack(side="right", padx=(8, 0))
        flat_btn(foot, "Confirm", _confirm,    bg=CGR, pady=6).pack(side="right")
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        W, H = 420, 440
        dlg.geometry(
            f"{W}x{H}+"
            f"{self.master.winfo_rootx()+self.master.winfo_width()//2-W//2}+"
            f"{self.master.winfo_rooty()+self.master.winfo_height()//2-H//2}")

    def _view_stock_history(self):
        """Show transaction history for the selected stock item."""
        item = self._get_selected_stock()
        if item is None:
            messagebox.showinfo("History", "Select a stock item first.")
            return

        dlg = tk.Toplevel(self.master)
        dlg.title(f"Transaction History — {item.get('name','')}")
        dlg.transient(self.master)
        dlg.grab_set()
        dlg.configure(bg=CBG)
        W, H = 700, 480
        dlg.geometry(
            f"{W}x{H}+"
            f"{self.master.winfo_rootx()+self.master.winfo_width()//2-W//2}+"
            f"{self.master.winfo_rooty()+self.master.winfo_height()//2-H//2}")

        hdr = tk.Frame(dlg, bg=CA, padx=14, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Transaction History", bg=CA, fg="white",
                 font=(FAM, 11, "bold")).pack(anchor="w")
        tk.Label(hdr, text=item.get("name", ""), bg=CA, fg="#A9CCE3",
                 font=F_SM).pack(anchor="w")

        wrap = tk.Frame(dlg, bg=CCA, padx=0, pady=0)
        wrap.pack(fill="both", expand=True, padx=14, pady=(10, 0))
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        h_cols = ("when", "action", "change", "after", "user", "notes")
        htree  = ttk.Treeview(wrap, columns=h_cols, show="headings",
                               style="TAF.Treeview", selectmode="browse")
        htree.grid(row=0, column=0, sticky="nsew")

        for col, hd, wd in [
            ("when",   "When",     155),
            ("action", "Action",   110),
            ("change", "Change",    90),
            ("after",  "After",     90),
            ("user",   "User",     120),
            ("notes",  "Notes",    999),
        ]:
            htree.heading(col, text=hd)
            htree.column(col, width=wd, anchor="center" if col in ("change","after") else "w",
                         stretch=(col == "notes"))

        hsb = ttk.Scrollbar(wrap, orient="vertical", command=htree.yview)
        hsb.grid(row=0, column=1, sticky="ns")
        htree.configure(yscrollcommand=hsb.set)
        htree.tag_configure("receive",  foreground="#155724")
        htree.tag_configure("use",      foreground="#004085")
        htree.tag_configure("writeoff", foreground="#B71C1C")
        htree.tag_configure("count",    foreground="#856404")

        loading = tk.Label(dlg, text="Loading…", bg=CBG, fg=CMU, font=F_SM)
        loading.pack()

        def _load():
            txns = _db.get_stock_transactions(item["id"])
            dlg.after(0, lambda: _populate(txns))

        def _populate(txns):
            loading.destroy()
            unit = item.get("unit", "each")
            for i, t in enumerate(txns):
                ts   = (t.get("created_at") or "")[:19].replace("T", " ")
                atype = t.get("transaction_type", "")
                delta = float(t.get("quantity_change", 0) or 0)
                after = float(t.get("quantity_after",  0) or 0)
                def _f(n):
                    sign = "+" if n >= 0 else ""
                    s = str(int(n)) if n == int(n) else f"{n:.3f}".rstrip("0")
                    return f"{sign}{s} {unit}"
                def _f2(n):
                    s = str(int(n)) if n == int(n) else f"{n:.3f}".rstrip("0")
                    return f"{s} {unit}"
                htree.insert("", "end", tags=(atype,), values=(
                    ts, atype.title(),
                    _f(delta), _f2(after),
                    t.get("username", ""),
                    t.get("notes", "") or "—",
                ))

        flat_btn(dlg, "Close", dlg.destroy,
                 bg=CNE, pady=6).pack(side="bottom", pady=8)
        threading.Thread(target=_load, daemon=True).start()

    def _delete_stock_item(self):
        item = self._get_selected_stock()
        if item is None:
            messagebox.showinfo("Delete", "Select a stock item first.")
            return
        if not (_db.is_ready() and _db.can_manage_stock()):
            messagebox.showinfo("Delete", "Managers or above can delete stock items.")
            return
        name = item.get("name", "")
        if not messagebox.askyesno(
                "Delete Stock Item",
                f"Permanently delete '{name}'?\n\n"
                "This will also delete all transaction history for this item.\n"
                "This cannot be undone."):
            return
        try:
            _db.delete_stock_item(item["id"])
            _db.log_action("stock_deleted", f"Item: {name}")
            self.status_var.set(f"Deleted: {name}")
            self._refresh_stock_list()
        except Exception as exc:
            messagebox.showerror("Error", f"Could not delete:\n{exc}")

    # ── Audit Log tab ─────────────────────────────────────────────────────

    def _build_audit_log_tab(self):
        frm = tk.Frame(self.content, bg=CBG, padx=14, pady=12)
        frm.grid(row=0, column=0, sticky="nsew")
        frm.rowconfigure(1, weight=1)
        frm.columnconfigure(0, weight=1)
        self._tab_frames["audit_log"] = frm

        hdr = tk.Frame(frm, bg=CBG)
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        tk.Label(hdr, text="Audit Log", bg=CBG, fg=CA, font=F_TTL).pack(side="left")
        flat_btn(hdr, "Refresh", self._refresh_audit_log,
                 bg=CNE, pady=5, padx=10, font=F_BODY).pack(side="right")

        tbl_wrap = tk.Frame(frm, bg=CCA,
                            highlightbackground=CSP, highlightthickness=1)
        tbl_wrap.grid(row=1, column=0, sticky="nsew")
        tbl_wrap.rowconfigure(0, weight=1)
        tbl_wrap.columnconfigure(0, weight=1)

        acols = ("when", "user", "action", "details")
        self.audit_tree = ttk.Treeview(tbl_wrap, columns=acols,
                                        show="headings",
                                        style="TAF.Treeview",
                                        selectmode="browse")
        self.audit_tree.grid(row=0, column=0, sticky="nsew")

        for col, hd, wd, anc in [
            ("when",    "When",    155, "center"),
            ("user",    "User",    140, "w"),
            ("action",  "Action",  160, "w"),
            ("details", "Details", 400, "w"),
        ]:
            self.audit_tree.heading(col, text=hd)
            self.audit_tree.column(col, width=wd, anchor=anc, minwidth=60,
                                   stretch=(col == "details"))
        self.audit_tree.tag_configure("even", background=CRE)
        self.audit_tree.tag_configure("odd",  background=CCA)

        avsb = ttk.Scrollbar(tbl_wrap, orient="vertical",
                              command=self.audit_tree.yview)
        avsb.grid(row=0, column=1, sticky="ns")
        self.audit_tree.configure(yscrollcommand=avsb.set)

    def _refresh_audit_log(self):
        import queue as _q
        q = _q.Queue()

        def _work():
            try:
                rows = _db.get_audit_log(500)
                q.put(("ok", rows))
            except Exception as exc:
                q.put(("error", str(exc)))

        def _poll():
            try:
                while True:
                    kind, payload = q.get_nowait()
                    if kind == "ok":
                        for iid in self.audit_tree.get_children():
                            self.audit_tree.delete(iid)
                        for i, row in enumerate(payload):
                            ts  = (row.get("created_at") or "")[:19].replace("T", " ")
                            tag = "even" if i % 2 == 0 else "odd"
                            self.audit_tree.insert("", "end", tags=(tag,), values=(
                                ts,
                                row.get("username", ""),
                                row.get("action", "").replace("_", " ").title(),
                                row.get("details", ""),
                            ))
                        return
                    else:
                        self.status_var.set(f"Audit log error: {payload}")
                        return
            except _q.Empty:
                pass
            self.master.after(50, _poll)

        threading.Thread(target=_work, daemon=True).start()
        self.master.after(50, _poll)

    # ── Settings tab ──────────────────────────────────────────────────────

    def _build_settings_tab(self):
        outer = tk.Frame(self.content, bg=CBG)
        outer.grid(row=0, column=0, sticky="nsew")
        self._tab_frames["settings"] = outer

        # ── Scrollable canvas wrapper ─────────────────────────────────────
        _cv = tk.Canvas(outer, bg=CBG, highlightthickness=0)
        _sb = ttk.Scrollbar(outer, orient="vertical", command=_cv.yview)
        _cv.configure(yscrollcommand=_sb.set)
        _sb.pack(side="right", fill="y")
        _cv.pack(side="left", fill="both", expand=True)
        frm = tk.Frame(_cv, bg=CBG, padx=20, pady=16)
        _win = _cv.create_window((0, 0), window=frm, anchor="nw")
        frm.bind("<Configure>", lambda e: _cv.configure(scrollregion=_cv.bbox("all")))
        _cv.bind("<Configure>", lambda e: _cv.itemconfig(_win, width=e.width))
        def _mw(e): _cv.yview_scroll(-1 * (e.delta // 120), "units")
        _cv.bind("<Enter>", lambda e: _cv.bind_all("<MouseWheel>", _mw))
        _cv.bind("<Leave>", lambda e: _cv.unbind_all("<MouseWheel>"))

        frm.columnconfigure(0, weight=1)

        # row 0 – title
        tk.Label(frm, text="Settings",
                 bg=CBG, fg=CA, font=(FAM, 13, "bold"),
                 anchor="w").grid(row=0, column=0, sticky="w", pady=(0, 12))

        # row 2 – Software Update  (always visible to everyone)
        upd_card = tk.Frame(frm, bg=CCA, bd=1, relief="solid", padx=16, pady=12)
        upd_card.grid(row=2, column=0, sticky="ew", pady=(12, 0))

        upd_top = tk.Frame(upd_card, bg=CCA)
        upd_top.pack(fill="x")
        tk.Label(upd_top, text="Software Update",
                 bg=CCA, fg=CA, font=F_SEC, anchor="w").pack(side="left")
        self._upd_version_lbl = tk.Label(upd_top,
                 text=f"Current version: {APP_VERSION}",
                 bg=CCA, fg=CMU, font=F_SM, anchor="e")
        self._upd_version_lbl.pack(side="right")

        self._upd_status_var = tk.StringVar(value="")
        tk.Label(upd_card, textvariable=self._upd_status_var,
                 bg=CCA, fg=CMU, font=F_SM, anchor="w").pack(anchor="w", pady=(2, 8))

        btn_row = tk.Frame(upd_card, bg=CCA)
        btn_row.pack(anchor="w")
        self._check_upd_btn = flat_btn(btn_row, "Check for Updates",
                                        self._check_update_manual, bg=CA, pady=6)
        self._check_upd_btn.pack(side="left")
        self._install_upd_btn = flat_btn(btn_row, "Update Now",
                                          lambda: self._do_update(self._pending_update),
                                          bg=CGR, pady=6)
        self._install_upd_btn.pack(side="left", padx=(8, 0))
        self._install_upd_btn.pack_forget()
        self._pending_update = None

        # row 3 – User Management (Managers and above only)
        if _db.is_ready() and _db.can_manage_roles():
            um_card = tk.Frame(frm, bg=CCA, bd=1, relief="solid",
                               padx=16, pady=12)
            um_card.grid(row=3, column=0, sticky="ew", pady=(12, 0))
            tk.Label(um_card, text="User Management",
                     bg=CCA, fg=CA, font=F_SEC, anchor="w").pack(anchor="w")
            tk.Label(um_card,
                     text="View all accounts, assign roles, edit profiles and create users.",
                     bg=CCA, fg=CMU, font=F_SM, anchor="w").pack(anchor="w", pady=(2, 8))
            flat_btn(um_card, "Open User Management",
                     self._open_user_management,
                     bg=CA, pady=6).pack(anchor="w")

        # ── Media Types card ──────────────────────────────────────────────
        card_o, card_b = card_frame(frm, title="Media Types")
        card_o.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        card_b.columnconfigure(0, weight=1)

        # Description
        tk.Label(card_b,
                 text="Add custom media types that will appear in the Filter Order dialog.\n"
                      "Built-in types (shown in grey) cannot be deleted.",
                 bg=CCA, fg=CMU, font=F_SM, justify="left", anchor="w",
                 ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        # Listbox + scrollbar
        lb_wrap = tk.Frame(card_b, bg=CSP)
        lb_wrap.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        self.media_lb = tk.Listbox(
            lb_wrap,
            font=F_BODY,
            bg=CCA, fg=CTX,
            selectbackground=CA, selectforeground="white",
            activestyle="none",
            relief="flat", bd=0,
            highlightthickness=0,
            height=14,
        )
        self.media_lb.pack(side="left", fill="both", expand=True, padx=1, pady=1)

        lb_sb = ttk.Scrollbar(lb_wrap, orient="vertical",
                               command=self.media_lb.yview)
        lb_sb.pack(side="right", fill="y")
        self.media_lb.configure(yscrollcommand=lb_sb.set)

        # Toolbar
        tb = tk.Frame(card_b, bg=CCA)
        tb.grid(row=2, column=0, sticky="w")

        flat_btn(tb, "+ Add Type",  self._add_media_type,
                 bg=CA,  pady=5, padx=10, font=F_BODY).pack(side="left", padx=(0, 6))
        flat_btn(tb, "Edit",        self._edit_media_type,
                 bg=CNE, pady=5, padx=10, font=F_BODY).pack(side="left", padx=(0, 6))
        flat_btn(tb, "Delete",      self._delete_media_type,
                 bg=CRD, pady=5, padx=10, font=F_BODY).pack(side="left", padx=(0, 6))
        flat_btn(tb, "Move Up",     lambda: self._move_media(-1),
                 bg=CNE, pady=5, padx=10, font=F_BODY).pack(side="left", padx=(0, 6))
        flat_btn(tb, "Move Down",   lambda: self._move_media(1),
                 bg=CNE, pady=5, padx=10, font=F_BODY).pack(side="left")

        self._refresh_media_list()

        # ── Local Storage ─────────────────────────────────────────────────
        ls_card = tk.Frame(frm, bg=CCA, bd=1, relief="solid", padx=16, pady=12)
        ls_card.grid(row=7, column=0, sticky="ew", pady=(12, 0))
        tk.Label(ls_card, text="Local Storage",
                 bg=CCA, fg=CA, font=F_SEC, anchor="w").pack(anchor="w")
        tk.Label(ls_card,
                 text="Delete all order PDFs and JSON files saved on this computer.\n"
                      "This does NOT delete anything from the shared database.",
                 bg=CCA, fg=CMU, font=F_SM, justify="left").pack(anchor="w", pady=(2, 8))
        self._local_storage_lbl = tk.StringVar(value=self._local_storage_info())
        tk.Label(ls_card, textvariable=self._local_storage_lbl,
                 bg=CCA, fg=CTX, font=F_BODY).pack(anchor="w", pady=(0, 8))
        flat_btn(ls_card, "🗑  Delete All Local Order Files",
                 self._delete_local_order_files,
                 bg=CRD, pady=6).pack(anchor="w")

        # ── Change Password ───────────────────────────────────────────────
        cp_card = tk.Frame(frm, bg=CCA, bd=1, relief="solid", padx=16, pady=12)
        cp_card.grid(row=6, column=0, sticky="ew", pady=(12, 0))
        tk.Label(cp_card, text="Change Password",
                 bg=CCA, fg=CA, font=F_SEC, anchor="w").pack(anchor="w")
        tk.Label(cp_card,
                 text="Change your own password without needing an email link.",
                 bg=CCA, fg=CMU, font=F_SM).pack(anchor="w", pady=(2, 8))
        cp_fields = tk.Frame(cp_card, bg=CCA)
        cp_fields.pack(anchor="w")
        self._cp_old = tk.StringVar(); self._cp_new = tk.StringVar(); self._cp_new2 = tk.StringVar()
        for lbl, var, row in [("Current password", self._cp_old, 0),
                               ("New password",     self._cp_new, 1),
                               ("Confirm new",      self._cp_new2, 2)]:
            tk.Label(cp_fields, text=lbl, bg=CCA, fg=CTX, font=F_BODY,
                     width=18, anchor="w").grid(row=row, column=0, sticky="w", pady=2)
            e = field_entry(cp_fields, textvariable=var, width=24)
            e.config(show="•")
            e.grid(row=row, column=1, sticky="w", pady=2, padx=(6, 0))
        self._cp_status = tk.StringVar()
        tk.Label(cp_card, textvariable=self._cp_status,
                 bg=CCA, fg=CRD, font=F_SM).pack(anchor="w", pady=(4, 4))
        flat_btn(cp_card, "Change Password", self._do_change_password,
                 bg=CA, pady=6).pack(anchor="w")

        # ── PDF File Naming ───────────────────────────────────────────────
        pn_card = tk.Frame(frm, bg=CCA, bd=1, relief="solid", padx=16, pady=12)
        pn_card.grid(row=9, column=0, sticky="ew", pady=(12, 0))
        tk.Label(pn_card, text="PDF File Naming",
                 bg=CCA, fg=CA, font=F_SEC, anchor="w").pack(anchor="w")
        tk.Label(pn_card,
                 text="Customise the filename given to generated order PDFs.\n"
                      "Available tokens:  {customer}  {order_no}  {date}  {date_due}  {type}",
                 bg=CCA, fg=CMU, font=F_SM, justify="left").pack(anchor="w", pady=(2, 8))

        pn_row = tk.Frame(pn_card, bg=CCA)
        pn_row.pack(anchor="w", fill="x")

        saved_template = self._settings.get("pdf_name_template", "{customer}_{order_no}_{date}")
        self._pdf_name_var = tk.StringVar(value=saved_template)
        pn_entry = field_entry(pn_row, textvariable=self._pdf_name_var, width=38)
        pn_entry.pack(side="left", padx=(0, 8))

        def _save_pdf_name():
            t = self._pdf_name_var.get().strip() or "{customer}_{order_no}_{date}"
            self._settings["pdf_name_template"] = t
            _save_settings(self._settings)
            self.status_var.set(f"PDF naming template saved: {t}")

        def _reset_pdf_name():
            default = "{customer}_{order_no}_{date}"
            self._pdf_name_var.set(default)
            self._settings["pdf_name_template"] = default
            _save_settings(self._settings)
            self.status_var.set("PDF naming reset to default.")

        flat_btn(pn_row, "Save",  _save_pdf_name,  bg=CGR, pady=4, padx=10, font=F_SM).pack(side="left", padx=(0, 6))
        flat_btn(pn_row, "Reset", _reset_pdf_name, bg=CNE, pady=4, padx=10, font=F_SM).pack(side="left")

        # Preview row
        pn_preview_var = tk.StringVar()
        tk.Label(pn_card, textvariable=pn_preview_var,
                 bg=CCA, fg=CMU, font=F_SM).pack(anchor="w", pady=(6, 0))

        def _update_preview(*_):
            tmpl = self._pdf_name_var.get().strip() or "{customer}_{order_no}_{date}"
            sample = {
                "Customer Name": "ABC Company",
                "Order Number":  "1234",
                "Date Ordered":  "04-06-25",
                "Date Due":      "ASAP",
            }
            try:
                preview = self._apply_pdf_name_template(sample, "filter")
            except Exception:
                preview = "—"
            pn_preview_var.set(f"Preview:  {preview}.pdf")

        self._pdf_name_var.trace_add("write", _update_preview)
        _update_preview()

        # ── Default Printer ───────────────────────────────────────────────
        pr_card = tk.Frame(frm, bg=CCA, bd=1, relief="solid", padx=16, pady=12)
        pr_card.grid(row=8, column=0, sticky="ew", pady=(12, 0))
        tk.Label(pr_card, text="Default Printer",
                 bg=CCA, fg=CA, font=F_SEC, anchor="w").pack(anchor="w")
        tk.Label(pr_card,
                 text="Choose which printer is used when you click 🖨 Print.\n"
                      "Leave blank to use your system default printer.",
                 bg=CCA, fg=CMU, font=F_SM, justify="left").pack(anchor="w", pady=(2, 8))

        pr_row = tk.Frame(pr_card, bg=CCA)
        pr_row.pack(anchor="w", fill="x")

        saved_printer = self._settings.get("default_printer", "")
        self._printer_var = tk.StringVar(value=saved_printer)
        self._printer_cb  = ttk.Combobox(pr_row, textvariable=self._printer_var,
                                          state="readonly", width=36)
        self._printer_cb.pack(side="left", padx=(0, 8))

        def _refresh_printers():
            try:
                import subprocess as _sp
                out = _sp.run(
                    ["powershell", "-NoProfile", "-Command",
                     "Get-Printer | Select-Object -ExpandProperty Name"],
                    capture_output=True, text=True, timeout=8
                )
                names = [p.strip() for p in out.stdout.splitlines() if p.strip()]
            except Exception:
                names = []
            values = ["(System Default)"] + names
            self._printer_cb.configure(values=values)
            cur = self._printer_var.get()
            if not cur or cur not in names:
                self._printer_cb.set("(System Default)")
            else:
                self._printer_cb.set(cur)

        flat_btn(pr_row, "↻ Refresh", _refresh_printers,
                 bg=CNE, pady=4, padx=10, font=F_SM).pack(side="left", padx=(0, 8))

        def _save_printer():
            sel = self._printer_var.get().strip()
            printer = "" if sel in ("", "(System Default)") else sel
            self._settings["default_printer"] = printer
            _save_settings(self._settings)
            self.status_var.set(
                f"Default printer set to: {printer or 'System Default'}")

        flat_btn(pr_row, "Save", _save_printer,
                 bg=CGR, pady=4, padx=10, font=F_SM).pack(side="left")

        # Load printers on first open
        self.master.after(300, _refresh_printers)

        # ── Appearance / Dark Mode ────────────────────────────────────────
        ap_card = tk.Frame(frm, bg=CCA, bd=1, relief="solid", padx=16, pady=12)
        ap_card.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        tk.Label(ap_card, text="Appearance",
                 bg=CCA, fg=CA, font=F_SEC, anchor="w").pack(anchor="w")
        is_dark = self._settings.get("dark_mode", False)
        tk.Label(ap_card,
                 text="Toggle between light and dark theme. The app will restart to apply the change.",
                 bg=CCA, fg=CMU, font=F_SM, anchor="w").pack(anchor="w", pady=(2, 8))
        mode_row = tk.Frame(ap_card, bg=CCA)
        mode_row.pack(anchor="w")
        mode_lbl = "🌙  Switch to Dark Mode" if not is_dark else "☀  Switch to Light Mode"
        self._dark_mode_btn = flat_btn(mode_row, mode_lbl, self._toggle_dark_mode,
                                       bg=CNE, pady=6, padx=14)
        self._dark_mode_btn.pack(side="left")
        cur_lbl = "Dark" if is_dark else "Light"
        self._dark_mode_cur_lbl = tk.Label(mode_row,
                                            text=f"  Current: {cur_lbl} Mode",
                                            bg=CCA, fg=CMU, font=F_SM)
        self._dark_mode_cur_lbl.pack(side="left", padx=(12, 0))

        # ── Low Stock Alert Thresholds (Manager+ only) ────────────────────
        if _db.is_ready() and _db.can_manage_stock_alerts():
            alert_outer = tk.Frame(frm, bg=CCA, bd=1, relief="solid",
                                   padx=16, pady=12)
            alert_outer.grid(row=4, column=0, sticky="ew", pady=(12, 0))
            tk.Label(alert_outer, text="Low Stock Alert Thresholds",
                     bg=CCA, fg=CA, font=F_SEC, anchor="w").pack(anchor="w")
            tk.Label(alert_outer,
                     text="Alert on the Dashboard if a media type is used more than N times this month.",
                     bg=CCA, fg=CMU, font=F_SM).pack(anchor="w", pady=(2, 8))
            self._alert_thresh_frame = tk.Frame(alert_outer, bg=CCA)
            self._alert_thresh_frame.pack(fill="x")
            self._refresh_alert_thresholds_ui()

    def _local_storage_info(self) -> str:
        """Return a human-readable summary of what's in the local orders folder."""
        try:
            if not ORDERS_DIR.exists():
                return "No local files found."
            files = list(ORDERS_DIR.iterdir())
            if not files:
                return "No local files found."
            total_bytes = sum(f.stat().st_size for f in files if f.is_file())
            mb = total_bytes / 1_048_576
            return f"{len(files)} files  ({mb:.1f} MB)  in {ORDERS_DIR}"
        except Exception:
            return str(ORDERS_DIR)

    def _delete_local_order_files(self):
        """Delete all files in the local orders folder (not the database)."""
        if not ORDERS_DIR.exists() or not any(ORDERS_DIR.iterdir()):
            messagebox.showinfo("Local Storage",
                "No local order files to delete.", parent=self.master)
            return
        files = [f for f in ORDERS_DIR.iterdir() if f.is_file()]
        if not messagebox.askyesno(
                "Delete Local Files",
                f"This will permanently delete {len(files)} file(s) from:\n"
                f"  {ORDERS_DIR}\n\n"
                "Orders in the database are NOT affected.\n\n"
                "Continue?",
                icon="warning", parent=self.master):
            return
        deleted, failed = 0, 0
        for f in files:
            try:
                f.unlink()
                deleted += 1
            except Exception:
                failed += 1
        # Also remove empty subdirs
        try:
            for d in ORDERS_DIR.iterdir():
                if d.is_dir():
                    try:
                        d.rmdir()
                    except Exception:
                        pass
        except Exception:
            pass
        msg = f"Deleted {deleted} file(s)."
        if failed:
            msg += f"  ({failed} could not be removed — they may be open.)"
        self.status_var.set(msg)
        if hasattr(self, "_local_storage_lbl"):
            self._local_storage_lbl.set(self._local_storage_info())
        messagebox.showinfo("Done", msg, parent=self.master)

    def _do_change_password(self):
        old  = self._cp_old.get()
        new1 = self._cp_new.get()
        new2 = self._cp_new2.get()
        if not old or not new1:
            self._cp_status.set("Please fill in all fields.")
            return
        if new1 != new2:
            self._cp_status.set("New passwords do not match.")
            return
        if len(new1) < 6:
            self._cp_status.set("New password must be at least 6 characters.")
            return
        self._cp_status.set("Changing…")
        self.update()
        import queue as _q
        q = _q.Queue()
        def _work():
            try:
                email = _db.current_email()
                _db.sign_in(email, old)          # verify current password
                _db.get_client().auth.update_user({"password": new1})
                q.put(("ok", None))
            except Exception as exc:
                q.put(("error", str(exc)))
        def _poll():
            try:
                while True:
                    kind, data = q.get_nowait()
                    if kind == "ok":
                        self._cp_status.set("Password changed successfully.")
                        self._cp_old.set(""); self._cp_new.set(""); self._cp_new2.set("")
                        # Update status label colour to green
                        for w in self._cp_status._tk.winfo_children() if hasattr(self._cp_status, '_tk') else []:
                            pass
                    else:
                        msg = str(data)
                        if "invalid" in msg.lower() or "credentials" in msg.lower():
                            msg = "Current password is incorrect."
                        self._cp_status.set(f"Error: {msg}")
                    return
            except _q.Empty:
                pass
            self.master.after(50, _poll)
        threading.Thread(target=_work, daemon=True).start()
        self.master.after(50, _poll)

    def _refresh_alert_thresholds_ui(self):
        frm = self._alert_thresh_frame
        for w in frm.winfo_children():
            w.destroy()
        try:
            existing = {a["media_type"]: a["threshold"] for a in _db.get_stock_alerts()}
        except Exception:
            existing = {}
        all_media = list(DEFAULT_MEDIA_TYPES) + list(self._custom_media)
        for mt in all_media:
            row_f = tk.Frame(frm, bg=CCA)
            row_f.pack(fill="x", pady=2)
            tk.Label(row_f, text=mt, bg=CCA, fg=CTX, font=F_BODY,
                     width=14, anchor="w").pack(side="left")
            var = tk.StringVar(value=str(existing.get(mt, "")))
            field_entry(row_f, textvariable=var, width=6).pack(side="left", padx=4)
            tk.Label(row_f, text="orders / month  (blank = no alert)",
                     bg=CCA, fg=CMU, font=F_SM).pack(side="left")
            def _save(mt=mt, var=var):
                val = var.get().strip()
                try:
                    if not val:
                        _db.delete_stock_alert(mt)
                    else:
                        n = int(val)
                        if n > 0:
                            _db.upsert_stock_alert(mt, n)
                except Exception:
                    pass
            flat_btn(row_f, "Save", _save, bg=CGR, pady=2,
                     padx=8, font=F_SM).pack(side="left", padx=6)

    def _refresh_media_list(self, _reload_db=True):
        """Reload custom media from DB then redraw the listbox."""
        if _reload_db and _db.is_ready() and _db.current_user():
            try:
                self._custom_media = _db.get_custom_media_types()
                self._settings["custom_media_types"] = self._custom_media
                _save_settings(self._settings)
            except Exception:
                pass  # fall back to locally cached list

        self.media_lb.delete(0, "end")
        for mt in DEFAULT_MEDIA_TYPES:
            self.media_lb.insert("end", f"  {mt}  (built-in)")
        for mt in self._custom_media:
            self.media_lb.insert("end", f"  {mt}")
        n_default = len(DEFAULT_MEDIA_TYPES)
        for i in range(n_default):
            self.media_lb.itemconfig(i, fg=CMU)

    def _get_selected_media_index(self):
        """Return selected listbox index, or None."""
        sel = self.media_lb.curselection()
        return sel[0] if sel else None

    def _selected_custom_index(self):
        """Return index into self._custom_media for selection, or None if built-in."""
        idx = self._get_selected_media_index()
        if idx is None:
            return None
        n = len(DEFAULT_MEDIA_TYPES)
        if idx < n:
            return None   # built-in — not editable
        return idx - n

    def _prompt_media_name(self, title="Media Type", initial="") -> "str | None":
        """Simple inline prompt dialog for a media type name."""
        dlg = tk.Toplevel(self.master)
        dlg.title(title)
        dlg.resizable(False, False)
        dlg.transient(self.master)
        dlg.grab_set()
        dlg.lift()
        dlg.configure(bg=CBG)

        # Header (top)
        hdr = tk.Frame(dlg, bg=CA, padx=14, pady=8)
        hdr.pack(fill="x", side="top")
        tk.Label(hdr, text=title, bg=CA, fg="white",
                 font=F_BOLD).pack(anchor="w")

        result = [None]

        def _ok():
            v = var.get().strip().upper()
            if not v:
                messagebox.showwarning("Empty", "Please enter a type name.", parent=dlg)
                return
            result[0] = v
            dlg.destroy()

        # Footer (bottom) — packed before body so it always gets space
        foot = tk.Frame(dlg, bg=CBG, padx=16, pady=12)
        foot.pack(fill="x", side="bottom")
        flat_btn(foot, "Cancel", dlg.destroy, bg=CNE, pady=6).pack(side="right", padx=(6, 0))
        flat_btn(foot, "Save",   _ok,         bg=CGR, pady=6).pack(side="right")

        # Body (fills middle)
        body = tk.Frame(dlg, bg=CBG, padx=16, pady=12)
        body.pack(fill="x", side="top")
        tk.Label(body, text="Type name:", bg=CBG, fg=CTX,
                 font=F_BODY).pack(anchor="w", pady=(0, 4))
        var = tk.StringVar(value=initial)
        ent = field_entry(body, textvariable=var, width=28)
        ent.pack(fill="x")
        ent.focus_set()
        ent.select_range(0, "end")
        dlg.bind("<Return>",  lambda e: _ok())
        dlg.bind("<Escape>",  lambda e: dlg.destroy())
        dlg.wait_window()
        return result[0]

    def _add_media_type(self):
        if _db.is_ready() and not _db.can_manage_media_types():
            messagebox.showwarning("No Permission",
                "Only Managers, Admins and Directors can add media types.")
            return
        name = self._prompt_media_name(title="Add Media Type")
        if name is None:
            return
        if name in self.all_media_types:
            messagebox.showwarning("Duplicate",
                f'"{name}" already exists in the media type list.')
            return
        if _db.is_ready() and _db.current_user():
            try:
                _db.add_media_type(name)
            except Exception as exc:
                messagebox.showerror("DB Error", f"Could not save to database:\n{exc}")
                return
        self._custom_media.append(name)
        self._persist_media()
        self._refresh_media_list(_reload_db=False)
        self.media_lb.see("end")
        self.status_var.set(f'Media type "{name}" added.')

    def _edit_media_type(self):
        if _db.is_ready() and not _db.can_manage_media_types():
            messagebox.showwarning("No Permission",
                "Only Managers, Admins and Directors can edit media types.")
            return
        ci = self._selected_custom_index()
        if ci is None:
            if self._get_selected_media_index() is not None:
                messagebox.showinfo("Built-in", "Built-in media types cannot be edited.")
            else:
                messagebox.showinfo("Edit", "Select a custom media type to edit.")
            return
        old = self._custom_media[ci]
        new = self._prompt_media_name(title="Edit Media Type", initial=old)
        if new is None or new == old:
            return
        if new in self.all_media_types and new != old:
            messagebox.showwarning("Duplicate",
                f'"{new}" already exists in the media type list.')
            return
        if _db.is_ready() and _db.current_user():
            try:
                _db.rename_media_type(old, new)
            except Exception as exc:
                messagebox.showerror("DB Error", f"Could not save to database:\n{exc}")
                return
        self._custom_media[ci] = new
        self._persist_media()
        self._refresh_media_list(_reload_db=False)
        self.status_var.set(f'Media type renamed to "{new}".')

    def _delete_media_type(self):
        if _db.is_ready() and not _db.can_manage_media_types():
            messagebox.showwarning("No Permission",
                "Only Managers, Admins and Directors can delete media types.")
            return
        ci = self._selected_custom_index()
        if ci is None:
            if self._get_selected_media_index() is not None:
                messagebox.showinfo("Built-in", "Built-in media types cannot be deleted.")
            else:
                messagebox.showinfo("Delete", "Select a custom media type to delete.")
            return
        name = self._custom_media[ci]
        if not messagebox.askyesno("Delete",
                f'Delete media type "{name}"?\n\n'
                "Existing orders that use this type will still open correctly,\n"
                "but new orders won't be able to select it."):
            return
        if _db.is_ready() and _db.current_user():
            try:
                _db.remove_media_type(name)
            except Exception as exc:
                messagebox.showerror("DB Error", f"Could not remove from database:\n{exc}")
                return
        self._custom_media.pop(ci)
        self._persist_media()
        self._refresh_media_list(_reload_db=False)
        self.status_var.set(f'Media type "{name}" deleted.')

    def _move_media(self, delta: int):
        ci = self._selected_custom_index()
        if ci is None:
            return
        new_ci = ci + delta
        if new_ci < 0 or new_ci >= len(self._custom_media):
            return
        self._custom_media[ci], self._custom_media[new_ci] = (
            self._custom_media[new_ci], self._custom_media[ci])
        if _db.is_ready() and _db.current_user():
            try:
                _db.reorder_media_types(self._custom_media)
            except Exception:
                pass
        self._persist_media()
        self._refresh_media_list(_reload_db=False)
        new_lb_idx = len(DEFAULT_MEDIA_TYPES) + new_ci
        self.media_lb.selection_clear(0, "end")
        self.media_lb.selection_set(new_lb_idx)
        self.media_lb.see(new_lb_idx)

    def _persist_media(self):
        self._settings["custom_media_types"] = self._custom_media
        _save_settings(self._settings)

    # ── Status bar ────────────────────────────────────────────────────────

    def _build_status_bar(self):
        bar = tk.Frame(self, bg=CCA, pady=4, padx=14,
                       highlightbackground=CSP, highlightthickness=1)
        bar.pack(fill="x", side="bottom")

        left = tk.Frame(bar, bg=CCA)
        left.pack(side="left")
        tk.Label(left, text="●", bg=CCA, fg=CGR,
                 font=(FAM, 8)).pack(side="left", padx=(0, 6))
        self.status_var = tk.StringVar(value="Ready")
        tk.Label(left, textvariable=self.status_var,
                 bg=CCA, fg=CMU, font=F_SM, anchor="w").pack(side="left")

        tk.Label(bar, text=f"V{APP_VERSION}", bg=CCA, fg=CMU,
                 font=F_SM).pack(side="right")

    # ═══════════════════════════════════════════════════════════════════════
    # New Order logic
    # ═══════════════════════════════════════════════════════════════════════

    _LABEL_WRAP_NOTE = "BLANK LABELS & Wrap in Clear Plastic"
    _LABEL_WRAP_TRIGGERS = {"JAF", "AES"}

    def _check_customer_note(self):
        """If customer name contains JAF or AES, auto-add the label/wrap note."""
        name = self.hvars["Customer Name"].get().upper()
        triggered = any(t in name for t in self._LABEL_WRAP_TRIGGERS)
        current   = self.txt_header_notes.get("1.0", "end").strip()
        has_note  = self._LABEL_WRAP_NOTE in current

        if triggered and not has_note:
            prefix = (current + "\n") if current else ""
            self.txt_header_notes.delete("1.0", "end")
            self.txt_header_notes.insert("1.0", prefix + self._LABEL_WRAP_NOTE)
        elif not triggered and has_note:
            # Remove the auto-note if the trigger word is removed
            updated = current.replace(self._LABEL_WRAP_NOTE, "").strip()
            self.txt_header_notes.delete("1.0", "end")
            if updated:
                self.txt_header_notes.insert("1.0", updated)

    # ── Validation ────────────────────────────────────────────────────────

    _REQUIRED_FIELDS = {
        "Customer Name": "Customer Name is required",
        "Order Number":  "Order Number is required",
        "Date Ordered":  "Date Ordered is required",
    }

    def _validate_header(self) -> bool:
        """
        Check required fields.  Any that are empty get a red highlight and
        label.  A summary banner appears below the card.
        Returns True only if everything is valid.
        """
        self._clear_all_field_errors()
        errors = []
        for key, msg in self._REQUIRED_FIELDS.items():
            if not self.hvars[key].get().strip():
                self._mark_field_error(key)
                errors.append(f"  ⚠  {msg}")

        if errors:
            self._validation_banner_lbl.config(text="\n".join(errors))
            self._validation_banner.pack(fill="x", pady=(4, 0), before=self.master)
            # Pack it above the priority row by re-inserting before pri_row sibling
            try:
                self._validation_banner.pack_forget()
                self._validation_banner.pack(fill="x", pady=(4, 0))
            except Exception:
                pass
            # Scroll the left panel so errors are visible
            try:
                self._hentries[next(iter(errors))].focus_set()
            except Exception:
                pass
            # Focus the first bad field
            for key in self._REQUIRED_FIELDS:
                if not self.hvars[key].get().strip():
                    try:
                        self._hentries[key].focus_set()
                    except Exception:
                        pass
                    break
        return not errors

    def _mark_field_error(self, key: str):
        """Highlight an entry and its label in red."""
        e = self._hentries.get(key)
        if e:
            e.config(bg="#FDECEC", highlightbackground=CRD, highlightthickness=1)
        lbl = self._hfield_labels.get(key)
        if lbl:
            lbl.config(fg=CRD, font=F_BOLD)

    def _clear_field_error(self, key: str):
        """Remove red highlight from a single field (restore normal field style)."""
        e = self._hentries.get(key)
        if e:
            e.config(bg=CFD, highlightbackground=CSP, highlightthickness=1)
        lbl = self._hfield_labels.get(key)
        if lbl:
            lbl.config(fg=CTX, font=F_BODY)
        # If all required fields now valid, hide the banner
        all_ok = all(
            self.hvars[k].get().strip()
            for k in self._REQUIRED_FIELDS
        )
        if all_ok and hasattr(self, "_validation_banner"):
            self._validation_banner.pack_forget()

    def _clear_all_field_errors(self):
        """Remove all validation highlights."""
        for key in self._REQUIRED_FIELDS:
            e = self._hentries.get(key)
            if e:
                e.config(bg=CFD, highlightbackground=CSP, highlightthickness=1)
            lbl = self._hfield_labels.get(key)
            if lbl:
                lbl.config(fg=CTX, font=F_BODY)
        if hasattr(self, "_validation_banner"):
            self._validation_banner.pack_forget()

    def _load_known_customers(self):
        """Fetch full customer records from the DB for autocomplete."""
        if not (_db.is_ready() and _db.current_user()):
            return
        def _work():
            try:
                records = _db.get_customers()
                self._customer_records = records
                # Keep the plain-name list for legacy compatibility
                self._known_customers = [c.get("name", "") for c in records]
            except Exception:
                try:
                    names = _db.get_known_customers()
                    self._known_customers  = names
                    self._customer_records = [{"name": n} for n in names]
                except Exception:
                    pass
        threading.Thread(target=_work, daemon=True).start()

    def _pick_customer(self, cust: dict):
        """Apply a selected customer record to the New Order form."""
        self.hvars["Customer Name"].set(cust.get("name", ""))
        # Auto-fill Attention with contact person if blank
        if not self.hvars["Attention"].get().strip():
            self.hvars["Attention"].set(cust.get("contact_person", ""))
        # Auto-fill Location with delivery city / state if blank
        if not self.hvars["Location"].get().strip():
            city  = cust.get("delivery_city", "")
            state = cust.get("delivery_state", "")
            loc   = ", ".join(p for p in [city, state] if p)
            if loc:
                self.hvars["Location"].set(loc)
        # Store the customer_id for order linking
        self._selected_customer_id = cust.get("id", "")
        self._close_ac_popup()

    def _customer_autocomplete(self):
        """Show a dropdown of matching customer records below the entry."""
        typed = self.hvars["Customer Name"].get().strip()
        self._close_ac_popup()
        if len(typed) < 2:
            return

        typed_up = typed.upper()
        # Search full customer records first; fall back to name-only list
        records  = self._customer_records or []
        if records:
            matches = [c for c in records if typed_up in (c.get("name") or "").upper()
                       or typed_up in (c.get("abn") or "").upper()
                       or typed_up in (c.get("contact_person") or "").upper()]
        else:
            matches = [{"name": n} for n in self._known_customers
                       if typed_up in n.upper()]

        if not matches:
            return
        # Don't show popup if the only match is an exact match already filled
        if (len(matches) == 1
                and matches[0].get("name", "").upper() == typed_up):
            return

        ent = getattr(self, "_customer_entry", None)
        if not ent:
            return

        ent.update_idletasks()
        x = ent.winfo_rootx()
        y = ent.winfo_rooty() + ent.winfo_height()
        w = max(ent.winfo_width(), 320)

        popup = tk.Toplevel(self.master)
        popup.overrideredirect(True)
        popup.configure(bg=CSP)
        row_h  = 28
        popup.geometry(f"{w}x{min(len(matches), 7) * row_h + 2}+{x}+{y}")
        popup.lift()
        self._ac_popup = popup

        lb = tk.Listbox(
            popup, font=F_BODY, bg=CCA, fg=CTX,
            selectbackground=CA, selectforeground="white",
            relief="flat", bd=0, highlightthickness=0,
            activestyle="none", height=min(len(matches), 7),
        )
        lb.pack(fill="both", expand=True, padx=1, pady=1)

        for c in matches:
            name  = c.get("name", "")
            city  = c.get("delivery_city", "")
            state = c.get("delivery_state", "")
            loc   = ", ".join(p for p in [city, state] if p)
            label = f"{name}  ·  {loc}" if loc else name
            lb.insert("end", f"  {label}")

        def _pick(evt=None):
            sel = lb.curselection()
            if sel:
                self._pick_customer(matches[sel[0]])
            self._close_ac_popup()

        lb.bind("<ButtonRelease-1>", _pick)
        lb.bind("<Return>",          _pick)
        ent.bind("<Escape>",   lambda e: self._close_ac_popup(), add="+")
        ent.bind("<FocusOut>", lambda e: self.master.after(150, self._close_ac_popup), add="+")
        popup.bind("<FocusOut>", lambda e: self.master.after(150, self._close_ac_popup))

    def _close_ac_popup(self):
        if self._ac_popup:
            try:
                self._ac_popup.destroy()
            except Exception:
                pass
            self._ac_popup = None

    # ── Draft auto-save ───────────────────────────────────────────────────

    def _schedule_draft_save(self):
        """Debounced: save draft 4 s after the last change."""
        if self._draft_save_id:
            try:
                self.master.after_cancel(self._draft_save_id)
            except Exception:
                pass
        self._draft_save_id = self.master.after(4000, self._save_draft)

    def _save_draft(self):
        """Write current form state to DRAFT_FILE."""
        self._draft_save_id = None
        try:
            header = {k: v.get() for k, v in self.hvars.items()}
            header["Notes"] = self.txt_header_notes.get("1.0", "end").strip()
            draft = {
                "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "header":   header,
                "items":    self.items,
            }
            DRAFT_FILE.write_text(
                json.dumps(draft, indent=2, default=str),
                encoding="utf-8")
        except Exception:
            pass

    def _clear_draft(self):
        """Delete the draft file (order was saved or explicitly discarded)."""
        self._draft_save_id = None
        try:
            if DRAFT_FILE.exists():
                DRAFT_FILE.unlink()
        except Exception:
            pass

    def _check_restore_draft(self):
        """On startup, offer to restore an unsaved draft if one exists."""
        if not DRAFT_FILE.exists():
            return
        try:
            draft = json.loads(DRAFT_FILE.read_text(encoding="utf-8"))
        except Exception:
            return

        h         = draft.get("header", {})
        items     = draft.get("items", [])
        saved_at  = draft.get("saved_at", "")
        customer  = h.get("Customer Name", "").strip()
        order_no  = h.get("Order Number", "").strip()
        n_items   = len(items)

        # Nothing worth restoring
        if not customer and not order_no and not items:
            self._clear_draft()
            return

        summary = []
        if customer: summary.append(f"Customer: {customer}")
        if order_no: summary.append(f"O/N: {order_no}")
        summary.append(f"{n_items} item{'s' if n_items != 1 else ''}")
        if saved_at: summary.append(f"Last saved: {saved_at.replace('T', ' ')}")

        if messagebox.askyesno(
                "Restore Unsaved Draft",
                "An unsaved order draft was found:\n\n"
                + "\n".join(summary)
                + "\n\nRestore it?"):
            for k, var in self.hvars.items():
                var.set(str(h.get(k, "")))
            notes_txt = h.get("Notes", "") or ""
            self.txt_header_notes.delete("1.0", "end")
            self.txt_header_notes.insert("1.0", notes_txt)
            for it in items:
                if "item_kind" not in it:
                    it["item_kind"] = "bag" if "product_type" in it else "filter"
            self.items = items
            self._refresh_items_tree()
            self._show_tab("new_order")
            self.status_var.set("Draft restored — continue editing your order.")
        else:
            self._clear_draft()

    # ── PDF naming template ───────────────────────────────────────────────

    def _apply_pdf_name_template(self, header: dict, order_type: str = "filter") -> str:
        """
        Build a safe PDF base filename from the template in settings.
        Tokens: {customer}, {order_no}, {date}, {date_due}, {type}
        """
        template = self._settings.get(
            "pdf_name_template", "{customer}_{order_no}_{date}").strip()
        if not template:
            template = "{customer}_{order_no}_{date}"

        def _safe(s: str) -> str:
            return "".join(c for c in (s or "")
                           if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")

        date_str = (header.get("Date Ordered") or "").replace("/", "-")
        due_str  = (header.get("Date Due") or "").replace("/", "-")
        type_str = {"bags": "Bags", "mixed": "Mixed", "filter": "Filter"}.get(
            order_type, "Filter")

        result = (template
                  .replace("{customer}", _safe(header.get("Customer Name", "")))
                  .replace("{order_no}", _safe(header.get("Order Number",  "")))
                  .replace("{date}",     _safe(date_str))
                  .replace("{date_due}", _safe(due_str))
                  .replace("{type}",     type_str))

        # Strip leading/trailing underscores and collapse double-underscores
        result = result.strip("_")
        while "__" in result:
            result = result.replace("__", "_")
        return result or "order"

    # ── Orders tree hover tooltip ─────────────────────────────────────────

    def _hide_order_tooltip(self):
        if self._tooltip_win:
            try:
                self._tooltip_win.destroy()
            except Exception:
                pass
            self._tooltip_win = None

    def _on_orders_tree_hover(self, event):
        """Show a tooltip with the latest note when hovering over an order row."""
        iid = self.orders_tree.identify_row(event.y)
        if not iid:
            self._hide_order_tooltip()
            return

        displayed = getattr(self, "_displayed_orders", [])
        try:
            idx = int(iid)
            row = displayed[idx] if idx < len(displayed) else None
        except (ValueError, IndexError):
            row = None

        if not row:
            self._hide_order_tooltip()
            return

        notes_list = row.get("notes_list") or []
        if not notes_list:
            self._hide_order_tooltip()
            return

        # Build tooltip text from the most recent note
        latest = notes_list[-1]
        ts     = latest.get("ts", "")
        author = latest.get("author", "")
        text   = latest.get("text", "")
        n_more = len(notes_list) - 1

        tip_lines = []
        if author or ts:
            tip_lines.append(f"📝  {author}  {ts}".strip())
        tip_lines.append(text[:200] + ("…" if len(text) > 200 else ""))
        if n_more > 0:
            tip_lines.append(f"  (+{n_more} more note{'s' if n_more != 1 else ''})")
        tip_text = "\n".join(tip_lines)

        # Reuse existing tooltip window if already showing same content
        if self._tooltip_win and getattr(self, "_tooltip_iid", None) == iid:
            return
        self._hide_order_tooltip()
        self._tooltip_iid = iid

        tip = tk.Toplevel(self.master)
        tip.overrideredirect(True)
        tip.configure(bg="#FFFDE7")
        tip.attributes("-topmost", True)
        tk.Label(tip, text=tip_text,
                 bg="#FFFDE7", fg="#2D3748",
                 font=(FAM, 9),
                 justify="left", anchor="w",
                 padx=10, pady=6,
                 relief="solid", bd=1,
                 wraplength=340).pack()

        # Position near cursor, nudged right and below
        x = self.master.winfo_rootx() + event.x_root - self.master.winfo_rootx() + 16
        y = self.master.winfo_rooty() + event.y_root - self.master.winfo_rooty() + 20
        # Use absolute screen coords
        tip.geometry(f"+{event.x_root + 16}+{event.y_root + 12}")
        self._tooltip_win = tip

    def _new_order(self):
        has_data = self.items or any(v.get() for v in self.hvars.values())
        if has_data:
            if not messagebox.askyesno(
                    "New Order", "Clear the current order and start fresh?"):
                return
        for v in self.hvars.values():
            v.set("")
        self.hvars["Date Due"].set("ASAP")
        self.txt_header_notes.delete("1.0", "end")
        if hasattr(self, "_priority_var"):
            self._priority_var.set(False)
        self._clear_all_field_errors()
        self._selected_customer_id = ""
        self.items = []
        self._refresh_items_tree()
        self._clear_draft()
        self.status_var.set("New order started.")

    def _add_filter_item(self):
        dlg = LineItemDialog(self.master, title="Add Filter Item",
                             media_types=self.all_media_types)
        self.master.wait_window(dlg)
        if dlg.result:
            dlg.result["item_kind"] = "filter"
            self.items.append(dlg.result)
            self._refresh_items_tree()
            n = len(self.items)
            self.status_var.set(f"Filter item added — {n} item{'s' if n != 1 else ''} total.")

    def _add_bag_item(self):
        dlg = BagLineItemDialog(self.master, title="Add Bag / Roll Item",
                                media_types=self.all_media_types)
        self.master.wait_window(dlg)
        if dlg.result:
            dlg.result["item_kind"] = "bag"
            self.items.append(dlg.result)
            self._refresh_items_tree()
            n = len(self.items)
            self.status_var.set(f"Bag item added — {n} item{'s' if n != 1 else ''} total.")

    def _open_compressor_presets(self):
        dlg = CompressorFilterDialog(self.master)
        self.master.wait_window(dlg)
        if not dlg.result:
            return

        for it in dlg.result["items"]:
            self.items.append(it)

        # Only set Job if one was returned
        job = dlg.result.get("job", "")
        if job:
            self.hvars["Job"].set(job)

        # Set Notes based on what the preset returned
        frame_notes = dlg.result.get("notes", "")
        if frame_notes:
            # GD packs have a job name — prefix the housing line
            if job:
                full_note = f"Housing: {job}\n{frame_notes}"
            else:
                # Sigrist / no-job presets — use the note directly
                full_note = frame_notes
            self.txt_header_notes.delete("1.0", "end")
            self.txt_header_notes.insert("1.0", full_note)

        self._refresh_items_tree()
        n = len(self.items)
        self.status_var.set(
            f"Dedicated filter preset applied — {n} item{'s' if n != 1 else ''} total.")

    def _get_selected_index(self) -> "int | None":
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _edit_item(self):
        idx = self._get_selected_index()
        if idx is None:
            messagebox.showinfo("Edit", "Select a line item to edit first.")
            return
        item = self.items[idx]
        if item.get("item_kind") == "bag":
            dlg = BagLineItemDialog(self.master, title="Edit Bag / Roll Item",
                                    initial=item,
                                    media_types=self.all_media_types)
        else:
            dlg = LineItemDialog(self.master, title="Edit Filter Item",
                                 initial=item,
                                 media_types=self.all_media_types)
        self.master.wait_window(dlg)
        if dlg.result:
            dlg.result["item_kind"] = item.get("item_kind", "filter")
            self.items[idx] = dlg.result
            self._refresh_items_tree()
            self.tree.selection_set(str(idx))
            self.status_var.set("Line item updated.")

    def _delete_item(self):
        idx = self._get_selected_index()
        if idx is None:
            messagebox.showinfo("Delete", "Select a line item to delete first.")
            return
        if not messagebox.askyesno("Delete Item", "Delete the selected line item?"):
            return
        self.items.pop(idx)
        self._refresh_items_tree()
        self.status_var.set("Line item deleted.")

    def _duplicate_item(self):
        idx = self._get_selected_index()
        if idx is None:
            messagebox.showinfo("Duplicate", "Select a line item to duplicate.")
            return
        self.items.insert(idx + 1, dict(self.items[idx]))
        self._refresh_items_tree()
        self.tree.selection_set(str(idx + 1))
        self.status_var.set("Line item duplicated.")

    def _move_item(self, delta: int):
        idx = self._get_selected_index()
        if idx is None:
            return
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= len(self.items):
            return
        self.items[idx], self.items[new_idx] = self.items[new_idx], self.items[idx]
        self._refresh_items_tree()
        self.tree.selection_set(str(new_idx))

    def _refresh_items_tree(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for i, item in enumerate(self.items):
            kind = item.get("item_kind", "filter")
            if kind == "bag":
                pt    = item.get("product_type", "")
                qty   = item.get("quantity", "")
                media = item.get("media", "")
                size  = item_summary_short(item)
                if pt == "Media Roll":
                    size = f"{item.get('roll_width','')}×{item.get('roll_length','')}"
                opts = []
                if item.get("on_wire"):      opts.append("Wire")
                if item.get("gelled"):       opts.append("Gelled")
                if item.get("special_size"): opts.append("Special")
                if item.get("label_suffix"): opts.append(item["label_suffix"])
                opt_str  = ", ".join(opts) if opts else "—"
                notes    = (item.get("notes", "") or "")[:140]
                kind_lbl = "Bag/Roll"
                tag      = "bag_e" if i % 2 == 0 else "bag_o"
            else:
                qty   = item.get("Quantity", "")
                pt    = item.get("Filter Type", "")
                s     = item.get("Short",   "")
                l     = item.get("Long",    "")
                ch    = item.get("Channel", "")
                size  = f"{s}×{l}×{ch}" if (s or l or ch) else "—"
                media = item.get("Media Type", "")
                flags = []
                if item.get("Pleat Insert"):        flags.append("Pleat")
                if item.get("Header"):              flags.append("Header")
                if item.get("Use Stock V-form"):    flags.append("Stock V")
                if item.get("Use Stock Flyscreen"): flags.append("Stock FS")
                opt_str  = ", ".join(flags) if flags else "—"
                _pg_job  = item.get("item_job", "") or ""
                _pg_note = (item.get("Notes", "") or "")
                notes    = (f"[JOB: {_pg_job}] " if _pg_job else "") + _pg_note
                notes    = notes[:140]
                kind_lbl = "Filter"
                tag      = "even" if i % 2 == 0 else "odd"

            _kb = _type_badge(kind_lbl)
            self.tree.insert("", "end", iid=str(i), tags=(tag,),
                text=("" if _kb else kind_lbl), image=(_kb or ""),
                values=(qty, pt, size, media, opt_str, notes))
        n = len(self.items)
        self._items_card.set_header_right(f"{n} item{'s' if n != 1 else ''}")
        self._schedule_draft_save()

    def _collect_header(self) -> dict:
        header = {k: v.get().strip() for k, v in self.hvars.items()}
        header["Notes"]       = self.txt_header_notes.get("1.0", "end").strip()
        header["customer_id"] = getattr(self, "_selected_customer_id", "")
        return header

    @staticmethod
    def _merge_pdfs(pdf_paths: list, out_path: str) -> bool:
        """Merge a list of PDF file paths into one. Returns True on success."""
        return _ProgressDialog._merge(pdf_paths, out_path)

    def _generate(self):
        # ── Validate required fields first ────────────────────────────────
        if not self._validate_header():
            self._show_tab("new_order")   # make sure we're on the right tab
            return
        if not self.items:
            messagebox.showwarning("No Items", "Add at least one item before generating.")
            return
        header = self._collect_header()
        if _db.is_ready() and _db.current_user():
            header["Created By"] = _db.current_full_name() or _db.current_username() or ""
        header["priority"] = bool(getattr(self, "_priority_var", None) and self._priority_var.get())

        ORDERS_DIR.mkdir(parents=True, exist_ok=True)

        # Ensure every stepped filter carries the *STEPPED FILTER* customer note
        # (covers items loaded/duplicated from older orders too).
        for _it in self.items:
            apply_stepped_filter_note(_it)

        filter_items = [i for i in self.items if i.get("item_kind", "filter") != "bag"]
        bag_items    = [i for i in self.items if i.get("item_kind") == "bag"]
        total        = len(self.items)
        n_filter     = len(filter_items)
        bag_start    = n_filter + 1

        has_filter = bool(filter_items)
        has_bag    = bool(bag_items)
        if has_filter and has_bag:
            order_type = "mixed"
        elif has_bag:
            order_type = "bags"
        else:
            order_type = "filter"

        base = self._apply_pdf_name_template(header, order_type)

        prog = _ProgressDialog(self.master, order_type)
        self.status_var.set("Generating output…")

        # Snapshot of items captured now (immutable inside thread)
        all_items        = list(self.items)
        custom_media     = list(self._custom_media)
        service          = self.service

        def _worker():
            pdf_paths = []
            errors    = []

            # ── Step: build + export (parallel for mixed orders) ──────────
            if order_type == "mixed":
                # Run filter Excel and bag Word generation simultaneously;
                # each spawns its own PowerShell COM process → real speedup.
                prog.advance("Building filter worksheets & bag docket in parallel…")

                def _do_filter():
                    return service.create_order(
                        header, filter_items, persist_json=False,
                        extra_media_types=custom_media, auto_open=False,
                        page_start=1, grand_total=total)

                def _do_bags():
                    docx_p = str(ORDERS_DIR / f"{base}_bags.docx")
                    return generate_bag_docket(
                        header, bag_items, docx_p, auto_open=False,
                        item_start=bag_start, grand_total=total)

                with ThreadPoolExecutor(max_workers=2) as pool:
                    fut_f = pool.submit(_do_filter)
                    fut_b = pool.submit(_do_bags)

                    prog.advance("Exporting PDFs…")

                    try:
                        r = fut_f.result()
                        p = r.get("output_path", "")
                        if p:
                            pdf_paths.append(p)
                    except Exception as exc:
                        errors.append(f"Filter worksheets: {exc}")

                    try:
                        p = fut_b.result()
                        if p:
                            pdf_paths.append(p)
                    except Exception as exc:
                        errors.append(f"Bag docket: {exc}")

            else:
                # ── Filter-only ──────────────────────────────────────────
                if has_filter:
                    prog.advance("Building filter worksheets…")
                    try:
                        r = service.create_order(
                            header, filter_items, persist_json=False,
                            extra_media_types=custom_media, auto_open=False,
                            page_start=1, grand_total=total)
                        prog.advance("Exporting to PDF…")
                        p = r.get("output_path", "")
                        if p:
                            pdf_paths.append(p)
                    except Exception as exc:
                        errors.append(f"Filter worksheets: {exc}")

                # ── Bag-only ─────────────────────────────────────────────
                if has_bag:
                    prog.advance("Building bag / roll docket…")
                    try:
                        docx_p = str(ORDERS_DIR / f"{base}_bags.docx")
                        prog.advance("Exporting to PDF…")
                        p = generate_bag_docket(
                            header, bag_items, docx_p, auto_open=False,
                            item_start=bag_start, grand_total=total)
                        if p:
                            pdf_paths.append(p)
                    except Exception as exc:
                        errors.append(f"Bag docket: {exc}")

            # ── Merge PDFs ────────────────────────────────────────────────
            real_pdfs = [p for p in pdf_paths
                         if str(p).lower().endswith(".pdf") and os.path.exists(p)]

            if len(real_pdfs) > 1:
                prog.advance("Merging PDFs…")
                merged = str(ORDERS_DIR / f"{base}_order.pdf")
                if _ProgressDialog._merge(real_pdfs, merged):
                    opened = merged
                else:
                    opened = " + ".join(real_pdfs)
            elif real_pdfs:
                opened = real_pdfs[0]
            elif pdf_paths:
                opened = " + ".join(pdf_paths)
            else:
                opened = ""

            # ── Save JSON + Database ───────────────────────────────────────
            prog.advance("Saving order…")
            json_path = None
            try:
                json_path = service.save_order_json(header, all_items)
            except Exception as exc:
                errors.append(f"JSON save: {exc}")

            if _db.is_ready() and _db.current_user():
                try:
                    _db.save_order(header, all_items, order_type)
                    _db.log_action("order_created",
                        f"Customer: {header.get('Customer Name','')}  "
                        f"O/N: {header.get('Order Number','')}  "
                        f"Type: {order_type}  Items: {len(all_items)}")
                except Exception as exc:
                    errors.append(f"Database save failed: {exc}\n\nThe order was saved locally but not to the shared database.")

            prog.advance("Done!")

            # ── Hand results back to the main thread ──────────────────────
            prog.after(0, lambda: _finish(opened, json_path, errors,
                                          real_pdfs, pdf_paths))

        def _finish(opened, json_path, errors, real_pdfs, pdf_paths):
            prog.close()

            # Collect the PDF(s) to send to the printer. We no longer open the
            # PDF on generation — it's generated (and saved) then printed
            # automatically, same routing the Print button uses.
            to_print = []
            if len(real_pdfs) > 1:
                merged = str(ORDERS_DIR / f"{base}_order.pdf")
                to_print = [merged] if os.path.exists(merged) else list(real_pdfs)
            elif real_pdfs:
                to_print = [real_pdfs[0]]
            elif pdf_paths:
                to_print = [p for p in pdf_paths if os.path.exists(p)]

            if errors:
                messagebox.showerror("Errors", "\n\n".join(errors))

            if opened or json_path:
                self._clear_draft()
                # New order created — force Previous Orders + Dashboard to reload
                # next time they're shown (freshness cache invalidation).
                self._tab_loaded.pop("prev_orders", None)
                self._tab_loaded.pop("dashboard", None)
                self._all_orders_data = []
                msg = f"Order PDF:\n  {opened}" if opened else ""
                if json_path:
                    msg += (("\n\n" if msg else "") + f"Order saved:\n  {json_path}")

                # Send to the printer on a background thread so the UI stays
                # responsive while the job spools (printing can take seconds).
                if to_print:
                    self.status_var.set("Order generated — sending to printer…")

                    def _print_worker():
                        perr = ""
                        for p in to_print:
                            perr = self._print_file(p)
                            if perr:
                                break

                        def _done():
                            if perr:
                                messagebox.showerror(
                                    "Print Error",
                                    f"The order was generated and saved, but "
                                    f"printing failed:\n{perr}")
                                self.status_var.set("Order generated — printing failed.")
                            else:
                                self.status_var.set("Order generated and sent to printer.")
                        self.master.after(0, _done)

                    threading.Thread(target=_print_worker, daemon=True).start()
                else:
                    self.status_var.set("Order generated.")

                messagebox.showinfo("Done", msg)

        threading.Thread(target=_worker, daemon=True).start()

    def _load_json(self):
        fp = filedialog.askopenfilename(
            title="Select Order JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if fp:
            self._load_from_path(Path(fp))

    def _load_from_path(self, path: Path):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            header  = payload.get("header", {})
            items   = payload.get("items",  [])
        except Exception as exc:
            messagebox.showerror("Load Error", f"Could not load JSON:\n{exc}")
            return
        # Back-compat: items without item_kind were all filter items
        for it in items:
            if "item_kind" not in it:
                # Detect bag items by the presence of bag-specific keys
                if "product_type" in it:
                    it["item_kind"] = "bag"
                else:
                    it["item_kind"] = "filter"
        for k, var in self.hvars.items():
            var.set(str(header.get(k, "")))
        self.txt_header_notes.delete("1.0", "end")
        self.txt_header_notes.insert("1.0", header.get("Notes", "") or "")
        self.items = items
        self._refresh_items_tree()
        self._show_tab("new_order")
        self.status_var.set(f"Loaded: {path.name}")

    # ═══════════════════════════════════════════════════════════════════════
    # Previous Orders logic
    # ═══════════════════════════════════════════════════════════════════════

    def _scan_local_orders(self) -> list:
        """Return order-summary dicts from the local orders/ directory."""
        if not ORDERS_DIR.exists():
            return []
        rows = []
        for p in sorted(ORDERS_DIR.glob("*.json"),
                        key=lambda f: f.stat().st_mtime,
                        reverse=True):
            try:
                payload = json.loads(p.read_text(encoding="utf-8"))
                h     = payload.get("header", {})
                otype = payload.get("order_type", "filter")
                rows.append({
                    "source":       "local",
                    "order_type":   otype,
                    "customer":     h.get("Customer Name", ""),
                    "order_no":     h.get("Order Number",  ""),
                    "date_ordered": h.get("Date Ordered",  ""),
                    "date_due":     h.get("Date Due",      ""),
                    "n_items":      len(payload.get("items", [])),
                    "created_by":   "local",
                    "path":         p,
                    "filename":     p.name,
                    "db_id":        None,
                    "db_header":    None,
                    "db_items":     None,
                })
            except Exception:
                pass
        return rows

    def _scan_orders(self) -> list:
        """Return combined order list: DB (all users) + local fallback."""
        rows = []

        # ── Database orders (from all users) ──────────────────────────────
        if _db.is_ready() and _db.current_user():
            try:
                db_rows = _db.get_all_orders()
                for r in db_rows:
                    rows.append({
                        "source":       "db",
                        "order_type":   r.get("order_type", "filter"),
                        "customer":     r.get("customer_name", ""),
                        "order_no":     r.get("order_number", ""),
                        "date_ordered": r.get("date_ordered", ""),
                        "date_due":     r.get("date_due", ""),
                        "n_items":      len(r.get("items") or []),
                        "created_by":   r.get("full_name") or r.get("username") or r.get("user_email", ""),
                    "created_by_role": r.get("created_by_role", "Employee"),
                    "user_id":      r.get("user_id", ""),
                        "path":         None,
                        "filename":     "database",
                        "db_id":        r.get("id"),
                        "db_header":    r.get("header") or {},
                        "db_items":     r.get("items") or [],
                        "priority":          bool((r.get("header") or {}).get("priority", False)),
                        "status":            (r.get("header") or {}).get("status", "Pending") or "Pending",
                        "notes_list":        (r.get("header") or {}).get("order_notes") or [],
                        "notes_count":       len((r.get("header") or {}).get("order_notes") or []),
                    })
            except Exception as exc:
                self.status_var.set(f"DB fetch error: {exc}")

        # ── Local orders (this machine only, fallback) ─────────────────────
        local = self._scan_local_orders()
        # Avoid showing duplicates: skip local files whose order_no already
        # appears in the DB results.
        db_order_nos = {r["order_no"] for r in rows if r["source"] == "db"}
        for row in local:
            if row["order_no"] and row["order_no"] in db_order_nos:
                continue
            rows.append(row)

        return rows

    def _refresh_orders_list(self):
        import queue as _queue
        self.status_var.set("Loading orders…")

        # Clear the tree immediately so the UI doesn't freeze on tab switch
        for iid in self.orders_tree.get_children():
            self.orders_tree.delete(iid)

        q = _queue.Queue()

        def _work():
            try:
                rows = self._scan_orders()
                q.put(("ok", rows))
            except Exception as exc:
                q.put(("error", str(exc)))

        def _poll():
            try:
                while True:
                    kind, data = q.get_nowait()
                    if kind == "ok":
                        self._all_orders_data = data
                        self._filter_orders_list()
                        n   = len(data)
                        src = "database + local" if _db.is_ready() and _db.current_user() else "local files"
                        self.status_var.set(f"Found {n} order{'s' if n != 1 else ''} ({src})")
                        return
                    elif kind == "error":
                        self.status_var.set(f"Error loading orders: {data}")
                        return
            except _queue.Empty:
                pass
            self.master.after(50, _poll)

        threading.Thread(target=_work, daemon=True).start()
        self.master.after(50, _poll)

    def _filter_orders_list(self):
        q           = self.search_var.get().strip().lower()
        type_sel    = getattr(self, "filter_type_var",   None)
        status_sel  = getattr(self, "filter_status_var", None)
        date_from   = getattr(self, "filter_date_from",  None)
        date_to     = getattr(self, "filter_date_to",    None)
        type_val    = type_sel.get()   if type_sel   else "All"
        status_val  = status_sel.get() if status_sel else "All"
        df_str      = date_from.get().strip() if date_from else ""
        dt_str      = date_to.get().strip()   if date_to   else ""

        # Parse optional date bounds (dd/mm/yy or dd/mm/yyyy)
        def _parse_date(s):
            for fmt in ("%d/%m/%y", "%d/%m/%Y", "%d-%m-%y", "%d-%m-%Y"):
                try:
                    return datetime.datetime.strptime(s, fmt)
                except (ValueError, AttributeError):
                    pass
            return None

        d_from = _parse_date(df_str) if df_str else None
        d_to   = _parse_date(dt_str) if dt_str else None

        for iid in self.orders_tree.get_children():
            self.orders_tree.delete(iid)

        def _row_date(r):
            return _parse_date(r.get("date_ordered", ""))

        displayed = []
        for r in self._all_orders_data:
            # Text search
            if q and not (
                q in r["customer"].lower()
                or q in r["order_no"].lower()
                or q in r.get("created_by", "").lower()
            ):
                continue
            # Type filter
            if type_val != "All":
                ot = {"bags": "Bags", "mixed": "Mixed", "filter": "Filter"}.get(
                    r.get("order_type", "filter"), "Filter")
                if ot != type_val:
                    continue
            # Status filter
            if status_val != "All":
                row_status = r.get("status", "Pending") or "Pending"
                if row_status != status_val:
                    continue
            # Date range filter
            rd = _row_date(r)
            if d_from and rd and rd < d_from:
                continue
            if d_to and rd and rd > d_to:
                continue
            displayed.append(r)

        # Cache the displayed list so _get_selected_order() stays in sync
        self._displayed_orders = displayed

        for i, row in enumerate(displayed):
            is_priority = bool(row.get("priority", False))
            status      = row.get("status", "Pending") or "Pending"
            notes_cnt   = row.get("notes_count", 0) or 0
            status_lbl  = f"📝 {status}" if notes_cnt else status

            if is_priority:
                tag = "priority"
            elif status == "In Production":
                tag = "in_prod"
            elif status == "Complete":
                tag = "complete"
            elif status == "Dispatched":
                tag = "dispatched"
            else:
                tag = "even" if i % 2 == 0 else "odd"

            ot          = row.get("order_type", "filter")
            otype_label = {"bags": "Bags", "mixed": "Mixed", "filter": "Filter"}.get(ot, "Filter")
            src_label   = "Database" if row.get("source") == "db" else row.get("filename", "")
            cust_display = ("🚨 " + row["customer"]) if is_priority else row["customer"]
            _badge = _type_badge(otype_label)
            self.orders_tree.insert("", "end", iid=str(i), tags=(tag,),
                text=("" if _badge else otype_label), image=(_badge or ""),
                values=(
                cust_display,
                row["order_no"],
                row["date_ordered"],
                row["date_due"],
                status_lbl,
                row["n_items"],
                row.get("created_by", ""),
                src_label,
            ))

    def _get_selected_order(self) -> "dict | None":
        """Return the first selected order row, or None."""
        sel = self.orders_tree.selection()
        if not sel:
            return None
        idx = int(sel[0])
        displayed = getattr(self, "_displayed_orders", self._all_orders_data)
        return displayed[idx] if idx < len(displayed) else None

    def _get_selected_orders(self) -> list:
        """Return all selected order rows (supports multi-select)."""
        sel = self.orders_tree.selection()
        if not sel:
            return []
        displayed = getattr(self, "_displayed_orders", self._all_orders_data)
        result = []
        for iid in sel:
            idx = int(iid)
            if idx < len(displayed):
                result.append(displayed[idx])
        return result

    def _load_prev_order(self):
        row = self._get_selected_order()
        if row is None:
            messagebox.showinfo("Load Order", "Select an order from the list first.")
            return
        if row.get("source") == "db":
            self._load_from_db_row(row)
        else:
            self._load_from_path(row["path"])

    def _duplicate_prev_order(self):
        """Load a previous order into the New Order form, clearing order-specific fields."""
        row = self._get_selected_order()
        if row is None:
            messagebox.showinfo("Duplicate Order", "Select an order from the list first.")
            return

        # Pull header + items from DB or local file
        if row.get("source") == "db":
            header = dict(row.get("db_header") or {})
            items  = list(row.get("db_items") or [])
        else:
            try:
                payload = json.loads(row["path"].read_text(encoding="utf-8"))
                header  = dict(payload.get("header", {}))
                items   = list(payload.get("items", []))
            except Exception as exc:
                messagebox.showerror("Error", f"Could not read order file:\n{exc}")
                return

        # Tag items without item_kind (back-compat)
        for it in items:
            if "item_kind" not in it:
                it["item_kind"] = "bag" if "product_type" in it else "filter"

        # Clear fields that should be fresh for a new order
        header["Order Number"] = ""
        today = datetime.date.today()
        header["Date Ordered"] = today.strftime("%d/%m/%y")
        header["Date Due"]     = "ASAP"

        # Populate form
        for k, var in self.hvars.items():
            var.set(str(header.get(k, "")))
        self.txt_header_notes.delete("1.0", "end")
        self.txt_header_notes.insert("1.0", header.get("Notes", "") or "")
        self.items = items
        self._refresh_items_tree()
        self._show_tab("new_order")

        cust = row.get("customer", "")
        self.status_var.set(
            f"Duplicated order from {cust} — enter a new Order # and generate.")

    def _load_from_db_row(self, row: dict):
        header = row.get("db_header") or {}
        items  = list(row.get("db_items") or [])
        for it in items:
            if "item_kind" not in it:
                it["item_kind"] = "bag" if "product_type" in it else "filter"
        for k, var in self.hvars.items():
            var.set(str(header.get(k, "")))
        self.txt_header_notes.delete("1.0", "end")
        self.txt_header_notes.insert("1.0", header.get("Notes", "") or "")
        self.items = items
        self._refresh_items_tree()
        self._show_tab("new_order")
        self.status_var.set(f"Loaded from database: {row.get('customer', '')} / {row.get('order_no', '')}")

    def _regen_prev_order(self):
        row = self._get_selected_order()
        if row is None:
            messagebox.showinfo("Regenerate", "Select an order from the list first.")
            return
        if row.get("source") == "db":
            header = row.get("db_header") or {}
            items  = list(row.get("db_items") or [])
        else:
            try:
                payload = json.loads(row["path"].read_text(encoding="utf-8"))
                header  = payload.get("header", {})
                items   = payload.get("items",  [])
            except Exception as exc:
                messagebox.showerror("Error", f"Could not read order file:\n{exc}")
                return

        # Back-compat: tag items without item_kind
        for it in items:
            if "item_kind" not in it:
                it["item_kind"] = "bag" if "product_type" in it else "filter"

        if row.get("source") == "db":
            _name_hdr  = {
                "Customer Name": row.get("customer", ""),
                "Order Number":  row.get("order_no", ""),
                "Date Ordered":  row.get("date_ordered", ""),
                "Date Due":      row.get("date_due", ""),
            }
            base       = self._apply_pdf_name_template(_name_hdr, order_type)
            _base_path = ORDERS_DIR / base
        else:
            _base_path = row["path"].with_suffix("")
            base       = row["path"].stem
        filter_items = [i for i in items if i.get("item_kind", "filter") != "bag"]
        bag_items    = [i for i in items if i.get("item_kind") == "bag"]
        total        = len(items)
        n_filter     = len(filter_items)
        bag_start    = n_filter + 1

        has_filter = bool(filter_items)
        has_bag    = bool(bag_items)
        if has_filter and has_bag:
            order_type = "mixed"
        elif has_bag:
            order_type = "bags"
        else:
            order_type = "filter"

        prog         = _ProgressDialog(self.master, order_type)
        service      = self.service
        custom_media = list(self._custom_media)

        label = row.get("customer") or row.get("filename") or "order"
        self.status_var.set(f"Regenerating {label}…")

        def _worker():
            pdf_paths = []
            errors    = []

            if order_type == "mixed":
                prog.advance("Building filter worksheets & bag docket in parallel…")

                def _do_filter():
                    return service.create_order(
                        header, filter_items, persist_json=False,
                        extra_media_types=custom_media, auto_open=False,
                        page_start=1, grand_total=total)

                def _do_bags():
                    docx_p = str(ORDERS_DIR / f"{base}_bags.docx")
                    return generate_bag_docket(
                        header, bag_items, docx_p, auto_open=False,
                        item_start=bag_start, grand_total=total)

                with ThreadPoolExecutor(max_workers=2) as pool:
                    fut_f = pool.submit(_do_filter)
                    fut_b = pool.submit(_do_bags)
                    prog.advance("Exporting PDFs…")
                    try:
                        r = fut_f.result()
                        p = r.get("output_path", "")
                        if p:
                            pdf_paths.append(p)
                    except Exception as exc:
                        errors.append(f"Filter worksheets: {exc}")
                    try:
                        p = fut_b.result()
                        if p:
                            pdf_paths.append(p)
                    except Exception as exc:
                        errors.append(f"Bag docket: {exc}")
            else:
                if has_filter:
                    prog.advance("Building filter worksheets…")
                    try:
                        r = service.create_order(
                            header, filter_items, persist_json=False,
                            extra_media_types=custom_media, auto_open=False,
                            page_start=1, grand_total=total)
                        prog.advance("Exporting to PDF…")
                        p = r.get("output_path", "")
                        if p:
                            pdf_paths.append(p)
                    except Exception as exc:
                        errors.append(f"Filter worksheets: {exc}")
                if has_bag:
                    prog.advance("Building bag / roll docket…")
                    try:
                        docx_p = str(ORDERS_DIR / f"{base}_bags.docx")
                        prog.advance("Exporting to PDF…")
                        p = generate_bag_docket(
                            header, bag_items, docx_p, auto_open=False,
                            item_start=bag_start, grand_total=total)
                        if p:
                            pdf_paths.append(p)
                    except Exception as exc:
                        errors.append(f"Bag docket: {exc}")

            real_pdfs = [p for p in pdf_paths
                         if str(p).lower().endswith(".pdf") and os.path.exists(p)]

            if len(real_pdfs) > 1:
                prog.advance("Merging PDFs…")
                merged = str(ORDERS_DIR / f"{base}_order.pdf")
                _ProgressDialog._merge(real_pdfs, merged)

            prog.advance("Done!")
            prog.after(0, lambda: _finish(pdf_paths, real_pdfs, errors))

        def _finish(pdf_paths, real_pdfs, errors):
            prog.close()
            if len(real_pdfs) > 1:
                merged = str(ORDERS_DIR / f"{base}_order.pdf")
                if os.path.exists(merged):
                    os.startfile(merged)
                    opened = merged
                else:
                    for p in real_pdfs:
                        os.startfile(p)
                    opened = " + ".join(real_pdfs)
            elif real_pdfs:
                os.startfile(real_pdfs[0])
                opened = real_pdfs[0]
            elif pdf_paths:
                for p in pdf_paths:
                    if os.path.exists(p):
                        os.startfile(p)
                opened = " + ".join(pdf_paths)
            else:
                opened = ""

            if errors:
                messagebox.showerror("Regenerate Errors", "\n\n".join(errors))

            self.status_var.set("Order regenerated and opened.")
            _db.log_action("order_regenerated",
                f"Customer: {row.get('customer','')}  O/N: {row.get('order_no','')}")
            messagebox.showinfo("Done", f"Order PDF:\n  {opened}")

        threading.Thread(target=_worker, daemon=True).start()

    def _delete_prev_order(self):
        row = self._get_selected_order()
        if row is None:
            messagebox.showinfo("Delete Order", "Select an order first.")
            return

        if row.get("source") != "db":
            messagebox.showinfo("Delete Order",
                                "Only database orders can be deleted here.\n"
                                "To remove local files, use Open Orders Folder.")
            return

        if not _db.can_delete_order(row):
            messagebox.showwarning("No Permission",
                                   "You do not have permission to delete this order.\n\n"
                                   "Employees can delete their own orders.\n"
                                   "Managers can delete Employee and Manager orders.\n"
                                   "Directors and Admins can delete any order.")
            return

        customer = row.get("customer", "")
        order_no = row.get("order_no", "")
        creator  = row.get("created_by", "")
        if not messagebox.askyesno(
                "Delete Order",
                f"Permanently delete this order?\n\n"
                f"  Customer: {customer}\n"
                f"  Order #:  {order_no}\n"
                f"  Created by: {creator}\n\n"
                "This cannot be undone."):
            return

        db_id = row.get("db_id")
        self.status_var.set("Deleting order…")
        self.update()

        import queue as _q
        q = _q.Queue()

        def _work():
            try:
                _db.delete_order(db_id)
                q.put(("ok", None))
            except Exception as exc:
                q.put(("error", str(exc)))

        def _poll():
            try:
                while True:
                    kind, data = q.get_nowait()
                    if kind == "ok":
                        self.status_var.set("Order deleted.")
                        _db.log_action("order_deleted",
                            f"Customer: {row.get('customer','')}  O/N: {row.get('order_no','')}")
                        self._refresh_orders_list()
                        return
                    elif kind == "error":
                        messagebox.showerror("Delete Failed", data)
                        self.status_var.set("Delete failed.")
                        return
            except _q.Empty:
                pass
            self.master.after(50, _poll)

        threading.Thread(target=_work, daemon=True).start()
        self.master.after(50, _poll)

    def _archive_prev_order(self):
        row = self._get_selected_order()
        if row is None:
            messagebox.showinfo("Archive Order", "Select an order first.")
            return

        if row.get("source") != "db":
            messagebox.showinfo("Archive Order", "Only database orders can be archived.")
            return

        if not _db.can_archive_order():
            messagebox.showwarning("No Permission",
                                   "Only Directors and Admins can archive orders.")
            return

        customer = row.get("customer", "")
        order_no = row.get("order_no", "")
        if not messagebox.askyesno(
                "Archive Order",
                f"Archive this order? It will be hidden from the orders list.\n\n"
                f"  Customer: {customer}\n"
                f"  Order #:  {order_no}"):
            return

        db_id = row.get("db_id")
        self.status_var.set("Archiving order…")
        self.update()

        import queue as _q
        q = _q.Queue()

        def _work():
            try:
                _db.archive_order(db_id)
                q.put(("ok", None))
            except Exception as exc:
                q.put(("error", str(exc)))

        def _poll():
            try:
                while True:
                    kind, data = q.get_nowait()
                    if kind == "ok":
                        self.status_var.set("Order archived.")
                        _db.log_action("order_archived",
                            f"Customer: {row.get('customer','')}  O/N: {row.get('order_no','')}")
                        self._refresh_orders_list()
                        return
                    elif kind == "error":
                        messagebox.showerror("Archive Failed", data)
                        self.status_var.set("Archive failed.")
                        return
            except _q.Empty:
                pass
            self.master.after(50, _poll)

        threading.Thread(target=_work, daemon=True).start()
        self.master.after(50, _poll)

    def _toggle_dark_mode(self):
        """Switch theme live — no restart needed."""
        is_dark = self._settings.get("dark_mode", False)
        new_dark = not is_dark

        # Build color swap map before updating globals
        if new_dark:
            color_map = {v.upper(): _DARK_COLORS[k] for k, v in _LIGHT_COLORS.items()}
            _set_dark_mode()
        else:
            color_map = {v.upper(): _LIGHT_COLORS[k] for k, v in _DARK_COLORS.items()}
            _set_light_mode()

        # Save preference
        self._settings["dark_mode"] = new_dark
        _save_settings(self._settings)

        # Re-apply TTK styles with new colours
        _configure_ttk_style()

        # Walk every widget and swap colours
        _restyle_widget_tree(self.master, color_map)
        self.master.configure(bg=CBG)

        # Re-configure treeview row tags (not caught by widget walk)
        for tree_attr in ("tree", "orders_tree", "audit_tree"):
            tv = getattr(self, tree_attr, None)
            if tv:
                tv.tag_configure("even",  background=CRE)
                tv.tag_configure("odd",   background=CCA)
                tv.tag_configure("bag_e", background=CRE)
                tv.tag_configure("bag_o", background=CCA)

        # Update the toggle button label
        if hasattr(self, "_dark_mode_btn") and self._dark_mode_btn.winfo_exists():
            lbl = "☀  Switch to Light Mode" if new_dark else "🌙  Switch to Dark Mode"
            self._dark_mode_btn.config(text=lbl, bg=CNE,
                                       activebackground=_dk(CNE))
        if hasattr(self, "_dark_mode_cur_lbl") and self._dark_mode_cur_lbl.winfo_exists():
            self._dark_mode_cur_lbl.config(text=f"  Current: {'Dark' if new_dark else 'Light'} Mode",
                                            bg=CCA, fg=CMU)

        # Re-raise the active tab so any canvas-based tabs redraw
        active = next((k for k, f in self._tab_frames.items()
                       if f.winfo_ismapped()), "settings")
        self._show_tab(active)
        self.status_var.set(f"{'Dark' if new_dark else 'Light'} mode applied.")

    def _toggle_order_priority(self):
        """Toggle the high-priority flag on the selected order."""
        row = self._get_selected_order()
        if row is None:
            messagebox.showinfo("Toggle Priority", "Select an order first.")
            return
        if row.get("source") != "db":
            messagebox.showinfo("Toggle Priority", "Priority can only be set on database orders.")
            return
        db_id = row.get("db_id")
        if not db_id:
            return
        current = bool(row.get("priority", False))
        new_val = not current
        try:
            _db.set_order_priority(str(db_id), new_val)
            _db.log_action("order_priority",
                f"O/N: {row.get('order_no','')} | Customer: {row.get('customer','')} | "
                f"Priority: {'ON' if new_val else 'OFF'}")
            self.status_var.set(
                f"Priority {'set' if new_val else 'cleared'} for {row.get('customer','')}.")
            self._refresh_orders_list()
        except Exception as exc:
            messagebox.showerror("Error", f"Could not update priority:\n{exc}")

    def _add_order_note(self):
        """Prompt for a note and log it against the selected order."""
        row = self._get_selected_order()
        if row is None:
            messagebox.showinfo("Add Note", "Select an order from the list first.")
            return
        if row.get("source") != "db":
            messagebox.showinfo("Add Note",
                "Notes can only be added to database orders.")
            return

        order_no = row.get("order_no", "")
        customer = row.get("customer", "")

        dlg = tk.Toplevel(self.master)
        dlg.title("Add Note")
        dlg.resizable(False, False)
        dlg.transient(self.master)
        dlg.grab_set()
        dlg.configure(bg=CBG)

        hdr = tk.Frame(dlg, bg=CA, padx=14, pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Add Note to Order", bg=CA, fg="white",
                 font=F_BOLD).pack(anchor="w")
        tk.Label(hdr, text=f"{customer}  /  O/N: {order_no}",
                 bg=CA, fg="#A9CCE3", font=F_SM).pack(anchor="w")

        foot = tk.Frame(dlg, bg=CBG, padx=14, pady=10)
        foot.pack(fill="x", side="bottom")

        result = [None]

        def _save():
            txt = note_txt.get("1.0", "end").strip()
            if not txt:
                messagebox.showwarning("Empty", "Please enter a note.", parent=dlg)
                return
            result[0] = txt
            dlg.destroy()

        flat_btn(foot, "Cancel", dlg.destroy, bg=CNE, pady=6).pack(side="right", padx=(6, 0))
        flat_btn(foot, "Save Note", _save,    bg=CGR, pady=6).pack(side="right")

        body = tk.Frame(dlg, bg=CBG, padx=14, pady=10)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="Note:", bg=CBG, fg=CTX, font=F_BODY).pack(anchor="w", pady=(0, 4))
        note_txt = tk.Text(body, width=50, height=5, wrap="word",
                           font=F_BODY, relief="solid", bd=1,
                           bg=CCA, fg=CTX, insertbackground=CTX)
        note_txt.pack(fill="both", expand=True)
        note_txt.focus_set()

        dlg.bind("<Escape>", lambda e: dlg.destroy())
        W, H = 440, 260
        dlg.geometry(f"{W}x{H}+{self.master.winfo_rootx()+self.master.winfo_width()//2-W//2}"
                     f"+{self.master.winfo_rooty()+self.master.winfo_height()//2-H//2}")
        self.master.wait_window(dlg)

        if result[0]:
            db_id = row.get("db_id")
            try:
                _db.log_action("order_note",
                    f"O/N: {order_no} | Customer: {customer} | {result[0]}")
                # Also persist note into the order's header JSON so it's counted
                if db_id:
                    _db.append_order_note(
                        str(db_id), result[0],
                        _db.current_full_name() or _db.current_username()
                    )
                self.status_var.set(f"Note added to order {order_no}.")
                messagebox.showinfo("Note Saved",
                    "Your note has been saved to the order history.")
                self._refresh_orders_list()
            except Exception as exc:
                messagebox.showerror("Error", f"Could not save note:\n{exc}")

    def _change_order_status(self):
        """Show a dialog to change status for one or more selected orders (bulk-capable)."""
        rows = self._get_selected_orders()
        if not rows:
            messagebox.showinfo("Change Status", "Select one or more orders first.")
            return
        db_rows = [r for r in rows if r.get("source") == "db" and r.get("db_id")]
        if not db_rows:
            messagebox.showinfo("Change Status",
                "Status can only be set on database orders.\n"
                "The selected order(s) are local only.")
            return

        # Dialog
        n         = len(db_rows)
        is_bulk   = n > 1
        title_txt = f"Change Status — {n} Orders" if is_bulk else "Change Order Status"
        sub_txt   = (f"{n} orders selected" if is_bulk
                     else f"{db_rows[0].get('customer','')}  /  O/N: {db_rows[0].get('order_no','')}")
        # If single order, pre-select its current status
        current   = db_rows[0].get("status", "Pending") if not is_bulk else "Pending"

        dlg = tk.Toplevel(self.master)
        dlg.title(title_txt)
        dlg.resizable(False, False)
        dlg.transient(self.master)
        dlg.grab_set()
        dlg.configure(bg=CBG)

        hdr = tk.Frame(dlg, bg=CA, padx=14, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text=title_txt, bg=CA, fg="white", font=F_BOLD).pack(anchor="w")
        tk.Label(hdr, text=sub_txt,   bg=CA, fg="#A9CCE3", font=F_SM).pack(anchor="w")

        body = tk.Frame(dlg, bg=CBG, padx=16, pady=14)
        body.pack(fill="both", expand=True)

        if is_bulk:
            tk.Label(body,
                     text="All selected orders will be updated to the chosen status.",
                     bg=CBG, fg=CMU, font=F_SM).pack(anchor="w", pady=(0, 8))

        _STATUS_META = [
            ("Pending",       "⏳", CMU),
            ("In Production", "🔧", "#856404"),
            ("Complete",      "✅", "#155724"),
            ("Dispatched",    "🚚", "#004085"),
        ]

        status_var = tk.StringVar(value=current)
        for s, icon, color in _STATUS_META:
            rb_row = tk.Frame(body, bg=CBG, pady=3)
            rb_row.pack(fill="x")
            tk.Radiobutton(rb_row, text=f"  {icon}  {s}",
                           variable=status_var, value=s,
                           bg=CBG, fg=color, font=F_BODY,
                           selectcolor=CCA, activebackground=CBG,
                           relief="flat").pack(side="left")

        foot = tk.Frame(dlg, bg=CBG, padx=14, pady=10)
        foot.pack(fill="x")
        result = [None]

        def _save():
            result[0] = status_var.get()
            dlg.destroy()

        lbl = f"Apply to {n} Orders" if is_bulk else "Save Status"
        flat_btn(foot, "Cancel", dlg.destroy, bg=CNE, pady=6).pack(side="right", padx=(6, 0))
        flat_btn(foot, lbl, _save, bg=CGR, pady=6).pack(side="right")
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        W, H = 340, 300 if is_bulk else 280
        dlg.geometry(f"{W}x{H}+{self.master.winfo_rootx()+self.master.winfo_width()//2-W//2}"
                     f"+{self.master.winfo_rooty()+self.master.winfo_height()//2-H//2}")
        self.master.wait_window(dlg)

        if not result[0]:
            return

        new_status = result[0]
        failed = 0
        changed = 0
        for r in db_rows:
            old_status = r.get("status", "Pending") or "Pending"
            if old_status == new_status:
                continue
            try:
                _db.set_order_status(str(r["db_id"]), new_status)
                _db.log_action("order_status",
                    f"O/N: {r.get('order_no','')} | Customer: {r.get('customer','')} | "
                    f"Status: {old_status} → {new_status}")
                changed += 1
            except Exception:
                failed += 1

        if changed:
            self.status_var.set(
                f"Status set to '{new_status}' on {changed} order{'s' if changed != 1 else ''}."
                + (f"  ({failed} failed)" if failed else ""))
            self._refresh_orders_list()
        elif failed:
            messagebox.showerror("Error", f"Could not update {failed} order(s).")

    @staticmethod
    def _shell_verb(path: str, verb: str, params: str = "") -> bool:
        """Run a Windows shell verb ('print' / 'printto') on a file.

        Returns True only on success. ShellExecuteW returns a value > 32 on
        success and an error code <= 32 on failure — the old code ignored this,
        so a failed 'printto' looked like it worked and nothing printed.
        """
        import ctypes
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, verb, str(path), (params or None), str(Path(path).parent), 0)
        return int(rc) > 32

    @staticmethod
    def _get_default_printer() -> str:
        """Current Windows default printer name ('' if unknown)."""
        try:
            import win32print
            return win32print.GetDefaultPrinter() or ""
        except Exception:
            pass
        import subprocess as _sp
        try:
            out = _sp.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_Printer -Filter 'Default=TRUE').Name"],
                creationflags=0x08000000, capture_output=True, text=True, timeout=10)
            return (out.stdout or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _set_default_printer(name: str) -> bool:
        """Set the Windows default printer. Returns True on apparent success."""
        try:
            import win32print
            win32print.SetDefaultPrinter(name)
            return True
        except Exception:
            pass
        import subprocess as _sp
        esc = name.replace("'", "''")
        try:
            r = _sp.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(New-Object -ComObject WScript.Network).SetDefaultPrinter('{esc}')"],
                creationflags=0x08000000, timeout=15)
            return r.returncode == 0
        except Exception:
            return False

    @staticmethod
    def _print_with_sumatra(path: str, printer: str) -> bool:
        """Print a PDF via the bundled SumatraPDF.exe.

        SumatraPDF renders and prints the PDF itself, so it needs no PDF viewer
        and no shell 'print'/'printto' verb — it talks to the printer directly.
        Prints to the given printer, or the Windows default when none is set.

        Returns True on success, False if the helper is missing or fails, so
        the caller can fall back to the shell-verb method.
        """
        helper = RESOURCE_DIR / "SumatraPDF.exe"
        if not helper.exists():
            return False
        import subprocess as _sp
        if printer:
            cmd = [str(helper), "-print-to", printer,
                   "-silent", "-exit-when-done", str(path)]
        else:
            cmd = [str(helper), "-print-to-default",
                   "-silent", "-exit-when-done", str(path)]
        try:
            # -silent suppresses dialogs; CREATE_NO_WINDOW hides any flash.
            r = _sp.run(cmd, creationflags=0x08000000, timeout=180)
            return r.returncode == 0
        except Exception:
            return False

    def _print_file(self, path: str) -> str:
        """Send a file to the configured printer (or OS default if none set).

        Returns "" on success, or an error message on failure. This method
        blocks while the print job spools, so it MUST be called from a
        background thread — it touches no UI, so that is safe.
        """
        printer = self._settings.get("default_printer", "").strip()
        try:
            if platform.system() != "Windows":
                import subprocess as _sp
                cmd = ["lpr", "-P", printer, str(path)] if printer else ["lpr", str(path)]
                _sp.Popen(cmd)
                return ""

            # ── Preferred: bundled SumatraPDF.exe (no PDF viewer needed) ─────
            # It renders + prints the PDF directly to the chosen printer (or the
            # Windows default when blank). If the helper is absent or fails, we
            # fall through to the shell-verb path below.
            if str(path).lower().endswith(".pdf") and \
                    self._print_with_sumatra(path, printer):
                return ""

            # ── No specific printer → plain 'print' verb → OS default ────────
            if not printer:
                if not self._shell_verb(path, "print"):
                    raise RuntimeError(
                        "Windows couldn't print this PDF. Make sure a PDF viewer "
                        "is installed and set as the default for .pdf files.")
                return ""

            # ── A specific printer is configured ────────────────────────────
            # Try the direct 'printto' verb first (doesn't touch the system
            # default). Many default PDF handlers (Edge, Chrome) don't register
            # it, so fall back to temporarily making the chosen printer the
            # default and using the near-universal 'print' verb, then restore.
            if self._shell_verb(path, "printto", f'"{printer}"'):
                return ""

            previous = self._get_default_printer()
            if not self._set_default_printer(printer):
                raise RuntimeError(
                    f"Couldn't select the printer '{printer}'.\n"
                    "Open Settings → Default Printer → Refresh and make sure "
                    "the name matches exactly, or leave it blank to use the "
                    "Windows default printer.")
            try:
                ok = self._shell_verb(path, "print")
            finally:
                # Restore the user's previous default once the PDF app has had
                # time to launch and spool the job (printing is asynchronous).
                # A plain Timer avoids touching Tk from this worker thread.
                if previous and previous != printer:
                    import threading as _th
                    _th.Timer(8.0, lambda p=previous: self._set_default_printer(p)).start()
            if not ok:
                raise RuntimeError(
                    "Windows couldn't print this PDF. Make sure a PDF viewer "
                    "is installed and set as the default for .pdf files.")
            return ""
        except Exception as exc:
            return str(exc)

    def _print_prev_order(self):
        """Regenerate the selected order's PDFs and send to the default printer."""
        row = self._get_selected_order()
        if row is None:
            messagebox.showinfo("Print", "Select an order from the list first.")
            return

        if not messagebox.askyesno(
                "Print Order",
                f"Regenerate and print:\n"
                f"{row.get('customer','')}  /  O/N: {row.get('order_no','')}\n\n"
                "This will send the PDF to your default printer."):
            return

        if row.get("source") == "db":
            header = dict(row.get("db_header") or {})
            items  = list(row.get("db_items") or [])
        else:
            try:
                payload = json.loads(row["path"].read_text(encoding="utf-8"))
                header  = dict(payload.get("header", {}))
                items   = list(payload.get("items", []))
            except Exception as exc:
                messagebox.showerror("Error", f"Could not read order:\n{exc}")
                return

        for it in items:
            if "item_kind" not in it:
                it["item_kind"] = "bag" if "product_type" in it else "filter"

        filter_items = [i for i in items if i.get("item_kind", "filter") != "bag"]
        bag_items    = [i for i in items if i.get("item_kind") == "bag"]
        total        = len(items)
        n_filter     = len(filter_items)
        bag_start    = n_filter + 1
        has_filter   = bool(filter_items)
        has_bag      = bool(bag_items)

        if has_filter and has_bag:
            order_type = "mixed"
        elif has_bag:
            order_type = "bags"
        else:
            order_type = "filter"

        _name_hdr = {
            "Customer Name": row.get("customer", ""),
            "Order Number":  row.get("order_no", ""),
            "Date Ordered":  row.get("date_ordered", ""),
            "Date Due":      row.get("date_due", ""),
        }
        base = self._apply_pdf_name_template(_name_hdr, order_type)

        prog         = _ProgressDialog(self.master, order_type)
        service      = self.service
        custom_media = list(self._custom_media)
        self.status_var.set(f"Preparing to print {row.get('customer','')}…")

        def _worker():
            pdf_paths = []
            errors    = []
            if has_filter:
                prog.advance("Building filter worksheets…")
                try:
                    r = service.create_order(
                        header, filter_items, persist_json=False,
                        extra_media_types=custom_media, auto_open=False,
                        page_start=1, grand_total=total)
                    prog.advance("Exporting to PDF…")
                    p = r.get("output_path", "")
                    if p:
                        pdf_paths.append(p)
                except Exception as exc:
                    errors.append(f"Filter: {exc}")
            if has_bag:
                prog.advance("Building bag docket…")
                try:
                    docx_p = str(ORDERS_DIR / f"{base}_bags.docx")
                    prog.advance("Exporting to PDF…")
                    p = generate_bag_docket(
                        header, bag_items, docx_p, auto_open=False,
                        item_start=bag_start, grand_total=total)
                    if p:
                        pdf_paths.append(p)
                except Exception as exc:
                    errors.append(f"Bags: {exc}")

            real_pdfs = [p for p in pdf_paths
                         if str(p).lower().endswith(".pdf") and os.path.exists(p)]
            if len(real_pdfs) > 1:
                prog.advance("Merging PDFs…")
                merged = str(ORDERS_DIR / f"{base}_order.pdf")
                if _ProgressDialog._merge(real_pdfs, merged):
                    real_pdfs = [merged]

            prog.advance("Done!")
            prog.after(0, lambda: _finish(real_pdfs, errors))

        def _finish(real_pdfs, errors):
            prog.close()
            if errors:
                messagebox.showerror("Print Errors", "\n\n".join(errors))
                return
            if not real_pdfs:
                messagebox.showerror("Print", "No PDF was generated.")
                return

            # Spooling blocks (SumatraPDF can take several seconds), so do it on
            # a background thread — otherwise the whole UI freezes ("Not
            # Responding") until the printer finishes. UI updates are marshalled
            # back to the main thread with after().
            self.status_var.set(f"Sending to printer: {row.get('customer','')}…")

            def _print_worker():
                err = ""
                for p in real_pdfs:
                    err = self._print_file(p)
                    if err:
                        break
                if not err:
                    try:
                        _db.log_action("order_printed",
                            f"Customer: {row.get('customer','')}  O/N: {row.get('order_no','')}")
                    except Exception:
                        pass

                def _done():
                    if err:
                        messagebox.showerror(
                            "Print Error", f"Could not send to printer:\n{err}")
                        self.status_var.set("Print failed — see the error message.")
                    else:
                        self.status_var.set(
                            f"Sent to printer: {row.get('customer','')} / {row.get('order_no','')}")
                self.master.after(0, _done)

            threading.Thread(target=_print_worker, daemon=True).start()

        threading.Thread(target=_worker, daemon=True).start()

    def _view_order_history(self):
        """Show a popup with the full audit history for the selected order."""
        row = self._get_selected_order()
        if row is None:
            messagebox.showinfo("View History", "Select an order from the list first.")
            return

        order_no = row.get("order_no", "")
        customer = row.get("customer", "")

        dlg = tk.Toplevel(self.master)
        dlg.title(f"Order History — {order_no}")
        dlg.transient(self.master)
        dlg.grab_set()
        dlg.configure(bg=CBG)
        W, H = 700, 460
        dlg.geometry(f"{W}x{H}+{self.master.winfo_rootx()+self.master.winfo_width()//2-W//2}"
                     f"+{self.master.winfo_rooty()+self.master.winfo_height()//2-H//2}")

        hdr = tk.Frame(dlg, bg=CA, padx=14, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Order History", bg=CA, fg="white",
                 font=(FAM, 11, "bold")).pack(anchor="w")
        tk.Label(hdr, text=f"{customer}  /  O/N: {order_no}",
                 bg=CA, fg="#A9CCE3", font=F_SM).pack(anchor="w")

        # Status label while loading
        status_lbl = tk.Label(dlg, text="Loading…", bg=CBG, fg=CMU, font=F_SM)
        status_lbl.pack(pady=6)

        # Timeline frame (scrollable)
        wrap = tk.Frame(dlg, bg=CBG)
        wrap.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        canvas = tk.Canvas(wrap, bg=CBG, highlightthickness=0)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=CBG)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))
        dlg.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-1*(e.delta//120), "units"))

        foot = tk.Frame(dlg, bg=CBG, pady=8, padx=14)
        foot.pack(fill="x")
        flat_btn(foot, "Close", dlg.destroy, bg=CNE, pady=6).pack(side="right")

        ACTION_COLORS = {
            "order_created":     ("#10B981", "✦  Created"),
            "order_regenerated": ("#3B82F6", "↺  Regenerated"),
            "order_deleted":     ("#EF4444", "✕  Deleted"),
            "order_archived":    ("#8B5CF6", "⊡  Archived"),
            "order_note":        ("#F59E0B", "📝 Note"),
        }

        def _populate(entries):
            status_lbl.destroy()
            if not entries:
                tk.Label(inner, text="No history found for this order.",
                         bg=CBG, fg=CMU, font=F_BODY).pack(pady=20)
                return
            for i, entry in enumerate(entries):
                action  = entry.get("action", "")
                details = entry.get("details", "")
                user    = entry.get("username", "")
                ts      = (entry.get("created_at") or "")[:19].replace("T", " ")
                color, label = ACTION_COLORS.get(action, (CMU, action.replace("_", " ").title()))

                row_f = tk.Frame(inner, bg=CCA if i % 2 == 0 else CBG,
                                 padx=10, pady=8)
                row_f.pack(fill="x", pady=(0, 2))

                # Dot + action label
                top_row = tk.Frame(row_f, bg=row_f["bg"])
                top_row.pack(fill="x")
                tk.Label(top_row, text="●", bg=row_f["bg"], fg=color,
                         font=(FAM, 12)).pack(side="left", padx=(0, 6))
                tk.Label(top_row, text=label, bg=row_f["bg"], fg=color,
                         font=F_BOLD).pack(side="left")
                tk.Label(top_row, text=f"  {user}  ·  {ts}",
                         bg=row_f["bg"], fg=CMU, font=F_SM).pack(side="left", padx=(8, 0))

                # Detail text (strip O/N prefix for cleanliness in notes)
                detail_txt = details
                if action == "order_note" and " | " in details:
                    # Format: "O/N: xxx | Customer: yyy | actual note"
                    parts = details.split(" | ", 2)
                    detail_txt = parts[2] if len(parts) > 2 else details
                if detail_txt:
                    tk.Label(row_f, text=detail_txt,
                             bg=row_f["bg"], fg=CTX,
                             font=F_BODY, wraplength=580, justify="left",
                             anchor="w").pack(anchor="w", padx=(24, 0))

        def _load():
            try:
                all_entries = _db.get_audit_log(2000)
                # Filter to entries related to this order number
                term = f"O/N: {order_no}"
                filtered = [e for e in all_entries
                            if order_no and term in (e.get("details") or "")]
                # Sort oldest first for timeline
                filtered.sort(key=lambda e: e.get("created_at") or "")
                dlg.after(0, lambda: _populate(filtered))
            except Exception as exc:
                dlg.after(0, lambda: _populate([]))

        threading.Thread(target=_load, daemon=True).start()

    def _open_orders_folder(self):
        if not ORDERS_DIR.exists():
            messagebox.showinfo("No Orders",
                                "No orders have been saved yet.\n"
                                "Generate an order first.")
            return
        sys_name = platform.system()
        if sys_name == "Windows":
            os.startfile(str(ORDERS_DIR))
        elif sys_name == "Darwin":
            import subprocess
            subprocess.Popen(["open", str(ORDERS_DIR)])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(ORDERS_DIR)])


# ═══════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════

def _apply_icon(root):
    """Apply the TAF logo as the window icon. Try .ico first, fall back to .png."""
    ico = RESOURCE_DIR / "TAF_logo.ico"
    png = RESOURCE_DIR / "TAF_logo.png"
    if ico.exists():
        try:
            root.iconbitmap(default=str(ico))
            return
        except Exception:
            pass
    if png.exists():
        try:
            img = tk.PhotoImage(file=str(png))
            root.wm_iconphoto(True, img)
            root._icon_img = img   # prevent GC
        except Exception:
            pass


def _start_app():
    """Create root window, run login flow, then open main app."""
    # Apply dark mode BEFORE any widgets are created so colour globals are correct
    settings = _load_settings()
    if settings.get("dark_mode"):
        _set_dark_mode()

    root = tk.Tk()
    root.withdraw()          # hide until login succeeds
    _load_app_fonts()        # register Public Sans before any widgets are built
    root.title(APP_TITLE)
    root.configure(bg=CBG)
    _apply_icon(root)

    # ── Load settings + initialise Supabase ──────────────────────────────
    anon_key = settings.get("supabase_anon_key", "").strip()

    if anon_key:
        try:
            _db.init(anon_key)
        except Exception:
            pass

    # If not yet connected, prompt for API key
    if not _db.is_ready():
        from taf_order_app.login_window import ApiKeySetupDialog
        dlg = ApiKeySetupDialog(root)
        root.wait_window(dlg)
        if dlg.result:
            settings["supabase_anon_key"] = dlg.result
            _save_settings(settings)

    # ── Check tables exist ────────────────────────────────────────────────
    if _db.is_ready():
        profiles_ok, orders_ok = _db.tables_exist()
        if not profiles_ok or not orders_ok:
            missing = []
            if not profiles_ok: missing.append("profiles")
            if not orders_ok:   missing.append("orders")
            messagebox.showerror(
                "Database Setup Required",
                f"The following database tables are missing: {', '.join(missing)}\n\n"
                "Please run setup_database.sql in your Supabase SQL Editor:\n"
                "  supabase.com → your project → SQL Editor → New query\n\n"
                "The app will open in offline mode.",
                parent=root,
            )
            _db.sign_out()

    # ── Login ─────────────────────────────────────────────────────────────
    if _db.is_ready():
        from taf_order_app.login_window import LoginWindow
        login = LoginWindow(root)
        root.wait_window(login)
        if login.result is None:
            root.destroy()
            return

    # ── Main window ───────────────────────────────────────────────────────
    root.geometry("1280x760")
    try:
        root.state("zoomed")
    except Exception:
        pass
    root.deiconify()
    ModernOrderApp(root)
    root.mainloop()


def main():
    _start_app()


if __name__ == "__main__":
    main()
