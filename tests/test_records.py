"""The seven that needed a table of their own.

Kits, sites, returns, stocktakes, buying, agreed prices and the shutdown
calendar. What is tested here is the arithmetic and the refusals - the parts
that decide what a person is told and what the database is asked to do. The
reads and writes themselves are row-level security, which is tested against
the migration rather than against a mock that would agree with whatever it
was told.
"""
from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import records as _rec        # noqa: E402

SQL = (ROOT / "migrate_more_features.sql").read_text(encoding="utf-8")


# ── What a particular customer pays ──────────────────────────────────────────

def test_nothing_agreed_is_the_list_price_and_says_so():
    out = _rec.price_for("PPFG445-030", 100.0, [])
    assert out["price"] == 100.0 and out["why"] == "list price"


def test_a_price_for_this_part_beats_a_general_discount():
    """The specific thing somebody agreed beats the general thing they agreed
    earlier."""
    out = _rec.price_for("PPFG445-030", 100.0, [
        {"part_number": "", "discount": 12.5},
        {"part_number": "PPFG445-030", "unit_price": 88.0}])
    assert out["price"] == 88.0 and out["why"] == "agreed for this part"


def test_an_across_the_board_discount_applies_to_anything():
    out = _rec.price_for("ANYTHING", 200.0, [{"part_number": "",
                                              "discount": 10}])
    assert out["price"] == 180.0 and "10% off" in out["why"]


def test_a_part_number_matches_however_it_was_typed():
    out = _rec.price_for("ppfg445-030", 100.0,
                         [{"part_number": " PPFG445-030 ", "unit_price": 88}])
    assert out["price"] == 88.0


def test_an_agreement_that_is_neither_a_price_nor_a_discount_is_refused():
    """A row that says nothing would quietly override the list price with
    nothing."""
    try:
        _rec.set_customer_price("c1", "X")
    except ValueError as exc:
        assert "either a price or a discount" in str(exc)
    else:
        raise AssertionError("it stored an agreement that means nothing")


def test_a_discount_has_to_be_a_percentage():
    for bad in (-5, 100, 250):
        try:
            _rec.set_customer_price("c1", "X", discount=bad)
        except ValueError as exc:
            assert "percentage" in str(exc), bad
        else:
            raise AssertionError(f"it stored a discount of {bad}")


def test_one_row_per_customer_per_part():
    """A pair of rows disagreeing about what somebody pays is worse than no
    agreement at all."""
    assert "customer_prices_one_each" in SQL
    assert "UNIQUE INDEX" in SQL


# ── Buying ───────────────────────────────────────────────────────────────────

LOW = [
    {"id": "s1", "name": "G4 roll", "stock_on_hand": 6, "minimum_on_hand": 25,
     "supplier": "Acme", "supplier_email": "a@acme", "unit": "m"},
    {"id": "s2", "name": "F5 roll", "stock_on_hand": 40, "minimum_on_hand": 20,
     "supplier": "Acme", "unit": "m"},
    {"id": "s3", "name": "Clips", "stock_on_hand": 0, "minimum_on_hand": 500,
     "supplier": "Bolt Co", "unit": "each"},
]


def test_only_what_is_actually_short_gets_ordered():
    drafts = _rec.purchase_from_low_stock(LOW)
    ordered = {l["name"] for d in drafts for l in d["lines"]}
    assert ordered == {"G4 roll", "Clips"}


def test_it_is_one_order_per_supplier():
    drafts = _rec.purchase_from_low_stock(LOW)
    assert {d["supplier"] for d in drafts} == {"Acme", "Bolt Co"}


def test_what_is_already_coming_is_taken_off():
    """Without this, every look at the screen raises the same order again and
    the same roll gets bought three times."""
    plain = _rec.purchase_from_low_stock(LOW)[0]["lines"][0]["quantity"]
    with_coming = _rec.purchase_from_low_stock(LOW, {"s1": 10})
    line = [l for d in with_coming for l in d["lines"]
            if l["name"] == "G4 roll"][0]
    assert plain == 19 and line["quantity"] == 9


def test_enough_already_on_order_means_nothing_to_raise():
    drafts = _rec.purchase_from_low_stock(LOW, {"s1": 100, "s3": 1000})
    assert drafts == []


def test_an_item_with_no_minimum_is_not_short():
    """A minimum of zero means nobody has decided what to keep, not that we
    want none of it."""
    assert _rec.purchase_from_low_stock(
        [{"id": "x", "name": "Thing", "stock_on_hand": 0,
          "minimum_on_hand": 0, "supplier": "Acme"}]) == []


def test_quantities_on_order_ignores_what_has_arrived():
    rows = [{"status": "sent", "lines": [{"item_id": "s1", "quantity": 5}]},
            {"status": "received", "lines": [{"item_id": "s1", "quantity": 99}]}]
    assert _rec.quantities_on_order(rows) == {"s1": 5.0}


def test_a_purchase_order_with_nothing_on_it_is_refused():
    try:
        _rec.draft_purchase("Acme", [])
    except ValueError as exc:
        assert "not an" in str(exc) or "nothing on it" in str(exc)
    else:
        raise AssertionError("it raised an empty purchase order")


def test_committing_money_is_a_manager_s_decision():
    """Unlike writing down an offcut, which anyone at the saw may do."""
    block = SQL.split('CREATE POLICY "Managers raise purchases"')[1].split(";")[0]
    assert "public.is_manager()" in block


# ── Days that do not exist ───────────────────────────────────────────────────

XMAS = [{"day": "2026-12-25"}, {"day": "2026-12-28"}]


def test_a_shut_day_moves_to_the_next_open_one():
    assert _rec.next_working_day(_dt.date(2026, 12, 25), XMAS) == \
        _dt.date(2026, 12, 29)


def test_a_weekend_counts_as_shut_without_anybody_recording_it():
    saturday = _dt.date(2026, 9, 12)
    assert saturday.weekday() == 5
    assert _rec.next_working_day(saturday) == _dt.date(2026, 9, 14)


def test_an_open_day_is_left_alone():
    thursday = _dt.date(2026, 12, 24)
    assert _rec.next_working_day(thursday, XMAS) == thursday


def test_the_days_there_actually_are_to_do_it_in():
    got = _rec.working_days_between(_dt.date(2026, 12, 24),
                                    _dt.date(2026, 12, 31), XMAS)
    assert got == 4      # 24th, 29th, 30th, 31st


def test_a_range_that_runs_backwards_is_no_days():
    assert _rec.working_days_between(_dt.date(2026, 12, 31),
                                     _dt.date(2026, 12, 24), XMAS) == 0


# ── A filter that came back ──────────────────────────────────────────────────

def test_a_return_needs_a_reason():
    """Why it came back is the whole point of writing it down."""
    try:
        _rec.log_return("PO-1", "Bells", 1, "")
    except ValueError as exc:
        assert "Why it came back" in str(exc)
    else:
        raise AssertionError("it recorded a return with no reason")


def test_none_came_back_is_not_a_return():
    try:
        _rec.log_return("PO-1", "Bells", 0, "Wrong size")
    except ValueError as exc:
        assert "more than none" in str(exc)
    else:
        raise AssertionError("it recorded a return of nothing")


def test_a_return_ends_one_of_four_ways():
    try:
        _rec.close_return("r1", "lost it")
    except ValueError as exc:
        assert "not one of the ways" in str(exc)
    else:
        raise AssertionError("it closed a return as something meaningless")


def test_the_pattern_is_what_the_list_is_for():
    """One return is bad luck. The same reason from the same customer four
    times is something to go and look at."""
    rows = [{"customer_name": "Bells", "reason": "Wrong size", "quantity": 2},
            {"customer_name": "Bells", "reason": "Wrong size", "quantity": 1},
            {"customer_name": "CAS", "reason": "Damaged", "quantity": 5}]
    worst = _rec.returns_pattern(rows)[0]
    assert worst["customer"] == "Bells" and worst["times"] == 2
    assert worst["filters"] == 3


def test_deleting_an_order_does_not_delete_what_came_back_off_it():
    """The return survives with the order number still written on it, which
    is what somebody reading it needs."""
    block = SQL.split("CREATE TABLE IF NOT EXISTS public.returns")[1].split(");")[0]
    assert "ON DELETE SET NULL" in block
    assert "order_number  text" in block


def test_a_record_of_something_going_wrong_is_not_deletable_by_anyone():
    block = SQL.split('CREATE POLICY "Managers bin returns"')[1].split(";")[0]
    assert "public.is_manager()" in block


# ── Counting a rack ──────────────────────────────────────────────────────────

def test_a_count_cannot_be_less_than_nothing():
    try:
        _rec.count_item("st1", "s1", -4)
    except ValueError as exc:
        assert "less than nothing" in str(exc)
    else:
        raise AssertionError("it recorded a negative count")


def test_counting_the_same_rack_twice_leaves_one_figure():
    """It happens. The second count is the one that stands, and two rows
    disagreeing would be worse than either."""
    assert "stocktake_one_per_item" in SQL
    assert "(stocktake_id, item_id)" in SQL


def test_applying_a_count_twice_applies_it_once():
    """Through the same locked-row, client-reference path a scanning gun
    uses, so two people finishing the same session do not double it."""
    body = SQL.split("CREATE OR REPLACE FUNCTION public.apply_stocktake")[1]
    assert "adjust_stock_atomic" in body
    assert "'stocktake-' || p_stocktake::text" in body, \
        "the reference does not identify the session"


def test_the_stocktake_function_runs_as_whoever_called_it():
    body = SQL.split("CREATE OR REPLACE FUNCTION public.apply_stocktake")[1]
    assert "SECURITY INVOKER" in body.split("AS $$")[0]


def test_finishing_a_session_and_applying_it_are_separate():
    """A count that moved every figure the moment it was typed would have
    nobody ever daring to type one."""
    import inspect
    source = inspect.getsource(_rec.finish_stocktake)
    assert "apply: bool = False" in source


# ── Kits and sites ───────────────────────────────────────────────────────────

def test_a_kit_with_nothing_in_it_is_refused():
    try:
        _rec.save_kit("Empty", [])
    except ValueError as exc:
        assert "add nothing" in str(exc)
    else:
        raise AssertionError("it saved a kit that does nothing")


def test_a_kit_needs_a_name_to_be_found_by():
    try:
        _rec.save_kit("  ", [{"Quantity": 1}])
    except ValueError as exc:
        assert "name" in str(exc)
    else:
        raise AssertionError("it saved a nameless kit")


def test_two_kits_cannot_share_a_name():
    assert "kits_one_name" in SQL
    assert "lower(btrim(name))" in SQL


def test_a_site_with_no_cycle_is_never_due():
    """A blank interval means nobody has decided. Inventing one would put
    work on somebody's list that nobody agreed to."""
    rows = [{"id": "a", "name": "Roof", "every_months": 0,
             "last_done": "2020-01-01"}]
    assert _rec.sites_due(rows, _dt.date(2026, 9, 11)) == []


def test_a_site_on_a_cycle_comes_round():
    rows = [{"id": "a", "name": "AHU 3", "every_months": 3,
             "last_done": "2026-05-01"}]
    due = _rec.sites_due(rows, _dt.date(2026, 9, 11))
    assert len(due) == 1
    assert due[0]["due"] == _dt.date(2026, 8, 1)
    assert due[0]["overdue_days"] == 41


def test_a_site_never_done_is_due_now():
    rows = [{"id": "a", "name": "AHU 3", "every_months": 6, "last_done": None}]
    due = _rec.sites_due(rows, _dt.date(2026, 9, 11))
    assert len(due) == 1 and due[0]["due"] is None


def test_a_site_not_yet_round_again_is_left_alone():
    rows = [{"id": "a", "name": "AHU 3", "every_months": 6,
             "last_done": "2026-08-01"}]
    assert _rec.sites_due(rows, _dt.date(2026, 9, 11)) == []
