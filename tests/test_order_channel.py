"""The channel for a whole order, and pages sharing a length."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import order_channel as oc                # noqa: E402


def _line(page, short, long_, qty=1, channel=25, ftype="Flat Panel"):
    return {"page": page, "Filter Type": ftype, "Short": short,
            "Long": long_, "Channel": channel, "Quantity": qty}


def test_two_gs_from_two_pages_share_one_length():
    # A 1312 G (300 x 350) and an 1112 G (250 x 300): 2424 on one 2440.
    plan = oc.order_plan([_line(1, 300, 350), _line(2, 250, 300)],
                         prefer="g")
    d = plan["depths"][0]
    assert (d["depth"], d["lengths"], d["alone"], d["saved"]) == \
        (25, 1, 2, 1)
    one = oc.page_lines(plan, 1)
    assert one[0][0] == ("SHARE A LENGTH: cut G 1312 from one end, then "
                         "page 2's G 1112 from the other end")
    assert oc.page_lines(plan, 2)[0][0].startswith("SHARE A LENGTH: cut "
                                                   "G 1112")
    assert "25mm: 1 length (2,424mm cut), 1 saved by sharing" in one[-1][0]


def test_different_channel_never_shares():
    plan = oc.order_plan([_line(1, 300, 350), _line(2, 250, 300,
                                                    channel=45,
                                                    ftype="V-form")],
                         prefer="g")
    assert [(d["depth"], d["lengths"]) for d in plan["depths"]] == \
        [(25, 1), (45, 1)]
    assert plan["shares"] == {}


def test_too_long_together_stays_apart_and_totals_add_up():
    plan = oc.order_plan([_line(1, 500, 600), _line(2, 500, 600)],
                         prefer="g")
    d = plan["depths"][0]
    assert d["lengths"] == d["alone"] == 2 and d["saved"] == 0
    assert d["cut_mm"] == 2 * plan["depths"][0]["sticks"][0]["pieces"][0][
        "length"]
    assert oc.short_text(plan) == "Channel 25mm x2"


def test_what_is_not_framed_is_left_out():
    assert not oc.framed({"Filter Type": "Flyscreen", "Short": 500,
                          "Long": 500, "Channel": 10})
    assert not oc.framed(dict(_line(1, 500, 500), **{"Use Stock V-form": 1}))
    assert not oc.framed({"item_kind": "bag", "product_type": "3-Peak"})
    assert oc.order_plan([])["depths"] == []


def test_methods_are_chosen_for_the_whole_order():
    """O/N 21692 (Batare): 2 x 525x790 and 2 x 525x815, 50mm. Each page on
    its own ties U against Sideways U and picked U - 6 lengths, the U caps
    (788, 813) too long to share. Made Sideways U both, the frames take 2
    lengths a page and all four 523 caps go on one: 5, as marked up by
    hand on the printed sheets."""
    plan = oc.order_plan([_line(1, 525, 790, 2, 50, "V-form"),
                          _line(2, 525, 815, 2, 50, "V-form")])
    assert plan["depths"][0]["lengths"] == 5
    assert {p: m["method"] for p, m in plan["methods"].items()} == \
        {1: "sideways_u", 2: "sideways_u"}
    one = [t for t, _bold in oc.page_lines(plan, 1)]
    assert one[0] == "CHANNEL: 2 lengths of Sideways U 2139"
    assert one[1] == ("SHARE A LENGTH: cut 2 x cap 523 from one end, then "
                      "page 2's 2 x cap 523 from the other end")
    from taf_order_app import worksheet_blocks as wb
    mark = wb.frame_lines(_line(1, 525, 790, 2, 50, "V-form"), "", None,
                          "sideways_u")
    assert mark[0][0].startswith("MARK AS SIDEWAYS U - use the FLIPPED")
    # A customer's asked-for way is kept, whatever it costs.
    asked = oc.order_plan([_line(1, 525, 790, 2, 50, "V-form"),
                           _line(2, 525, 815, 2, 50, "V-form")], prefer="u")
    assert {m["method"] for m in asked["methods"].values()} == {"u"}


def test_a_big_order_is_planned_quickly():
    import time
    lines = [_line(i, 300 + 17 * i, 500 + 23 * i, 1 + i % 4)
             for i in range(1, 21)]
    start = time.perf_counter()
    plan = oc.order_plan(lines)
    assert time.perf_counter() - start < 3.0
    assert plan["depths"][0]["lengths"] <= plan["depths"][0]["alone"]
