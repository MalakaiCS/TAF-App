"""The C-channel calculator: dimensions, weights, stacks, frames and stock.

The arithmetic is checked against the formula written out by hand, never
against numbers the calculator produced.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import calc_settings as cs              # noqa: E402
from taf_order_app import cchannel as cc                   # noqa: E402
from taf_order_app import delivery_labels as dl            # noqa: E402
from taf_order_app import order_packing as op              # noqa: E402

MAT = cc.DEFAULT_MATERIAL


def close(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


def by_hand(centre, length=2440, left=23, right=23, t=0.55, rho=7850):
    return (left + centre + right) * length * t * rho / 1e9


def settings(**material):
    s = cs.defaults()
    s["c_channel"]["materials"][MAT].update(material)
    return s


# ── The worked example ──────────────────────────────────────────────────────

def test_the_23_44_23_example():
    """90 x 2440 x 0.55 x 7850 / 1e9 = 0.948123 kg. (The brief's 0.947997
    is a slip; its stack weights are right either way.)"""
    r = cc.channel_weight(45)
    assert r["actual_centre_width_mm"] == 44
    assert r["developed_width_mm"] == 90
    assert close(r["raw_weight_kg"], 0.948123)
    assert close(r["raw_weight_kg"], by_hand(44))
    assert r["display_weight_kg"] == 1.0
    assert cc.size_text(r) == "23 x 44 x 23 x 2440 mm"
    stacks = cc.stack_weights(r)
    assert [x["stack_quantity"] for x in stacks] == [1, 2, 5, 10]
    assert [x["stack_display_weight_kg"] for x in stacks] == \
        [1.0, 1.9, 4.8, 9.5]
    assert close(stacks[3]["stack_raw_weight_kg"], 9.48123)
    assert [cc.kg_text(x["stack_display_weight_kg"]) for x in stacks] == \
        ["1.0 kg", "1.9 kg", "4.8 kg", "9.5 kg"]


def test_the_result_carries_everything_other_programs_need():
    r = cc.channel_weight(45)
    for key in ("calculation_status", "material_code", "nominal_depth_mm",
                "actual_centre_width_mm", "left_flange_mm", "right_flange_mm",
                "channel_length_mm", "material_thickness_mm",
                "steel_density_kg_m3", "dimension_source",
                "verification_status", "weight_basis", "raw_weight_kg",
                "display_weight_kg", "missing_inputs", "validation_errors",
                "calculation_warnings"):
        assert key in r, key
    assert r["material_code"] == MAT and r["material_thickness_mm"] == 0.55
    assert r["steel_density_kg_m3"] == 7850 and r["channel_length_mm"] == 2440
    assert isinstance(r["raw_weight_kg"], float)       # a number, not "kg"


# ── Every depth ─────────────────────────────────────────────────────────────

def test_every_depth_from_10_to_250():
    rows = cc.table()
    assert [r["nominal_depth_mm"] for r in rows] == list(range(10, 255, 5))
    for r in rows:
        d = r["nominal_depth_mm"]
        width = cc.SUPPLIED_WIDTHS.get(d, 10 if d == 10 else d - 2)
        assert r["actual_centre_width_mm"] == width, d
        assert close(r["raw_weight_kg"], by_hand(width)), d
        for s in r["stacks"]:
            want = math.ceil(round(by_hand(width) * s["stack_quantity"] * 10,
                                   9)) / 10
            assert s["stack_display_weight_kg"] == want, (d, s)
        assert r["size"] == f"23 x {width:g} x 23 x 2440 mm"


def test_where_each_width_came_from_is_kept_apart():
    status = {r["nominal_depth_mm"]: r["verification_status"]
              for r in cc.table()}
    assert status[10] == cc.PROVISIONAL
    for d in cc.SUPPLIED_WIDTHS:
        assert status[d] == cc.SUPPLIED, d
    for d in range(105, 255, 5):
        assert status[d] == cc.ESTIMATED, d
    # Nothing is verified until somebody says so.
    assert cc.VERIFIED not in status.values()
    r = cc.channel_weight(150)
    assert r["dimension_source"] == "estimated_rule"
    assert any("estimate" in w for w in r["calculation_warnings"])
    r = cc.channel_weight(45)
    assert r["dimension_source"] == "supplied_measurement"
    assert any("not yet confirmed" in w for w in r["calculation_warnings"])


def test_a_verified_width_wins_and_the_estimate_rule_is_a_setting():
    s = cs.defaults()
    s["c_channel"]["centre_widths"]["45"] = {"width_mm": 43,
                                             "status": cc.VERIFIED}
    s["c_channel"]["centre_widths"]["150"] = {"width_mm": 147,
                                              "status": cc.VERIFIED}
    s["c_channel"]["estimate_rule"] = {"subtract_mm": 3}
    assert cc.channel_weight(45, settings=s)["actual_centre_width_mm"] == 43
    r = cc.channel_weight(150, settings=s)
    assert r["actual_centre_width_mm"] == 147
    assert r["verification_status"] == cc.VERIFIED
    assert r["dimension_source"] == "verified_measurement"
    assert r["calculation_warnings"] == []
    assert cc.channel_weight(200, settings=s)["actual_centre_width_mm"] == 197


def test_custom_dimensions_and_lengths():
    r = cc.channel_weight(centre_width_mm=60, length_mm=1000,
                          left_flange_mm=20, right_flange_mm=25)
    assert r["verification_status"] == cc.CUSTOM
    assert close(r["raw_weight_kg"], by_hand(60, 1000, 20, 25))
    assert close(r["weight_per_mm_kg"], by_hand(60, 1, 20, 25))
    r = cc.channel_weight(45, length_mm=3000)
    assert close(r["raw_weight_kg"], by_hand(44, 3000))


def test_custom_stacks_and_rounding_from_the_raw_weight():
    r = cc.channel_weight(45)
    s = cc.stack_weights(r, [3, 7, 20])
    assert [x["stack_display_weight_kg"] for x in s] == [2.9, 6.7, 19.0]
    # 7 x 0.948123 = 6.636861 - rounded once, up; not 7 x 1.0.
    assert close(s[1]["stack_raw_weight_kg"], 6.636861)
    bad = cc.stack_weights(r, [0, -1, 2.5, True, "x", None])
    assert all(x["stack_display_weight_kg"] is None and x["validation_errors"]
               for x in bad)
    assert cc.stack_weights(r, ["4"])[0]["stack_quantity"] == 4


def test_rounding_up_is_to_the_next_100_grams_and_exact_tenths_stay():
    assert cc.round_up(1.0) == 1.0
    assert cc.round_up(1.0000001) == 1.1
    assert cc.round_up(0.3 * 3) == 0.9          # 0.8999999999999999
    assert cc.round_up(None) is None


# ── Bad input ───────────────────────────────────────────────────────────────

def test_missing_zero_negative_and_non_numbers_are_refused():
    for depth in (0, -5, float("nan"), float("inf"), "deep", True):
        r = cc.channel_weight(depth)
        assert r["calculation_status"] == "invalid_input", depth
        assert r["raw_weight_kg"] is None
    assert cc.channel_weight()["calculation_status"] == "needs_input"
    assert cc.channel_weight(45, length_mm=0)["calculation_status"] == \
        "invalid_input"
    assert cc.channel_weight(centre_width_mm=-1)["raw_weight_kg"] is None
    for key, value in (("density_kg_m3", 0), ("nominal_thickness_mm", -0.5),
                       ("left_flange_mm", 0), ("density_kg_m3", "heavy"),
                       ("stock_length_mm", None)):
        r = cc.channel_weight(45, settings=settings(**{key: value}))
        assert r["calculation_status"] == "invalid_input", key
        assert r["raw_weight_kg"] is None, key
    assert cc.channel_weight(45, material_code="NOPE")["calculation_status"] \
        == "invalid_input"


# ── Material options ────────────────────────────────────────────────────────

def test_material_settings_are_used_not_constants():
    r = cc.channel_weight(45, settings=settings(nominal_thickness_mm=0.6,
                                                density_kg_m3=7800,
                                                stock_length_mm=3000,
                                                left_flange_mm=25))
    assert close(r["raw_weight_kg"], by_hand(44, 3000, 25, 23, 0.6, 7800))


def test_zinc_is_not_counted_twice():
    # Asked to add the coating while the 0.55 may already include it: no.
    r = cc.channel_weight(45, settings=settings(include_coating_mass=True))
    assert close(r["raw_weight_kg"], by_hand(44))
    assert r["weight_basis"] == "calculated_base_steel"
    assert any("coating not added" in w for w in r["calculation_warnings"])
    # Base-metal thickness known: steel plus 275 g/m2 over the developed area.
    r = cc.channel_weight(45, settings=settings(include_coating_mass=True,
                                                base_metal_thickness_mm=0.51))
    steel = by_hand(44, t=0.51)
    zinc = 90 * 2440 / 1e6 * 0.275
    assert close(r["raw_weight_kg"], steel + zinc)
    assert r["weight_basis"] == "calculated_steel_and_coating"
    # A coated thickness: the zinc's thickness comes out of the steel first.
    r = cc.channel_weight(45, settings=settings(thickness_basis="coated"))
    assert close(r["material_thickness_mm"], 0.55 - 275 / 7140)
    assert close(r["raw_weight_kg"], by_hand(44, t=0.55 - 275 / 7140))


def test_bend_correction_and_calibration():
    r = cc.channel_weight(45, settings=settings(bend_correction_mm=-1.5))
    assert r["developed_width_mm"] == 88.5
    assert close(r["raw_weight_kg"], 88.5 * 2440 * 0.55 * 7850 / 1e9)
    r = cc.channel_weight(45, settings=settings(mass_calibration_factor=1.02))
    assert close(r["raw_weight_kg"], by_hand(44) * 1.02)
    assert r["weight_basis"].endswith("_calibrated")


def test_a_verified_measured_weight_is_preferred():
    s = cs.defaults()
    s["c_channel"]["measured_weights"] = [
        {"nominal_depth_mm": 45, "length_mm": 2440, "kg": 0.97,
         "verified": True},
        {"nominal_depth_mm": 50, "length_mm": 2440, "kg": 5.0,
         "verified": False}]
    r = cc.channel_weight(45, settings=s)
    assert r["weight_basis"] == "measured" and r["raw_weight_kg"] == 0.97
    r = cc.channel_weight(45, length_mm=1220, settings=s)
    assert r["weight_basis"] == "measured_scaled_to_length"
    assert close(r["raw_weight_kg"], 0.485)
    # Unverified: the calculation stands.
    assert cc.channel_weight(50, settings=s)["weight_basis"] == \
        "calculated_base_steel"


# ── Frames ──────────────────────────────────────────────────────────────────

def test_a_frame_weighs_its_cut_sections_not_whole_lengths():
    per_mm = by_hand(22, 1)                        # 25mm depth: 22 centre
    for method, cuts in (("u", (1819, 593)), ("sideways_u", (1819, 593)),
                         ("g", (2392,)), ("l", (1206, 1206))):
        cut = cc.frame_cut_list(595, 595, method, 25)
        r = cc.frame_weight(cut, 10)
        assert r["calculation_status"] == "ok"
        assert close(r["frame_weight_kg"], per_mm * sum(cuts)), method
        assert close(r["frame_weight_kg_order"], 10 * per_mm * sum(cuts))
        # Never a whole 2440 length per filter.
        assert r["frame_weight_kg"] < by_hand(22)


def test_sections_can_be_measured_and_mixed():
    rows = [{"nominal_depth_mm": 25, "cut_length_mm": 1000,
             "section_quantity": 2},
            {"nominal_depth_mm": 90, "cut_length_mm": 500,
             "section_quantity": 1, "measured_kg": 0.33}]
    r = cc.frame_weight(rows, 3)
    assert close(r["frame_weight_kg"], by_hand(22, 2000) + 0.33)
    assert r["sections"][1]["weight_basis"] == "measured"
    assert close(r["frame_weight_kg_order"], 3 * r["frame_weight_kg"])


def test_no_cut_list_is_said_not_invented():
    for cut in (None, []):
        r = cc.frame_weight(cut)
        assert r["calculation_status"] == "needs_frame_cut_rule"
        assert r["frame_weight_kg"] is None and r["missing_inputs"]
    assert cc.frame_cut_list(0, 595) is None
    bad = cc.frame_weight([{"nominal_depth_mm": 25, "cut_length_mm": -1}])
    assert bad["calculation_status"] == "invalid_input"
    assert bad["frame_weight_kg"] is None


# ── Stock and labels ────────────────────────────────────────────────────────

def test_stock_weights_from_existing_stock_records():
    w = cc.stock_item_weight({"name": "Channel 45mm", "product_type":
                              "Channel", "unit": "each",
                              "stock_on_hand": 20})
    assert close(w["on_hand_raw_weight_kg"], 20 * 0.948123)
    assert w["on_hand_display_weight_kg"] == 19.0
    w = cc.stock_item_weight({"name": "C-Channel 90mm 3000 bundle of 10",
                              "product_type": "Channel", "unit": "bundle",
                              "stock_on_hand": 2})
    assert close(w["bundle_raw_weight_kg"], 10 * by_hand(89, 3000))
    assert close(w["on_hand_raw_weight_kg"], 20 * by_hand(89, 3000))
    assert cc.stock_item_weight({"name": "Spline", "product_type":
                                 "Spline"}) is None
    nameless = cc.stock_item_weight({"name": "Channel",
                                     "product_type": "Channel"})
    assert nameless["missing_inputs"] and \
        nameless["on_hand_raw_weight_kg"] is None
    r = cc.stock_weight(45, 10)
    assert r["stack_display_weight_kg"] == 9.5
    assert cc.stock_weight(45, 0)["calculation_status"] == "invalid_input"


def test_a_package_of_channel_and_filters_rounds_once():
    s = cs.defaults()
    cust = {"name": "X", "delivery_address1": "1 St", "delivery_city": "Y",
            "delivery_state": "QLD", "delivery_postcode": "4000"}
    items = [{"item_kind": "catalogue", "Product Type": "Channel",
              "Part Number": "CH45", "Description": "45mm channel 2440",
              "Quantity": 7},
             {"item_kind": "catalogue", "Product Type": "Hardware",
              "Description": "4mm rivets", "Quantity": 2}]
    labs = dl.build_for_order({"order_number": "1", "header": {},
                               "items": items}, cust, s, "Base")
    # 7 x 0.948123 = 6.636861 raw, rounded up once to 6.7 - not 7 x 1.0.
    assert close(labs[0]["weight_raw_kg"], 6.636861)
    assert labs[0]["weight_kg"] == "6.7"
    assert labs[0]["filter_size"] == "CH45 - 45mm channel 2440"
    # Something that cannot be weighed is left to write in, not zero.
    assert labs[1]["weight_kg"] == "" and labs[1]["weight_raw_kg"] is None
    assert labs[1]["filter_size"] == "4mm rivets"


def test_a_saved_order_keeps_the_weight_it_was_labelled_with():
    s = cs.defaults()
    item = {"Filter Type": "Flat Panel", "Short": 595, "Long": 595,
            "Channel": 25, "Quantity": 10, "Media Type": "F5"}
    saved, _ = op.refresh_items([item], s, "office", "2026-10-14")
    kept = saved[0]["Weight Snapshot"]
    assert kept["versions"]["c_channel"] == cc.VERSION
    assert kept["frame_weight_kg_per_filter"] > 0
    heavier = cs.defaults()
    heavier["c_channel"]["materials"][MAT]["density_kg_m3"] = 9000
    assert op.evaluate_line(saved[0], heavier)["unit_kg"] == \
        kept["complete_filter_weight_kg_per_filter"]
    # A new order, or a changed line, is worked out afresh.
    assert op.evaluate_line(item, heavier)["unit_kg"] > \
        kept["complete_filter_weight_kg_per_filter"]
    changed = dict(saved[0], Short=495)
    assert op.evaluate_line(changed, heavier)["unit_kg"] != \
        kept["complete_filter_weight_kg_per_filter"]


def test_depth_and_length_read_from_wording():
    assert cc.depth_from_text("Channel 45mm") == 45
    assert cc.depth_from_text("CH90") == 90
    assert cc.depth_from_text("c-channel 25") == 25
    assert cc.depth_from_text("Spline") is None
    assert cc.length_from_text("45mm channel 2440") == 2440
    assert cc.length_from_text("45mm channel") is None
    assert cc.bundle_from_text("bundle of 10") == 10
    assert cc.bundle_from_text("5/pack") == 5


def test_stored_settings_merge_over_the_defaults():
    m = cc.merged({"materials": {MAT: {"density_kg_m3": 7900}},
                   "centre_widths": {"45": {"width_mm": 43,
                                            "status": cc.VERIFIED}}})
    assert m["materials"][MAT]["density_kg_m3"] == 7900
    assert m["materials"][MAT]["nominal_thickness_mm"] == 0.55
    assert m["centre_widths"]["45"]["width_mm"] == 43
    assert m["centre_widths"]["50"]["width_mm"] == 48
    merged = cs.merge({"c_channel": {"value": {"estimate_rule":
                                               {"subtract_mm": 4}},
                                     "version": 3}})
    assert merged["c_channel"]["estimate_rule"]["subtract_mm"] == 4
    assert merged["versions"]["c_channel"] == 3
