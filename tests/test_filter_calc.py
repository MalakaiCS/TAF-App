"""Wire, media and component weights, bracing and mounting frames.

The arithmetic checks use measured cut pieces only. They test the sums, not
new manufacturing rules: a measured piece is a final blank, so whatever the
calculator does to one other than area x rate is a bug.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import bracing as br                    # noqa: E402
from taf_order_app import calc_settings as cs              # noqa: E402
from taf_order_app import filter_calc as fc                # noqa: E402
from taf_order_app import materials as m                   # noqa: E402
from taf_order_app import mounting_frames as mf            # noqa: E402


def close(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


def piece(w=600, l=1000, n=1, **kw):
    return dict({"cut_width_mm": w, "cut_length_mm": l,
                 "pieces_per_filter": n}, **kw)


def wire_only(code, pieces, qty=1, installed=None):
    wire = {"pieces": pieces}
    if installed:
        wire["installed"] = installed
    return fc.calculate({"wire": wire, "wire_material_override": code,
                         "order_quantity": qty, "parts": ["wire"]})


def media_only(code, pieces, qty=1, installed=None):
    comp = {"media_code": code, "pieces": pieces}
    if installed:
        comp["installed"] = installed
    return fc.calculate({"media_components": [comp], "order_quantity": qty,
                         "parts": ["media"]})


# ── Material rates, from the supplied stock ──────────────────────────────────

def test_wire_rates_are_roll_mass_over_roll_area():
    large = m.wire_material("LARGE_WIRE")
    small = m.wire_material("SMALL_WIRE")
    assert large["roll_area_m2"] == 36.0 and small["roll_area_m2"] == 36.0
    assert close(large["kg_per_m2"], 24.87 / 36)
    assert close(small["kg_per_m2"], 19.30 / 36)
    assert large["basis"] == small["basis"] == "supplied_roll_mass"
    # The source measurement travels with the rate.
    assert large["source"]["roll_weight_kg"] == 24.87
    assert large["source"]["wire_diameter_mm"] == 1.24


def test_rates_are_not_rounded():
    assert m.wire_material("LARGE_WIRE")["kg_per_m2"] != 0.691
    assert repr(m.wire_material("LARGE_WIRE")["kg_per_m2"]).startswith(
        "0.69083333")


def test_every_media_rate():
    want = {"WASHABLE": 0.240, "F5": 0.350, "G4": 0.300, "180": 0.180,
            "GREY": 0.150, "BLACK": 0.150}
    for code, rate in want.items():
        got = m.media_material(code)
        assert close(got["kg_per_m2"], rate), (code, got["kg_per_m2"])
    assert m.media_material("180")["stock_area_m2"] == 84.0
    assert m.media_material("WASHABLE")["stock_weight_kg"] == 10.08


def test_black_is_derived_from_grey():
    black = m.media_material("BLACK")
    assert black["basis"] == "derived_from_GREY"
    assert close(black["stock_weight_kg"], 9.45)
    assert black["stock_area_m2"] == 63.0
    assert black["source"]["derived_from"] == "GREY"


def test_black_follows_grey_until_it_is_weighed():
    s = m.default_settings()
    s["media"]["GREY"]["stock_weight_kg"] = 16.8           # re-weighed: 0.2
    assert close(m.media_material("BLACK", s)["kg_per_m2"], 0.2)
    measured = m.replace_black_with_measurement(s, 11.34, 63.0, "Sam")
    black = m.media_material("BLACK", measured)
    assert black["basis"] == "measured"
    assert close(black["kg_per_m2"], 0.18)
    # Re-weighing GREY no longer moves BLACK.
    measured["media"]["GREY"]["stock_weight_kg"] = 25.2
    assert close(m.media_material("BLACK", measured)["kg_per_m2"], 0.18)


def test_media_roll_size_is_not_inferred_from_area():
    for code in m.MEDIA_CODES:
        mat = m.media_material(code)
        assert mat["roll_width_mm"] is None and mat["roll_length_mm"] is None


def test_180_stays_a_string_code_and_aliases_are_the_ones_in_use():
    assert m.normalise_media_code("180") == "180"
    assert m.normalise_media_code(180) == "180"
    assert m.normalise_media_code("wash") == "WASHABLE"
    assert m.normalise_media_code(" g4 ") == "G4"
    for bad in ("E-MESH", "carbon", "F6", 180.5, "", None, True):
        try:
            m.normalise_media_code(bad)
        except m.MaterialError:
            continue
        raise AssertionError(f"{bad!r} was accepted")


# ── Which wire ──────────────────────────────────────────────────────────────

def test_v_form_wire_by_depth_including_the_edges():
    small = (30, 50, 60, 115, 150, 250)
    large = (65, 90, 110)
    for d in small:
        assert m.select_wire("V-form", d)["code"] == "SMALL_WIRE", d
    for d in large:
        assert m.select_wire("V-form", d)["code"] == "LARGE_WIRE", d


def test_depths_without_a_rule_are_a_question_not_a_guess():
    for d in (25, 29.9, 61, 62, 64, 111, 114):
        sel = m.select_wire("V-form", d)
        assert sel["code"] is None and sel["status"] == "needs_wire_rule", d
    assert m.select_wire("Flat Panel", 25)["status"] == "needs_wire_rule"


def test_an_override_is_recorded_as_one():
    sel = m.select_wire("V-form", 62, override="large_wire")
    assert sel["code"] == "LARGE_WIRE" and sel["overridden"] is True
    assert m.select_wire("V-form", 90)["overridden"] is False
    assert m.select_wire("Flat Panel", 20,
                         rules={"Flat Panel": "SMALL_WIRE"})["code"] \
        == "SMALL_WIRE"


# ── The arithmetic, on measured pieces ──────────────────────────────────────

def test_one_large_wire_piece():
    r = wire_only("LARGE_WIRE", [piece()])
    assert close(r["cut_mesh_area_m2_per_filter"], 0.6)
    assert close(r["wire_blank_weight_kg_per_filter"], 0.4145)


def test_two_large_wire_pieces_and_ten_filters():
    r = wire_only("LARGE_WIRE", [piece(n=2)], qty=10)
    assert close(r["cut_mesh_area_m2_per_filter"], 1.2)
    assert close(r["wire_blank_weight_kg_per_filter"], 0.829)
    assert close(r["wire_blank_weight_kg_order"], 8.29)


def test_small_wire_pieces():
    assert close(wire_only("SMALL_WIRE", [piece()])
                 ["wire_blank_weight_kg_per_filter"], 0.6 * 19.30 / 36)
    r = wire_only("SMALL_WIRE", [piece(n=2)])
    assert close(r["wire_blank_weight_kg_per_filter"], 1.2 * 19.30 / 36)
    assert repr(r["wire_blank_weight_kg_per_filter"]).startswith("0.64333")


def test_one_media_piece_of_every_code():
    want = {"WASHABLE": 0.144, "F5": 0.210, "G4": 0.180, "180": 0.108,
            "GREY": 0.090, "BLACK": 0.090}
    for code, kg in want.items():
        r = media_only(code, [piece()])
        assert close(r["media_blank_weight_kg_per_filter"], kg), code


def test_wire_plus_media_blanks():
    r = fc.calculate({
        "wire": {"pieces": [piece(n=2)]},
        "wire_material_override": "LARGE_WIRE",
        "media_components": [{"media_code": "F5", "pieces": [piece()]}],
        "order_quantity": 10})
    assert close(r["wire_blank_weight_kg_per_filter"]
                 + r["media_blank_weight_kg_per_filter"], 1.039)
    assert close(r["wire_blank_weight_kg_order"]
                 + r["media_blank_weight_kg_order"], 10.39)
    # Not yet an installed subtotal: nobody said the blanks stay whole.
    assert r["installed_wire_weight_kg_per_filter"] is None
    assert r["complete_filter_weight_kg_per_filter"] is None


def test_installed_subtotal_only_when_the_blanks_stay_whole():
    r = fc.calculate({
        "wire": {"pieces": [piece(n=2)], "installed": "full_blank"},
        "wire_material_override": "LARGE_WIRE",
        "media_components": [{"media_code": "F5", "pieces": [piece()],
                              "installed": "full_blank"}],
        "order_quantity": 10})
    assert close(r["known_material_weight_kg_per_filter"], 1.039)
    assert close(r["known_material_weight_kg_order"], 10.39)
    # Still not a filter weight: no frame, no construction.
    assert r["complete_filter_weight_kg_per_filter"] is None
    assert r["weight_complete"] is False


def test_measured_cuts_get_nothing_added_or_rounded():
    s = cs.defaults()
    s["cut_profiles"] = [{"id": "P", "version": 1, "kind": "wire",
                          "verified": True, "constructions": ["V-form"],
                          "method": "linear", "cut_increment_mm": 25,
                          "width": {"from": "short"},
                          "length": {"from": "long"},
                          "pieces_per_filter": 2}]
    r = fc.calculate({"filter_type": "V-form", "width_mm": 601,
                      "height_mm": 1001, "nominal_depth_mm": 90,
                      "wire": {"pieces": [piece(601, 1001)]},
                      "parts": ["wire"]}, s)
    p = r["wire"]["pieces"][0]
    assert (p["cut_width_mm"], p["cut_length_mm"]) == (601, 1001)
    assert r["wire"]["measured_cut_pieces"] is True


def test_several_piece_sizes_layers_and_media_codes():
    r = fc.calculate({"media_components": [
        {"media_code": "G4", "pieces": [piece(500, 500, 2), piece(100, 400, 3)]},
        {"media_code": "GREY", "pieces": [piece(500, 500, 1)]},
    ], "parts": ["media"]})
    g4 = (0.25 * 2 + 0.04 * 3) * 0.3
    grey = 0.25 * 0.15
    assert close(r["media_components"][0]["blank_weight_kg_per_filter"], g4)
    assert close(r["media_blank_weight_kg_per_filter"], g4 + grey)


def test_known_media_area_with_unknown_roll_size():
    r = media_only("G4", [piece()])
    c = r["media_components"][0]
    assert c["media_roll_fit_status"] == "not_configured"
    assert close(c["blank_weight_kg_per_filter"], 0.18)


def test_a_media_piece_checked_against_a_configured_roll():
    s = cs.defaults()
    s["materials"]["media"]["G4"].update(roll_width_mm=1000,
                                         roll_length_mm=20000)
    r = fc.calculate({"media_components": [{"media_code": "G4",
                      "pieces": [piece(1100, 600)]}], "parts": ["media"]}, s)
    # Media has a direction: it is not turned to make it fit.
    assert r["media_components"][0]["status"] == "cut_does_not_fit_roll"
    r = fc.calculate({"media_components": [{"media_code": "G4",
                      "pieces": [piece(1100, 600, rotation_allowed=True)]}],
                      "parts": ["media"]}, s)
    assert r["media_components"][0]["media_roll_fit_status"] == "fits"


def test_wire_that_cannot_fit_the_roll():
    r = wire_only("LARGE_WIRE", [piece(1300, 1300)])
    assert r["wire"]["status"] == "cut_does_not_fit_roll"
    assert r["wire_blank_weight_kg_per_filter"] is None
    r = wire_only("LARGE_WIRE", [piece(1300, 900)])           # turned
    assert r["wire"]["roll_fit_status"] == "fits"
    r = wire_only("LARGE_WIRE", [piece(1300, 900, rotation_allowed=False)])
    assert r["wire"]["status"] == "cut_does_not_fit_roll"


def test_trimmed_blanks_use_the_retained_area():
    r = wire_only("LARGE_WIRE", [piece()], installed={
        "rule": "retained_area", "retained_area_mm2_per_filter": 500_000})
    assert close(r["wire_blank_weight_kg_per_filter"], 0.4145)
    assert close(r["installed_wire_weight_kg_per_filter"],
                 0.5 * 24.87 / 36)


def test_bad_inputs_are_refused():
    for bad in ({"width_mm": 0}, {"width_mm": -5}, {"width_mm": "nan"},
                {"height_mm": float("inf")}, {"order_quantity": 0},
                {"order_quantity": 2.5}, {"order_quantity": True},
                {"order_quantity": -1}):
        req = dict({"filter_type": "V-form", "width_mm": 500,
                    "height_mm": 500, "nominal_depth_mm": 50}, **bad)
        r = fc.calculate(req)
        assert r["status"] == "invalid_input", bad
    r = wire_only("LARGE_WIRE", [piece(n=0)])
    assert r["status"] == "invalid_input"
    r = wire_only("LARGE_WIRE", [piece(n=1.5)])
    assert r["status"] == "invalid_input"
    r = media_only("CARBON", [piece()])
    assert r["status"] == "invalid_input"
    assert r["media_components"][0]["status"] == "unsupported_media_code"
    r = fc.calculate({"filter_type": "Bag", "width_mm": 1, "height_mm": 1})
    assert r["status"] == "invalid_input"


def test_quantity_defaults_to_one():
    r = wire_only("LARGE_WIRE", [piece()], qty=None)
    assert r["order_quantity"] == 1


# ── Profiles ────────────────────────────────────────────────────────────────

def test_the_worksheet_formulas_are_the_v_form_profiles():
    r = fc.calculate({"filter_type": "V-form", "width_mm": 595,
                      "height_mm": 595, "nominal_depth_mm": 90,
                      "media_code": "G4"})
    w = r["wire"]["pieces"][0]
    assert r["wire"]["profile_id"] == "TAF-WS-V85-100"
    assert (w["cut_width_mm"], w["cut_length_mm"]) == (585, 1062)
    assert w["pieces_per_filter"] == 2
    mp = r["media_components"][0]["pieces"][0]
    assert (mp["cut_width_mm"], mp["cut_length_mm"]) == (645, 1102)
    assert r["wire"]["code"] == "LARGE_WIRE"


def test_a_depth_the_worksheet_has_no_rule_for():
    for depth in (62, 105, 150):
        r = fc.calculate({"filter_type": "V-form", "width_mm": 500,
                          "height_mm": 500, "nominal_depth_mm": depth,
                          "media_code": "G4"})
        assert r["wire"]["status"] == "needs_cut_rule", depth
        assert r["wire_blank_weight_kg_per_filter"] is None
        assert r["media_components"][0]["status"] == "needs_media_cut_rule"
    # The wire rate is still known at 150 even with no cut.
    r = fc.calculate({"filter_type": "V-form", "width_mm": 500,
                      "height_mm": 500, "nominal_depth_mm": 150})
    assert r["wire"]["code"] == "SMALL_WIRE"
    assert r["wire"]["material"]["kg_per_m2"] > 0


def test_wire_and_media_calculate_independently():
    # No wire rule for a flat panel, but its media still works out.
    r = fc.calculate({"filter_type": "Flat Panel", "width_mm": 500,
                      "height_mm": 600, "nominal_depth_mm": 25,
                      "media_code": "G4"})
    assert r["wire"]["code"] is None
    assert close(r["media_blank_weight_kg_per_filter"], 0.3 * 0.3)
    # And media alone, for a V-form whose media comes off the wire blank.
    r = fc.calculate({"filter_type": "V-form", "width_mm": 595,
                      "height_mm": 595, "nominal_depth_mm": 90,
                      "media_code": "G4", "parts": ["media"]})
    assert r["wire"] is None
    assert r["media_components"][0]["pieces"][0]["cut_width_mm"] == 645


def test_triangular_geometry_from_a_confirmed_profile():
    prof = {"id": "TRI", "version": 3, "kind": "wire", "verified": True,
            "constructions": ["V-form"], "method": "triangular_v",
            "v_count": 4, "usable_span_mm": 400, "peak_to_trough_mm": 80,
            "straight_dimension_mm": {"from": "short", "add": -10},
            "length_allowances_mm": [10, 10], "width_allowances_mm": 5,
            "cut_increment_mm": {"length": 12}, "pieces_per_filter": 2}
    s = cs.defaults()
    s["cut_profiles"] = [prof]
    r = fc.calculate({"filter_type": "V-form", "width_mm": 500,
                      "height_mm": 600, "nominal_depth_mm": 90,
                      "wire": {"profile_id": "TRI", "profile_version": 3},
                      "parts": ["wire"]}, s)
    developed = 2 * 4 * math.sqrt(50 ** 2 + 80 ** 2)
    want_len = math.ceil((developed + 20) / 12) * 12
    p = r["wire"]["pieces"][0]
    assert p["cut_width_mm"] == 495
    assert p["cut_length_mm"] == want_len
    assert r["wire"]["profile_version"] == 3


def test_segment_geometry_and_an_exact_increment():
    prof = {"id": "SEG", "version": 1, "kind": "media", "verified": True,
            "constructions": ["V-form"], "method": "segments",
            "segments": [[30, 40], [30, 40], [0, 50]],
            "straight_dimension_mm": 500, "cut_increment_mm": 50,
            "pieces_per_filter": 1}
    assert fc.profile_cut(prof, {"short": 1, "long": 1})[0] == (500, 150)


def test_an_unverified_or_missing_profile_is_not_used():
    s = cs.defaults()
    s["cut_profiles"] = [{"id": "DRAFT", "version": 1, "kind": "wire",
                          "verified": False, "constructions": ["V-form"],
                          "method": "linear", "width": 1, "length": 1}]
    for pid in ("DRAFT", "NOPE"):
        r = fc.calculate({"filter_type": "V-form", "width_mm": 500,
                          "height_mm": 500, "nominal_depth_mm": 90,
                          "wire": {"profile_id": pid}, "parts": ["wire"]}, s)
        assert r["wire"]["status"] == "needs_cut_rule", pid
        assert r["wire"]["cut_width_mm"] is None


# ── Components and completeness ─────────────────────────────────────────────

def _complete_settings(brace_kg=0.35):
    s = cs.defaults()
    s["cut_profiles"] = [
        {"id": "W", "version": 1, "kind": "wire", "verified": True,
         "constructions": ["Flat Panel"], "method": "linear",
         "width": {"from": "short", "add": -10},
         "length": {"from": "long", "add": -10},
         "pieces_per_filter": 2, "installed": "full_blank"},
        {"id": "M", "version": 1, "kind": "media", "verified": True,
         "constructions": ["Flat Panel"], "method": "flat",
         "usable_width_mm": {"from": "short"},
         "usable_length_mm": {"from": "long"},
         "pieces_per_filter": 1, "installed": "full_blank"}]
    s["wire_rules"] = {"Flat Panel": "SMALL_WIRE"}
    s["component_profiles"] = [{"name": "filter_frame", "id": "FR",
                                "version": 1, "verified": True,
                                "method": "per_perimeter_m", "kg_per_m": 0.5}]
    if brace_kg is not None:
        s["brace_profiles"] = {"Flat Panel": {
            "kg_each_including_fixings": brace_kg, "version": 1}}
    return s


def test_a_complete_weight_needs_every_part():
    s = _complete_settings()
    r = fc.calculate({"filter_type": "Flat Panel", "width_mm": 500,
                      "height_mm": 600, "nominal_depth_mm": 25,
                      "media_code": "G4", "order_quantity": 3}, s)
    wire = 2 * 0.49 * 0.59 * 19.30 / 36
    media = 0.3 * 0.3
    frame = 0.5 * 2.2
    assert r["weight_complete"] is True and r["status"] == "complete"
    assert close(r["complete_filter_weight_kg_per_filter"],
                 wire + media + frame)
    assert close(r["complete_filter_weight_kg_order"],
                 3 * (wire + media + frame))
    braces = [c for c in r["components"] if c["name"] == "braces"][0]
    assert braces["status"] == "not_applicable"


def test_a_required_brace_is_counted_once_and_its_weight_is_needed():
    s = _complete_settings(brace_kg=0.35)
    base = {"filter_type": "Flat Panel", "nominal_depth_mm": 25,
            "media_code": "G4"}
    small = fc.calculate(dict(base, width_mm=701, height_mm=600), s)
    braced = fc.calculate(dict(base, width_mm=701, height_mm=701), s)
    brace = [c for c in braced["components"] if c["name"] == "braces"][0]
    assert brace["count"] == 1 and close(brace["installed_kg_per_filter"], 0.35)
    names = [c["name"] for c in braced["components"]]
    assert names.count("braces") == 1
    wire_diff = 2 * (0.691 * 0.691 - 0.691 * 0.59) * 19.30 / 36
    media_diff = (0.701 * 0.701 - 0.701 * 0.6) * 0.3
    frame_diff = 0.5 * 2 * 0.101
    assert close(braced["complete_filter_weight_kg_per_filter"]
                 - small["complete_filter_weight_kg_per_filter"],
                 wire_diff + media_diff + frame_diff + 0.35, 1e-9)
    unknown = fc.calculate(dict(base, width_mm=701, height_mm=701),
                           _complete_settings(brace_kg=None))
    assert unknown["complete_filter_weight_kg_per_filter"] is None
    assert any("brace weight" in x for x in unknown["missing"])
    assert unknown["known_material_weight_kg_per_filter"] is not None


def test_an_unknown_frame_keeps_the_total_empty_not_zero():
    s = _complete_settings()
    s["component_profiles"] = []
    r = fc.calculate({"filter_type": "Flat Panel", "width_mm": 500,
                      "height_mm": 600, "nominal_depth_mm": 25,
                      "media_code": "G4"}, s)
    assert r["complete_filter_weight_kg_per_filter"] is None
    assert "filter_frame" in r["excluded_components"]
    assert r["status"] == "partial"


def test_extra_components_known_unknown_and_not_applicable():
    s = _complete_settings()
    base = {"filter_type": "Flat Panel", "width_mm": 500, "height_mm": 600,
            "nominal_depth_mm": 25, "media_code": "G4"}
    a = fc.calculate(dict(base, components=[
        {"name": "clips", "kg_per_filter": 0.05},
        {"name": "label", "not_applicable": True}]), s)
    b = fc.calculate(base, s)
    assert close(a["complete_filter_weight_kg_per_filter"]
                 - b["complete_filter_weight_kg_per_filter"], 0.05)
    c = fc.calculate(dict(base, components=[{"name": "clips"}]), s)
    assert c["complete_filter_weight_kg_per_filter"] is None


def test_mixed_lines_add_up_unrounded():
    s = _complete_settings()
    lines = [fc.calculate({"filter_type": "Flat Panel", "width_mm": w,
                           "height_mm": h, "nominal_depth_mm": 25,
                           "media_code": "G4", "order_quantity": q}, s)
             for w, h, q in ((333, 444, 7), (555, 666, 3))]
    total = sum(r["complete_filter_weight_kg_order"] for r in lines)
    per = [r["complete_filter_weight_kg_per_filter"] for r in lines]
    assert close(total, per[0] * 7 + per[1] * 3)
    assert total != round(per[0], 3) * 7 + round(per[1], 3) * 3


def test_the_order_calculator_and_the_old_wire_columns_agree():
    import pdf_generator as g
    for s, l, ch in ((295, 310, 50), (595, 595, 90), (400, 900, 70),
                     (500, 600, 25)):
        label = ("F" if ch == 25 else "V") + str(ch)
        cols = g._wire_media(s, l, ch, label, 1)
        r = fc.calculate({"filter_type": "Flat Panel" if ch == 25
                          else "V-form", "width_mm": s, "height_mm": l,
                          "nominal_depth_mm": ch, "media_code": "G4"})
        p = r["wire"]["pieces"][0]
        assert cols["wc"] == f"{int(p['cut_width_mm'])}*{int(p['cut_length_mm'])}"
        mp = r["media_components"][0]["pieces"][0]
        assert cols["mc"] == f"{int(mp['cut_width_mm'])}*{int(mp['cut_length_mm'])}"


def test_results_say_what_produced_them():
    r = fc.calculate({"filter_type": "V-form", "width_mm": 595,
                      "height_mm": 595, "nominal_depth_mm": 90,
                      "media_code": "G4"})
    assert r["provenance"]["calc_version"] == fc.CALC_VERSION
    assert r["provenance"]["materials_version"] == m.DEFAULTS_VERSION
    assert r["wire"]["material"]["source"]["roll_weight_kg"] == 24.87


# ── Bracing ─────────────────────────────────────────────────────────────────

def test_flat_panel_bracing_edges():
    def b(w, h):
        return br.evaluate("Flat Panel", w, h)
    assert b(700, 700)["required"] is False
    one = b(701, 701)
    assert one["required"] and one["count"] == 1 and one["arrangement"] is None
    assert b(1300, 701)["count"] == 1
    two = b(1301, 700)
    assert two["count"] == 2 and two["arrangement"] == "Cross Format"
    assert two["message"] == "Brace Required - 2 braces, Cross Format"


def test_bracing_does_not_care_which_way_round():
    for kind in ("Flat Panel", "V-form", "Flyscreen"):
        for w, h in ((1301, 701), (701, 701), (800, 150), (1301, 651)):
            a, b = br.evaluate(kind, w, h), br.evaluate(kind, h, w)
            assert (a["required"], a["advisory"], a["count"], a["message"]) \
                == (b["required"], b["advisory"], b["count"], b["message"])


def test_v_form_bracing_needs_both_thresholds():
    assert br.evaluate("V-form", 1301, 701)["required"] is True
    assert br.evaluate("V-form", 1300, 701)["required"] is False
    assert br.evaluate("V-form", 1301, 700)["required"] is False
    # The rule alone does not give a count.
    assert br.evaluate("V-form", 1301, 701)["count"] is None
    two = br.evaluate("V-form", 1301, 701, {"count": 2})
    assert two["arrangement"] == "Cross Format"


def test_flyscreen_bracing():
    assert br.evaluate("Flyscreen", 800, 150)["message"] == "use brace in filter"
    assert br.evaluate("Flyscreen", 800, 150)["required"] is True
    assert br.evaluate("Flyscreen", 800, 151)["required"] is False
    assert br.evaluate("Flyscreen", 800, 151)["advisory"] is False
    advice = br.evaluate("Flyscreen", 1301, 650)
    assert advice["message"] == "consider bracing"
    assert advice["advisory"] and not advice["required"]
    both = br.evaluate("Flyscreen", 1301, 651)
    assert both["message"] == "use brace in filter" and both["required"]
    assert br.evaluate("Flyscreen", 600, 650)["required"] is False


def test_bracing_that_cannot_be_decided_says_so():
    assert br.evaluate("Flat Panel", 0, 500)["status"] == "invalid_input"
    assert br.evaluate("Flat Panel", "x", 500)["status"] == "invalid_input"
    assert br.evaluate("Stepped Filter", 900, 900)["status"] == "needs_rule"
    assert br.evaluate("", 900, 900)["status"] == "needs_rule"
    # A header is a flat panel.
    assert br.evaluate("Header", 701, 701)["count"] == 1


# ── Mounting frames ─────────────────────────────────────────────────────────

SYNTHETIC = {"id": "TEST-ONLY", "version": 1, "verified": True,
             "sizes": [[610, 610]],
             "pieces": [{"name": "side", "qty": 4,
                         "developed_flat_width_mm": 100,
                         "retained_length_mm": 500}],
             "hardware": [{"name": "rivet", "qty": 8, "kg_each": 0.002}]}
STEEL = {"density_kg_m3": 8000, "basis": "test", "version": 1}


def test_mounting_frame_unit_conversion_on_a_synthetic_volume():
    r = mf.calculate(610, 610, 3, SYNTHETIC, STEEL)
    steel = 4 * 100 * 500 * 2.0 * 8000 / 1e9                  # 3.2 kg
    assert close(steel, 3.2)
    assert close(r["mounting_frame_weight_kg_each"], steel + 0.016)
    assert close(r["mounting_frame_weight_kg_order"], 3 * (steel + 0.016))
    assert r["thickness_mm"] == 2.0


def test_mounting_frame_holes_overlaps_and_solid_sections():
    prof = dict(SYNTHETIC, removed_area_mm2=1000,
                retained_overlap_area_mm2=400,
                pieces=[{"name": "bar", "qty": 1,
                         "cross_section_area_mm2": 50,
                         "retained_length_mm": {"from": "long", "add": -10}}],
                hardware=[])
    r = mf.calculate(610, 610, 1, prof, STEEL)
    want = 50 * 600 * 8000 / 1e9 + (400 - 1000) * 2.0 * 8000 / 1e9
    assert close(r["mounting_frame_weight_kg_each"], want)


def test_a_mounting_frame_with_no_profile_or_density_is_unknown():
    r = mf.calculate(610, 610, 2, None, STEEL)
    assert r["status"] == "needs_mounting_frame_profile"
    assert r["mounting_frame_weight_kg_each"] is None
    r = mf.calculate(610, 610, 2, SYNTHETIC, {"density_kg_m3": None})
    assert r["status"] == "needs_mounting_frame_profile"
    assert any("density" in x for x in r["missing"])
    assert mf.calculate(0, 610, 1, SYNTHETIC, STEEL)["status"] == \
        "invalid_input"
    assert mf.calculate(610, 610, 1, dict(SYNTHETIC, thickness_mm=1.6),
                        STEEL)["status"] == "invalid_input"


def test_mixed_mounting_frame_sizes():
    other = dict(SYNTHETIC, sizes=[[455, 510]])
    a = mf.calculate(610, 610, 2, SYNTHETIC, STEEL)
    b = mf.calculate(510, 455, 5, other, STEEL)
    total = mf.order_total([a, b])
    assert close(total["mounting_frame_weight_kg_order"],
                 a["mounting_frame_weight_kg_each"] * 2
                 + b["mounting_frame_weight_kg_each"] * 5)
    assert mf.order_total([a, mf.calculate(1, 1, 1, None, STEEL)]
                          )["mounting_frame_weight_kg_order"] is None
    assert mf.profile_for(610, 610, [SYNTHETIC]) is SYNTHETIC
    assert mf.profile_for(700, 700, [SYNTHETIC]) is None


def test_no_synthetic_geometry_ships_as_a_taf_profile():
    d = cs.defaults()
    assert d["mounting_frame_profiles"] == []
    assert d["steel"]["density_kg_m3"] is None
    assert d["brace_profiles"] == {} and d["component_profiles"] == []
    sizes = [(s["width_mm"], s["height_mm"]) for s in mf.known_sizes()]
    assert (610, 610) in sizes


def test_a_mounting_frame_counts_only_when_the_product_includes_one():
    s = _complete_settings()
    s["mounting_frame_profiles"] = [SYNTHETIC]
    s["steel"] = STEEL
    base = {"filter_type": "Flat Panel", "width_mm": 610, "height_mm": 610,
            "nominal_depth_mm": 25, "media_code": "G4"}
    without = fc.calculate(base, s)
    with_ = fc.calculate(dict(base, includes_mounting_frame=True), s)
    assert close(with_["complete_filter_weight_kg_per_filter"]
                 - without["complete_filter_weight_kg_per_filter"],
                 3.2 + 0.016)
    assert [c["name"] for c in with_["components"]].count("mounting_frame") == 1


def test_the_database_seed_matches_the_supplied_numbers():
    """The migration seeds the same measurements the code falls back to.
    Two copies of one fact drift; this keeps them the same."""
    import json
    import re as _re
    sql = (ROOT / "migrate_packing_and_merge.sql").read_text()
    seed = sql.split("INSERT INTO public.calc_settings (key, value) VALUES")[1]
    blob = _re.search(r"\('materials', '(\{.*?\})'\)", seed, _re.S).group(1)
    stored = json.loads(blob)
    defaults = m.default_settings()
    assert stored["version"] == defaults["version"]
    for kind in ("wire", "media"):
        for code, row in defaults[kind].items():
            for field, value in stored[kind][code].items():
                assert row[field] == value or float(row[field]) == float(value), \
                    (kind, code, field)
    company = _re.search(r"\('company', '(\{.*?\})'\)", seed).group(1)
    assert json.loads(company)["base_address"] == cs.BASE_ADDRESS_DEFAULT
    handling = _re.search(r"\('handling_profiles', '(\[.*?\])'\)", seed,
                          _re.S).group(1)
    assert json.loads(handling) == cs.DEFAULT_HANDLING_PROFILES
