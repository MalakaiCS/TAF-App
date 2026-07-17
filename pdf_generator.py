"""
TAF Filter Order Worksheet — direct PDF generator.
Draws ONLY the exact borders defined in Templates.xlsx (no extra boxes).
"""
from __future__ import annotations
from datetime import datetime, timedelta
import os

from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors

PAGE_W, PAGE_H = landscape(A4)   # 841.89 × 595.28 pt
MARGIN = 14.0
BLACK  = colors.black
LW_THIN   = 0.5
LW_MEDIUM = 1.5


def _get_logo_path():
    """Return path to TAF_logo.png whether running frozen or from source."""
    import sys
    from pathlib import Path
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent
    p = base / "TAF_logo.png"
    return str(p) if p.exists() else None


# ── Date helpers ──────────────────────────────────────────────────────────────

def _add_biz(start, n):
    d, added = start, 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d


def _fmt_dates(ordered_raw, due_raw):
    for fmt in ("%d/%m/%y", "%d/%m/%Y", "%d-%m-%y", "%d-%m-%Y"):
        try:
            ordered = datetime.strptime((ordered_raw or "").strip(), fmt); break
        except ValueError:
            pass
    else:
        ordered = datetime.today()
    if due_raw and due_raw.strip().upper() != "ASAP":
        for fmt in ("%d/%m/%y", "%d/%m/%Y", "%d-%m-%y", "%d-%m-%Y"):
            try:
                due = datetime.strptime(due_raw.strip(), fmt); break
            except ValueError:
                pass
        else:
            due = _add_biz(ordered, 2)
    else:
        due = _add_biz(ordered, 2)
    return (f"{ordered.day}-{ordered.month}-{ordered.strftime('%y')}",
            due.strftime("%a %d-%m-%y").upper())


# ── Calculations ──────────────────────────────────────────────────────────────

def _markings(short, long_):
    m1, m2 = 20, 20 + short - 2
    m3, m4 = m2 + long_ - 2, m2 + long_ - 2 + short - 2
    mc, mt = m4 + 20, m4 + long_ - 2
    fw_cap  = long_ - 2
    fm1, fm2 = 20, 20 + long_ - 2
    fm3, fm4 = fm2 + short - 2, fm2 + short - 2 + long_ - 2
    fmc, fmt_ = fm4 + 20, fm4 + short - 2
    fl_cap = short - 2
    rm1 = long_ - 2
    rm2, rm3 = rm1 + short - 2, rm1 + short - 2 + long_ - 2
    rm4, rmc  = rm3 + short - 2, rm3 + short - 2 + 20
    return dict(fwd=(m1, m2, m3, m4, mc, mt, fw_cap),
                flp=(fm1, fm2, fm3, fm4, fmc, fmt_, fl_cap),
                rev=(rm1, rm2, rm3, rm4, rmc))


def _wire_media(short, long_, channel, label, qty):
    lbl = str(label).upper()
    if lbl.startswith("F"):
        ws, wl, ms, ml = short-10, long_-10, short, long_
    elif lbl.startswith("V"):
        d = min(channel, 100)
        if   30 <= d <= 60:  ws = short-15; wl = int(round(long_*1.36))
        elif 65 <= d <= 80:  ws = short-10; wl = int(round(long_*1.55))
        elif 85 <= d <= 100: ws = short-10; wl = int(round(long_*1.785))
        else:                ws, wl = short, long_
        ms, ml = ws+60, wl+40
    else:
        ws, wl, ms, ml = short, long_, short, long_
    return dict(wc=f"{ws}*{wl}", wq=qty*2, mc=f"{ms}*{ml}", mq=qty)


# ── Low-level drawing ─────────────────────────────────────────────────────────

def _h(c, x1, y, x2, lw=LW_THIN):
    c.setStrokeColor(BLACK); c.setLineWidth(lw)
    c.line(x1, y, x2, y)

def _v(c, x, y1, y2, lw=LW_THIN):
    c.setStrokeColor(BLACK); c.setLineWidth(lw)
    c.line(x, y1, x, y2)

def _box(c, x, y, w, h, lw=LW_THIN):
    c.setStrokeColor(BLACK); c.setLineWidth(lw)
    c.rect(x, y, w, h, stroke=1, fill=0)

def _txt(c, x, y, w, h, text, bold=False, size=8, align="left", valign="center", offset=0):
    if text is None: return
    lines = [str(l).strip() for l in (text if isinstance(text, (list,tuple)) else [str(text)])]
    lines = [l for l in lines if l]
    if not lines: return
    font = "Helvetica-Bold" if bold else "Helvetica"
    c.setFont(font, size)
    c.setFillColor(BLACK)
    line_h = size + 1.5
    total_h = len(lines) * line_h
    if valign == "bottom":
        # Last line baseline sits just above the bottom border
        last_baseline = y + size * 0.3 + 2
        top_baseline  = last_baseline + (len(lines) - 1) * line_h
    elif valign == "top":
        # First line sits just below the top border; offset pushes it down
        top_baseline = y + h - size * 0.7 - 2 - offset
    else:
        top_baseline = y + (h + total_h) / 2 - size * 0.3
    for i, line in enumerate(lines):
        ty = top_baseline - i * line_h
        if align == "center": c.drawCentredString(x + w/2, ty, line)
        elif align == "right": c.drawRightString(x + w - 2, ty, line)
        else: c.drawString(x + 2, ty, line)


# ── Geometry ──────────────────────────────────────────────────────────────────

def _geom(col_chars, row_heights_pt):
    content_w = PAGE_W - 2 * MARGIN
    scale_x   = content_w / sum(col_chars)
    col_w = [ch * scale_x for ch in col_chars]
    col_x, x = [], MARGIN
    for cw in col_w:
        col_x.append(x); x += cw

    row_h = {r: 15.0 for r in range(1, 27)}
    row_h.update(row_heights_pt)
    scale_y = 1.25   # fixed scale — content fills ~75% of page height
    row_h = {r: row_h[r] * scale_y for r in row_h}

    row_y, y = {}, PAGE_H - MARGIN
    for r in range(1, 27):
        row_y[r] = y - row_h[r]; y -= row_h[r]
    return col_x, col_w, row_y, row_h

_VORF_ROW_H = {
    1:26.25, 2:0.1,  3:26.25, 4:4.0,   # header — row 2 gap removed (5pt closer)
    5:28.4,  6:15.0,                    # data grid
    7:5.0,   8:15.0, 9:5.0,  10:15.0,  # FLIPPED / REVERSED
    11:9.2,                             # gap to production (+4pt)
    12:21.75,13:3.0, 14:21.75,15:3.0,
    16:21.75,17:3.0, 18:21.75,19:3.0, 20:21.75,
    21:5.0,  22:21.0,                  # gap + BRACE REQ
    23:4.0,  24:13.0,25:13.0, 26:13.0, # bottom table
}
_FS_ROW_H = {
    1:26.25, 2:0.1,  3:26.25, 4:4.0,   # header — row 2 gap removed (5pt closer)
    5:28.4,  6:15.0,                    # data grid — same as VorF
    7:5.0,   8:5.0,  9:5.0,  10:5.0,  11:9.2,   # gap (no flipped/reversed)
    12:21.75,13:3.0, 14:21.75,15:3.0,
    16:21.75,17:3.0, 18:21.75,19:3.0, 20:21.75,  # production rows — same as VorF
    21:5.0,  22:21.0,                  # gap + BRACE REQ — same as VorF
    23:4.0,  24:13.0,25:13.0, 26:13.0, # bottom table — same as VorF
}
_VORF_CHARS = [8.7] + [8.43]*16   # A-Q
_FS_CHARS   = [8.7] + [8.43]*11   # A-L


# ── Header text (rows 1-4, NO borders) ───────────────────────────────────────

def _draw_header(c, col_x, col_w, row_y, row_h,
                 cust, ord_n, attn, d_ord, page_num, total_pages, last_idx,
                 created_by=""):
    cx  = lambda i: col_x[i]
    cw  = lambda *ii: sum(col_w[i] for i in ii)
    ry  = lambda r: row_y[r]
    rh  = lambda r: row_h[r]

    # ── Company logo in column A (rows 1-4) ──────────────────────────────────
    logo_path = _get_logo_path()
    if logo_path:
        try:
            pad = 3
            lx = col_x[0] + pad
            ly = row_y[4]                                    # bottom of row 4
            lw = col_w[0] - pad * 2
            lh = (row_y[1] + row_h[1]) - row_y[4] - pad    # top of row 1 → bottom of row 4
            c.drawImage(logo_path, lx, ly + pad, width=lw, height=lh,
                        preserveAspectRatio=True, anchor='c', mask='auto')
        except Exception:
            pass  # never crash the PDF over a missing logo

    _txt(c, cx(2), ry(1), cw(2,3,4,5), rh(1), cust, bold=True, size=13)
    _txt(c, cx(6), ry(1), cw(*range(6, last_idx+1)), rh(1),
         f"DATE ORDERED: {d_ord}", bold=True, size=11)
    if created_by:
        _txt(c, cx(last_idx), ry(1), cw(last_idx), rh(1),
             f"BY: {created_by.upper()}", bold=True, size=9, align="right")

    _txt(c, cx(1), ry(3), cw(1),       rh(3), "O/N:", size=9)
    _txt(c, cx(2), ry(3), cw(2,3,4,5), rh(3), ord_n,  bold=True, size=12)
    _txt(c, cx(6), ry(3), cw(6),       rh(3), "ATT:", size=9)
    _txt(c, cx(7), ry(3), cw(7,8,9),   rh(3), attn,   bold=True, size=11)
    _txt(c, cx(10), ry(3), cw(*range(10, last_idx+1)), rh(3),
         f"{page_num} OF {total_pages}", bold=True, size=11, align="center")


# ── VorF page ─────────────────────────────────────────────────────────────────

def _draw_vorf(c, header, item, page_num, total_pages, d_ord, d_due):
    col_x, col_w, row_y, row_h = _geom(_VORF_CHARS, _VORF_ROW_H)
    CI = {l:i for i,l in enumerate("ABCDEFGHIJKLMNOPQ")}
    cx  = lambda l: col_x[CI[l]]
    cw  = lambda *ls: sum(col_w[CI[l]] for l in ls)
    xr  = lambda l: col_x[CI[l]] + col_w[CI[l]]   # right edge of column
    ry  = lambda r: row_y[r]
    rh  = lambda r: row_h[r]
    yt  = lambda r: row_y[r] + row_h[r]             # top of row
    yb  = lambda r: row_y[r]                        # bottom of row

    qty     = item.get("Quantity", 0)
    short   = int(item.get("Short", 0))
    long_   = int(item.get("Long", 0))
    channel = int(item.get("Channel", 0))
    media   = item.get("Media Type", "")
    ftype   = (item.get("Filter Type") or "").lower()
    is_pleat = bool(item.get("Pleat Insert"))
    is_hdr   = bool(item.get("Header"))
    use_sv   = bool(item.get("Use Stock V-form"))
    # item_job / item_notes let compressor presets stamp each page with its
    # own job number and mounting-frame note rather than sharing a single
    # order-level value across all pages.
    job  = item.get("item_job") or (header.get("Job", "") or "")
    loc  = (header.get("Location","") or "").upper()
    cust = (header.get("Customer Name","") or "").upper()
    ord_n = header.get("Order Number","") or ""
    attn  = (header.get("Attention","") or "").upper()
    label = f"F{channel}" if ftype == "flat panel" else f"V{channel}"
    item_xtra  = (item.get("item_notes") or "")
    notes      = (item.get("Notes") or "")
    hdr_notes  = (header.get("Notes") or "")
    full_notes = " | ".join(p for p in [hdr_notes, item_xtra, notes] if p)

    # ── Rows 1-4: header text only ─────────────────────────────────────────
    _draw_header(c, col_x, col_w, row_y, row_h,
                 cust, ord_n, attn, d_ord, page_num, total_pages, 16,
                 created_by=(header.get("Created By") or ""))

    # ── Row 5: bottom line only, ALL column dividers ─────────────────────
    _h(c, cx('B'), yb(5), xr('Q'))   # bottom line
    # All vertical dividers (every column individually bordered)
    for col in "BCDEFGHIJKLMNOPQ":
        _v(c, cx(col), yb(5), yt(5))
    _v(c, xr('Q'), yb(5), yt(5))

    # ── Row 5 header text (centered in each cell/group) ───────────────────
    h5 = [("B","MEDIA"),    ("C","QTY"),              ("D",["FILTER","TYPE"]),
          ("E","SHORT"),    ("F","LONG"),
          # MARK 1-4 span G-J as one visual group (no internal dividers)
          ("G","MARK  1"),  ("H","MARK  2"),           ("I","MARK  3"), ("J","MARK  4"),
          ("K",["MARK IF","CAP"]),    ("L",["TOTAL","LENGTH"]), ("M",["CAP","SIZE"]),
          ("N",["WIRE","CUT"]),       ("O",["WIRE","QTY"]),
          ("P",["MEDIA","CUT"]),      ("Q",["MEDIA","QTY"])]
    for col, text in h5:
        _txt(c, cx(col), ry(5), cw(col), rh(5), text, size=7, align="center", valign="bottom")

    # ── Row 6: column dividers only (B-Q, no bottom line) ───────────────
    for col in "BCDEFGHIJKLMNOPQ":
        _v(c, cx(col), yb(6), yt(6))
    _v(c, xr('Q'), yb(6), yt(6))

    # ── Row 6 data text ───────────────────────────────────────────────────
    for col, val in [("B",media), ("C",qty), ("D",label),
                     ("E",short), ("F",long_)]:
        _txt(c, cx(col), ry(6), cw(col), rh(6), val, size=9, align="center", valign="top", offset=2)

    can_mark = not use_sv and not is_pleat
    if can_mark:
        marks = _markings(short, long_)
        for col, val in zip("GHIJ", marks["fwd"][:4]):
            _txt(c, cx(col), ry(6), cw(col), rh(6), val, size=9, align="center", valign="top", offset=2)
        for col, val in zip("KLM", marks["fwd"][4:7]):
            if val is not None:
                _txt(c, cx(col), ry(6), cw(col), rh(6), val, size=9, align="center", valign="top", offset=2)

    # Wire Cut/Qty & Media Cut/Qty — required for pleat inserts too,
    # so shown whenever NOT a stock item and NOT header-only.
    if not use_sv and not is_hdr:
        wm = _wire_media(short, long_, channel, label, int(qty))
        for col, val in [("N",wm["wc"]),("O",wm["wq"]),("P",wm["mc"]),("Q",wm["mq"])]:
            _txt(c, cx(col), ry(6), cw(col), rh(6), val, size=9, align="center", valign="top", offset=2)

    # ── Rows 8 & 10: EXACT borders (F|G and J|K dividers + K-M boxes) ────
    if can_mark:
        marks = _markings(short, long_)

        # Row 8: FLIPPED — dividers for B-F (media side) + mark cols G-M
        _txt(c, cx('E'), ry(8), cw('E','F'), rh(8), "FLIPPED", size=8)
        for col in "GHIJKLM":
            _v(c, cx(col), yb(8), yt(8))
        _v(c, xr('M'), yb(8), yt(8))
        for col, val in zip("GHIJ", marks["flp"][:4]):
            _txt(c, cx(col), ry(8), cw(col), rh(8), val, size=9, align="center")
        for col, val in zip("KLM", marks["flp"][4:7]):
            _txt(c, cx(col), ry(8), cw(col), rh(8), val, size=9, align="center")

        # Row 10: REVERSED — dividers, box for K
        _txt(c, cx('E'), ry(10), cw('E','F'), rh(10), "REVERSED", size=8)
        for col in "GHIJK":
            _v(c, cx(col), yb(10), yt(10))
        _v(c, xr('K'), yb(10), yt(10))
        for col, val in zip("GHIJ", marks["rev"][:4]):
            _txt(c, cx(col), ry(10), cw(col), rh(10), val, size=9, align="center")
        _txt(c, cx('K'), ry(10), cw('K'), rh(10), marks["rev"][4], size=9, align="center")
    else:
        _txt(c, cx('E'), ry(8),  cw('E','F'), rh(8),  "FLIPPED",  size=8)
        _txt(c, cx('E'), ry(10), cw('E','F'), rh(10), "REVERSED", size=8)

    # ── Production section: ONLY cell E has a box (medium weight) ─────────
    prod = {12:"MARKED CHANNEL", 14:"CUT CHANNEL", 16:"DRILLED CHANNEL",
            18:"ASSEMBLED",     20:"PACKED"}
    info = {12:f"JOB: {job}", 14:f"DUE: {d_due}",
            16:f"LOCATION: {loc}", 18:f"NOTES: {full_notes}"}

    for row, label_text in prod.items():
        _txt(c, cx('B'), ry(row), cw('B','C','D'), rh(row), label_text, bold=True, size=8)
        pad = rh(row) * 0.15
        _box(c, cx('E') + 3, ry(row) + pad, cw('E') - 6, rh(row) - pad * 2, lw=LW_MEDIUM)
        if row in info:
            _txt(c, cx('G'), ry(row),
                 cw('G','H','I','J','K','L','M','N','O','P','Q'),
                 rh(row), info[row], bold=True, size=9)

    # ── Row 22: BRACE REQ? ────────────────────────────────────────────────
    _txt(c, cx('B'), ry(22), cw('B','C','D'), rh(22), "BRACE REQ?", bold=True, size=8)
    _txt(c, cx('E'), ry(22), cw('E'),         rh(22), "Y/N", size=8, align="center")

    # ── Bottom table rows 24-26 (B-F) — exact borders ─────────────────────
    # Row 24: single cell B-F
    _box(c, cx('B'), ry(24), cw('B','C','D','E','F'), rh(24))
    _txt(c, cx('B'), ry(24), cw('B','C','D','E','F'), rh(24), "OFFICE USE", size=7, align="center")
    # Row 25: cell B-E  +  cell F
    _box(c, cx('B'), ry(25), cw('B','C','D','E'), rh(25))
    _txt(c, cx('B'), ry(25), cw('B','C','D','E'), rh(25), "MEASUREMENTS DOUBLE CHECKED", size=6)
    _box(c, cx('F'), ry(25), cw('F'), rh(25))
    # Row 26: single cell B-F
    _box(c, cx('B'), ry(26), cw('B','C','D','E','F'), rh(26))
    _txt(c, cx('B'), ry(26), cw('B','C','D','E','F'), rh(26), "INVOICED", size=7, align="center")


# ── FS page ───────────────────────────────────────────────────────────────────

def _draw_fs(c, header, item, page_num, total_pages, d_ord, d_due):
    col_x, col_w, row_y, row_h = _geom(_FS_CHARS, _FS_ROW_H)
    CI = {l:i for i,l in enumerate("ABCDEFGHIJKL")}
    cx  = lambda l: col_x[CI[l]]
    cw  = lambda *ls: sum(col_w[CI[l]] for l in ls)
    xr  = lambda l: col_x[CI[l]] + col_w[CI[l]]
    ry  = lambda r: row_y[r]
    rh  = lambda r: row_h[r]
    yt  = lambda r: row_y[r] + row_h[r]
    yb  = lambda r: row_y[r]

    qty   = item.get("Quantity", 0)
    short = int(item.get("Short", 0))
    long_ = int(item.get("Long", 0))
    media = item.get("Media Type", "")
    use_stk = bool(item.get("Use Stock Flyscreen"))
    job  = item.get("item_job") or (header.get("Job", "") or "")
    loc  = (header.get("Location","") or "").upper()
    cust = (header.get("Customer Name","") or "").upper()
    ord_n = header.get("Order Number","") or ""
    attn  = (header.get("Attention","") or "").upper()
    item_xtra  = (item.get("item_notes") or "")
    notes      = (item.get("Notes") or "")
    hdr_notes  = (header.get("Notes") or "")
    full_notes = " | ".join(p for p in [hdr_notes, item_xtra, notes] if p)

    # ── Rows 1-4: header text only ─────────────────────────────────────────
    _draw_header(c, col_x, col_w, row_y, row_h,
                 cust, ord_n, attn, d_ord, page_num, total_pages, 11,
                 created_by=(header.get("Created By") or ""))

    # ── Row 5: bottom line only + all column dividers (matches VorF) ─────
    _h(c, cx('B'), yb(5), xr('L'))   # bottom only — no top border
    for col in "BCDEFGHIJKL":
        _v(c, cx(col), yb(5), yt(5))
    _v(c, xr('L'), yb(5), yt(5))

    h5 = [("B","MEDIA"),("C","QTY"),("D",["FILTER","TYPE"]),
          ("E","SHORT"),("F","LONG"),
          ("G",["SHORT SIDE","CUT"]),("H",["QTY","REQ"]),
          ("I",["LONG","CUT"]),      ("J",["QTY","REQ"]),
          ("K",["MEDIA CUT","SIZE"]),("L",["QTY","REQ"])]
    for col, text in h5:
        _txt(c, cx(col), ry(5), cw(col), rh(5), text, size=7, align="center", valign="bottom")

    # ── Row 6: vertical dividers only, no bottom line (matches VorF) ─────
    for col in "BCDEFGHIJKL":
        _v(c, cx(col), yb(6), yt(6))
    _v(c, xr('L'), yb(6), yt(6))

    # Row 6 data text — top-aligned with 2pt offset (matches VorF)
    for col, val in [("B",media),("C",qty),("D","FS9"),("E",short),("F",long_)]:
        _txt(c, cx(col), ry(6), cw(col), rh(6), val, size=9, align="center", valign="top", offset=2)
    if not use_stk:
        iq = int(qty)
        cuts = [short-2, iq*2, long_, iq*2, f"{short+20}*{long_+20}", iq]
        for col, val in zip("GHIJKL", cuts):
            _txt(c, cx(col), ry(6), cw(col), rh(6), val, size=9, align="center", valign="top", offset=2)

    # ── Production section: padded col-E box (matches VorF style) ─────────
    # Rows 12, 14, 16, 18, 20 — same 5-row layout as VorF
    fs_prod = {12:"CUT ALUMINIUM", 14:"ASSEMBLED", 16:"LOADED", 18:"PACKED", 20:"CHECKED"}
    fs_info = {12:f"JOB: {job}", 14:f"DUE: {d_due}",
               16:f"LOCATION: {loc}", 18:f"NOTES: {full_notes}"}

    for row, label_text in fs_prod.items():
        _txt(c, cx('B'), ry(row), cw('B','C','D'), rh(row), label_text, bold=True, size=8)
        pad = rh(row) * 0.15
        _box(c, cx('E') + 3, ry(row) + pad, cw('E') - 6, rh(row) - pad * 2, lw=LW_MEDIUM)
        if row in fs_info:
            _txt(c, cx('G'), ry(row), cw('G','H','I','J','K','L'),
                 rh(row), fs_info[row], bold=True, size=9)

    # ── Row 22: BRACE REQ? (matches VorF row 22) ─────────────────────────
    _txt(c, cx('B'), ry(22), cw('B','C','D'), rh(22), "BRACE REQ?", bold=True, size=8)
    _txt(c, cx('E'), ry(22), cw('E'),         rh(22), "Y/N", size=8, align="center")

    # ── Bottom table rows 24-26 (B-F) — matches VorF ─────────────────────
    _box(c, cx('B'), ry(24), cw('B','C','D','E','F'), rh(24))
    _txt(c, cx('B'), ry(24), cw('B','C','D','E','F'), rh(24), "OFFICE USE", size=7, align="center")
    _box(c, cx('B'), ry(25), cw('B','C','D','E'), rh(25))
    _txt(c, cx('B'), ry(25), cw('B','C','D','E'), rh(25), "MEASUREMENTS DOUBLE CHECKED", size=6)
    _box(c, cx('F'), ry(25), cw('F'), rh(25))
    _box(c, cx('B'), ry(26), cw('B','C','D','E','F'), rh(26))
    _txt(c, cx('B'), ry(26), cw('B','C','D','E','F'), rh(26), "INVOICED", size=7, align="center")


# ── Main entry point ──────────────────────────────────────────────────────────

def generate_pdf(header_data, items, output_path, page_start=1, grand_total=None):
    d_ord, d_due = _fmt_dates(header_data.get("Date Ordered",""),
                              header_data.get("Date Due",""))
    total_pages  = grand_total if grand_total is not None else len(items)
    page_counter = page_start
    c = rl_canvas.Canvas(output_path, pagesize=landscape(A4))

    for i, item in enumerate(items):
        ftype = (item.get("Filter Type") or "").lower()
        if ftype == "stepped filter":
            _draw_fs(c, header_data, item, page_counter, total_pages, d_ord, d_due)
            c.showPage()
            inner = {**item,
                     "Short":       max(0, int(item.get("Short",   0)) - 25),
                     "Long":        max(0, int(item.get("Long",    0)) - 25),
                     "Channel":     max(0, int(item.get("Channel", 0)) - 10),
                     "Filter Type": "V-form"}
            _draw_vorf(c, header_data, inner, page_counter, total_pages, d_ord, d_due)
        elif ftype == "flyscreen":
            _draw_fs(c, header_data, item, page_counter, total_pages, d_ord, d_due)
        else:
            _draw_vorf(c, header_data, item, page_counter, total_pages, d_ord, d_due)
        page_counter += 1
        if i < len(items) - 1:
            c.showPage()

    c.save()
    return output_path
