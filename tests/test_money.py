"""Sales targets, a job's profit, and the order the van goes round in."""
from __future__ import annotations

import datetime as _dt

from taf_order_app import delivery as dl
from taf_order_app import money as mn

# Friday 16 October 2026. October has 22 working days; 12 are done by the end
# of today and 10 are left.
TODAY = _dt.date(2026, 10, 16)


def test_working_days_are_monday_to_friday():
    assert mn.working_days(_dt.date(2026, 10, 1), _dt.date(2026, 10, 31)) == 22
    assert mn.working_days(_dt.date(2026, 10, 17), _dt.date(2026, 10, 18)) == 0
    assert mn.working_days(_dt.date(2026, 10, 5), _dt.date(2026, 10, 1)) == 0


def test_how_the_month_is_going():
    p = mn.target_progress(30000, 60000, TODAY)
    assert p["percent"] == 50 and p["short"] == 30000
    assert p["days_left"] == 10 and p["per_day"] == 3000
    # 12 of 22 working days gone: on a straight line it should be $32,727.27.
    assert p["expected"] == 32727.27 and p["ahead"] == -2727.27
    assert not p["made_it"]
    assert mn.target_text(p, TODAY) == (
        "October: $30,000 of $60,000 (50%). $3,000 a day for the 10 working "
        "days left.")


def test_a_target_made_and_no_target():
    p = mn.target_progress(61000, 60000, TODAY)
    assert p["made_it"] and p["short"] == 0 and p["percent"] == 101
    assert mn.target_text(p, TODAY).endswith("Target made.")
    assert mn.target_progress(1000, 0, TODAY) is None
    assert mn.target_text(None, TODAY) == "No target set for October."


def test_the_last_day_of_the_month():
    last = _dt.date(2026, 10, 30)          # the last Friday
    p = mn.target_progress(50000, 60000, last)
    assert p["days_left"] == 0 and p["per_day"] == 10000
    assert "no working days left" in mn.target_text(p, last)


ORDER = {
    "id": "o1", "order_number": "PO-1", "customer_name": "Bells Creek",
    "header": {"Delivery Fee": 25},
    "items": [
        {"line_id": "a", "Filter Type": "V-Form", "Quantity": 10,
         "Unit Price": 40, "Part Number": "VF-1"},
        {"line_id": "b", "Filter Type": "Panel", "Quantity": 4,
         "Unit Price": 20, "Part Number": "PN-1"},
        {"line_id": "c", "item_kind": "catalogue", "Description": "Bag clip",
         "Quantity": 2, "Unit Price": 5, "Unit Cost": 1},
    ],
}
COSTS = {"VF-1": 15.0}                # the panel has no cost on file
TIMES = [{"order_id": "o1", "line_id": "a", "minutes": 90},
         {"order_id": "o1", "line_id": "a", "minutes": 30},
         {"order_id": "o1", "line_id": "", "minutes": 12},      # not a line
         {"order_id": "o2", "line_id": "a", "minutes": 999},    # another job
         {"order_id": "o1", "line_id": "b", "minutes": None}]   # still running


def test_a_jobs_profit_uses_the_timer_and_the_costs_on_file():
    j = mn.job_profit(ORDER, COSTS, {}, TIMES, {"panel": 6.0}, 60.0, 15.0)
    # Sold: 400 + 80 + 10 + 25 delivery.
    assert j["sold"] == 515 and j["delivery"] == 25
    # Materials: 150 for the V-forms, 2 for the clips; the panel is not costed.
    assert j["materials"] == 152 and j["uncosted"] == 1
    # Labour: 120 timed on a, 12 loose, 4 x 6 estimated on b, none on bought-in.
    assert j["minutes"] == 156 and j["labour"] == 156 and j["estimated"]
    assert j["profit"] == 515 - 152 - 156 and j["percent"] == round(207 / 515 * 100, 1)
    a, b, c = j["lines"]
    assert (a["minutes"], a["estimated"]) == (120, False)
    assert (b["minutes"], b["estimated"], b["materials"]) == (24, True, None)
    assert c["minutes"] == 0 and c["type"] == "Bag clip"


def test_an_unpriced_line_is_counted_not_sold_for_nothing():
    order = {"id": "o3", "items": [{"Filter Type": "Panel", "Quantity": 2}]}
    j = mn.job_profit(order, {}, {}, [], {}, 60.0, 15.0)
    assert j["unpriced"] == 1 and j["sold"] == 0 and j["percent"] is None


def test_profit_added_up_by_customer_and_by_type():
    one = mn.job_profit(ORDER, COSTS, {}, TIMES, {"panel": 6.0}, 60.0, 15.0)
    two = mn.job_profit({**ORDER, "id": "o2", "customer_name": "Tweed"}, COSTS,
                        {}, [], {"panel": 6.0, "v-form": 10.0}, 60.0, 15.0)
    by_customer = mn.profit_by([one, two])
    assert [g["name"] for g in by_customer] == ["Tweed", "Bells Creek"]
    assert by_customer[1]["profit"] == one["profit"]
    by_type = {g["name"]: g for g in mn.profit_by([one, two], "type")}
    assert by_type["V-Form"]["jobs"] == 2 and by_type["V-Form"]["sold"] == 800
    assert by_type["V-Form"]["minutes"] == 220            # 120 timed, 100 usual


def test_customer_address_for_the_map():
    c = {"delivery_address1": "1 Smith St", "delivery_address2": "",
         "delivery_city": "Hillcrest", "delivery_state": "QLD",
         "delivery_postcode": "4118"}
    assert dl.address_text(c) == "1 Smith St, Hillcrest QLD 4118"
    assert dl.address_text({}) == "" and dl.address_text(None) == ""


STOPS = [
    {"id": "1", "region": "Gold Coast", "address": "Southport QLD 4215", "customer": "B"},
    {"id": "2", "region": "Local", "address": "Loganholme QLD 4129", "customer": "A"},
    {"id": "3", "region": "Pick Up", "address": "", "customer": "C"},
    {"id": "4", "region": "Local", "address": "Hillcrest QLD 4118", "customer": "D"},
    {"id": "5", "region": "Freight", "address": "", "customer": "E"},
]


def test_a_route_is_suggested_by_region_then_postcode_without_pickups():
    assert [s["id"] for s in dl.suggest_route(STOPS)] == ["4", "2", "1", "5"]


def test_a_saved_route_keeps_its_order_and_takes_in_new_work():
    got = dl.apply_route(STOPS, ["1", "gone", "4", "1"])
    assert [s["id"] for s in got] == ["1", "4", "2", "5"]


def test_maps_links_go_round_and_come_back():
    links = dl.maps_links("Base, QLD 4118", ["A St", "", "B St"])
    assert links == [dl.MAPS + "&origin=Base%2C%20QLD%204118&destination="
                     "Base%2C%20QLD%204118&travelmode=driving&waypoints=A%20St%7CB%20St"]
    assert dl.maps_links("Base", []) == []


def test_a_long_run_is_several_links_each_from_the_last_stop():
    links = dl.maps_links("Base", [f"S{i}" for i in range(12)])
    assert len(links) == 2
    assert "origin=Base&destination=S9" in links[0] and "S8" in links[0]
    assert "origin=S9&destination=Base" in links[1] and "S10%7CS11" in links[1]


def test_the_run_sheet_follows_a_saved_route():
    a = {"db_id": "a", "location": "Local", "customer": "A"}
    b = {"db_id": "b", "location": "Gold Coast", "customer": "B"}
    c = {"db_id": "c", "location": "Pick Up", "customer": "C"}
    grouped = dl.group_by_region([a, b, c])
    assert dl.route_grouped(grouped, []) == grouped
    got = dl.route_grouped(grouped, ["b", "a"])
    assert [(h, [o["db_id"] for o in rows]) for h, rows in got] == [
        ("The run, in order", ["b", "a"]), ("Pick Up", ["c"])]


def test_a_database_time_shown_on_this_computer():
    assert mn.local_when("2026-10-17T00:42:00") == "17/10/2026 00:42"
    assert mn.local_when("not a time") == "" and mn.local_when(None) == ""
