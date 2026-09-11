"""Working out how to make a filter.

The anchor for all of this is a real worksheet: O/N 12576, a 295 x 310 in F5,
which prints all three ways of making it. If the numbers below ever stop
matching that sheet, the calculator is wrong and the sheet is right.

The rest is about the saw blade. A calculator that adds up piece lengths and
divides by 2440 will tell somebody they get seven frames out of a stick and
an offcut long enough for a cap, and they will get seven frames and an offcut
that is 20mm short, because six cuts at 3mm went on the floor. That is the
difference between a tool people use and a tool people stop believing.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import cutting as _cut     # noqa: E402


# ── Against the worksheet ────────────────────────────────────────────────────

def test_the_u_matches_the_worksheet():
    """O/N 12576, marks 20 / 313 / 621 / 914 / 934, cap 308."""
    out = _cut.layout(295, 310, "u")
    assert out["marks"] == [20, 313, 621, 914, 934]
    assert out["cap"] == 308
    assert out["frame"] == 934


def test_the_sideways_u_matches_the_worksheet():
    """Marks 20 / 328 / 621 / 929 / 949, cap 293."""
    out = _cut.layout(295, 310, "sideways_u")
    assert out["marks"] == [20, 328, 621, 929, 949]
    assert out["cap"] == 293


def test_the_g_matches_the_worksheet():
    """Marks 308 / 601 / 909 / 1202 / 1222, and no cap."""
    out = _cut.layout(295, 310, "g")
    assert out["marks"] == [308, 601, 909, 1202, 1222]
    assert out["cap"] == 0


def test_the_cap_is_the_size_less_the_allowance():
    """Not the nominal size. A cap cut at 310 on a 310 side does not go in."""
    assert _cut.layout(295, 310, "u")["cap"] == 308          # long  - 2
    assert _cut.layout(295, 310, "sideways_u")["cap"] == 293  # short - 2


def test_every_side_is_cut_two_short():
    out = _cut.layout(295, 310, "u")
    assert out["segments"] == [20, 293, 308, 293, 20]


def test_the_lip_does_not_change_with_anything():
    """Twenty each end, whatever the filter is."""
    for short, long in ((100, 100), (295, 310), (595, 495)):
        for method in ("u", "sideways_u"):
            segs = _cut.layout(short, long, method)["segments"]
            assert segs[0] == 20 and segs[-1] == 20
        assert _cut.layout(short, long, "g")["segments"][-1] == 20


def test_the_marks_are_cumulative():
    """A tape is pulled out once and every mark struck off it. Measuring each
    segment from the last pencil line turns a 1mm error into a 4mm one."""
    out = _cut.layout(295, 310, "u")
    running = 0
    for segment, mark in zip(out["segments"], out["marks"]):
        running += segment
        assert mark == running


# ── The blade ────────────────────────────────────────────────────────────────

def test_the_blade_is_counted():
    """334mm frames: 2440/334 is 7.3, and seven of them plus six cuts at 3mm
    is 2356, which fits. Eight never did."""
    assert _cut.per_stick(334) == 7
    assert _cut.per_stick(334, {"kerf_mm": 0}) == 7
    # 305mm: eight fit with no blade (2440), seven once the blade is counted.
    assert _cut.per_stick(305, {"kerf_mm": 0}) == 8
    assert _cut.per_stick(305, {"kerf_mm": 3}) == 7


def test_the_blade_comes_off_the_offcut_too():
    """The last piece still has to be cut free, so the offcut is short by the
    width of one more cut. This is exactly where a calculator promises an
    offcut that is not on the rack when you go and look."""
    out = _cut.pack([1000, 1000], {"kerf_mm": 3})
    stick = out["lengths"][0]
    # 2440 - (1000 + 3 + 1000) = 437 on the stick, less one more cut.
    assert stick["offcut"] == 434


def test_a_piece_longer_than_a_stick_is_reported_not_guessed():
    out = _cut.best(1200, 1200, 1)
    assert out["ok"] is False
    assert "2440" in out["why"] and "not come off" in out["why"]


# ── The rack ─────────────────────────────────────────────────────────────────

def test_short_offcuts_are_scrap_and_long_ones_are_kept():
    """400mm is the line. A bin of 300mm pieces nobody wrote down is where
    the money actually goes."""
    keep = _cut.pack([1000], {"keep_offcut_mm": 400})["lengths"][0]
    assert keep["keep"] is True and keep["offcut"] == 1437
    tight = _cut.pack([2100], {"keep_offcut_mm": 400})["lengths"][0]
    assert tight["offcut"] == 337 and tight["keep"] is False


def test_what_is_on_the_rack_is_used_before_a_new_length():
    """A 900mm piece nobody reaches for is a 900mm piece that gets thrown
    out."""
    out = _cut.pack([308, 308], offcuts=[900])
    assert out["sticks"] == 0, "it opened a new length with the rack full"
    assert out["from_rack"] == 1


def test_the_rack_is_worked_longest_first():
    out = _cut.pack([934], offcuts=[500, 1300])
    used = [b for b in out["lengths"] if b["pieces"]]
    assert used[0]["length"] == 1300


# ── Which way to make it ─────────────────────────────────────────────────────

def test_the_answer_changes_with_the_size():
    """This is the whole reason it is a program. At 100 x 100 the U gets
    seven frames off a stick where the G gets five; at 300 x 300 the G lands
    almost exactly on 2440 twice and the U is nowhere near."""
    small = _cut.best(100, 100, 21)
    assert small["best"]["method"] in ("u", "sideways_u")
    big = _cut.best(300, 300, 10)
    assert big["best"]["method"] == "g"


def test_it_says_what_it_turned_down():
    """Somebody who can see it was close will overrule it when the rack says
    otherwise. Somebody told only the answer either follows it blindly or
    ignores it."""
    why = _cut.best(300, 300, 10)["why"]
    assert "G" in why and "U would be" in why


def test_a_square_is_not_offered_the_same_answer_twice():
    """On a square the U and the sideways U are the same strip cut the same
    way. "U - same as Sideways U" tells nobody anything."""
    out = _cut.best(100, 100, 10)
    shapes = [(o["shape"]["frame"], o["shape"]["cap"])
              for o in [out["best"]] + out["others"]]
    assert len(shapes) == len(set(shapes))
    assert "same as" not in out["why"]


def test_a_rectangle_still_offers_both_ways_round():
    out = _cut.best(295, 310, 12)
    methods = {o["method"] for o in [out["best"]] + out["others"]}
    assert {"u", "sideways_u", "g"} <= methods


def test_fewer_sticks_beats_less_channel():
    """A G uses less channel per filter than a U and its cap, and still loses
    when it wastes the end of every stick. Counting material rather than
    lengths is the mistake this exists to avoid."""
    out = _cut.best(100, 100, 21)
    won = out["best"]
    beaten = [o for o in out["others"] if o["method"] == "g"][0]
    assert won["channel_each"] > beaten["channel_each"]
    assert won["sticks"] < beaten["sticks"]


# ── A whole job ──────────────────────────────────────────────────────────────

def test_a_job_adds_up():
    out = _cut.plan([{"short": 100, "long": 100, "qty": 21},
                     {"short": 300, "long": 300, "qty": 10}])
    assert all(line["ok"] for line in out["lines"])
    assert out["sticks"] == 4 + 5
    assert 0 <= out["scrap_pct"] <= 100


def test_a_line_that_cannot_be_made_does_not_take_the_job_with_it():
    out = _cut.plan([{"short": 100, "long": 100, "qty": 2},
                     {"short": 1200, "long": 1200, "qty": 1}])
    assert out["lines"][0]["ok"] is True
    assert out["lines"][1]["ok"] is False
    assert out["sticks"] == 1


def test_it_reads_the_app_s_own_line_shape():
    """Order lines come through as Short / Long / Quantity, so a cut list
    can be worked out from an order without anything in between."""
    out = _cut.plan([{"Short": 295, "Long": 310, "Quantity": 4}])
    assert out["lines"][0]["ok"] is True


# ── The workshop's numbers ───────────────────────────────────────────────────

def test_the_stick_length_is_not_hard_coded():
    """A different supplier delivers a different length and everything below
    changes with it."""
    assert _cut.per_stick(600, {"stick_length_mm": 2440}) == 4
    assert _cut.per_stick(600, {"stick_length_mm": 6000}) == 9


def test_a_filter_smaller_than_the_allowance_is_refused():
    try:
        _cut.layout(1, 1, "g")
    except ValueError as exc:
        assert "allowance" in str(exc)
    else:
        raise AssertionError("it cut a filter with negative sides")


def test_nothing_prints_a_rounding_error():
    """A worksheet with 934.0000001 on it makes the whole sheet look wrong."""
    for value in _cut.layout(295, 310, "u")["marks"]:
        assert isinstance(value, int)
