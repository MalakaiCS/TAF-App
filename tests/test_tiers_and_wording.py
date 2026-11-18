"""Three price tiers, the price on the work order, and the invoice wording.

Each customer is on Tier 1, 2 or 3. A line on the work order is priced from
its customer's tier unless somebody typed a price on it, and that price is
what Xero gets. What Xero puts on the line is the invoice wording for the
filter type, not the worksheet's description.
"""
from __future__ import annotations

import csv
import tempfile
from pathlib import Path

from taf_order_app import invoice_wording as wording
from taf_order_app import pricing
from taf_order_app import xero

PRICE_ROWS = [
    {"part_number": "PPFG445-030", "unit_price": 30, "unit_price_2": 27,
     "unit_price_3": None},
    {"part_number": "FPFG425-040", "unit_price": "12.5", "unit_price_2": "",
     "unit_price_3": 10},
]
RATE_ROWS = [{"filter_type": "V-form", "media_type": "G4", "rate_per_sqm": 40,
              "rate_per_sqm_2": None, "rate_per_sqm_3": 32}]


def _vform(qty=4, part="PPFG445-030", **extra):
    item = {"Filter Type": "V-form", "Media Type": "G4", "Short": 595,
            "Long": 595, "Channel": 45, "Quantity": qty, "Part Number": part}
    item.update(extra)
    return item


# ── Tiers ────────────────────────────────────────────────────────────────────

def test_each_tier_has_its_price_and_a_blank_one_is_tier_1s():
    assert pricing.prices_for_tier(PRICE_ROWS, 1) == {"PPFG445-030": 30.0,
                                                      "FPFG425-040": 12.5}
    assert pricing.prices_for_tier(PRICE_ROWS, 2) == {"PPFG445-030": 27.0,
                                                      "FPFG425-040": 12.5}
    assert pricing.prices_for_tier(PRICE_ROWS, 3) == {"PPFG445-030": 30.0,
                                                      "FPFG425-040": 10.0}


def test_rates_per_square_metre_are_tiered_the_same_way():
    key = pricing._rate_key("V-form", "G4")
    assert pricing.rates_for_tier(RATE_ROWS, 2)[key] == 40.0
    assert pricing.rates_for_tier(RATE_ROWS, 3)[key] == 32.0


def test_a_customer_with_no_tier_or_a_strange_one_is_on_tier_1():
    assert pricing.tier_of({"price_tier": 3}) == 3
    assert pricing.tier_of({"price_tier": "2"}) == 2
    for odd in ({}, None, {"price_tier": 7}, {"price_tier": "gold"}):
        assert pricing.tier_of(odd) == 1


# ── The price on the work order ──────────────────────────────────────────────

def test_a_line_is_priced_from_the_customers_tier():
    item = pricing.price_line(_vform(), pricing.prices_for_tier(PRICE_ROWS, 2),
                              {}, 2)
    assert item["Unit Price"] == 27.0 and item["Price Source"] == "tier 2"


def test_a_new_customer_on_the_order_reprices_the_line():
    item = pricing.price_line(_vform(), pricing.prices_for_tier(PRICE_ROWS, 2),
                              {}, 2)
    pricing.price_line(item, pricing.prices_for_tier(PRICE_ROWS, 1), {}, 1)
    assert item["Unit Price"] == 30.0 and item["Price Source"] == "tier 1"


def test_a_price_typed_on_the_line_stays_whatever_the_tier_says():
    item = _vform(**{"Unit Price": 22.0, "Price Source": "manual"})
    pricing.price_line(item, pricing.prices_for_tier(PRICE_ROWS, 3), {}, 3)
    assert item["Unit Price"] == 22.0


def test_a_line_nothing_can_price_is_left_without_one_not_zero():
    item = pricing.price_line(_vform(part="NOPE-1", Channel=46), {}, {}, 1)
    assert "Unit Price" not in item and "Price Source" not in item


def test_the_work_orders_price_is_the_one_invoiced():
    """Once on the order it is the price, even if the list changes."""
    unit, source = pricing.price_for_item(
        _vform(**{"Unit Price": 25.0, "Price Source": "tier 2"}),
        {"PPFG445-030": 99.0}, {})
    assert (unit, source) == (25.0, "tier 2")


def test_bag_filters_are_invoiced_with_their_quantity():
    """They used to be read as nought of them and quietly left off."""
    bag = {"item_kind": "bag", "product_type": "3-Peak", "quantity": 2,
           "media": "F7", "width": 592, "height": 592, "depth": 600,
           "part_number": "BAG-1"}
    line = pricing.quote_lines([bag], {"BAG-1": 40.0}, {})[0]
    assert line["quantity"] == 2 and line["unit_price"] == 40.0
    assert line["description"] == "3-Peak F7 - 592 x 592 x 600mm"


def test_a_price_file_can_carry_all_three_tiers():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tiers.csv"
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Code", "Description", "Sell Price", "Tier 2 Price",
                        "Tier 3 Price"])
            w.writerow(["FPFG425-040", "Panel", "10.00", "9.00", ""])
        rows, problems, report = pricing.read_price_file(path)
    assert not problems
    assert rows[0]["unit_price"] == 10.0 and rows[0]["unit_price_2"] == 9.0
    assert "unit_price_3" not in rows[0]        # blank: Tier 1's price
    assert "tier2 = Tier 2 Price" in report[0]


def test_a_tier_2_column_is_never_read_as_the_price():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tiers.csv"
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Part Number", "Tier 2 Price", "Tier 1 Price"])
            w.writerow(["FPFG425-040", "9.00", "10.00"])
        rows, _p, _r = pricing.read_price_file(path)
    assert rows[0]["unit_price"] == 10.0 and rows[0]["unit_price_2"] == 9.0


# ── The invoice wording ──────────────────────────────────────────────────────

def test_the_standard_wording_for_each_kind_of_filter():
    assert wording.describe(_vform(), wording.DEFAULT_RULES) == (
        "Galvanised Pleated Panel Filter in G4\nSize: 595 x 595 x 45mm")
    assert wording.describe(
        {"Filter Type": "Flat Panel", "Media Type": "F5", "Short": 495,
         "Long": 595, "Channel": 25}, wording.DEFAULT_RULES) == (
        "Galvanised Flat Panel Filters in F5\nSize: 495 x 595 x 25mm")
    assert wording.describe(
        {"Filter Type": "Flyscreen", "Media Type": "GREY", "Short": 495,
         "Long": 595, "Channel": 10}, wording.DEFAULT_RULES) == (
        "Flat Panel Flyscreen Filter in GREY\nSize: 495 x 595 x 10mm")


def test_a_v_form_under_30mm_is_not_called_a_pleated_panel():
    thin = _vform(Channel=25)
    assert wording.rule_for(thin, wording.DEFAULT_RULES) is None
    assert "Pleated" not in wording.describe(thin, wording.DEFAULT_RULES)


def test_the_deepest_rule_a_line_reaches_wins():
    rules = wording.DEFAULT_RULES + [
        {"filter_type": "V-form", "min_depth": 90, "wording": "Deep {Size}"}]
    assert wording.describe(_vform(Channel=95), rules) == "Deep 595 x 595 x 95mm"
    assert wording.describe(_vform(), rules).startswith("Galvanised Pleated")


def test_a_lines_own_xero_description_wins():
    item = _vform(**{"Xero Description": "Pleated panel, special order"})
    assert wording.describe(item) == "Pleated panel, special order"


def test_a_bag_type_can_have_wording_too():
    rules = [{"filter_type": "3-Peak", "min_depth": 0,
              "wording": "3 Peak Bag Filter {Media}\nSize: {Size}"}]
    bag = {"item_kind": "bag", "product_type": "3-Peak", "media": "F7",
           "width": 592, "height": 592, "depth": 600}
    assert wording.describe(bag, rules) == \
        "3 Peak Bag Filter F7\nSize: 592 x 592 x 600mm"


def test_stored_wording_is_checked_before_it_is_used():
    assert wording.clean([{"filter_type": "V-form"}, "junk",
                          {"filter_type": "X", "wording": "ok",
                           "min_depth": "-5", "max_depth": "x"}]) == [
        {"filter_type": "X", "min_depth": 0, "max_depth": 0, "wording": "ok"}]
    wording.set_rules(None)
    assert wording.current() == wording.DEFAULT_RULES


# ── What Xero is sent ────────────────────────────────────────────────────────

def test_the_draft_carries_the_work_order_price_and_the_invoice_wording():
    items = [_vform(**{"Unit Price": 25.0, "Price Source": "manual"}),
             _vform(part="FPFG425-040", Channel=25, **{"Filter Type": "Flat Panel"})]
    built = xero.draft_from({"Customer Name": "Bells", "Order Number": "A-1",
                             "Date Ordered": "16/10/26"}, items, {"price_tier": 3},
                            pricing.prices_for_tier(PRICE_ROWS, 3), {},
                            wording.DEFAULT_RULES)
    lines = built["invoice"]["lines"]
    assert [l["unit_amount"] for l in lines] == [25.0, 10.0]
    assert lines[0]["description"].startswith("Galvanised Pleated Panel Filter")
    assert lines[1]["description"].startswith("Galvanised Flat Panel Filters")
    assert built["unpriced"] == 0


def test_the_csv_export_uses_the_same_wording():
    rows, unpriced = pricing.invoice_for_order(
        {"Customer Name": "Bells", "Order Number": "A-1",
         "Date Ordered": "16/10/26"}, [_vform()],
        prices=pricing.prices_for_tier(PRICE_ROWS, 1), rates={},
        wording=wording.DEFAULT_RULES)
    assert rows[0]["*Description"].startswith("Galvanised Pleated Panel Filter")
    assert rows[0]["*UnitAmount"] == "30.00"


def _panel(depth, ftype="Flat Panel"):
    return {"Filter Type": ftype, "Media Type": "G4", "Short": 595,
            "Long": 595, "Channel": depth}


def test_flat_panel_wording_covers_10_to_25mm():
    for depth in (10, 11, 25):
        assert wording.describe(_panel(depth), wording.DEFAULT_RULES).startswith(
            "Galvanised Flat Panel Filters"), depth
    assert not wording.describe(_panel(28), wording.DEFAULT_RULES).startswith(
        "Galvanised")


def test_flyscreen_wording_covers_9_and_11mm():
    for depth in (9, 11):
        assert wording.describe(_panel(depth, "Flyscreen"),
                                wording.DEFAULT_RULES).startswith(
            "Flat Panel Flyscreen Filter"), depth


def test_a_rule_says_its_depths():
    assert [wording.depth_text(r) for r in wording.DEFAULT_RULES] == [
        "9-11mm", "10-25mm", "30mm+"]


def test_a_flyscreen_is_9_or_11mm_and_a_flat_panel_10_to_25():
    from taf_order_app import part_numbers as pn
    assert [pn.filter_type_for_thickness(d) for d in (9, 10, 11, 12, 25)] == [
        "Flyscreen", "Flat Panel", "Flyscreen", "Flat Panel", "Flat Panel"]


# ── Delivery fees ────────────────────────────────────────────────────────────

def test_the_order_says_its_delivery_fee_or_takes_the_customers():
    assert pricing.delivery_fee({"Delivery Fee": "25"}, {"delivery_fee": 40}) == 25.0
    assert pricing.delivery_fee({"Delivery Fee": ""}, {"delivery_fee": 40}) == 0.0
    # An order from before delivery fees, or raised on a phone.
    assert pricing.delivery_fee({}, {"delivery_fee": "40"}) == 40.0
    assert pricing.delivery_fee({}, {}) == 0.0
    assert pricing.delivery_fee({"Delivery Fee": "lots"}) == 0.0


def test_the_delivery_fee_goes_on_the_invoice_as_its_own_line():
    built = xero.draft_from({"Customer Name": "Bells", "Delivery Fee": "35.00"},
                            [_vform(**{"Unit Price": 10.0, "Price Source": "manual"})],
                            {"xero_contact_id": "abc"}, {}, {})
    lines = built["invoice"]["lines"]
    assert lines[-1] == {"description": "Delivery", "quantity": 1.0,
                         "unit_amount": 35.0, "item_code": "DELIVERY"}
    assert built["invoice"]["contact_id"] == "abc"
    rows, _u = pricing.invoice_for_order(
        {"Customer Name": "Bells", "Order Number": "A-1",
         "Date Ordered": "16/10/26"}, [_vform()],
        customer={"delivery_fee": 20}, prices={"PPFG445-030": 30.0}, rates={})
    assert [(r["InventoryItemCode"], r["*UnitAmount"]) for r in rows] == [
        ("PPFG445-030", "30.00"), ("DELIVERY", "20.00")]


# ── Prices typed into the table ──────────────────────────────────────────────

def test_a_price_to_more_places_keeps_them_and_a_plain_one_has_two():
    assert pricing.money_text(27.5) == "27.50"
    assert pricing.money_text(33.33333) == "33.3333"
    assert pricing.money_text(0) == "0.00"


def test_xero_finds_a_customers_contact_only_when_one_name_matches():
    contacts = [{"id": "1", "name": "Bells Pty Ltd"}, {"id": "2", "name": "Bells Creek"}]
    assert xero.best_contact(contacts, ["BELLS PTY LTD", "Bells"])["id"] == "1"
    assert xero.best_contact(contacts, ["Bells"]) is None
    assert xero.best_contact(contacts + [{"id": "3", "name": "bells pty ltd"}],
                             ["Bells Pty Ltd"]) is None


# ── Collection or delivery slip ──────────────────────────────────────────────

def test_a_pick_up_gets_a_collection_slip_and_the_rest_a_delivery_slip():
    from taf_order_app import dockets
    assert dockets.handover([{"location": "Pick Up"}]) == dockets.COLLECTED
    assert dockets.handover([{"location": "Logan"}]) == dockets.DELIVERED
    assert dockets.handover([{"db_header": {"Location": "Pick Up"}}]) == \
        dockets.COLLECTED
