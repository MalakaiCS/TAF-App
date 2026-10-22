"""The factory floor: the TV board, quality checks, faults and timings."""
from __future__ import annotations

import datetime as _dt

from taf_order_app import floor

TODAY = _dt.date(2026, 10, 16)          # a Friday


def _order(**kw):
    row = {"id": kw.pop("id", "o"), "customer_name": kw.pop("customer", "Bells"),
           "order_number": kw.pop("no", "1"), "date_due": kw.pop("due", "16/10/2026"),
           "n_items": kw.pop("lines", 4), "n_made": kw.pop("made", 0),
           "archived": kw.pop("archived", False), "header": {}}
    row["header"].update(kw)
    return row


def test_each_order_is_in_one_column():
    col = lambda **kw: floor.board_column(_order(**kw), TODAY)
    assert col() == "to_cut"
    assert col(stages={"marked": True}) == "to_cut"
    assert col(stages={"cut": True}) == "making"
    assert col(made=1) == "making"
    assert col(status="In Production") == "making"
    assert col(stages={"cut": True, "packed": True}) == "packed"
    assert col(status="Complete") == "packed"
    assert col(archived=True) == ""


def test_out_the_door_is_only_what_went_today():
    col = lambda **kw: floor.board_column(_order(**kw), TODAY)
    # Stamped by the database in UTC: 2am the next day in UTC is still
    # "today" wherever the clock is behind it - here the tests run in UTC.
    assert col(status="Dispatched", status_at="2026-10-16T03:00:00Z") == "out"
    assert col(status="Dispatched", status_at="2026-10-15T03:00:00Z") == ""
    # Before step 44, the day it was due stands in.
    assert col(status="Delivered") == "out"
    assert col(status="Collected", due="10/10/2026") == ""


def test_the_board_shows_todays_work_in_the_order_to_do_it():
    rows = [
        _order(id="a", customer="Zeta", due="16/10/2026"),
        _order(id="b", customer="Alpha", due="19/10/2026"),     # Monday: next working day
        _order(id="c", customer="Bravo", due="20/10/2026"),     # too far ahead
        _order(id="d", customer="Late", due="14/10/2026"),
        _order(id="e", customer="Rush", due="16/10/2026", priority=True),
        _order(id="f", customer="Started", due="30/10/2026", made=2),
        _order(id="g", customer="NoDate", due="ASAP"),
    ]
    cols = {c["key"]: c for c in floor.production_board(rows, TODAY)}
    assert [c["key"] for c in floor.production_board([], TODAY)] == \
        ["to_cut", "making", "packed", "out"]
    assert [c["id"] for c in cols["to_cut"]["cards"]] == ["e", "d", "a", "b"]
    assert cols["to_cut"]["cards"][1]["late"] and cols["to_cut"]["cards"][2]["today"]
    assert [c["id"] for c in cols["making"]["cards"]] == ["f"]
    assert floor.working_days_on(TODAY, 1) == _dt.date(2026, 10, 19)
    assert [c["id"] for c in floor.production_board(rows, TODAY, ahead=2)[0]["cards"]] \
        == ["e", "d", "a", "b", "c"]


def test_each_filter_type_has_its_checks_or_the_general_ones():
    lists = {"V-Form": ["Pleats even", "Brace in"], "*": ["Size checked"]}
    assert floor.checks_for("v-form", lists) == ["Pleats even", "Brace in"]
    assert floor.checks_for("Flat Panel", lists) == ["Size checked"]
    assert floor.checks_for("Flat Panel", {"V-Form": ["x"]}) == []
    assert floor.qc_record(["Size checked"], "Dave", "16/10/2026 09:00") == {
        "passed": True, "checks": ["Size checked"], "by": "Dave",
        "at": "16/10/2026 09:00"}


def test_checks_are_typed_one_a_line():
    assert floor.parse_checks("- Size checked\n\n  Pleats   even\nsize CHECKED\n• Label on") \
        == ["Size checked", "Pleats even", "Label on"]


def test_faults_add_up_into_patterns():
    rows = [
        {"reason": "Wrong size", "filter_type": "V-Form", "made_by": "Dave",
         "found": "qc", "quantity": 2, "created_at": "2026-10-10T00:00:00Z"},
        {"reason": "Wrong size", "filter_type": "Flat Panel", "made_by": "Amy",
         "found": "returned", "quantity": 1, "created_at": "2026-10-12T00:00:00Z"},
        {"reason": "Media damaged", "filter_type": "V-Form", "made_by": "Dave",
         "found": "qc", "created_at": "2026-10-14T00:00:00Z"},
        {"reason": "Old", "created_at": "2026-01-01T00:00:00Z"},
    ]
    got = floor.fault_patterns(rows, since=_dt.date(2026, 10, 1))
    assert got["total"] == 4
    assert got["by_reason"] == [{"name": "Wrong size", "count": 3},
                                {"name": "Media damaged", "count": 1}]
    assert got["by_type"][0] == {"name": "V-Form", "count": 3}
    assert got["by_maker"][0] == {"name": "Dave", "count": 3}
    assert got["by_found"] == [{"name": "Found in QC", "count": 3},
                               {"name": "Came back", "count": 1}]


def test_minutes_read_as_people_say_them():
    assert floor.minutes_text(4) == "4 min"
    assert floor.minutes_text(4.5) == "4.5 min"
    assert floor.minutes_text(25.4) == "25 min"
    assert floor.minutes_text(65) == "1 h 05 min"
    assert floor.minutes_text("x") == ""


def test_the_customer_sees_the_finished_job_on_their_portal():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    sql = (root / "migrate_floor.sql").read_text(encoding="utf-8")
    page = (root / "docs" / "portal" / "index.html").read_text(encoding="utf-8")
    assert "'photos'" in sql and "f.kind = 'finished'" in sql
    assert "o.photos" in page and "/storage/v1/object/public/job-photos/" in page


def test_the_phone_has_the_same_fault_reasons():
    import json
    import re
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "docs" / "app"
          / "screens.js").read_text(encoding="utf-8")
    got = re.search(r"var FAULT_REASONS = (\[.*?\]);", js, re.S).group(1)
    assert json.loads(got) == floor.FAULT_REASONS
