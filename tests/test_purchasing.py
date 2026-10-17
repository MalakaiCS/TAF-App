"""Buying through Xero: a size with no code is priced from the sizes either
side of it, requests become purchase order lines, and what has arrived is
not still counted as on order.
"""
from __future__ import annotations

from taf_order_app import purchasing
from taf_order_app import records

PRICES = {"FDG-C45-2440": 18.50, "FDG-C50-2440": 20.90, "FDG-C25-2440": 12.00}
ITEMS = [{"code": c, "purchase_price": p, "supplier_id": "s-fdg",
          "stock_item_id": "st-45" if c == "FDG-C45-2440" else None}
         for c, p in PRICES.items()]
ITEMS.append({"code": "VUL-FLY-9", "purchase_price": 4.10,
              "supplier_id": "s-vul", "name": "Flyscreen 9mm"})


def test_a_code_xero_has_is_its_own_price():
    assert purchasing.estimate_price("fdg-c45-2440", PRICES) == (18.5, "")


def test_a_size_between_two_is_read_off_the_line_between_them():
    price, how = purchasing.estimate_price("FDG-C47-2440", PRICES)
    assert price == 19.46
    assert how == "estimated from FDG-C45-2440 and FDG-C50-2440"


def test_past_the_largest_size_it_carries_on_from_the_last_two():
    assert purchasing.estimate_price("FDG-C55-2440", PRICES)[0] == 23.30


def test_with_one_neighbour_it_goes_in_proportion_to_the_size():
    price, how = purchasing.estimate_price("ABC-90", {"ABC-45": 10.0})
    assert (price, how) == (20.0, "estimated from ABC-45")


def test_nothing_near_enough_says_so():
    assert purchasing.estimate_price("FDG-C47-3000", PRICES) == (None, "")
    assert purchasing.estimate_price("TAPE", PRICES) == (None, "")
    assert purchasing.estimate_price("FDG-C47-2440", {}) == (None, "")


def test_a_request_for_a_size_finds_the_suppliers_code():
    got = purchasing.guess_line("45mm channel", ITEMS, "s-fdg")
    assert got == {"item_code": "FDG-C45-2440", "unit_price": 18.5,
                   "estimated": ""}


def test_a_size_with_no_code_gets_one_and_an_estimate():
    got = purchasing.guess_line("47", ITEMS, "s-fdg")
    assert got["item_code"] == "FDG-C47-2440"
    assert got["unit_price"] == 19.46 and got["estimated"]


def test_another_suppliers_items_are_not_used():
    assert purchasing.guess_line("47mm", ITEMS, "s-vul") == {}


def test_requests_become_lines():
    lines = purchasing.lines_from_requests([
        {"id": "r1", "item": "Channel", "detail": "47mm",
         "quantity": "20 lengths", "supplier_id": "s-fdg"},
        {"id": "r2", "item": "Channel", "detail": "45", "quantity": "6",
         "supplier_id": "s-fdg"},
        {"id": "r3", "item": "Rivets", "detail": "4mm pop", "quantity": "",
         "supplier_id": ""},
    ], ITEMS)
    assert lines[0]["quantity"] == 20 and lines[0]["request_ids"] == ["r1"]
    assert lines[0]["estimated"].startswith("estimated from")
    assert lines[1]["item_code"] == "FDG-C45-2440"
    assert lines[1]["stock_item_id"] == "st-45"
    assert lines[2]["quantity"] == 1 and lines[2]["unit_price"] is None


def test_a_request_with_its_code_takes_xeros_wording_and_price():
    line = purchasing.lines_from_requests(
        [{"id": "r", "item": "Other", "detail": "flyscreen", "quantity": "3",
          "item_code": "VUL-FLY-9"}], ITEMS)[0]
    assert (line["description"], line["unit_price"]) == ("Flyscreen 9mm", 4.10)


def test_one_purchase_order_per_supplier():
    groups = purchasing.group_by_supplier([
        {"id": 1, "supplier_id": "a"}, {"id": 2, "supplier_id": None},
        {"id": 3, "supplier_id": "a"}])
    assert {k: [r["id"] for r in v] for k, v in groups.items()} == \
        {"a": [1, 3], "": [2]}


def test_totals_and_what_is_still_to_come():
    lines = [{"quantity": 20, "unit_price": 18.5, "received": 5},
             {"quantity": 2, "unit_price": None},
             {"quantity": "x", "unit_price": 3}]
    assert purchasing.po_total(lines) == 370.0
    assert purchasing.outstanding(lines[0]) == 15
    assert purchasing.outstanding({"quantity": 3, "received": 5}) == 0


def test_what_has_arrived_is_not_still_on_order():
    rows = [{"status": "part_received",
             "lines": [{"stock_item_id": "st-45", "quantity": 20, "received": 5},
                       {"item_id": "st-9", "quantity": 4, "received": 4}]},
            {"status": "received",
             "lines": [{"item_id": "st-45", "quantity": 99}]}]
    assert records.quantities_on_order(rows) == {"st-45": 15.0}


# ── Where each stock item comes from ─────────────────────────────────────────

STOCK = [
    {"id": "st-45", "name": "C Channel 45mm", "product_type": "Channel",
     "stock_on_hand": 4, "minimum_on_hand": 20},
    {"id": "st-50", "name": "C Channel 50mm", "product_type": "Channel",
     "stock_on_hand": 30, "minimum_on_hand": 10},
    {"id": "st-tape", "name": "Foil tape 50mm", "product_type": "Consumables",
     "stock_on_hand": 0, "minimum_on_hand": 6},
    {"id": "st-glue", "name": "Glue", "product_type": "Consumables",
     "stock_on_hand": 0, "minimum_on_hand": 2},
]
LINKS = [
    {"id": "l1", "stock_item_id": "st-45", "supplier_id": "s-ad",
     "supplier_code": "AD-C45", "unit_price": 17.0, "preferred": False},
    {"id": "l2", "stock_item_id": "st-45", "supplier_id": "s-fdg",
     "supplier_code": "FDG-C45-2440", "unit_price": None, "preferred": True},
    {"id": "l3", "stock_item_id": "st-tape", "supplier_id": "s-ad",
     "supplier_code": "", "unit_price": 9.5, "preferred": False},
]


def test_order_supplies_offers_the_stock_items_of_that_kind():
    names = [s["name"] for s in purchasing.stock_for("Channel", STOCK)]
    assert names == ["C Channel 45mm", "C Channel 50mm"]
    assert [s["name"] for s in purchasing.stock_for("Tape", STOCK)] == ["Foil tape 50mm"]
    assert len(purchasing.stock_for("Other", STOCK)) == 4
    assert len(purchasing.stock_for("Mesh Wire", STOCK)) == 4    # nothing matches


def test_the_preferred_supplier_comes_first():
    assert [l["supplier_id"] for l in purchasing.suppliers_for("st-45", LINKS)] == \
        ["s-fdg", "s-ad"]
    assert purchasing.suppliers_for("st-glue", LINKS) == []


def test_a_stock_line_takes_the_suppliers_code_and_price():
    fdg = purchasing.stock_line(STOCK[0], LINKS[1], ITEMS, 16)
    assert (fdg["item_code"], fdg["unit_price"], fdg["stock_item_id"]) == \
        ("FDG-C45-2440", 18.5, "st-45")      # no agreed price: Xero's
    ad = purchasing.stock_line(STOCK[0], LINKS[0], ITEMS, 16)
    assert (ad["item_code"], ad["unit_price"], ad["description"]) == \
        ("AD-C45", 17.0, "C Channel 45mm")


def test_low_stock_becomes_an_order_per_supplier():
    orders = purchasing.low_stock_orders(STOCK, LINKS, ITEMS, {"st-45": 6})
    assert set(orders) == {"s-fdg", "s-ad", ""}
    assert [(l["item_code"], l["quantity"]) for l in orders["s-fdg"]] == \
        [("FDG-C45-2440", 10.0)]             # 20 wanted, 4 here, 6 coming
    assert orders["s-ad"][0]["unit_price"] == 9.5
    assert [l["description"] for l in orders[""]] == ["Glue"]


def test_enough_on_hand_is_not_ordered():
    assert purchasing.shortfall(STOCK[1]) == 0
    assert purchasing.shortfall({"stock_on_hand": 1.2, "minimum_on_hand": 3}) == 2
    assert purchasing.shortfall({"stock_on_hand": 0, "minimum_on_hand": 0}) == 0


def test_a_request_for_a_stock_item_uses_that_suppliers_code():
    line = purchasing.lines_from_requests(
        [{"id": "r1", "item": "Channel", "detail": "C Channel 45mm",
          "quantity": "12 lengths", "supplier_id": "s-ad",
          "stock_item_id": "st-45"}], ITEMS, LINKS, STOCK)[0]
    assert (line["item_code"], line["unit_price"], line["quantity"],
            line["stock_item_id"], line["request_ids"]) == \
        ("AD-C45", 17.0, 12.0, "st-45", ["r1"])


# ── A supply order picked from the stock list ────────────────────────────────

def test_a_stock_item_is_the_kind_of_supply_it_sounds_like():
    assert purchasing.supply_item_for({"name": "C Channel 45mm",
                                       "product_type": "Other"}) == "Channel"
    assert purchasing.supply_item_for({"name": "Foil tape 50mm"}) == "Tape"
    assert purchasing.supply_item_for({"name": "G4 roll",
                                       "product_type": "Media"}) == "Media"
    assert purchasing.supply_item_for({"name": "Pop rivet 4mm"}) == "Rivets"
    assert purchasing.supply_item_for({"name": "Galv mesh 6mm"}) == "Mesh Wire"
    assert purchasing.supply_item_for({"name": "Glue"}) == "Other"


def test_a_line_names_the_stock_item_in_its_own_units():
    line = purchasing.stock_request_line(
        {"id": "st-45", "name": "C Channel 45mm", "unit": "lengths"}, "20",
        "s-fdg")
    assert line == {"item": "Channel", "detail": "C Channel 45mm",
                    "quantity": "20 lengths", "supplier_id": "s-fdg",
                    "item_code": "", "stock_item_id": "st-45"}
    assert purchasing.stock_request_line({"id": "g", "name": "Glue"},
                                         "2 tubs")["quantity"] == "2 tubs"
    assert purchasing.stock_request_line({"id": "g", "name": "Glue",
                                          "unit": "each"}, "1")["quantity"] == "1 piece"


_NEW_STOCK = [
    {"id": "a", "name": "C Channel 45mm", "product_type": "Channel",
     "stock_on_hand": 4, "minimum_on_hand": 20, "unit": "lengths"},
    {"id": "b", "name": "Foil tape 48mm", "product_type": "Tape",
     "stock_on_hand": 30, "minimum_on_hand": 10, "unit": "rolls"},
    {"id": "c", "name": "C Channel 25mm", "product_type": "Channel",
     "stock_on_hand": 0, "minimum_on_hand": 0, "unit": "lengths"},
    {"id": "d", "name": "G4 media", "description": "Pleated, 25mm",
     "stock_on_hand": 2, "minimum_on_hand": 5.5, "unit": "rolls"},
]
_NEW_LINKS = [
    {"stock_item_id": "a", "supplier_id": "s-vul", "supplier_code": "V45"},
    {"stock_item_id": "a", "supplier_id": "s-fdg", "supplier_code": "CC45",
     "preferred": True},
    {"stock_item_id": "d", "supplier_id": "s-vul", "supplier_code": "G4"},
]


def test_a_new_order_line_carries_the_suppliers_code():
    line = purchasing.stock_request_line(_NEW_STOCK[0], "16", "s-fdg", _NEW_LINKS)
    assert line["item_code"] == "CC45"
    assert purchasing.stock_request_line(_NEW_STOCK[0], "16", "s-x",
                                         _NEW_LINKS)["item_code"] == ""
    assert purchasing.stock_request_line(_NEW_STOCK[0], "16", "",
                                         _NEW_LINKS)["item_code"] == ""


def test_searching_stock_matches_every_word_low_ones_first():
    names = lambda rows: [r["id"] for r in rows]
    # Out (c), then low (a, d), then the rest - each by name.
    assert names(purchasing.search_stock(_NEW_STOCK)) == ["c", "a", "d", "b"]
    assert names(purchasing.search_stock(_NEW_STOCK, "45 chan")) == ["a"]
    assert names(purchasing.search_stock(_NEW_STOCK, "CHANNEL")) == ["c", "a"]
    assert names(purchasing.search_stock(_NEW_STOCK, "pleated")) == ["d"]
    assert purchasing.search_stock(_NEW_STOCK, "nothing like it") == []


def test_a_picked_item_comes_with_what_it_is_short_and_its_supplier():
    pick = purchasing.new_order_pick(_NEW_STOCK[0], _NEW_LINKS)
    assert (pick["quantity"], pick["supplier_id"]) == ("16", "s-fdg")
    assert purchasing.new_order_pick(_NEW_STOCK[0], _NEW_LINKS,
                                     on_order=10)["quantity"] == "6"
    # Not low: somebody says how many. Nowhere to buy it: no supplier.
    plenty = purchasing.new_order_pick(_NEW_STOCK[1], _NEW_LINKS)
    assert (plenty["quantity"], plenty["supplier_id"]) == ("", "")
    assert purchasing.new_order_pick(_NEW_STOCK[3], _NEW_LINKS) == {
        "stock": _NEW_STOCK[3], "quantity": "4", "supplier_id": "s-vul"}


def test_add_everything_low_puts_on_each_item_below_its_minimum():
    picks = purchasing.low_picks(_NEW_STOCK, _NEW_LINKS)
    assert [(p["stock"]["id"], p["quantity"]) for p in picks] == \
        [("a", "16"), ("d", "4")]
    # What is already on order counts.
    assert [p["stock"]["id"] for p in purchasing.low_picks(
        _NEW_STOCK, _NEW_LINKS, {"a": 16})] == ["d"]
