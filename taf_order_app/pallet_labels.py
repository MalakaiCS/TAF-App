"""Pallet labels: one sheet per pallet, saying which pallet it is and what
is on it.

For an order going out on pallets rather than in wraps. Somebody picks the
order, says how many pallets, and how many of each line go on each; every
pallet gets an A4 landscape sheet with

    PALLET 1 of 3
    the filters on that pallet - size and type, and how many
    who it is for: customer, delivery address, order and job number

The delivery address comes from the customer's account, the same as the
delivery labels, so the two cannot disagree. Nothing here changes the order.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import calc_settings as _settings
from . import delivery_labels as _dl
from .numbers import positive_int


class PalletError(ValueError):
    def __init__(self, problems: Sequence[str]):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


def line_text(item: Dict[str, Any]) -> str:
    """What a line is, in a few words: '595 × 595 × 25 mm Flat Panel F5'."""
    kind = item.get("item_kind", "filter")
    if item.get("Filter Type") or kind == "filter":
        dims = [item.get(k) for k in ("Short", "Long", "Channel")]
        size = " × ".join(f"{float(d):g}" for d in dims
                          if d not in (None, "", 0)) if any(dims) else ""
        bits = [size + " mm" if size else "", str(item.get("Filter Type") or ""),
                str(item.get("Media Type") or "")]
        return " ".join(b for b in bits if b).strip() or "Filter"
    if kind == "bag" or item.get("product_type"):
        dims = [item.get(k) for k in ("width", "height", "depth")]
        size = " × ".join(f"{float(d):g}" for d in dims
                          if d not in (None, "", 0)) if any(dims) else ""
        bits = [size + " mm" if size else "", str(item.get("product_type") or ""),
                str(item.get("media") or "")]
        text = " ".join(b for b in bits if b).strip()
        return text or str(item.get("description") or "Item")
    parts = [str(item.get(k) or "").strip()
             for k in ("Part Number", "Description")]
    return " - ".join(p for p in parts if p) or \
        str(item.get("Product Type") or "Item")


def line_job(item: Dict[str, Any], header: Dict[str, Any]) -> str:
    """The job a line belongs to: its own job number (a preset or a line
    given its own job), else the order's. "" when there is none."""
    own = str(item.get("item_job") or "").strip()
    return own or str((header or {}).get("Job") or "").strip()


def ordered(item: Dict[str, Any]) -> int:
    return positive_int(item.get("Quantity", item.get("quantity"))) or 0


def spread(quantity: int, pallets: int) -> List[int]:
    """A line shared as evenly as it goes, the extra on the first pallets."""
    base, extra = divmod(max(0, int(quantity)), max(1, int(pallets)))
    return [base + (1 if i < extra else 0) for i in range(max(1, pallets))]


def check(items: Sequence[Dict[str, Any]], pallets: Any,
          grid: Sequence[Sequence[Any]]) -> Tuple[List[List[int]], List[str]]:
    """The quantities on each pallet, checked. grid[line][pallet].

    Returns (quantities, warnings). Raises PalletError for what cannot
    print: no pallets, a quantity that is not a whole number, more of a
    line on pallets than was ordered, an empty pallet. A line not all on
    pallets is a warning - part of an order can go on pallets."""
    n = positive_int(pallets)
    problems: List[str] = []
    if n is None:
        raise PalletError(["the number of pallets is a whole number of 1 or "
                           "more"])
    if len(grid) != len(items):
        problems.append("every line needs a row of pallet quantities")
    out: List[List[int]] = []
    warnings: List[str] = []
    for i, (item, row) in enumerate(zip(items, grid), start=1):
        row = list(row) + [0] * (n - len(row))
        if len(row) > n:
            problems.append(f"line {i} has quantities for {len(row)} pallets, "
                            f"not {n}")
            row = row[:n]
        qs = []
        for j, v in enumerate(row, start=1):
            if v in (None, ""):
                qs.append(0)
                continue
            q = 0 if str(v).strip() == "0" else positive_int(v)
            if q is None:
                problems.append(f"line {i}, pallet {j}: a whole number, "
                                "0 or more")
                q = 0
            qs.append(q)
        total, want = sum(qs), ordered(item)
        if total > want:
            problems.append(f"line {i}: {total} on pallets but {want} "
                            "ordered")
        elif total < want:
            warnings.append(f"line {i}: {want - total} of {want} not on a "
                            "pallet")
        out.append(qs)
    for j in range(n):
        if out and not any(row[j] for row in out):
            problems.append(f"pallet {j + 1} has nothing on it")
    if problems:
        raise PalletError(problems)
    return out, warnings


def build(order: Dict[str, Any], items: Sequence[Dict[str, Any]],
          customer: Optional[Dict[str, Any]], pallets: Any,
          grid: Sequence[Sequence[Any]]) -> Tuple[List[Dict[str, Any]],
                                                   List[str]]:
    """Every pallet's label, in order. Raises PalletError."""
    quantities, warnings = check(items, pallets, grid)
    header = dict(order.get("header") or {})
    c = customer or {}
    problems = []
    addr1 = str(c.get("delivery_address1") or "").strip()
    if not addr1:
        problems.append("the customer has no delivery address on their "
                        "account - add it first")
    if problems:
        raise PalletError(problems)
    n = len(quantities[0]) if quantities else positive_int(pallets)
    address = [addr1] + ([str(c["delivery_address2"]).strip()]
                         if str(c.get("delivery_address2") or "").strip()
                         else [])
    state = _dl.normalise_state(c.get("delivery_state")) or \
        str(c.get("delivery_state") or "")
    common = {
        "company": _settings.COMPANY["name"],
        "abn": _settings.COMPANY["abn"],
        "phone": _settings.COMPANY["phone"],
        "customer_name": str(c.get("name") or order.get("customer_name")
                             or header.get("Customer Name") or ""),
        "address_lines": address,
        "locality": f"{c.get('delivery_city') or ''}  {state}  "
                    f"{c.get('delivery_postcode') or ''}".strip(),
        "order_number": str(order.get("order_number")
                            or header.get("Order Number") or ""),
        "job_number": _dl.job_text(header.get("Job", order.get("job"))),
        "contact_name": str(header.get("Attention")
                            or c.get("contact_person") or ""),
        "contact_phone": str(c.get("phone") or ""),
    }
    labels = []
    for j in range(n):
        rows = [{"line": i + 1, "text": line_text(item),
                 "job": line_job(item, header),
                 "quantity": quantities[i][j], "ordered": ordered(item)}
                for i, item in enumerate(items) if quantities[i][j]]
        # The job at the top: the one every line on the pallet shares, or
        # "see lines" when they differ. Never the order number.
        jobs = {r["job"] for r in rows}
        top_job = (_dl.job_text(next(iter(jobs))) if len(jobs) == 1
                   else "See each line")
        labels.append(dict(common, job_number=top_job, pallet=j + 1, pallets=n,
                           pallet_text=f"{j + 1} of {n}", items=rows,
                           filters_on_pallet=sum(r["quantity"]
                                                 for r in rows)))
    return labels, warnings


def render_pdf(labels: Sequence[Dict[str, Any]], path: str) -> str:
    """One A4 landscape page per pallet (more if its list is long)."""
    from reportlab.lib.colors import HexColor, black
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfgen import canvas

    if not labels:
        raise PalletError(["there are no pallets to print"])
    W, H = landscape(A4)
    left, right = 15 * mm, W - 15 * mm
    top, bottom = H - 12 * mm, 12 * mm
    grey = HexColor("#C4C4C4")
    soft = HexColor("#555555")
    logo = _dl._logo_path()
    c = canvas.Canvas(path, pagesize=landscape(A4))
    c.setTitle("Pallet labels")
    c.setAuthor(_settings.COMPANY["name"])

    def box(x, y, w, h):
        c.setStrokeColor(grey)
        c.setLineWidth(0.8)
        c.rect(x, y, w, h, stroke=1, fill=0)

    def caption(x, y, text):
        c.setFillColor(black)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x, y, text)

    def fit(text, font, size, width, min_size=8):
        s = size
        while s > min_size and c.stringWidth(text, font, s) > width:
            s -= 0.5
        return s

    gap = 4 * mm
    for lab in labels:
        rows = list(lab["items"])
        page = 0
        while True:
            page += 1
            c.setFillColor(black)
            # Header: logo, title, phone.
            hh = 26 * mm
            y0 = top - hh
            box(left, y0, right - left, hh)
            if logo:
                lh = 18 * mm
                c.drawImage(logo, left + 3 * mm, top - 4 * mm - lh,
                            width=lh * 2.985, height=lh,
                            preserveAspectRatio=True, mask="auto")
            c.setFont("Helvetica-Bold", 26)
            c.drawRightString(right - 5 * mm, top - 13 * mm, "Pallet label")
            c.setFont("Helvetica", 10)
            c.drawRightString(right - 5 * mm, top - 21 * mm,
                              f"Phone {lab['phone']}   ·   ABN {lab['abn']}")

            # Who it is for, and which pallet.
            bh = 52 * mm
            by = y0 - gap - bh
            pw = 78 * mm
            box(left, by, right - left - pw - gap, bh)
            box(right - pw, by, pw, bh)
            caption(left + 4 * mm, by + bh - 7 * mm, "Deliver to")
            inner = right - left - pw - gap - 10 * mm
            ns = fit(lab["customer_name"], "Helvetica-Bold", 22, inner, 12)
            c.setFont("Helvetica-Bold", ns)
            c.drawString(left + 5 * mm, by + bh - 17 * mm,
                         lab["customer_name"])
            y = by + bh - 26 * mm
            c.setFont("Helvetica", 13)
            for line in (lab["address_lines"] + [lab["locality"]])[:3]:
                for part in simpleSplit(line, "Helvetica", 13, inner)[:1]:
                    c.drawString(left + 5 * mm, y, part)
                y -= 6 * mm
            c.setFont("Helvetica", 10)
            c.setFillColor(soft)
            c.drawString(left + 5 * mm, by + 4 * mm,
                         f"Order Number  {lab['order_number']}     "
                         f"Job Number  {lab['job_number']}")
            c.setFillColor(black)
            caption(right - pw + 4 * mm, by + bh - 7 * mm, "Pallet")
            ps = fit(lab["pallet_text"], "Helvetica-Bold", 54, pw - 8 * mm, 24)
            c.setFont("Helvetica-Bold", ps)
            c.drawCentredString(right - pw / 2, by + bh / 2 - ps * 0.3,
                                lab["pallet_text"])
            c.setFont("Helvetica", 10)
            c.setFillColor(soft)
            c.drawCentredString(right - pw / 2, by + 5 * mm,
                                f"{lab['filters_on_pallet']} on this pallet")
            c.setFillColor(black)

            # What is on it.
            ty = by - gap
            th = ty - bottom
            box(left, bottom, right - left, th)
            caption(left + 4 * mm, ty - 7 * mm,
                    "On this pallet" + (" (continued)" if page > 1 else ""))
            qx = left + 5 * mm
            tx = left + 30 * mm
            ox = right - 5 * mm
            # A job column when any line on this pallet has a job.
            jobs_shown = any(r.get("job") for r in lab["items"])
            jx = ox - 85 * mm
            c.setFont("Helvetica-Bold", 10)
            c.setFillColor(soft)
            c.drawString(qx, ty - 15 * mm, "QTY")
            c.drawString(tx, ty - 15 * mm, "FILTER")
            if jobs_shown:
                c.drawString(jx, ty - 15 * mm, "JOB")
            c.drawRightString(ox, ty - 15 * mm, "ORDERED")
            c.setFillColor(black)
            row_h = 9 * mm
            y = ty - 15 * mm - row_h
            fits = max(1, int((y - bottom - 2 * mm) // row_h) + 1)
            shown, rows = rows[:fits], rows[fits:]
            for r in shown:
                c.setFont("Helvetica-Bold", 18)
                c.drawString(qx, y, str(r["quantity"]))
                width = (jx - tx - 4 * mm) if jobs_shown else ox - tx - 25 * mm
                fs = fit(r["text"], "Helvetica", 15, width, 9)
                c.setFont("Helvetica", fs)
                c.drawString(tx, y, r["text"])
                if jobs_shown:
                    job = r.get("job") or "N/A"
                    js = fit(job, "Helvetica-Bold", 14, ox - jx - 22 * mm, 8)
                    c.setFont("Helvetica-Bold", js)
                    c.drawString(jx, y, job)
                c.setFont("Helvetica", 11)
                c.setFillColor(soft)
                c.drawRightString(ox, y, f"of {r['ordered']}")
                c.setFillColor(black)
                c.setStrokeColor(grey)
                c.line(left + 4 * mm, y - 3 * mm, right - 4 * mm, y - 3 * mm)
                y -= row_h
            c.showPage()
            if not rows:
                break
    c.save()
    return path
