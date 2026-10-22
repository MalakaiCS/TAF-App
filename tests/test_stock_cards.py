"""The Stock page's square cards: how many across, the units, the price."""
from __future__ import annotations

from taf_order_app import stock_cards as cards


def test_five_four_three_then_two_and_one_across():
    assert [cards.columns_for(w) for w in (1500, 1100, 1000, 860, 700, 600,
                                           500, 420, 380, 300)] == \
        [5, 5, 4, 4, 3, 3, 2, 2, 1, 1]


def test_a_high_dpi_screen_counts_its_room_at_100_percent():
    # 2000 real pixels at 200% is a 1000-pixel window: four across.
    assert cards.columns_for(2000, 2.0) == 4


def test_every_card_is_the_same_size_and_they_fit():
    side = cards.card_size(1000, 4, 14)
    assert side == 232
    assert 4 * side + 5 * 14 <= 1000


def test_units_are_said_for_the_quantity():
    assert cards.unit_label("rolls", 1) == "roll"
    assert cards.unit_label("roll", 3) == "rolls"
    assert cards.unit_label("each", 5) == "pieces"
    assert cards.unit_label("m2", 40) == "m²"
    assert cards.unit_label("lengths", 1) == "length"
    assert cards.unit_label("bundle", 2) == "bundle"      # one we do not know
    assert cards.unit_label("", 2) == "pieces"


def test_quantities_are_shown_plainly():
    assert cards.qty_text(40.0) == "40"
    assert cards.qty_text(2.5) == "2.5"
    assert cards.qty_text(None) == "0"


LINKS = [
    {"stock_item_id": "st", "supplier_id": "a", "supplier_code": "AD-1",
     "unit_price": None, "preferred": False},
    {"stock_item_id": "st", "supplier_id": "f", "supplier_code": "FDG-1",
     "unit_price": None, "preferred": True},
]
ITEMS = [{"code": "FDG-1", "purchase_price": 18.5},
         {"code": "AD-1", "purchase_price": 17.0},
         {"code": "OTHER", "purchase_price": 9.0, "stock_item_id": "st2"}]


def test_the_price_is_what_we_pay_the_preferred_supplier():
    assert cards.price_for({"id": "st"}, LINKS, ITEMS) == 18.5
    agreed = [dict(LINKS[0], unit_price=16.0), LINKS[1]]
    assert cards.price_for({"id": "st"}, agreed, ITEMS) == 16.0


def test_or_xeros_price_for_the_item_linked_to_it():
    assert cards.price_for({"id": "st2"}, LINKS, ITEMS) == 9.0
    assert cards.price_for({"id": "nothing"}, LINKS, ITEMS) is None


def test_the_price_is_ex_gst_per_unit():
    assert cards.price_text(18.5, "rolls") == "$18.50 ex GST / roll"
    assert cards.price_text(None, "rolls") == "No price yet"


def test_low_and_out_as_the_list_had_them():
    assert cards.stock_state({"stock_on_hand": 0, "minimum_on_hand": 5}) == "out"
    assert cards.stock_state({"stock_on_hand": 3, "minimum_on_hand": 5}) == "low"
    assert cards.stock_state({"stock_on_hand": 9, "minimum_on_hand": 5}) == "ok"
