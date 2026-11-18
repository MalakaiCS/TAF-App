"""The screen turned to face the customer, and the delivery charge on it.

Somebody comes in and asks what a few filters will cost. Until now they
watched the back of a monitor and heard one number at the end.

Two things had to be right for that to be worth doing.

What is on it. The quote screen knows what every line COST as well as what
it sells for — it prints the margin along the bottom for the people who set
prices — and that is the one figure in the building that must never be
readable from the customer's side of the counter. Most of what follows is
about that, because it is the failure that cannot be taken back: a customer
who has seen the margin has seen it.

And the delivery. It used to be worked out in somebody's head and added at
invoicing, which is how a customer is told one number at the counter and
billed another.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import counter_display as _cd    # noqa: E402
from taf_order_app import pricing as _pricing       # noqa: E402

GUI = (ROOT / "modern_order_gui.py").read_text(encoding="utf-8")


def _code(text: str) -> str:
    """The source with its prose taken out.

    A test looking for the word "margin" in the window's source found it in
    the comment explaining why no margin goes near the window. Checking that
    something is absent only means anything if what is being read is the
    code and not the explanation of the code.
    """
    out, in_doc = [], False
    for line in text.split("\n"):
        bare = line.strip()
        if bare.startswith(('"""', "'''")):
            # A one-line docstring opens and closes on the same line.
            if not (len(bare) > 5 and bare.endswith(('"""', "'''"))):
                in_doc = not in_doc
            continue
        if in_doc:
            continue
        if bare.startswith("#"):
            continue
        out.append(line.split("  # ")[0])
    return "\n".join(out)

# A quote as the app builds it — with the cost fields the margin code adds,
# because that is the shape this has to be safe against.
LINES = [
    {"part_number": "PPF50-1.8-G4", "description": "V-form 595x495x50 G4",
     "quantity": 8, "unit_price": 48.5, "line_total": 388.0,
     "source": "price list", "unit_cost": 19.4, "margin": 232.8},
    {"part_number": "BAG-592-6P", "description": "Bag filter 592 6 pocket",
     "quantity": 4, "unit_price": 47.25, "line_total": 189.0,
     "source": "price list", "unit_cost": 22.0, "margin": 101.0},
]
UNPRICED = dict(LINES[0], part_number="", description="Special frame",
                unit_price=0, line_total=0, source="")


# ── What must never be on it ─────────────────────────────────────────────────

def test_no_cost_reaches_the_rows():
    """Not "is not displayed" — not present in the data at all. A row that
    carries a cost is one careless label away from showing it."""
    for row in _cd.display_lines(LINES):
        assert "unit_cost" not in row and "margin" not in row, row
        text = " ".join(str(v) for v in row.values())
        for secret in ("19.4", "22.0", "232.8", "101.0"):
            assert secret not in text, f"{secret} reached the customer: {row}"


def test_a_row_carries_only_what_a_customer_reads():
    allowed = {"description", "part", "quantity", "unit_price", "line_total",
               "priced"}
    for row in _cd.display_lines(LINES):
        assert set(row) == allowed, set(row) - allowed


def test_the_totals_are_prices_only():
    rows = _cd.display_totals(LINES, shipping=35.0)
    text = " ".join(f"{a} {b}" for a, b, _ in rows).lower()
    for word in ("cost", "margin", "markup", "profit"):
        assert word not in text, f"the word {word} is on the customer's screen"


def test_the_display_never_asks_for_the_cost_data():
    """The quote tab loads costs to work out the margin. If this module ever
    learns how to do that, the separation stops being structural and becomes
    somebody remembering."""
    src = (ROOT / "taf_order_app/counter_display.py").read_text(encoding="utf-8")
    body = _code(src)
    for forbidden in ("_cost_data", "with_margin", "margin_summary",
                      "margin_label", "unit_cost"):
        assert forbidden not in body, f"{forbidden} is reachable from the display"


def test_the_window_draws_from_the_display_module_and_nothing_else():
    """If the window ever reads a quote line's fields directly, the rule
    above stops being enforced by anything."""
    cls = _code(GUI.split("class CounterDisplay")[1].split("\nclass ")[0])
    assert "_counter.display_lines" in cls
    assert "_counter.display_totals" in cls
    for forbidden in ("unit_cost", "margin", "_cost_data"):
        assert forbidden not in cls, f"{forbidden} appears in the window itself"


# ── What is on it ────────────────────────────────────────────────────────────

def test_every_line_shows_its_price_and_its_total():
    rows = _cd.display_lines(LINES)
    assert rows[0]["unit_price"] == "48.50"
    assert rows[0]["line_total"] == "388.00"
    assert rows[0]["quantity"] == "8"


def test_a_line_nobody_could_price_is_shown_without_a_number():
    """It has to appear — a customer who asked for it is entitled to see it
    on the list — but with nothing beside it that looks like a price."""
    row = _cd.display_lines([UNPRICED])[0]
    assert row["unit_price"] == _cd.TO_CONFIRM
    assert row["line_total"] == _cd.TO_CONFIRM
    assert row["priced"] == "no"


def test_the_total_says_when_it_does_not_cover_everything():
    """A customer reading a total that silently leaves out two of their
    lines is being given a number that is wrong for them, and they will
    hold us to it."""
    note = _cd.caveat(LINES + [UNPRICED])
    assert note and "not included" in note
    assert _cd.caveat(LINES) == "", "a complete quote should carry no warning"


def test_an_empty_quote_still_draws_totals():
    rows = _cd.display_totals([])
    assert rows and rows[-1][0] == "Total"


# ── Delivery ─────────────────────────────────────────────────────────────────

def test_delivery_is_added_to_the_goods_and_taxed_with_them():
    """Freight on a taxable supply is itself taxable. A quote that put GST on
    the filters and not on the delivery understates the total by a tenth of
    the freight."""
    t = _pricing.quote_totals(LINES, shipping=35.0)
    assert t["goods"] == 577.0
    assert t["shipping"] == 35.0
    assert t["subtotal"] == 612.0
    assert t["gst"] == 61.20
    assert t["total"] == 673.20


def test_no_delivery_leaves_the_totals_exactly_as_they_were():
    """Every quote written before today, and every screen that never passes
    one, must come out at the same numbers."""
    t = _pricing.quote_totals(LINES)
    assert t["shipping"] == 0
    assert t["subtotal"] == 577.0 == t["goods"]
    assert t["total"] == 634.70


def test_a_delivery_of_nothing_is_not_listed():
    """A line reading "Delivery 0.00" invites the question of what it would
    have been."""
    labels = [label for label, _, _ in _cd.display_totals(LINES, 0)]
    assert "Delivery" not in labels
    labels = [label for label, _, _ in _cd.display_totals(LINES, 35.0)]
    assert "Delivery" in labels and "Goods" in labels


def test_nonsense_in_the_delivery_box_is_not_a_negative_quote():
    for bad in (-50, "", None, "abc"):
        t = _pricing.quote_totals(LINES, shipping=bad)
        assert t["shipping"] == 0, bad
        assert t["total"] >= t["goods"]


def test_what_is_typed_into_the_box_is_read_the_way_people_type_it():
    """"$45", "45.00 ", "1,200" — it is a box being typed into, so it spends
    most of its life half-finished and none of those may stop the totals
    redrawing."""
    fn = GUI.split("def _quote_shipping(self)")[1].split("\n    def ")[0]
    assert '"$"' in fn and '","' in fn
    assert "except ValueError" in fn
    assert "max(0.0" in fn, "a negative delivery would reduce the total"


def test_the_delivery_is_saved_with_the_quote():
    """Otherwise it is on the screen the customer saw and nowhere else, and
    the invoice goes out without it."""
    assert '"shipping":       totals["shipping"]' in GUI
    db = (ROOT / "taf_order_app/db.py").read_text(encoding="utf-8")
    assert '"shipping":       round(float(data.get("shipping") or 0), 2)' in db
    sql = (ROOT / "migrate_quote_shipping.sql").read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS shipping" in sql


def test_a_reopened_quote_still_has_its_delivery():
    fn = GUI.split("def _load_quote(self, row)")[1].split("\n    def ")[0]
    assert 'row.get("shipping")' in fn


def test_a_new_quote_does_not_inherit_the_last_delivery():
    fn = GUI.split("def _new_quote(self)")[1].split("\n    def ")[0]
    assert "quote_shipping_var.set(\"\")" in fn


def test_the_pdf_shows_delivery_when_there_is_one():
    pdf = (ROOT / "taf_order_app/quote_pdf.py").read_text(encoding="utf-8")
    assert "shipping: float = 0.0" in pdf
    assert '"Delivery"' in pdf
    assert 'if totals["shipping"]' in pdf


# ── How the window behaves ───────────────────────────────────────────────────

def test_it_does_not_take_the_keyboard():
    """Whoever is typing is typing on the other screen. A window that grabs
    focus every time a line is added makes the quote take twice as long."""
    cls = _code(GUI.split("class CounterDisplay")[1].split("\nclass ")[0])
    assert "grab_set" not in cls
    assert "transient" not in cls


def test_escape_does_not_close_it():
    """The person who would press Escape is standing on the wrong side of
    it. Escape leaves full screen instead."""
    cls = GUI.split("class CounterDisplay")[1].split("\nclass ")[0]
    esc = [l for l in cls.split("\n") if '"<Escape>"' in l]
    assert esc, "Escape does nothing at all"
    assert "fullscreen" in esc[0] and "destroy" not in esc[0], esc[0]


def test_it_is_readable_across_a_counter():
    """The quote screen's type is sized for somebody a foot away."""
    cls = GUI.split("class CounterDisplay")[1].split("\nclass ")[0]
    sizes = {k: int(v) for k, v in
             re.findall(r"F_(HEAD|ROW|TOT)\s*=\s*(\d+)", cls)}
    assert sizes["ROW"] >= 15, sizes
    assert sizes["TOT"] > sizes["ROW"], "the total is not the biggest number"


def test_it_does_not_follow_dark_mode():
    """Dark on a cheap second monitor at an angle across a counter is harder
    to read, and the person choosing the theme is not the one reading it."""
    cls = GUI.split("class CounterDisplay")[1].split("\nclass ")[0]
    assert re.search(r'BG\s*=\s*"#FFFFFF"', cls)
    for app_colour in ("bg=CBG", "bg=CCA", "fg=CTX"):
        assert app_colour not in cls, f"{app_colour} follows the app's theme"


def test_it_is_redrawn_from_the_one_place_a_quote_changes():
    """A second list of the places a quote can change would eventually miss
    one, and the customer would be reading a screen a line behind."""
    fn = GUI.split("def _refresh_quote_lines(self)")[1].split("\n    def ")[0]
    assert "_push_to_counter" in fn


def test_a_display_that_has_gone_does_not_take_the_quote_with_it()  :
    """Screen unplugged, window killed. The quote carries on."""
    fn = GUI.split("def _push_to_counter")[1].split("\n    def ")[0]
    assert "except Exception" in fn
    assert "self._counter_win = None" in fn


def test_it_is_only_offered_where_somebody_turned_it_on():
    """Most PCs in the building have one monitor and no counter."""
    assert 'is_on("customer_display")' in GUI
    from taf_order_app import features as _feat
    assert "customer_display" in _feat.BY_KEY
    assert _feat.BY_KEY["customer_display"].built
