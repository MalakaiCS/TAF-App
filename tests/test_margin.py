"""What a job actually makes.

The app has always known what a filter sells for and never what it costs to
make, so a quote could be written, sent and accepted without anyone being
able to say whether it was worth doing.

The whole thing turns on one distinction: a line nobody has costed is
*unknown*, not free. Get that wrong and the app reports a 100% margin on
every product whose cost was never entered — a number that reads as fact,
is wrong, and is worse than showing nothing at all.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import pricing as _p     # noqa: E402

PRICES = {"FPFG425-020": 30.0, "FPFG425-030": 40.0}
COSTS = {"FPFG425-020": 12.0}               # the 30mm has no cost recorded
RATES = {_p._rate_key("V-form", "G4"): 50.0}
CRATES = {_p._rate_key("V-form", "G4"): 20.0}


def _two_lines():
    items = [
        {"item_kind": "catalogue", "Part Number": "FPFG425-020",
         "Description": "Flat panel G4", "Quantity": 2, "Unit Price": 30.0},
        {"item_kind": "catalogue", "Part Number": "FPFG425-030",
         "Description": "Flat panel G4 30mm", "Quantity": 1, "Unit Price": 40.0},
    ]
    return _p.with_margin(_p.quote_lines(items, PRICES, RATES), COSTS, CRATES)


# ── Unknown is not zero ──────────────────────────────────────────────────────

def test_a_line_nobody_costed_has_no_margin_rather_than_all_of_it():
    lines = _two_lines()
    assert lines[0]["margin"] == 36.0
    assert lines[1]["margin"] is None, \
        "an uncosted line was reported as pure profit"


def test_a_cost_of_zero_means_not_known_not_free():
    """Zero is what a numeric column holds when nobody has filled it in."""
    unit, source = _p.cost_for_item(
        {"item_kind": "catalogue", "Part Number": "X"}, {"X": 0.0}, {})
    assert source == "" and unit == 0.0


def test_a_rate_of_zero_does_not_cost_a_filter_at_nothing():
    item = {"Filter Type": "V-form", "Media Type": "G4",
            "Short": 500, "Long": 600, "Channel": 45}
    _, source = _p.cost_for_item(item, {}, {_p._rate_key("V-form", "G4"): 0.0})
    assert source == ""


def test_the_totals_leave_out_what_they_cannot_know():
    s = _p.margin_summary(_two_lines())
    assert s["sell"] == 60.0 and s["cost"] == 24.0
    assert s["margin"] == 36.0 and s["percent"] == 60.0
    assert s["known"] == 1 and s["unknown"] == 1


def test_the_line_says_how_much_was_left_out():
    """A margin worked out over half the lines and shown as "the margin" is
    worse than no figure — it reads as fact."""
    label = _p.margin_label(_p.margin_summary(_two_lines()))
    assert "1 line not costed" in label
    assert "$36.00" in label


def test_nothing_costed_claims_nothing():
    lines = _p.with_margin(
        _p.quote_lines([{"item_kind": "catalogue", "Part Number": "FPFG425-020",
                         "Quantity": 1, "Unit Price": 30.0}], PRICES, RATES),
        {}, {})
    s = _p.margin_summary(lines)
    assert s["known"] == 0 and s["percent"] is None
    assert "unknown" in _p.margin_label(s).lower()


# ── Costing works the way pricing does ───────────────────────────────────────

def test_a_filter_is_costed_over_the_same_area_it_is_priced_on():
    item = {"Filter Type": "V-form", "Media Type": "G4",
            "Short": 500, "Long": 600, "Channel": 45}
    price, psrc = _p.price_for_item(item, {}, RATES)
    cost, csrc = _p.cost_for_item(item, {}, CRATES)
    assert psrc == "rate" and csrc == "rate"
    assert price > 0 and cost > 0
    # Same area, so the ratio is exactly the ratio of the two rates.
    assert abs(cost / price - 20.0 / 50.0) < 1e-9


def test_a_blank_media_rate_covers_every_grade_on_the_cost_side_too():
    item = {"Filter Type": "Flyscreen", "Media Type": "WASH",
            "Short": 300, "Long": 400, "Channel": 25}
    cost, source = _p.cost_for_item(
        item, {}, {_p._rate_key("Flyscreen", ""): 15.0})
    assert source == "rate" and cost > 0


def test_there_is_no_nearest_size_fallback_for_cost():
    """Pricing a 48mm filter as the 50mm is a decision somebody can see on a
    quote and correct. Costing it that way would quietly move a margin
    figure nobody is checking."""
    src = (ROOT / "taf_order_app" / "pricing.py").read_text(encoding="utf-8")
    fn = src.split("def cost_for_item")[1].split("\ndef ")[0]
    assert "nearest_priced_part" not in fn


# ── What reaches the screen ──────────────────────────────────────────────────

def test_the_products_list_shows_a_dash_not_a_hundred_per_cent():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_gui_src", ROOT / "modern_order_gui.py")
    # Reading the function out rather than importing the module: importing it
    # needs tkinter, and the rest of this suite runs without a display.
    src = (ROOT / "modern_order_gui.py").read_text(encoding="utf-8")
    fn = src.split("def _price_cost_cells")[1].split("\ndef ")[0]
    ns: dict = {}
    exec("def _price_cost_cells" + fn, ns)          # noqa: S102
    cells = ns["_price_cost_cells"]
    assert cells({"unit_price": 30, "unit_cost": 12}) == ("12.00", "60%")
    assert cells({"unit_price": 30, "unit_cost": 0}) == ("—", "—")
    assert cells({"unit_price": 30}) == ("—", "—")
    assert cells({"unit_price": 0, "unit_cost": 12}) == ("12.00", "—")
    del spec


def test_margin_is_only_shown_to_the_people_who_set_prices():
    """It is the one number on the quote screen that must never end up in
    front of a customer."""
    # Anchored on the function rather than a fixed number of characters
    # after a line. It used to slice 700 characters, and adding the delivery
    # row to the totals pushed the margin past the end of the slice — a test
    # that stops reading the thing it is about is a test that passes.
    src = (ROOT / "modern_order_gui.py").read_text(encoding="utf-8")
    block = src.split("def _refresh_quote_lines(self)")[1].split("\n    def ")[0]
    assert "margin_label" in block, "the margin has left the quote screen"
    assert "can_manage_prices()" in block
    assert block.index("can_manage_prices()") < block.index("margin_label")


def test_a_price_import_cannot_wipe_costs_already_entered():
    """Price spreadsheets have no cost column. Sending unit_cost=0 for every
    row would erase months of entry on the next import."""
    src = (ROOT / "taf_order_app" / "db.py").read_text(encoding="utf-8")
    fn = src.split("def upsert_prices")[1].split("\ndef ")[0]
    assert 'if row.get("unit_cost") not in (None, "", 0, 0.0):' in fn


def test_it_still_saves_prices_without_the_migration():
    """Most people will run this build before they run the SQL, and a price
    correction must not start failing because of a column they haven't added
    yet."""
    src = (ROOT / "taf_order_app" / "db.py").read_text(encoding="utf-8")
    for fn_name in ("upsert_prices", "set_price_rate"):
        fn = src.split(f"def {fn_name}")[1].split("\ndef ")[0]
        assert "except Exception" in fn and "raise" in fn, fn_name
