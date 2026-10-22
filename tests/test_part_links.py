"""The part number each product sells as: a code the app makes for a line,
linked to the part in the price list (step 52)."""
from __future__ import annotations

from taf_order_app import bag_filler as bf
from taf_order_app import pricing as pr

BAG = {"item_kind": "bag", "product_type": "3-Peak", "media": "G4",
       "width": 610, "height": 610, "depth": 570, "quantity": 4,
       "part_number": "3PG4-610610570"}
PRICES = {"TAF-3P-G4-FL": 21.5, "3PF7-610610570": 30.0}


def _reset():
    pr.set_links([])
    pr.set_known({})


def test_a_line_sells_as_the_part_its_code_is_linked_to():
    _reset()
    assert pr.price_for_item(dict(BAG), PRICES) == (0.0, "")
    pr.set_links([{"code": "3pg4-610610570 ", "part_number": "taf-3p-g4-fl"}])
    assert pr.line_part_number(BAG) == "TAF-3P-G4-FL"
    assert pr.raw_part_number(BAG) == "3PG4-610610570"
    assert pr.price_for_item(dict(BAG), PRICES) == (21.5, "list")
    line = pr.quote_lines([dict(BAG)], PRICES)[0]
    assert line["part_number"] == "TAF-3P-G4-FL" and line["line_total"] == 86.0
    _reset()


def test_its_cost_comes_from_the_part_too():
    _reset()
    pr.set_links([{"code": "3PG4-610610570", "part_number": "TAF-3P-G4-FL"}])
    assert pr.cost_for_item(dict(BAG), {"TAF-3P-G4-FL": 9.0}) == (9.0, "list")
    _reset()


def test_a_code_with_no_link_is_itself_and_nonsense_links_are_ignored():
    _reset()
    pr.set_links([{"code": "X", "part_number": "x"}, {"code": "", "part_number": "Y"},
                  {"code": "Z", "part_number": ""}])
    assert pr.LINKS == {}
    f7 = dict(BAG, media="F7", part_number="3PF7-610610570")
    assert pr.price_for_item(f7, PRICES) == (30.0, "list")
    _reset()


def test_what_a_code_sells_as():
    _reset()
    pr.set_known(PRICES)
    pr.set_links([{"code": "3PG4-610610570", "part_number": "TAF-3P-G4-FL"},
                  {"code": "2WG4-610610340", "part_number": "GONE"}])
    assert pr.link_status("3pg4-610610570") == {
        "code": "3PG4-610610570", "part": "TAF-3P-G4-FL", "linked": True, "price": 21.5}
    assert pr.link_status("3PF7-610610570")["price"] == 30.0
    assert not pr.link_status("3PF7-610610570")["linked"]
    assert pr.link_status("2WG4-610610340")["price"] is None
    assert pr.link_status("NOPE") == {"code": "NOPE", "part": "NOPE", "linked": False,
                                      "price": None}
    _reset()


def test_every_standard_bag_and_roll_is_listed_once_with_its_code():
    got = bf.standard_products()
    codes = [p["code"] for p in got]
    assert len(codes) == len(set(codes))
    assert "3PG4-610610570" in codes and "3PF8-305610340" in codes
    assert "MPHE-F78P595595560" in codes and "TAFTFM390D" in codes
    assert all(bf.generate_part_number(p["item"]).upper() == p["code"] for p in got)
    assert not any("Custom" in p["product"] for p in got)


def test_xero_gets_the_part_it_sells_as():
    from taf_order_app import xero as xr
    _reset()
    pr.set_links([{"code": "3PG4-610610570", "part_number": "TAF-3P-G4-FL"}])
    built = xr.draft_from({"Order Number": "1", "Customer Name": "A"}, [dict(BAG)],
                          {}, PRICES, {})
    assert built["invoice"]["lines"][0]["item_code"] == "TAF-3P-G4-FL"
    assert built["invoice"]["lines"][0]["unit_amount"] == 21.5
    _reset()


def test_a_line_from_the_price_list_goes_on_the_docket_not_the_filter_worksheet():
    from taf_order_app import bag_headers as bh
    cat = {"item_kind": "catalogue", "Product Type": "Hardware",
           "Part Number": "TAF-CLIP-10", "Description": "Bag clips",
           "Quantity": 4, "Unit": "box", "Unit Price": 5.0}
    filt = {"item_kind": "filter", "Filter Type": "V-form", "Quantity": 1}
    filters, bags, total = bh.worksheet_split([filt, cat, dict(BAG)])
    assert filters == [filt] and total == 3
    assert bags[0]["product_type"] == "Other" and bags[0]["part_number"] == "TAF-CLIP-10"
    assert bf.build_label_line(bags[0]) == "4 x Bag clips (box)"
    assert bags[1]["product_type"] == "3-Peak"
