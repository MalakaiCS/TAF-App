"""
The rules an order, a part number and a price are built from.

Every test here is a regression: something in this file went wrong in a
shipped build and reached the people using it. A published release
auto-updates every PC immediately and there is no staging, so the only place
these can be caught is before the installer is built.

Plain functions and plain asserts — run with `python tests/run.py` (no
dependencies) or with pytest.
"""
import datetime

from taf_order_app import part_numbers as pn
from taf_order_app import pricing as pricing
from taf_order_app import stock_usage as stock_usage


# ── Part numbers ────────────────────────────────────────────────────────────

def _item(ftype, media, channel, short=0, long=0, qty=1, area=0):
    it = {"Filter Type": ftype, "Media Type": media, "Channel": channel,
          "Short": short, "Long": long, "Quantity": qty}
    if area:
        it["Stated Square Metres"] = area
    return it


def test_part_number_from_dimensions():
    it = _item("Flat Panel", "Carbon", 25, 150, 750)
    pn.apply_derived_fields(it)
    # 0.15 x 0.75 = 0.1125 m2, charged at the next 0.1
    assert it["Nominal Square Metres"] == 0.2
    assert it["Part Number"] == "FPFCARB25-020"


def test_square_metre_suffix_changes_shape_at_one():
    # The priced catalogue runs 010..090 then 1.0..2.0. Writing 1.8 as "180"
    # produced a code no price could ever match.
    assert pn.sqm_suffix(0.1) == "010"
    assert pn.sqm_suffix(0.9) == "090"
    assert pn.sqm_suffix(1.0) == "1.0"
    assert pn.sqm_suffix(1.8) == "1.8"
    assert pn.sqm_suffix(2.0) == "2.0"


def test_media_codes_match_the_catalogue():
    # Washable is coded W in the catalogue; guessing gave WASH and missed.
    assert pn.default_media_code("Washable") == "W"
    assert pn.default_media_code("WASH") == "W"
    assert pn.default_media_code("Carbon") == "CARB"
    assert pn.default_media_code("G4") == "G4"
    assert pn.default_media_code("180") == "180"
    for grade in ("F5", "F6", "F7", "F8"):
        assert pn.default_media_code(grade) == grade


def test_nominal_area_rounds_up_but_not_past_an_exact_value():
    assert pn.nominal_square_metres(0.1125) == 0.2
    assert pn.nominal_square_metres(0.2) == 0.2        # not 0.3
    assert pn.nominal_square_metres(0.0) == 0.0


def test_area_can_come_from_a_stated_figure():
    it = _item("Flat Panel", "G4", 25, area=0.3)
    pn.apply_derived_fields(it)
    assert it["Part Number"] == "FPFG425-030"


def test_no_part_number_rather_than_half_a_one():
    assert pn.part_number(_item("Flat Panel", "G4", 0, 100, 100)) == ""
    assert pn.part_number(_item("Flat Panel", "G4", 25, 0, 0)) == ""
    assert pn.part_number(_item("", "G4", 25, 100, 100)) == ""


# ── Filter types ────────────────────────────────────────────────────────────

def test_wording_on_an_order_is_read_as_what_it_means():
    # "V Filter" on a purchase order came through as an unknown filter type.
    for written in ("V Filter", "V-Filter", "vee bank", "Pleated Panel",
                    "pleated panel filter", "V-form"):
        assert pn.canonical_filter_type(written) == "V-form", written
    for written in ("Panel Filter", "flat panel", "Filter Pad"):
        assert pn.canonical_filter_type(written) == "Flat Panel", written
    assert pn.canonical_filter_type("fly screen") == "Flyscreen"
    assert pn.canonical_filter_type("stepped") == "Stepped Filter"
    assert pn.canonical_filter_type("something else entirely") == ""


def test_forty_five_and_fifty_millimetres_are_always_vform():
    assert pn.filter_type_for_thickness(45) == "V-form"
    assert pn.filter_type_for_thickness(50) == "V-form"
    assert pn.filter_type_for_thickness(10) == "Flyscreen"
    assert pn.filter_type_for_thickness(20) == "Flat Panel"
    assert pn.filter_type_for_thickness(0) == ""


def test_a_stepped_filter_is_always_fifty_millimetres():
    it = _item("stepped filter", "", 40, 535, 535)
    assert pn.resolve_filter_type(it) == "Stepped Filter"
    assert it["Channel"] == pn.STEPPED_THICKNESS == 50
    pn.apply_media_rules(it, ["G4", "180"])
    assert it["Media Type"] == "180"
    pn.apply_derived_fields(it)
    assert it["Part Number"] == "STPPFW50-030"


def test_a_flyscreen_in_emesh_takes_an_m():
    it = _item("Flyscreen", "E-MESH", 10, 500, 500)
    pn.apply_derived_fields(it)
    assert it["Part Number"] == "FPF09-030-M"


def test_a_header_is_coded_as_the_flat_panel_it_is():
    it = _item("Header", "G4", 25, 610, 610)
    pn.apply_derived_fields(it)
    assert it["Part Number"] == "FPFG425-040"


def test_a_correction_beats_the_built_in_wording_table():
    learned = {pn.wording_key("Panel"): "V-form"}
    assert pn.canonical_filter_type("Panel", learned=learned) == "V-form"


def test_media_defaults_and_unknown_grades():
    it = _item("Flat Panel", "", 25, 100, 100)
    assert pn.apply_media_rules(it, ["G4"]) == ""
    assert it["Media Type"] == "G4"                    # unstated means G4
    it = _item("Flat Panel", "MERV13", 25, 100, 100)
    assert pn.apply_media_rules(it, ["G4", "F5"]) == "MERV13"   # ask a human
    it = _item("Flat Panel", "MERV13", 25, 100, 100)
    learned = {pn.wording_key("MERV13"): "F5"}
    assert pn.apply_media_rules(it, ["G4", "F5"], learned) == ""
    assert it["Media Type"] == "F5"


def test_header_panel_sizes_for_a_bag():
    assert pn.header_panel_for_bag(595, 595) == (610, 610, 25)
    assert pn.header_panel_for_bag(610, 610) == (630, 630, 25)
    assert pn.header_panel_for_bag(595, 595, half_size=True) == (610, 305, 25)
    assert pn.header_panel_for_bag(500, 500) is None   # invent nothing


# ── Prices ──────────────────────────────────────────────────────────────────

PRICES = {"FPFG425-020": 27.0, "PPFG450-040": 45.0, "FPFG425-1.2": 61.0}


def test_a_listed_price_wins():
    it = _item("Flat Panel", "G4", 25, 150, 750, qty=4)
    pn.apply_derived_fields(it)
    unit, source = pricing.price_for_item(it, PRICES)
    assert (unit, source) == (27.0, "list")


def test_a_rate_per_square_metre_is_the_fallback():
    it = _item("Flyscreen", "GREY", 10, 500, 500)
    pn.apply_derived_fields(it)
    rates = {pricing._rate_key("Flyscreen", "GREY"): 30.0}
    unit, source = pricing.price_for_item(it, PRICES, rates)
    assert source == "rate" and unit == 9.0        # 0.3 m2 x 30


def test_an_unpriced_line_is_never_guessed_at():
    it = _item("V-form", "G4", 95, 595, 595)
    pn.apply_derived_fields(it)
    assert pricing.price_for_item(it, PRICES) == (0.0, "")
    line = pricing.quote_lines([it], PRICES)[0]
    assert line["source"] == "" and line["line_total"] == 0
    assert line["reason"]                          # and it says why


def test_totals_exclude_what_could_not_be_priced():
    priced = _item("Flat Panel", "G4", 25, 150, 750, qty=2)
    unpriced = _item("V-form", "G4", 95, 595, 595, qty=5)
    for it in (priced, unpriced):
        pn.apply_derived_fields(it)
    lines = pricing.quote_lines([priced, unpriced], PRICES)
    totals = pricing.quote_totals(lines)
    assert totals["subtotal"] == 54.0              # 2 x 27, nothing invented
    assert totals["gst"] == 5.4 and totals["total"] == 59.4
    assert len(pricing.unpriced(lines)) == 1


# ── Reading a price spreadsheet ─────────────────────────────────────────────

XERO_HEADER = ["ItemCode", "ItemName", "PurchasesDescription",
               "PurchasesUnitPrice", "PurchasesAccount", "SalesDescription",
               "SalesUnitPrice", "SalesAccount"]


def test_the_sales_price_column_is_the_one_used():
    # A Xero item export carries both, and the purchases column is empty.
    # Taking the first heading containing "price" landed on the empty one and
    # the whole import came back with nothing.
    cols = pricing._pick_columns(XERO_HEADER)
    assert XERO_HEADER[cols["price"]] == "SalesUnitPrice"
    assert XERO_HEADER[cols["desc"]] == "SalesDescription"
    assert XERO_HEADER[cols["code"]] == "ItemCode"
    assert XERO_HEADER[cols["name"]] == "ItemName"


def test_the_price_column_is_checked_against_the_rows_beneath_it():
    rows = [[f"FPFG425-0{n}0", "name", "", None, "", "desc", 20 + n, "200"]
            for n in range(1, 6)]
    cands = pricing._candidates(XERO_HEADER)
    best = pricing._best_price_column(rows, 0, cands["code"][0], cands["price"])
    assert XERO_HEADER[best] == "SalesUnitPrice"


def test_a_paragraph_is_not_a_column_heading():
    # A Read Me sheet mentioning "code", "price" and "description" in prose
    # was being read as a header row.
    prose = ("Codes below 1.0m2 retain -010 through -090; sales prices are "
             "estimates and the sales descriptions leave Size blank.")
    assert pricing._pick_columns([prose, prose]) is None


def test_money_is_read_out_of_however_it_is_written():
    assert pricing._money("$12.50") == 12.5
    assert pricing._money(12.5) == 12.5
    assert pricing._money("24") == 24.0
    assert pricing._money("") is None
    assert pricing._money(None) is None
    assert pricing._money("n/a") is None


def test_reasons_tell_a_gap_apart_from_a_bad_line():
    priced = {"PPFG4100-1.0": 10.0, "PPFG4100-2.0": 20.0}
    over = _item("V-form", "G4", 100, 1200, 2000)
    pn.apply_derived_fields(over)
    assert "not at" in pricing.why_unpriced(over, priced)

    stepped = _item("Stepped Filter", "180", 50, 535, 535)
    pn.apply_derived_fields(stepped)
    assert "price list" in pricing.why_unpriced(stepped, priced)

    blank = {"Filter Type": "", "Quantity": 1}
    assert "no filter type" in pricing.why_unpriced(blank, priced)


# ── Xero export ─────────────────────────────────────────────────────────────

def test_xero_rows_carry_the_invoice_fields_on_every_line():
    items = [_item("Flat Panel", "G4", 25, 150, 750, qty=4)]
    pn.apply_derived_fields(items[0])
    lines = pricing.quote_lines(items, PRICES)
    rows = pricing.xero_rows(
        {"Order Number": "PO1", "Date Ordered": "02/09/26", "Job": "J9",
         "Location": "Sunshine Coast"},
        lines, {"legal_name": "Complete Air Supply Pty Ltd"})
    assert len(rows) == 1
    row = rows[0]
    assert row["*ContactName"] == "Complete Air Supply Pty Ltd"
    assert row["*InvoiceNumber"] == "PO1"
    assert row["*InvoiceDate"] == "02/09/2026"
    assert row["*DueDate"] == "02/10/2026"          # 30 days when none given
    assert row["InventoryItemCode"] == "FPFG425-020"
    assert row["*Quantity"] == "4" and row["*UnitAmount"] == "27.00"
    assert set(row) == set(pricing.XERO_COLUMNS)     # Xero rejects extras


def test_invoice_descriptions_stay_ascii():
    it = _item("Flat Panel", "G4", 25, 150, 750)
    pn.apply_derived_fields(it)
    pricing.describe_item(it).encode("ascii")        # raises if it isn't


# ── Stock ───────────────────────────────────────────────────────────────────

STOCK = [
    {"id": "s1", "sku": "FPFG425-020", "name": "Flat panel G4 25mm",
     "product_type": "Panel Filter", "unit": "each"},
    {"id": "s2", "sku": "G4", "name": "G4 media", "product_type": "Media Roll",
     "unit": "m2"},
    {"id": "s3", "sku": "GREY", "name": "Grey mesh", "product_type": "Media Roll",
     "unit": "metre"},
]


def test_a_finished_item_is_deducted_by_its_part_number():
    it = _item("Flat Panel", "G4", 25, 150, 750, qty=4)
    pn.apply_derived_fields(it)
    plan = stock_usage.plan_deductions([it], STOCK, "PO1")
    assert len(plan["deduct"]) == 1
    row = plan["deduct"][0]
    assert row["item"]["id"] == "s1" and row["quantity"] == 4
    assert not plan["unmatched"]


def test_media_is_deducted_by_area_when_it_is_kept_in_square_metres():
    it = _item("V-form", "G4", 50, 595, 595, qty=2)
    pn.apply_derived_fields(it)
    plan = stock_usage.plan_deductions([it], STOCK, "PO1")
    assert plan["deduct"][0]["item"]["id"] == "s2"
    assert plan["deduct"][0]["quantity"] == 0.8      # 2 x 0.4 m2


def test_media_kept_in_metres_is_reported_not_guessed_at():
    it = _item("Flyscreen", "GREY", 10, 500, 500, qty=3)
    pn.apply_derived_fields(it)
    plan = stock_usage.plan_deductions([it], STOCK, "PO1")
    assert not plan["deduct"]
    assert "not m2" in plan["unmatched"][0]["why"]
    assert stock_usage.find_unit_problem(STOCK)


def test_a_line_matching_nothing_is_reported():
    it = _item("V-form", "F7", 95, 595, 595, qty=1)
    pn.apply_derived_fields(it)
    plan = stock_usage.plan_deductions([it], STOCK, "PO1")
    assert not plan["deduct"] and len(plan["unmatched"]) == 1


def test_a_failing_deduction_does_not_stop_the_others():
    calls = []

    def adjust(item_id, kind, qty, notes):
        calls.append(item_id)
        if item_id == "s1":
            raise RuntimeError("network")

    items = []
    for spec in (("Flat Panel", "G4", 25, 150, 750, 4),
                 ("V-form", "G4", 50, 595, 595, 2)):
        it = _item(*spec)
        pn.apply_derived_fields(it)
        items.append(it)
    plan = stock_usage.plan_deductions(items, STOCK, "PO1")
    assert stock_usage.apply_plan(plan, adjust) == 1
    assert len(calls) == 2


# ── Nearest-thickness pricing ───────────────────────────────────────────────
# A 48mm V-form is common on purchase orders and has no row in a catalogue
# priced in 5mm steps. It is the same filter as the 50mm, so it is priced as
# one — and always said to be.

def test_a_near_thickness_is_priced_as_the_size_it_matches():
    prices = {"PPFG450-040": 45.0, "PPFG445-040": 44.0}
    it = _item("V-form", "G4", 48, 595, 595)
    pn.apply_derived_fields(it)
    unit, source = pricing.price_for_item(it, prices)
    assert (unit, source) == (45.0, "near")          # 50 is nearer than 45
    assert it["_priced_as"] == "PPFG450-040"


def test_a_near_price_says_so_rather_than_passing_as_listed():
    prices = {"PPFG450-040": 45.0}
    it = _item("V-form", "G4", 48, 595, 595)
    pn.apply_derived_fields(it)
    line = pricing.quote_lines([it], prices)[0]
    assert line["source"] == "near"
    assert "Priced as PPFG450-040" == pricing.source_label(line)
    exact = _item("Flat Panel", "G4", 25, 150, 750)
    pn.apply_derived_fields(exact)
    assert pricing.source_label(pricing.quote_lines([exact], PRICES)[0]) == "Price list"


def test_nearest_pricing_will_not_reach_across_a_real_size_difference():
    prices = {"PPFG450-040": 45.0}
    it = _item("V-form", "G4", 40, 595, 595)         # 10mm away is a different filter
    pn.apply_derived_fields(it)
    assert pricing.price_for_item(it, prices) == (0.0, "")


def test_nearest_pricing_never_crosses_media_or_area():
    prices = {"PPFF750-040": 69.0, "PPFG450-030": 40.0}
    it = _item("V-form", "G4", 48, 595, 595)          # 0.4 m2, G4
    pn.apply_derived_fields(it)
    assert pricing.price_for_item(it, prices) == (0.0, "")


# ── Freight tracking ────────────────────────────────────────────────────────

def test_a_tracking_link_is_built_from_the_carrier():
    from taf_order_app import db
    url = db.tracking_url("TNT", "1234567890")
    assert "1234567890" in url and url.startswith("https://")


def test_a_link_typed_in_by_hand_wins():
    # Carriers move their tracking pages; what someone actually checked beats
    # a template that may have gone stale.
    from taf_order_app import db
    assert db.tracking_url("TNT", "123", "https://example/track") == \
        "https://example/track"


def test_no_link_rather_than_a_broken_one():
    from taf_order_app import db
    assert db.tracking_url("TNT", "") == ""
    assert db.tracking_url("", "123") == ""
    assert db.tracking_url("Other", "123") == ""      # no tracking page known


def test_a_consignment_number_is_escaped_into_the_url():
    from taf_order_app import db
    url = db.tracking_url("Startrack", "AB 12/34")
    assert " " not in url and "AB%2012%2F34" in url


# ── Our own order numbers ───────────────────────────────────────────────────
# For customers who ring up without a purchase order number. Kept apart from
# invoice numbering on purpose.

def test_our_order_numbers_look_the_way_they_should():
    assert pn.supplied_order_number(1) == "TAF-ON-0001"
    assert pn.supplied_order_number(42) == "TAF-ON-0042"
    assert pn.supplied_order_number(9999) == "TAF-ON-9999"


def test_they_get_longer_rather_than_wrapping():
    # A number that repeats would be far worse than a five-digit one.
    assert pn.supplied_order_number(10000) == "TAF-ON-10000"
    assert pn.supplied_order_number(123456) == "TAF-ON-123456"


def test_a_bad_counter_value_produces_nothing():
    for bad in (0, -1, None, "", "x"):
        assert pn.supplied_order_number(bad) == ""


def test_ours_are_recognised_however_they_are_typed():
    for text in ("TAF-ON-0001", "taf-on-0001", " TAF-ON-0001 ", "Taf-On-0042"):
        assert pn.is_supplied_order_number(text), text
    for text in ("PO1234", "TAF-0001", "TAF-ON-", "TAFON0001", "", "TAF-ON-AB"):
        assert not pn.is_supplied_order_number(text), text


def test_the_counter_can_be_read_back_out():
    assert pn.supplied_order_value("TAF-ON-0042") == 42
    assert pn.supplied_order_value("taf-on-10000") == 10000
    assert pn.supplied_order_value("PO1234") == 0


def test_ours_are_tidied_and_a_customers_is_left_alone():
    # Ours are normalised so TAF-ON-7 and taf-on-0007 are the same order.
    assert pn.normalise_order_number("taf-on-0007") == "TAF-ON-0007"
    assert pn.normalise_order_number("  TAF-ON-0007 ") == "TAF-ON-0007"
    # Theirs is their reference, not ours to reformat.
    for theirs in ("po 1234", "4500/A", "j-99  b", "0001"):
        assert pn.normalise_order_number(theirs) == theirs.strip()


def test_our_numbers_never_collide_with_a_part_number():
    # Both appear on a worksheet; neither format may be mistaken for the other.
    assert not pn.is_supplied_order_number("FPFG425-020")
    assert pn.canonical_filter_type("TAF-ON-0001") == ""
