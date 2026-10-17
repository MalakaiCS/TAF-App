"""Who is in, and whether a day is already full."""
from __future__ import annotations

import datetime as _dt

from taf_order_app import planning

FRI = _dt.date(2026, 10, 16)
MON = _dt.date(2026, 10, 19)
WORKSHOP = {"minutes_per_filter": 15, "making_share": 0.5}
ROSTER = [
    {"person": "Dave", "days": [1, 2, 3, 4, 5], "hours": 8, "makes": True},
    {"person": "Amy", "days": [1, 2, 3, 4, 5], "hours": 8, "makes": True},
    {"person": "Office", "days": [1, 2, 3, 4, 5], "hours": 8, "makes": False},
    {"person": "Gone", "days": [1, 2, 3, 4, 5], "hours": 8, "active": False},
]
RATES = [{"filter_type": "V-Form", "minutes_each": 20}]


def _order(due, *lines, status="Pending", oid="o"):
    return {"id": oid, "date_due": due, "header": {"status": status},
            "items": list(lines)}


def test_a_day_is_the_hours_of_those_in_making():
    room = planning.available(FRI, ROSTER, [], [], 0.5)
    assert room == {"minutes": 480.0, "in": ["Dave", "Amy"], "away": [], "shut": ""}
    leave = [{"person": "amy", "first_day": "2026-10-15", "last_day": "16/10/2026"}]
    room = planning.available(FRI, ROSTER, leave, [], 0.5)
    assert (room["minutes"], room["away"]) == (240.0, ["Amy"])
    shut = planning.available(FRI, ROSTER, [], [{"day": "2026-10-16",
                                                 "name": "Show day"}], 0.5)
    assert (shut["minutes"], shut["shut"]) == (0.0, "Show day")
    assert planning.available(_dt.date(2026, 10, 17), ROSTER, [], [], 0.5)["minutes"] == 0


def test_what_is_booked_is_what_is_left_to_make_that_day():
    orders = [
        _order("16/10/2026", {"Filter Type": "V-Form", "Quantity": 6},
               {"Filter Type": "V-Form", "Quantity": 4, "made": True}),
        _order("16/10/26", {"Filter Type": "Flat Panel", "Quantity": "2"}),
        _order("16/10/2026", {"Filter Type": "V-Form", "Quantity": 9},
               status="Complete"),
        _order("19/10/2026", {"Filter Type": "V-Form", "Quantity": 9}),
        _order("16/10/2026", {"item_kind": "catalogue", "Quantity": 50}),
    ]
    rates = planning.rate_map(RATES)
    assert planning.booked_minutes(orders, FRI, rates, 15) == 6 * 20 + 2 * 15


def test_a_new_order_on_a_full_day_says_so_and_finds_room():
    orders = [_order("16/10/2026", {"Filter Type": "V-Form", "Quantity": 22})]
    new = [{"Filter Type": "Flat Panel", "Quantity": 4}]
    got = planning.check_due("16/10/2026", new, orders, RATES, ROSTER, [], [], WORKSHOP)
    assert got["full"] and got["booked"] == 440 and got["need"] == 60
    assert got["minutes"] == 480 and got["next_free"] == MON
    text = planning.describe(got)
    assert text.startswith("Friday 16/10 is already full: 7.3 h booked, and this "
                           "order adds 1 h, against 8 h with 2 in.")
    assert text.endswith("Monday 19/10 has room.")
    ok = planning.check_due("16/10/2026", [{"Filter Type": "V-Form", "Quantity": 2}],
                            orders, RATES, ROSTER, [], [], WORKSHOP)
    assert not ok["full"] and ok["next_free"] is None     # 440 + 40 = 480: fits


def test_nothing_is_said_without_a_date_or_a_roster():
    assert planning.check_due("ASAP", [], [], RATES, ROSTER, [], [], WORKSHOP) is None
    assert planning.check_due("16/10/2026", [], [], RATES, [], [], [], WORKSHOP) is None


def test_the_order_being_changed_is_not_counted_twice():
    orders = [_order("16/10/2026", {"Filter Type": "V-Form", "Quantity": 21}, oid="me")]
    got = planning.check_due("16/10/2026", [{"Filter Type": "V-Form", "Quantity": 21}],
                             orders, RATES, ROSTER, [], [], WORKSHOP, skip_id="me")
    assert got["booked"] == 0 and not got["full"]


def test_days_are_typed_the_way_people_say_them():
    assert planning.parse_days("Mon-Fri") == [1, 2, 3, 4, 5]
    assert planning.parse_days("mon wed, FRI") == [1, 3, 5]
    assert planning.parse_days("1,2 7") == [1, 2, 7]
    assert planning.days_text([1, 2, 3, 4, 5]) == "Mon-Fri"
    assert planning.days_text([5, 1, 3]) == "Mon Wed Fri"
    assert planning.days_text([]) == ""


def test_a_repeat_order_starts_fresh():
    old = [{"Filter Type": "V-Form", "Quantity": 2, "made": True, "made_by": "Dave",
            "made_at": "x", "qc": {"passed": True}, "line_id": "L1",
            "Unit Price": 50}]
    assert planning.repeat_items(old) == [
        {"Filter Type": "V-Form", "Quantity": 2, "Unit Price": 50}]


def test_the_fortnight_ahead_shows_who_is_in_and_what_is_booked():
    orders = [_order("19/10/2026", {"Filter Type": "V-Form", "Quantity": 3})]
    leave = [{"person": "Dave", "first_day": "2026-10-19", "last_day": "2026-10-19"}]
    view = planning.week_view(FRI, orders, RATES, ROSTER, leave, [], WORKSHOP, days=3)
    assert [v["day"] for v in view] == [FRI, MON, _dt.date(2026, 10, 20)]
    assert view[1]["in"] == ["Amy"] and view[1]["away"] == ["Dave"]
    assert view[1]["booked"] == 60 and view[1]["minutes"] == 240
