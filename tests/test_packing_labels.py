"""Packing plans, wrap-page codes, wrap weights and delivery labels."""
from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import calc_settings as cs              # noqa: E402
from taf_order_app import delivery_labels as dl            # noqa: E402
from taf_order_app import order_packing as op              # noqa: E402
from taf_order_app import packing as pk                    # noqa: E402

BASE = cs.BASE_ADDRESS_DEFAULT

ORDER = {
    "customer_name": "Complete Air Supply - Tweed Heads",
    "address_line_1": "3A/38 Enterprise Avenue", "address_line_2": "",
    "suburb": "Tweed Heads", "state": "NSW", "postcode": "2486",
    "contact_name": "Michael", "contact_phone": "07 5513 1044",
    "order_number": "57920", "job_number": None,
    "items": [
        {"quantity": 10, "width_mm": 500, "height_mm": 600, "depth_mm": 50,
         "wrap_quantities": [5, 5]},
        {"quantity": 2, "width_mm": 500, "height_mm": 600, "depth_mm": 90,
         "wrap_quantities": [2]},
    ],
}


def order(**changes):
    o = copy.deepcopy(ORDER)
    o.update(changes)
    return o


def refused(fn, *a, **k):
    try:
        fn(*a, **k)
    except (pk.PackingError, dl.LabelError):
        return True
    return False


# ── Wrap-page numbering ─────────────────────────────────────────────────────

def test_one_size_two_wraps():
    labs = dl.build(order(items=[{"quantity": 10, "width_mm": 600,
                                  "height_mm": 600, "depth_mm": 90,
                                  "wrap_quantities": [5, 5]}]), BASE)
    assert [(l["filter_size"], l["wrap_quantity"], l["line_quantity"],
             l["wrap_page"]) for l in labs] == [
        ("600 × 600 × 90 mm", 5, 10, "1 of 2"),
        ("600 × 600 × 90 mm", 5, 10, "2 of 2")]


def test_mixed_sizes():
    labs = dl.build(order(), BASE)
    assert [(l["filter_size"], l["wrap_quantity"], l["line_quantity"],
             l["wrap_page"]) for l in labs] == [
        ("500 × 600 × 50 mm", 5, 10, "1A/2"),
        ("500 × 600 × 50 mm", 5, 10, "1B/2"),
        ("500 × 600 × 90 mm", 2, 2, "2/2")]


def test_a_single_wrap_is_1_of_1():
    labs = dl.build(order(items=[{"quantity": 3, "width_mm": 1,
                                  "height_mm": 1, "depth_mm": 1,
                                  "wrap_quantities": [3]}]), BASE)
    assert [l["wrap_page"] for l in labs] == ["1 of 1"]


def test_lines_that_match_are_not_merged():
    same = {"quantity": 2, "width_mm": 500, "height_mm": 500, "depth_mm": 50,
            "wrap_quantities": [2]}
    labs = dl.build(order(items=[same, dict(same)]), BASE)
    assert [l["wrap_page"] for l in labs] == ["1/2", "2/2"]


def test_lettering_beyond_z():
    assert [pk.letters(n) for n in (1, 26, 27, 28, 52, 53, 702, 703)] == \
        ["A", "Z", "AA", "AB", "AZ", "BA", "ZZ", "AAA"]
    codes = pk.wrap_codes([30, 1])[0]
    assert codes[25] == "1Z/2" and codes[26] == "1AA/2" and codes[29] == "1AD/2"


def test_numbering_is_business_numbering_not_pdf_pages():
    labs = dl.build(order(), BASE)
    assert all("of 3" not in l["wrap_page"] for l in labs)


def test_a_batch_resets_per_order_and_a_reprint_keeps_its_code():
    a = dl.build(order(), BASE)
    b = dl.build(order(items=[{"quantity": 4, "width_mm": 1, "height_mm": 1,
                               "depth_mm": 1, "max_per_wrap": 2}]), BASE)
    assert [l["wrap_page"] for l in b] == ["1 of 2", "2 of 2"]
    assert [l["wrap_page"] for l in a][0] == "1A/2"


# ── Splitting ───────────────────────────────────────────────────────────────

def test_twelve_at_five_is_five_five_two():
    assert pk.split(12, 5) == [5, 5, 2]
    labs = dl.build(order(items=[{"quantity": 12, "width_mm": 1,
                                  "height_mm": 1, "depth_mm": 1,
                                  "max_per_wrap": 5}]), BASE)
    assert [l["wrap_quantity"] for l in labs] == [5, 5, 2]
    assert [l["wrap_page"] for l in labs] == ["1 of 3", "2 of 3", "3 of 3"]


def test_wrap_quantities_are_checked():
    item = {"quantity": 10, "width_mm": 1, "height_mm": 1, "depth_mm": 1}
    for bad in ([5, 4], [5, 6], [5, 0, 5], [5, -5, 10], [2.5, 7.5],
                ["5", "5"], [], [True] * 10):
        assert refused(dl.build, order(items=[dict(item,
                       wrap_quantities=bad)]), BASE), bad
    for bad in (0, -1, 2.5, "5", True):
        assert refused(dl.build, order(items=[dict(item,
                       max_per_wrap=bad)]), BASE), bad
    both = dict(item, wrap_quantities=[5, 5], max_per_wrap=5)
    assert refused(dl.build, order(items=[both]), BASE)


def test_five_is_not_a_universal_limit():
    labs = dl.build(order(items=[{"quantity": 20, "width_mm": 1,
                                  "height_mm": 1, "depth_mm": 1,
                                  "wrap_quantities": [10, 10]}]), BASE)
    assert [l["wrap_quantity"] for l in labs] == [10, 10]


# ── Weights on labels ───────────────────────────────────────────────────────

def test_measured_weights_per_wrap_and_their_precision():
    o = order()
    o["items"][0]["wrap_weights_kg"] = [3.2, 3.45]
    labs = dl.build(o, BASE)
    assert [l["weight_kg"] for l in labs] == ["3.2", "3.45", ""]
    assert labs[0]["weight_source"] == "measured"


def test_a_measured_weight_beats_a_calculated_one_and_adds_no_wrapping():
    s = cs.defaults()
    s["packaging"] = {"confirmed": True, "base_kg": 0.25}
    o = order()
    o["items"][0].update(complete_filter_weight_kg_per_filter=1.0,
                         wrap_weights_kg=[4.8, None])
    labs = dl.build(o, BASE, s)
    assert labs[0]["weight_kg"] == "4.8" and labs[0]["weight_source"] == \
        "measured"
    # 5 x 1.0 + 0.25 = 5.25, rounded up once, on the whole wrap.
    assert labs[1]["weight_kg"] == "5.3"
    assert labs[1]["weight_raw_kg"] == 5.25
    assert labs[1]["weight_source"] == "calculated"


def test_a_remainder_is_weighed_as_itself():
    s = cs.defaults()
    s["packaging"] = {"confirmed": True, "base_kg": 0.2, "per_filter_kg": 0.01}
    o = order(items=[{"quantity": 12, "width_mm": 1, "height_mm": 1,
                      "depth_mm": 1, "max_per_wrap": 5,
                      "complete_filter_weight_kg_per_filter": 1.5}])
    labs = dl.build(o, BASE, s)
    assert [l["weight_raw_kg"] for l in labs] == [
        1.5 * 5 + 0.2 + 0.05, 1.5 * 5 + 0.2 + 0.05, 1.5 * 2 + 0.2 + 0.02]


def test_unknown_weights_print_a_writing_space():
    s = cs.defaults()
    s["packaging"] = {"confirmed": False}
    o = order()
    o["items"][0]["complete_filter_weight_kg_per_filter"] = 1.0
    labs = dl.build(o, BASE, s)             # wrapping not confirmed
    assert labs[0]["weight_kg"] == ""
    assert "the wrapping's weight" in labs[0]["weight_missing"]
    o["items"][0].pop("complete_filter_weight_kg_per_filter")
    s["packaging"] = {"confirmed": True, "base_kg": 0}
    labs = dl.build(o, BASE, s)
    assert labs[0]["weight_kg"] == ""
    assert "a complete filter weight" in labs[0]["weight_missing"]


def test_zero_wrapping_only_when_confirmed():
    assert pk.packaging_kg({"confirmed": False, "base_kg": 0}, 3) is None
    assert pk.packaging_kg(None, 3) is None
    assert pk.packaging_kg({"confirmed": True, "base_kg": 0}, 3) == 0
    s = cs.defaults()
    s["packaging"] = {"confirmed": False}
    o = order()
    o["items"][0].update(complete_filter_weight_kg_per_filter=1.0,
                         packaging_weights_kg=[0, None])
    labs = dl.build(o, BASE, s)
    assert labs[0]["weight_kg"] == "5.0" and labs[1]["weight_kg"] == ""
    # By default the wrapping counts as 0 kg until it is weighed, so every
    # wrap with a known filter weight gets a weight on its label.
    labs = dl.build(o, BASE)
    assert labs[0]["weight_kg"] == "5.0" and labs[1]["weight_kg"] == "5.0"


def test_weight_arrays_must_line_up():
    o = order()
    o["items"][0]["wrap_weights_kg"] = [3.2]
    assert refused(dl.build, o, BASE)
    for bad in (-1, 0, float("nan"), "3.2", True):
        o["items"][0]["wrap_weights_kg"] = [bad, None]
        assert refused(dl.build, o, BASE), bad
    o["items"][0]["wrap_weights_kg"] = None
    o["items"][0]["packaging_weights_kg"] = [-0.1, None]
    assert refused(dl.build, o, BASE)


def test_shipping_rounding_happens_once_on_the_total():
    assert op.round_package(5.2500001, "up_0.1") == "5.3"
    assert op.round_package(5.3, "up_0.1") == "5.3"          # not 5.4
    assert op.round_package(0.30000000000000004, "up_0.1") == "0.3"
    assert op.round_package(5.25, "none") == "5.250"
    s = cs.defaults()
    s["shipping_rounding"] = "up_0.1"
    s["packaging"] = {"confirmed": True, "base_kg": 0.04}
    o = order(items=[{"quantity": 3, "width_mm": 1, "height_mm": 1,
                      "depth_mm": 1, "wrap_quantities": [3],
                      "complete_filter_weight_kg_per_filter": 1.01}])
    lab = dl.build(o, BASE, s)[0]
    # 3.03 + 0.04 = 3.07 -> 3.1. Rounding each filter first would give 3.4.
    assert lab["weight_kg"] == "3.1"


# ── The label's own fields ──────────────────────────────────────────────────

def test_job_number_or_na():
    for blank in (None, "", "   ", "\t"):
        assert dl.build(order(job_number=blank), BASE)[0]["job_number"] \
            == "N/A"
    o = order()
    o.pop("job_number")
    assert dl.build(o, BASE)[0]["job_number"] == "N/A"
    assert dl.build(order(job_number="J-0042"), BASE)[0]["job_number"] == \
        "J-0042"
    # Never the order number in its place.
    assert dl.build(order(job_number=None), BASE)[0]["job_number"] != "57920"


def test_references_phones_and_postcodes_stay_text():
    assert refused(dl.build, order(postcode=870), BASE)
    assert refused(dl.build, order(order_number=57920), BASE)
    assert refused(dl.build, order(contact_phone=755131044), BASE)
    lab = dl.build(order(postcode="0870", state="NT",
                         contact_phone="0800 111 222",
                         order_number="00731"), BASE)[0]
    assert lab["locality"].endswith("0870")
    assert lab["contact_phone"] == "0800 111 222"
    assert lab["order_number"] == "00731"


def test_removed_fields_are_refused_not_printed():
    for key in ("fax", "purchase_order_number", "dispatch_date",
                "delivery_instructions"):
        assert refused(dl.build, order(**{key: "x"}), BASE), key
    lab = dl.build(order(), BASE)[0]
    for key in ("fax", "purchase_order_number", "dispatch_date",
                "delivery_instructions"):
        assert key not in lab


def test_an_empty_second_address_line_is_dropped():
    assert dl.build(order(), BASE)[0]["address_lines"] == \
        ["3A/38 Enterprise Avenue"]
    lab = dl.build(order(address_line_2="Rear dock"), BASE)[0]
    assert lab["address_lines"] == ["3A/38 Enterprise Avenue", "Rear dock"]
    lab = dl.build(order(contact_name="", contact_phone=""), BASE)[0]
    assert lab["contact_name"] == "" and lab["contact_phone"] == ""


def test_the_base_address_is_the_setting_read_once():
    labs = dl.build(order(), "PO Box 1, Somewhere QLD 4000")
    assert {l["from_address"] for l in labs} == {"PO Box 1, Somewhere QLD 4000"}
    s = cs.merge({"company": {"value": {"base_address": "New place"},
                              "version": 2}})
    assert cs.base_address(s) == "New place"
    assert cs.base_address(cs.defaults()) == \
        "Unit 1/19 Tradelink Road, Hillcrest Queensland 4118 Australia"
    src = (ROOT / "taf_order_app" / "delivery_labels.py").read_text()
    assert "Tradelink" not in src, "the address is hard-coded in the layout"


def test_states_are_normalised_or_refused():
    assert dl.build(order(state="Queensland"), BASE)[0]["locality"] == \
        "Tweed Heads  QLD  2486"
    assert refused(dl.build, order(state="Ontario"), BASE)
    assert refused(dl.build, order(postcode="248"), BASE)


# ── Automatic packing ───────────────────────────────────────────────────────

def test_exactly_ten_kilograms_is_allowed_and_over_splits():
    fixed = {"confirmed": True, "base_kg": 0.0}
    assert pk.weight_capacity(2.0, fixed, 99) == 5
    assert pk.weight_capacity(2.0000001, fixed, 99) == 4
    p = pk.propose(12, 2.0, fixed)
    assert [w["quantity"] for w in p["wraps"]] == [5, 5, 2]
    assert p["wraps"][0]["raw_kg"] == 10.0 and p["compliant"]


def test_packaging_counts_toward_the_limit():
    assert pk.weight_capacity(2.0, {"confirmed": True, "base_kg": 0.5},
                              99) == 4
    per = {"confirmed": True, "base_kg": 0.1, "per_filter_kg": 0.1}
    # q x 1.9 + 0.1 + 0.1q <= 10  ->  q = 4 (8.1 + .. = 8.5); 5 -> 10.1
    assert pk.weight_capacity(1.9, per, 99) == 4
    table = {"confirmed": True, "by_quantity": {"1": 0.5, "2": 0.5,
                                                "3": 1.5}}
    assert pk.weight_capacity(3.0, table, 3) == 2


def test_the_sixty_filter_example():
    s = cs.defaults()
    item = {"Filter Type": "V-form", "Quantity": 60, "Short": 412,
            "Long": 412, "Channel": 90, "Media Type": "G4"}
    ev = op.evaluate_line(item, s)
    assert [w["quantity"] for w in ev["plan"]["wraps"]] == [5] * 12
    # Weighed from the supplied rates: well under 10 kg, so the handling
    # limit of five decides.
    assert ev["status"] == "ok" and ev["unit_kg"] * 5 < 10
    out = op.order_wraps([dict(item, Packing=ev["plan"])], s)
    codes = [w["code"] for w in out["lines"][0]["wraps"]]
    assert codes == [f"{i} of 12" for i in range(1, 13)]
    # A known weight that only allows four wins over the handling five.
    p = pk.propose(60, 2.4, {"confirmed": True, "base_kg": 0.2}, 5)
    assert [w["quantity"] for w in p["wraps"]] == [4] * 15


def test_handling_can_cut_below_the_weight_limit():
    p = pk.propose(9, 0.5, {"confirmed": True, "base_kg": 0}, 4)
    assert p["limits"]["weight"] == 9 and p["capacity"] == 4
    assert [w["quantity"] for w in p["wraps"]] == [4, 4, 1]
    staff = pk.propose(9, 0.5, {"confirmed": True, "base_kg": 0}, 4, 3)
    assert staff["capacity"] == 3


def test_unknown_weight_needs_a_check_and_nothing_known_needs_input():
    p = pk.propose(20, None, None, 5)
    assert p["status"] == "needs_weight_check" and not p["compliant"]
    assert [w["quantity"] for w in p["wraps"]] == [5, 5, 5, 5]
    assert all(w["raw_kg"] is None for w in p["wraps"])
    # Nothing known at all: still planned, five a wrap unless set, and the
    # wraps flagged for weighing - never left waiting for somebody.
    none = pk.propose(20, None, None)
    assert none["status"] == "needs_weight_check"
    assert [w["quantity"] for w in none["wraps"]] == [5, 5, 5, 5]
    four = pk.propose(9, None, None, fallback_max=4)
    assert [w["quantity"] for w in four["wraps"]] == [4, 4, 1]
    one = pk.propose(1, None, None)
    assert [w["quantity"] for w in one["wraps"]] == [1]


def test_an_item_too_heavy_on_its_own():
    p = pk.propose(3, 10.5, {"confirmed": True, "base_kg": 0.1})
    assert p["status"] == "single_item_exception"
    assert [w["quantity"] for w in p["wraps"]] == [1, 1, 1]
    assert all(w["over_limit"] for w in p["wraps"]) and not p["compliant"]


def test_a_manual_limit_cannot_let_an_overweight_bundle_through():
    check = pk.check_plan([{"quantity": 6}, {"quantity": 4}], 10, 2.0,
                          {"confirmed": True, "base_kg": 0})
    assert not check["ok"]
    assert any("12.000 kg" in i for i in check["issues"])
    assert [w["quantity"] for w in check["proposal"]["wraps"]] == [5, 5]


def test_a_weighed_bundle_over_the_limit_is_flagged():
    check = pk.check_plan([{"quantity": 5, "measured_weight_kg": 10.2},
                           {"quantity": 5}], 10)
    assert any("repack and reweigh" in i for i in check["issues"])


# ── Saved plans and history ─────────────────────────────────────────────────

def test_wrap_ids_are_stable_until_the_wraps_change():
    rows = [{"quantity": 5}, {"quantity": 5}]
    first = pk.make_plan(rows, "manual")
    first = pk.record_weight(first, first["wraps"][0]["id"], "4.20", "Sam")
    again = pk.make_plan(rows, "manual", previous=first)
    assert [w["id"] for w in again["wraps"]] == [w["id"] for w in first["wraps"]]
    assert again["wraps"][0]["measured_weight_kg"] == 4.2
    changed = pk.make_plan([{"quantity": 4}, {"quantity": 4},
                            {"quantity": 2}], "manual", previous=first)
    assert not {w["id"] for w in changed["wraps"]} & \
        {w["id"] for w in first["wraps"]}
    assert all(w["measured_weight_kg"] is None for w in changed["wraps"])
    assert changed["history"][-1]["wraps"][0]["measured_weight_text"] == "4.20"


def test_a_reprint_of_one_wrap_keeps_its_code():
    s = cs.defaults()
    items = [{"Filter Type": "V-form", "Quantity": 10, "Short": 500,
              "Long": 600, "Channel": 50, "Media Type": "G4"},
             {"Filter Type": "V-form", "Quantity": 2, "Short": 500,
              "Long": 600, "Channel": 90, "Media Type": "G4"}]
    items[0]["Packing"] = op.set_manual(items[0], [5, 5])
    items[1]["Packing"] = op.set_manual(items[1], [2])
    order_row = {"order_number": "57920", "header": {"Job": ""},
                 "items": items}
    cust = {"name": "Complete Air Supply - Tweed Heads",
            "delivery_address1": "3A/38 Enterprise Avenue",
            "delivery_city": "Tweed Heads", "delivery_state": "NSW",
            "delivery_postcode": "2486", "phone": "07 5513 1044"}
    all_ = dl.build_for_order(order_row, cust, s, BASE)
    assert [l["wrap_page"] for l in all_] == ["1A/2", "1B/2", "2/2"]
    one = dl.build_for_order(order_row, cust, s, BASE,
                             only_wrap_ids=[all_[1]["wrap_id"]])
    assert [l["wrap_page"] for l in one] == ["1B/2"]


# ── Office packing plans and the worksheet wording ──────────────────────────

def test_instruction_wording():
    assert pk.instruction([3, 3, 3]) == "(Wrap 3 Filters x 3)"
    assert pk.instruction([10, 10]) == "(Wrap 10 Filters x 2)"
    assert pk.instruction([5] * 12) == "(Wrap 5 Filters x 12)"
    assert pk.instruction([5, 5, 2]) == \
        "(Wrap 5 Filters x 2 + Wrap 2 Filters x 1)"
    assert sum([3, 3, 3]) == 9


def test_a_manual_plan_survives_save_and_reload():
    s = cs.defaults()
    item = {"Filter Type": "Flat Panel", "Quantity": 20, "Short": 500,
            "Long": 500, "Channel": 25, "Media Type": "G4"}
    item["Packing"] = op.set_manual(item, [10, 10], by="Office")
    saved = json.loads(json.dumps(item))                  # through the db
    items, changed = op.refresh_items([saved], s, by="Floor")
    # The plan is left exactly as the office set it (the line's weight is
    # kept alongside it, which is the only thing added).
    assert items[0]["Packing"] == saved["Packing"]
    ev = op.evaluate_line(items[0], s)
    assert ev["plan"]["mode"] == "manual"
    assert [w["quantity"] for w in ev["plan"]["wraps"]] == [10, 10]
    assert ev["instructions"] == ["(Wrap 10 Filters x 2)"]


def test_manual_plans_are_not_overwritten_and_conflicts_stay_visible():
    s = cs.defaults()
    item = {"Filter Type": "V-form", "Quantity": 10, "Short": 412,
            "Long": 412, "Channel": 90, "Media Type": "G4"}
    item["Packing"] = op.set_manual(item, [10])
    items, changed = op.refresh_items([item], s)
    assert items[0]["Packing"] == item["Packing"]
    ev = op.evaluate_line(items[0], s)
    assert [w["quantity"] for w in ev["plan"]["wraps"]] == [10]
    assert ev["status"] == "conflict"
    assert any("handled 5 at most" in i for i in ev["issues"])
    assert [w["quantity"] for w in ev["proposal"]["wraps"]] == [5, 5]


def test_manual_plans_must_add_up():
    item = {"Quantity": 9}
    for bad in ([3, 3], [3, 3, 4], [0, 9], [4.5, 4.5]):
        assert refused(op.set_manual, item, bad), bad


def test_area_groups_keep_their_totals_and_their_wraps():
    s = cs.defaults()
    item = {"Filter Type": "Flat Panel", "Quantity": 20, "Short": 500,
            "Long": 500, "Channel": 25, "Media Type": "G4"}
    groups = [{"name": "Area A", "quantity": 10},
              {"name": "Area B", "quantity": 10}]
    item["Packing"] = op.set_manual(item, [10, 10], groups=groups,
                                    group_of_wrap=["Area A", "Area B"])
    ev = op.evaluate_line(item, s)
    assert ev["instructions"] == ["Area A: 10 filters (Wrap 10 Filters x 1)",
                                  "Area B: 10 filters (Wrap 10 Filters x 1)"]
    # Split further by a limit, every wrap stays in its area.
    auto = op.set_automatic(item, s, max_per_wrap=4, groups=groups)
    by_area = {}
    for w in auto["wraps"]:
        by_area.setdefault(w["group"], []).append(w["quantity"])
    assert by_area == {"Area A": [4, 4, 2], "Area B": [4, 4, 2]}
    # Groups do not change the page count: still one line.
    out = op.order_wraps([dict(item, Packing=auto)], s)
    assert out["lines"][0]["wraps"][-1]["code"] == "6 of 6"
    order_row = {"order_number": "1", "header": {}, "items": [
        dict(item, Packing=auto)]}
    cust = {"name": "X", "delivery_address1": "1 St", "delivery_city": "Y",
            "delivery_state": "QLD", "delivery_postcode": "4000"}
    labs = dl.build_for_order(order_row, cust, s, BASE)
    assert [l["group"] for l in labs] == ["Area A"] * 3 + ["Area B"] * 3
    assert refused(op.set_manual, item, [10, 10], groups=[
        {"name": "Area A", "quantity": 12}, {"name": "Area B",
                                             "quantity": 8}],
        group_of_wrap=["Area A", "Area B"])


def test_the_worksheet_the_labels_and_the_plan_agree():
    s = cs.defaults()
    item = {"Filter Type": "V-form", "Quantity": 9, "Short": 500,
            "Long": 600, "Channel": 50, "Media Type": "G4"}
    item["Packing"] = op.set_manual(item, [3, 3, 3])
    ev = op.evaluate_line(item, s)
    order_row = {"order_number": "9", "header": {}, "items": [item]}
    cust = {"name": "X", "delivery_address1": "1 St", "delivery_city": "Y",
            "delivery_state": "QLD", "delivery_postcode": "4000"}
    labs = dl.build_for_order(order_row, cust, s, BASE)
    assert ev["instructions"] == ["(Wrap 3 Filters x 3)"]
    assert len(labs) == 3 and sum(l["wrap_quantity"] for l in labs) == 9
    assert [l["wrap_id"] for l in labs] == \
        [w["id"] for w in item["Packing"]["wraps"]]


# ── The printed sheet ───────────────────────────────────────────────────────

def _pdf_text(path: str) -> str:
    """The text, by pdftotext where it is installed, else by reading
    ReportLab's page streams with the standard library (see test_dockets:
    pypdf's compiled crypto panics on some machines, and "the check did not
    run" must not look like "the check passed")."""
    try:
        out = subprocess.run(["pdftotext", "-layout", path, "-"],
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout
    except Exception:
        pass
    from tests.test_dockets import _pages_without_pypdf
    return "\n\f".join(_pages_without_pypdf(path))


def _page_sizes_mm(path: str):
    raw = Path(path).read_bytes()
    boxes = re.findall(rb"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)"
                       rb"\s+([\d.]+)\s*\]", raw)
    return [(round((float(c) - float(a)) / 72 * 25.4),
             round((float(d) - float(b)) / 72 * 25.4)) for a, b, c, d in boxes]


def test_one_landscape_a4_page_per_wrap_with_everything_on_it():
    o = order(address_line_2="Loading dock 3, via the rear service lane, "
                             "ask at the gatehouse for the stores supervisor",
              job_number="J-77")
    o["items"][0]["wrap_weights_kg"] = [3.2, 3.45]
    labs = dl.build(o, "Unit 9 Somewhere Street, Brisbane QLD 4000")
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "labels.pdf")
        dl.render_pdf(labs, path)
        assert _page_sizes_mm(path) == [(297, 210)] * 3
        text = _pdf_text(path)
    flat = re.sub(r"\s+", " ", text)
    assert flat.count("Delivery label") == 3
    assert "Unit 9 Somewhere Street" in flat
    assert "3.2 kg" in flat and "3.45 kg" in flat and "____ kg" in flat
    assert "1A/2" in flat and "1B/2" in flat and "2/2" in flat
    assert "J-77" in flat and "57920" in flat
    assert "45 667 800 893" in flat and "07 3800 3448" in flat
    assert "ask at the gatehouse" in flat
    for gone in ("Fax", "Purchase Order", "Dispatch", "Delivery Instructions"):
        assert gone.lower() not in flat.lower(), gone
    # The order reference once per label, as Order Number.
    assert flat.count("57920") == 3


def test_nothing_to_print_is_an_error_not_an_empty_file():
    assert refused(dl.render_pdf, [], "/nonexistent/never.pdf")


def test_exactly_ten_with_wrapping_that_grows_with_the_count():
    """The count-by-count path, not the closed form: 1.5 kg filters with
    0.5 kg of wrapping each come to exactly 10.0 kg at five."""
    per = {"confirmed": True, "per_filter_kg": 0.5}
    assert pk.bundle_kg(1.5, 5, per) == 10.0
    assert pk.weight_capacity(1.5, per, 99) == 5
    assert pk.weight_capacity(1.5000001, per, 99) == 4


def test_packing_never_touches_the_notes():
    s = cs.defaults()
    item = {"Filter Type": "V-form", "Quantity": 9, "Short": 500,
            "Long": 600, "Channel": 50, "Media Type": "G4",
            "Notes": "Customer: label each one"}
    item["Packing"] = op.set_manual(item, [3, 3, 3])
    out, _ = op.refresh_items([item], s)
    auto = op.set_automatic(item, s, max_per_wrap=2)
    assert out[0]["Notes"] == "Customer: label each one"
    assert item["Notes"] == "Customer: label each one"
    assert "Notes" not in auto and "Notes" not in item["Packing"]
