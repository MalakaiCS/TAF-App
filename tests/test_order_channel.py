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
