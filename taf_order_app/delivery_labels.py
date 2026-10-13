"""Delivery labels: one A4 landscape sheet for every wrapped bundle.

The label data contract
-----------------------
validate() checks an order as a label printer needs it, and refuses what a
label must not carry. The fields:

    order_number     the order's reference - shown once, as Order Number.
                     (The old "Purchase Order Number" was the same reference
                     under a second name; it is gone.)
    job_number       the attached job's number. Missing, null or blank
                     prints N/A. The order number is never used in its place.
    customer_name, address_line_1, address_line_2 (optional), suburb,
    state, postcode
    contact_name, contact_phone   optional; blank when not known
    items[]          one per order line, in order:
        width_mm, height_mm, depth_mm   positive numbers
        quantity                        a whole number of 1 or more
        product_type                    optional
        wrap_quantities  OR  max_per_wrap   - never both; neither means
                                            "plan it automatically"
        wrap_weights_kg      measured, wrapping included; one per wrap or null
        packaging_weights_kg confirmed wrapping per wrap, or null
        complete_filter_weight_kg_per_filter   from the calculator, if known
        wrap_ids, wrap_groups   per wrap, carried from a saved plan

References, phone numbers and postcodes must be text, so a leading zero in
"0800 ..." or "0870" survives. Fax, a separate purchase order number, a
dispatch date and delivery instructions are not part of a label and are
refused if sent.

From address
------------
The "From" line is {Base Address}, filled from the company's base_address
setting. It is read once per print request and used on every label in it,
so a move means changing one setting - every label generated afterwards,
for any order old or new, shows the new address.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import calc_settings as _settings
from . import order_packing as _op
from . import packing as _pk
from .numbers import finite, non_negative, positive, positive_int, trim_zeros

STATES = ("ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA")
STATE_NAMES = {
    "AUSTRALIANCAPITALTERRITORY": "ACT", "NEWSOUTHWALES": "NSW",
    "NORTHERNTERRITORY": "NT", "QUEENSLAND": "QLD", "SOUTHAUSTRALIA": "SA",
    "TASMANIA": "TAS", "VICTORIA": "VIC", "WESTERNAUSTRALIA": "WA",
}

TOP_FIELDS = {
    "order_number": (False, 24), "job_number": (False, 28),
    "customer_name": (True, 90), "address_line_1": (True, 100),
    "address_line_2": (False, 100), "suburb": (True, 45),
    "state": (True, None), "postcode": (True, None),
    "contact_name": (False, 55), "contact_phone": (False, 30),
    "items": (True, None),
}
ITEM_FIELDS = {
    "width_mm", "height_mm", "depth_mm", "quantity", "product_type",
    "wrap_quantities", "max_per_wrap", "wrap_weights_kg",
    "packaging_weights_kg", "complete_filter_weight_kg_per_filter",
    "wrap_ids", "wrap_groups", "profile_refs", "packing_status",
}
# Kept off labels on purpose. Named so the refusal can say why.
REMOVED_FIELDS = {"fax", "purchase_order_number", "po_number",
                  "dispatch_date", "delivery_instructions"}

BLANK_WEIGHT = "____"


class LabelError(ValueError):
    """An order that cannot be printed as labels, with every reason why."""

    def __init__(self, problems: Sequence[str]):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


# ── The contract ────────────────────────────────────────────────────────────

def job_text(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return text or "N/A"


def normalise_state(value: Any) -> str:
    key = re.sub(r"[^A-Z]", "", str(value or "").upper())
    if key in STATES:
        return key
    return STATE_NAMES.get(key, "")


def validate(order: Dict[str, Any]) -> Dict[str, Any]:
    """A clean copy of a label order, or LabelError listing every problem."""
    problems: List[str] = []
    if not isinstance(order, dict):
        raise LabelError(["the order has to be an object"])
    for key in order:
        if key in REMOVED_FIELDS:
            problems.append(f"{key} is not printed on delivery labels")
        elif key not in TOP_FIELDS:
            problems.append(f"{key} is not a label field")
    clean: Dict[str, Any] = {}
    for key, (required, limit) in TOP_FIELDS.items():
        if key == "items":
            continue
        value = order.get(key)
        if key == "job_number" and value is None:
            clean[key] = None
            continue
        if value is None:
            value = ""
        if not isinstance(value, str):
            problems.append(f"{key} has to be text (so leading zeros "
                            "survive)")
            continue
        value = value.strip()
        if required and not value:
            problems.append(f"{key} is required")
        if limit and len(value) > limit:
            problems.append(f"{key} is longer than {limit} characters")
        clean[key] = value
    if clean.get("state") is not None and clean.get("state"):
        st = normalise_state(clean["state"])
        if not st:
            problems.append(f"state {clean['state']!r} is not an Australian "
                            "state or territory")
        clean["state"] = st
    if clean.get("postcode") and not re.fullmatch(r"[0-9]{4}",
                                                  clean["postcode"]):
        problems.append("postcode has to be four digits")

    items = order.get("items")
    if not isinstance(items, list) or not items:
        problems.append("there has to be at least one item")
        items = []
    clean_items = []
    for i, it in enumerate(items, start=1):
        clean_items.append(_validate_item(it, i, problems))
    clean["items"] = clean_items
    if problems:
        raise LabelError(problems)
    return clean


def _validate_item(it: Any, i: int, problems: List[str]) -> Dict[str, Any]:
    where = f"line {i}"
    if not isinstance(it, dict):
        problems.append(f"{where} has to be an object")
        return {}
    for key in it:
        if key in REMOVED_FIELDS:
            problems.append(f"{where}: {key} is not printed on labels")
        elif key not in ITEM_FIELDS:
            problems.append(f"{where}: {key} is not a label field")
    out = dict(it)
    for key in ("width_mm", "height_mm", "depth_mm"):
        if key == "depth_mm" and it.get(key) is None and \
                str(it.get("product_type") or "") == "Mounting Frame":
            out[key] = None              # a frame has no filter depth
            continue
        if isinstance(it.get(key), bool) or positive(it.get(key)) is None:
            problems.append(f"{where}: {key} has to be a number above zero")
        else:
            out[key] = positive(it[key])
    qty = it.get("quantity")
    if isinstance(qty, str) or positive_int(qty) is None:
        problems.append(f"{where}: quantity has to be a whole number of 1 "
                        "or more")
        return out
    out["quantity"] = int(qty)
    try:
        resolved = _pk.resolve_quantities(qty, it.get("wrap_quantities"),
                                          it.get("max_per_wrap"))
    except _pk.PackingError as exc:
        problems.append(f"{where}: {exc}")
        resolved = None
    out["_resolved"] = resolved
    for key, check in (("wrap_weights_kg", positive),
                       ("packaging_weights_kg", non_negative)):
        arr = it.get(key)
        if arr is None:
            continue
        if not isinstance(arr, list):
            problems.append(f"{where}: {key} has to be a list")
            continue
        for j, v in enumerate(arr, start=1):
            if v is not None and (isinstance(v, (bool, str))
                                  or check(v) is None):
                problems.append(f"{where}: {key} entry {j} has to be "
                                + ("a number above zero" if check is positive
                                   else "zero or more"))
        if resolved is not None and len(arr) != len(resolved):
            problems.append(f"{where}: {key} has {len(arr)} entries for "
                            f"{len(resolved)} wraps")
    unit = it.get("complete_filter_weight_kg_per_filter")
    if unit is not None and (isinstance(unit, (bool, str))
                             or non_negative(unit) is None):
        problems.append(f"{where}: complete_filter_weight_kg_per_filter has "
                        "to be zero or more")
    return out


# ── Labels from a contract ──────────────────────────────────────────────────

def size_text(w: Optional[float], h: Optional[float],
              d: Optional[float]) -> str:
    parts = [w, h] + ([d] if d else [])
    return " × ".join(f"{p:g}" for p in parts) + " mm"


def build(order: Dict[str, Any], base_address: str,
          settings: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Every label for one order, in order. Raises LabelError.

    base_address is passed in, read once by whoever is printing, so every
    label in this request carries the same From line.
    """
    clean = validate(order)
    s = settings if settings is not None else _settings.defaults()
    packaging = s.get("packaging")
    policy = s.get("shipping_rounding") or "none"
    max_kg = float(s.get("max_bundle_kg") or _pk.MAX_BUNDLE_KG)
    problems: List[str] = []
    per_line: List[List[Dict[str, Any]]] = []
    for i, it in enumerate(clean["items"], start=1):
        unit = finite(it.get("complete_filter_weight_kg_per_filter"))
        quantities = it.get("_resolved")
        if quantities is None:
            hp = _pk.handling_limit(it["width_mm"], it["height_mm"],
                                    it.get("depth_mm"), "",
                                    s.get("handling_profiles"))
            prop = _pk.propose(it["quantity"], unit, packaging,
                               hp.get("max_per_wrap") if hp else None,
                               None, None, max_kg)
            if not prop["wraps"]:
                problems.append(f"line {i}: " + "; ".join(prop["issues"]))
                per_line.append([])
                continue
            quantities = [w["quantity"] for w in prop["wraps"]]
        weights = it.get("wrap_weights_kg") or [None] * len(quantities)
        packs = it.get("packaging_weights_kg") or [None] * len(quantities)
        ids = it.get("wrap_ids") or [None] * len(quantities)
        groups = it.get("wrap_groups") or [None] * len(quantities)
        wraps = []
        for j, q in enumerate(quantities):
            wrap = {"quantity": q, "measured_weight_kg": weights[j]}
            if packs[j] is not None:
                wrap.update(packaging_weight_kg=packs[j],
                            packaging_confirmed=True)
            wraps.append({"quantity": q, "id": ids[j], "group": groups[j],
                          "weight": _op.resolve_wrap_weight(
                              wrap, unit, packaging, policy)})
        per_line.append(wraps)
    if problems:
        raise LabelError(problems)

    codes = _pk.wrap_codes([len(w) for w in per_line])
    address_lines = [clean["address_line_1"]]
    if clean.get("address_line_2"):
        address_lines.append(clean["address_line_2"])
    labels = []
    for i, (it, wraps, line_codes) in enumerate(
            zip(clean["items"], per_line, codes), start=1):
        for wrap, code in zip(wraps, line_codes):
            labels.append({
                "company": _settings.COMPANY["name"],
                "abn": _settings.COMPANY["abn"],
                "phone": _settings.COMPANY["phone"],
                "from_address": base_address,
                "customer_name": clean["customer_name"],
                "address_lines": address_lines,
                "locality": f"{clean['suburb']}  {clean['state']}  "
                            f"{clean['postcode']}",
                "filter_size": size_text(it["width_mm"], it["height_mm"],
                                         it.get("depth_mm")),
                "wrap_quantity": wrap["quantity"],
                "line_quantity": it["quantity"],
                "weight_kg": wrap["weight"]["display"],
                "weight_source": wrap["weight"]["source"],
                "weight_raw_kg": wrap["weight"]["raw_kg"],
                "weight_missing": wrap["weight"]["missing"],
                "wrap_page": code,
                "contact_name": clean.get("contact_name") or "",
                "contact_phone": clean.get("contact_phone") or "",
                "order_number": clean.get("order_number") or "",
                "job_number": job_text(clean.get("job_number")),
                "group": wrap.get("group") or "",
                "wrap_id": wrap.get("id"),
                "line": i,
            })
    return labels


# ── Labels from a saved order ───────────────────────────────────────────────

def order_contract(order: Dict[str, Any], customer: Optional[Dict[str, Any]],
                   settings: Dict[str, Any]) -> Dict[str, Any]:
    """The label contract for an order as saved, using its saved plans.

    Every line must already have a packing plan (order_packing does that on
    save). Measured weights come from the plan's wraps; the calculated unit
    weight from the calculator with the current settings.
    """
    header = dict(order.get("header") or {})
    items = list(order.get("items") or [])
    c = customer or {}
    contract: Dict[str, Any] = {
        "order_number": str(order.get("order_number")
                            or header.get("Order Number") or ""),
        "job_number": header.get("Job", order.get("job")),
        "customer_name": str(c.get("name") or order.get("customer_name")
                             or header.get("Customer Name") or ""),
        "address_line_1": str(c.get("delivery_address1") or ""),
        "address_line_2": str(c.get("delivery_address2") or ""),
        "suburb": str(c.get("delivery_city") or ""),
        "state": normalise_state(c.get("delivery_state")) or
        str(c.get("delivery_state") or ""),
        "postcode": str(c.get("delivery_postcode") or ""),
        "contact_name": str(header.get("Attention") or
                            c.get("contact_person") or ""),
        "contact_phone": str(c.get("phone") or ""),
        "items": [],
    }
    for item in items:
        ev = _op.evaluate_line(item, settings)
        plan = ev["plan"] or {}
        wraps = plan.get("wraps") or []
        w, h, d = _op.line_dims(item)
        entry: Dict[str, Any] = {
            "width_mm": finite(w), "height_mm": finite(h),
            "depth_mm": finite(d) if d not in (None, "", 0) else None,
            "quantity": positive_int(item.get("Quantity",
                                              item.get("quantity"))),
            "product_type": str(item.get("Filter Type")
                                or item.get("product_type") or ""),
        }
        if wraps:
            entry["wrap_quantities"] = [x["quantity"] for x in wraps]
            entry["wrap_weights_kg"] = [x.get("measured_weight_kg")
                                        for x in wraps]
            entry["wrap_ids"] = [x.get("id") for x in wraps]
            entry["wrap_groups"] = [x.get("group") for x in wraps]
            entry["packaging_weights_kg"] = [
                x.get("packaging_weight_kg") if x.get("packaging_confirmed")
                else None for x in wraps]
        if ev["unit_kg"] is not None:
            entry["complete_filter_weight_kg_per_filter"] = ev["unit_kg"]
        contract["items"].append(entry)
    return contract


def build_for_order(order: Dict[str, Any], customer: Optional[Dict[str, Any]],
                    settings: Dict[str, Any], base_address: str,
                    only_wrap_ids: Optional[Sequence[str]] = None
                    ) -> List[Dict[str, Any]]:
    """Labels for a saved order; optionally just some wraps, for a reprint.

    The whole order is numbered first and the chosen wraps picked out after,
    so a reprint carries the code the wrap was first printed with.
    """
    labels = build(order_contract(order, customer, settings), base_address,
                   settings)
    if only_wrap_ids:
        wanted = set(only_wrap_ids)
        labels = [l for l in labels if l.get("wrap_id") in wanted]
    return labels


# ── Drawing them ────────────────────────────────────────────────────────────

def _logo_path() -> Optional[str]:
    import sys
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    p = base / "TAF_logo_horizontal.png"
    return str(p) if p.exists() else None


def render_pdf(labels: Sequence[Dict[str, Any]], path: str) -> str:
    """Write the labels to one PDF, one A4 landscape page each.

    Preview, print and export all use this file, so they cannot differ.
    """
    from reportlab.lib.colors import HexColor, black
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfgen import canvas

    if not labels:
        raise LabelError(["there are no labels to print"])
    W, H = landscape(A4)
    left, right = 15 * mm, W - 15 * mm
    top, bottom = H - 12 * mm, 12 * mm
    grey = HexColor("#C4C4C4")
    soft = HexColor("#555555")
    logo = _logo_path()
    c = canvas.Canvas(path, pagesize=landscape(A4))
    c.setTitle("Delivery labels")
    c.setAuthor(_settings.COMPANY["name"])

    def box(x, y, w, h):
        c.setStrokeColor(grey)
        c.setLineWidth(0.8)
        c.rect(x, y, w, h, stroke=1, fill=0)

    def caption(x, y, text):
        c.setFillColor(black)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x, y, text)

    def fit(text, font, size, width, min_size=8, max_lines=2):
        """The largest size up to `size` at which `text` wraps into
        max_lines lines of `width`. Never clips: at the smallest size it
        takes as many lines as it needs."""
        s = size
        while s > min_size:
            lines = simpleSplit(text, font, s, width)
            if len(lines) <= max_lines:
                return s, lines
            s -= 0.5
        return min_size, simpleSplit(text, font, min_size, width)

    def lines_at(x, y, lines, font, size, lead=1.15):
        c.setFont(font, size)
        for k, line in enumerate(lines):
            c.drawString(x, y - k * size * lead, line)
        return y - len(lines) * size * lead

    gap = 4 * mm
    for lab in labels:
        c.setFillColor(black)
        # Header: logo and From on the left, title and contact on the right.
        hh = 36 * mm
        y0 = top - hh
        box(left, y0, right - left, hh)
        split_x = left + (right - left) * 0.62
        c.setStrokeColor(grey)
        c.line(split_x, y0, split_x, top)
        if logo:
            lh = 22 * mm
            c.drawImage(logo, left + 3 * mm, top - 3 * mm - lh,
                        width=lh * 2.985, height=lh,
                        preserveAspectRatio=True, mask="auto")
        from_w = split_x - left - 8 * mm - c.stringWidth("FROM  ",
                                                          "Helvetica-Bold", 9)
        fsize, flines = fit(lab["from_address"], "Helvetica", 10, from_w,
                            min_size=7, max_lines=2)
        fy = y0 + 4 * mm + (len(flines) - 1) * fsize * 1.15
        c.setFont("Helvetica-Bold", 9)
        c.drawString(left + 4 * mm, fy, "FROM")
        lines_at(left + 4 * mm + c.stringWidth("FROM  ", "Helvetica-Bold", 9),
                 fy, flines, "Helvetica", fsize)
        c.setFont("Helvetica-Bold", 26)
        c.drawRightString(right - 5 * mm, top - 13 * mm, "Delivery label")
        c.setFont("Helvetica", 11)
        phone_w = c.stringWidth(lab["phone"], "Helvetica-Bold", 12)
        c.drawRightString(right - 5 * mm - phone_w - 2 * mm, top - 22 * mm,
                          "Phone")
        c.setFont("Helvetica-Bold", 12)
        c.drawRightString(right - 5 * mm, top - 22 * mm, lab["phone"])
        c.setFont("Helvetica", 10)
        c.drawRightString(right - 5 * mm, top - 29 * mm, f"ABN {lab['abn']}")

        # Deliver to: name, address, locality. Shrinks to fit, never clips.
        dh = 46 * mm
        dy = y0 - gap - dh
        box(left, dy, right - left, dh)
        inner = right - left - 10 * mm
        caption(left + 5 * mm, dy + dh - 7 * mm, "Deliver to")
        y = dy + dh - 17 * mm
        ns, nl = fit(lab["customer_name"], "Helvetica-Bold", 26, inner,
                     min_size=12, max_lines=1)
        if len(nl) > 1:
            ns, nl = fit(lab["customer_name"], "Helvetica-Bold", 20, inner,
                         min_size=12, max_lines=2)
        y = lines_at(left + 5 * mm, y, nl, "Helvetica-Bold", ns)
        addr = ", ".join(lab["address_lines"])
        as_, al = fit(addr, "Helvetica", 17, inner, min_size=9, max_lines=2)
        y = lines_at(left + 5 * mm, y - 1 * mm, al, "Helvetica", as_)
        ls, ll = fit(lab["locality"], "Helvetica-Bold", 18, inner,
                     min_size=10, max_lines=1)
        lines_at(left + 5 * mm, y - 1 * mm, ll, "Helvetica-Bold", ls)

        # The four that matter at a glance.
        bh = 50 * mm
        by = dy - gap - bh
        widths = [0.40, 0.17, 0.22, 0.21]
        total = right - left - 3 * gap
        x = left
        cells = [("Filter size", lab["filter_size"], "Width × Height × Depth"
                  if lab["filter_size"].count("×") == 2 else "Width × Height"),
                 ("Qty in this wrap", str(lab["wrap_quantity"]),
                  f"Ordered {lab['line_quantity']}"),
                 ("Wrap weight", (lab["weight_kg"] or BLANK_WEIGHT) + " kg",
                  {"measured": "Weighed", "calculated": "Calculated"}
                  .get(lab["weight_source"], "Weigh and write in")),
                 ("Wrap page", lab["wrap_page"],
                  f"Area: {lab['group']}" if lab.get("group") else "")]
        big = {"Filter size": 30, "Qty in this wrap": 54, "Wrap weight": 30,
               "Wrap page": 44}
        for (title, value, sub), frac in zip(cells, widths):
            cw = total * frac
            box(x, by, cw, bh)
            caption(x + 4 * mm, by + bh - 7 * mm, title)
            # One line if it will go at a readable size; two if not.
            size, vl = fit(value, "Helvetica-Bold", big[title],
                           cw - 8 * mm, min_size=20, max_lines=1)
            if len(vl) > 1:
                size, vl = fit(value, "Helvetica-Bold", big[title],
                               cw - 8 * mm, min_size=12, max_lines=2)
            vy = by + bh / 2 - size * 0.3 + (len(vl) - 1) * size * 0.55
            lines_at(x + 4 * mm, vy, vl, "Helvetica-Bold", size, lead=1.1)
            if sub:
                c.setFillColor(soft)
                ss, sl = fit(sub, "Helvetica", 11, cw - 8 * mm, min_size=7,
                             max_lines=1)
                lines_at(x + 4 * mm, by + 5 * mm, sl[:1], "Helvetica", ss)
                c.setFillColor(black)
            x += cw + gap

        # Contact, then references.
        rh = 19 * mm

        def row(ry, pairs):
            n = len(pairs)
            rw = (right - left - (n - 1) * gap) / n
            rx = left
            for title, value in pairs:
                box(rx, ry, rw, rh)
                caption(rx + 4 * mm, ry + rh - 7 * mm, title)
                vs, vl = fit(value or "", "Helvetica-Bold", 14, rw - 8 * mm,
                             min_size=8, max_lines=1)
                lines_at(rx + 4 * mm, ry + 5 * mm, vl[:1] if len(vl) == 1
                         else [" ".join(vl)], "Helvetica-Bold", vs)
                rx += rw + gap

        ry = by - gap - rh
        row(ry, [("Delivery contact", lab["contact_name"]),
                 ("Contact phone", lab["contact_phone"])])
        ry -= gap + rh
        row(ry, [("Order Number", lab["order_number"]),
                 ("Job Number", lab["job_number"])])
        c.showPage()
    c.save()
    return path
