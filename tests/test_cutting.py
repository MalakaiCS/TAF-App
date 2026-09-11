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


# ── The lip, and what it buys ────────────────────────────────────────────────

def test_two_frames_onto_one_stick_by_shortening_the_lip():
    """Two G frames of a 295 x 310 are 2444 against a 2440 stick - four
    millimetres over. Two off each lip and they are 2440 exactly, with
    nothing on the floor. This is the whole rule."""
    out = _cut.frames_per_stick(295, 310, "g")
    assert out["n"] == 2
    assert out["lip"] == 18
    assert out["frame"] == 1220
    assert out["shortened"] is True
    assert out["frame"] * 2 == 2440


def test_the_lip_is_only_ever_shortened_to_win_a_frame():
    """Trimming it for nothing would be a smaller lip on every filter we make
    in exchange for an offcut that was going in the bin anyway."""
    # A 100 x 100 U is 334: seven fit at the full lip with 102 to spare, and
    # an eighth is far out of reach.
    out = _cut.frames_per_stick(100, 100, "u")
    assert out["n"] == 7
    assert out["lip"] == 20
    assert out["shortened"] is False


def test_a_lip_is_never_taken_below_what_closes_the_filter():
    out = _cut.frames_per_stick(295, 310, "g", {"min_lip_mm": 19})
    assert out["n"] == 1, "it shortened the lip past what will fold down"
    assert out["lip"] == 20


def test_a_lip_that_will_not_close_is_refused_outright():
    try:
        _cut.layout(295, 310, "g", None, lip=4)
    except ValueError as exc:
        assert "close" in str(exc)
    else:
        raise AssertionError("it cut a lip too short to fold down")


def test_shortening_moves_the_marks():
    """The marks are what somebody strikes off the tape. A shortened lip that
    still printed 1222 would have them cut it at the old length."""
    full = _cut.layout(295, 310, "g")
    short = _cut.layout(295, 310, "g", None, lip=18)
    assert full["marks"][-1] == 1222
    assert short["marks"][-1] == 1220
    assert short["marks"][:-1] == full["marks"][:-1],         "shortening the lip moved a side as well"


def test_a_part_full_stick_keeps_the_full_lip():
    """Nothing is won by trimming the lip on the odd one at the end."""
    out = _cut.best(295, 310, 3)["best"]
    last = out["frame_sticks"][-1]
    assert last["lip"] == 20, "it shortened a lip for no gain"


# ── The blade ────────────────────────────────────────────────────────────────

def test_the_blade_takes_nothing_unless_it_is_told_to():
    """A frame is not cut into pieces at its marks: the 45 degree notches and
    the lip cut come off the flanges, not the running length. The only cut
    through the channel is between one strip and the next."""
    assert _cut.DEFAULTS["kerf_mm"] == 0
    assert _cut.per_stick(305) == 8            # 8 x 305 is exactly 2440
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
    assert keep["keep"] is True and keep["offcut"] == 1440
    tight = _cut.pack([2100], {"keep_offcut_mm": 400})["lengths"][0]
    assert tight["offcut"] == 340 and tight["keep"] is False


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
    seven frames off a stick against the G's five at a full lip; at 300 x 300
    the G lands almost exactly on 2440 twice and the U is nowhere near."""
    assert _cut.frames_per_stick(100, 100, "u")["n"] == 7
    assert _cut.frames_per_stick(300, 300, "g")["n"] == 2
    assert _cut.best(300, 300, 10)["best"]["method"] == "g"
    assert _cut.best(100, 100, 50)["best"]["method"] in ("u", "sideways_u")


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
    out = _cut.best(100, 100, 50)
    won = out["best"]
    beaten = [o for o in out["others"] if o["method"] == "g"][0]
    assert won["channel_each"] > beaten["channel_each"], \
        "the winner was not the one using more channel"
    assert won["sticks"] <= beaten["sticks"]


# ── A whole job ──────────────────────────────────────────────────────────────

def test_a_job_adds_up():
    out = _cut.plan([{"short": 100, "long": 100, "qty": 21},
                     {"short": 300, "long": 300, "qty": 10}])
    assert all(line["ok"] for line in out["lines"])
    assert out["sticks"] == sum(line["answer"]["best"]["sticks"]
                                for line in out["lines"])
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
    assert _cut.per_stick(600, {"stick_length_mm": 6000}) == 10


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


# ── Which marks belong to which length ───────────────────────────────────────

def test_a_single_frame_keeps_the_full_lip_and_its_own_marks():
    """The shape that fits most onto a stick is not the shape of a part-full
    one. Two G frames of a 295 x 310 share a stick at a lip of 18 and a last
    mark of 1220; one on its own is the full 20 and 1222. Printing 1220
    against a single filter has somebody cut it two short for nothing."""
    one = _cut.best(295, 310, 1)
    g = [o for o in [one["best"]] + one["others"] if o["method"] == "g"][0]
    assert g["frame_sticks"][0]["lip"] == 20
    assert g["frame_sticks"][0]["marks"][-1] == 1222

    two = _cut.best(295, 310, 2)["best"]
    assert two["frame_sticks"][0]["lip"] == 18
    assert two["frame_sticks"][0]["marks"][-1] == 1220


def test_every_length_carries_the_marks_it_is_cut_to():
    """Three of them: two share a stick with the lip trimmed, the third is on
    its own and does not."""
    out = _cut.best(295, 310, 3, {"lip_mm": 20})
    g = [o for o in out["options"] if o["method"] == "g"][0]
    assert [len(b["pieces"]) for b in g["frame_sticks"]] == [2, 1]
    assert g["frame_sticks"][0]["marks"][-1] == 1220
    assert g["frame_sticks"][1]["marks"][-1] == 1222


# ── What the customer asked for ──────────────────────────────────────────────

def test_a_customer_s_preference_is_not_overruled():
    """A filter made the cheap way and sent back is not a saving."""
    free = _cut.best(300, 300, 10)
    assert free["best"]["method"] == "g"
    forced = _cut.best(300, 300, 10, prefer="u")
    assert forced["best"]["method"] == "u"
    assert forced["forced"] is True


def test_what_the_preference_costs_is_said_out_loud():
    """Taken out of somebody's hands quietly is how a preference nobody
    remembers setting ends up costing a stick a week for a year."""
    forced = _cut.best(300, 300, 10, prefer="u")
    assert "asked for" in forced["why"]
    assert "would have been 5" in forced["why"]


def test_a_preference_that_is_already_the_cheapest_is_not_flagged():
    out = _cut.best(300, 300, 10, prefer="g")
    assert out["forced"] is False
    assert "asked for" not in out["why"]


# ── Near a size we already make ──────────────────────────────────────────────

def test_two_millimetres_off_something_we_run_every_week():
    known = [{"short": 595, "long": 495, "seen": 40},
             {"short": 295, "long": 310, "seen": 6}]
    close = _cut.near_standard(597, 497, known)
    assert close and close[0]["short"] == 595 and close[0]["off_by"] == 2


def test_the_size_itself_is_not_offered_back():
    known = [{"short": 595, "long": 495, "seen": 40}]
    assert _cut.near_standard(595, 495, known) == []


def test_something_genuinely_different_is_left_alone():
    known = [{"short": 595, "long": 495, "seen": 40}]
    assert _cut.near_standard(300, 300, known) == []


def test_the_closest_comes_first_then_the_one_made_most():
    known = [{"short": 596, "long": 496, "seen": 1},
             {"short": 595, "long": 495, "seen": 90},
             {"short": 594, "long": 494, "seen": 3}]
    close = _cut.near_standard(597, 497, known)
    assert close[0]["short"] == 596          # 1mm out beats 2mm out
    assert close[1]["short"] == 595          # both 2-3mm, this one is made more


def test_a_rubbish_row_does_not_stop_the_rest():
    known = [{"short": "", "long": None, "seen": "x"},
             {"short": 595, "long": 495, "seen": 40}]
    assert len(_cut.near_standard(597, 497, known)) == 1
