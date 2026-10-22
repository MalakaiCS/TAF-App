"""Who may do what on the noticeboard, and the how-to library."""
from __future__ import annotations

import datetime as _dt

from taf_order_app import staff_board as sb


def test_out_of_the_box_managers_post_and_directors_pin():
    rules = sb.rules_with_defaults([])
    assert not sb.may("post_board", "Employee", rules)
    assert sb.may("post_board", "Manager", rules)
    assert not sb.may("pin", "Manager", rules)
    assert sb.may("pin", "Director", rules) and sb.may("pin", "Admin", rules)
    assert sb.may("make_group", "Manager", rules)
    assert not sb.may("remove_any", "Manager", rules)


def test_rules_are_changed_and_nonsense_is_ignored():
    rules = sb.rules_with_defaults([
        {"action": "post_board", "min_role": "Employee"},
        {"action": "pin", "min_role": "Director"},      # not a choice
        {"action": "fly", "min_role": "Employee"}])
    assert sb.may("post_board", "Employee", rules)
    assert rules["pin"] == "Admin" and "fly" not in rules


def test_nobody_without_a_role_may_do_anything():
    assert not sb.may("post_board", "", {"post_board": "Employee"})
    assert not sb.may("anything", "Manager", {})
    assert sb.may("anything", "Director", {})


def test_when_a_message_was_sent():
    now = _dt.datetime(2026, 10, 16, 15, 0)
    assert sb.message_time("2026-10-16T10:42:00", now) == "10:42"
    assert sb.message_time("2026-10-14T08:05:00", now) == "Wed 08:05"
    assert sb.message_time("2026-10-01T08:05:00", now) == "01/10/2026"
    assert sb.message_time("garbage", now) == ""


SOPS = [
    {"id": "a", "title": "Making a V-form", "category": "Floor",
     "filter_type": "V-Form", "version": 3},
    {"id": "b", "title": "Bracing", "category": "Floor", "filter_type": "v-form",
     "version": 1},
    {"id": "c", "title": "Old way", "category": "Floor", "filter_type": "V-Form",
     "archived": True},
    {"id": "d", "title": "Answering the phone", "category": "", "version": 1},
    {"id": "e", "title": "Ordering media", "category": "Office", "version": 1},
]


def test_how_tos_for_a_filter_type():
    assert [s["id"] for s in sb.sops_for_type(SOPS, " v-form ")] == ["b", "a"]
    assert sb.sops_for_type(SOPS, "") == []


def test_how_tos_by_category_with_the_unfiled_last():
    got = [(c, [s["id"] for s in rows]) for c, rows in sb.by_category(SOPS)]
    assert got == [("Floor", ["b", "a"]), ("Office", ["e"]), ("Other", ["d"])]


def test_read_means_read_this_version():
    assert sb.read_state(SOPS[0], None) == "new"
    assert sb.read_state(SOPS[0], {"version": 2}) == "changed"
    assert sb.read_state(SOPS[0], {"version": 3}) == "read"


def test_who_has_read_it():
    reads = [{"sop_id": "a", "person": "Dave", "version": 3},
             {"sop_id": "a", "person": "Sam", "version": 2},
             {"sop_id": "b", "person": "Jo", "version": 1}]
    assert sb.sign_offs(SOPS[0], reads, ["Dave", "Sam", "Jo", "Kai"]) == {
        "read": ["Dave"], "behind": ["Sam"], "not": ["Jo", "Kai"]}


def test_a_video_link_is_a_web_address():
    assert sb.video_ok("https://youtu.be/x") and not sb.video_ok("javascript:x")
