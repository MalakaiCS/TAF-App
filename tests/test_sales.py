"""Chasing quotes, why they are lost, filter-change reminders, price changes
and who owes what."""
from __future__ import annotations

import datetime as _dt

from taf_order_app import sales

TODAY = _dt.date(2026, 10, 16)


def test_only_quotes_waiting_a_week_and_not_just_chased_are_chased():
    quotes = [
        {"id": "a", "status": "sent", "sent_at": "2026-10-01T00:00:00Z"},
        {"id": "b", "status": "viewed", "sent_at": "2026-10-08T00:00:00Z"},
        {"id": "c", "status": "sent", "sent_at": "2026-10-12T00:00:00Z"},
        {"id": "d", "status": "accepted", "sent_at": "2026-09-01T00:00:00Z"},
        {"id": "e", "status": "sent", "sent_at": "2026-09-20T00:00:00Z",
         "chased_at": "2026-10-14T00:00:00Z"},
        {"id": "f", "status": "sent", "sent_at": "2026-09-20T00:00:00Z",
         "chased_at": "2026-10-05T00:00:00Z"},
    ]
    got = sales.to_chase(quotes, TODAY)
    assert [q["id"] for q in got] == ["f", "a", "b"]
    assert got[0]["waited"] == 26


def test_a_chase_is_written_ready_to_send():
    mail = sales.chase_email({"quote_number": "Q-1041", "total": 1287.5},
                             "https://x/quote/?t=abc", contact="Dave Nguyen")
    assert mail["subject"] == "Quote Q-1041 from Total Air Filtration"
    assert mail["body"].startswith("Hi Dave,\n\nJust following up on our quote "
                                   "Q-1041 ($1,287.50 inc GST).")
    assert "https://x/quote/?t=abc" in mail["body"]
    link = sales.mailto("dave@site.com", mail["subject"], "a b&c")
    assert link == ("mailto:dave@site.com?subject=Quote%20Q-1041%20from%20Total"
                    "%20Air%20Filtration&body=a%20b%26c")


def test_lost_quotes_add_up_by_reason():
    quotes = [
        {"status": "accepted", "total": 1000, "responded_at": "2026-10-01"},
        {"status": "declined", "total": 500, "lost_reason": "Price",
         "responded_at": "2026-10-02"},
        {"status": "declined", "total": 300, "lost_reason": "Price",
         "responded_at": "2026-10-03"},
        {"status": "expired", "total": 50, "updated_at": "2026-10-04"},
        {"status": "declined", "total": 9, "lost_reason": "Price",
         "responded_at": "2025-01-01"},
        {"status": "sent", "total": 70},
    ]
    got = sales.lost_report(quotes, since=_dt.date(2026, 1, 1))
    assert (got["won"], got["lost"], got["lost_value"]) == (1, 3, 850)
    assert got["win_rate"] == 0.25
    assert got["reasons"] == [{"name": "Price", "count": 2, "value": 800},
                              {"name": "Not given", "count": 1, "value": 50}]


def test_customers_due_for_a_filter_change():
    customers = [
        {"name": "Bells Creek", "short_name": "Bells", "service_weeks": 12},
        {"name": "Tweed", "service_weeks": 26},
        {"name": "Snoozed", "service_weeks": 4, "service_snoozed_until": "2026-11-01"},
        {"name": "Never", "service_weeks": None},
        {"name": "No orders", "service_weeks": 4},
    ]
    orders = [
        {"customer_name": "Bells", "date_ordered": "20/07/2026"},
        {"customer_name": "Bells Creek", "date_ordered": "01/06/2026"},
        {"customer_name": "Tweed", "date_ordered": "01/09/2026"},
        {"customer_name": "Snoozed", "date_ordered": "01/01/2026"},
        {"customer_name": "Never", "date_ordered": "01/01/2026"},
    ]
    got = sales.service_due(customers, orders, TODAY)
    assert [(r["customer"]["name"], r["due"].isoformat(), r["late"]) for r in got] \
        == [("Bells Creek", "2026-10-12", 4)]
    soon = sales.service_due(customers, orders, TODAY, ahead=200)
    assert [r["customer"]["name"] for r in soon] == ["Bells Creek", "Tweed"]


def test_a_price_change_rounds_to_the_cent_and_leaves_blank_tiers_blank():
    assert sales.new_price(10, 3.5) == 10.35
    assert sales.new_price(18.5, 4) == 19.24
    assert sales.new_price(None, 10) is None
    assert sales.new_price(100, -10) == 90.0


def test_a_price_change_preview_is_what_it_will_change():
    lists = [{"part_number": "TAF-G4-595", "name": "Panel G4", "unit_price": 20,
              "unit_price_2": 18, "unit_price_3": None},
             {"part_number": "BAG-F7", "name": "Bag F7", "unit_price": 50}]
    rates = [{"filter_type": "V-Form", "media_type": "G4", "rate_per_sqm": 30,
              "rate_per_sqm_2": None, "rate_per_sqm_3": 25}]
    got = sales.price_preview(lists, rates, {"scope": "all", "percent": 10,
                                             "tiers": [1, 2, 3]})
    assert [(r["what"], r["tier"], r["old"], r["new"]) for r in got] == [
        ("TAF-G4-595", 1, 20.0, 22.0), ("TAF-G4-595", 2, 18.0, 19.8),
        ("BAG-F7", 1, 50.0, 55.0),
        ("V-Form G4 /m²", 1, 30.0, 33.0), ("V-Form G4 /m²", 3, 25.0, 27.5)]
    only = sales.price_preview(lists, rates, {"scope": "list", "percent": 5,
                                              "tiers": [1], "match_text": "g4"})
    assert [(r["what"], r["new"]) for r in only] == [("TAF-G4-595", 21.0)]


def test_who_owes_what_is_aged_by_customer():
    rows = [
        {"customer": "Bells", "number": "INV-1", "due": "2026-09-01",
         "total": 100, "owing": 100, "days_late": 45},
        {"customer": "Bells", "number": "INV-2", "due": "2026-10-20",
         "total": 50, "owing": 20, "days_late": 0},
        {"customer": "Tweed", "number": "INV-3", "due": "2026-06-01",
         "total": 300, "owing": 300, "days_late": 137},
    ]
    got = sales.owing_by_customer(rows)
    assert [c["customer"] for c in got] == ["Tweed", "Bells"]
    bells = got[1]
    assert (bells["owing"], bells["d60"], bells["current"], bells["oldest"]) == \
        (120, 100, 20, 45)
    assert got[0]["over"] == 300
    assert sales.statement_lines(bells) == [
        ["INV-1", "2026-09-01", "$100.00", "$100.00", "45"],
        ["INV-2", "2026-10-20", "$50.00", "$20.00", ""]]


def test_the_phone_has_the_same_lost_reasons():
    import json
    import re
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "docs" / "app"
          / "screens.js").read_text(encoding="utf-8")
    got = re.search(r"var LOST_REASONS = (\[.*?\]);", js, re.S).group(1)
    assert json.loads(got) == sales.LOST_REASONS
