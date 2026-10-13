"""What the worksheet prints under Notes: wrapping, then the calculator.

Read back off the real PDF, because "the block is drawn" and "the block is
drawn below Notes, in its own box, without touching what was typed in Notes"
are different claims and only the second one is what was asked for.
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import calc_settings as cs              # noqa: E402
from taf_order_app import delivery_labels as dl            # noqa: E402
from taf_order_app import order_packing as op              # noqa: E402
from taf_order_app import worksheet_blocks as wb           # noqa: E402

HEADER = {"Customer Name": "Complete Air Supply - Tweed Heads",
          "Order Number": "57920", "Date Ordered": "13/10/26",
          "Attention": "Michael", "Job": "", "Location": "Freight",
          "Notes": "Deliver before 10am"}


def _items():
    items = [
        {"Quantity": 20, "Short": 595, "Long": 595, "Channel": 90,
         "Filter Type": "V-form", "Media Type": "G4",
         "Notes": "Bag them in pairs"},
        {"Quantity": 9, "Short": 500, "Long": 600, "Channel": 25,
         "Filter Type": "Flat Panel", "Media Type": "WASH"},
        {"Quantity": 3, "Short": 150, "Long": 800, "Channel": 9,
         "Filter Type": "Flyscreen", "Media Type": "GREY"},
    ]
    items[0]["Packing"] = op.set_manual(
        items[0], [10, 10], groups=[{"name": "Area A", "quantity": 10},
                                    {"name": "Area B", "quantity": 10}],
        group_of_wrap=["Area A", "Area B"])
    items[1]["Packing"] = op.set_manual(items[1], [3, 3, 3])
    items[2]["Packing"] = op.set_manual(items[2], [3])
    return items


DRAWN: list = []


def _render(items):
    """Draw the worksheet for real, recording every piece of text with its
    page and position. Reading the text back out of the PDF would depend on
    which PDF reader a machine has; this does not."""
    import pdf_generator as g
    real = g.rl_canvas.Canvas

    class Recorder(real):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._page = 0

        def showPage(self):
            self._page += 1
            super().showPage()

        def _rec(self, x, y, text):
            DRAWN.append((self._page, float(x), float(y), str(text)))

        def drawString(self, x, y, text, *a, **k):
            self._rec(x, y, text)
            return super().drawString(x, y, text, *a, **k)

        def drawCentredString(self, x, y, text, *a, **k):
            self._rec(x, y, text)
            return super().drawCentredString(x, y, text, *a, **k)

        def drawRightString(self, x, y, text, *a, **k):
            self._rec(x, y, text)
            return super().drawRightString(x, y, text, *a, **k)

    DRAWN.clear()
    g.rl_canvas.Canvas = Recorder
    try:
        path = str(Path(tempfile.mkdtemp()) / "ws.pdf")
        g.generate_pdf(dict(HEADER), items, path)
    finally:
        g.rl_canvas.Canvas = real
    pages = {}
    for page, _x, _y, text in DRAWN:
        pages.setdefault(page, []).append(text)
    return [" ".join(pages[k]) for k in sorted(pages)]


def _where(page: int, starts: str):
    """(x, y) of the first text on a page that starts with `starts`."""
    for p, x, y, text in DRAWN:
        if p == page and text.startswith(starts):
            return x, y
    raise AssertionError(f"{starts!r} is not on page {page + 1}")


def _flat(t):
    return re.sub(r"\s+", " ", t)


def test_the_blocks_come_after_notes_in_their_own_order():
    pages = _render(_items())
    for page in (0, 1):
        nx, ny = _where(page, "NOTES:")
        wx, wy = _where(page, "WRAPPING INSTRUCTIONS")
        cx, cy = _where(page, "FILTER CALCULATOR")
        # Below Notes (PDF y grows upwards), in the Notes column, in order.
        assert ny > wy > cy, (ny, wy, cy)
        assert abs(wx - nx) < 5 and abs(cx - nx) < 5, (nx, wx, cx)
    # Nothing of the blocks reaches down into the barcode at the foot.
    import pdf_generator as g
    lowest = min(y for p, x, y, t in DRAWN
                 if p == 0 and x > 250 and t != "57920")
    assert lowest > g.MARGIN + 40, lowest     # the barcode sits below this
    assert pages


def test_notes_keep_exactly_what_was_typed():
    pages = _render(_items())
    first = _flat(pages[0])
    notes_line = first[first.index("NOTES:"):first.index(
        "WRAPPING INSTRUCTIONS")]
    assert "Deliver before 10am | Bag them in pairs" in notes_line
    for leaked in ("Wrap", "Bracing", "kg", "WIRE"):
        assert leaked not in notes_line, (leaked, notes_line)


def test_the_wording_is_the_saved_plan():
    pages = _render(_items())
    first, second = _flat(pages[0]), _flat(pages[1])
    assert "Area A: 10 filters (Wrap 10 Filters x 1)" in first
    assert "Area B: 10 filters (Wrap 10 Filters x 1)" in first
    assert "(Wrap 3 Filters x 3)" in second
    assert "Set by the office" in second


def test_flat_and_pleated_pages_have_the_calculator_and_flyscreens_do_not():
    pages = _render(_items())
    assert "FILTER CALCULATOR" in _flat(pages[0])      # V-form
    assert "FILTER CALCULATOR" in _flat(pages[1])      # Flat Panel
    assert "FILTER CALCULATOR" not in _flat(pages[2])  # Flyscreen
    assert "WRAPPING INSTRUCTIONS" in _flat(pages[2])


def test_the_calculator_uses_the_shared_profiles():
    pages = _render(_items())
    first, second = _flat(pages[0]), _flat(pages[1])
    assert "2 x 585 x 1062 mm (TAF-WS-V85-100 v1)" in first
    assert "Media G4 (0.300 kg/m2): 1 x 645 x 1102 mm" in first
    # A flat panel's wire has no rule set: said, not guessed.
    assert "Wire wire not chosen" in second or "no verified" in second
    assert "Media WASHABLE (0.240 kg/m2): 1 x 500 x 600 mm" in second
    # Incomplete is said as incomplete, not printed as a filter weight.
    assert "not the filter weight" in first
    assert "Complete weight" not in first


def test_brace_req_is_answered():
    items = _items()
    items[1].update(Short=700, Long=1301)
    items[1]["Packing"] = op.set_manual(items[1], [3, 3, 3])
    pages = _render(items)
    assert "YES x2" in _flat(pages[1])
    assert "Brace Required - 2 braces, Cross Format" in _flat(pages[1])
    assert "use brace in filter" in _flat(pages[2])


def test_sheet_codes_match_the_labels():
    s = cs.defaults()
    items = _items()
    ctx = wb.order_context(items, s)
    sheet_codes = [w["code"] for c in ctx for w in c["wraps"]]
    order_row = {"order_number": "57920", "header": {}, "items": items}
    cust = {"name": "X", "delivery_address1": "1 St", "delivery_city": "Y",
            "delivery_state": "QLD", "delivery_postcode": "4000"}
    labels = dl.build_for_order(order_row, cust, s, "Base")
    assert sheet_codes == [l["wrap_page"] for l in labels] == \
        ["1A/3", "1B/3", "2A/3", "2B/3", "2C/3", "3/3"]
    assert sum(l["wrap_quantity"] for l in labels) == 32


def test_a_mixed_order_prints_codes_numbered_across_the_whole_order():
    """The filter sheet is drawn from the filter lines alone; the codes
    still have to be the whole order's, as the labels number them."""
    s = cs.defaults()
    items = _items()
    bag = {"item_kind": "bag", "product_type": "3-Peak", "quantity": 2,
           "width": 592, "height": 592, "depth": 600}
    bag["Packing"] = op.set_manual(bag, [2])
    stamped = op.stamp_codes(items + [bag], s)
    filter_only = [i for i in stamped if i.get("item_kind") != "bag"]
    ctx = wb.order_context(filter_only, s)
    assert ctx[0]["wraps"][0]["code"] == "1A/4"
    assert op.strip_codes(stamped)[0].get("_wrap_codes") is None


def test_an_unplanned_line_says_so():
    items = _items()
    items[1].pop("Packing")
    items[1]["Quantity"] = 12
    pages = _render(items)
    assert "SET BEFORE PACKING" in _flat(pages[1])
