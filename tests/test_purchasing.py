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
