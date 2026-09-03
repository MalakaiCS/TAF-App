
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
import re
import threading
from concurrent.futures import ThreadPoolExecutor

from taf_order_app import OrderService
from taf_order_app.validation import (VALID_FILTER_TYPES, VALID_MEDIA_TYPES,
                                      parse_date)
from taf_order_app import db as _db
from taf_order_app import po_import as _po_import
from taf_order_app import part_numbers as _pn
from taf_order_app import stock_usage as _stock_usage
from taf_order_app import pricing as _pricing
from taf_order_app import delivery as _delivery
from taf_order_app import backup as _backup
from taf_order_app import labels as _labels
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
# Orders that couldn't reach the shared database (no connection) wait here
# and are re-sent automatically — see _sync_pending_orders.
PENDING_SYNC_DIR  = APP_DIR / "pending_sync"
LAST_VERSION_FILE = APP_DIR / "last_seen_version.txt"

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
      • 45, 50 mm → V-form — those depths are only ever made as a V-form
      • 30 mm +   → V-form / pleated panel filter (media left as-is)

    The thickness table itself lives in ``part_numbers`` so the import path
    reads a purchase order the same way this form reads a typed thickness.
    """
    ft = _pn.filter_type_for_thickness(channel)
    if not ft:
        return (None, None)
    return (ft, "GREY" if ft == "Flyscreen" else None)


# ── When work is due ─────────────────────────────────────────────────────────
# An order that is finished or gone is not due, whatever its date says, so the
# buckets below are only ever about work still in the shop.

DONE_STATUSES = ("Complete", "Dispatched")
DUE_FILTERS = ["All", "Overdue", "Due today", "Due this week", "No due date"]


def due_bucket(row: dict, today=None) -> str:
    """Where an order sits against its due date.

    One of "overdue", "today", "week" (the next seven days), "later",
    "none" (no date given) or "done". "ASAP" with no date counts as due today
    — it is the one wording that means "now" rather than "sometime".
    """
    if (row.get("status") or "Pending") in DONE_STATUSES:
        return "done"
    raw = (row.get("date_due") or "").strip()
    if not raw:
        return "none"
    if raw.lower() == "asap":
        return "today"
    parsed = parse_date(raw)
    if not parsed:
        return "none"
    today = today or datetime.date.today()
    days = (parsed.date() - today).days
    if days < 0:
        return "overdue"
    if days == 0:
        return "today"
    if days <= 7:
        return "week"
    return "later"


def due_sort_key(row: dict):
    """Sort orders by when they are due, soonest first, undated last."""
    raw = (row.get("date_due") or "").strip()
    if raw.lower() == "asap":
        return (0, datetime.date.min)
    parsed = parse_date(raw)
    if not parsed:
        return (1, datetime.date.max)      # undated sinks to the bottom
    return (0, parsed.date())


class _Tooltip:
    """A small label that appears under a widget on hover.

    For controls whose name has to be short enough to fit but is too short to
    explain itself.
    """

    def __init__(self, widget, text: str, delay: int = 450):
        self._widget = widget
        self._text = text
        self._delay = delay
        self._after = None
        self._window = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self._after = self._widget.after(self._delay, self._show)

    def _cancel(self):
        if self._after is not None:
            try:
                self._widget.after_cancel(self._after)
            except Exception:
                pass
            self._after = None

    def _show(self):
        if self._window is not None:
            return
        try:
            x = self._widget.winfo_rootx()
            y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        except Exception:
            return
        self._window = tk.Toplevel(self._widget)
        self._window.wm_overrideredirect(True)
        self._window.configure(bg=CTX)
        tk.Label(self._window, text=self._text, bg=CTX, fg="white",
                 font=F_SM, justify="left", wraplength=260,
                 padx=8, pady=5).pack()
        self._window.wm_geometry(f"+{x}+{y}")

    def _hide(self, _event=None):
        self._cancel()
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None


def _pick_one(parent, title: str, prompt: str, options: list,
              current: str = "") -> str:
    """A small "which of these?" dialog. Returns "" if it was closed."""
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.configure(bg=CBG)
    dlg.transient(parent)
    dlg.grab_set()
    dlg.resizable(False, False)
    tk.Label(dlg, text=title, bg=CA, fg="white", font=F_BOLD,
             padx=16, pady=10, anchor="w").pack(fill="x")
    body = tk.Frame(dlg, bg=CBG, padx=16, pady=14)
    body.pack(fill="both", expand=True)
    tk.Label(body, text=prompt, bg=CBG, fg=CTX, font=F_BODY,
             anchor="w", justify="left").pack(anchor="w", pady=(0, 10))
    var = tk.StringVar(value=current or (options[0] if options else ""))
    for opt in options:
        tk.Radiobutton(body, text=opt, variable=var, value=opt,
                       bg=CBG, fg=CTX, font=F_BODY, activebackground=CBG,
                       activeforeground=CTX, selectcolor=CCA, anchor="w",
                       highlightthickness=0, bd=0).pack(anchor="w")
    chosen = {"value": ""}

    def _ok():
        chosen["value"] = var.get()
        dlg.destroy()

    foot = tk.Frame(dlg, bg=CBG, padx=16, pady=10)
    foot.pack(fill="x")
    flat_btn(foot, "Cancel", dlg.destroy, bg=CNE,
             pady=7).pack(side="right", padx=(8, 0))
    flat_btn(foot, "OK", _ok, bg=CGR, pady=7).pack(side="right")
    dlg.bind("<Escape>", lambda _e: dlg.destroy())
    dlg.bind("<Return>", lambda _e: _ok())
    dlg.update_idletasks()
    dlg.geometry(f"+{parent.winfo_rootx() + 160}+{parent.winfo_rooty() + 140}")
    parent.wait_window(dlg)
    return chosen["value"]


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
CHD  = "#F7FAFC"   # table heading fill — a label, not a heavy navy bar
CHT  = "#40525F"   # table heading text
CBR  = "#E3EAEF"   # hairline border: card edges, dividers, input outlines


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
    global CGR, CGH, CRD, CRH, CNE, CNH, CRE, CSL, CNV, CFD, CHD, CHT, CBR
    CA  = "#1DA1E6";  CAH = "#38B0EE";  CA2 = "#4FB4ED"
    CBG = "#0C1A24";  CCA = "#13242F"
    CTX = "#EAF1F6";  CMU = "#8FA0AC";  CSP = "#243540"
    CGR = "#09A659";  CGH = "#0BB863"
    CRD = "#E5484D";  CRH = "#F05A5F"
    CNE = "#5C6B78";  CNH = "#6A7A86"
    CRE = "#16242E";  CSL = "#143246"
    CNV = "#0A1F2B";  CFD = "#0F2029"
    CHD = "#182B37";  CHT = "#9FB0BC";  CBR = "#22333E"

def _set_light_mode():
    """Restore all module-level colour globals to the light palette."""
    global CA, CAH, CA2, CBG, CCA, CTX, CMU, CSP
    global CGR, CGH, CRD, CRH, CNE, CNH, CRE, CSL, CNV, CFD, CHD, CHT, CBR
    CA  = "#1DA1E6";  CAH = "#1791CF";  CA2 = "#1187C9"
    CBG = "#EDF1F4";  CCA = "#FFFFFF"
    CTX = "#0F1A24";  CMU = "#5C6B78";  CSP = "#DCE4EA"
    CGR = "#09A659";  CGH = "#08914E"
    CRD = "#E5484D";  CRH = "#D23A3F"
    CNE = "#546572";  CNH = "#44525C"
    CRE = "#FAFCFD";  CSL = "#E5F4FC"
    CNV = "#16384B";  CFD = "#F4F8FA"
    CHD = "#F7FAFC";  CHT = "#40525F";  CBR = "#E3EAEF"

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
F_BODY = (FAM, 10)
F_BOLD = (FAM, 10, "bold")
F_SEC  = (FAM, 11, "bold")
F_TTL  = (FAM, 17, "bold")
F_SM   = (FAM, 9)


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
    F_BODY = (fam, 10)
    F_BOLD = (fam, 10, "bold")
    F_SEC  = (fam, 11, "bold")
    F_TTL  = (fam, 17, "bold")
    F_SM   = (fam, 9)


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

# ── Editable catalogue ───────────────────────────────────────────────────────
# The preset tables above are only the *defaults*. Managers can add/edit/
# remove models from the Dedicated Filter Presets dialog; changes are stored
# in the shared catalog_lists table (see migrate_catalog.sql) so every PC
# sees the same presets, with a local cache for offline starts. The dicts are
# mutated IN PLACE so every existing reference picks up changes.

import copy as _copy
DEFAULT_GD_PACKS      = _copy.deepcopy(DEDICATED_FILTER_PACKS)
DEFAULT_SIGRIST_PACK  = _copy.deepcopy(SIGRIST_PACK)
DEFAULT_STEPPED_PACKS = _copy.deepcopy(STEPPED_PACKS)

CATALOG_CACHE_FILE = APP_DIR / "catalog_cache.json"

# ── What the app has learned from corrections ────────────────────────────────
# When someone fixes a line in the purchase-order review screen — the document
# said "V Filter" and they picked V-form, or it said "MERV 8" and they swapped
# it for G4 — the wording and what it turned out to mean are kept here. The
# next order that says the same thing is read correctly without asking.
# Shared through the catalogue table so one person's correction teaches every
# PC, and cached locally so it survives a start with no connection.
PO_CORRECTIONS = {"filter_types": {}, "media_types": {}}

# ── Stock behaviour ──────────────────────────────────────────────────────────
# Off until someone turns it on, deliberately: stock has to be counted before
# automatic deduction means anything, and a figure that started from a guess
# never recovers. Shared through the catalogue, so it is switched on once for
# the company rather than on each PC.
STOCK_SETTINGS = {"auto_deduct": False}

# Kinds of thing this business sells, beyond the filters the app was built
# around. A quote has to be able to carry a bag filter, a roll of media, a
# service call or whatever gets added next — so the list is data, saved to the
# shared catalogue, rather than something that needs a new release each time.
#
# `unit` is what one of them is counted in and is printed on the quote.
DEFAULT_PRODUCT_TYPES = [
    {"name": "Bag Filter",     "unit": "each"},
    {"name": "Media Roll",     "unit": "roll"},
    {"name": "Panel Filter",   "unit": "each"},
    {"name": "Carbon Filter",  "unit": "each"},
    {"name": "HEPA Filter",    "unit": "each"},
    {"name": "Filter Housing", "unit": "each"},
    {"name": "Frame",          "unit": "each"},
    {"name": "Gasket / Seal",  "unit": "m"},
    {"name": "Freight",        "unit": "each"},
    {"name": "Labour",         "unit": "hour"},
]
PRODUCT_TYPES = [dict(p) for p in DEFAULT_PRODUCT_TYPES]


def product_type_names() -> list:
    return [p.get("name", "") for p in PRODUCT_TYPES if p.get("name")]


def product_type_unit(name: str) -> str:
    key = (name or "").strip().lower()
    for p in PRODUCT_TYPES:
        if (p.get("name") or "").strip().lower() == key:
            return p.get("unit") or "each"
    return "each"


def _merge_corrections(data) -> None:
    """Fold a stored corrections map into the live one."""
    if not isinstance(data, dict):
        return
    for bucket in ("filter_types", "media_types"):
        got = data.get(bucket)
        if isinstance(got, dict):
            PO_CORRECTIONS[bucket].update(
                {str(k): str(v) for k, v in got.items() if k and v})


def _apply_catalog(data: dict) -> None:
    """Overwrite the in-memory preset tables from a catalogue dict."""
    gd = data.get("gd_packs")
    if isinstance(gd, dict) and gd:
        DEDICATED_FILTER_PACKS.clear()
        DEDICATED_FILTER_PACKS.update(gd)
    sig = data.get("sigrist_pack")
    if isinstance(sig, dict) and sig.get("filters"):
        SIGRIST_PACK.clear()
        SIGRIST_PACK.update(sig)
    st = data.get("stepped_packs")
    if isinstance(st, dict) and st:
        STEPPED_PACKS.clear()
        STEPPED_PACKS.update(st)
    _merge_corrections(data.get("po_corrections"))
    stock = data.get("stock_settings")
    if isinstance(stock, dict) and "auto_deduct" in stock:
        STOCK_SETTINGS["auto_deduct"] = bool(stock["auto_deduct"])
    kinds = data.get("product_types")
    if isinstance(kinds, list) and kinds:
        cleaned = [{"name": str(k.get("name", "")).strip(),
                    "unit": str(k.get("unit", "") or "each").strip()}
                   for k in kinds if isinstance(k, dict) and k.get("name")]
        if cleaned:
            PRODUCT_TYPES.clear()
            PRODUCT_TYPES.extend(cleaned)


def _load_catalog_cache() -> None:
    try:
        if CATALOG_CACHE_FILE.exists():
            _apply_catalog(json.loads(CATALOG_CACHE_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass


def _save_catalog_cache() -> None:
    try:
        CATALOG_CACHE_FILE.write_text(json.dumps({
            "gd_packs":        DEDICATED_FILTER_PACKS,
            "sigrist_pack":    SIGRIST_PACK,
            "stepped_packs":   STEPPED_PACKS,
            "po_corrections":  PO_CORRECTIONS,
            "stock_settings":  STOCK_SETTINGS,
            "product_types":   PRODUCT_TYPES,
        }, indent=2), encoding="utf-8")
    except Exception:
        pass


def _persist_catalog_key(key: str, value, parent=None, quiet: bool = False) -> bool:
    """Save one catalogue list to the shared DB (+ local cache). Returns
    True if the shared save worked; shows a helpful error if not.

    `quiet` is for saves the user didn't ask for — the local cache still keeps
    the change, and a dialog would only interrupt whatever they were doing."""
    _save_catalog_cache()
    if not (_db.is_ready() and _db.current_user()):
        return False
    try:
        _db.set_catalog_value(key, value)
        _db.log_action("catalog_changed", f"Updated {key}")
        return True
    except Exception as exc:
        if quiet:
            return False
        try:
            messagebox.showerror(
                "Database Error",
                "The change is applied on this PC, but couldn't be saved to "
                f"the shared database:\n{exc}\n\n"
                "If this mentions a missing 'catalog_lists' table, run "
                "migrate_catalog.sql in the Supabase SQL Editor.",
                parent=parent)
        except Exception:
            pass
        return False


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


# Tk accepts colour names as well as hex, and the app uses "white" for button
# text in about fifty places. Blending one of those — which is what disabling
# a button does — used to try to read "wh" as a hexadecimal number and crash
# the screen being built.
_NAMED_COLOURS = {
    "white": "#FFFFFF", "black": "#000000", "red": "#FF0000",
    "green": "#008000", "blue": "#0000FF", "grey": "#808080",
    "gray": "#808080", "yellow": "#FFFF00", "orange": "#FFA500",
}


def _rgb(c: str):
    h = _NAMED_COLOURS.get(str(c).strip().lower(), str(c)).lstrip("#")
    if len(h) == 3:                       # #abc is shorthand for #aabbcc
        h = "".join(ch * 2 for ch in h)
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        # An unrecognised colour name. Mid-grey blends to something sane and
        # keeps the window up, which beats a half-drawn tab.
        return 128, 128, 128


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
        # A cached PhotoImage belongs to the Tk window it was created under.
        # After sign-out the whole window is rebuilt, and using a stale image
        # raises TclError ('image "pyimageN" doesn't exist') — which silently
        # killed list refreshes (items not appearing after Save). Verify the
        # image is still alive; if not, drop it and re-render.
        try:
            cached.tk.call("image", "type", str(cached))
            return cached
        except Exception:
            _BADGE_CACHE.pop(key, None)
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
                 hover=None, font=None, h=None, padx=None, radius=None,
                 bgbase=None):
        h = px(36) if h is None else h
        padx = px(16) if padx is None else padx
        radius = max(px(4), int(h * 0.26)) if radius is None else radius
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
             width=None, font=F_BOLD, pady=6, padx=14,
             variant=None) -> "PillButton":
    """Rounded pill button (Canvas-based). `width` (char count) is ignored —
    pills size to their text.

    `variant` sets the weight of the button rather than its colour, so a
    screen can have one obvious action and a row of quieter ones instead of
    six saturated rectangles competing for the eye:

        "primary"   filled, brand blue — the thing to do on this screen
        "secondary" tinted, quiet — supporting actions
        "ghost"     text only until hovered — the least important
        "danger"    filled red — deleting things

    Callers that pass an explicit `bg` keep exactly what they asked for, so
    every existing button is untouched.
    """
    if variant:
        bg, fg = _BUTTON_VARIANTS.get(variant, (bg, fg))
    return PillButton(parent, text, command=command, bg=bg, fg=fg,
                      font=font, h=px(pady * 2 + 24), padx=px(padx))


def _button_variants() -> dict:
    """Built fresh each time so a dark-mode swap is picked up."""
    return {
        "primary":   (CA, "white"),
        "secondary": (_blend(CA, CCA, 0.88), CA),
        "ghost":     (CCA, CMU),
        "danger":    (CRD, "white"),
        "success":   (CGR, "white"),
    }


class _VariantMap(dict):
    """Looks the colours up when asked, not when the module was imported."""

    def get(self, key, default=None):
        return _button_variants().get(key, default)


_BUTTON_VARIANTS = _VariantMap()


def attach_empty_state(tree, title, hint="", action=None, action_text=""):
    """Say what an empty table means, and what to do about it.

    A blank white rectangle tells someone nothing — not whether the list is
    empty, still loading, or filtered down to nothing. This puts a line of
    plain English in the middle of it, and takes itself away the moment there
    is a row to show.

    It hooks the tree's own insert and delete so no caller has to remember to
    keep it in step.
    """
    holder = tree.master
    panel = tk.Frame(holder, bg=CCA)
    tk.Label(panel, text=title, bg=CCA, fg=CTX, font=F_SEC).pack()
    if hint:
        tk.Label(panel, text=hint, bg=CCA, fg=CMU, font=F_BODY,
                 justify="center").pack(pady=(px(4), 0))
    if action and action_text:
        flat_btn(panel, action_text, action, bg=CA,
                 pady=px(6)).pack(pady=(px(12), 0))

    def _sync():
        try:
            if tree.get_children():
                panel.place_forget()
            else:
                panel.place(relx=0.5, rely=0.42, anchor="center")
        except Exception:
            pass

    for name in ("insert", "delete"):
        original = getattr(tree, name)

        def wrapped(*a, _orig=original, **kw):
            result = _orig(*a, **kw)
            tree.after_idle(_sync)
            return result

        setattr(tree, name, wrapped)

    tree.after_idle(_sync)
    tree._empty_state = panel      # keep a reference so it isn't collected
    return panel


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


# ── Sharpness on a modern screen ──────────────────────────────────────────
# Almost every laptop sold in the last few years runs Windows at 125% or 150%
# scaling. A program that doesn't say it understands that is drawn by Windows
# at 96 DPI and then stretched like a photograph - every letter and every line
# smeared across a fraction of a pixel. That is what "pixelated" looks like,
# and no amount of restyling fixes it.
#
# Saying so has to happen before the first window exists, so this is called at
# the very top of start-up. Windows 8.1 and later have the per-monitor call;
# older ones only have the system-wide one; anything else is not Windows and
# has nothing to do.

UI_SCALE = 1.0          # set from the real screen once Tk is up


def _enable_hidpi() -> None:
    """Tell Windows this program draws its own pixels. Must run before Tk."""
    if sys.platform != "win32":
        return
    import ctypes
    try:
        # 2 = per-monitor aware: correct when a laptop is docked to a second
        # screen at a different scaling, which is the normal office setup.
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass            # an old Windows, or already set by the launcher


def _apply_ui_scale(root) -> float:
    """Match Tk's idea of a point to the actual screen, and remember by how much.

    Tk sizes fonts in points and everything else in pixels. Once the program is
    DPI-aware, Tk sees the true resolution, so the text comes out the right
    physical size on its own - but anything measured in pixels does not, and a
    row sized for 96 DPI clips its own text at 150%. UI_SCALE is what the rest
    of the file multiplies those by.
    """
    global UI_SCALE
    try:
        dpi = float(root.winfo_fpixels("1i"))
    except Exception:
        dpi = 96.0
    # Ignore nonsense from an odd X server, and don't scale below 1: shrinking
    # the layout to fit a mis-reported DPI is worse than leaving it alone.
    scale = min(3.0, max(1.0, dpi / 96.0))
    UI_SCALE = scale
    try:
        root.tk.call("tk", "scaling", dpi / 72.0)
    except Exception:
        pass
    return scale


def px(value: float) -> int:
    """A pixel measurement that keeps its physical size on a high-DPI screen."""
    return int(round(value * UI_SCALE))


# ── Style helper (called once at startup) ─────────────────────────────────

def _configure_ttk_style():
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass

    # ── Tables ────────────────────────────────────────────────────────────
    # Rows given room to breathe, and a heading that reads as a label rather
    # than a heavy navy bar: quiet background, brand-blue rule underneath,
    # and the row text is what the eye lands on.
    style.configure("TAF.Treeview",
                    background=CCA,
                    fieldbackground=CCA,
                    foreground=CTX,
                    font=F_BODY,
                    rowheight=px(32),
                    borderwidth=0,
                    relief="flat")
    style.configure("TAF.Treeview.Heading",
                    background=CHD,
                    foreground=CHT,
                    font=F_BOLD,
                    relief="flat",
                    borderwidth=0,
                    padding=(px(10), px(9)))
    style.map("TAF.Treeview",
              background=[("selected", CSL)],
              foreground=[("selected", CTX)])
    style.map("TAF.Treeview.Heading",
              background=[("active", _blend(CHD, CA, 0.10))],
              foreground=[("active", CA)])
    # clam draws a sunken frame around a Treeview; this removes it so the
    # table sits flush inside its card instead of in a box within a box.
    try:
        style.layout("TAF.Treeview", [
            ("Treeview.treearea", {"sticky": "nswe"})])
    except Exception:
        pass

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

    # ── Scrollbars ────────────────────────────────────────────────────────
    # The default is the grey 3D bar with a raised arrow button at each end,
    # and it is the single most dated thing on the screen. This is a thin
    # rounded thumb on a quiet trough, and no arrows - the same shape every
    # other program has used for a decade.
    for orient in ("Vertical", "Horizontal"):
        style.configure(f"{orient}.TScrollbar",
                        background=_blend(CMU, CBG, 0.62),   # the thumb
                        troughcolor=CBG,
                        bordercolor=CBG,
                        lightcolor=CBG, darkcolor=CBG,
                        borderwidth=0,
                        relief="flat",
                        gripcount=0,
                        arrowsize=px(1),        # 0 is rejected; 1 hides them
                        width=px(11))
        style.map(f"{orient}.TScrollbar",
                  background=[("pressed", CA),
                              ("active", _blend(CMU, CBG, 0.35))])

    # ── Fields ────────────────────────────────────────────────────────────
    style.configure("TEntry",
                    fieldbackground=CFD, background=CFD, foreground=CTX,
                    bordercolor=CSP, lightcolor=CSP, darkcolor=CSP,
                    insertcolor=CTX, padding=(px(8), px(6)), relief="flat")
    style.map("TEntry",
              bordercolor=[("focus", CA)],
              lightcolor=[("focus", CA)], darkcolor=[("focus", CA)])

    style.configure("TSeparator", background=CSP)

    style.configure("TAF.TCheckbutton", background=CCA, foreground=CTX,
                    font=F_BODY, focuscolor=CCA)
    style.map("TAF.TCheckbutton", background=[("active", CCA)])

    # ── Progress ──────────────────────────────────────────────────────────
    style.configure("TAF.Horizontal.TProgressbar",
                    troughcolor=_blend(CSP, CCA, 0.4),
                    background=CA, bordercolor=CBG,
                    lightcolor=CA, darkcolor=CA,
                    borderwidth=0, thickness=px(6))


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
        self.configure(bg=CSP, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR)
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

class _PresetRowDialog(tk.Toplevel):
    """Small modal for one preset row (a mounting frame or a filter).

    `fields` is a list of (key, label, kind) where kind is "int" or "str".
    result = None if cancelled, else {key: value}.
    """

    def __init__(self, master, title, fields, initial=None):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.configure(bg=CBG)
        self.result = None
        initial = initial or {}
        self._fields = fields

        hdr = tk.Frame(self, bg=CA, padx=14, pady=8)
        hdr.pack(fill="x", side="top")
        tk.Label(hdr, text=title, bg=CA, fg="white", font=F_BOLD).pack(anchor="w")

        foot = tk.Frame(self, bg=CBG, padx=16, pady=12)
        foot.pack(fill="x", side="bottom")
        flat_btn(foot, "Cancel", self.destroy, bg=CNE, pady=6).pack(side="right", padx=(6, 0))
        flat_btn(foot, "Save",   self._save,   bg=CGR, pady=6).pack(side="right")

        body = tk.Frame(self, bg=CBG, padx=16, pady=12)
        body.pack(fill="both", expand=True, side="top")
        self._vars = {}
        for i, (key, label, kind) in enumerate(fields):
            tk.Label(body, text=label, bg=CBG, fg=CTX,
                     font=F_BODY, anchor="w").grid(row=i, column=0, sticky="w", pady=4)
            v = tk.StringVar(value=str(initial.get(key, "") if initial.get(key) is not None else ""))
            self._vars[key] = v
            e = field_entry(body, textvariable=v, width=16)
            e.grid(row=i, column=1, sticky="ew", padx=(12, 0), pady=4)
            if i == 0:
                e.focus_set()
        body.columnconfigure(1, weight=1)

        self.bind("<Return>", lambda e: self._save())
        self.bind("<Escape>", lambda e: self.destroy())

    def _save(self):
        out = {}
        for key, label, kind in self._fields:
            raw = self._vars[key].get().strip()
            if kind == "int":
                try:
                    out[key] = int(raw)
                except Exception:
                    messagebox.showwarning(
                        "Invalid Number",
                        f"'{label}' must be a whole number.", parent=self)
                    return
                if out[key] <= 0:
                    messagebox.showwarning(
                        "Invalid Number",
                        f"'{label}' must be greater than zero.", parent=self)
                    return
            else:
                out[key] = raw
        self.result = out
        self.destroy()


class _GDModelEditor(tk.Toplevel):
    """Add / edit one Comp Air / Gardner Denver housing model: its name, its
    mounting frames and its filters. result = None or (name, pack dict)."""

    FRAME_FIELDS  = [("qty", "Quantity", "int"), ("short", "Short (mm)", "int"),
                     ("long", "Long (mm)", "int"), ("label", "Label (optional)", "str")]
    FILTER_FIELDS = [("qty", "Quantity", "int"), ("short", "Short (mm)", "int"),
                     ("long", "Long (mm)", "int"), ("channel", "Channel (mm)", "int"),
                     ("media", "Media (blank = G4)", "str"),
                     ("filter_type", "Filter Type (blank = V-form)", "str"),
                     ("label", "Label (optional)", "str")]

    def __init__(self, master, name="", pack=None):
        super().__init__(master)
        self.title("Edit Model" if name else "Add Model")
        self.transient(master)
        self.grab_set()
        self.configure(bg=CBG)
        self.result = None
        pack = pack or {}
        self._frames  = [dict(f) for f in pack.get("frames", [])]
        self._filters = [dict(f) for f in pack.get("filters", [])]

        hdr = tk.Frame(self, bg=CA, padx=16, pady=10)
        hdr.pack(fill="x", side="top")
        tk.Label(hdr, text=("Edit Model" if name else "Add Model"),
                 bg=CA, fg="white", font=(FAM, 11, "bold")).pack(anchor="w")
        tk.Label(hdr, text="Mounting frames become a note on the worksheet; "
                           "filters become the actual line items.",
                 bg=CA, fg="#A9CCE3", font=F_SM).pack(anchor="w")

        foot = tk.Frame(self, bg=CBG, padx=16, pady=10)
        foot.pack(fill="x", side="bottom")
        flat_btn(foot, "Cancel", self.destroy, bg=CNE, pady=7).pack(side="right", padx=(8, 0))
        flat_btn(foot, "Save",   self._save,   bg=CGR, pady=7).pack(side="right")

        body = tk.Frame(self, bg=CBG, padx=16, pady=12)
        body.pack(fill="both", expand=True, side="top")

        name_row = tk.Frame(body, bg=CBG)
        name_row.pack(fill="x", pady=(0, 10))
        tk.Label(name_row, text="Model name:", bg=CBG, fg=CTX,
                 font=F_BOLD).pack(side="left", padx=(0, 8))
        self._name_var = tk.StringVar(value=name)
        ent = field_entry(name_row, textvariable=self._name_var, width=24)
        ent.pack(side="left", fill="x", expand=True)
        if not name:
            ent.focus_set()

        self._frames_tree  = self._build_section(
            body, "Mounting Frames  (optional — housing orders only)",
            ("Qty", "Short", "Long", "Label"), self._frames, self.FRAME_FIELDS)
        self._filters_tree = self._build_section(
            body, "Filters",
            ("Qty", "Short", "Long", "Channel", "Media", "Type", "Label"),
            self._filters, self.FILTER_FIELDS)

        self._refresh_tree(self._frames_tree,  self._frames,
                           ("qty", "short", "long", "label"))
        self._refresh_tree(self._filters_tree, self._filters,
                           ("qty", "short", "long", "channel", "media",
                            "filter_type", "label"))

        self.update_idletasks()
        W, H = 620, 600
        self.geometry(f"{W}x{H}+{master.winfo_rootx()+40}+{max(0, master.winfo_rooty()-20)}")

    def _build_section(self, parent, title, columns, rows_ref, fields):
        tk.Label(parent, text=title, bg=CBG, fg=CA,
                 font=F_SEC, anchor="w").pack(anchor="w", pady=(6, 4))
        wrap = tk.Frame(parent, bg=CCA, highlightbackground=CSP, highlightthickness=1)
        wrap.pack(fill="both", expand=True)
        tree = ttk.Treeview(wrap, columns=columns, show="headings",
                            style="TAF.Treeview", height=5)
        for c in columns:
            tree.heading(c, text=c)
            tree.column(c, width=px(90), anchor="center",
                        stretch=(c == "Label"))
        tree.pack(fill="both", expand=True, padx=1, pady=1)

        bar = tk.Frame(parent, bg=CBG)
        bar.pack(anchor="w", pady=(4, 2))
        keys = tuple(f[0] for f in fields)
        flat_btn(bar, "+ Add", lambda: self._row_add(tree, rows_ref, fields, keys),
                 bg=CA,  pady=4, padx=8, font=F_SM).pack(side="left", padx=(0, 4))
        flat_btn(bar, "Edit",  lambda: self._row_edit(tree, rows_ref, fields, keys),
                 bg=CNE, pady=4, padx=8, font=F_SM).pack(side="left", padx=(0, 4))
        flat_btn(bar, "Remove", lambda: self._row_remove(tree, rows_ref, keys),
                 bg=CRD, pady=4, padx=8, font=F_SM).pack(side="left")
        return tree

    def _refresh_tree(self, tree, rows, keys):
        for iid in tree.get_children():
            tree.delete(iid)
        for i, r in enumerate(rows):
            tree.insert("", "end", iid=str(i),
                        values=tuple(r.get(k, "") for k in keys))

    def _row_add(self, tree, rows, fields, keys):
        dlg = _PresetRowDialog(self, "Add Row", fields)
        self.wait_window(dlg)
        try:
            self.grab_set()   # child dialog took the grab — take it back
        except Exception:
            pass
        if dlg.result:
            row = {k: v for k, v in dlg.result.items()
                   if not (isinstance(v, str) and not v)}
            rows.append(row)
            self._refresh_tree(tree, rows, keys)

    def _row_edit(self, tree, rows, fields, keys):
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("Edit Row", "Select a row first.", parent=self)
            return
        idx = int(sel[0])
        dlg = _PresetRowDialog(self, "Edit Row", fields, initial=rows[idx])
        self.wait_window(dlg)
        try:
            self.grab_set()   # child dialog took the grab — take it back
        except Exception:
            pass
        if dlg.result:
            rows[idx] = {k: v for k, v in dlg.result.items()
                         if not (isinstance(v, str) and not v)}
            self._refresh_tree(tree, rows, keys)

    def _row_remove(self, tree, rows, keys):
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("Remove Row", "Select a row first.", parent=self)
            return
        rows.pop(int(sel[0]))
        self._refresh_tree(tree, rows, keys)

    def _save(self):
        name = self._name_var.get().strip()
        if not name:
            messagebox.showwarning("Name Required",
                                   "Enter a model name.", parent=self)
            return
        if not self._filters:
            messagebox.showwarning("No Filters",
                                   "Add at least one filter row.", parent=self)
            return
        self.result = (name, {"frames": self._frames, "filters": self._filters})
        self.destroy()


class CompressorFilterDialog(tk.Toplevel):
    """
    Dedicated Filter Presets dialog — three tabs:
      1. Comp Air / Gardner Denver  (L11…L160-250V2)
      2. Sigrist                    (412×412×90, F5 media)
      3. Stepped Filters            (535×535×50 / 535×1135×50, 180 Media)

    result = None if cancelled, else {"items": [...], "job": str, "notes": str}
    """

    def __init__(self, master):
        super().__init__(master)
        # Managers and above can add/edit/remove the presets themselves
        # (shown offline too, so a dev copy without Supabase still has them).
        try:
            self._can_manage = (not _db.is_ready()) or bool(
                _db.current_user() and _db.can_manage_catalog())
        except Exception:
            self._can_manage = False
        self.title("Dedicated Filter Presets")
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
        tk.Label(hdr, text=("Select a preset — filter items will be added to the current order"
                            + ("   ·   presets can be added, edited and removed below"
                               if self._can_manage else "")),
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
        W, H = (660, 580) if self._can_manage else (600, 500)
        px = master.winfo_rootx() + master.winfo_width()  // 2 - W // 2
        py = master.winfo_rooty() + master.winfo_height() // 2 - H // 2
        self.geometry(f"{W}x{H}+{px}+{max(0, py)}")
        self.minsize(560, 460)

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
                   width=5, font=F_BODY, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR,
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

        # Model radio list — rebuilt whenever a model is added/edited/removed
        self._gd_model = tk.StringVar()
        self._gd_list_frame = tk.Frame(left, bg=CBG)
        self._gd_list_frame.pack(anchor="w", fill="y")
        self._gd_rebuild_models()

        if self._can_manage:
            mgr = tk.Frame(left, bg=CBG)
            mgr.pack(anchor="w", pady=(8, 0))
            flat_btn(mgr, "+ Add", self._gd_add_model,
                     bg=CA,  pady=4, padx=8, font=F_SM).pack(side="left", padx=(0, 4))
            flat_btn(mgr, "Edit",  self._gd_edit_model,
                     bg=CNE, pady=4, padx=8, font=F_SM).pack(side="left", padx=(0, 4))
            flat_btn(mgr, "Delete", self._gd_delete_model,
                     bg=CRD, pady=4, padx=8, font=F_SM).pack(side="left")

        right = tk.Frame(cols, bg=CBG)
        right.pack(side="left", fill="both", expand=True)
        tk.Label(right, text="Preview", bg=CBG, fg=CMU, font=F_SM).pack(anchor="w", pady=(0, 4))

        prev = tk.Frame(right, bg=CCA, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR, padx=10, pady=8)
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

    def _gd_rebuild_models(self, select=None):
        """(Re)draw the model radio list from DEDICATED_FILTER_PACKS."""
        for w in self._gd_list_frame.winfo_children():
            w.destroy()
        models = list(DEDICATED_FILTER_PACKS.keys())
        if select in models:
            self._gd_model.set(select)
        elif self._gd_model.get() not in models:
            self._gd_model.set(models[0] if models else "")
        for m in models:
            tk.Radiobutton(self._gd_list_frame, text=m, variable=self._gd_model,
                           value=m, bg=CBG, fg=CTX, font=F_BODY,
                           activebackground=CRE, selectcolor=CCA,
                           command=self._gd_update_preview, cursor="hand2"
                           ).pack(anchor="w", pady=1)
        if not models:
            tk.Label(self._gd_list_frame, text="(no models — add one)",
                     bg=CBG, fg=CMU, font=F_SM).pack(anchor="w")
        # Skipped on the first call: the preview widgets are built after this
        # list, and _build_gd_tab refreshes the preview itself at the end.
        if hasattr(self, "_gd_txt"):
            self._gd_update_preview()

    def _gd_add_model(self):
        dlg = _GDModelEditor(self)
        self.wait_window(dlg)
        try:
            self.grab_set()   # child dialog took the grab — take it back
        except Exception:
            pass
        if not dlg.result:
            return
        name, pack = dlg.result
        if name in DEDICATED_FILTER_PACKS:
            messagebox.showwarning("Duplicate",
                f'A model named "{name}" already exists.', parent=self)
            return
        DEDICATED_FILTER_PACKS[name] = pack
        _persist_catalog_key("gd_packs", DEDICATED_FILTER_PACKS, parent=self)
        self._gd_rebuild_models(select=name)

    def _gd_edit_model(self):
        model = self._gd_model.get()
        if not model or model not in DEDICATED_FILTER_PACKS:
            messagebox.showinfo("Edit Model", "Select a model first.", parent=self)
            return
        dlg = _GDModelEditor(self, name=model, pack=DEDICATED_FILTER_PACKS[model])
        self.wait_window(dlg)
        try:
            self.grab_set()   # child dialog took the grab — take it back
        except Exception:
            pass
        if not dlg.result:
            return
        new_name, pack = dlg.result
        if new_name != model and new_name in DEDICATED_FILTER_PACKS:
            messagebox.showwarning("Duplicate",
                f'A model named "{new_name}" already exists.', parent=self)
            return
        # Rebuild preserving list order (so a rename keeps its position)
        rebuilt = {}
        for k, v in DEDICATED_FILTER_PACKS.items():
            if k == model:
                rebuilt[new_name] = pack
            else:
                rebuilt[k] = v
        DEDICATED_FILTER_PACKS.clear()
        DEDICATED_FILTER_PACKS.update(rebuilt)
        _persist_catalog_key("gd_packs", DEDICATED_FILTER_PACKS, parent=self)
        self._gd_rebuild_models(select=new_name)

    def _gd_delete_model(self):
        model = self._gd_model.get()
        if not model or model not in DEDICATED_FILTER_PACKS:
            messagebox.showinfo("Delete Model", "Select a model first.", parent=self)
            return
        if not messagebox.askyesno(
                "Delete Model",
                f'Delete the "{model}" preset?\n\n'
                "Existing orders are unaffected — this only removes the preset "
                "from this dialog.", parent=self, icon="warning", default="no"):
            return
        DEDICATED_FILTER_PACKS.pop(model, None)
        _persist_catalog_key("gd_packs", DEDICATED_FILTER_PACKS, parent=self)
        self._gd_rebuild_models()

    def _gd_update_preview(self):
        model   = self._gd_model.get()
        is_rep  = self._gd_order_type.get() == "rep"
        pack    = DEDICATED_FILTER_PACKS.get(model)
        if pack is None:
            self._gd_lbl_job.config(text="—")
            self._gd_txt.config(state="normal")
            self._gd_txt.delete("1.0", "end")
            self._gd_txt.insert("end", "(no model selected)")
            self._gd_txt.config(state="disabled")
            return
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
            lines.append(f"  {fl.get('filter_type', 'V-form')}  "
                         f"{fl['short']}x{fl['long']}x{fl['channel']}mm  "
                         f"{fl.get('media', 'G4')}  x{qty}{lbl}")
        self._gd_txt.config(state="normal")
        self._gd_txt.delete("1.0", "end")
        self._gd_txt.insert("end", "\n".join(lines) or "(no items)")
        self._gd_txt.config(state="disabled")

    # ── Tab 2: Sigrist ────────────────────────────────────────────────────

    def _build_sigrist_tab(self, nb):
        frm = tk.Frame(nb, bg=CBG, padx=20, pady=16)
        nb.add(frm, text="  Sigrist  ")

        top = tk.Frame(frm, bg=CBG)
        top.pack(fill="x")
        tk.Label(top, text="Sigrist Filter",
                 bg=CBG, fg=CA, font=F_SEC, anchor="w").pack(side="left")
        if self._can_manage:
            flat_btn(top, "Edit Spec", self._sigrist_edit,
                     bg=CNE, pady=4, padx=10, font=F_SM).pack(side="right")
        tk.Frame(frm, bg=CSP, height=1).pack(fill="x", pady=(6, 10))

        self._sigrist_spec_frame = tk.Frame(frm, bg=CBG)
        self._sigrist_spec_frame.pack(fill="x")

        tk.Frame(frm, bg=CSP, height=1).pack(fill="x", pady=(14, 8))

        qty_row = tk.Frame(frm, bg=CBG)
        qty_row.pack(anchor="w", pady=(0, 8))
        tk.Label(qty_row, text="Quantity:", bg=CBG, fg=CTX,
                 font=F_BOLD).pack(side="left", padx=(0, 10))
        self._sigrist_qty = tk.StringVar(value="1")
        tk.Spinbox(qty_row, from_=1, to=50, textvariable=self._sigrist_qty,
                   width=5, font=F_BODY, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR).pack(side="left")

        self._sigrist_hint = tk.Label(frm, text="", bg=CBG, fg=CMU,
                                      font=F_SM, justify="left")
        self._sigrist_hint.pack(anchor="w")
        self._sigrist_refresh()

    def _sigrist_spec(self) -> dict:
        """The single Sigrist filter spec (falling back to the default)."""
        fl = (SIGRIST_PACK.get("filters") or [{}])[0]
        return fl or dict(DEFAULT_SIGRIST_PACK["filters"][0])

    def _sigrist_refresh(self):
        fl = self._sigrist_spec()
        for w in self._sigrist_spec_frame.winfo_children():
            w.destroy()
        specs = [
            ("Dimensions",  f"{fl.get('short','')} x {fl.get('long','')} x "
                            f"{fl.get('channel','')} mm"),
            ("Filter Type", fl.get("filter_type", "V-form")),
            ("Media",       fl.get("media", "F5")),
        ]
        note = fl.get("note", "BLANK F5 Labels To be used!")
        if note:
            specs.append(("Note", note))
        for label, value in specs:
            row = tk.Frame(self._sigrist_spec_frame, bg=CBG)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=f"{label}:", bg=CBG, fg=CMU,
                     font=F_BOLD, width=14, anchor="w").pack(side="left")
            fg = CRD if label == "Note" else CTX
            tk.Label(row, text=value, bg=CBG, fg=fg,
                     font=F_BODY, anchor="w").pack(side="left")
        self._sigrist_hint.config(
            text="Clicking 'Add to Order' will add the selected quantity of\n"
                 f"{fl.get('filter_type','V-form')} "
                 f"{fl.get('short','')}x{fl.get('long','')}x{fl.get('channel','')}mm "
                 f"filters with {fl.get('media','F5')} media.")

    def _sigrist_edit(self):
        fields = [("short", "Short (mm)", "int"), ("long", "Long (mm)", "int"),
                  ("channel", "Channel (mm)", "int"),
                  ("filter_type", "Filter Type", "str"), ("media", "Media", "str"),
                  ("note", "Note (optional)", "str")]
        cur = dict(self._sigrist_spec())
        cur.setdefault("note", "BLANK F5 Labels To be used!")
        dlg = _PresetRowDialog(self, "Edit Sigrist Spec", fields, initial=cur)
        self.wait_window(dlg)
        try:
            self.grab_set()   # child dialog took the grab — take it back
        except Exception:
            pass
        if not dlg.result:
            return
        spec = dict(dlg.result)
        spec["qty"] = 1
        if not spec.get("filter_type"):
            spec["filter_type"] = "V-form"
        if not spec.get("media"):
            spec["media"] = "F5"
        SIGRIST_PACK.clear()
        SIGRIST_PACK["filters"] = [spec]
        _persist_catalog_key("sigrist_pack", SIGRIST_PACK, parent=self)
        self._sigrist_refresh()

    # ── Tab 3: Stepped Filters ────────────────────────────────────────────

    def _build_stepped_tab(self, nb):
        frm = tk.Frame(nb, bg=CBG, padx=20, pady=16)
        nb.add(frm, text="  Stepped Filters  ")

        top = tk.Frame(frm, bg=CBG)
        top.pack(fill="x")
        tk.Label(top, text="Stepped Filter Presets",
                 bg=CBG, fg=CA, font=F_SEC, anchor="w").pack(side="left")
        if self._can_manage:
            flat_btn(top, "Delete", self._stepped_delete,
                     bg=CRD, pady=4, padx=8, font=F_SM).pack(side="right")
            flat_btn(top, "Edit",   self._stepped_edit,
                     bg=CNE, pady=4, padx=8, font=F_SM).pack(side="right", padx=(0, 4))
            flat_btn(top, "+ Add",  self._stepped_add,
                     bg=CA,  pady=4, padx=8, font=F_SM).pack(side="right", padx=(0, 4))
        tk.Frame(frm, bg=CSP, height=1).pack(fill="x", pady=(6, 12))

        self._stepped_model = tk.StringVar()
        self._stepped_list_frame = tk.Frame(frm, bg=CBG)
        self._stepped_list_frame.pack(fill="x")
        self._stepped_rebuild()

        tk.Frame(frm, bg=CSP, height=1).pack(fill="x", pady=(12, 10))

        specs = [
            ("Filter Type", "Stepped Filter — 50mm (40mm V-form + 9mm flyscreen)"),
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
                   width=5, font=F_BODY, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR).pack(side="left")

        tk.Label(frm,
                 text="Clicking 'Add to Order' will add the selected quantity of\n"
                      "Stepped Filter items with 180 Media.",
                 bg=CBG, fg=CMU, font=F_SM, justify="left").pack(anchor="w")

    # ── Stepped preset management ─────────────────────────────────────────

    def _stepped_rebuild(self, select=None):
        for w in self._stepped_list_frame.winfo_children():
            w.destroy()
        keys = list(STEPPED_PACKS.keys())
        if select in keys:
            self._stepped_model.set(select)
        elif self._stepped_model.get() not in keys:
            self._stepped_model.set(keys[0] if keys else "")
        for key in keys:
            fl = (STEPPED_PACKS[key].get("filters") or [{}])[0]
            label = (f"{fl.get('short','')} x {fl.get('long','')} x "
                     f"{fl.get('channel','')} mm") if fl else key
            tk.Radiobutton(self._stepped_list_frame, text=label,
                           variable=self._stepped_model, value=key,
                           bg=CBG, fg=CTX, font=F_BODY,
                           activebackground=CRE, selectcolor=CCA, cursor="hand2"
                           ).pack(anchor="w", pady=3)
        if not keys:
            tk.Label(self._stepped_list_frame, text="(no sizes — add one)",
                     bg=CBG, fg=CMU, font=F_SM).pack(anchor="w")

    _STEPPED_FIELDS = [("short", "Short (mm)", "int"), ("long", "Long (mm)", "int"),
                       ("channel", "Channel (mm)", "int"), ("media", "Media", "str")]

    def _stepped_save(self, spec: dict, replacing: str = None):
        spec = dict(spec)
        spec["qty"] = 1
        spec["filter_type"] = "Stepped Filter"
        if not spec.get("media"):
            spec["media"] = "180"
        key = f"{spec['short']}x{spec['long']}x{spec['channel']}"
        if key != replacing and key in STEPPED_PACKS:
            messagebox.showwarning("Duplicate",
                f"A {spec['short']} x {spec['long']} x {spec['channel']} mm "
                "preset already exists.", parent=self)
            return None
        rebuilt = {}
        if replacing and replacing in STEPPED_PACKS:
            for k, v in STEPPED_PACKS.items():
                rebuilt[key if k == replacing else k] = (
                    {"filters": [spec]} if k == replacing else v)
        else:
            rebuilt = dict(STEPPED_PACKS)
            rebuilt[key] = {"filters": [spec]}
        STEPPED_PACKS.clear()
        STEPPED_PACKS.update(rebuilt)
        _persist_catalog_key("stepped_packs", STEPPED_PACKS, parent=self)
        self._stepped_rebuild(select=key)
        return key

    def _stepped_add(self):
        dlg = _PresetRowDialog(self, "Add Stepped Size", self._STEPPED_FIELDS,
                               initial={"media": "180"})
        self.wait_window(dlg)
        try:
            self.grab_set()   # child dialog took the grab — take it back
        except Exception:
            pass
        if dlg.result:
            self._stepped_save(dlg.result)

    def _stepped_edit(self):
        key = self._stepped_model.get()
        if not key or key not in STEPPED_PACKS:
            messagebox.showinfo("Edit Size", "Select a size first.", parent=self)
            return
        cur = (STEPPED_PACKS[key].get("filters") or [{}])[0]
        dlg = _PresetRowDialog(self, "Edit Stepped Size", self._STEPPED_FIELDS,
                               initial=cur)
        self.wait_window(dlg)
        try:
            self.grab_set()   # child dialog took the grab — take it back
        except Exception:
            pass
        if dlg.result:
            self._stepped_save(dlg.result, replacing=key)

    def _stepped_delete(self):
        key = self._stepped_model.get()
        if not key or key not in STEPPED_PACKS:
            messagebox.showinfo("Delete Size", "Select a size first.", parent=self)
            return
        if not messagebox.askyesno(
                "Delete Size",
                f'Delete the "{key}" stepped-filter preset?\n\n'
                "Existing orders are unaffected.",
                parent=self, icon="warning", default="no"):
            return
        STEPPED_PACKS.pop(key, None)
        _persist_catalog_key("stepped_packs", STEPPED_PACKS, parent=self)
        self._stepped_rebuild()

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
        pack    = DEDICATED_FILTER_PACKS.get(model)
        if pack is None:
            messagebox.showinfo("No Model",
                                "Select a model first.", parent=self)
            return
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
                "Filter Type": fl.get("filter_type", "V-form"),
                "Media Type":  fl.get("media", "G4"),
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
        fl   = self._sigrist_spec()
        note = fl.get("note", "BLANK F5 Labels To be used!")
        self.result = {
            "items": [{
                "item_kind": "filter", "Quantity": qty,
                "Filter Type": fl.get("filter_type", "V-form"),
                "Media Type":  fl.get("media", "F5"),
                "Short":   fl.get("short", 412),
                "Long":    fl.get("long", 412),
                "Channel": fl.get("channel", 90),
                "Pleat Insert": False, "Header": False,
                "Use Stock V-form": False, "Use Stock Flyscreen": False,
                "Notes": note,
            }],
            "job":   "",
            "notes": note,
        }
        self.destroy()

    def _confirm_stepped(self):
        key  = self._stepped_model.get()
        pack = STEPPED_PACKS.get(key)
        if not pack or not pack.get("filters"):
            messagebox.showinfo("No Size", "Select a size first.", parent=self)
            return
        fl   = pack["filters"][0]
        try:
            qty = max(1, int(self._stepped_qty.get()))
        except Exception:
            qty = 1
        self.result = {
            "items": [{
                "item_kind": "filter", "Quantity": fl.get("qty", 1) * qty,
                "Filter Type": fl.get("filter_type", "Stepped Filter"),
                "Media Type":  fl.get("media", "180"),
                "Short": fl.get("short"), "Long": fl.get("long"),
                "Channel": fl.get("channel"),
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

    def __init__(self, master, title="Line Item", initial=None, media_types=None,
                 filter_types=None):
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
        # Keep the exact lists shown in the dropdowns — Save must validate
        # against THESE (built-ins + custom types), not the built-in lists
        # alone, or any custom type gets rejected and the item never saves.
        self._media_types  = list(_media_types)
        self._filter_types = list(filter_types) if filter_types else list(VALID_FILTER_TYPES)

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
                               relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR, padx=16, pady=14)
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
                 "·   30+ (45 & 50 included) → V-form / Pleated",
            bg=CCA, fg=CMU, font=F_SM, anchor="w")
        self._auto_hint.grid(row=1, column=0, columnspan=4, sticky="w", pady=(10, 0))

        # ── Classification ────────────────────────────────────────────────
        cls_f = tk.LabelFrame(body, text=" Classification ",
                               bg=CCA, fg=CA, font=F_SEC,
                               relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR, padx=16, pady=14)
        cls_f.pack(fill="x", pady=(0, 12))

        for col, (key, vals) in enumerate([
            ("Filter Type", self._filter_types),
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
            om.config(relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR, bg=CBG, fg=CTX,
                      font=F_BODY, anchor="w",
                      activebackground=CRE, activeforeground=CTX, cursor="hand2", padx=8, pady=4)
            om["menu"].config(bg=CCA, fg=CTX, font=F_BODY,
                              activebackground=CA, activeforeground="white")
            om.pack(fill="x", pady=(3, 0))

        # Auto-set Filter/Media Type from the channel thickness as the user
        # types. Attached AFTER the initial values are set so editing an
        # existing item does not clobber its saved classification on open.
        self.vars["Channel"].trace_add("write", self._on_channel_change)
        # A stepped filter is always 50mm overall, so choosing it fills the
        # thickness in rather than leaving it to be typed (and mistyped).
        self.vars["Filter Type"].trace_add("write", self._on_filter_type_change)

        # ── Options ───────────────────────────────────────────────────────
        opt_f = tk.LabelFrame(body, text=" Options ",
                               bg=CCA, fg=CA, font=F_SEC,
                               relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR, padx=16, pady=14)
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
                              relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR, padx=16, pady=14)
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
                                  font=F_BODY, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR,
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

        A stepped filter is left alone: it is 50mm by definition, and 50mm
        would otherwise read as a plain V-form and overwrite the choice.
        """
        if self.vars["Filter Type"].get().strip() == "Stepped Filter":
            return
        ft, mt = classify_by_channel(self.vars["Channel"].get())
        if ft:
            self.vars["Filter Type"].set(ft)
        if mt:
            self.vars["Media Type"].set(mt)
        elif ft and self.vars["Media Type"].get().strip().upper() == "GREY":
            self.vars["Media Type"].set("G4")

    def _on_filter_type_change(self, *_):
        """A stepped filter is a 40mm V-form plus its 9mm flyscreen — 50mm
        overall, and 180 media, every time. Both are filled in on choosing it
        so neither has to be remembered."""
        if self.vars["Filter Type"].get().strip() != "Stepped Filter":
            return
        if self.vars["Channel"].get().strip() != str(_pn.STEPPED_THICKNESS):
            self.vars["Channel"].set(str(_pn.STEPPED_THICKNESS))
        if self.vars["Media Type"].get().strip() != _pn.STEPPED_MEDIA:
            self.vars["Media Type"].set(_pn.STEPPED_MEDIA)

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

        if ft not in self._filter_types and ft not in VALID_FILTER_TYPES:
            messagebox.showerror("Invalid Input",
                                 "Please select a valid Filter Type.", parent=self)
            return
        # Validate against the dropdown's own list (built-ins + custom types) —
        # checking VALID_MEDIA_TYPES alone rejected every custom media type.
        if mt not in self._media_types and mt not in VALID_MEDIA_TYPES:
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


class CatalogueLineDialog(tk.Toplevel):
    """Add anything that isn't a made-to-measure filter.

    Two ways in, on one screen. Search the price list — twelve thousand part
    numbers, and every one of them quotable — or type a product in by hand for
    a one-off. Either way the line carries its own price, so nothing has to be
    worked back from dimensions it doesn't have.

    The product-type list is shared and editable, so a kind of thing this
    business starts selling next year needs a new entry, not a new release.
    """

    def __init__(self, master, title="Add Product", initial=None,
                 product_types=None, on_lookup=None):
        super().__init__(master)
        self.title(title)
        self.configure(bg=CBG, padx=px(18), pady=px(16))
        self.resizable(False, False)
        self.transient(master)
        self.result = None
        self._on_lookup = on_lookup          # (search) -> [price rows]
        self._matches = []
        initial = initial or {}

        types = list(product_types or []) or ["Item"]

        tk.Label(self, text="Search the price list",
                 bg=CBG, fg=CA, font=F_SEC).grid(row=0, column=0, columnspan=3,
                                                 sticky="w")
        tk.Label(self, text="Part number or description — pick one and the "
                            "price comes with it.",
                 bg=CBG, fg=CMU, font=F_SM).grid(row=1, column=0, columnspan=3,
                                                 sticky="w", pady=(0, px(6)))

        self.search_var = tk.StringVar()
        se = field_entry(self, textvariable=self.search_var, width=38)
        se.grid(row=2, column=0, columnspan=2, sticky="ew")
        se.bind("<Return>", lambda _e: self._search())
        flat_btn(self, "Search", self._search, bg=CA,
                 pady=px(5)).grid(row=2, column=2, sticky="w", padx=(px(8), 0))

        self.results = tk.Listbox(self, height=7, width=58, font=F_BODY,
                                  bg=CCA, fg=CTX, highlightthickness=1,
                                  highlightbackground=CSP, relief="flat",
                                  activestyle="none",
                                  selectbackground=CSL, selectforeground=CTX)
        self.results.grid(row=3, column=0, columnspan=3, sticky="ew",
                          pady=(px(6), px(2)))
        self.results.bind("<<ListboxSelect>>", self._take_match)
        self.results.bind("<Double-Button-1>", lambda _e: self._save())

        self._hint = tk.StringVar(value="")
        tk.Label(self, textvariable=self._hint, bg=CBG, fg=CMU,
                 font=F_SM, anchor="w").grid(row=4, column=0, columnspan=3,
                                             sticky="w", pady=(0, px(10)))

        ttk.Separator(self, orient="horizontal").grid(
            row=5, column=0, columnspan=3, sticky="ew", pady=(0, px(10)))

        tk.Label(self, text="The line", bg=CBG, fg=CA,
                 font=F_SEC).grid(row=6, column=0, columnspan=3, sticky="w",
                                  pady=(0, px(6)))

        self.vars = {
            "Product Type": tk.StringVar(value=initial.get("Product Type") or types[0]),
            "Part Number":  tk.StringVar(value=initial.get("Part Number", "")),
            "Description":  tk.StringVar(value=initial.get("Description", "")),
            "Quantity":     tk.StringVar(value=str(initial.get("Quantity", "1"))),
            "Unit":         tk.StringVar(value=initial.get("Unit", "each")),
            "Unit Price":   tk.StringVar(value=str(initial.get("Unit Price", ""))),
        }

        row = 7
        tk.Label(self, text="Product type", bg=CBG, fg=CTX,
                 font=F_BODY).grid(row=row, column=0, sticky="w", pady=px(3))
        cb = ttk.Combobox(self, textvariable=self.vars["Product Type"],
                          values=types, state="readonly", width=26)
        cb.grid(row=row, column=1, columnspan=2, sticky="w", padx=(px(8), 0))
        cb.bind("<<ComboboxSelected>>", self._type_changed)
        row += 1

        for label, key, width in (("Part number", "Part Number", 26),
                                  ("Description", "Description", 38)):
            tk.Label(self, text=label, bg=CBG, fg=CTX,
                     font=F_BODY).grid(row=row, column=0, sticky="w", pady=px(3))
            field_entry(self, textvariable=self.vars[key], width=width).grid(
                row=row, column=1, columnspan=2, sticky="w", padx=(px(8), 0))
            row += 1

        qty_row = tk.Frame(self, bg=CBG)
        qty_row.grid(row=row, column=0, columnspan=3, sticky="w", pady=px(3))
        tk.Label(qty_row, text="Quantity", bg=CBG, fg=CTX,
                 font=F_BODY).pack(side="left")
        field_entry(qty_row, textvariable=self.vars["Quantity"], width=7).pack(
            side="left", padx=(px(8), px(4)))
        field_entry(qty_row, textvariable=self.vars["Unit"], width=8).pack(
            side="left", padx=(0, px(16)))
        tk.Label(qty_row, text="Unit price  $", bg=CBG, fg=CTX,
                 font=F_BODY).pack(side="left")
        pe = field_entry(qty_row, textvariable=self.vars["Unit Price"], width=11)
        pe.pack(side="left", padx=(px(4), 0))
        row += 1

        self._total = tk.StringVar(value="")
        tk.Label(self, textvariable=self._total, bg=CBG, fg=CTX,
                 font=F_BOLD, anchor="e").grid(row=row, column=0, columnspan=3,
                                               sticky="e", pady=(px(8), px(4)))
        for key in ("Quantity", "Unit Price"):
            self.vars[key].trace_add("write", lambda *_a: self._retotal())
        self._retotal()
        row += 1

        btns = tk.Frame(self, bg=CBG)
        btns.grid(row=row, column=0, columnspan=3, sticky="e", pady=(px(10), 0))
        flat_btn(btns, "Cancel", self.destroy, bg=CNE,
                 pady=px(6)).pack(side="left", padx=(0, px(8)))
        flat_btn(btns, "Add to Quote", self._save, bg=CGR,
                 pady=px(6)).pack(side="left")

        self.columnconfigure(1, weight=1)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Return>", lambda _e: self._save())
        se.focus_set()
        self.grab_set()

    # ── the price list ────────────────────────────────────────────────────
    def _search(self):
        term = self.search_var.get().strip()
        self.results.delete(0, "end")
        self._matches = []
        if not term:
            self._hint.set("Type a part number or a few words first.")
            return
        if not self._on_lookup:
            self._hint.set("The price list isn't loaded on this PC.")
            return
        self._hint.set("Searching…")
        self.update_idletasks()
        try:
            rows = self._on_lookup(term) or []
        except Exception as exc:
            self._hint.set(f"Couldn't search the price list: {exc}")
            return
        self._matches = rows[:200]
        for r in self._matches:
            name = (r.get("name") or r.get("description") or "").replace("\n", " ")
            price = float(r.get("unit_price") or 0)
            self.results.insert("end",
                                f"{r.get('part_number', ''):<22} "
                                f"{name[:44]:<46} ${price:,.2f}")
        if not self._matches:
            self._hint.set(f"Nothing in the price list matches “{term}”. "
                           "You can still type the product in below.")
        else:
            more = " (showing the first 200)" if len(rows) > 200 else ""
            self._hint.set(f"{len(rows):,} match{'es' if len(rows) != 1 else ''}"
                           f"{more} — click one to use it.")

    def _take_match(self, _event=None):
        sel = self.results.curselection()
        if not sel or sel[0] >= len(self._matches):
            return
        row = self._matches[sel[0]]
        self.vars["Part Number"].set(row.get("part_number", ""))
        self.vars["Description"].set(
            (row.get("name") or row.get("description") or "").replace("\n", " "))
        self.vars["Unit Price"].set(f'{float(row.get("unit_price") or 0):.2f}')
        self._retotal()

    def _type_changed(self, _event=None):
        # Only fill the unit in if it hasn't been touched — never overwrite
        # something someone deliberately typed.
        if self.vars["Unit"].get().strip() in ("", "each", "roll", "hour", "m"):
            self.vars["Unit"].set(product_type_unit(self.vars["Product Type"].get()))

    def _retotal(self):
        try:
            qty = float(self.vars["Quantity"].get().strip() or 0)
            unit = float(self.vars["Unit Price"].get().strip() or 0)
        except ValueError:
            self._total.set("")
            return
        self._total.set(f"Line total   ${qty * unit:,.2f}" if qty and unit else "")

    def _save(self):
        try:
            qty = int(float(self.vars["Quantity"].get().strip()))
        except ValueError:
            messagebox.showerror("Quantity",
                                 "Quantity must be a number.", parent=self)
            return
        if qty <= 0:
            messagebox.showerror("Quantity",
                                 "Quantity must be more than zero.", parent=self)
            return
        price_text = self.vars["Unit Price"].get().strip().lstrip("$")
        try:
            unit = float(price_text or 0)
        except ValueError:
            messagebox.showerror("Unit price",
                                 "The unit price must be a number.", parent=self)
            return
        desc = self.vars["Description"].get().strip()
        part = self.vars["Part Number"].get().strip().upper()
        if not desc and not part:
            messagebox.showerror(
                "Nothing to quote",
                "Give the line a description, or pick a part number from the "
                "price list — otherwise the customer sees a blank line.",
                parent=self)
            return
        if unit <= 0 and not messagebox.askyesno(
                "No price",
                "This line has no price, so it will show on the quote as "
                "\"to be confirmed\" and be left out of the total.\n\nAdd it "
                "anyway?", parent=self, icon="warning", default="no"):
            return

        self.result = {
            "item_kind":    "catalogue",
            "Product Type": self.vars["Product Type"].get().strip(),
            "Part Number":  part,
            "Description":  desc,
            "Quantity":     qty,
            "Unit":         self.vars["Unit"].get().strip() or "each",
            "Unit Price":   round(unit, 4),
            "_price_source": "list" if unit > 0 else "",
        }
        self.destroy()


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
        om_pt.config(relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR, bg=CCA, fg=CTX, font=F_BODY,
                     width=16, anchor="w", activebackground=CRE,
                     activeforeground=CTX, cursor="hand2")
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
        self.om_preset.config(relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR, bg=CCA, fg=CTX, font=F_BODY,
                              width=28, anchor="w", activebackground=CRE,
                              activeforeground=CTX, cursor="hand2")
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
        self.om_media.config(relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR, bg=CCA, fg=CTX, font=F_BODY,
                             width=10, anchor="w", activebackground=CRE, cursor="hand2")
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
        self.var_bhdr    = tk.BooleanVar(value=bool(d.get("header")))
        self.var_half    = tk.BooleanVar(value=bool(d.get("half_size")))

        chk_defs = [
            ("On Wire",      self.var_wire,    0, 0),
            ("Gelled",       self.var_gelled,  0, 1),
            ("Special Size", self.var_special, 0, 2),
            ("Header",       self.var_bhdr,    1, 0),
            ("Half Size",    self.var_half,    1, 1),
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
                                  font=F_BODY, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR,
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
            "header":       bool(self.var_bhdr.get()),
            "half_size":    bool(self.var_half.get()),
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
# Imported Purchase Order Review
# ═══════════════════════════════════════════════════════════════════════════

class JobNumberHighlighter(tk.Toplevel):
    """Teach the app where a customer puts their job number.

    Show one of their purchase orders, drag a box around the job number, and
    the app reads that piece and keeps the WORDING in front of the number
    ("Our Reference:") rather than the position on the page — wording survives
    a layout change, a remembered position does not.

    result = None if cancelled, else the label to save.
    """

    MAX_W, MAX_H = 900, 620

    def __init__(self, master, image_path=None):
        super().__init__(master)
        self.title("Where is the Job Number?")
        self.transient(master)
        self.grab_set()
        self.configure(bg=CBG)
        self.result = None
        self._img = None
        self._photo = None
        self._scale = 1.0
        self._start = None
        self._rect = None

        hdr = tk.Frame(self, bg=CA, padx=16, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Where is the Job Number?", bg=CA, fg="white",
                 font=(FAM, 12, "bold")).pack(anchor="w")
        tk.Label(hdr, text="Open one of this customer's purchase orders and drag a "
                           "box around their job number — include the words in front of it.",
                 bg=CA, fg="#A9CCE3", font=F_SM).pack(anchor="w")

        bar = tk.Frame(self, bg=CBG, padx=16, pady=8)
        bar.pack(fill="x")
        flat_btn(bar, "📁  Open a Purchase Order", self._pick_image,
                 bg=CA, pady=6, padx=14, font=F_BODY).pack(side="left")
        self._status = tk.StringVar(
            value="Open a photo or scan of one of their purchase orders.")
        tk.Label(bar, textvariable=self._status, bg=CBG, fg=CMU,
                 font=F_SM, anchor="w").pack(side="left", padx=(12, 0))

        wrap = tk.Frame(self, bg=CCA, highlightbackground=CSP, highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=16)
        self._canvas = tk.Canvas(wrap, bg="#3A3A3A", highlightthickness=0,
                                 width=self.MAX_W, height=self.MAX_H, cursor="cross")
        self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<ButtonPress-1>",   self._drag_start)
        self._canvas.bind("<B1-Motion>",       self._drag_move)
        self._canvas.bind("<ButtonRelease-1>", self._drag_end)

        res = tk.Frame(self, bg=CBG, padx=16, pady=10)
        res.pack(fill="x")
        tk.Label(res, text="Job number appears after:", bg=CBG, fg=CTX,
                 font=F_BOLD).pack(side="left", padx=(0, 8))
        self._label_var = tk.StringVar()
        field_entry(res, textvariable=self._label_var, width=30).pack(side="left")
        self._found = tk.Label(res, text="", bg=CBG, fg=CMU, font=F_SM)
        self._found.pack(side="left", padx=(10, 0))

        foot = tk.Frame(self, bg=CBG, padx=16, pady=12)
        foot.pack(fill="x")
        flat_btn(foot, "Cancel", self.destroy, bg=CNE, pady=7).pack(side="right", padx=(8, 0))
        flat_btn(foot, "Save",   self._save,   bg=CGR, pady=7).pack(side="right")
        tk.Label(foot, text="You can also just type the wording yourself.",
                 bg=CBG, fg=CMU, font=F_SM).pack(side="left")

        self.update_idletasks()
        self.geometry(f"+{max(0, master.winfo_rootx() + 20)}"
                      f"+{max(0, master.winfo_rooty() + 10)}")
        if image_path:
            self._load_image(image_path)

    # ── Loading the page ──────────────────────────────────────────────────

    def _pick_image(self):
        path = filedialog.askopenfilename(
            title="Open a purchase order",
            parent=self,
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.webp *.bmp"),
                       ("All files", "*.*")])
        if path:
            self._load_image(path)

    def _load_image(self, path):
        try:
            from PIL import Image, ImageTk
        except Exception as exc:
            messagebox.showerror("Can't Show Image",
                                 f"Image support is unavailable:\n{exc}", parent=self)
            return
        if str(path).lower().endswith(".pdf"):
            messagebox.showinfo(
                "Use an Image",
                "Highlighting works on a photo or scan.\n\n"
                "For a PDF, take a screenshot of the page (or photograph it) "
                "and open that instead — or just type the wording in below.",
                parent=self)
            return
        try:
            img = Image.open(path)
            img.load()
            img = img.convert("RGB")
        except Exception as exc:
            messagebox.showerror("Couldn't Open",
                                 f"That image couldn't be opened:\n{exc}", parent=self)
            return

        self._img = img
        # Fit to the canvas, remembering the scale so the box can be mapped
        # back to full-resolution pixels before cropping.
        self._scale = min(self.MAX_W / img.width, self.MAX_H / img.height, 1.0)
        disp = img.resize((max(1, int(img.width * self._scale)),
                           max(1, int(img.height * self._scale))), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(disp)
        self._canvas.delete("all")
        self._canvas.config(width=disp.width, height=disp.height)
        self._canvas.create_image(0, 0, anchor="nw", image=self._photo)
        self._rect = None
        self._status.set("Now drag a box around the job number.")

    # ── Dragging the box ──────────────────────────────────────────────────

    def _drag_start(self, e):
        if self._img is None:
            return
        self._start = (e.x, e.y)
        if self._rect:
            self._canvas.delete(self._rect)
        self._rect = self._canvas.create_rectangle(e.x, e.y, e.x, e.y,
                                                   outline="#E74C3C", width=2)

    def _drag_move(self, e):
        if self._start and self._rect:
            self._canvas.coords(self._rect, self._start[0], self._start[1], e.x, e.y)

    def _drag_end(self, e):
        if not (self._start and self._img):
            return
        x0, y0 = self._start
        x1, y1 = e.x, e.y
        self._start = None
        if abs(x1 - x0) < 8 or abs(y1 - y0) < 8:
            self._status.set("That box was too small — drag across the job number.")
            return
        self._read_region(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

    def _read_region(self, x0, y0, x1, y1):
        """Crop what was highlighted and ask what wording introduces it."""
        from PIL import Image
        s = self._scale or 1.0
        # A little margin, so the wording just outside the box still counts.
        pad = 12
        box = (max(0, int(x0 / s) - pad), max(0, int(y0 / s) - pad),
               min(self._img.width,  int(x1 / s) + pad),
               min(self._img.height, int(y1 / s) + pad))
        crop = self._img.crop(box)
        # Upscale a small crop — a few words at screen resolution are easier
        # to read enlarged.
        if crop.width < 600:
            f = min(3.0, 600 / max(1, crop.width))
            crop = crop.resize((int(crop.width * f), int(crop.height * f)), Image.LANCZOS)

        import io
        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        data = buf.getvalue()

        self._status.set("Reading the highlighted area…")
        self.update_idletasks()

        def _work():
            try:
                got = _po_import.read_job_label(data)
                err = ""
            except _po_import.POImportError as exc:
                got, err = None, str(exc)
            except Exception as exc:
                got, err = None, f"Couldn't read that area:\n{exc}"

            def _done():
                if err:
                    self._status.set("Couldn't read that area.")
                    messagebox.showerror("Couldn't Read", err, parent=self)
                    return
                label = got.get("label", "")
                value = got.get("value", "")
                if label:
                    self._label_var.set(label)
                    self._status.set("Check it looks right, then Save.")
                else:
                    self._status.set(
                        "No wording found in front of that number — type it below.")
                self._found.config(
                    text=(f'found "{value}"' if value else "") +
                         ("   (unsure — please check)"
                          if got.get("confidence") == "low" else ""))
            self.after(0, _done)

        threading.Thread(target=_work, daemon=True).start()

    def _save(self):
        label = self._label_var.get().strip()
        if not label:
            messagebox.showwarning(
                "Nothing to Save",
                "Highlight the job number, or type the wording that comes "
                "before it.", parent=self)
            return
        self.result = label
        self.destroy()


class _UnknownMediaDialog(tk.Toplevel):
    """A purchase order asked for a media grade that isn't on the list.

    Rather than silently substituting one, ask: add it, or use a grade we do
    stock. result = None if cancelled, else ("create", name) or ("swap", other).
    """

    def __init__(self, master, name, known):
        super().__init__(master)
        self.title("Unknown Media Type")
        self.transient(master)
        self.grab_set()
        self.resizable(False, False)
        self.configure(bg=CBG)
        self.result = None

        hdr = tk.Frame(self, bg=CA, padx=16, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text=f'Media "{name}" isn\'t on the list',
                 bg=CA, fg="white", font=(FAM, 12, "bold")).pack(anchor="w")
        tk.Label(hdr, text="A purchase order asked for it. What should this order use?",
                 bg=CA, fg="#A9CCE3", font=F_SM).pack(anchor="w")

        body = tk.Frame(self, bg=CBG, padx=18, pady=16)
        body.pack(fill="both", expand=True)

        choice = tk.StringVar(value="create")
        tk.Radiobutton(body, text=f'Add "{name}" as a new media type',
                       variable=choice, value="create", bg=CBG, fg=CTX,
                       font=F_BODY, activebackground=CBG, selectcolor=CCA,
                       cursor="hand2").pack(anchor="w")
        tk.Label(body, text="   Shared with every PC, and usable on future orders.",
                 bg=CBG, fg=CMU, font=F_SM).pack(anchor="w", pady=(0, 10))

        tk.Radiobutton(body, text="Use a media type we already have:",
                       variable=choice, value="swap", bg=CBG, fg=CTX,
                       font=F_BODY, activebackground=CBG, selectcolor=CCA,
                       cursor="hand2").pack(anchor="w")
        alt = tk.StringVar(value=(known[0] if known else ""))
        ttk.Combobox(body, textvariable=alt, state="readonly",
                     values=list(known), width=26).pack(anchor="w", padx=(24, 0), pady=(4, 0))
        tk.Label(body, text="   Every line asking for "
                            f'"{name}" on this import will use it instead.',
                 bg=CBG, fg=CMU, font=F_SM).pack(anchor="w", pady=(4, 0))

        foot = tk.Frame(self, bg=CBG, padx=18, pady=12)
        foot.pack(fill="x")

        def _ok():
            if choice.get() == "create":
                self.result = ("create", name)
            else:
                if not alt.get():
                    messagebox.showwarning("Pick One",
                        "Choose a media type to use instead.", parent=self)
                    return
                self.result = ("swap", alt.get())
            self.destroy()

        flat_btn(foot, "Cancel Import", self.destroy, bg=CNE, pady=7).pack(side="right", padx=(8, 0))
        flat_btn(foot, "Continue",      _ok,          bg=CGR, pady=7).pack(side="right")

        self.update_idletasks()
        W = max(430, self.winfo_reqwidth())
        H = self.winfo_reqheight()
        self.geometry(f"{W}x{H}+{master.winfo_rootx()+master.winfo_width()//2-W//2}"
                      f"+{max(0, master.winfo_rooty()+140)}")


def _int_or_zero(value) -> int:
    """Parse a dimension; 0 for anything unreadable (which is a fault worth
    flagging, never a value to quietly generate a filter from)."""
    try:
        return int(str(value).strip())
    except Exception:
        return 0

class POReviewDialog(tk.Toplevel):
    """Check what was read out of an uploaded purchase order before anything
    is manufactured.

    Every field stays editable, each line shows the text it was read from, and
    anything the reader was unsure about is highlighted — a misread dimension
    costs a scrapped filter, so nothing generates until a person has looked.

    result = None if cancelled, else a list of {"header", "items"} to generate.
    """

    CONF_COLORS = {
        "low":    ("#FDECEC", "#C0392B"),
        "medium": ("#FFF3CD", "#856404"),
    }

    def __init__(self, master, orders, media_types=None, filter_types=None,
                 on_create_customer=None):
        super().__init__(master)
        self.title("Review Imported Purchase Orders")
        self.transient(master)
        self.grab_set()
        self.configure(bg=CBG)
        self.result = None
        # What the corrections made in here taught the app; read by the caller
        # after the dialog closes.
        self.learned = {"filter_types": {}, "media_types": {}}
        self._orders = orders
        self._media_types  = media_types  or list(DEFAULT_MEDIA_TYPES)
        self._filter_types = filter_types or list(VALID_FILTER_TYPES)
        self._current = None
        self._on_create_customer = on_create_customer
        for o in self._orders:
            o.setdefault("include", True)

        n = len(orders)
        hdr = tk.Frame(self, bg=CA, padx=16, pady=10)
        hdr.pack(fill="x", side="top")
        tk.Label(hdr, text=f"Found {n} purchase order{'s' if n != 1 else ''}",
                 bg=CA, fg="white", font=(FAM, 12, "bold")).pack(anchor="w")
        tk.Label(hdr, text="Check every line against the document — amber and red "
                           "rows are ones the reader wasn't sure about.",
                 bg=CA, fg="#A9CCE3", font=F_SM).pack(anchor="w")

        foot = tk.Frame(self, bg=CBG, padx=16, pady=10)
        foot.pack(fill="x", side="bottom")
        flat_btn(foot, "Cancel", self._cancel, bg=CNE, pady=8).pack(side="right", padx=(8, 0))
        self._go_btn = flat_btn(foot, "Generate & Print", self._confirm, bg=CGR, pady=8)
        self._go_btn.pack(side="right")
        self._count_lbl = tk.Label(foot, text="", bg=CBG, fg=CMU, font=F_SM)
        self._count_lbl.pack(side="left")

        body = tk.Frame(self, bg=CBG, padx=14, pady=12)
        body.pack(fill="both", expand=True, side="top")
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # ── Left: the orders found ────────────────────────────────────────
        left = tk.Frame(body, bg=CBG)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        tk.Label(left, text="Orders", bg=CBG, fg=CMU, font=F_SM).pack(anchor="w")
        lb_wrap = tk.Frame(left, bg=CSP)
        lb_wrap.pack(fill="both", expand=True)
        self._order_lb = tk.Listbox(lb_wrap, font=F_BODY, bg=CCA, fg=CTX,
                                    selectbackground=CA, selectforeground="white",
                                    activestyle="none", relief="flat", bd=0,
                                    highlightthickness=0, width=32, height=16)
        self._order_lb.pack(fill="both", expand=True, padx=1, pady=1)
        self._order_lb.bind("<<ListboxSelect>>", lambda e: self._on_select())

        self._include_var = tk.BooleanVar(value=True)
        tk.Checkbutton(left, text="Include this order", variable=self._include_var,
                       command=self._toggle_include, bg=CBG, fg=CTX, font=F_BODY,
                       activebackground=CBG, selectcolor=CCA,
                       cursor="hand2").pack(anchor="w", pady=(8, 0))

        # ── Right: the selected order ─────────────────────────────────────
        right = tk.Frame(body, bg=CBG)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)

        cust_bar = tk.Frame(right, bg=CCA, highlightbackground=CSP,
                            highlightthickness=1, padx=10, pady=8)
        cust_bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self._cust_lbl = tk.Label(cust_bar, text="", bg=CCA, fg=CTX, font=F_BODY,
                                  justify="left", anchor="w", wraplength=520)
        self._cust_lbl.pack(side="left", fill="x", expand=True)
        self._cust_btn = flat_btn(cust_bar, "Create Profile",
                                  self._make_customer, bg=CA, pady=5, padx=12,
                                  font=F_BODY)
        self._cust_btn.pack(side="right")

        self._warn_lbl = tk.Label(right, text="", bg="#FDECEC", fg="#C0392B",
                                  font=F_SM, justify="left", anchor="w",
                                  wraplength=640, padx=10, pady=6)

        hf = tk.LabelFrame(right, text=" Order Details ", bg=CCA, fg=CA,
                           font=F_SEC, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR, padx=12, pady=10)
        hf.grid(row=2, column=0, sticky="ew")
        self._hvars = {}
        fields = [("Customer Name", True), ("Order Number", True),
                  ("Date Ordered", True), ("Date Due", False),
                  ("Attention", False), ("Job", False),
                  ("Location", True), ("Notes", False)]
        for i, (key, required) in enumerate(fields):
            r, c = divmod(i, 2)
            sub = tk.Frame(hf, bg=CCA)
            sub.grid(row=r, column=c, sticky="ew", padx=(0, 14), pady=3)
            hf.columnconfigure(c, weight=1)
            tk.Label(sub, text=key.upper() + (" *" if required else ""),
                     bg=CCA, fg=(CRD if required else CMU),
                     font=F_BOLD).pack(anchor="w")
            v = tk.StringVar()
            self._hvars[key] = v
            v.trace_add("write", lambda *_a, k=key: self._on_header_edit(k))
            if key == "Order Number":
                # The commonest reason a read order is blocked: the document
                # never carried a number. Fixing it should be one click.
                row_f = tk.Frame(sub, bg=CCA)
                row_f.pack(fill="x", pady=(2, 0))
                field_entry(row_f, textvariable=v, width=18).pack(
                    side="left", fill="x", expand=True)
                btn = tk.Button(row_f, text="TAF #",
                                command=self._supplied_number_for_current,
                                bg=CA, fg="white", relief="flat", bd=0,
                                font=(FAM, 8, "bold"), padx=7, pady=2,
                                cursor="hand2", activebackground=_dk(CA),
                                activeforeground="white")
                btn.pack(side="left", padx=(4, 0))
                _Tooltip(btn, "No purchase order number on the document? "
                              "Give it one of ours.")
            else:
                field_entry(sub, textvariable=v, width=24).pack(fill="x",
                                                                pady=(2, 0))

        itf = tk.Frame(right, bg=CBG)
        itf.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        itf.rowconfigure(1, weight=1)
        itf.columnconfigure(0, weight=1)
        tk.Label(itf, text="Line items — double-click to correct one",
                 bg=CBG, fg=CMU, font=F_SM).grid(row=0, column=0, sticky="w")

        tw = tk.Frame(itf, bg=CCA, highlightbackground=CSP, highlightthickness=1)
        tw.grid(row=1, column=0, sticky="nsew")
        tw.rowconfigure(0, weight=1)
        tw.columnconfigure(0, weight=1)
        cols = ("qty", "type", "size", "sqm", "media", "partno", "notes", "read")
        self._items_tree = ttk.Treeview(tw, columns=cols, show="headings",
                                        style="TAF.Treeview", height=8)
        self._items_tree.grid(row=0, column=0, sticky="nsew")
        for col, (txt, wd, anc, stretch) in {
            "qty":    ("Qty",            50,  "center", False),
            "type":   ("Filter Type",    120, "w",      False),
            "size":   ("Size (mm)",      140, "center", False),
            "sqm":    ("m²",              58, "center", False),
            "media":  ("Media",           74, "center", False),
            "partno": ("Part Number",    140, "w",      False),
            "notes":  ("Notes",          140, "w",      True),
            "read":   ("Read from PO",   220, "w",      True),
        }.items():
            self._items_tree.heading(col, text=txt,
                                     anchor="center" if anc == "center" else "w")
            self._items_tree.column(col, width=px(wd), anchor=anc, minwidth=px(40),
                                    stretch=stretch)
        for level, (bg, fg) in self.CONF_COLORS.items():
            self._items_tree.tag_configure(level, background=bg, foreground=fg)
        self._items_tree.tag_configure("high", background=CCA)
        vsb = ttk.Scrollbar(tw, orient="vertical", command=self._items_tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self._items_tree.configure(yscrollcommand=vsb.set)
        self._items_tree.bind("<Double-1>", lambda e: self._edit_item())

        bar = tk.Frame(itf, bg=CBG)
        bar.grid(row=2, column=0, sticky="w", pady=(6, 0))
        flat_btn(bar, "Edit Item",   self._edit_item,
                 bg=CNE, pady=5, padx=10, font=F_BODY).pack(side="left", padx=(0, 6))
        flat_btn(bar, "Remove Item", self._remove_item,
                 bg=CRD, pady=5, padx=10, font=F_BODY).pack(side="left")

        self._refresh_order_list()
        if self._orders:
            self._order_lb.selection_set(0)
            self._on_select()

        self.update_idletasks()
        W, H = 1040, 720
        self.geometry(f"{W}x{H}+{max(0, master.winfo_rootx() + 40)}"
                      f"+{max(0, master.winfo_rooty() + 10)}")
        self.minsize(880, 560)
        self.protocol("WM_DELETE_WINDOW", self._cancel)

    # ── Order list ────────────────────────────────────────────────────────

    def _missing_required(self, order) -> list:
        h = order["header"]
        return [k for k in ("Customer Name", "Order Number",
                            "Date Ordered", "Location")
                if not (h.get(k) or "").strip()]

    def _item_problems(self, order) -> list:
        """Line-item faults that would fail validation or make a wrong filter.

        Caught here rather than at generation, so the fix is a dropdown in
        this dialog instead of a confusing error part-way through a batch.
        """
        problems = []
        for n, it in enumerate(order["items"], start=1):
            ft = (it.get("Filter Type") or "").strip()
            mt = (it.get("Media Type") or "").strip()
            if ft not in self._filter_types:
                problems.append(
                    f"Line {n}: filter type "
                    + (f'"{ft}" isn\'t one the app knows' if ft else "is blank")
                    + " — edit the line to pick one.")
            if mt not in self._media_types:
                problems.append(
                    f"Line {n}: media "
                    + (f'"{mt}" isn\'t one the app knows' if mt else "is blank")
                    + " — edit the line to pick one.")
            missing_dims = [label for label, key in
                            (("short", "Short"), ("long", "Long"), ("channel", "Channel"))
                            if not _int_or_zero(it.get(key))]
            if missing_dims:
                problems.append(
                    f"Line {n}: {', '.join(missing_dims)} not read from the "
                    "document — check the size against the order.")
        return problems

    def _needs_customer(self, order) -> bool:
        """True while this order has no customer branch profile.

        Without one the order would be written under the legal name on the
        purchase order and with no delivery region — exactly the mix-up this
        is here to prevent — so it blocks.
        """
        return not (order.get("customer") or {}).get("id")

    def _needs_attention(self, order) -> bool:
        return bool(self._missing_required(order)
                    or not order["items"]
                    or self._needs_customer(order)
                    or self._item_problems(order))

    def _refresh_customer_bar(self):
        order = self._orders[self._current] if self._current is not None else None
        if order is None:
            return
        cust = order.get("customer") or {}
        po_name = order.get("po_customer_name") or "(no name read)"
        po_addr = order.get("po_customer_address") or ""
        if cust.get("id"):
            region = order["header"].get("Location") or "(no region)"
            self._cust_lbl.config(
                text=f"Customer:  {order['header'].get('Customer Name','')}"
                     f"      Region:  {region}\n"
                     f"Read from the order as: {po_name}"
                     + (f" — {po_addr}" if po_addr else ""),
                fg=CTX)
            self._cust_btn.config(text="Change", command=self._make_customer)
        else:
            self._cust_lbl.config(
                text=f"No customer profile for: {po_name}"
                     + (f"\n{po_addr}" if po_addr else "")
                     + "\nCreate one to set the short name and region that go on the order.",
                fg=CRD)
            self._cust_btn.config(text="Create Profile", command=self._make_customer)

    def _make_customer(self):
        if self._current is None or not self._on_create_customer:
            return
        order = self._orders[self._current]

        def _after():
            self._refresh_customer_bar()
            self._refresh_order_list()
            self._on_select()

        self._on_create_customer(order, _after)

    def _refresh_order_list(self):
        sel = self._order_lb.curselection()
        self._order_lb.delete(0, "end")
        for o in self._orders:
            h = o["header"]
            label = (h.get("Customer Name") or "(no customer)")[:22]
            on    = h.get("Order Number") or "—"
            mark  = "  " if o.get("include", True) else "✕ "
            flag  = ""
            if self._needs_attention(o):
                flag = "  ⚠"
            elif o.get("confidence") == "low":
                flag = "  ●"
            self._order_lb.insert(
                "end", f"{mark}{label}  ·  {on}  ({len(o['items'])}){flag}")
        for i, o in enumerate(self._orders):
            if not o.get("include", True):
                self._order_lb.itemconfig(i, fg=CMU)
            elif self._needs_attention(o) or o.get("confidence") == "low":
                self._order_lb.itemconfig(i, fg="#C0392B")
        if sel:
            self._order_lb.selection_set(sel[0])
        self._update_count()

    def _update_count(self):
        ready, blocked = 0, 0
        for o in self._orders:
            if not o.get("include", True):
                continue
            if self._needs_attention(o):
                blocked += 1
            else:
                ready += 1
        bits = [f"{ready} order{'s' if ready != 1 else ''} ready"]
        if blocked:
            bits.append(f"{blocked} still missing required fields (marked ⚠)")
        self._count_lbl.config(text="   ·   ".join(bits))

    def _on_select(self):
        sel = self._order_lb.curselection()
        if not sel:
            return
        self._current = sel[0]
        order = self._orders[self._current]
        self._loading = True
        for k, var in self._hvars.items():
            var.set(order["header"].get(k, ""))
        self._loading = False
        self._include_var.set(order.get("include", True))
        self._refresh_customer_bar()
        self._refresh_items()

        warns = list(order.get("warnings") or [])
        missing = self._missing_required(order)
        if missing:
            warns.insert(0, "Required field(s) still blank: " + ", ".join(missing))
        if not order["items"]:
            warns.insert(0, "This order has no line items.")
        if self._needs_customer(order):
            warns.insert(0, "No customer profile — create one so the order gets "
                            "the right short name and delivery region.")
        warns.extend(self._item_problems(order))
        if warns:
            self._warn_lbl.config(text="⚠  " + "\n⚠  ".join(warns))
            self._warn_lbl.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        else:
            self._warn_lbl.grid_remove()

    def _on_header_edit(self, key):
        if getattr(self, "_loading", False) or self._current is None:
            return
        self._orders[self._current]["header"][key] = self._hvars[key].get()
        self._refresh_order_list()

    def _toggle_include(self):
        if self._current is None:
            return
        self._orders[self._current]["include"] = bool(self._include_var.get())
        self._refresh_order_list()

    # ── Items ─────────────────────────────────────────────────────────────

    def _refresh_items(self):
        for iid in self._items_tree.get_children():
            self._items_tree.delete(iid)
        if self._current is None:
            return
        for i, it in enumerate(self._orders[self._current]["items"]):
            conf = (it.get("_confidence") or "high").lower()
            size = f"{it.get('Short','')} × {it.get('Long','')} × {it.get('Channel','')}"
            area = _pn.effective_area(it)
            self._items_tree.insert(
                "", "end", iid=str(i),
                tags=(conf if conf in self.CONF_COLORS else "high",),
                values=(it.get("Quantity", ""),
                        it.get("Filter Type", "") or "—",
                        size,
                        _pn.format_sqm(area) if area > 0 else "—",
                        it.get("Media Type", "") or "—",
                        it.get("Part Number", "") or "—",
                        it.get("Notes", ""),
                        it.get("_source_text", "")))

    def _selected_item_index(self):
        sel = self._items_tree.selection()
        return int(sel[0]) if sel else None

    def _edit_item(self):
        idx = self._selected_item_index()
        if idx is None or self._current is None:
            messagebox.showinfo("Edit Item", "Select a line item first.", parent=self)
            return
        items = self._orders[self._current]["items"]
        dlg = LineItemDialog(self, title="Correct Line Item", initial=items[idx],
                             media_types=self._media_types,
                             filter_types=self._filter_types)
        self.wait_window(dlg)
        try:
            self.grab_set()   # child dialog took the grab — take it back
        except Exception:
            pass
        if dlg.result:
            # A human has now confirmed this line, so it stops being flagged.
            # The review metadata is carried across the replacement — the
            # wording the document used is what a correction is learned from.
            keep = {k: v for k, v in items[idx].items() if k.startswith("_")}
            items[idx] = dict(dlg.result)
            items[idx].update(keep)
            items[idx]["_confidence"] = "high"
            self._refresh_items()
            self._on_select()

    def _remove_item(self):
        idx = self._selected_item_index()
        if idx is None or self._current is None:
            messagebox.showinfo("Remove Item", "Select a line item first.", parent=self)
            return
        self._orders[self._current]["items"].pop(idx)
        self._refresh_items()
        self._refresh_order_list()
        self._on_select()

    # ── Finish ────────────────────────────────────────────────────────────

    def _cancel(self):
        self.result = None
        self.destroy()

    def _confirm(self):
        approved = [o for o in self._orders if o.get("include", True)]
        if not approved:
            messagebox.showinfo("Nothing to Generate",
                                "No orders are ticked for import.", parent=self)
            return

        bad = [o for o in approved if self._needs_attention(o)]
        if bad:
            messagebox.showwarning(
                "Incomplete Orders",
                f"{len(bad)} of the ticked orders still need attention "
                "(marked ⚠ in the list).\n\n"
                "Fill in the missing fields, or untick those orders, then try "
                "again.", parent=self)
            return

        n = len(approved)
        if not messagebox.askyesno(
                "Generate Orders",
                f"Generate and print {n} order{'s' if n != 1 else ''}?\n\n"
                "Worksheets are created, saved to the shared database and sent "
                "to the printer — the same as pressing Generate Output on each "
                "one.", parent=self):
            return

        self.learned = self._collect_corrections(approved)
        self.result = [{
            "header": dict(o["header"]),
            "items":  [_po_import.strip_review_fields(i) for i in o["items"]],
        } for o in approved]
        self.destroy()

    def _supplied_number_for_current(self):
        """Give the order being reviewed one of our own numbers."""
        var = self._hvars.get("Order Number")
        if var is None:
            return
        existing = var.get().strip()
        if _pn.is_supplied_order_number(existing):
            messagebox.showinfo(
                "TAF Order Number",
                f"This order already has {existing}.", parent=self)
            return
        if existing and not messagebox.askyesno(
                "TAF Order Number",
                f'This order already has the number "{existing}".\n\n'
                "Replace it with one of ours?", default="no", parent=self):
            return
        try:
            var.set(_db.next_supplied_order_number())
        except Exception as exc:
            messagebox.showerror(
                "TAF Order Number",
                f"The next number could not be taken:\n{exc}\n\n"
                "If this mentions a missing function, run "
                "migrate_supplied_order_numbers.sql in the Supabase SQL "
                "Editor.", parent=self)

    def _collect_corrections(self, approved) -> dict:
        """What the wordings on these orders turned out to mean.

        Only wordings the app read differently from what was approved are
        recorded, so confirming a line the app already got right teaches it
        nothing new. Keyed by wording with punctuation stripped, so "V Filter"
        and "v-filter" are the same lesson.
        """
        learned = {"filter_types": {}, "media_types": {}}
        pairs = (("_read_filter_type", "Filter Type", "filter_types"),
                 ("_read_media_type",  "Media Type",  "media_types"))
        for o in approved:
            for it in o["items"]:
                for read_key, final_key, bucket in pairs:
                    written = (it.get(read_key) or "").strip()
                    final = (it.get(final_key) or "").strip()
                    if not written or not final:
                        continue
                    if written.lower() == final.lower():
                        continue        # read correctly — nothing to learn
                    key = _pn.wording_key(written)
                    if key:
                        learned[bucket][key] = final
        return learned


# ═══════════════════════════════════════════════════════════════════════════
# Quote
# ═══════════════════════════════════════════════════════════════════════════

class QuoteDialog(tk.Toplevel):
    """What an order comes to, line by line, before anything is sent out.

    Unpriced lines are shown in red rather than hidden or zeroed quietly:
    they are the reason a quote would go out wrong, so they are the thing the
    screen is loudest about.
    """

    def __init__(self, master, header, lines, customer=None,
                 prepared_by="", on_pdf=None, on_xero=None):
        super().__init__(master)
        self.title("Quote")
        self.configure(bg=CBG)
        self.transient(master)
        self.grab_set()
        self._lines = list(lines)
        self._header = header
        self._customer = customer or {}
        self._on_pdf = on_pdf
        self._on_xero = on_xero

        missing = _pricing.unpriced(self._lines)
        totals = _pricing.quote_totals(self._lines)

        hdr = tk.Frame(self, bg=CA, padx=16, pady=10)
        hdr.pack(fill="x")
        who = ((self._customer.get("short_name") or "").strip()
               or (header.get("Customer Name") or "").strip() or "—")
        tk.Label(hdr, text=f"Quote — {who}", bg=CA, fg="white",
                 font=(FAM, 12, "bold")).pack(anchor="w")
        tk.Label(hdr, text=f"Order {header.get('Order Number') or '—'}  ·  "
                           f"{len(self._lines)} line"
                           f"{'s' if len(self._lines) != 1 else ''}",
                 bg=CA, fg="#A9CCE3", font=F_SM).pack(anchor="w")

        foot = tk.Frame(self, bg=CBG, padx=16, pady=10)
        foot.pack(fill="x", side="bottom")
        flat_btn(foot, "Close", self.destroy, bg=CNE,
                 pady=8).pack(side="right", padx=(8, 0))
        flat_btn(foot, "Export for Xero", self._xero, bg=CA2,
                 pady=8).pack(side="right", padx=(8, 0))
        flat_btn(foot, "Save Quote PDF", self._pdf, bg=CGR,
                 pady=8).pack(side="right")

        tot_txt = (f"Subtotal  ${totals['subtotal']:,.2f}      "
                   f"GST  ${totals['gst']:,.2f}      "
                   f"Total  ${totals['total']:,.2f}")
        tk.Label(foot, text=tot_txt, bg=CBG, fg=CTX,
                 font=F_BOLD).pack(side="left")

        if missing:
            warn = tk.Frame(self, bg="#FDEDEC", padx=16, pady=8)
            warn.pack(fill="x", side="bottom")
            tk.Label(warn,
                     text=f"⚠  {len(missing)} line"
                          f"{'s have' if len(missing) != 1 else ' has'} no price. "
                          "The totals exclude them — add the part number to the "
                          "price list, or set a rate per m2, before sending "
                          "this out.",
                     bg="#FDEDEC", fg=CRD, font=F_SM,
                     justify="left", wraplength=760).pack(anchor="w")

        wrap = tk.Frame(self, bg=CCA, highlightbackground=CSP,
                        highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=16, pady=(12, 0))
        cols = ("part", "desc", "qty", "unit", "total", "src")
        tree = ttk.Treeview(wrap, columns=cols, show="headings",
                            style="TAF.Treeview", height=14)
        for col, (hd, wd, anc) in {
                "part":  ("Part Number", 130, "w"),
                "desc":  ("Description", 330, "w"),
                "qty":   ("Qty",          50, "center"),
                "unit":  ("Unit Price",   95, "e"),
                "total": ("Line Total",   95, "e"),
                "src":   ("Priced from",  240, "w")}.items():
            tree.heading(col, text=hd)
            tree.column(col, width=px(wd), anchor=anc,
                        stretch=(col == "desc"))
        tree.tag_configure("even", background=CRE)
        tree.tag_configure("odd", background=CCA)
        tree.tag_configure("missing", background="#FDEDEC", foreground=CRD)

        for i, line in enumerate(self._lines):
            priced = bool(line.get("source"))
            tree.insert("", "end",
                        tags=("missing" if not priced
                              else ("even" if i % 2 == 0 else "odd"),),
                        values=(
                            line.get("part_number") or "—",
                            line.get("description") or "",
                            line.get("quantity", 0),
                            f'{line.get("unit_price", 0):,.2f}' if priced else "—",
                            f'{line.get("line_total", 0):,.2f}' if priced else "—",
                            # For a priced line, where the price came from.
                            # For one that found none, why — a gap in the
                            # list reads very differently from a bad line.
                            _pricing.source_label(line),
                        ))
        tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        sb.pack(side="right", fill="y")
        tree.configure(yscrollcommand=sb.set)

        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        W, H = 900, 560
        self.geometry(f"{W}x{H}+{max(0, master.winfo_rootx() + 60)}"
                      f"+{max(0, master.winfo_rooty() + 40)}")
        self.minsize(720, 420)

    def _pdf(self):
        if self._on_pdf:
            self._on_pdf(self._header, self._lines, self._customer)

    def _xero(self):
        if self._on_xero:
            self._on_xero(self._header, self._lines, self._customer)


# ═══════════════════════════════════════════════════════════════════════════
# Main Application
# ═══════════════════════════════════════════════════════════════════════════

class ModernOrderApp(tk.Frame):

    def __init__(self, master):
        super().__init__(master, bg=CBG)
        self.master = master
        # Anchor order storage to APP_DIR (never cwd — see OrderService).
        # This also aligns saved order JSONs with ORDERS_DIR, where the
        # Previous Orders local scan looks for them.
        self.service = OrderService(APP_DIR)
        self.items: list = []
        self._all_orders_data: list = []
        self._tab_frames: dict = {}
        self._tab_buttons: dict = {}
        self._tab_loaded: dict = {}   # tab -> monotonic time of last data load (freshness cache)

        # Load persisted settings
        self._settings = _load_settings()
        self._custom_media: list = list(self._settings.get("custom_media_types", []))
        self._custom_filter_types: list = list(
            self._settings.get("custom_filter_types", []))
        # {media name: part-number code} — Carbon -> CARB, so a flat panel
        # comes out as FPFCARB25-020.
        self._media_codes: dict = dict(self._settings.get("media_codes", {}))
        # Presets/filter types come from the shared catalogue; start from the
        # last-known local copy so a slow or offline start still has them.
        _load_catalog_cache()

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

        # Push any orders queued while offline, then re-check every 5 minutes
        self.master.after(3000, self._start_pending_sync_loop)

        # Collect and read any purchase-order photos sent from a phone
        self.master.after(5000, self._start_phone_inbox_loop)

        # Pull the shared catalogue (presets + custom filter types)
        self.master.after(200, self._refresh_catalog_from_db)

        # First launch after an update → show that version's release notes once
        self.master.after(1500, self._maybe_show_whats_new)

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
        from taf_order_app.updater import latest_release, UpdateCheckError
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
            # One request, not two: the check used to ask GitHub twice per
            # click, which doubled how fast an office connection ran into
            # GitHub's 60-an-hour limit for the answer it already had.
            try:
                q.put(("ok", latest_release()))
            except UpdateCheckError as exc:
                q.put(("error", str(exc)))
            except Exception as exc:
                q.put(("error", str(exc) or exc.__class__.__name__))

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
                info = data
                v = info.get("version", "")
                if info.get("is_newer"):
                    self._upd_status_var.set(f"v{v} is available.")
                    self._pending_update = info
                    self._install_upd_btn.pack(side="left", padx=(8, 0))
                    self._update_banner_shown = False   # allow re-show
                    self._show_update_banner(info)
                    self._download_upd_btn.pack_forget()
                else:
                    # Only said when GitHub actually answered the question.
                    self._upd_status_var.set(
                        f"You're up to date. This PC is on v{APP_VERSION}, "
                        f"and the newest release is v{v}.")
                    self._install_upd_btn.pack_forget()
                    self._download_upd_btn.pack_forget()
            else:
                # A failed check is NOT "up to date" — saying so would leave
                # someone on an old build sure they were on the newest one.
                self._upd_status_var.set(
                    f"Couldn't check for updates — {data}. "
                    f"This PC is on v{APP_VERSION}.")
                self._install_upd_btn.pack_forget()
                self._download_upd_btn.pack(side="left", padx=(8, 0))

        threading.Thread(target=_work, daemon=True).start()
        self.master.after(150, _poll)

    def _open_releases_page(self):
        """Open the Releases page so the installer can be downloaded by hand."""
        import webbrowser
        from taf_order_app.updater import RELEASES_PAGE
        try:
            webbrowser.open(RELEASES_PAGE)
            self.status_var.set("Opened the Releases page in your browser.")
        except Exception:
            messagebox.showinfo(
                "Download the Update",
                "Open this page in a browser and download "
                f"TAFOrderEntry_Setup.exe:\n\n{RELEASES_PAGE}")

    def _open_user_management(self):
        from taf_order_app.user_management import UserManagementDialog
        UserManagementDialog(self.master)

    @property
    def all_media_types(self) -> list:
        """Default built-in types followed by any user-added custom types."""
        seen = set(DEFAULT_MEDIA_TYPES)
        custom = [m for m in self._custom_media if m not in seen]
        return DEFAULT_MEDIA_TYPES + custom

    @property
    def all_filter_types(self) -> list:
        """Built-in filter types followed by any user-added custom ones."""
        seen = set(VALID_FILTER_TYPES)
        custom = [f for f in getattr(self, "_custom_filter_types", [])
                  if f not in seen]
        return list(VALID_FILTER_TYPES) + custom

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
        # The other tabs are constructed lazily — a cold start shouldn't be
        # blocked building screens (and their date pickers / babel locale data)
        # the user hasn't opened yet. They warm up during idle time below, and
        # _show_tab builds any tab on demand if it's clicked first.
        self._lazy_tab_builders = {
            "new_order":   self._build_new_order_tab,
            "prev_orders": self._build_prev_orders_tab,
            "delivery":    self._build_delivery_tab,
            "quotes":      self._build_quotes_tab,
            "products":    self._build_products_tab,
            "customers":   self._build_customers_tab,
            "stock":       self._build_stock_tab,
            "audit_log":   self._build_audit_log_tab,
            "settings":    self._build_settings_tab,
        }
        self._build_dashboard_tab()
        self._build_status_bar()

        # Land on the Dashboard: what's due and what's low is the first thing
        # worth seeing, and it's the leftmost tab.
        self._show_tab("dashboard")

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
            ("dashboard",   "▦  Dashboard"),
            ("new_order",   "＋  New Order"),
            ("prev_orders", "▤  Previous Orders"),
            ("delivery",    "🚚  Delivery"),
            ("quotes",      "💲  Quotes"),
            ("products",    "🏷  Products"),
            ("customers",   "👥  Customers"),
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
    # A few tabs hold things that barely move between visits. Re-reading the
    # whole price list because someone looked at Products two minutes ago is
    # a wait for no new information.
    _TAB_TTLS = {"products": 900, "customers": 300, "audit_log": 120}

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

        ttl = self._TAB_TTLS.get(key, self._TAB_TTL)
        if time.monotonic() - self._tab_loaded.get(key, 0.0) < ttl:
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
        elif key == "products":
            self._refresh_products_list()
        elif key == "delivery":
            self._refresh_delivery_run()
        elif key == "quotes":
            self._refresh_quote_prices()
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
        # Lines added before this tab existed — a restored draft, a purchase
        # order read from a photo — go into the table now that there is one.
        self._refresh_items_tree()

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
            elif key == "Order Number":
                # A customer who rings up without a purchase order number
                # still needs the job identified, so we can issue one.
                wrap = tk.Frame(card_body, bg=CCA)
                wrap.grid(row=row, column=1, sticky="we", pady=4)
                wrap.columnconfigure(0, weight=1)
                e = field_entry(wrap, textvariable=self.hvars[key])
                e.grid(row=0, column=0, sticky="we")
                self._hentries[key] = e
                self._taf_on_btn = tk.Button(
                    wrap, text="TAF #", command=self._use_supplied_order_number,
                    bg=CA, fg="white", relief="flat", bd=0,
                    font=(FAM, 8, "bold"), padx=7, pady=2, cursor="hand2",
                    activebackground=_dk(CA), activeforeground="white")
                self._taf_on_btn.grid(row=0, column=1, padx=(3, 0))
                _Tooltip(self._taf_on_btn,
                         "No purchase order number? Give this order one of "
                         "ours — TAF-ON-0001 and up.")
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
            font=F_BODY, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR,
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

        cols = ("qty", "type", "size", "sqm", "media", "partno", "options", "notes")
        self.tree = ttk.Treeview(tree_wrap, columns=cols,
                                  show="tree headings",
                                  style="TAF.Treeview",
                                  selectmode="browse")
        self.tree.grid(row=0, column=0, sticky="nsew")
        attach_empty_state(
                    self.tree,
                    "No lines on this order yet",
                    "Add a filter, a bag or roll, or import a purchase order.",
                    action=self._add_filter_item, action_text="＋  Add Filter Item")
        self.tree.heading("#0", text="Kind", anchor="center")
        self.tree.column("#0", width=px(92), minwidth=px(80), anchor="center", stretch=False)

        col_defs = {
            "qty":     ("Qty",          50, "center"),
            "type":    ("Type",        138, "w"),
            "size":    ("Dimensions",  148, "center"),
            "sqm":     ("m²",           62, "center"),
            "media":   ("Media",        72, "center"),
            "partno":  ("Part Number", 150, "w"),
            "options": ("Options",     175, "w"),
            "notes":   ("Notes",       999, "w"),
        }
        for col, (hd, wd, anc) in col_defs.items():
            self.tree.heading(col, text=hd)
            self.tree.column(col, width=px(wd), anchor=anc, minwidth=px(40),
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
        flat_btn(gen_row, "💲  Quote",
                 self._quote_current_order, bg=CA2,
                 pady=10, padx=18, font=F_BOLD).pack(side="right", padx=(0, 8))
        flat_btn(gen_row, "📄  Import Purchase Order",
                 self._import_purchase_orders, bg=CA,
                 pady=10, padx=18, font=F_BOLD).pack(side="left")
        # Only shown once photos sent from a phone are read and waiting.
        self._inbox_btn = flat_btn(gen_row, "📱  Phone Inbox",
                                   self._open_phone_inbox, bg=CGR,
                                   pady=10, padx=18, font=F_BOLD)
        self._refresh_inbox_badge()

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

        # Due filter — what still has to be made, and by when. Picking
        # anything but "All" also sorts the list by due date, soonest first.
        tk.Label(srch, text="Due:", bg=CBG, fg=CTX,
                 font=F_BOLD).pack(side="left", padx=(0, 6))
        self.filter_due_var = tk.StringVar(value="All")
        due_cb = ttk.Combobox(srch, textvariable=self.filter_due_var,
                              values=DUE_FILTERS, state="readonly", width=13)
        due_cb.pack(side="left", padx=(0, 14))
        self.filter_due_var.trace_add("write", lambda *_: self._filter_orders_list())

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
            self.filter_due_var.set("All")
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

        ocols = ("customer", "order_no", "date_ordered", "date_due", "status", "printed", "n_items", "created_by", "file")
        self.orders_tree = ttk.Treeview(tbl_wrap, columns=ocols,
                                         show="tree headings",
                                         style="TAF.Treeview",
                                         selectmode="extended")
        self.orders_tree.grid(row=0, column=0, sticky="nsew")
        attach_empty_state(
                    self.orders_tree,
                    "No orders to show",
                    "Nothing matches the current search and filters.\n"
                    "Clear them to see everything, or start a new order.")
        self.orders_tree.heading("#0", text="Type", anchor="center")
        self.orders_tree.column("#0", width=px(106), minwidth=px(92), anchor="center", stretch=False)

        o_col_defs = {
            "customer":     ("Customer Name",  200, "w"),
            "order_no":     ("Order #",        120, "w"),
            "date_ordered": ("Date Ordered",   110, "center"),
            "date_due":     ("Date Due",       100, "center"),
            "status":       ("Status",         120, "center"),
            "printed":      ("Printed",         90, "center"),
            "n_items":      ("# Items",         70, "center"),
            "created_by":   ("Created By",     180, "w"),
            "file":         ("Source",         130, "center"),
        }
        for col, (hd, wd, anc) in o_col_defs.items():
            self.orders_tree.heading(col, text=hd, anchor="center" if anc == "center" else "w")
            self.orders_tree.column(col, width=px(wd), anchor=anc, minwidth=px(40),
                                    stretch=(col in ("customer", "created_by")))

        self.orders_tree.tag_configure("even",        background=CRE)
        self.orders_tree.tag_configure("odd",         background=CCA)
        self.orders_tree.tag_configure("priority",    background="#FDECEC", foreground="#D33A3F")
        self.orders_tree.tag_configure("overdue",     background="#FADBD8", foreground="#922B21")
        self.orders_tree.tag_configure("due_today",   background="#FDEBD0", foreground="#7E5109")
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

        flat_btn(bot, "👁 View Items",         self._view_order_items,
                 bg=CA,  pady=7).pack(side="left", padx=(0, 8))
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
        flat_btn(bot, "💲 Quote",             self._quote_prev_order,
                 bg=CA2, pady=7).pack(side="left", padx=(0, 8))
        flat_btn(bot, "🚚 Freight / Delay",   self._edit_order_freight,
                 bg=CNE, pady=7).pack(side="left", padx=(0, 8))
        flat_btn(bot, "🧾 Invoice to Xero",   self._invoice_selected_orders,
                 bg=CGR, pady=7).pack(side="left", padx=(0, 8))
        flat_btn(bot, "Delete Order",          self._delete_prev_order,
                 bg=CRD, pady=7).pack(side="right", padx=(8, 0))
        flat_btn(bot, "Archive Order",         self._archive_prev_order,
                 bg="#7D3C98", pady=7).pack(side="right")

    # ── Delivery tab ──────────────────────────────────────────────────────
    # What is finished and where it goes. Orders already carry a region and a
    # due date; this turns them into a run sheet the driver takes with them
    # and a way to mark a run out the door in one go.

    def _build_delivery_tab(self):
        frm = tk.Frame(self.content, bg=CBG, padx=14, pady=12)
        frm.grid(row=0, column=0, sticky="nsew")
        frm.rowconfigure(2, weight=1)
        frm.columnconfigure(0, weight=1)
        self._tab_frames["delivery"] = frm

        top = tk.Frame(frm, bg=CBG)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        tk.Label(top, text="Delivery", bg=CBG, fg=CA,
                 font=F_TTL).pack(side="left")
        self._run_summary_var = tk.StringVar(value="")
        tk.Label(top, textvariable=self._run_summary_var, bg=CBG, fg=CMU,
                 font=F_BODY).pack(side="left", padx=(14, 0))
        flat_btn(top, "Refresh", self._refresh_delivery_run, bg=CNE,
                 pady=6, padx=12, font=F_BODY).pack(side="right")

        opts = tk.Frame(frm, bg=CBG)
        opts.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self._run_include_wip = tk.BooleanVar(value=False)
        tk.Checkbutton(
            opts,
            text="Also show what's still being made (for planning tomorrow)",
            variable=self._run_include_wip,
            command=self._refresh_delivery_run,
            bg=CBG, fg=CTX, font=F_BODY, activebackground=CBG,
            activeforeground=CTX, selectcolor=CCA, anchor="w",
            highlightthickness=0, bd=0).pack(side="left")
        tk.Label(opts, text="Only orders marked Complete are ready to load.",
                 bg=CBG, fg=CMU, font=F_SM).pack(side="left", padx=(14, 0))

        wrap = tk.Frame(frm, bg=CCA, highlightbackground=CSP,
                        highlightthickness=1)
        wrap.grid(row=2, column=0, sticky="nsew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        cols = ("order_no", "customer", "items", "due", "status")
        self.delivery_tree = ttk.Treeview(wrap, columns=cols,
                                          show="tree headings",
                                          style="TAF.Treeview",
                                          selectmode="extended")
        self.delivery_tree.heading("#0", text="Region / Order", anchor="w")
        self.delivery_tree.column("#0", width=px(230), minwidth=px(160), stretch=False)
        for col, (hd, wd, anc) in {
                "order_no": ("Order #",   130, "w"),
                "customer": ("Customer",  260, "w"),
                "items":    ("# Items",    70, "center"),
                "due":      ("Due",       120, "center"),
                "status":   ("Status",    120, "center")}.items():
            self.delivery_tree.heading(col, text=hd)
            self.delivery_tree.column(col, width=px(wd), anchor=anc,
                                      stretch=(col == "customer"))
        self.delivery_tree.tag_configure("region", background=CCA,
                                         font=(FAM, 10, "bold"))
        self.delivery_tree.tag_configure("even", background=CRE)
        self.delivery_tree.tag_configure("odd", background=CCA)
        self.delivery_tree.tag_configure("overdue", background="#FADBD8",
                                         foreground="#922B21")
        self.delivery_tree.grid(row=0, column=0, sticky="nsew")
        attach_empty_state(
                    self.delivery_tree,
                    "Nothing ready to go out",
                    "Orders appear here once they are marked Complete.")
        dsb = ttk.Scrollbar(wrap, orient="vertical",
                            command=self.delivery_tree.yview)
        dsb.grid(row=0, column=1, sticky="ns")
        self.delivery_tree.configure(yscrollcommand=dsb.set)

        bot = tk.Frame(frm, bg=CBG, pady=8)
        bot.grid(row=3, column=0, sticky="ew")
        flat_btn(bot, "🖨  Print Run Sheet", self._print_run_sheet, bg=CGR,
                 pady=7).pack(side="left", padx=(0, 8))
        flat_btn(bot, "✓ Mark Selected Dispatched", self._mark_dispatched,
                 bg=CA, pady=7).pack(side="left", padx=(0, 8))
        flat_btn(bot, "View Items", self._view_delivery_items, bg=CNE,
                 pady=7).pack(side="left", padx=(0, 8))
        flat_btn(bot, "🚚 Freight / Delay", self._edit_delivery_freight,
                 bg=CA2, pady=7).pack(side="left", padx=(0, 8))
        flat_btn(bot, "🧾 Invoice Run to Xero", self._invoice_delivery_run,
                 bg=CNE, pady=7).pack(side="left")

    def _refresh_delivery_run(self):
        """Rebuild the run from the orders already loaded, off the main thread."""
        tree = getattr(self, "delivery_tree", None)
        if tree is None:
            return

        def _work():
            data = getattr(self, "_all_orders_data", None)
            if not data:
                try:
                    data = self._scan_orders()
                    self._all_orders_data = data
                except Exception:
                    data = []
            self.master.after(0, lambda: _show(data))

        def _show(data):
            for iid in tree.get_children():
                tree.delete(iid)
            ready = _delivery.ready_for_delivery(
                data, include_in_production=bool(self._run_include_wip.get()))
            grouped = _delivery.group_by_region(ready)
            self._run_rows = {}
            for region, rows in grouped:
                node = tree.insert(
                    "", "end", text=f"  {region}  ({len(rows)})",
                    tags=("region",), open=True, values=("", "", "", "", ""))
                for i, order in enumerate(rows):
                    overdue = _delivery.is_overdue(order)
                    due = (order.get("date_due") or "").strip() or "—"
                    iid = f"o{len(self._run_rows)}"
                    self._run_rows[iid] = order
                    tree.insert(
                        node, "end", iid=iid, text="",
                        tags=("overdue" if overdue
                              else ("even" if i % 2 == 0 else "odd"),),
                        values=(
                            order.get("order_no") or "—",
                            order.get("customer") or "—",
                            _delivery.item_count(order),
                            ("⚠ " if overdue else "") + due,
                            order.get("status") or "Pending",
                        ))
            self._run_grouped = grouped
            self._run_summary_var.set(_delivery.run_summary(grouped))

        self._run_summary_var.set("Loading…")
        threading.Thread(target=_work, daemon=True).start()

    def _selected_delivery_orders(self) -> list:
        """The orders selected, ignoring the region headings."""
        rows = getattr(self, "_run_rows", {})
        return [rows[iid] for iid in self.delivery_tree.selection()
                if iid in rows]

    def _print_run_sheet(self):
        """Build the run sheet and send it to the printer."""
        grouped = getattr(self, "_run_grouped", None)
        if not grouped:
            messagebox.showinfo(
                "Run Sheet",
                "Nothing is marked Complete, so there is nothing to load.\n\n"
                "Mark orders Complete in Previous Orders, then print this.")
            return
        ORDERS_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.date.today()
        out = ORDERS_DIR / f"Run_Sheet_{today:%Y-%m-%d}.pdf"
        try:
            path = _delivery.build_run_sheet_pdf(
                out, grouped, today,
                prepared_by=(_db.current_full_name()
                             or _db.current_username() or ""))
        except Exception as exc:
            messagebox.showerror("Run Sheet",
                                 f"The run sheet could not be created:\n{exc}")
            return
        try:
            _db.log_action("run_sheet_printed", _delivery.run_summary(grouped))
        except Exception:
            pass
        self.status_var.set(f"Run sheet saved: {Path(path).name} — printing…")

        def _print_worker():
            err = self._print_file(str(path))
            def _done():
                if err:
                    self.status_var.set("Run sheet saved — printing failed.")
                    try:
                        os.startfile(str(path))
                    except Exception:
                        messagebox.showinfo("Run Sheet", f"Saved to:\n{path}")
                else:
                    self.status_var.set("Run sheet sent to the printer.")
            self.master.after(0, _done)

        threading.Thread(target=_print_worker, daemon=True).start()

    def _mark_dispatched(self):
        """Mark a whole run out the door in one go."""
        orders = self._selected_delivery_orders()
        if not orders:
            messagebox.showinfo(
                "Mark Dispatched",
                "Select the orders that went out — or click a region and "
                "select the rows under it.")
            return
        n = len(orders)
        if not messagebox.askyesno(
                "Mark Dispatched",
                f"Mark {n} order{'s' if n != 1 else ''} as Dispatched?\n\n"
                "They come off the run and show as Dispatched in Previous "
                "Orders."):
            return

        done, failed = 0, []
        for order in orders:
            oid = order.get("db_id") or order.get("id")
            if not oid:
                failed.append(order.get("order_no") or "—")
                continue
            try:
                _db.set_order_status(oid, _delivery.DISPATCHED)
                order["status"] = _delivery.DISPATCHED
                done += 1
            except Exception:
                failed.append(order.get("order_no") or "—")

        if done:
            try:
                _db.log_action("orders_dispatched", f"{done} order(s)")
            except Exception:
                pass
        # Previous Orders and the Dashboard both count on status.
        self._tab_loaded.pop("prev_orders", None)
        self._tab_loaded.pop("dashboard", None)
        self._refresh_delivery_run()
        if failed:
            messagebox.showwarning(
                "Mark Dispatched",
                f"{done} marked dispatched.\n\n"
                f"{len(failed)} could not be: {', '.join(failed[:6])}. "
                "Orders only saved on this PC have no shared record to update "
                "until they sync.")
        self.status_var.set(
            f"{done} order{'s' if done != 1 else ''} marked dispatched.")

    def _edit_delivery_freight(self):
        orders = self._selected_delivery_orders()
        if not orders:
            messagebox.showinfo("Freight / Delay", "Select an order first.")
            return
        self._freight_dialog(orders[0], on_saved=self._refresh_delivery_run)

    def _edit_order_freight(self):
        row = self._get_selected_order()
        if not row:
            messagebox.showinfo("Freight / Delay", "Select an order first.")
            return
        self._freight_dialog(row)

    def _freight_dialog(self, row, on_saved=None):
        """Record how an order is travelling and anything holding it up.

        All of it shows on the customer's portal. "Where is it" and "why is
        it late" are the two questions a delivery generates, and both are
        better answered before they are asked.
        """
        order_id = row.get("db_id") or row.get("id")
        if not order_id:
            messagebox.showinfo(
                "Freight / Delay",
                "This order is only saved on this PC. It needs to reach the "
                "shared database before freight details can be added.")
            return
        try:
            current = _db.get_order_freight(order_id)
        except Exception:
            current = {}

        dlg = tk.Toplevel(self.master)
        dlg.title("Freight / Delay")
        dlg.configure(bg=CBG)
        dlg.transient(self.master)
        dlg.grab_set()

        hdr = tk.Frame(dlg, bg=CA, padx=16, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text=f"Order {row.get('order_no', '')} — "
                           f"{row.get('customer', '')}",
                 bg=CA, fg="white", font=F_BOLD).pack(anchor="w")
        tk.Label(hdr, text="The customer sees all of this on their portal.",
                 bg=CA, fg="#A9CCE3", font=F_SM).pack(anchor="w")

        body = tk.Frame(dlg, bg=CBG, padx=16, pady=14)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        v_carrier = tk.StringVar(value=current.get("carrier", ""))
        v_number = tk.StringVar(value=current.get("number", ""))
        v_url = tk.StringVar(value=current.get("url", ""))
        v_expected = tk.StringVar(value=current.get("expected", ""))
        v_note = current.get("note", "")

        tk.Label(body, text="Carrier", bg=CBG, fg=CTX, font=F_BODY,
                 anchor="w").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Combobox(body, textvariable=v_carrier,
                     values=list(_db.FREIGHT_CARRIERS), state="readonly",
                     width=22).grid(row=0, column=1, sticky="w", padx=(10, 0))

        for r, (label, var, hint) in enumerate((
                ("Consignment number", v_number, "As it appears on the connote"),
                ("Tracking link", v_url,
                 "Optional — filled in from the carrier if left blank"),
                ("Now expected", v_expected, "Optional — e.g. 09/09/26")), start=1):
            tk.Label(body, text=label, bg=CBG, fg=CTX, font=F_BODY,
                     anchor="w").grid(row=r, column=0, sticky="w", pady=4)
            field_entry(body, textvariable=var, width=44).grid(
                row=r, column=1, sticky="ew", padx=(10, 0), pady=4)
            tk.Label(body, text=hint, bg=CBG, fg=CMU, font=F_SM).grid(
                row=r, column=2, sticky="w", padx=(10, 0))

        tk.Label(body, text="What to tell them", bg=CBG, fg=CTX, font=F_BODY,
                 anchor="w").grid(row=4, column=0, sticky="nw", pady=(10, 4))
        note = tk.Text(body, height=4, wrap="word", font=F_BODY, bg=CFD,
                       fg=CTX, relief="flat", bd=8, highlightthickness=1,
                       highlightbackground=CSP)
        note.grid(row=4, column=1, columnspan=2, sticky="ew",
                  padx=(10, 0), pady=(10, 4))
        note.insert("1.0", v_note)
        tk.Label(body,
                 text="Written in plain words for the customer — say what is "
                      "holding it up and when it will be ready. Leave it blank "
                      "if nothing is wrong.",
                 bg=CBG, fg=CMU, font=F_SM, justify="left",
                 wraplength=560).grid(row=5, column=1, columnspan=2,
                                      sticky="w", padx=(10, 0))

        def _save():
            try:
                _db.set_order_freight(
                    order_id, v_carrier.get(), v_number.get().strip(),
                    v_url.get().strip(), note.get("1.0", "end").strip(),
                    v_expected.get().strip())
                _db.log_action(
                    "order_freight",
                    f"O/N {row.get('order_no','')}: "
                    f"{v_carrier.get()} {v_number.get().strip()}".strip())
            except Exception as exc:
                messagebox.showerror("Freight / Delay",
                                     f"Could not save:\n{exc}", parent=dlg)
                return
            self._tab_loaded.pop("prev_orders", None)
            self._all_orders_data = []
            dlg.destroy()
            if on_saved:
                on_saved()
            self.status_var.set(
                f"Freight details saved for {row.get('order_no','')}.")

        foot = tk.Frame(dlg, bg=CBG, padx=16, pady=10)
        foot.pack(fill="x")
        flat_btn(foot, "Cancel", dlg.destroy, bg=CNE,
                 pady=7).pack(side="right", padx=(8, 0))
        flat_btn(foot, "Save", _save, bg=CGR, pady=7).pack(side="right")
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        W, H = 760, 400
        dlg.geometry(f"{W}x{H}+{self.master.winfo_rootx() + 90}"
                     f"+{self.master.winfo_rooty() + 80}")

    def _view_delivery_items(self):
        """What's actually in the order about to be loaded."""
        orders = self._selected_delivery_orders()
        if not orders:
            messagebox.showinfo("View Items", "Select an order first.")
            return
        row = orders[0]
        header, items = self._order_header_items(row, "View Items")
        if items is None:
            return
        lines = "\n".join(
            f"  {i}.  {it.get('Quantity', 1)} x "
            f"{(it.get('Part Number') or '').strip() or '—'}   "
            f"{(it.get('Filter Type') or '')} "
            f"{(it.get('Media Type') or '')} "
            f"{it.get('Short', '')}x{it.get('Long', '')}x{it.get('Channel', '')}"
            for i, it in enumerate(items, start=1)) or "  (no items)"
        messagebox.showinfo(
            f"Order {row.get('order_no', '')}",
            f"{header.get('Customer Name', '')}  ·  "
            f"{header.get('Location', '')}\n"
            f"Due {header.get('Date Due') or '—'}\n\n{lines}")

    # ── Quotes tab ────────────────────────────────────────────────────────
    # Build a quote without creating an order: pick the customer, add the
    # lines, and every line is priced as it is added. An order that already
    # exists can be pulled in rather than re-keyed.

    def _build_quotes_tab(self):
        frm = tk.Frame(self.content, bg=CBG, padx=14, pady=12)
        frm.grid(row=0, column=0, sticky="nsew")
        frm.rowconfigure(2, weight=1)
        frm.columnconfigure(0, weight=1)
        self._tab_frames["quotes"] = frm
        self.quote_items: list = []
        # Set once the quote has been saved — what Convert to Order needs so
        # the order can be traced back to what was quoted.
        self._current_quote_id = None
        self._current_quote_status = "draft"

        top = tk.Frame(frm, bg=CBG)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        tk.Label(top, text="Quotes", bg=CBG, fg=CA, font=F_TTL).pack(side="left")
        self._quote_price_state = tk.StringVar(value="")
        tk.Label(top, textvariable=self._quote_price_state, bg=CBG, fg=CMU,
                 font=F_SM).pack(side="left", padx=(14, 0))
        flat_btn(top, "Load from an Order", self._quote_from_order, bg=CNE,
                 pady=6, padx=12, font=F_BODY).pack(side="right")
        flat_btn(top, "📋 Saved Quotes", self._open_saved_quotes, bg=CA2,
                 pady=6, padx=12, font=F_BODY).pack(side="right", padx=(0, 8))
        flat_btn(top, "⏳ Follow Up", self._follow_up_quotes, bg=CNE,
                 pady=6, padx=12, font=F_BODY).pack(side="right", padx=(0, 8))
        flat_btn(top, "New", self._new_quote, bg=CMU,
                 pady=6, padx=12, font=F_BODY).pack(side="right", padx=(0, 8))

        # ── Who it is for ────────────────────────────────────────────────
        det = tk.Frame(frm, bg=CCA, highlightbackground=CSP,
                       highlightthickness=1, padx=14, pady=10)
        det.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        det.columnconfigure(1, weight=1)
        det.columnconfigure(3, weight=1)

        self.quote_customer_var = tk.StringVar()
        self.quote_ref_var = tk.StringVar()
        self.quote_number_var = tk.StringVar()
        self.quote_location_var = tk.StringVar()
        self._quote_customer = None

        tk.Label(det, text="CUSTOMER", bg=CCA, fg=CMU,
                 font=F_BOLD).grid(row=0, column=0, sticky="w")
        self.quote_customer_cb = ttk.Combobox(
            det, textvariable=self.quote_customer_var, width=32)
        self.quote_customer_cb.grid(row=1, column=0, sticky="ew", padx=(0, 14))
        self.quote_customer_var.trace_add(
            "write", lambda *_: self._on_quote_customer())

        tk.Label(det, text="QUOTE NUMBER", bg=CCA, fg=CMU,
                 font=F_BOLD).grid(row=0, column=1, sticky="w")
        field_entry(det, textvariable=self.quote_number_var, width=18
                    ).grid(row=1, column=1, sticky="ew", padx=(0, 14))

        tk.Label(det, text="THEIR REFERENCE", bg=CCA, fg=CMU,
                 font=F_BOLD).grid(row=0, column=2, sticky="w")
        field_entry(det, textvariable=self.quote_ref_var, width=18
                    ).grid(row=1, column=2, sticky="ew", padx=(0, 14))

        tk.Label(det, text="REGION", bg=CCA, fg=CMU,
                 font=F_BOLD).grid(row=0, column=3, sticky="w")
        ttk.Combobox(det, textvariable=self.quote_location_var,
                     values=list(_pn.REGION_NAMES), state="readonly", width=16
                     ).grid(row=1, column=3, sticky="ew")

        # ── The lines ────────────────────────────────────────────────────
        wrap = tk.Frame(frm, bg=CCA, highlightbackground=CSP,
                        highlightthickness=1)
        wrap.grid(row=2, column=0, sticky="nsew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        cols = ("part", "desc", "qty", "unit", "total", "src")
        self.quote_tree = ttk.Treeview(wrap, columns=cols, show="headings",
                                       style="TAF.Treeview")
        for col, (hd, wd, anc, stretch) in {
                "part":  ("Part Number", 140, "w", False),
                "desc":  ("Description", 360, "w", True),
                "qty":   ("Qty",          50, "center", False),
                "unit":  ("Unit Price",   95, "e", False),
                "total": ("Line Total",   95, "e", False),
                "src":   ("Priced from", 260, "w", False)}.items():
            self.quote_tree.heading(col, text=hd)
            self.quote_tree.column(col, width=px(wd), anchor=anc, stretch=stretch)
        self.quote_tree.tag_configure("even", background=CRE)
        self.quote_tree.tag_configure("odd", background=CCA)
        self.quote_tree.tag_configure("missing", background="#FDEDEC",
                                      foreground=CRD)
        self.quote_tree.grid(row=0, column=0, sticky="nsew")
        attach_empty_state(
                    self.quote_tree,
                    "Nothing on this quote yet",
                    "Add a filter, a bag or roll, or pick a product\n"
                    "straight out of the price list.",
                    action=self._quote_add_menu, action_text="＋  Add Line")
        qsb = ttk.Scrollbar(wrap, orient="vertical",
                            command=self.quote_tree.yview)
        qsb.grid(row=0, column=1, sticky="ns")
        self.quote_tree.configure(yscrollcommand=qsb.set)
        self.quote_tree.bind("<Double-1>", lambda _e: self._edit_quote_item())

        # ── Actions and totals ───────────────────────────────────────────
        bot = tk.Frame(frm, bg=CBG, pady=8)
        bot.grid(row=3, column=0, sticky="ew")
        # One button, four kinds of line. A quote has to be able to carry
        # anything this business sells, not just a made-to-measure filter.
        self._quote_add_btn = flat_btn(bot, "＋ Add Line  ▾",
                                       self._quote_add_menu, bg=CA, pady=7)
        self._quote_add_btn.pack(side="left", padx=(0, 8))
        flat_btn(bot, "Edit", self._edit_quote_item, bg=CNE,
                 pady=7).pack(side="left", padx=(0, 8))
        flat_btn(bot, "Remove", self._remove_quote_item, bg=CRD,
                 pady=7).pack(side="left", padx=(0, 8))
        flat_btn(bot, "Clear", self._clear_quote, bg=CMU,
                 pady=7).pack(side="left", padx=(0, 8))
        flat_btn(bot, "Export for Xero", self._quote_tab_xero, bg=CA2,
                 pady=7).pack(side="right")
        flat_btn(bot, "Save Quote PDF", self._quote_tab_pdf, bg=CNE,
                 pady=7).pack(side="right", padx=(0, 8))
        flat_btn(bot, "💾 Save Quote", self._save_quote, bg=CGR,
                 pady=7).pack(side="right", padx=(0, 8))
        self._convert_btn = flat_btn(bot, "→ Convert to Order",
                                     self._convert_quote_to_order, bg=CA2, pady=7)
        self._convert_btn.pack(side="right", padx=(0, 8))
        self._send_btn = flat_btn(bot, "🔗 Send to Customer",
                                  self._share_quote_link, bg=CA, pady=7)
        self._send_btn.pack(side="right", padx=(0, 8))

        self._quote_totals_var = tk.StringVar(value="No lines yet.")
        tk.Label(frm, textvariable=self._quote_totals_var, bg=CBG, fg=CTX,
                 font=F_BOLD, anchor="w").grid(row=4, column=0, sticky="w")
        self._quote_warn_var = tk.StringVar(value="")
        tk.Label(frm, textvariable=self._quote_warn_var, bg=CBG, fg=CRD,
                 font=F_SM, anchor="w", justify="left", wraplength=1000
                 ).grid(row=5, column=0, sticky="w", pady=(2, 0))

    def _refresh_quote_prices(self):
        """Load the price list for the Quotes tab and say what it found."""
        def _work():
            prices, rates = self._load_prices()
            def _done():
                if prices or rates:
                    self._quote_price_state.set(
                        f"{len(prices):,} priced part numbers"
                        + (f" · {len(rates)} rate(s) per m²" if rates else ""))
                else:
                    self._quote_price_state.set(
                        "No prices loaded — import them on the Products tab.")
                self._refresh_quote_lines()
            self.master.after(0, _done)

        self._quote_price_state.set("Checking prices…")
        threading.Thread(target=_work, daemon=True).start()
        try:
            names = _db.get_customers(active_only=True)
            self._quote_customers = names
            self.quote_customer_cb["values"] = [
                (c.get("short_name") or c.get("name") or "").strip()
                for c in names if (c.get("short_name") or c.get("name"))]
        except Exception:
            self._quote_customers = []

    def _on_quote_customer(self):
        """Remember which branch profile the typed name belongs to."""
        typed = self.quote_customer_var.get().strip().lower()
        self._quote_customer = next(
            (c for c in getattr(self, "_quote_customers", [])
             if (c.get("short_name") or "").strip().lower() == typed
             or (c.get("name") or "").strip().lower() == typed), None)
        if self._quote_customer and not self.quote_location_var.get().strip():
            self.quote_location_var.set(
                (self._quote_customer.get("region") or "").strip())

    def _quote_header(self) -> dict:
        return {
            "Customer Name": self.quote_customer_var.get().strip(),
            "Order Number":  self.quote_number_var.get().strip(),
            "Job":           self.quote_ref_var.get().strip(),
            "Location":      self.quote_location_var.get().strip(),
            "Date Ordered":  datetime.date.today().strftime("%d/%m/%y"),
            "Date Due":      "",
        }

    def _quote_current_lines(self):
        prices, rates = self._load_prices()
        return _pricing.quote_lines(self.quote_items, prices, rates)

    def _refresh_quote_lines(self):
        tree = getattr(self, "quote_tree", None)
        if tree is None:
            return
        for iid in tree.get_children():
            tree.delete(iid)
        lines = self._quote_current_lines()
        for i, line in enumerate(lines):
            priced = bool(line.get("source"))
            tree.insert("", "end", iid=str(i),
                        tags=("missing" if not priced
                              else ("even" if i % 2 == 0 else "odd"),),
                        values=(
                            line.get("part_number") or "—",
                            line.get("description") or "",
                            line.get("quantity", 0),
                            f'{line.get("unit_price", 0):,.2f}' if priced else "—",
                            f'{line.get("line_total", 0):,.2f}' if priced else "—",
                            _pricing.source_label(line),
                        ))
        if not lines:
            self._quote_totals_var.set("No lines yet.")
            self._quote_warn_var.set("")
            return
        t = _pricing.quote_totals(lines)
        self._quote_totals_var.set(
            f"Subtotal  ${t['subtotal']:,.2f}      GST  ${t['gst']:,.2f}      "
            f"Total  ${t['total']:,.2f}")
        missing = _pricing.unpriced(lines)
        self._quote_warn_var.set(
            f"⚠  {len(missing)} line{'s' if len(missing) != 1 else ''} "
            f"{'have' if len(missing) != 1 else 'has'} no price and "
            f"{'are' if len(missing) != 1 else 'is'} excluded from the totals. "
            "Price them on the Products tab before sending this out."
            if missing else "")

    def _quote_add_menu(self):
        """Everything a quote can carry, in one list.

        A made-to-measure filter is only one of the things this business
        sells, and until now it was the only thing a quote could hold.
        """
        menu = tk.Menu(self.master, tearoff=0, bg=CCA, fg=CTX,
                       activebackground=CA, activeforeground="white",
                       font=F_BODY, bd=0, relief="flat")
        menu.add_command(label="  Filter — made to measure",
                         command=self._add_quote_item)
        menu.add_command(label="  Bag filter or media roll",
                         command=self._add_quote_bag)
        menu.add_separator()
        menu.add_command(label="  From the price list…",
                         command=self._add_quote_product)
        menu.add_separator()
        menu.add_command(label="  Manage product types…",
                         command=self._manage_product_types)
        btn = self._quote_add_btn
        try:
            menu.tk_popup(btn.winfo_rootx(),
                          btn.winfo_rooty() + btn.winfo_height())
        finally:
            menu.grab_release()

    def _add_quote_item(self):
        dlg = LineItemDialog(self.master, title="Add Quote Line",
                             media_types=self.all_media_types,
                             filter_types=self.all_filter_types)
        self.master.wait_window(dlg)
        if dlg.result:
            self.quote_items.append(self._stamp_item(dict(dlg.result)))
            self._refresh_quote_lines()

    def _add_quote_bag(self):
        dlg = BagLineItemDialog(self.master, title="Add Bag / Roll to Quote",
                                media_types=self.all_media_types)
        self.master.wait_window(dlg)
        if dlg.result:
            self.quote_items.append(self._stamp_item(dict(dlg.result)))
            self._refresh_quote_lines()

    def _manage_product_types(self):
        """Add a kind of product once; every PC has it from then on.

        Saved to the shared catalogue rather than this machine's settings —
        a product type someone adds on the office PC is no use if the person
        writing quotes on another one can't pick it.
        """
        dlg = tk.Toplevel(self.master)
        dlg.title("Product Types")
        dlg.configure(bg=CBG, padx=px(18), pady=px(16))
        dlg.transient(self.master)
        dlg.grab_set()

        tk.Label(dlg, text="Product Types", bg=CBG, fg=CA,
                 font=F_SEC).grid(row=0, column=0, columnspan=3, sticky="w")
        tk.Label(dlg, text="The kinds of thing a quote can carry, besides a\n"
                           "made-to-measure filter. Shared with every PC.",
                 bg=CBG, fg=CMU, font=F_SM, justify="left").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(0, px(8)))

        box = tk.Listbox(dlg, height=11, width=38, font=F_BODY, bg=CCA, fg=CTX,
                         highlightthickness=1, highlightbackground=CSP,
                         relief="flat", activestyle="none",
                         selectbackground=CSL, selectforeground=CTX)
        box.grid(row=2, column=0, columnspan=2, sticky="nsew")

        def _fill():
            box.delete(0, "end")
            for p in PRODUCT_TYPES:
                box.insert("end", f"  {p['name']}   ({p.get('unit') or 'each'})")

        _fill()

        entry_row = tk.Frame(dlg, bg=CBG)
        entry_row.grid(row=3, column=0, columnspan=3, sticky="w", pady=(px(8), 0))
        name_var, unit_var = tk.StringVar(), tk.StringVar(value="each")
        tk.Label(entry_row, text="Name", bg=CBG, fg=CTX,
                 font=F_BODY).pack(side="left")
        name_e = field_entry(entry_row, textvariable=name_var, width=20)
        name_e.pack(side="left", padx=(px(6), px(12)))
        tk.Label(entry_row, text="Counted in", bg=CBG, fg=CTX,
                 font=F_BODY).pack(side="left")
        field_entry(entry_row, textvariable=unit_var, width=9).pack(
            side="left", padx=(px(6), 0))

        def _add():
            name = name_var.get().strip()
            if not name:
                return
            if any((p.get("name") or "").lower() == name.lower()
                   for p in PRODUCT_TYPES):
                messagebox.showinfo("Product Types",
                                    f"“{name}” is already on the list.",
                                    parent=dlg)
                return
            PRODUCT_TYPES.append({"name": name,
                                  "unit": unit_var.get().strip() or "each"})
            name_var.set("")
            unit_var.set("each")
            _fill()
            name_e.focus_set()

        def _remove():
            sel = box.curselection()
            if not sel:
                return
            gone = PRODUCT_TYPES.pop(sel[0])
            _fill()
            self.status_var.set(f"Removed product type: {gone.get('name', '')}")

        def _save():
            if _persist_catalog_key("product_types", PRODUCT_TYPES, parent=dlg):
                self.status_var.set(
                    f"{len(PRODUCT_TYPES)} product type"
                    f"{'s' if len(PRODUCT_TYPES) != 1 else ''} saved for everyone.")
            dlg.destroy()

        name_e.bind("<Return>", lambda _e: _add())

        btns = tk.Frame(dlg, bg=CBG)
        btns.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(px(12), 0))
        flat_btn(btns, "Add", _add, bg=CA, pady=px(6)).pack(side="left",
                                                            padx=(0, px(8)))
        flat_btn(btns, "Remove", _remove, bg=CRD,
                 pady=px(6)).pack(side="left")
        flat_btn(btns, "Save", _save, bg=CGR,
                 pady=px(6)).pack(side="right")
        flat_btn(btns, "Cancel", dlg.destroy, bg=CNE,
                 pady=px(6)).pack(side="right", padx=(0, px(8)))

        dlg.columnconfigure(0, weight=1)
        dlg.rowconfigure(2, weight=1)
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        name_e.focus_set()

    def _price_list_lookup(self, term: str) -> list:
        """Search every priced part number. Used by the product picker."""
        try:
            return _db.get_price_rows(term, limit=400)
        except Exception:
            # Offline, or the price list hasn't been imported. Fall back to
            # whatever this session already has cached.
            prices, _rates = self._load_prices()
            t = term.strip().upper()
            return [{"part_number": p, "name": "", "unit_price": v}
                    for p, v in prices.items() if t in p][:400]

    def _add_quote_product(self, initial=None, index=None):
        dlg = CatalogueLineDialog(
            self.master,
            title="Edit Product Line" if index is not None else "Add Product",
            initial=initial, product_types=product_type_names(),
            on_lookup=self._price_list_lookup)
        self.master.wait_window(dlg)
        if not dlg.result:
            return
        line = dict(dlg.result)
        if index is None:
            self.quote_items.append(line)
        else:
            self.quote_items[index] = line
        self._refresh_quote_lines()

    def _edit_quote_item(self):
        sel = self.quote_tree.selection()
        if not sel:
            messagebox.showinfo("Edit Line", "Select a line first.")
            return
        idx = int(sel[0])
        item = self.quote_items[idx]
        # Open the line in the dialog it was made in — editing a media roll in
        # the filter dialog would ask for a channel depth it hasn't got.
        kind = item.get("item_kind") or "filter"
        if kind == "catalogue":
            self._add_quote_product(initial=item, index=idx)
            return
        if kind == "bag":
            dlg = BagLineItemDialog(self.master, title="Edit Bag / Roll",
                                    initial=item,
                                    media_types=self.all_media_types)
        else:
            dlg = LineItemDialog(self.master, title="Edit Quote Line",
                                 initial=item,
                                 media_types=self.all_media_types,
                                 filter_types=self.all_filter_types)
        self.master.wait_window(dlg)
        if dlg.result:
            self.quote_items[idx] = self._stamp_item(dict(dlg.result))
            self._refresh_quote_lines()

    def _remove_quote_item(self):
        sel = self.quote_tree.selection()
        if not sel:
            messagebox.showinfo("Remove Line", "Select a line first.")
            return
        self.quote_items.pop(int(sel[0]))
        self._refresh_quote_lines()

    def _clear_quote(self):
        if self.quote_items and not messagebox.askyesno(
                "Clear Quote", "Remove every line from this quote?"):
            return
        self.quote_items = []
        self._refresh_quote_lines()

    def _quote_from_order(self):
        """Pull a saved order's lines into the quote rather than re-keying."""
        rows = getattr(self, "_all_orders_data", None)
        if not rows:
            self.status_var.set("Loading orders…")
            self.master.update_idletasks()
            try:
                rows = self._scan_orders()
                self._all_orders_data = rows
            except Exception as exc:
                messagebox.showerror("Load from an Order",
                                     f"Could not read orders:\n{exc}")
                return
        if not rows:
            messagebox.showinfo("Load from an Order", "There are no orders yet.")
            return

        dlg = tk.Toplevel(self.master)
        dlg.title("Load from an Order")
        dlg.configure(bg=CBG)
        dlg.transient(self.master)
        dlg.grab_set()
        tk.Label(dlg, text="Pick the order to quote", bg=CA, fg="white",
                 font=F_BOLD, padx=16, pady=10, anchor="w").pack(fill="x")
        lb = tk.Listbox(dlg, font=F_BODY, bg=CCA, fg=CTX, activestyle="none",
                        selectbackground=CA, selectforeground="white",
                        relief="flat", highlightthickness=1,
                        highlightbackground=CSP)
        lb.pack(fill="both", expand=True, padx=16, pady=12)
        recent = rows[:300]
        for r in recent:
            lb.insert("end", f"  {r.get('date_ordered',''):10}  "
                             f"{r.get('order_no','') or '—':14}  "
                             f"{r.get('customer','')}")

        def _ok():
            sel = lb.curselection()
            if not sel:
                return
            row = recent[sel[0]]
            header, items = self._order_header_items(row, "Load from an Order")
            if items is None:
                return
            dlg.destroy()
            self.quote_customer_var.set(header.get("Customer Name", ""))
            self.quote_number_var.set(header.get("Order Number", ""))
            self.quote_ref_var.set(header.get("Job", ""))
            self.quote_location_var.set(header.get("Location", ""))
            self.quote_items = [self._stamp_item(dict(i)) for i in items]
            self._refresh_quote_lines()
            self.status_var.set(
                f"Loaded {len(self.quote_items)} line"
                f"{'s' if len(self.quote_items) != 1 else ''} into the quote.")

        foot = tk.Frame(dlg, bg=CBG, padx=16, pady=10)
        foot.pack(fill="x")
        flat_btn(foot, "Cancel", dlg.destroy, bg=CNE,
                 pady=7).pack(side="right", padx=(8, 0))
        flat_btn(foot, "Load", _ok, bg=CGR, pady=7).pack(side="right")
        lb.bind("<Double-1>", lambda _e: _ok())
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        W, H = 620, 460
        dlg.geometry(f"{W}x{H}+{self.master.winfo_rootx() + 120}"
                     f"+{self.master.winfo_rooty() + 70}")

    def _quote_tab_ready(self) -> bool:
        if not self.quote_items:
            messagebox.showinfo("Quote", "Add at least one line first.")
            return False
        if not self.quote_customer_var.get().strip():
            messagebox.showinfo("Quote", "Enter who the quote is for.")
            return False
        return True

    # ── Saving a quote, and turning an accepted one into an order ─────────

    def _new_quote(self):
        """Start a fresh quote, keeping nothing from the last one."""
        if self.quote_items and not messagebox.askyesno(
                "New Quote", "Clear this quote and start a new one?"):
            return
        self._current_quote_id = None
        self.quote_items = []
        self.quote_customer_var.set("")
        self.quote_ref_var.set("")
        self.quote_location_var.set("")
        self.quote_number_var.set("")
        self._refresh_quote_lines()
        self._update_convert_button()

    def _update_convert_button(self):
        """Convert and Send only mean something once a quote has been saved."""
        state = "normal" if getattr(self, "_current_quote_id", None) else "disabled"
        for name in ("_convert_btn", "_send_btn"):
            btn = getattr(self, name, None)
            if btn is not None:
                btn.config(state=state)

    # ── The link a customer opens ─────────────────────────────────────────

    # ── The customer's own portal ─────────────────────────────────────────

    def _portal_page_base(self) -> str:
        override = (self._settings.get("portal_page_url") or "").strip()
        if override:
            return override.rstrip("/") + "/"
        try:
            from taf_order_app.updater import GITHUB_REPO
            owner, repo = GITHUB_REPO.split("/", 1)
        except Exception:
            owner, repo = "MalakaiCS", "TAF-App"
        return f"https://{owner.lower()}.github.io/{repo}/portal/"

    def _portal_link(self, token: str) -> str:
        from urllib.parse import urlencode
        return (self._portal_page_base() + "?"
                + urlencode({"t": token, "k": _db.current_anon_key()}))

    def _customer_portal_link(self):
        """Give a customer a link to their orders, quotes and account."""
        cust = self._get_selected_customer()
        if not cust:
            messagebox.showinfo("Customer Portal", "Select a customer first.")
            return
        name = (cust.get("short_name") or cust.get("name")
                or cust.get("legal_name") or "this customer")
        try:
            row = _db.get_customer(cust["id"]) or {}
        except Exception:
            row = cust
        has_link = bool((row.get("portal_token") or "").strip())
        enabled = bool(row.get("portal_enabled"))

        dlg = tk.Toplevel(self.master)
        dlg.title("Customer Portal")
        dlg.configure(bg=CBG)
        dlg.transient(self.master)
        dlg.grab_set()

        hdr = tk.Frame(dlg, bg=CA, padx=16, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text=f"Portal for {name}", bg=CA, fg="white",
                 font=F_BOLD).pack(anchor="w")
        tk.Label(hdr,
                 text="They see their own orders and what stage each is at, "
                      "their quotes, and their account details.",
                 bg=CA, fg="#A9CCE3", font=F_SM,
                 wraplength=560, justify="left").pack(anchor="w")

        body = tk.Frame(dlg, bg=CBG, padx=16, pady=14)
        body.pack(fill="both", expand=True)

        state = tk.StringVar()
        tk.Label(body, textvariable=state, bg=CBG, fg=CTX, font=F_BODY,
                 anchor="w").pack(anchor="w", pady=(0, 8))

        box = tk.Text(body, height=4, wrap="char", font=F_SM, bg=CFD, fg=CTX,
                      relief="flat", bd=8, highlightthickness=1,
                      highlightbackground=CSP)
        box.pack(fill="x")

        tk.Label(body,
                 text="Anyone with this link can see this customer's orders, "
                      "quotes and account — so send it to them and nobody "
                      "else. It shows no other customer, no prices beyond "
                      "their own quotes, and nothing internal.\n"
                      "If it ever goes astray, New Link replaces it and every "
                      "old link stops working immediately.",
                 bg=CBG, fg=CMU, font=F_SM, justify="left",
                 wraplength=580, anchor="w").pack(anchor="w", pady=(10, 0))

        holder = {"link": ""}

        def _set_link(token):
            holder["link"] = self._portal_link(token)
            box.config(state="normal")
            box.delete("1.0", "end")
            box.insert("1.0", holder["link"])
            box.config(state="disabled")
            state.set("Portal is on. The link is copied to your clipboard.")
            self.master.clipboard_clear()
            self.master.clipboard_append(holder["link"])

        def _issue(rotate=False):
            try:
                token = _db.customer_portal_token(cust["id"], rotate=rotate)
            except Exception as exc:
                messagebox.showerror(
                    "Customer Portal",
                    f"The link could not be made:\n{exc}\n\n"
                    "If this mentions a missing column, run "
                    "migrate_customer_portal.sql in the Supabase SQL Editor.",
                    parent=dlg)
                return
            try:
                _db.log_action("customer_portal",
                               f"{'New link for' if rotate else 'Link for'} {name}")
            except Exception:
                pass
            _set_link(token)

        def _turn_off():
            if not messagebox.askyesno(
                    "Turn Off Portal",
                    f"Turn the portal off for {name}?\n\n"
                    "Their link stops working. Turning it back on later uses "
                    "the same link unless you issue a new one.", parent=dlg):
                return
            try:
                _db.set_customer_portal(cust["id"], False)
                _db.log_action("customer_portal", f"Turned off for {name}")
            except Exception as exc:
                messagebox.showerror("Customer Portal",
                                     f"Could not turn it off:\n{exc}", parent=dlg)
                return
            state.set("Portal is off. Their link no longer works.")
            box.config(state="normal")
            box.delete("1.0", "end")
            box.config(state="disabled")

        if has_link and enabled:
            _set_link(row.get("portal_token"))
        elif has_link:
            state.set("Portal is off for this customer.")
            box.config(state="disabled")
        else:
            state.set("No link yet — Create Link makes one.")
            box.config(state="disabled")

        foot = tk.Frame(dlg, bg=CBG, padx=16, pady=10)
        foot.pack(fill="x")
        flat_btn(foot, "Close", dlg.destroy, bg=CNE,
                 pady=7).pack(side="right", padx=(8, 0))
        if has_link:
            flat_btn(foot, "New Link", lambda: _issue(rotate=True), bg=CRD,
                     pady=7).pack(side="right", padx=(8, 0))
            if enabled:
                flat_btn(foot, "Turn Off", _turn_off, bg=CMU,
                         pady=7).pack(side="right", padx=(8, 0))
        flat_btn(foot, "Create Link" if not has_link else "Copy Link",
                 lambda: _issue(rotate=False), bg=CGR,
                 pady=7).pack(side="right")
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        W, H = 660, 400
        dlg.geometry(f"{W}x{H}+{self.master.winfo_rootx() + 110}"
                     f"+{self.master.winfo_rooty() + 90}")

    def _quote_page_base(self) -> str:
        """Where the customer quote page is hosted: GitHub Pages, this repo.

        Not Supabase — it serves anything it hosts as text/plain under a
        sandbox CSP, so the page would arrive as unstyled source with every
        script blocked. Same reason the phone page lives there.
        """
        override = (self._settings.get("quote_page_url") or "").strip()
        if override:
            return override.rstrip("/") + "/"
        try:
            from taf_order_app.updater import GITHUB_REPO
            owner, repo = GITHUB_REPO.split("/", 1)
        except Exception:
            owner, repo = "MalakaiCS", "TAF-App"
        return f"https://{owner.lower()}.github.io/{repo}/quote/"

    def _quote_link(self, token: str) -> str:
        """The address to send a customer.

        Carries the quote's token and the publishable key — the same key that
        ships in this app. The key opens nothing on its own: the quotes table
        gives anonymous callers no access, and the page can only call two
        functions that each take the token.
        """
        from urllib.parse import urlencode
        return (self._quote_page_base() + "?"
                + urlencode({"t": token, "k": _db.current_anon_key()}))

    def _share_quote_link(self):
        """Make the customer link, copy it, and mark the quote sent."""
        quote_id = getattr(self, "_current_quote_id", None)
        if not quote_id:
            messagebox.showinfo(
                "Send to Customer",
                "Save the quote first — the link points at the saved quote.")
            return
        unpriced = _pricing.unpriced(self._quote_current_lines())
        if unpriced and not messagebox.askyesno(
                "Unpriced Lines",
                f"{len(unpriced)} line{'s' if len(unpriced) != 1 else ''} on "
                "this quote have no price. The customer will see them as "
                "\"to be confirmed\" and they are left out of the total.\n\n"
                "Send it anyway?", icon="warning", default="no"):
            return
        try:
            token = _db.ensure_quote_token(quote_id)
            _db.mark_quote_sent(quote_id)
        except Exception as exc:
            messagebox.showerror(
                "Send to Customer",
                f"The link could not be made:\n{exc}\n\n"
                "If this mentions a missing column, run "
                "migrate_quote_portal.sql in the Supabase SQL Editor.")
            return
        link = self._quote_link(token)
        self._current_quote_status = "sent"
        try:
            _db.log_action("quote_sent",
                           f"{self.quote_number_var.get().strip()} · "
                           f"{self.quote_customer_var.get().strip()}")
        except Exception:
            pass
        self._show_quote_link(link)

    def _show_quote_link(self, link: str):
        """Show the link, already copied, with the wording to send with it."""
        dlg = tk.Toplevel(self.master)
        dlg.title("Send to Customer")
        dlg.configure(bg=CBG)
        dlg.transient(self.master)
        dlg.grab_set()

        hdr = tk.Frame(dlg, bg=CA, padx=16, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="The customer's link", bg=CA, fg="white",
                 font=F_BOLD).pack(anchor="w")
        tk.Label(hdr, text="Copied to the clipboard — paste it into an email.",
                 bg=CA, fg="#A9CCE3", font=F_SM).pack(anchor="w")

        body = tk.Frame(dlg, bg=CBG, padx=16, pady=14)
        body.pack(fill="both", expand=True)
        tk.Label(body,
                 text="They can read the quote and press Accept or Decline. "
                      "You'll see their answer here, with who approved it and "
                      "their order number.",
                 bg=CBG, fg=CTX, font=F_BODY, justify="left",
                 wraplength=560, anchor="w").pack(anchor="w", pady=(0, 10))

        box = tk.Text(body, height=4, wrap="char", font=F_SM, bg=CFD, fg=CTX,
                      relief="flat", bd=8, highlightthickness=1,
                      highlightbackground=CSP)
        box.pack(fill="x")
        box.insert("1.0", link)
        box.config(state="disabled")

        tk.Label(body,
                 text="Anyone with this link can see this one quote, so send "
                      "it to the customer and nobody else. It shows no other "
                      "quote, customer or price.",
                 bg=CBG, fg=CMU, font=F_SM, justify="left",
                 wraplength=560, anchor="w").pack(anchor="w", pady=(10, 0))

        def _copy():
            self.master.clipboard_clear()
            self.master.clipboard_append(link)
            self.status_var.set("Quote link copied.")

        def _open():
            import webbrowser
            try:
                webbrowser.open(link)
            except Exception:
                pass

        _copy()
        foot = tk.Frame(dlg, bg=CBG, padx=16, pady=10)
        foot.pack(fill="x")
        flat_btn(foot, "Close", dlg.destroy, bg=CNE,
                 pady=7).pack(side="right", padx=(8, 0))
        flat_btn(foot, "Open It Myself", _open, bg=CNE,
                 pady=7).pack(side="right", padx=(8, 0))
        flat_btn(foot, "Copy Again", _copy, bg=CGR, pady=7).pack(side="right")
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        W, H = 640, 340
        dlg.geometry(f"{W}x{H}+{self.master.winfo_rootx() + 120}"
                     f"+{self.master.winfo_rooty() + 100}")

    def _follow_up_quotes(self):
        """Quotes sent to a customer that nobody has answered."""
        try:
            rows = _db.quotes_awaiting_reply()
        except Exception as exc:
            messagebox.showerror("Follow Up", f"Could not read quotes:\n{exc}")
            return
        if not rows:
            messagebox.showinfo(
                "Follow Up",
                "Nothing is waiting on a customer.\n\n"
                "Quotes appear here once you've sent the link and before "
                "they've accepted or declined.")
            return

        dlg = tk.Toplevel(self.master)
        dlg.title("Quotes Awaiting a Reply")
        dlg.configure(bg=CBG)
        dlg.transient(self.master)
        dlg.grab_set()
        hdr = tk.Frame(dlg, bg=CA, padx=16, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Waiting on the customer", bg=CA, fg="white",
                 font=F_BOLD).pack(anchor="w")
        tk.Label(hdr,
                 text="Opened means they've read it. Longest wait first.",
                 bg=CA, fg="#A9CCE3", font=F_SM).pack(anchor="w")

        wrap = tk.Frame(dlg, bg=CCA, highlightbackground=CSP,
                        highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=16, pady=12)
        cols = ("number", "customer", "total", "sent", "opened")
        tree = ttk.Treeview(wrap, columns=cols, show="headings",
                            style="TAF.Treeview", height=13)
        for col, (hd, wd, anc) in {
                "number":   ("Quote",     100, "w"),
                "customer": ("Customer",  240, "w"),
                "total":    ("Total",     100, "e"),
                "sent":     ("Sent",      110, "center"),
                "opened":   ("Opened",    130, "center")}.items():
            tree.heading(col, text=hd)
            tree.column(col, width=px(wd), anchor=anc,
                        stretch=(col == "customer"))
        tree.tag_configure("even", background=CRE)
        tree.tag_configure("odd", background=CCA)
        tree.tag_configure("stale", background="#FDEBD0", foreground="#7E5109")
        tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        sb.pack(side="right", fill="y")
        tree.configure(yscrollcommand=sb.set)

        today = datetime.date.today()
        for i, r in enumerate(rows):
            sent = (r.get("sent_at") or "")[:10]
            waited = 0
            try:
                waited = (today - datetime.date.fromisoformat(sent)).days
            except ValueError:
                pass
            tree.insert("", "end", iid=str(i),
                        tags=("stale" if waited >= 7
                              else ("even" if i % 2 == 0 else "odd"),),
                        values=(
                            r.get("quote_number", ""),
                            r.get("customer_name", ""),
                            f'{float(r.get("total") or 0):,.2f}',
                            sent or "—",
                            (r.get("viewed_at") or "")[:10] or "not yet",
                        ))

        def _open_selected():
            sel = tree.selection()
            if not sel:
                return
            row = rows[int(sel[0])]
            dlg.destroy()
            self._load_quote(row)

        foot = tk.Frame(dlg, bg=CBG, padx=16, pady=10)
        foot.pack(fill="x")
        flat_btn(foot, "Open Quote", _open_selected, bg=CGR,
                 pady=7).pack(side="left")
        flat_btn(foot, "Close", dlg.destroy, bg=CNE, pady=7).pack(side="right")
        tree.bind("<Double-1>", lambda _e: _open_selected())
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        W, H = 740, 470
        dlg.geometry(f"{W}x{H}+{self.master.winfo_rootx() + 110}"
                     f"+{self.master.winfo_rooty() + 70}")

    def _save_quote(self):
        """Store the quote as it stands, so it can be found and followed up.

        The priced lines are saved as quoted, not as a pointer at today's
        prices — what a customer was told does not change because the price
        list did.
        """
        if not self._quote_tab_ready():
            return
        lines = self._quote_current_lines()
        totals = _pricing.quote_totals(lines)
        if not self.quote_number_var.get().strip():
            try:
                self.quote_number_var.set(_db.next_quote_number())
            except Exception:
                pass
        cust = self._quote_customer or {}
        payload = {
            "id":             getattr(self, "_current_quote_id", None),
            "quote_number":   self.quote_number_var.get().strip(),
            "customer_id":    cust.get("id"),
            "customer_name":  self.quote_customer_var.get().strip(),
            "reference":      self.quote_ref_var.get().strip(),
            "location":       self.quote_location_var.get().strip(),
            "status":         getattr(self, "_current_quote_status", "draft"),
            "items":          [_po_import.strip_review_fields(dict(i))
                               for i in self.quote_items],
            # What the customer is shown, frozen at today's prices.
            "lines":          [{k: v for k, v in line.items() if k != "item"}
                               for line in lines],
            "subtotal":       totals["subtotal"],
            "gst":            totals["gst"],
            "total":          totals["total"],
            "unpriced_count": len(_pricing.unpriced(lines)),
            "valid_until":    (datetime.date.today() +
                               datetime.timedelta(days=30)).isoformat(),
        }
        try:
            saved = _db.save_quote(payload)
        except Exception as exc:
            messagebox.showerror(
                "Save Quote",
                f"The quote could not be saved:\n{exc}\n\n"
                "If this mentions a missing 'quotes' table, run "
                "migrate_quotes.sql in the Supabase SQL Editor.")
            return
        if saved and saved.get("id"):
            self._current_quote_id = saved["id"]
        try:
            _db.log_action("quote_saved",
                           f"{payload['quote_number']} · "
                           f"{payload['customer_name']} · "
                           f"${payload['total']:,.2f}")
        except Exception:
            pass
        self._update_convert_button()
        self.status_var.set(
            f"Quote {payload['quote_number']} saved — "
            f"${payload['total']:,.2f}.")

    def _open_saved_quotes(self):
        """The quotes already written: find one, reopen it, or set its status."""
        dlg = tk.Toplevel(self.master)
        dlg.title("Saved Quotes")
        dlg.configure(bg=CBG)
        dlg.transient(self.master)
        dlg.grab_set()

        hdr = tk.Frame(dlg, bg=CA, padx=16, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Saved Quotes", bg=CA, fg="white",
                 font=F_BOLD).pack(anchor="w")
        tk.Label(hdr, text="Open one to work on it, or mark what happened to it.",
                 bg=CA, fg="#A9CCE3", font=F_SM).pack(anchor="w")

        bar = tk.Frame(dlg, bg=CBG, padx=16, pady=8)
        bar.pack(fill="x")
        status_var = tk.StringVar(value="All")
        tk.Label(bar, text="Status:", bg=CBG, fg=CTX,
                 font=F_BOLD).pack(side="left", padx=(0, 6))
        ttk.Combobox(bar, textvariable=status_var,
                     values=["All"] + list(_db.QUOTE_STATUSES),
                     state="readonly", width=12).pack(side="left", padx=(0, 12))
        search_var = tk.StringVar()
        tk.Label(bar, text="Search:", bg=CBG, fg=CTX,
                 font=F_BOLD).pack(side="left", padx=(0, 6))
        field_entry(bar, textvariable=search_var, width=24).pack(side="left")

        wrap = tk.Frame(dlg, bg=CCA, highlightbackground=CSP,
                        highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        cols = ("number", "customer", "total", "status", "answer", "created")
        tree = ttk.Treeview(wrap, columns=cols, show="headings",
                            style="TAF.Treeview", height=14)
        for col, (hd, wd, anc) in {
                "number":   ("Quote",       100, "w"),
                "customer": ("Customer",    220, "w"),
                "total":    ("Total",        95, "e"),
                "status":   ("Status",      100, "center"),
                "answer":   ("Their answer", 200, "w"),
                "created":  ("Created",     100, "center")}.items():
            tree.heading(col, text=hd)
            tree.column(col, width=px(wd), anchor=anc,
                        stretch=(col == "customer"))
        tree.tag_configure("even", background=CRE)
        tree.tag_configure("odd", background=CCA)
        tree.tag_configure("accepted", background="#D4EDDA", foreground="#155724")
        tree.tag_configure("declined", background="#FDEDEC", foreground=CRD)
        tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        sb.pack(side="right", fill="y")
        tree.configure(yscrollcommand=sb.set)

        rows: list = []

        def _reload(*_):
            for iid in tree.get_children():
                tree.delete(iid)
            rows.clear()
            try:
                rows.extend(_db.get_quotes(status_var.get(), search_var.get()))
            except Exception as exc:
                messagebox.showerror("Saved Quotes",
                                     f"Could not read quotes:\n{exc}\n\n"
                                     "If this mentions a missing 'quotes' "
                                     "table, run migrate_quotes.sql.",
                                     parent=dlg)
                return
            for i, r in enumerate(rows):
                status = r.get("status", "draft")
                tag = ("accepted" if status == "accepted"
                       else "declined" if status == "declined"
                       else "even" if i % 2 == 0 else "odd")
                # What the customer actually did, in their own words where
                # they gave any — the reason for having a portal at all.
                who = (r.get("response_name") or "").strip()
                when = (r.get("responded_at") or "")[:10]
                if who or when:
                    answer = " ".join(x for x in (who, when) if x)
                    ref = (r.get("response_reference") or "").strip()
                    if ref:
                        answer += f"  ({ref})"
                elif r.get("viewed_at"):
                    answer = "opened " + (r.get("viewed_at") or "")[:10]
                elif r.get("sent_at"):
                    answer = "sent, not opened"
                else:
                    answer = ""
                tree.insert("", "end", iid=str(i), tags=(tag,), values=(
                    r.get("quote_number", ""),
                    r.get("customer_name", ""),
                    f'{float(r.get("total") or 0):,.2f}',
                    status + (" →order" if r.get("converted_order_id") else ""),
                    answer,
                    (r.get("created_at") or "")[:10],
                ))
            if not rows:
                self.status_var.set("No quotes saved yet.")

        status_var.trace_add("write", _reload)
        search_var.trace_add("write", _reload)

        def _selected():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("Saved Quotes", "Select a quote first.",
                                    parent=dlg)
                return None
            idx = int(sel[0])
            return rows[idx] if idx < len(rows) else None

        def _open():
            row = _selected()
            if not row:
                return
            dlg.destroy()
            self._load_quote(row)

        def _set_status():
            row = _selected()
            if not row:
                return
            choice = _pick_one(dlg, "Quote Status",
                               f"What happened to {row.get('quote_number','')}?",
                               list(_db.QUOTE_STATUSES),
                               row.get("status", "draft"))
            if not choice:
                return
            try:
                _db.set_quote_status(row["id"], choice)
                _db.log_action("quote_status",
                               f"{row.get('quote_number','')} → {choice}")
            except Exception as exc:
                messagebox.showerror("Saved Quotes",
                                     f"Could not update:\n{exc}", parent=dlg)
                return
            _reload()

        def _delete():
            row = _selected()
            if not row:
                return
            if not messagebox.askyesno(
                    "Delete Quote",
                    f"Delete quote {row.get('quote_number','')} for "
                    f"{row.get('customer_name','')}?\n\nThis cannot be undone.",
                    icon="warning", default="no", parent=dlg):
                return
            try:
                _db.delete_quote(row["id"])
            except Exception as exc:
                messagebox.showerror("Saved Quotes",
                                     f"Could not delete:\n{exc}", parent=dlg)
                return
            if getattr(self, "_current_quote_id", None) == row["id"]:
                self._current_quote_id = None
                self._update_convert_button()
            _reload()

        foot = tk.Frame(dlg, bg=CBG, padx=16, pady=10)
        foot.pack(fill="x")
        flat_btn(foot, "Open", _open, bg=CGR, pady=7).pack(side="left")
        flat_btn(foot, "Mark Status", _set_status, bg=CA2,
                 pady=7).pack(side="left", padx=(8, 0))
        if _db.is_ready() and _db.can_delete_quotes():
            flat_btn(foot, "Delete", _delete, bg=CRD,
                     pady=7).pack(side="left", padx=(8, 0))
        flat_btn(foot, "Close", dlg.destroy, bg=CNE,
                 pady=7).pack(side="right")
        tree.bind("<Double-1>", lambda _e: _open())
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        W, H = 780, 520
        dlg.geometry(f"{W}x{H}+{self.master.winfo_rootx() + 100}"
                     f"+{self.master.winfo_rooty() + 60}")
        _reload()

    def _load_quote(self, row):
        """Reopen a saved quote in the Quotes tab."""
        self._current_quote_id = row.get("id")
        self._current_quote_status = row.get("status", "draft")
        self.quote_number_var.set(row.get("quote_number", ""))
        self.quote_customer_var.set(row.get("customer_name", ""))
        self.quote_ref_var.set(row.get("reference", ""))
        self.quote_location_var.set(row.get("location", ""))
        self.quote_items = [self._stamp_item(dict(i))
                            for i in (row.get("items") or [])]
        self._refresh_quote_lines()
        self._update_convert_button()
        self._show_tab("quotes")
        self.status_var.set(
            f"Quote {row.get('quote_number','')} opened — "
            f"{len(self.quote_items)} line"
            f"{'s' if len(self.quote_items) != 1 else ''}.")

    def _convert_quote_to_order(self):
        """Turn an accepted quote into an order without re-keying it.

        The lines go straight onto the New Order form, ready to generate. The
        quote is marked accepted and pointed at the order, so the same quote
        can't quietly be made twice.
        """
        quote_id = getattr(self, "_current_quote_id", None)
        if not quote_id:
            messagebox.showinfo(
                "Convert to Order",
                "Save the quote first — converting records which quote the "
                "order came from.")
            return
        if not self.quote_items:
            messagebox.showinfo("Convert to Order", "This quote has no lines.")
            return

        row = None
        try:
            row = _db.get_quote(quote_id)
        except Exception:
            pass
        if row and row.get("converted_order_id"):
            if not messagebox.askyesno(
                    "Already Converted",
                    f"Quote {row.get('quote_number','')} was already made "
                    "into an order.\n\nMake another one from it?",
                    icon="warning", default="no"):
                return

        unpriced = _pricing.unpriced(self._quote_current_lines())
        if unpriced and not messagebox.askyesno(
                "Unpriced Lines",
                f"{len(unpriced)} line{'s' if len(unpriced) != 1 else ''} on "
                "this quote have no price.\n\nConvert it to an order anyway?",
                icon="warning", default="yes"):
            return

        header = {
            "Customer Name": self.quote_customer_var.get().strip(),
            "Order Number":  self.quote_ref_var.get().strip(),
            "Job":           self.quote_ref_var.get().strip(),
            "Location":      self.quote_location_var.get().strip(),
            "Date Ordered":  datetime.date.today().strftime("%d/%m/%y"),
            "Date Due":      "",
            "Notes":         f"From quote {self.quote_number_var.get().strip()}",
        }
        self._load_order_into_form(header, [dict(i) for i in self.quote_items])
        try:
            _db.mark_quote_converted(quote_id)
            _db.log_action("quote_converted",
                           f"{self.quote_number_var.get().strip()} → order for "
                           f"{header['Customer Name']}")
        except Exception:
            pass          # the order matters more than the bookkeeping
        self._current_quote_status = "accepted"
        self._show_tab("new_order")
        self.status_var.set(
            f"Quote {self.quote_number_var.get().strip()} loaded into a new "
            "order — check the order number and due date, then Generate.")
        messagebox.showinfo(
            "Converted to Order",
            "The quote's lines are on the New Order tab and the quote is "
            "marked accepted.\n\nFill in the customer's order number and the "
            "due date, then press Generate Output.")

    def _quote_tab_pdf(self):
        if self._quote_tab_ready():
            self._save_quote_pdf(self._quote_header(),
                                 self._quote_current_lines(),
                                 self._quote_customer)

    def _quote_tab_xero(self):
        if self._quote_tab_ready():
            self._export_quote_xero(self._quote_header(),
                                    self._quote_current_lines(),
                                    self._quote_customer)

    # ── Products tab ──────────────────────────────────────────────────────
    # The priced catalogue: one row per part number. This is what a quote
    # looks a line up in, and the part numbers are the item codes in Xero.

    def _build_products_tab(self):
        frm = tk.Frame(self.content, bg=CBG, padx=14, pady=12)
        frm.grid(row=0, column=0, sticky="nsew")
        frm.rowconfigure(2, weight=1)
        frm.columnconfigure(0, weight=1)
        self._tab_frames["products"] = frm

        top = tk.Frame(frm, bg=CBG)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        tk.Label(top, text="Products & Prices", bg=CBG, fg=CA,
                 font=F_TTL).pack(side="left")
        self._products_count = tk.StringVar(value="")
        tk.Label(top, textvariable=self._products_count, bg=CBG, fg=CMU,
                 font=F_BODY).pack(side="left", padx=(14, 0))

        srch = tk.Frame(frm, bg=CBG)
        srch.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        tk.Label(srch, text="Search:", bg=CBG, fg=CTX,
                 font=F_BOLD).pack(side="left", padx=(0, 6))
        self.product_search_var = tk.StringVar()
        e = field_entry(srch, textvariable=self.product_search_var, width=34)
        e.pack(side="left", padx=(0, 8))
        e.bind("<Return>", lambda _e: self._refresh_products_list())
        flat_btn(srch, "Search", self._refresh_products_list, bg=CA,
                 pady=5, padx=12, font=F_BODY).pack(side="left", padx=(0, 6))
        flat_btn(srch, "Clear", lambda: (self.product_search_var.set(""),
                                         self._refresh_products_list()),
                 bg=CMU, pady=5, padx=10, font=F_BODY).pack(side="left")
        tk.Label(srch, text="Part number, name or description.",
                 bg=CBG, fg=CMU, font=F_SM).pack(side="left", padx=(12, 0))

        wrap = tk.Frame(frm, bg=CCA, highlightbackground=CSP,
                        highlightthickness=1)
        wrap.grid(row=2, column=0, sticky="nsew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        cols = ("part", "name", "price", "updated")
        self.products_tree = ttk.Treeview(wrap, columns=cols, show="headings",
                                          style="TAF.Treeview")
        for col, (hd, wd, anc, stretch) in {
                "part":    ("Part Number", 160, "w", False),
                "name":    ("Product",     460, "w", True),
                "price":   ("Price ex GST", 110, "e", False),
                "updated": ("Updated",     150, "center", False)}.items():
            self.products_tree.heading(col, text=hd)
            self.products_tree.column(col, width=px(wd), anchor=anc, stretch=stretch)
        self.products_tree.tag_configure("even", background=CRE)
        self.products_tree.tag_configure("odd", background=CCA)
        self.products_tree.grid(row=0, column=0, sticky="nsew")
        attach_empty_state(
                    self.products_tree,
                    "No products priced yet",
                    "Import your price spreadsheets and every part number\n"
                    "in them becomes quotable.")
        sb = ttk.Scrollbar(wrap, orient="vertical",
                           command=self.products_tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.products_tree.configure(yscrollcommand=sb.set)
        self.products_tree.bind("<Double-1>", lambda _e: self._edit_product())

        bot = tk.Frame(frm, bg=CBG, pady=8)
        bot.grid(row=3, column=0, sticky="ew")
        can = _db.is_ready() and _db.can_manage_prices()
        for label, cmd, colour, rights in (
                ("＋ Add Product",        self._add_product,        CA,  True),
                ("Edit",                  self._edit_product,       CNE, True),
                ("Delete",                self._delete_product,     CRD, True),
                ("📥 Import Price Files", self._import_price_files, CA2, True),
                ("Rates per m²",          self._edit_price_rates,   CNE, True),
                ("Refresh",               self._refresh_products_list, CNE, False)):
            b = flat_btn(bot, label, cmd, bg=colour, pady=7)
            b.pack(side="left", padx=(0, 8))
            if rights and not can:
                b.config(state="disabled")
        b = flat_btn(bot, "Clear Price List", self._clear_price_list,
                     bg=CRD, pady=7)
        b.pack(side="right")
        if not can:
            b.config(state="disabled")

    def _refresh_products_list(self):
        """Load the price list, off the main thread — it is a long list."""
        tree = getattr(self, "products_tree", None)
        if tree is None:
            return
        search = self.product_search_var.get().strip()
        self._products_count.set("Loading…")

        def _work():
            try:
                # Nobody scrolls twelve thousand part numbers looking for one.
                # An unfiltered view is a sample to confirm the list loaded;
                # a search is what actually finds a product, and gets more
                # room. Both are capped — filling the table is the slow part,
                # not the query.
                rows = _db.get_price_rows(search, limit=1500 if search else 400)
                total = _db.count_prices()
            except Exception as exc:
                rows, total = [], -1
                self._products_error = str(exc)
            self.master.after(0, lambda: _show(rows, total))

        def _show(rows, total):
            for iid in tree.get_children():
                tree.delete(iid)
            self._products_rows = rows
            for i, r in enumerate(rows):
                tree.insert("", "end", iid=str(i),
                            tags=("even" if i % 2 == 0 else "odd",),
                            values=(
                                r.get("part_number", ""),
                                (r.get("name") or r.get("description") or "")
                                .replace("\n", " · "),
                                f'{float(r.get("unit_price") or 0):,.2f}',
                                (r.get("updated_at") or "")[:10],
                            ))
            if total < 0:
                self._products_count.set(
                    "Couldn't read the price list — run migrate_pricing.sql "
                    "in the Supabase SQL Editor.")
            elif search:
                more = " — narrow the search to see the rest" if len(rows) >= 1500 else ""
                self._products_count.set(
                    f"{len(rows):,} matching · {total:,} priced in total{more}")
            elif not total:
                self._products_count.set(
                    "Nothing priced yet — Import Price Files to load them.")
            elif len(rows) < total:
                self._products_count.set(
                    f"{total:,} part numbers priced · showing the first "
                    f"{len(rows):,} — search to find one")
            else:
                self._products_count.set(f"{total:,} part numbers priced")

        threading.Thread(target=_work, daemon=True).start()

    def _selected_product(self):
        sel = self.products_tree.selection()
        rows = getattr(self, "_products_rows", [])
        if not sel:
            return None
        idx = int(sel[0])
        return rows[idx] if idx < len(rows) else None

    def _add_product(self):
        self._product_dialog(None)

    def _edit_product(self):
        row = self._selected_product()
        if not row:
            messagebox.showinfo("Edit Product", "Select a product first.")
            return
        self._product_dialog(row)

    def _product_dialog(self, row):
        """Add or correct one priced part number."""
        editing = row is not None
        dlg = tk.Toplevel(self.master)
        dlg.title("Edit Product" if editing else "Add Product")
        dlg.configure(bg=CBG)
        dlg.transient(self.master)
        dlg.grab_set()

        hdr = tk.Frame(dlg, bg=CA, padx=16, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Edit Product" if editing else "Add Product",
                 bg=CA, fg="white", font=F_BOLD).pack(anchor="w")
        tk.Label(hdr, text="The part number is the item code in Xero — it has "
                           "to match exactly for a quote to find this price.",
                 bg=CA, fg="#A9CCE3", font=F_SM).pack(anchor="w")

        body = tk.Frame(dlg, bg=CBG, padx=16, pady=14)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        v_part = tk.StringVar(value=(row or {}).get("part_number", ""))
        v_name = tk.StringVar(value=(row or {}).get("name", ""))
        v_desc = tk.StringVar(value=(row or {}).get("description", ""))
        v_price = tk.StringVar(
            value=f'{float((row or {}).get("unit_price") or 0):.2f}'
            if editing else "")
        for r, (label, var, hint) in enumerate((
                ("Part number", v_part, "e.g. FPFG425-020"),
                ("Product",     v_name, "What it is, for this list"),
                ("Invoice text", v_desc, "What Xero puts on the line (optional)"),
                ("Price ex GST", v_price, "e.g. 27.00"))):
            tk.Label(body, text=label, bg=CBG, fg=CTX, font=F_BODY,
                     anchor="w").grid(row=r, column=0, sticky="w", pady=4)
            ent = field_entry(body, textvariable=var, width=40)
            ent.grid(row=r, column=1, sticky="ew", padx=(10, 0), pady=4)
            if editing and label == "Part number":
                ent.config(state="readonly")   # renaming would orphan the row
            tk.Label(body, text=hint, bg=CBG, fg=CMU,
                     font=F_SM).grid(row=r, column=2, sticky="w", padx=(10, 0))

        foot = tk.Frame(dlg, bg=CBG, padx=16, pady=10)
        foot.pack(fill="x")

        def _save():
            part = v_part.get().strip().upper()
            if not part:
                messagebox.showerror("Product", "A part number is required.",
                                     parent=dlg)
                return
            try:
                price = float(v_price.get().strip().lstrip("$") or 0)
            except ValueError:
                messagebox.showerror("Product",
                                     "Enter the price as a number, e.g. 27.00.",
                                     parent=dlg)
                return
            try:
                _db.set_price(part, price, v_name.get().strip(),
                              v_desc.get().strip())
            except Exception as exc:
                messagebox.showerror("Product", f"Could not save:\n{exc}",
                                     parent=dlg)
                return
            self._load_prices(force=True)
            dlg.destroy()
            self._refresh_products_list()
            self.status_var.set(f"{part} saved at ${price:,.2f}.")

        flat_btn(foot, "Cancel", dlg.destroy, bg=CNE,
                 pady=7).pack(side="right", padx=(8, 0))
        flat_btn(foot, "Save", _save, bg=CGR, pady=7).pack(side="right")
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        dlg.bind("<Return>", lambda _e: _save())
        W, H = 620, 260
        dlg.geometry(f"{W}x{H}+{self.master.winfo_rootx() + 140}"
                     f"+{self.master.winfo_rooty() + 110}")

    def _delete_product(self):
        row = self._selected_product()
        if not row:
            messagebox.showinfo("Delete Product", "Select a product first.")
            return
        part = row.get("part_number", "")
        if not messagebox.askyesno(
                "Delete Product",
                f"Remove {part} from the price list?\n\n"
                "Quotes will show it as \"to be confirmed\" until it is "
                "priced again."):
            return
        try:
            _db.delete_price(part)
        except Exception as exc:
            messagebox.showerror("Delete Product", f"Could not delete:\n{exc}")
            return
        self._load_prices(force=True)
        self._refresh_products_list()
        self.status_var.set(f"{part} removed from the price list.")

    def _clear_price_list(self):
        """Empty the price list — for starting a re-import from scratch."""
        try:
            total = _db.count_prices()
        except Exception:
            total = 0
        if not total:
            messagebox.showinfo("Clear Price List", "The price list is empty.")
            return
        if not messagebox.askyesno(
                "Clear Price List",
                f"Delete all {total:,} priced part numbers?\n\n"
                "Nothing else is touched — orders, customers and stock are "
                "unaffected — but every quote will show as unpriced until "
                "prices are imported again.\n\nThis cannot be undone.",
                icon="warning", default="no"):
            return
        try:
            _db.clear_price_list()
            _db.log_action("prices_cleared", f"{total} part numbers")
        except Exception as exc:
            messagebox.showerror("Clear Price List", f"Could not clear:\n{exc}")
            return
        self._load_prices(force=True)
        self._refresh_products_list()
        self.status_var.set("Price list cleared.")

    # ── Dashboard tab ─────────────────────────────────────────────────────

    def _build_dashboard_tab(self):
        frm = tk.Frame(self.content, bg=CBG, padx=16, pady=12)
        frm.grid(row=0, column=0, sticky="nsew")
        frm.columnconfigure(0, weight=1)
        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(1, weight=1)
        frm.rowconfigure(2, weight=1)
        self._tab_frames["dashboard"] = frm

        head = tk.Frame(frm, bg=CBG)
        head.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        tk.Label(head, text="Dashboard", bg=CBG, fg=CA,
                 font=F_TTL).pack(side="left", anchor="n")

        # Alerts panel top-right
        alert_outer = tk.Frame(frm, bg=CCA, relief="flat", bd=1,
                               highlightbackground=CSP, highlightthickness=1)
        alert_outer.grid(row=0, column=1, sticky="ne", padx=(8, 0))
        tk.Label(alert_outer, text="⚠  Low Stock Alerts", bg=CCA, fg=CRD,
                 font=F_SEC).pack(anchor="w", padx=8, pady=(6, 2))
        self._alert_list_frame = tk.Frame(alert_outer, bg=CCA)
        self._alert_list_frame.pack(fill="x", padx=8, pady=(0, 6))

        # What's due — the first thing worth knowing on opening the app.
        # Each line opens Previous Orders already filtered to it.
        due_outer = tk.Frame(head, bg=CCA, relief="flat", bd=1,
                             highlightbackground=CSP, highlightthickness=1)
        due_outer.pack(side="left", padx=(24, 0))
        tk.Label(due_outer, text="🗓  Due", bg=CCA, fg=CA,
                 font=F_SEC).pack(anchor="w", padx=8, pady=(6, 2))
        self._due_list_frame = tk.Frame(due_outer, bg=CCA)
        self._due_list_frame.pack(fill="x", padx=8, pady=(0, 6))

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
            self._refresh_due_panel(data)
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
            self._refresh_due_panel(data)

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

    def _refresh_due_panel(self, data=None):
        """Counts of what is late, due today and due this week.

        Finished and dispatched orders are not counted — the panel is about
        work still in the shop. Each line opens the list filtered to it, so
        the number is a way in rather than just a number.
        """
        frame = getattr(self, "_due_list_frame", None)
        if frame is None:
            return
        for w in frame.winfo_children():
            w.destroy()
        if data is None:
            data = getattr(self, "_all_orders_data", [])

        counts = {"overdue": 0, "today": 0, "week": 0}
        for row in data:
            bucket = due_bucket(row)
            if bucket in counts:
                counts[bucket] += 1

        rows = [
            ("Overdue",       counts["overdue"], "#FADBD8", "#922B21"),
            ("Due today",     counts["today"],   "#FDEBD0", "#7E5109"),
            ("Due this week", counts["overdue"] + counts["today"] + counts["week"],
             CCA, CTX),
        ]
        if not any(c for _, c, _, _ in rows):
            tk.Label(frame, text="✔  Nothing outstanding",
                     bg=CCA, fg=CMU, font=F_SM).pack(anchor="w")
            return
        for label, count, bg, fg in rows:
            lbl = tk.Label(frame, text=f"  {label}:  {count}  ",
                           bg=bg, fg=fg if count else CMU,
                           font=F_BODY if count else F_SM,
                           anchor="w", cursor="hand2")
            lbl.pack(fill="x", pady=1)
            lbl.bind("<Button-1>",
                     lambda _e, f=label: self._show_orders_due(f))

    def _show_orders_due(self, due_filter: str):
        """Open Previous Orders showing just that slice of the due list."""
        self._show_tab("prev_orders")
        try:
            self.filter_due_var.set(due_filter)
            self.filter_status_var.set("All")
            self.search_var.set("")
        except Exception:
            pass

    def _refresh_alerts(self, data=None):
        for w in self._alert_list_frame.winfo_children():
            w.destroy()
        if not (_db.is_ready() and _db.current_user()):
            tk.Label(self._alert_list_frame, text="Offline — no alerts",
                     bg=CCA, fg=CMU, font=F_SM).pack(anchor="w")
            return
        if data is None:
            data = getattr(self, "_all_orders_data", [])

        # How much of each grade has gone out this month, counted in the
        # database. This used to walk every line of every order the app had
        # downloaded — which is most of the reason it downloaded them.
        today = _dt_module.date.today()
        month_start = today.replace(day=1)
        media_usage = _db.media_usage_since(month_start)

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
        flat_btn(top, "⇩ Import from Orders",
                 self._import_customers_from_orders,
                 bg=CGR, pady=5, padx=12, font=F_BODY).pack(side="right", padx=(8, 0))
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
            self._cust_tree.column(col, width=px(wd), anchor=anc, minwidth=px(40),
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
        flat_btn(bot, "🌐 Customer Portal",
                 self._customer_portal_link,
                 bg=CNE, pady=7).pack(side="left", padx=(0, 8))

        flat_btn(bot, "🗑 Delete",
                 self._delete_customer,
                 bg=CRD, pady=7).pack(side="right")

        self._customers_data: list = []

    # ── Import customers from existing orders ─────────────────────────────
    @staticmethod
    def _split_location(loc: str) -> "tuple[str, str]":
        """Best-effort split of a free-text location into (city, state)."""
        loc = (loc or "").strip()
        if not loc:
            return "", ""
        if "," in loc:
            city, state = loc.rsplit(",", 1)
            return city.strip(), state.strip()
        return loc, ""

    def _import_customers_from_orders(self):
        """Create customer records for every customer that appears in existing
        orders (DB + local) but isn't in the customer database yet."""
        if not (_db.is_ready() and _db.current_user()):
            messagebox.showinfo("Import from Orders",
                "You need to be signed in to the shared database to import customers.")
            return
        if not messagebox.askyesno(
                "Import from Orders",
                "Scan all previous orders and add any customers that aren't in "
                "the customer database yet?\n\n"
                "Existing customers are left untouched. Contact name and "
                "location are filled in from each customer's most recent order "
                "where available."):
            return

        self.status_var.set("Importing customers from orders…")

        def _work():
            added, err = [], None
            try:
                # Existing names (active + inactive) to avoid duplicates.
                existing = {(c.get("name") or "").strip().lower()
                            for c in _db.get_customers(active_only=False)}

                # Gather headers from DB orders (richest) + local JSON orders.
                headers = []
                try:
                    for r in _db.get_all_orders():
                        h = r.get("header") or {}
                        headers.append({
                            "name":      r.get("customer_name") or h.get("Customer Name", ""),
                            "attention": h.get("Attention", ""),
                            "location":  h.get("Location", ""),
                        })
                except Exception:
                    pass
                for r in self._scan_local_orders():
                    h = (r.get("db_header") or {})
                    headers.append({
                        "name":      r.get("customer", ""),
                        "attention": h.get("Attention", ""),
                        "location":  h.get("Location", ""),
                    })

                # First occurrence wins (orders come newest-first).
                seen, to_add = set(existing), {}
                for h in headers:
                    name = (h.get("name") or "").strip()
                    key  = name.lower()
                    if not name or key in seen:
                        continue
                    seen.add(key)
                    to_add[key] = h

                for h in to_add.values():
                    city, state = self._split_location(h.get("location", ""))
                    try:
                        _db.create_customer({
                            "name":           h["name"].strip(),
                            "contact_person": (h.get("attention") or "").strip(),
                            "delivery_city":  city,
                            "delivery_state": state,
                            "notes":          "Imported from existing orders.",
                            "is_active":      True,
                        })
                        added.append(h["name"].strip())
                    except Exception:
                        pass
            except Exception as exc:
                err = str(exc)

            def _done():
                if err:
                    messagebox.showerror("Import from Orders", f"Import failed:\n{err}")
                    self.status_var.set("Customer import failed.")
                    return
                if added:
                    _db.log_action("customers_imported",
                                   f"{len(added)} customer(s) added from orders")
                    preview = "\n".join(f"  • {n}" for n in sorted(added)[:20])
                    more = f"\n  …and {len(added) - 20} more" if len(added) > 20 else ""
                    messagebox.showinfo("Import from Orders",
                        f"Added {len(added)} new customer(s):\n\n{preview}{more}")
                else:
                    messagebox.showinfo("Import from Orders",
                        "No new customers found — every customer in your orders "
                        "is already in the database.")
                self.status_var.set(
                    f"Customer import complete — {len(added)} added.")
                self._refresh_customers_list()

            self.master.after(0, _done)

        threading.Thread(target=_work, daemon=True).start()

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

    def _open_customer_dialog(self, edit: bool = False, prefill: dict = None,
                              on_saved=None):
        """Add or edit a customer.

        `prefill` seeds a new profile from a purchase order, and `on_saved`
        receives the saved record — that is how the review screen turns an
        unrecognised branch into a profile without leaving the import.
        """
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

        g = cust or prefill or {}

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
        tk.Label(body, text='Goes on the order, e.g. "CAS - Bells Creek". One per branch.',
                 bg=CBG, fg=CMU, font=(FAM, 7)).grid(
            row=_row-1, column=2, sticky="w", padx=6)
        _row_f("Legal Name",    v_legal)

        # Delivery region and job-number wording — both go onto every order
        # imported for this branch.
        v_region = tk.StringVar(value=g.get("region", ""))
        tk.Label(body, text="Region", bg=CBG, fg=CTX, font=F_BODY,
                 anchor="w").grid(row=_row, column=0, sticky="w", pady=4)
        _rg = ttk.Combobox(body, textvariable=v_region, state="readonly",
                           values=[""] + list(_pn.REGION_NAMES))
        _rg.grid(row=_row, column=1, sticky="ew", pady=4)
        tk.Label(body, text="Used as Location on their orders.",
                 bg=CBG, fg=CMU, font=(FAM, 7)).grid(
            row=_row, column=2, sticky="w", padx=6)
        _row += 1

        v_joblbl = tk.StringVar(value=g.get("job_number_label", ""))
        tk.Label(body, text="Job Number After", bg=CBG, fg=CTX, font=F_BODY,
                 anchor="w").grid(row=_row, column=0, sticky="w", pady=4)
        _jrow = tk.Frame(body, bg=CBG)
        _jrow.grid(row=_row, column=1, sticky="ew", pady=4)
        field_entry(_jrow, textvariable=v_joblbl, width=18).pack(
            side="left", fill="x", expand=True)

        def _highlight_job():
            dlg2 = JobNumberHighlighter(dlg)
            dlg.wait_window(dlg2)
            try:
                dlg.grab_set()   # child dialog took the grab — take it back
            except Exception:
                pass
            if dlg2.result:
                v_joblbl.set(dlg2.result)

        flat_btn(_jrow, "Highlight…", _highlight_job, bg=CA2, pady=3, padx=8,
                 font=F_SM).pack(side="left", padx=(6, 0))
        tk.Label(body, text='What precedes their job number, e.g. "Our Reference:".\n'
                            "Highlight it on one of their orders, or type it.",
                 bg=CBG, fg=CMU, font=(FAM, 7), justify="left").grid(
            row=_row, column=2, sticky="w", padx=6)
        _row += 1
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
                            font=F_BODY, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR,
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
                "region":           v_region.get().strip(),
                "job_number_label": v_joblbl.get().strip(),
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
                    saved  = _db.create_customer(data) or dict(data)
                    action = "customer_created"
                else:
                    _db.update_customer(cust["id"], data)
                    saved  = {**cust, **data}
                    action = "customer_updated"
                _db.log_action(action, f"Customer: {name}  ABN: {v_abn.get().strip()}")
                self.status_var.set(f"{'Created' if is_new else 'Updated'}: {name}")
                dlg.destroy()
                try:
                    self._refresh_customers_list()
                except Exception:
                    pass          # Customers tab may not be built yet
                if on_saved:
                    on_saved(saved)
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
        attach_empty_state(
                    self._stock_tree,
                    "No stock items",
                    "Add the media, frames and parts you keep on hand,\n"
                    "and orders can take them off automatically.")

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
            self._stock_tree.column(col, width=px(wd), anchor=anc, minwidth=px(30),
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
        flat_btn(bot, "🏷 Print Barcode Labels",
                 self._print_stock_labels,
                 bg=CGR, pady=7).pack(side="left", padx=(0, 8))
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
        idx   = int(sel[0])
        shown = self._shown_stock_items()
        return shown[idx] if idx < len(shown) else None

    def _selected_stock_items(self) -> list:
        """Every stock row selected, in the order the table shows them."""
        shown = self._shown_stock_items()
        out = []
        for iid in self._stock_tree.selection():
            try:
                idx = int(iid)
            except (TypeError, ValueError):
                continue
            if idx < len(shown):
                out.append(shown[idx])
        return out

    def _shown_stock_items(self) -> list:
        """The stock list as the table currently has it filtered.

        The tree stores row numbers, not items, so this rebuilds the same
        order the rows were drawn in — one place, so a filter added to one and
        not the other can't quietly select the wrong item.
        """
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
        return shown

    def _print_stock_labels(self):
        """Write a sheet of barcode labels for the racking and the rolls.

        A scanner is worth nothing until the things it scans carry a code,
        and nothing in a filter shop does by default.
        """
        picked = self._selected_stock_items()
        if not picked:
            shown = self._shown_stock_items()
            if not shown:
                messagebox.showinfo("Barcode Labels", "There are no stock items to label.")
                return
            if not messagebox.askyesno(
                    "Barcode Labels",
                    f"Nothing is selected, so this will print labels for all "
                    f"{len(shown)} item{'s' if len(shown) != 1 else ''} "
                    "currently listed.\n\nCarry on?"):
                return
            picked = shown

        dlg = tk.Toplevel(self.master)
        dlg.title("Barcode Labels")
        dlg.configure(bg=CBG, padx=18, pady=16)
        dlg.transient(self.master)
        dlg.grab_set()

        tk.Label(dlg, text=f"{len(picked)} label{'s' if len(picked) != 1 else ''} to print",
                 bg=CBG, fg=CA, font=F_SEC).grid(row=0, column=0, columnspan=2,
                                                 sticky="w", pady=(0, 2))
        tk.Label(dlg, text="Sticky label sheets, from any office supplier.\n"
                           "Feed a part-used sheet back in by telling it which\n"
                           "label to start on — counting left to right, top row first.",
                 bg=CBG, fg=CMU, font=F_SM, justify="left").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))

        tk.Label(dlg, text="Label sheet", bg=CBG, fg=CTX,
                 font=F_SM).grid(row=2, column=0, sticky="w", pady=4)
        lay_var = tk.StringVar(value=_labels.L7160.name)
        ttk.Combobox(dlg, textvariable=lay_var, state="readonly", width=32,
                     values=[l.name for l in _labels.LAYOUTS.values()]).grid(
            row=2, column=1, sticky="w", padx=(8, 0))

        tk.Label(dlg, text="Start on label", bg=CBG, fg=CTX,
                 font=F_SM).grid(row=3, column=0, sticky="w", pady=4)
        start_var = tk.StringVar(value="1")
        tk.Spinbox(dlg, from_=1, to=21, textvariable=start_var, width=6).grid(
            row=3, column=1, sticky="w", padx=(8, 0))

        guides_var = tk.BooleanVar(value=False)
        tk.Checkbutton(dlg, text="Draw label outlines (for a test print on plain paper)",
                       variable=guides_var, bg=CBG, fg=CMU, selectcolor=CCA,
                       activebackground=CBG, font=F_SM).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(6, 10))

        def _go():
            layout = next((l for l in _labels.LAYOUTS.values()
                           if l.name == lay_var.get()), _labels.L7160)
            try:
                start = max(1, int(start_var.get()))
            except ValueError:
                start = 1
            dlg.destroy()
            out = APP_DIR / "labels"
            stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
            try:
                path, problems = _labels.build_label_sheet(
                    out / f"stock_labels_{stamp}.pdf", picked,
                    layout=layout, start_at=start, guides=guides_var.get())
            except Exception as exc:
                messagebox.showerror("Barcode Labels",
                                     f"The labels could not be written:\n{exc}")
                return
            self.status_var.set(f"Labels saved: {Path(path).name}")
            if problems:
                shown = "\n".join(f"  • {p}" for p in problems[:8])
                more = f"\n  … and {len(problems) - 8} more" if len(problems) > 8 else ""
                messagebox.showwarning(
                    "Some Labels Won't Scan Well",
                    f"Saved to:\n{path}\n\n{shown}{more}")
            else:
                messagebox.showinfo(
                    "Labels Ready",
                    f"Saved to:\n{path}\n\n"
                    "Print at 100% — 'fit to page' shrinks the barcodes and a "
                    "scanner stops reading them.")
            try:
                os.startfile(str(Path(path).parent))
            except Exception:
                pass

        btns = tk.Frame(dlg, bg=CBG)
        btns.grid(row=5, column=0, columnspan=2, sticky="e")
        flat_btn(btns, "Cancel", dlg.destroy, bg=CNE, pady=6).pack(side="left", padx=(0, 8))
        flat_btn(btns, "Make Labels", _go, bg=CA, pady=6).pack(side="left")

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
                           font=F_BODY, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR,
                           bg=CCA, fg=CTX, insertbackground=CTX,
                           state="normal" if is_manager else "disabled")
        txt_desc.grid(row=r, column=1, sticky="ew", pady=5)
        if item and item.get("description"):
            txt_desc.insert("1.0", item["description"])
        r += 1

        # Notes
        _lbl(r, "Notes")
        txt_notes = tk.Text(body, height=2, width=36, wrap="word",
                            font=F_BODY, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR,
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
                               relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR, anchor="center")
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
                            font=F_BODY, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR,
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
            htree.column(col, width=px(wd), anchor="center" if col in ("change","after") else "w",
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
            self.audit_tree.column(col, width=px(wd), anchor=anc, minwidth=px(60),
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
        upd_card = tk.Frame(frm, bg=CCA, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR, padx=16, pady=12)
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
        # Shown only when the check itself failed: whatever is blocking the
        # API, the Releases page and its installer are still reachable in a
        # browser, so nobody is stuck on an old build waiting for a fix.
        self._download_upd_btn = flat_btn(btn_row, "Open Releases Page",
                                          self._open_releases_page,
                                          bg=CNE, pady=6)
        self._download_upd_btn.pack(side="left", padx=(8, 0))
        self._download_upd_btn.pack_forget()
        self._pending_update = None

        # row 3 – User Management (Managers and above only)
        if _db.is_ready() and _db.can_manage_roles():
            um_card = tk.Frame(frm, bg=CCA, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR,
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
                 bg=CNE, pady=5, padx=10, font=F_BODY).pack(side="left", padx=(0, 6))
        flat_btn(tb, "Part No. Code", self._edit_media_code,
                 bg=CA2, pady=5, padx=10, font=F_BODY).pack(side="left")

        self._refresh_media_list()

        # ── Filter Types card ─────────────────────────────────────────────
        ft_o, ft_b = card_frame(frm, title="Filter Types")
        ft_o.grid(row=9, column=0, sticky="ew", pady=(12, 0))
        ft_b.columnconfigure(0, weight=1)

        tk.Label(ft_b,
                 text="Add your own filter types (they appear in the Line Item "
                      "dialog alongside the built-ins).\n"
                      "Built-in types (shown in grey) cannot be changed. Shared "
                      "with every PC via the database.",
                 bg=CCA, fg=CMU, font=F_SM, justify="left", anchor="w",
                 ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        ft_wrap = tk.Frame(ft_b, bg=CSP)
        ft_wrap.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.filter_types_lb = tk.Listbox(
            ft_wrap, font=F_BODY, bg=CCA, fg=CTX,
            selectbackground=CA, selectforeground="white",
            activestyle="none", relief="flat", bd=0,
            highlightthickness=0, height=10)
        self.filter_types_lb.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        ft_sb = ttk.Scrollbar(ft_wrap, orient="vertical",
                              command=self.filter_types_lb.yview)
        ft_sb.pack(side="right", fill="y")
        self.filter_types_lb.configure(yscrollcommand=ft_sb.set)

        ft_tb = tk.Frame(ft_b, bg=CCA)
        ft_tb.grid(row=2, column=0, sticky="w")
        flat_btn(ft_tb, "+ Add Type", self._add_filter_type,
                 bg=CA,  pady=5, padx=10, font=F_BODY).pack(side="left", padx=(0, 6))
        flat_btn(ft_tb, "Edit",       self._edit_filter_type,
                 bg=CNE, pady=5, padx=10, font=F_BODY).pack(side="left", padx=(0, 6))
        flat_btn(ft_tb, "Delete",     self._delete_filter_type,
                 bg=CRD, pady=5, padx=10, font=F_BODY).pack(side="left")

        self._refresh_filter_types_list()

        # ── Stock ─────────────────────────────────────────────────────────
        st_card = tk.Frame(frm, bg=CCA, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR, padx=16, pady=12)
        st_card.grid(row=11, column=0, sticky="ew", pady=(12, 0))
        tk.Label(st_card, text="Stock", bg=CCA, fg=CA,
                 font=F_SEC, anchor="w").pack(anchor="w")
        tk.Label(st_card,
                 text="Take materials out of stock as orders are generated.\n"
                      "Leave this off until stock has been counted — figures "
                      "that start from a guess never come right.\n"
                      "A line is deducted when a stock item's SKU matches its "
                      "part number, or when its media is kept in m2.",
                 bg=CCA, fg=CMU, font=F_SM, justify="left",
                 anchor="w").pack(anchor="w", pady=(2, 8))
        self._auto_deduct_var = tk.BooleanVar(
            value=bool(STOCK_SETTINGS.get("auto_deduct")))
        can_stock = _db.is_ready() and _db.can_manage_stock()
        tk.Checkbutton(
            st_card, text="Deduct stock automatically when an order is generated",
            variable=self._auto_deduct_var, command=self._toggle_auto_deduct,
            bg=CCA, fg=CTX, font=F_BODY, activebackground=CCA,
            activeforeground=CTX, selectcolor=CBG, anchor="w",
            highlightthickness=0, bd=0,
            state=("normal" if can_stock else "disabled")).pack(anchor="w")
        self._auto_deduct_status = tk.StringVar(
            value="" if can_stock else "Only Managers and above can change this.")
        tk.Label(st_card, textvariable=self._auto_deduct_status,
                 bg=CCA, fg=CMU, font=F_SM, anchor="w").pack(anchor="w", pady=(6, 0))

        # ── Pricing ───────────────────────────────────────────────────────
        pc_card = tk.Frame(frm, bg=CCA, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR, padx=16, pady=12)
        pc_card.grid(row=12, column=0, sticky="ew", pady=(12, 0))
        tk.Label(pc_card, text="Pricing", bg=CCA, fg=CA,
                 font=F_SEC, anchor="w").pack(anchor="w")
        tk.Label(pc_card,
                 text="Import your price spreadsheets — one price per part "
                      "number. Any sheet works as long as it has a heading "
                      "row with a part-number column and a price column.\n"
                      "Where a part number has no listed price, a rate per m2 "
                      "for that filter type and media is used instead. A line "
                      "with neither is quoted as \"to be confirmed\", never "
                      "guessed at.",
                 bg=CCA, fg=CMU, font=F_SM, justify="left",
                 anchor="w").pack(anchor="w", pady=(2, 8))
        self._price_count_var = tk.StringVar(value="Prices loaded: checking…")
        tk.Label(pc_card, textvariable=self._price_count_var,
                 bg=CCA, fg=CTX, font=F_BODY).pack(anchor="w", pady=(0, 8))
        pc_tb = tk.Frame(pc_card, bg=CCA)
        pc_tb.pack(anchor="w")
        can_price = _db.is_ready() and _db.can_manage_prices()
        for label, cmd, colour, needs_rights in (
                ("📥  Import Price Files", self._import_price_files, CA,  True),
                ("Rates per m²",           self._edit_price_rates,   CNE, True),
                ("Refresh",                self._refresh_price_count, CNE, False)):
            b = flat_btn(pc_tb, label, cmd, bg=colour, pady=5, padx=10,
                         font=F_BODY)
            b.pack(side="left", padx=(0, 6))
            if needs_rights and not can_price:
                b.config(state="disabled")
        if not can_price:
            tk.Label(pc_card,
                     text="Only Managers and above can change prices.",
                     bg=CCA, fg=CMU, font=F_SM).pack(anchor="w", pady=(6, 0))
        self.master.after(400, self._refresh_price_count)

        # ── Local Storage ─────────────────────────────────────────────────
        ls_card = tk.Frame(frm, bg=CCA, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR, padx=16, pady=12)
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
        cp_card = tk.Frame(frm, bg=CCA, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR, padx=16, pady=12)
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
        pn_card = tk.Frame(frm, bg=CCA, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR, padx=16, pady=12)
        # row 10 — not 9: the Filter Types card already owns row 9, and two
        # cards in one grid cell draw on top of each other.
        pn_card.grid(row=10, column=0, sticky="ew", pady=(12, 0))
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
        pr_card = tk.Frame(frm, bg=CCA, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR, padx=16, pady=12)
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
        ap_card = tk.Frame(frm, bg=CCA, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR, padx=16, pady=12)
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
            alert_outer = tk.Frame(frm, bg=CCA, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR,
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

        # ── Backup ────────────────────────────────────────────────────────
        bk_card = tk.Frame(frm, bg=CCA, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR, padx=16, pady=12)
        bk_card.grid(row=13, column=0, sticky="ew", pady=(12, 0))
        tk.Label(bk_card, text="Backup & Export",
                 bg=CCA, fg=CA, font=F_SEC, anchor="w").pack(anchor="w")
        tk.Label(bk_card,
                 text="Save every order, line item, customer, quote, stock item\n"
                      "and price as spreadsheets in one dated zip file.\n\n"
                      "They open in Excel and need nothing else — not this app,\n"
                      "not an account, not the internet. Put a copy somewhere\n"
                      "that isn't the office PC.",
                 bg=CCA, fg=CMU, font=F_SM, justify="left").pack(anchor="w", pady=(2, 8))
        self._backup_status = tk.StringVar(value="")
        bk_row = tk.Frame(bk_card, bg=CCA)
        bk_row.pack(anchor="w", fill="x")
        self._backup_btn = flat_btn(bk_row, "💾  Back Up Everything",
                                    self._run_backup, bg=CGR, pady=7)
        self._backup_btn.pack(side="left", padx=(0, 8))
        flat_btn(bk_row, "Open Backups Folder", self._open_backup_folder,
                 bg=CNE, pady=7).pack(side="left", padx=(0, 8))
        tk.Label(bk_row, textvariable=self._backup_status,
                 bg=CCA, fg=CMU, font=F_SM).pack(side="left")

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
        # Only a manager gets this card, so on anyone else's screen there is
        # nothing to redraw.
        frm = getattr(self, "_alert_thresh_frame", None)
        if frm is None:
            return
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
        def _lbl(mt, suffix=""):
            code = _pn.media_code(mt, self._media_codes)
            return f"  {mt}{suffix}   →  {code}" if code else f"  {mt}{suffix}"
        for mt in DEFAULT_MEDIA_TYPES:
            self.media_lb.insert("end", _lbl(mt, "  (built-in)"))
        for mt in self._custom_media:
            self.media_lb.insert("end", _lbl(mt))
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

    def _prompt_media_name(self, title="Media Type", initial="",
                           upper=True) -> "str | None":
        """Simple inline prompt dialog for a type name. Media codes are
        upper-cased; filter type names keep their capitalisation."""
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
            v = var.get().strip()
            if upper:
                v = v.upper()
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

    def _edit_media_code(self):
        """Set the part-number code for a media type: Carbon -> CARB, so a
        flat panel comes out as FPFCARB25-020."""
        idx = self._get_selected_media_index()
        if idx is None:
            messagebox.showinfo("Part Number Code",
                                "Select a media type first.")
            return
        names = list(DEFAULT_MEDIA_TYPES) + list(self._custom_media)
        if idx >= len(names):
            return
        name = names[idx]
        current = _pn.media_code(name, self._media_codes)
        new = self._prompt_media_name(
            title=f"Part Number Code for {name}", initial=current)
        if not new or new == current:
            return
        self._media_codes[name] = new
        self._settings["media_codes"] = self._media_codes
        _save_settings(self._settings)
        if _db.is_ready() and _db.current_user() and name in self._custom_media:
            try:
                _db.set_media_code(name, new)
            except Exception as exc:
                messagebox.showwarning(
                    "Saved Locally Only",
                    f'"{name}" now uses code {new} on this PC, but it could '
                    f"not be shared:\n{exc}\n\n"
                    "If this mentions a missing column, run "
                    "migrate_customer_profiles.sql in the Supabase SQL Editor.")
        self._stamp_all_items()
        self._refresh_items_tree()
        self._refresh_media_list(_reload_db=False)
        self.status_var.set(f'{name} now uses part-number code {new}.')

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

    # ── Square metreage and part numbers ──────────────────────────────────

    def _stamp_item(self, item: dict) -> dict:
        """Recalculate a line's square metreage and part number.

        Called wherever an item is created, edited or loaded, so the two can
        never drift from the dimensions actually on the line.
        """
        return _pn.apply_derived_fields(item, self._media_codes)

    def _stamp_all_items(self):
        for it in self.items:
            self._stamp_item(it)

    def _refresh_media_codes(self):
        """Pull the part-number codes for the shared media list."""
        if not (_db.is_ready() and _db.current_user()):
            return
        try:
            codes = _db.get_media_codes()
        except Exception:
            return          # column not migrated yet — defaults still apply
        if codes:
            self._media_codes = codes
            self._settings["media_codes"] = codes
            _save_settings(self._settings)

    def _persist_media(self):
        self._settings["custom_media_types"] = self._custom_media
        _save_settings(self._settings)

    # ── Shared catalogue (presets + custom filter types) ──────────────────

    def _refresh_catalog_from_db(self):
        """Pull the shared catalogue in the background; fall back to the
        local cache (already loaded) if the table is missing or offline."""
        if not (_db.is_ready() and _db.current_user()):
            return

        def _work():
            try:
                data = _db.get_catalog_map()
            except Exception:
                return   # offline or migration not run — keep cached values
            def _apply():
                _apply_catalog(data)
                self._refresh_media_codes()
                cft = data.get("custom_filter_types")
                if isinstance(cft, list):
                    self._custom_filter_types = [str(x) for x in cft]
                    self._settings["custom_filter_types"] = self._custom_filter_types
                    _save_settings(self._settings)
                    if hasattr(self, "filter_types_lb"):
                        self._refresh_filter_types_list()
                _save_catalog_cache()
            self.master.after(0, _apply)

        threading.Thread(target=_work, daemon=True).start()

    # ── Pricing settings ──────────────────────────────────────────────────

    def _refresh_price_count(self):
        """Show how many prices and rates are loaded, off the main thread."""
        var = getattr(self, "_price_count_var", None)
        if var is None:
            return

        def _work():
            try:
                prices, rates = self._load_prices(force=True)
                text = (f"Prices loaded: {len(prices):,} part numbers"
                        f"  ·  {len(rates)} rate{'s' if len(rates) != 1 else ''} per m²")
                if not prices and not rates:
                    text = ("No prices loaded yet — import your price "
                            "spreadsheets, or run migrate_pricing.sql if "
                            "pricing has never been set up.")
            except Exception as exc:
                text = f"Couldn't read prices: {exc}"
            self.master.after(0, lambda: var.set(text))

        var.set("Prices loaded: checking…")
        threading.Thread(target=_work, daemon=True).start()

    def _import_price_files(self):
        """Read one or more price spreadsheets into the shared price list."""
        paths = filedialog.askopenfilenames(
            title="Select price spreadsheets",
            filetypes=[("Spreadsheets", "*.xlsx *.xlsm *.xls *.csv"),
                       ("Excel", "*.xlsx *.xlsm *.xls"),
                       ("CSV", "*.csv"), ("All files", "*.*")])
        if not paths:
            return
        self.status_var.set(f"Reading {len(paths)} price file"
                            f"{'s' if len(paths) != 1 else ''}…")
        self.master.update_idletasks()
        try:
            rows, problems, report = _pricing.read_price_files(paths)
        except Exception as exc:
            messagebox.showerror("Price Import",
                                 f"The files could not be read:\n{exc}")
            self.status_var.set("Price import failed.")
            return

        self._finish_price_import(paths, rows, problems, report)

    def _finish_price_import(self, paths, rows, problems, report):
        """Confirm what was read, then save it without freezing the window.

        A full price list is thousands of rows and goes up in batches, which
        takes long enough that doing it on the main thread would look like the
        app had hung.
        """
        if not rows:
            messagebox.showwarning(
                "Nothing Imported",
                "No priced rows were found.\n\n" + ("\n".join(problems) or
                "Each sheet needs a heading row with a part-number column "
                "and a price column."))
            self.status_var.set("Price import found nothing.")
            return

        # Show the columns it read from. Reading the wrong column is the
        # failure that looks like "it imported but ignored all the prices",
        # so it is put in front of the user before anything is saved.
        sample = "\n".join(
            f"    {r['part_number']}   ${r['unit_price']:,.2f}   "
            f"{(r.get('name') or r.get('description') or '')[:40]}"
            for r in rows[:3])
        cols = "\n".join(f"    {line}" for line in report[:6])
        if not messagebox.askyesno(
                "Import Prices",
                f"{len(rows):,} priced part numbers were read.\n\n"
                f"Columns used:\n{cols}\n\nFirst rows:\n{sample}\n\n"
                "Check the price column is the right one. Part numbers "
                "already in the list will be updated to these prices; "
                "anything not in these files is left as it is.\n\n"
                "Import them?"):
            self.status_var.set("Price import cancelled.")
            return

        self.status_var.set(f"Saving {len(rows):,} prices…")
        result = {}

        def _work():
            try:
                result["saved"] = _db.upsert_prices(rows)
                _db.log_action("prices_imported",
                               f"{result['saved']} part numbers from "
                               f"{len(paths)} file(s)")
            except Exception as exc:
                result["error"] = str(exc)
            self.master.after(0, _done)

        def _done():
            if "error" in result:
                messagebox.showerror(
                    "Price Import",
                    f"The prices could not be saved:\n{result['error']}\n\n"
                    "If this mentions a missing 'price_list' table, run "
                    "migrate_pricing.sql in the Supabase SQL Editor.")
                self.status_var.set("Price import failed.")
                return
            saved = result.get("saved", 0)
            self._refresh_price_count()
            if hasattr(self, "products_tree"):
                self._refresh_products_list()
            msg = f"{saved:,} prices imported."
            if problems:
                msg += "\n\nSome files had nothing to read:\n" + "\n".join(problems)
            messagebox.showinfo("Prices Imported", msg)
            self.status_var.set(f"{saved:,} prices imported.")

        threading.Thread(target=_work, daemon=True).start()

    def _edit_price_rates(self):
        """Set a fallback price per square metre per filter type and media."""
        dlg = tk.Toplevel(self.master)
        dlg.title("Rates per m²")
        dlg.configure(bg=CBG)
        dlg.transient(self.master)
        dlg.grab_set()

        hdr = tk.Frame(dlg, bg=CA, padx=16, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Rates per square metre", bg=CA, fg="white",
                 font=F_BOLD).pack(anchor="w")
        tk.Label(hdr, text="Used only where a part number has no listed price. "
                           "Leave the media blank to cover every grade.",
                 bg=CA, fg="#A9CCE3", font=F_SM).pack(anchor="w")

        body = tk.Frame(dlg, bg=CBG, padx=16, pady=12)
        body.pack(fill="both", expand=True)

        lb = tk.Listbox(body, font=F_BODY, bg=CCA, fg=CTX, height=9,
                        selectbackground=CA, selectforeground="white",
                        activestyle="none", relief="flat",
                        highlightthickness=1, highlightbackground=CSP)
        lb.pack(fill="both", expand=True)

        rows = []

        def _reload():
            lb.delete(0, "end")
            rows.clear()
            try:
                rows.extend(_db.get_price_rate_rows())
            except Exception:
                pass
            for r in rows:
                media = (r.get("media_type") or "").strip() or "any media"
                lb.insert("end", f"  {r.get('filter_type') or '—'}  ·  {media}"
                                 f"   —   ${float(r.get('rate_per_sqm') or 0):,.2f} / m²")
            if not rows:
                lb.insert("end", "  No rates set.")

        entry = tk.Frame(body, bg=CBG)
        entry.pack(fill="x", pady=(10, 0))
        tk.Label(entry, text="Filter type", bg=CBG, fg=CTX,
                 font=F_SM).grid(row=0, column=0, sticky="w")
        tk.Label(entry, text="Media (blank = any)", bg=CBG, fg=CTX,
                 font=F_SM).grid(row=0, column=1, sticky="w", padx=(8, 0))
        tk.Label(entry, text="$ per m²", bg=CBG, fg=CTX,
                 font=F_SM).grid(row=0, column=2, sticky="w", padx=(8, 0))
        ft_var = tk.StringVar(value=self.all_filter_types[0])
        mt_var = tk.StringVar(value="")
        rate_var = tk.StringVar(value="")
        ttk.Combobox(entry, textvariable=ft_var, values=self.all_filter_types,
                     state="readonly", width=16).grid(row=1, column=0, sticky="w")
        ttk.Combobox(entry, textvariable=mt_var,
                     values=[""] + list(self.all_media_types),
                     state="readonly", width=16
                     ).grid(row=1, column=1, sticky="w", padx=(8, 0))
        field_entry(entry, textvariable=rate_var, width=10
                    ).grid(row=1, column=2, sticky="w", padx=(8, 0))

        def _save():
            try:
                rate = float(str(rate_var.get()).strip().lstrip("$"))
            except ValueError:
                messagebox.showerror("Rate", "Enter the rate as a number, "
                                             "e.g. 34.50.", parent=dlg)
                return
            try:
                _db.set_price_rate(ft_var.get(), mt_var.get(), rate)
            except Exception as exc:
                messagebox.showerror("Rate", f"Could not save:\n{exc}", parent=dlg)
                return
            rate_var.set("")
            _reload()
            self._load_prices(force=True)

        def _delete():
            sel = lb.curselection()
            if not sel or sel[0] >= len(rows):
                return
            row = rows[sel[0]]
            if not messagebox.askyesno(
                    "Delete Rate",
                    f"Remove the rate for {row.get('filter_type')}?",
                    parent=dlg):
                return
            try:
                _db.delete_price_rate(row["id"])
            except Exception as exc:
                messagebox.showerror("Rate", f"Could not delete:\n{exc}", parent=dlg)
                return
            _reload()
            self._load_prices(force=True)

        btns = tk.Frame(body, bg=CBG)
        btns.pack(fill="x", pady=(10, 0))
        flat_btn(btns, "Save Rate", _save, bg=CGR, pady=6,
                 padx=12).pack(side="left")
        flat_btn(btns, "Delete Selected", _delete, bg=CRD, pady=6,
                 padx=12).pack(side="left", padx=(8, 0))
        flat_btn(btns, "Close", lambda: (self._refresh_price_count(), dlg.destroy()),
                 bg=CNE, pady=6, padx=12).pack(side="right")

        _reload()
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        W, H = 520, 430
        dlg.geometry(f"{W}x{H}+{self.master.winfo_rootx() + 120}"
                     f"+{self.master.winfo_rooty() + 80}")

    def _toggle_auto_deduct(self):
        """Turn automatic stock deduction on or off for the whole company."""
        on = bool(self._auto_deduct_var.get())
        STOCK_SETTINGS["auto_deduct"] = on
        saved = _persist_catalog_key("stock_settings", dict(STOCK_SETTINGS),
                                     parent=self.master)
        if on:
            warn = ""
            try:
                warn = _stock_usage.find_unit_problem(_db.get_stock_items()) or ""
            except Exception:
                pass
            msg = "On — orders will take their materials out of stock."
            if not saved:
                msg += " (This PC only; the shared save didn't go through.)"
            self._auto_deduct_status.set(msg)
            if warn:
                messagebox.showinfo("Stock Units", warn, parent=self.master)
        else:
            self._auto_deduct_status.set(
                "Off — stock is only changed by hand.")

    def _refresh_filter_types_list(self):
        self.filter_types_lb.delete(0, "end")
        for ft in VALID_FILTER_TYPES:
            self.filter_types_lb.insert("end", f"  {ft}  (built-in)")
        for ft in self._custom_filter_types:
            self.filter_types_lb.insert("end", f"  {ft}")
        for i in range(len(VALID_FILTER_TYPES)):
            self.filter_types_lb.itemconfig(i, fg=CMU)

    def _selected_custom_filter_index(self):
        sel = self.filter_types_lb.curselection()
        if not sel:
            return None
        idx = sel[0] - len(VALID_FILTER_TYPES)
        return idx if 0 <= idx < len(self._custom_filter_types) else None

    def _persist_filter_types(self):
        self._settings["custom_filter_types"] = self._custom_filter_types
        _save_settings(self._settings)
        _persist_catalog_key("custom_filter_types", self._custom_filter_types,
                             parent=self.master)

    def _can_manage_catalog_ui(self) -> bool:
        try:
            if _db.is_ready() and not _db.can_manage_catalog():
                messagebox.showwarning("No Permission",
                    "Only Managers, Admins and Directors can change filter types.")
                return False
        except Exception:
            pass
        return True

    def _add_filter_type(self):
        if not self._can_manage_catalog_ui():
            return
        name = self._prompt_media_name(title="Add Filter Type", upper=False)
        if not name:
            return
        if name in self.all_filter_types:
            messagebox.showwarning("Duplicate",
                f'"{name}" already exists in the filter type list.')
            return
        self._custom_filter_types.append(name)
        self._persist_filter_types()
        self._refresh_filter_types_list()
        self.status_var.set(f'Filter type "{name}" added.')

    def _edit_filter_type(self):
        if not self._can_manage_catalog_ui():
            return
        ci = self._selected_custom_filter_index()
        if ci is None:
            messagebox.showinfo("Edit", "Select a custom filter type to edit. "
                                        "Built-in types cannot be changed.")
            return
        old = self._custom_filter_types[ci]
        new = self._prompt_media_name(title="Edit Filter Type", initial=old, upper=False)
        if not new or new == old:
            return
        if new in self.all_filter_types:
            messagebox.showwarning("Duplicate",
                f'"{new}" already exists in the filter type list.')
            return
        self._custom_filter_types[ci] = new
        self._persist_filter_types()
        self._refresh_filter_types_list()
        self.status_var.set(f'Filter type renamed to "{new}".')

    def _delete_filter_type(self):
        if not self._can_manage_catalog_ui():
            return
        ci = self._selected_custom_filter_index()
        if ci is None:
            messagebox.showinfo("Delete", "Select a custom filter type to delete. "
                                          "Built-in types cannot be removed.")
            return
        name = self._custom_filter_types[ci]
        if not messagebox.askyesno("Delete",
                f'Delete filter type "{name}"?\n\n'
                "Existing orders that use it will still open correctly,\n"
                "but new items won't be able to select it."):
            return
        self._custom_filter_types.pop(ci)
        self._persist_filter_types()
        self._refresh_filter_types_list()
        self.status_var.set(f'Filter type "{name}" deleted.')

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

    def _use_supplied_order_number(self):
        """Give this order one of ours, for a customer with no PO number."""
        existing = self.hvars["Order Number"].get().strip()
        if existing and not _pn.is_supplied_order_number(existing):
            if not messagebox.askyesno(
                    "Use a TAF Order Number",
                    f'This order already has the number "{existing}".\n\n'
                    "Replace it with one of ours?", default="no"):
                return
        if _pn.is_supplied_order_number(existing):
            messagebox.showinfo(
                "Use a TAF Order Number",
                f"This order already has {existing}.\n\n"
                "Each one is only handed out once, so it keeps the number it "
                "has.")
            return
        if not (_db.is_ready() and _db.current_user()):
            messagebox.showerror(
                "Use a TAF Order Number",
                "A connection to the shared database is needed to take the "
                "next number.\n\nWithout it two PCs could be given the same "
                "one, so it isn't guessed at locally. Type the customer's own "
                "reference for now, or try again when you're back online.")
            return
        try:
            number = _db.next_supplied_order_number()
        except Exception as exc:
            messagebox.showerror(
                "Use a TAF Order Number",
                f"The next number could not be taken:\n{exc}\n\n"
                "If this mentions a missing function, run "
                "migrate_supplied_order_numbers.sql in the Supabase SQL "
                "Editor.")
            return
        self.hvars["Order Number"].set(number)
        try:
            _db.log_action("supplied_order_number",
                           f"{number} for "
                           f"{self.hvars['Customer Name'].get().strip()}")
        except Exception:
            pass
        self.status_var.set(f"{number} — our order number for this job.")

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

    # ── Offline order queue ───────────────────────────────────────────────
    # Orders that couldn't be written to the shared database (connection down,
    # Supabase unreachable) are parked as JSON in pending_sync/ and re-sent
    # automatically: shortly after startup and every 5 minutes thereafter.

    def _queue_order_for_sync(self, header, items, order_type, reason=""):
        """Park an order locally for later database sync. Returns the path,
        or None if even the local write failed."""
        try:
            PENDING_SYNC_DIR.mkdir(parents=True, exist_ok=True)
            stamp = _dt_module.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = PENDING_SYNC_DIR / f"order_{stamp}.json"
            path.write_text(json.dumps({
                "header":     header,
                "items":      items,
                "order_type": order_type,
                "queued_at":  _dt_module.datetime.now().isoformat(timespec="seconds"),
                "error":      (reason or "")[:300],
            }, indent=2, default=str), encoding="utf-8")
            return path
        except Exception:
            return None

    def _start_pending_sync_loop(self):
        """Try to sync queued orders now, then re-check every 5 minutes."""
        self._sync_pending_orders()
        self.master.after(5 * 60 * 1000, self._start_pending_sync_loop)

    def _sync_pending_orders(self):
        try:
            files = sorted(PENDING_SYNC_DIR.glob("*.json"))
        except Exception:
            files = []
        if not files or not (_db.is_ready() and _db.current_user()):
            return

        def _work():
            synced = 0
            for p in files:
                try:
                    payload = json.loads(p.read_text(encoding="utf-8"))
                    header  = payload.get("header", {})
                    items   = payload.get("items", [])
                    otype   = payload.get("order_type", "filter")

                    # If the order actually reached the database (e.g. the
                    # original insert timed out *after* succeeding), don't
                    # insert it twice — just drop the queued copy.
                    already = False
                    try:
                        on   = (header.get("Order Number", "") or "").strip().lower()
                        cust = (header.get("Customer Name", "") or "").strip().lower()
                        for d in _db.find_potential_duplicates(
                                header.get("Customer Name", ""),
                                header.get("Order Number", ""), items):
                            if ((d.get("order_number", "") or "").strip().lower() == on
                                    and (d.get("customer_name", "") or "").strip().lower() == cust):
                                already = True
                                break
                    except Exception:
                        pass

                    if not already:
                        _db.save_order(header, items, otype)
                        _db.log_action("order_created",
                            f"Customer: {header.get('Customer Name','')}  "
                            f"O/N: {header.get('Order Number','')}  "
                            f"Type: {otype}  Items: {len(items)}  "
                            f"(entered offline {payload.get('queued_at','')}, synced now)")
                    p.unlink()
                    synced += 1
                except Exception:
                    break   # still offline — leave the rest for the next cycle

            if synced:
                def _done():
                    self.status_var.set(
                        f"Synced {synced} queued order{'s' if synced != 1 else ''} "
                        f"to the shared database.")
                    self._tab_loaded.pop("prev_orders", None)
                    self._tab_loaded.pop("dashboard", None)
                self.master.after(0, _done)

        threading.Thread(target=_work, daemon=True).start()

    # ── "What's New" after an update ──────────────────────────────────────

    def _maybe_show_whats_new(self):
        """On the first launch of a new version, show its release notes once."""
        try:
            seen = LAST_VERSION_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            seen = ""
        if seen == APP_VERSION:
            return
        try:
            LAST_VERSION_FILE.write_text(APP_VERSION, encoding="utf-8")
        except Exception:
            pass
        if not seen:
            return   # fresh install, not an update — nothing to announce

        def _work():
            try:
                from taf_order_app import updater as _upd
                notes = _upd.get_release_notes(APP_VERSION)
            except Exception:
                notes = ""
            self.master.after(0, lambda: self._show_whats_new_dialog(notes, seen))

        threading.Thread(target=_work, daemon=True).start()

    def _show_whats_new_dialog(self, notes: str, old_version: str):
        dlg = tk.Toplevel(self.master)
        dlg.title(f"What's New — v{APP_VERSION}")
        dlg.transient(self.master)
        dlg.configure(bg=CBG)
        W, H = 560, 420
        dlg.geometry(f"{W}x{H}+{self.master.winfo_rootx()+self.master.winfo_width()//2-W//2}"
                     f"+{self.master.winfo_rooty()+self.master.winfo_height()//2-H//2}")

        hdr = tk.Frame(dlg, bg=CA, padx=14, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text=f"✨ Updated to v{APP_VERSION}", bg=CA, fg="white",
                 font=(FAM, 12, "bold")).pack(anchor="w")
        tk.Label(hdr, text=f"You were on v{old_version}", bg=CA, fg="#A9CCE3",
                 font=F_SM).pack(anchor="w")

        body = tk.Frame(dlg, bg=CCA, highlightbackground=CSP, highlightthickness=1)
        body.pack(fill="both", expand=True, padx=14, pady=12)
        txt = tk.Text(body, bg=CCA, fg=CTX, font=F_BODY, wrap="word",
                      relief="flat", padx=12, pady=10)
        vsb = ttk.Scrollbar(body, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        txt.insert("1.0", notes.strip() or
                   "The update installed successfully.\n\n"
                   "Release notes couldn't be fetched right now — you can read "
                   "them any time on the GitHub releases page.")
        txt.configure(state="disabled")

        foot = tk.Frame(dlg, bg=CBG, pady=4, padx=14)
        foot.pack(fill="x")
        flat_btn(foot, "Close", dlg.destroy, bg=CA, pady=6, padx=18).pack(side="right", pady=(0, 10))

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
                 relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR,
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
                             media_types=self.all_media_types,
                             filter_types=self.all_filter_types)
        self.master.wait_window(dlg)
        if dlg.result:
            dlg.result["item_kind"] = "filter"
            self._stamp_item(dlg.result)
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
                                 media_types=self.all_media_types,
                                 filter_types=self.all_filter_types)
        self.master.wait_window(dlg)
        if dlg.result:
            dlg.result["item_kind"] = item.get("item_kind", "filter")
            self._stamp_item(dlg.result)
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
        # New Order is built the first time it is opened, not at start-up, so
        # anything that touches the lines before then — a restored draft, an
        # imported purchase order — has no tree to draw into yet. The lines
        # are already in self.items; _build_new_order_tab draws them when it
        # builds the table.
        if getattr(self, "tree", None) is None:
            return
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
                if item.get("header"):       opts.append("Header")
                if item.get("half_size"):    opts.append("Half")
                if item.get("gelled"):       opts.append("Gelled")
                if item.get("special_size"): opts.append("Special")
                if item.get("label_suffix"): opts.append(item["label_suffix"])
                opt_str  = ", ".join(opts) if opts else "—"
                notes    = (item.get("notes", "") or "")[:140]
                kind_lbl = "Bag/Roll"
                tag      = "bag_e" if i % 2 == 0 else "bag_o"
                sqm      = "—"
                partno   = item.get("part_number", "") or "—"
                # A header is a flat panel made to sit on the bag; show what
                # it is so the floor knows what to cut.
                _hp = _pn.header_panel_item(item)
                if _hp:
                    _pn.apply_derived_fields(_hp, self._media_codes)
                    notes = (f"[HEADER {_hp['Short']}×{_hp['Long']}×{_hp['Channel']} "
                             f"{_hp.get('Part Number','')}] " + notes)[:180]
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
                area     = _pn.effective_area(item)
                sqm      = _pn.format_sqm(area) if area > 0 else "—"
                partno   = item.get("Part Number", "") or "—"

            _kb = _type_badge(kind_lbl)
            self.tree.insert("", "end", iid=str(i), tags=(tag,),
                text=("" if _kb else kind_lbl), image=(_kb or ""),
                values=(qty, pt, size, sqm, media, partno, opt_str, notes))
        n = len(self.items)
        self._items_card.set_header_right(f"{n} item{'s' if n != 1 else ''}")
        self._schedule_draft_save()

    def _collect_header(self) -> dict:
        header = {k: v.get().strip() for k, v in self.hvars.items()}
        # One of ours is tidied so TAF-ON-7 and taf-on-0007 are recognisably
        # the same order; a customer's own reference is left exactly as they
        # wrote it, because theirs is not ours to reformat.
        header["Order Number"] = _pn.normalise_order_number(
            header.get("Order Number", ""))
        header["Notes"]       = self.txt_header_notes.get("1.0", "end").strip()
        header["customer_id"] = getattr(self, "_selected_customer_id", "")
        return header

    @staticmethod
    def _merge_pdfs(pdf_paths: list, out_path: str) -> bool:
        """Merge a list of PDF file paths into one. Returns True on success."""
        return _ProgressDialog._merge(pdf_paths, out_path)

    # ── Phone inbox ───────────────────────────────────────────────────────
    # Photos sent from a phone are collected, read and queued in the
    # background; the button below appears with a count when any are ready.

    def _start_phone_inbox_loop(self):
        """Sweep the phone inbox now, then every minute."""
        self._sweep_phone_inbox()
        self.master.after(60 * 1000, self._start_phone_inbox_loop)

    def _sweep_phone_inbox(self):
        if not _po_import.is_configured():
            return

        def _work():
            try:
                ready = _po_import.fetch_new_batches(
                    APP_DIR, self._pair_id(),
                    media_types=self.all_media_types,
                    job_labels=self._job_labels())
            except Exception:
                ready = []

            def _done():
                if ready:
                    pend = _po_import.pending_batches(APP_DIR)
                    n = sum(len(p.get("orders") or []) for p in pend)
                    self.status_var.set(
                        f"📱 {n} order{'s' if n != 1 else ''} from a phone are "
                        f"ready to review — open Phone Inbox on the New Order tab.")
                self._refresh_inbox_badge()
            self.master.after(0, _done)

        threading.Thread(target=_work, daemon=True).start()

    def _refresh_inbox_badge(self):
        """Show the Phone Inbox button only while something is waiting."""
        btn = getattr(self, "_inbox_btn", None)
        if btn is None:
            return
        try:
            pend = _po_import.pending_batches(APP_DIR)
        except Exception:
            pend = []
        n = sum(len(p.get("orders") or []) for p in pend)
        if n:
            btn.config(text=f"📱  Phone Inbox ({n})")
            btn.pack(side="left", padx=(8, 0))
        else:
            btn.pack_forget()

    def _open_phone_inbox(self):
        """Review the oldest batch of phone-sent orders."""
        pend = _po_import.pending_batches(APP_DIR)
        if not pend:
            messagebox.showinfo(
                "Phone Inbox",
                "Nothing waiting.\n\nPhotos sent from a phone appear here "
                "within a minute of being sent.")
            self._refresh_inbox_badge()
            return

        payload = pend[0]
        batch   = payload.get("batch", "")
        orders  = payload.get("orders") or []
        who     = payload.get("sent_by") or "a phone"
        for o in orders:
            o.setdefault("warnings", [])
            o["warnings"] = [f"Sent from {who}"] + list(o["warnings"])

        self._review_imported_orders(
            orders,
            on_finish=lambda: (_po_import.clear_batch(APP_DIR, batch),
                               self._refresh_inbox_badge()))

    # ── Purchase-order import ─────────────────────────────────────────────

    # ── Phone pairing ─────────────────────────────────────────────────────

    def _pair_id(self) -> str:
        """This PC's pairing id — stamped on photos sent from a paired phone
        so they come back here and not to another office PC."""
        pid = (self._settings.get("phone_pair_id") or "").strip()
        if not pid:
            import uuid
            pid = uuid.uuid4().hex[:12]
            self._settings["phone_pair_id"] = pid
            _save_settings(self._settings)
        return pid

    def _pair_label(self) -> str:
        """Friendly name shown on the phone once it's linked."""
        who = ""
        try:
            who = _db.current_full_name() or _db.current_username() or ""
        except Exception:
            pass
        pc = os.environ.get("COMPUTERNAME") or platform.node() or "office PC"
        return f"{who} ({pc})" if who else pc

    def _phone_page_base(self) -> str:
        """Where the phone page is hosted: GitHub Pages, from this repo.

        Not Supabase. Supabase serves anything it hosts as text/plain with
        "Content-Security-Policy: default-src 'none'; sandbox" and nosniff — a
        deliberate anti-XSS policy — so a page served from an Edge Function or
        from Storage arrives on the phone as unstyled source with every script
        blocked.
        """
        override = (self._settings.get("phone_page_url") or "").strip()
        if override:
            return override.rstrip("/")
        try:
            from taf_order_app.updater import GITHUB_REPO
            owner, repo = GITHUB_REPO.split("/", 1)
        except Exception:
            owner, repo = "MalakaiCS", "TAF-App"
        return f"https://{owner.lower()}.github.io/{repo}/phone/"

    def _pair_url(self) -> str:
        """The address encoded in the QR code.

        Carries everything the phone needs — project, publishable key and this
        PC's pairing id — so the page itself holds no configuration and the
        phone remembers it after the first scan.
        """
        from urllib.parse import urlencode
        q = urlencode({
            "u": _db.SUPABASE_URL,
            "k": _db.current_anon_key(),
            "p": self._pair_id(),
            "n": self._pair_label(),
        })
        base = self._phone_page_base()
        joiner = "" if base.endswith("/") else "/"
        return f"{base}{joiner}?{q}"

    def _show_phone_qr(self):
        """Show the QR code a phone scans to link to this PC, and wait for
        photos to arrive."""
        try:
            import qrcode
            from PIL import ImageTk
        except Exception as exc:
            messagebox.showerror(
                "QR Code Unavailable",
                f"Couldn't build the QR code:\n{exc}")
            return

        try:
            url = self._pair_url()
        except Exception as exc:
            messagebox.showerror(
                "Phone Page Unavailable",
                f"Couldn't build the phone link:\n{exc}")
            return
        dlg = tk.Toplevel(self.master)
        dlg.title("Send from Phone")
        dlg.transient(self.master)
        dlg.grab_set()
        dlg.configure(bg=CBG)
        dlg.resizable(False, False)

        hdr = tk.Frame(dlg, bg=CA, padx=18, pady=12)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Scan with your phone", bg=CA, fg="white",
                 font=(FAM, 12, "bold")).pack(anchor="w")
        tk.Label(hdr, text="Point the phone camera at the code, then photograph "
                           "the purchase order.",
                 bg=CA, fg="#A9CCE3", font=F_SM).pack(anchor="w")

        body = tk.Frame(dlg, bg=CBG, padx=18, pady=16)
        body.pack(fill="both", expand=True)

        try:
            made = qrcode.make(url, box_size=8, border=2)
            # qrcode returns a thin wrapper; unwrap it so ImageTk always gets
            # a real PIL image regardless of the installed version.
            img = (made.get_image() if hasattr(made, "get_image") else made).convert("RGB")
            # A long publishable key makes a denser code; scale to a fixed size
            # so the dialog stays the same shape whatever the key's length.
            from PIL import Image as _PILImage
            img = img.resize((340, 340), _PILImage.NEAREST)
            photo = ImageTk.PhotoImage(img)
            lbl = tk.Label(body, image=photo, bg=CBG, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR)
            lbl.image = photo          # keep a reference or Tk drops it
            lbl.pack()
        except Exception as exc:
            tk.Label(body, text=f"Couldn't draw the code: {exc}",
                     bg=CBG, fg=CRD, font=F_BODY).pack()

        tk.Label(body, text=f"Linked to: {self._pair_label()}",
                 bg=CBG, fg=CTX, font=F_BOLD).pack(pady=(12, 2))
        tk.Label(body,
                 text="Sign in on the phone with your normal TAF login the "
                      "first time.\nPhotos sent from it come straight back to "
                      "this PC.",
                 bg=CBG, fg=CMU, font=F_SM, justify="center").pack()

        status = tk.StringVar(value="Waiting for photos from the phone...")
        tk.Label(body, textvariable=status, bg=CBG, fg=CA,
                 font=F_BOLD, wraplength=340, justify="center").pack(pady=(14, 0))

        link = tk.Entry(body, font=F_SM, width=46, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR)
        link.insert(0, url)
        link.configure(state="readonly")
        link.pack(pady=(12, 0))
        tk.Label(body, text="(if the camera won't scan, open this address on the phone)",
                 bg=CBG, fg=CMU, font=F_SM).pack(pady=(3, 0))

        # Stops the poll below when the window goes away, so a closed dialog
        # can't reopen itself or keep sweeping in the background.
        state = {"alive": True}
        def _closed():
            state["alive"] = False
            try:
                dlg.destroy()
            except Exception:
                pass

        foot = tk.Frame(dlg, bg=CBG, padx=18, pady=12)
        foot.pack(fill="x")
        flat_btn(foot, "Close", _closed, bg=CNE, pady=7).pack(side="right")
        dlg.protocol("WM_DELETE_WINDOW", _closed)

        def _poll():
            if not state["alive"]:
                return

            def _work():
                try:
                    ready = _po_import.fetch_new_batches(
                    APP_DIR, self._pair_id(),
                    media_types=self.all_media_types,
                    job_labels=self._job_labels())
                except Exception:
                    ready = []

                def _after():
                    if not state["alive"]:
                        return
                    if ready:
                        _closed()
                        self._refresh_inbox_badge()
                        self._open_phone_inbox()
                    else:
                        self.master.after(5000, _poll)
                self.master.after(0, _after)

            threading.Thread(target=_work, daemon=True).start()

        self.master.after(3000, _poll)

    # ── Purchase-order import ─────────────────────────────────────────────

    def _import_purchase_orders(self):
        """Offer the two ways in: photograph it on a phone, or pick a file
        that's already on this PC."""
        if not _po_import.is_configured():
            messagebox.showwarning(
                "Sign In Required",
                "Importing purchase orders needs a signed-in connection to the "
                "shared database.")
            return

        dlg = tk.Toplevel(self.master)
        dlg.title("Import Purchase Order")
        dlg.transient(self.master)
        dlg.grab_set()
        dlg.resizable(False, False)
        dlg.configure(bg=CBG)

        hdr = tk.Frame(dlg, bg=CA, padx=18, pady=12)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Import Purchase Order", bg=CA, fg="white",
                 font=(FAM, 12, "bold")).pack(anchor="w")
        tk.Label(hdr, text="Where is the purchase order?",
                 bg=CA, fg="#A9CCE3", font=F_SM).pack(anchor="w")

        body = tk.Frame(dlg, bg=CBG, padx=18, pady=16)
        body.pack(fill="both", expand=True)

        def _choose(fn):
            dlg.destroy()
            fn()

        flat_btn(body, "📱   Photograph it on a phone",
                 lambda: _choose(self._show_phone_qr),
                 bg=CA, pady=11, padx=18).pack(fill="x")
        tk.Label(body, text="Shows a QR code to scan. Photos come straight back here.",
                 bg=CBG, fg=CMU, font=F_SM).pack(anchor="w", pady=(4, 14))

        flat_btn(body, "📁   Choose a file on this PC",
                 lambda: _choose(self._import_po_files),
                 bg=CNE, pady=11, padx=18).pack(fill="x")
        tk.Label(body, text="PDF, photo, scan or a saved email.",
                 bg=CBG, fg=CMU, font=F_SM).pack(anchor="w", pady=(4, 0))

        foot = tk.Frame(dlg, bg=CBG, padx=18, pady=12)
        foot.pack(fill="x")
        flat_btn(foot, "Cancel", dlg.destroy, bg=CNE, pady=7).pack(side="right")

        dlg.update_idletasks()
        W = max(360, dlg.winfo_reqwidth())
        H = dlg.winfo_reqheight()
        dlg.geometry(f"{W}x{H}+{self.master.winfo_rootx()+self.master.winfo_width()//2-W//2}"
                     f"+{self.master.winfo_rooty()+self.master.winfo_height()//2-H//2}")

    def _import_po_files(self):
        """Read one or more purchase orders out of files on this PC, then
        open the review screen before anything is generated."""
        paths = filedialog.askopenfilenames(
            title="Select purchase order document(s)",
            filetypes=[
                ("Purchase orders", "*.pdf *.png *.jpg *.jpeg *.gif *.webp *.txt *.eml"),
                ("PDF files",   "*.pdf"),
                ("Images",      "*.png *.jpg *.jpeg *.gif *.webp"),
                ("Text / email", "*.txt *.eml *.msg"),
                ("All files",   "*.*"),
            ])
        if not paths:
            return

        n = len(paths)
        prog = tk.Toplevel(self.master)
        prog.title("Reading Purchase Orders")
        prog.transient(self.master)
        prog.grab_set()
        prog.resizable(False, False)
        prog.configure(bg=CBG)
        prog.protocol("WM_DELETE_WINDOW", lambda: None)
        tk.Label(prog, bg=CA, fg="white", font=(FAM, 11, "bold"),
                 text="Reading purchase orders…", padx=20, pady=12,
                 anchor="w").pack(fill="x")
        tk.Label(prog, bg=CBG, fg=CTX, font=F_BODY, justify="left", padx=20,
                 pady=14, text=f"Sending {n} document{'s' if n != 1 else ''} to be read.\n"
                               "This usually takes 10–40 seconds.").pack(anchor="w")
        bar = ttk.Progressbar(prog, mode="indeterminate", length=340)
        bar.pack(padx=20, pady=(0, 16))
        bar.start(12)
        prog.update_idletasks()
        W, H = 400, 190
        prog.geometry(f"{W}x{H}+{self.master.winfo_rootx()+self.master.winfo_width()//2-W//2}"
                      f"+{self.master.winfo_rooty()+self.master.winfo_height()//2-H//2}")

        self.status_var.set("Reading purchase orders…")

        def _work():
            try:
                orders = _po_import.extract_orders(
                    list(paths),
                    media_types=self.all_media_types,
                    job_labels=self._job_labels())
                err = ""
            except _po_import.POImportError as exc:
                orders, err = [], str(exc)
            except Exception as exc:
                orders, err = [], f"Import failed:\n{exc}"

            def _done():
                bar.stop()
                prog.grab_release()
                prog.destroy()
                if err:
                    self.status_var.set("Purchase order import failed.")
                    messagebox.showerror("Import Failed", err)
                    return
                if not orders:
                    self.status_var.set("No purchase orders found in those files.")
                    messagebox.showinfo(
                        "Nothing Found",
                        "No purchase orders could be read from those files.\n\n"
                        "If it's a photo, check the whole page is in frame and "
                        "the text is legible.")
                    return
                self._review_imported_orders(orders)
            self.master.after(0, _done)

        threading.Thread(target=_work, daemon=True).start()

    def _job_labels(self) -> list:
        """The wordings customers put in front of their job numbers.

        Every company labels it differently — "JOB:", "Our Reference:" — so the
        reader is told the ones we know rather than left to guess.
        """
        labels = []
        try:
            for c in _db.get_customers(active_only=True):
                lbl = (c.get("job_number_label") or "").strip()
                if lbl and lbl not in labels:
                    labels.append(lbl)
        except Exception:
            pass
        return labels

    def _create_customer_for_order(self, order, done=None):
        """Create (or link) the branch profile an imported order needs.

        Seeded from the purchase order, so the legal name and address are
        already filled in and only the short name and region need choosing.
        The wording seen on the order is remembered against the profile, so
        the next order from that branch matches without asking.
        """
        po_name = (order.get("po_customer_name") or "").strip()
        po_addr = (order.get("po_customer_address") or "").strip()
        prefill = {
            "legal_name":        po_name,
            "name":              po_name,
            "delivery_address1": po_addr,
            "contact_person":    (order["header"].get("Attention") or "").strip(),
        }

        def _saved(cust):
            # Remember the wording that points at THIS branch. The company
            # name on the order is deliberately not remembered: every branch
            # of the company prints it, so recording it against one profile
            # is what sent a Bells Creek order to the Tweed branch.
            legal = (cust.get("legal_name") or "").strip()
            for wording in (po_name, po_addr):
                if not wording or not cust.get("id"):
                    continue
                if wording.strip().lower() == legal.lower():
                    continue
                try:
                    _db.add_customer_alias(cust["id"], wording)
                except Exception:
                    pass
            order["customer"] = cust
            order["header"]["Customer Name"] = (
                (cust.get("short_name") or "").strip() or (cust.get("name") or "").strip())
            region = "Pick Up" if order.get("pickup") else (cust.get("region") or "").strip()
            if region:
                order["header"]["Location"] = region
            if done:
                done()

        self._open_customer_dialog(edit=False, prefill=prefill, on_saved=_saved)

    # ── Turning a read purchase order into a TAF order ────────────────────

    def _resolve_customer(self, order, customers=None) -> bool:
        """Point an imported order at a customer branch profile.

        The purchase order says "Complete Air Supply Pty Ltd" at a Bells Creek
        address; the order needs to say "CAS - Bells Creek" in "Sunshine
        Coast". Both come from the branch's profile, so an order with no
        profile is held back rather than written under the legal name.
        """
        try:
            people = customers if customers is not None else _db.get_customers(active_only=True)
            match = _db.match_customer(order.get("po_customer_name", ""),
                                       order.get("po_customer_address", ""),
                                       people)
        except Exception:
            match = None
        order["customer"] = match
        if not match:
            return False
        order["header"]["Customer Name"] = (
            (match.get("short_name") or "").strip() or (match.get("name") or "").strip())
        # A stated pick-up beats the branch's usual region.
        region = "Pick Up" if order.get("pickup") else (match.get("region") or "").strip()
        if region:
            order["header"]["Location"] = region
        return True

    def _apply_order_rules(self, order) -> list:
        """Settle filter type and media, then derive part numbers.

        The filter type is settled first: a stepped filter's 180 media and a
        flyscreen's part number both depend on knowing what the line is.
        Returns the media grades nobody has agreed to yet.
        """
        unknown = []
        for it in order.get("items", []):
            _pn.resolve_filter_type(it, self.all_filter_types,
                                    PO_CORRECTIONS["filter_types"])
            miss = _pn.apply_media_rules(it, self.all_media_types,
                                         PO_CORRECTIONS["media_types"])
            if miss and miss not in unknown:
                unknown.append(miss)
            self._stamp_item(it)
        return unknown

    def _resolve_unknown_media(self, names) -> bool:
        """Ask what to do about a grade that isn't on the media list.

        Returns False if the user backed out, so the caller can stop rather
        than generate an order against a media type nobody agreed to.
        """
        for name in names:
            dlg = _UnknownMediaDialog(self.master, name, self.all_media_types)
            self.master.wait_window(dlg)
            if not dlg.result:
                return False
            action, value = dlg.result
            if action == "create":
                if _db.is_ready() and _db.current_user():
                    try:
                        _db.add_media_type(name)
                    except Exception as exc:
                        messagebox.showerror(
                            "Couldn't Add Media",
                            f'"{name}" could not be added to the shared list:\n{exc}')
                        return False
                if name not in self._custom_media:
                    self._custom_media.append(name)
                self._persist_media()
                self.status_var.set(f'Media type "{name}" added.')
            else:
                self._media_swaps[name] = value
        return True

    def _review_imported_orders(self, orders, on_finish=None):
        """Show the review screen, then generate whatever was approved.

        `on_finish` runs once the batch is dealt with either way — it's what
        clears a phone batch from the inbox, including when the review is
        cancelled (the photos have been read; leaving it queued would just
        re-prompt forever).
        """
        n = len(orders)
        self.status_var.set(
            f"Read {n} purchase order{'s' if n != 1 else ''} — check them before generating.")

        # Settle media grades first: a grade nobody has agreed to must not
        # reach a part number.
        self._media_swaps = {}
        unknown = []
        for o in orders:
            for miss in self._apply_order_rules(o):
                if miss not in unknown:
                    unknown.append(miss)
        if unknown and not self._resolve_unknown_media(unknown):
            self.status_var.set("Import cancelled — media not settled.")
            if on_finish:
                on_finish()
            return
        if self._media_swaps:
            for o in orders:
                for it in o.get("items", []):
                    swap = self._media_swaps.get((it.get("Media Type") or "").strip())
                    if swap:
                        it["Media Type"] = swap
            # A grade swapped once is swapped from now on, rather than asked
            # about on every order that mentions it.
            self._learn_corrections({"media_types": dict(self._media_swaps)})
        for o in orders:
            self._apply_order_rules(o)

        # Then point each order at its customer branch.
        try:
            people = _db.get_customers(active_only=True)
        except Exception:
            people = []
        for o in orders:
            self._resolve_customer(o, people)

        dlg = POReviewDialog(self.master, orders,
                             media_types=self.all_media_types,
                             filter_types=self.all_filter_types,
                             on_create_customer=self._create_customer_for_order)
        self.master.wait_window(dlg)
        if not dlg.result:
            self.status_var.set("Purchase order import cancelled.")
            if on_finish:
                on_finish()
            return
        self._learn_corrections(dlg.learned)
        self._generate_imported_orders(dlg.result, on_finish=on_finish)

    def _learn_corrections(self, learned) -> None:
        """Keep what a review taught, and share it with the other PCs.

        Failing to save is not worth interrupting an import over — the lesson
        still applies on this PC for the rest of the session and is written to
        the local cache, so the next start keeps it.
        """
        if not isinstance(learned, dict):
            return
        added = 0
        for bucket in ("filter_types", "media_types"):
            for written, meaning in (learned.get(bucket) or {}).items():
                key = _pn.wording_key(str(written))
                meaning = str(meaning).strip()
                if not key or not meaning:
                    continue
                if PO_CORRECTIONS[bucket].get(key) == meaning:
                    continue
                PO_CORRECTIONS[bucket][key] = meaning
                added += 1
        if not added:
            return
        _persist_catalog_key("po_corrections", PO_CORRECTIONS, quiet=True)
        self.status_var.set(
            f"Learned {added} correction{'s' if added != 1 else ''} — "
            "the next order using that wording is read the same way.")

    def _generate_imported_orders(self, orders, on_finish=None):
        """Generate, save and print each approved order in turn.

        Each one goes through the normal Generate path — same validation,
        duplicate check, database save and printing — so an imported order is
        indistinguishable from a hand-entered one afterwards.
        """
        total = len(orders)
        results = {"ok": 0, "failed": 0}

        def _run(idx):
            if idx >= total:
                done = results["ok"]
                failed = results["failed"]
                self.status_var.set(
                    f"Imported {done} of {total} order{'s' if total != 1 else ''}.")
                msg = (f"{done} order{'s' if done != 1 else ''} generated, saved "
                       f"and sent to the printer.")
                if failed:
                    msg += (f"\n\n{failed} were not generated — they were "
                            "skipped, flagged as duplicates, or reported an "
                            "error above.")
                messagebox.showinfo("Import Complete", msg)
                if on_finish:
                    on_finish()
                return

            order = orders[idx]
            self.status_var.set(
                f"Generating imported order {idx + 1} of {total}…")
            self._load_order_into_form(order["header"], order["items"])

            def _next(ok):
                results["ok" if ok else "failed"] += 1
                # Let the current order's dialogs close before starting the
                # next one, so the popups don't stack up.
                self.master.after(400, lambda: _run(idx + 1))

            self._generate(on_done=_next, quiet=True)

        _run(0)

    def _load_order_into_form(self, header, items):
        """Put an order into the New Order tab, replacing whatever is there."""
        for k, var in self.hvars.items():
            var.set(str(header.get(k, "")))
        self.txt_header_notes.delete("1.0", "end")
        self.txt_header_notes.insert("1.0", header.get("Notes", "") or "")
        self.items = [dict(i) for i in items]
        for it in self.items:
            it.setdefault("item_kind", "bag" if "product_type" in it else "filter")
        self._stamp_all_items()
        self._refresh_items_tree()
        self._show_tab("new_order")
        self.master.update_idletasks()

    # ── Quotes ────────────────────────────────────────────────────────────

    # How long a fetched price list is treated as current. Long enough that
    # moving between tabs never re-downloads twelve thousand rows, short
    # enough that a price someone else corrected turns up the same morning.
    _PRICE_TTL = 600

    def _load_prices(self, force=False):
        """The price list and the per-m2 rates, cached between uses.

        A full list is thousands of rows and a dozen round trips. Opening the
        Quotes tab used to force a re-fetch every single time.
        """
        import time
        fresh = (time.monotonic() - getattr(self, "_price_cache_at", 0)
                 < self._PRICE_TTL)
        if force or not hasattr(self, "_price_cache") or not fresh:
            prices, rates = {}, {}
            try:
                prices = _db.get_price_list()
                for row in _db.get_price_rate_rows():
                    key = _pricing._rate_key(row.get("filter_type") or "",
                                             row.get("media_type") or "")
                    try:
                        rates[key] = float(row.get("rate_per_sqm") or 0)
                    except (TypeError, ValueError):
                        continue
            except Exception:
                pass
            import time as _time
            self._price_cache = (prices, rates)
            self._price_cache_at = _time.monotonic()
        return self._price_cache

    def _open_quote(self, header, items, customer=None):
        """Price a set of items and show the quote."""
        items = [i for i in items if i]
        if not items:
            messagebox.showinfo("Nothing to Quote",
                                "This order has no line items.")
            return
        prices, rates = self._load_prices()
        if not prices and not rates:
            if not messagebox.askyesno(
                    "No Prices Loaded",
                    "No price list has been imported yet, so every line will "
                    "come out unpriced.\n\n"
                    "Import your price spreadsheets under Settings → Pricing "
                    "first.\n\nShow the quote anyway?",
                    icon="warning", default="no"):
                return
        lines = _pricing.quote_lines(items, prices, rates)
        QuoteDialog(self.master, header, lines, customer,
                    prepared_by=(_db.current_full_name()
                                 or _db.current_username() or ""),
                    on_pdf=self._save_quote_pdf,
                    on_xero=self._export_quote_xero)

    def _quote_current_order(self):
        """Quote what is on the New Order form right now."""
        if not self.items:
            messagebox.showinfo("Nothing to Quote",
                                "Add at least one line item first.")
            return
        self._stamp_all_items()
        header = self._collect_header()
        customer = None
        try:
            customer = _db.match_customer(header.get("Customer Name", ""))
        except Exception:
            pass
        self._open_quote(header, list(self.items), customer)

    def _quote_prev_order(self):
        """Quote a saved order from the Previous Orders list."""
        row = self._get_selected_order()
        if not row:
            messagebox.showinfo("Quote", "Select an order first.")
            return
        header, items = self._order_header_items(row, "Quote")
        if items is None:
            return
        for it in items:
            self._stamp_item(it)
        customer = None
        try:
            customer = _db.match_customer(header.get("Customer Name", ""))
        except Exception:
            pass
        self._open_quote(header, items, customer)

    def _quote_filename(self, header, suffix: str) -> Path:
        order_no = re.sub(r"[^A-Za-z0-9_-]+", "_",
                          (header.get("Order Number") or "quote")).strip("_")
        cust = re.sub(r"[^A-Za-z0-9_-]+", "_",
                      (header.get("Customer Name") or "")).strip("_")
        stem = "_".join(x for x in ("Quote", cust, order_no) if x)
        return ORDERS_DIR / f"{stem}{suffix}"

    def _save_quote_pdf(self, header, lines, customer):
        from taf_order_app import quote_pdf as _quote_pdf
        ORDERS_DIR.mkdir(parents=True, exist_ok=True)
        out = self._quote_filename(header, ".pdf")
        try:
            path = _quote_pdf.build_quote_pdf(
                out, header, lines, customer,
                quote_number=(header.get("Order Number") or ""),
                prepared_by=(_db.current_full_name()
                             or _db.current_username() or ""))
        except Exception as exc:
            messagebox.showerror("Quote PDF",
                                 f"The quote could not be created:\n{exc}")
            return
        self.status_var.set(f"Quote saved: {Path(path).name}")
        try:
            _db.log_action("quote_created",
                           f"O/N: {header.get('Order Number','')}  "
                           f"{len(lines)} lines")
        except Exception:
            pass
        try:
            os.startfile(str(path))
        except Exception:
            messagebox.showinfo("Quote Saved", f"Saved to:\n{path}")

    # ── Backup ────────────────────────────────────────────────────────────

    def _backup_dir(self) -> Path:
        d = APP_DIR / "backups"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _open_backup_folder(self):
        try:
            os.startfile(str(self._backup_dir()))
        except Exception as exc:
            messagebox.showinfo("Backups", f"The folder is at:\n"
                                           f"{self._backup_dir()}\n\n({exc})")

    def _run_backup(self):
        """Write a dated zip of everything, off the main thread.

        A full backup is a few thousand rows over the network; on the main
        thread that is a frozen window and someone deciding the app crashed.
        """
        if not (_db.is_ready() and _db.current_user()):
            messagebox.showwarning(
                "Back Up Everything",
                "Sign in first — the backup reads from the shared database.")
            return
        if getattr(self, "_backup_running", False):
            return
        self._backup_running = True
        self._backup_btn.config(state="disabled")
        self._backup_status.set("Starting…")

        def _note(label):
            self.master.after(0, lambda: self._backup_status.set(f"{label}…"))

        def _work():
            try:
                path, problems = _backup.build_backup(self._backup_dir(),
                                                      progress=_note)
            except Exception as exc:
                self.master.after(0, lambda: _failed(str(exc)))
                return
            self.master.after(0, lambda: _done(path, problems))

        def _failed(msg):
            self._backup_running = False
            self._backup_btn.config(state="normal")
            self._backup_status.set("")
            messagebox.showerror("Back Up Everything",
                                 f"The backup could not be written:\n{msg}")

        def _done(path, problems):
            self._backup_running = False
            self._backup_btn.config(state="normal")
            size = 0
            try:
                size = Path(path).stat().st_size
            except OSError:
                pass
            self._backup_status.set(
                f"Saved {Path(path).name} ({size / 1024:,.0f} KB)")
            self.status_var.set(f"Backup saved: {Path(path).name}")
            try:
                _db.log_action("backup_exported", Path(path).name)
            except Exception:
                pass
            if problems:
                messagebox.showwarning(
                    "Backup Incomplete",
                    f"Saved to:\n{path}\n\n"
                    "These could not be read and are NOT in the file:\n"
                    + "\n".join(f"  • {p}" for p in problems))
            else:
                messagebox.showinfo(
                    "Backup Saved",
                    f"Saved to:\n{path}\n\n"
                    "Copy it somewhere off this PC — a cloud drive or a USB "
                    "stick. Everything inside is a plain spreadsheet.")
            try:
                os.startfile(str(Path(path).parent))
            except Exception:
                pass

        threading.Thread(target=_work, daemon=True).start()

    # ── Invoicing a finished order ────────────────────────────────────────

    def _customer_record(self, name: str):
        """The customer card behind an order, for the address on an invoice."""
        name = (name or "").strip()
        if not name:
            return {}
        cache = getattr(self, "_invoice_cust_cache", None)
        if cache is None:
            cache = self._invoice_cust_cache = {}
        key = name.upper()
        if key not in cache:
            try:
                match = _db.match_customer(name)
            except Exception:
                match = None
            cache[key] = match or {}
        return cache[key]

    def _invoice_orders(self, rows, what: str):
        """Write one Xero import file covering the given orders.

        Xero takes many invoices in one file — it groups the lines by invoice
        number — so a whole delivery run is invoiced in a single import rather
        than one file per drop.
        """
        if not rows:
            messagebox.showinfo("Invoice to Xero", f"Select {what} first.")
            return
        prices, rates = self._load_prices()
        if not prices and not rates:
            messagebox.showwarning(
                "No Prices",
                "There are no prices loaded, so nothing can be invoiced.\n\n"
                "Import Price Files on the Products tab first.")
            return

        out_rows, missing, empty = [], [], []
        seen_numbers = set()
        for row in rows:
            header, items = self._order_header_items(row, "Invoice")
            if items is None:
                continue
            number = (header.get("Order Number")
                      or row.get("order_no") or "").strip()
            if number in seen_numbers:
                continue          # the same order picked twice in a selection
            seen_numbers.add(number)
            header = dict(header)
            header.setdefault("Customer Name", row.get("customer", ""))
            header.setdefault("Order Number", number)
            customer = self._customer_record(header.get("Customer Name", ""))
            lines, unpriced = _pricing.invoice_for_order(
                header, items, customer=customer, prices=prices, rates=rates)
            if not lines:
                empty.append(number or "—")
            out_rows.extend(lines)
            for line in unpriced:
                missing.append(f"{number or '—'}: {line.get('description') or line.get('part_number') or '?'}")

        if not out_rows:
            messagebox.showwarning(
                "Nothing to Invoice",
                "None of the lines on "
                + ("this order" if len(rows) == 1 else "these orders")
                + " could be priced, so there is nothing to send to Xero.\n\n"
                "Check the part numbers against the Products tab.")
            return
        if missing:
            shown = "\n".join(f"  • {m}" for m in missing[:10])
            more = f"\n  … and {len(missing) - 10} more" if len(missing) > 10 else ""
            if not messagebox.askyesno(
                    "Unpriced Lines",
                    f"{len(missing)} line{'s' if len(missing) != 1 else ''} "
                    f"{'have' if len(missing) != 1 else 'has'} no price and "
                    f"will be left off the invoice:\n\n{shown}{more}\n\n"
                    "Export the rest anyway?",
                    icon="warning", default="no"):
                return

        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        if len(seen_numbers) == 1:
            label = re.sub(r"[^A-Za-z0-9._-]+", "_",
                           next(iter(seen_numbers)) or "order")
            name = f"invoice_{label}_{stamp}.csv"
        else:
            name = f"invoices_{len(seen_numbers)}_orders_{stamp}.csv"
        out = Path(self._invoice_dir()) / name
        try:
            path = _pricing.write_xero_csv(out, out_rows)
        except Exception as exc:
            messagebox.showerror("Invoice to Xero",
                                 f"The file could not be written:\n{exc}")
            return
        try:
            _db.log_action("invoiced_to_xero",
                           f"{len(seen_numbers)} order(s), {len(out_rows)} line(s)")
        except Exception:
            pass
        self.status_var.set(f"Xero invoice file saved: {Path(path).name}")
        messagebox.showinfo(
            "Ready for Xero",
            f"{len(seen_numbers)} invoice"
            f"{'s' if len(seen_numbers) != 1 else ''} "
            f"({len(out_rows)} line{'s' if len(out_rows) != 1 else ''}) "
            f"written to:\n{path}\n\n"
            "In Xero: Business → Invoices → Import, choose this file, and "
            "check the account code and tax rate on the preview before "
            "confirming. Nothing is created in Xero until you confirm there.")
        try:
            os.startfile(str(Path(path).parent))
        except Exception:
            pass

    def _invoice_dir(self) -> Path:
        d = APP_DIR / "invoices"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _invoice_selected_orders(self):
        """Invoice whatever is selected in Previous Orders."""
        rows = self._get_selected_orders()
        # Invoicing something still on the bench is how a customer gets billed
        # for filters that never arrived, so it takes a deliberate yes.
        undelivered = [r for r in rows
                       if (r.get("status") or "Pending") != _delivery.DISPATCHED]
        if undelivered and not messagebox.askyesno(
                "Invoice to Xero",
                f"{len(undelivered)} of these "
                f"{'orders have' if len(undelivered) != 1 else 'order has'} "
                "not gone out yet.\n\nInvoice anyway?",
                icon="warning", default="no"):
            return
        self._invoice_orders(rows, "an order")

    def _invoice_delivery_run(self):
        """Invoice the orders selected on the delivery run."""
        self._invoice_orders(self._selected_delivery_orders(),
                             "the orders that went out")

    def _export_quote_xero(self, header, lines, customer):
        """Write the quote as a Xero sales-invoice import file.

        A CSV import rather than the API on purpose: it needs no credentials,
        no app registration and no connection, and Xero shows the whole batch
        for approval before anything is created.
        """
        priced = [l for l in lines if l.get("source")]
        if not priced:
            messagebox.showwarning(
                "Nothing Priced",
                "None of these lines have a price, so there is nothing to "
                "send to Xero.")
            return
        skipped = len(lines) - len(priced)
        if skipped and not messagebox.askyesno(
                "Unpriced Lines",
                f"{skipped} line{'s' if skipped != 1 else ''} "
                f"{'have' if skipped != 1 else 'has'} no price and will be "
                "left out of the Xero file.\n\nExport the rest?",
                icon="warning", default="no"):
            return
        out = self._quote_filename(header, "_xero.csv")
        try:
            rows = _pricing.xero_rows(header, priced, customer)
            path = _pricing.write_xero_csv(out, rows)
        except Exception as exc:
            messagebox.showerror("Xero Export",
                                 f"The file could not be written:\n{exc}")
            return
        self.status_var.set(f"Xero file saved: {Path(path).name}")
        messagebox.showinfo(
            "Ready for Xero",
            f"{len(rows)} line{'s' if len(rows) != 1 else ''} written to:\n"
            f"{path}\n\n"
            "In Xero: Business → Invoices → Import, choose this file, and "
            "match the account code and tax rate on the preview before "
            "confirming.")
        try:
            os.startfile(str(Path(path).parent))
        except Exception:
            pass

    def _deduct_stock_for_order(self, header, items) -> str:
        """Take an order's materials out of stock. Returns a line to show.

        Runs on the generating thread, straight after the order is saved, and
        never raises: an order that has been made and printed must not be held
        up by the stock count, and every movement is recorded as a stock
        transaction that can be reversed by hand if it turns out to be wrong.
        """
        if not STOCK_SETTINGS.get("auto_deduct"):
            return ""
        try:
            stock = _db.get_stock_items()
            if not stock:
                return ""
            plan = _stock_usage.plan_deductions(
                items, stock, header.get("Order Number", ""))
            moved = _stock_usage.apply_plan(plan, _db.adjust_stock)
            note = _stock_usage.describe(plan)
            if moved or plan.get("unmatched"):
                _db.log_action(
                    "stock_deducted",
                    f"O/N: {header.get('Order Number','')}  {note}")
            return note
        except Exception:
            # Offline, or the stock tables aren't set up. The order stands.
            return ""

    def _generate(self, on_done=None, quiet=False):
        """Generate, save and print the current order.

        `on_done(ok)` fires once the order finishes (or is abandoned), which is
        what lets an imported batch run one order after another. `quiet`
        suppresses the per-order "Done" popup so a batch shows a single summary
        instead of one dialog per order — errors are always shown.
        """
        def _bail(ok=False):
            if on_done:
                on_done(ok)

        # ── Validate required fields first ────────────────────────────────
        if not self._validate_header():
            self._show_tab("new_order")   # make sure we're on the right tab
            _bail()
            return
        if not self.items:
            messagebox.showwarning("No Items", "Add at least one item before generating.")
            _bail()
            return
        header = self._collect_header()
        if _db.is_ready() and _db.current_user():
            header["Created By"] = _db.current_full_name() or _db.current_username() or ""
        header["priority"] = bool(getattr(self, "_priority_var", None) and self._priority_var.get())

        # ── Duplicate-order guard ─────────────────────────────────────────
        # Catch the same order being keyed twice (including by two people at
        # once): ask the shared database for the same order number, or the
        # same customer with identical line items in the last fortnight.
        if _db.is_ready() and _db.current_user():
            self.status_var.set("Checking for duplicate orders…")
            self.master.update_idletasks()
            try:
                dupes = _db.find_potential_duplicates(
                    header.get("Customer Name", ""),
                    header.get("Order Number", ""),
                    self.items)
            except Exception:
                dupes = []   # offline / query failed — never block generating
            if dupes:
                lines = []
                for d in dupes[:5]:
                    who = d.get("full_name") or d.get("username") or "unknown"
                    ts  = (d.get("created_at") or "")[:16].replace("T", "  ")
                    lines.append(
                        f"•  O/N {d.get('order_number') or '—'}  ·  "
                        f"{d.get('customer_name','')}\n"
                        f"    {d.get('duplicate_reason','')} — created by {who}"
                        f"{('  ·  ' + ts) if ts.strip() else ''}")
                if not messagebox.askyesno(
                        "Possible Duplicate Order",
                        "This looks like a duplicate of an order already in the "
                        "system:\n\n" + "\n\n".join(lines) +
                        "\n\nGenerate it anyway?",
                        icon="warning", default="no"):
                    self.status_var.set("Order not generated — flagged as possible duplicate.")
                    _bail()
                    return

        ORDERS_DIR.mkdir(parents=True, exist_ok=True)

        # Ensure every stepped filter carries the *STEPPED FILTER* customer note
        # (covers items loaded/duplicated from older orders too).
        for _it in self.items:
            apply_stepped_filter_note(_it)
        # Re-derive square metreage and part numbers from the final dimensions.
        self._stamp_all_items()

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
        self._last_stock_note = ""

        # Snapshot of items captured now (immutable inside thread)
        all_items        = list(self.items)
        custom_media     = list(self._custom_media)
        custom_filter_types = list(self._custom_filter_types)
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
                        extra_filter_types=custom_filter_types,
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
                            extra_filter_types=custom_filter_types,
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
            json_path     = None
            new_order_id  = None
            try:
                json_path = service.save_order_json(header, all_items)
            except Exception as exc:
                errors.append(f"JSON save: {exc}")

            if _db.is_ready() and _db.current_user():
                try:
                    new_order_id = _db.save_order(header, all_items, order_type)
                    _db.log_action("order_created",
                        f"Customer: {header.get('Customer Name','')}  "
                        f"O/N: {header.get('Order Number','')}  "
                        f"Type: {order_type}  Items: {len(all_items)}")
                    self._last_stock_note = self._deduct_stock_for_order(
                        header, all_items)
                except Exception as exc:
                    # Couldn't reach the shared database — queue the order
                    # locally and let the background sync push it through
                    # when the connection returns.
                    q_path = self._queue_order_for_sync(header, all_items,
                                                        order_type, str(exc))
                    if q_path:
                        errors.append(
                            "Couldn't reach the shared database — the order was "
                            "saved on this PC and will sync automatically when "
                            "the connection returns.")
                    else:
                        errors.append(f"Database save failed: {exc}\n\nThe order was saved locally but not to the shared database.")

            prog.advance("Done!")

            # ── Hand results back to the main thread ──────────────────────
            prog.after(0, lambda: _finish(opened, json_path, errors,
                                          real_pdfs, pdf_paths, new_order_id))

        def _finish(opened, json_path, errors, real_pdfs, pdf_paths, new_order_id=None):
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
                stock_note = getattr(self, "_last_stock_note", "")
                if stock_note:
                    msg += (("\n\n" if msg else "") + f"Stock:\n  {stock_note}")

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
                        if not perr:
                            # Auto-printed on generate → flag it printed.
                            self._flag_printed(db_id=new_order_id, json_path=json_path)

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

                if not quiet:
                    messagebox.showinfo("Done", msg)
                _bail(True)
            else:
                _bail(False)

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
                    "printed":      bool(h.get("printed", False)),
                    "printed_at":   h.get("printed_at", ""),
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
                # Without the line items: the list shows a count, not the
                # lines, and downloading every line of every order was what
                # made these screens slow.
                db_rows = _db.get_order_list()
                for r in db_rows:
                    rows.append({
                        "source":       "db",
                        "order_type":   r.get("order_type", "filter"),
                        "customer":     r.get("customer_name", ""),
                        "order_no":     r.get("order_number", ""),
                        "date_ordered": r.get("date_ordered", ""),
                        "date_due":     r.get("date_due", ""),
                        "n_items":      (r.get("n_items")
                                         if r.get("n_items") is not None
                                         else len(r.get("items") or [])),
                        "created_by":   r.get("full_name") or r.get("username") or r.get("user_email", ""),
                    "created_by_role": r.get("created_by_role", "Employee"),
                    "user_id":      r.get("user_id", ""),
                        "path":         None,
                        "filename":     "database",
                        "db_id":        r.get("id"),
                        "db_header":    r.get("header") or {},
                        # None means "not fetched yet" — _order_header_items
                        # asks for them when an order is actually opened.
                        "db_items":     r.get("items"),
                        "priority":          bool((r.get("header") or {}).get("priority", False)),
                        "status":            (r.get("header") or {}).get("status", "Pending") or "Pending",
                        "printed":           bool((r.get("header") or {}).get("printed", False)),
                        "printed_at":        (r.get("header") or {}).get("printed_at", ""),
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
        due_sel     = getattr(self, "filter_due_var",    None)
        type_val    = type_sel.get()   if type_sel   else "All"
        status_val  = status_sel.get() if status_sel else "All"
        due_val     = due_sel.get()    if due_sel    else "All"
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
            # Due filter — what still has to be made, and by when
            if due_val != "All":
                bucket = due_bucket(r)
                keep = {
                    "Overdue":       bucket == "overdue",
                    "Due today":     bucket == "today",
                    # "This week" includes what is already late: an overdue
                    # order is the most this-week thing there is.
                    "Due this week": bucket in ("overdue", "today", "week"),
                    "No due date":   bucket == "none",
                }.get(due_val, True)
                if not keep:
                    continue
            # Date range filter
            rd = _row_date(r)
            if d_from and rd and rd < d_from:
                continue
            if d_to and rd and rd > d_to:
                continue
            displayed.append(r)

        # Looking at what's due means looking at it in due order.
        if due_val != "All":
            displayed.sort(key=due_sort_key)

        # Cache the displayed list so _get_selected_order() stays in sync
        self._displayed_orders = displayed

        for i, row in enumerate(displayed):
            is_priority = bool(row.get("priority", False))
            status      = row.get("status", "Pending") or "Pending"
            notes_cnt   = row.get("notes_count", 0) or 0
            status_lbl  = f"📝 {status}" if notes_cnt else status

            # Late work outranks the status colours: an order that is "In
            # Production" and three days late needs to read as late.
            bucket = due_bucket(row)
            if is_priority:
                tag = "priority"
            elif bucket == "overdue":
                tag = "overdue"
            elif bucket == "today":
                tag = "due_today"
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
            printed_lbl  = "🖨 Printed" if row.get("printed") else "—"
            # Say it in the column as well as in the colour — the list gets
            # read over someone's shoulder and printed out.
            due_lbl = row["date_due"] or "—"
            if bucket == "overdue":
                due_lbl = f"⚠ {due_lbl}"
            elif bucket == "today":
                due_lbl = f"● {due_lbl}"
            _badge = _type_badge(otype_label)
            self.orders_tree.insert("", "end", iid=str(i), tags=(tag,),
                text=("" if _badge else otype_label), image=(_badge or ""),
                values=(
                cust_display,
                row["order_no"],
                row["date_ordered"],
                due_lbl,
                status_lbl,
                printed_lbl,
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
            items  = list(self._db_row_items(row))
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
        items  = list(self._db_row_items(row))
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
            items  = list(self._db_row_items(row))
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

        # order_type must be known before naming the output files — building
        # the name first raised UnboundLocalError for database-sourced orders.
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

        prog         = _ProgressDialog(self.master, order_type)
        service      = self.service
        custom_media = list(self._custom_media)
        custom_filter_types = list(self._custom_filter_types)

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
                        extra_filter_types=custom_filter_types,
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
                            extra_filter_types=custom_filter_types,
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
                           font=F_BODY, relief="flat", bd=0, highlightthickness=1, highlightbackground=CBR,
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
            items  = list(self._db_row_items(row))
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
        custom_filter_types = list(self._custom_filter_types)
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
                        extra_filter_types=custom_filter_types,
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
                    # Flag the order as printed (shows in the Previous Orders list).
                    self._flag_printed(db_id=row.get("db_id"), json_path=row.get("path"))
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
                        # Refresh so the "Printed" column updates.
                        self._tab_loaded.pop("prev_orders", None)
                        self._all_orders_data = []
                        self._refresh_orders_list()
                self.master.after(0, _done)

            threading.Thread(target=_print_worker, daemon=True).start()

        threading.Thread(target=_worker, daemon=True).start()

    def _flag_printed(self, db_id=None, json_path=None):
        """Mark an order as printed in the shared DB and/or its local JSON."""
        if db_id:
            try:
                _db.mark_order_printed(str(db_id))
            except Exception:
                pass
        if json_path:
            try:
                p = Path(json_path)
                payload = json.loads(p.read_text(encoding="utf-8"))
                h = payload.setdefault("header", {})
                h["printed"]    = True
                h["printed_at"] = _dt_module.datetime.now().strftime("%d/%m/%Y %H:%M")
                p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            except Exception:
                pass

    def _db_row_items(self, row) -> list:
        """A database order's line items, fetched the first time they matter.

        The order list deliberately doesn't carry them — the lines are the
        bulk of an order and no list shows them — so this is where they are
        actually asked for, and they stay on the row afterwards.
        """
        items = row.get("db_items")
        if items is None:
            items = _db.get_order_items(row.get("db_id") or "")
            row["db_items"] = items
        return items or []

    def _order_header_items(self, row, what: str = "Order"):
        """An order-list row's header and items, wherever it came from.

        Returns ``(header, items)``, or ``({}, None)`` after reporting why the
        local file couldn't be read — callers check for ``None``.
        """
        if row.get("source") == "db":
            items = row.get("db_items")
            if items is None:
                # The list doesn't carry the lines. Fetch them the first time
                # this order is opened, and keep them on the row after that.
                items = _db.get_order_items(row.get("db_id") or "")
                row["db_items"] = items
            return dict(row.get("db_header") or {}), list(items or [])
        try:
            payload = json.loads(Path(row["path"]).read_text(encoding="utf-8"))
            return payload.get("header", {}), payload.get("items", [])
        except Exception as exc:
            messagebox.showerror(what, f"Could not read order file:\n{exc}")
            return {}, None

    def _view_order_items(self):
        """Popup listing the selected order's line items — see what's in an
        order without loading it into the New Order tab."""
        row = self._get_selected_order()
        if row is None:
            messagebox.showinfo("View Items", "Select an order from the list first.")
            return

        header, items = self._order_header_items(row, "View Items")
        if items is None:
            return

        order_no = row.get("order_no", "")
        dlg = tk.Toplevel(self.master)
        dlg.title(f"Order Items — {order_no}")
        dlg.transient(self.master)
        dlg.grab_set()
        dlg.configure(bg=CBG)
        W, H = 960, 520
        dlg.geometry(f"{W}x{H}+{self.master.winfo_rootx()+self.master.winfo_width()//2-W//2}"
                     f"+{self.master.winfo_rooty()+self.master.winfo_height()//2-H//2}")

        hdr = tk.Frame(dlg, bg=CA, padx=14, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text=row.get("customer", ""), bg=CA, fg="white",
                 font=(FAM, 11, "bold")).pack(anchor="w")
        sub_bits = [f"O/N: {order_no or '—'}"]
        if header.get("Date Ordered"): sub_bits.append(f"Ordered {header['Date Ordered']}")
        if header.get("Date Due"):     sub_bits.append(f"Due {header['Date Due']}")
        sub_bits.append(f"{len(items)} item{'s' if len(items) != 1 else ''}")
        tk.Label(hdr, text="  ·  ".join(sub_bits),
                 bg=CA, fg="#A9CCE3", font=F_SM).pack(anchor="w")

        tbl_wrap = tk.Frame(dlg, bg=CCA, highlightbackground=CSP, highlightthickness=1)
        tbl_wrap.pack(fill="both", expand=True, padx=14, pady=(12, 0))
        tbl_wrap.rowconfigure(0, weight=1)
        tbl_wrap.columnconfigure(0, weight=1)

        cols = ("qty", "item", "size", "media", "notes")
        tree = ttk.Treeview(tbl_wrap, columns=cols, show="headings",
                            style="TAF.Treeview")
        tree.grid(row=0, column=0, sticky="nsew")
        for col, (hd_txt, wd, anc, stretch) in {
            "qty":   ("Qty",              60, "center", False),
            "item":  ("Item",            250, "w",      True),
            "size":  ("Size (mm)",       170, "center", False),
            "media": ("Media",           110, "center", False),
            "notes": ("Notes",           260, "w",      True),
        }.items():
            tree.heading(col, text=hd_txt, anchor="center" if anc == "center" else "w")
            tree.column(col, width=px(wd), anchor=anc, minwidth=px(40), stretch=stretch)
        tree.tag_configure("even", background=CRE)
        tree.tag_configure("odd",  background=CCA)

        vsb = ttk.Scrollbar(tbl_wrap, orient="vertical", command=tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=vsb.set)

        for i, it in enumerate(items):
            if (it.get("item_kind") or "filter") == "bag":
                name = it.get("product_type", "Bag / Roll")
                pn   = (it.get("part_number") or "").strip()
                if pn:
                    name += f"   (P/N {pn})"
                if it.get("roll_width") or it.get("roll_length"):
                    size = f"{it.get('roll_width','')} × {it.get('roll_length','')}".strip(" ×")
                else:
                    dims = [it.get("width"), it.get("height"), it.get("depth")]
                    size = " × ".join(str(d) for d in dims if d)
                qty   = it.get("quantity", "")
                media = it.get("media", "")
                notes = it.get("notes", "")
            else:
                name  = it.get("Filter Type", "Filter")
                size  = f"{it.get('Short','')} × {it.get('Long','')} × {it.get('Channel','')}"
                qty   = it.get("Quantity", "")
                media = it.get("Media Type", "")
                notes = it.get("Notes", "")
            tree.insert("", "end", tags=("even" if i % 2 == 0 else "odd",),
                        values=(qty, name, size, media, notes))

        if header.get("Notes"):
            tk.Label(dlg, text=f"Order notes:  {header['Notes']}",
                     bg=CBG, fg=CMU, font=F_SM, wraplength=W - 40,
                     justify="left", anchor="w").pack(fill="x", padx=16, pady=(8, 0))

        foot = tk.Frame(dlg, bg=CBG, pady=10, padx=14)
        foot.pack(fill="x")
        flat_btn(foot, "Close", dlg.destroy, bg=CNE, pady=6).pack(side="right")

        def _load_and_close():
            dlg.destroy()
            self._load_prev_order()
        flat_btn(foot, "Load into New Order", _load_and_close,
                 bg=CA, pady=6).pack(side="right", padx=(0, 8))

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

    _enable_hidpi()          # before the first window, or it has no effect
    root = tk.Tk()
    root.withdraw()          # hide until login succeeds
    _apply_ui_scale(root)    # match Tk's point size to the actual screen
    # A fresh Tk root invalidates every previously-rendered PhotoImage (this
    # runs again after sign-out) — drop the badge cache so it re-renders.
    _BADGE_CACHE.clear()
    _load_app_fonts()        # register Public Sans before any widgets are built
    # Show the running version in the title so support always knows the build.
    root.title(f"{APP_TITLE}  —  v{APP_VERSION}")

    # ── Never let an error vanish silently ───────────────────────────────
    # In the windowed (no-console) exe, an exception inside a Tk callback is
    # invisible: the callback just aborts, which looks like "I clicked and
    # nothing happened". Every unhandled error (UI callback, background
    # thread, or startup) is appended to app_error.log AND mirrored to the
    # shared audit log — so crashes on any machine are diagnosable centrally,
    # without asking staff for screenshots.
    def _record_crash(kind, exc, val, tb):
        log_path = APP_DIR / "app_error.log"
        try:
            import traceback
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n[{_dt_module.datetime.now():%d/%m/%Y %H:%M:%S}] "
                        f"v{APP_VERSION} — {kind}:\n")
                traceback.print_exception(exc, val, tb, file=f)
        except Exception:
            pass
        try:
            if _db.is_ready() and _db.current_user():
                import traceback
                detail = "".join(traceback.format_exception(exc, val, tb))[-1500:]
                threading.Thread(
                    target=lambda: _db.log_action(
                        "app_error", f"v{APP_VERSION} — {kind}:\n{detail}"),
                    daemon=True).start()
        except Exception:
            pass
        return log_path

    def _report_callback_exception(exc, val, tb):
        log_path = _record_crash("error in UI callback", exc, val, tb)
        try:
            messagebox.showerror(
                "Unexpected Error",
                f"Something went wrong:\n\n{val}\n\n"
                f"Details were saved to:\n{log_path}")
        except Exception:
            pass
    root.report_callback_exception = _report_callback_exception

    _prev_sys_hook = sys.excepthook
    def _sys_hook(exc, val, tb):
        _record_crash("unhandled error", exc, val, tb)
        _prev_sys_hook(exc, val, tb)
    sys.excepthook = _sys_hook

    def _thread_hook(args):
        if args.exc_type is SystemExit:
            return
        _record_crash(f"error in thread {args.thread.name if args.thread else '?'}",
                      args.exc_type, args.exc_value, args.exc_traceback)
    threading.excepthook = _thread_hook
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
