"""Reading what is already in the orders.

Four of these features add no data at all - capacity, batch by material, end
of month and one search box are arithmetic over rows that have been sitting
there for years. Which makes them the easiest to get quietly wrong: nothing
throws, a number is just wrong, and somebody promises a Friday on it.

So the arithmetic is tested against hand-counted fixtures with a fixed
"today", and the rule that a row nobody can read is reported rather than
dropped is tested too. A capacity figure that silently ignored the four
orders it could not parse is worse than no capacity figure.
"""
from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import insights as _ins      # noqa: E402

# A Friday. Its Monday is the 7th.
TODAY = _dt.date(2026, 9, 11)


def order(ref, who, due, status="Pending", lines=(), ordered="01/09/2026",
          stages=None, archived=False):
    header = {"status": status}
    if stages is not None:
        header["stages"] = stages
    return {
        "id": ref, "order_number": ref, "customer_name": who,
        "date_due": due, "date_ordered": ordered, "archived": archived,
        "header": header,
        "items": [{"item_kind": "filter", "Quantity": q, "Square Metres": a,
                   "Media Type": m, "Channel": d, "Short": 295, "Long": 310,
                   "Filter Type": "V-form"}
                  for q, a, m, d in lines],
    }


ROWS = [
    order("PO-1", "Bells Creek", "01/08/2026", lines=[(4, 0.3, "G4", 50)]),
    order("PO-2", "CAS - Tweed", "14/09/2026", lines=[(10, 0.5, "G4", 50)]),
    order("PO-3", "Pelican", "16/09/2026", lines=[(2, 1.2, "F5", 45)]),
    order("PO-4", "Bells Creek", "ASAP", lines=[(1, 0.2, "G4", 50)]),
    order("PO-5", "CAS - Tweed", "01/09/2026", "Complete",
          [(6, 0.4, "G4", 50)]),
]


# ── Dates people typed ───────────────────────────────────────────────────────

def test_it_reads_the_dates_people_actually_type():
    assert _ins.parse_date("01/08/2026") == _dt.date(2026, 8, 1)
    assert _ins.parse_date("1/8/26") == _dt.date(2026, 8, 1)
    assert _ins.parse_date("2026-08-01") == _dt.date(2026, 8, 1)


def test_asap_is_not_a_date_and_is_not_pretended_to_be_one():
    assert _ins.parse_date("ASAP") is None
    assert _ins.parse_date("asap") is None
    assert _ins.parse_date("") is None
    assert _ins.parse_date("next week sometime") is None


# ── What you can promise ─────────────────────────────────────────────────────

def test_overdue_is_its_own_bucket():
    """Smearing late work across the weeks it was originally promised for
    makes those weeks look busy and this week look free."""
    out = _ins.capacity(ROWS, weeks=3, today=TODAY)
    assert out["overdue"]["orders"] == 1
    assert out["overdue"]["filters"] == 4
    assert all(w["week"] >= _dt.date(2026, 9, 7) for w in out["weeks"])


def test_a_week_adds_up_across_orders():
    out = _ins.capacity(ROWS, weeks=3, today=TODAY)
    week = [w for w in out["weeks"] if w["week"] == _dt.date(2026, 9, 14)][0]
    assert week["orders"] == 2                 # PO-2 and PO-3
    assert week["filters"] == 12               # 10 + 2
    assert week["sqm"] == 7.4                  # 10*0.5 + 2*1.2
    assert week["customers"] == 2


def test_finished_work_is_not_still_promised():
    out = _ins.capacity(ROWS, weeks=3, today=TODAY)
    total = (out["overdue"]["filters"] + out["no_date"]["filters"]
             + sum(w["filters"] for w in out["weeks"]))
    assert total == 17, "the completed order is still being counted as work"


def test_no_due_date_is_shown_rather_than_dropped():
    """ASAP is most of the order book. Hiding it makes the load look light."""
    out = _ins.capacity(ROWS, weeks=3, today=TODAY)
    assert out["no_date"]["orders"] == 1
    assert out["no_date"]["filters"] == 1


def test_weeks_start_on_monday():
    out = _ins.capacity(ROWS, weeks=2, today=TODAY)
    assert out["weeks"][0]["week"] == _dt.date(2026, 9, 7)
    assert all(w["week"].weekday() == 0 for w in out["weeks"])


def test_throughput_is_what_was_actually_finished():
    out = _ins.throughput(ROWS, weeks=6, today=TODAY)
    assert out["filters_avg"] == 6.0
    assert out["orders_avg"] == 1.0


# ── Batch by material ────────────────────────────────────────────────────────

def test_work_is_grouped_by_what_it_is_made_of():
    groups = _ins.by_material(ROWS)
    g4 = [g for g in groups if g["media"] == "G4"][0]
    assert g4["filters"] == 15                 # 4 + 10 + 1, not the finished 6
    assert g4["customers"] == 2
    assert len(groups) == 2


def test_the_earliest_promise_sets_up_first():
    groups = _ins.by_material(ROWS)
    assert groups[0]["media"] == "G4"
    assert groups[0]["due"] == _dt.date(2026, 8, 1)


def test_inside_a_group_the_oldest_promise_is_worked_first():
    groups = _ins.by_material(ROWS)
    g4 = [g for g in groups if g["media"] == "G4"][0]
    dues = [l["due"] for l in g4["lines"] if l["due"]]
    assert dues == sorted(dues)


def test_finished_work_is_not_on_the_machine_list():
    groups = _ins.by_material(ROWS)
    for g in groups:
        for line in g["lines"]:
            assert line["order_no"] != "PO-5"


# ── End of month ─────────────────────────────────────────────────────────────

def test_a_month_counts_on_the_date_it_came_in():
    """An order that took six weeks belongs to the month it was promised in,
    not the month it happened to be finished."""
    out = _ins.month_end(ROWS, today=TODAY)
    sept = [m for m in out["months"] if m["month"] == "2026-09"][0]
    assert sept["orders"] == 5                 # finished ones count too
    assert sept["filters"] == 23


def test_the_busiest_customer_comes_first():
    out = _ins.month_end(ROWS, today=TODAY)
    assert out["customers"][0]["orders"] >= out["customers"][-1]["orders"]


def test_an_order_with_no_readable_date_is_counted_out_loud():
    rows = ROWS + [order("PO-6", "X", "", ordered="whenever")]
    out = _ins.month_end(rows, today=TODAY)
    assert out["unreadable"] == 1


# ── One search box ───────────────────────────────────────────────────────────

def test_an_exact_order_number_comes_first():
    """Somebody holding a piece of paper almost certainly meant that one."""
    hits = _ins.search("PO-3", orders=ROWS)
    assert hits and hits[0]["kind"] == "order" and "Pelican" in hits[0]["label"]


def test_it_looks_in_all_four_places():
    hits = _ins.search("g4", orders=ROWS,
                       stock=[{"id": "s1", "name": "G4 media roll",
                               "sku": "MED-G4", "stock_on_hand": 40}],
                       prices={"PPFG4-030": 22.5})
    kinds = {h["kind"] for h in hits}
    assert {"stock", "product"} <= kinds


def test_one_letter_is_not_a_search():
    """Every order in the book is not a useful answer to "a"."""
    assert _ins.search("a", orders=ROWS) == []


def test_it_finds_a_customer_by_their_suburb():
    hits = _ins.search("caloundra", customers=[
        {"id": "c1", "name": "Bells Creek Pty Ltd", "suburb": "Caloundra"}])
    assert hits and hits[0]["kind"] == "customer"


def test_nothing_matching_is_nothing_rather_than_everything():
    assert _ins.search("zzzznothing", orders=ROWS) == []


# ── Where everything has got to ──────────────────────────────────────────────

def test_a_job_sits_in_the_furthest_box_that_is_ticked():
    """Somebody who ticks Assembled without ticking Drilled has still
    assembled it. A board that sent that job back to the saw would be
    arguing with the person who did the work."""
    rows = [order("A", "Bells", "01/10/2026",
                  stages={"assembled": True}, lines=[(1, 0.3, "G4", 50)])]
    board = _ins.wip_board(rows)
    at = {c["label"]: len(c["orders"]) for c in board["columns"]}
    assert at["Assembled"] == 1 and at["Not started"] == 0


def test_a_job_nobody_has_touched_is_not_started():
    rows = [order("A", "Bells", "01/10/2026", lines=[(1, 0.3, "G4", 50)])]
    board = _ins.wip_board(rows)
    assert len(board["columns"][0]["orders"]) == 1


def test_the_board_uses_the_worksheets_own_five_boxes():
    """Not stages invented for a screen: these are already printed down the
    side of every worksheet and ticked with a pen."""
    labels = [label for _key, label in _ins.STAGES]
    assert labels == ["Not started", "Marked", "Cut", "Drilled",
                      "Assembled", "Packed"]


def test_finished_jobs_are_off_the_board():
    board = _ins.wip_board(ROWS)
    on_board = sum(len(c["orders"]) for c in board["columns"])
    assert on_board == 4, "a completed order is still on the board"


def test_a_pile_up_is_named():
    rows = [order(f"A{i}", "Bells", "01/10/2026", stages={"cut": True},
                  lines=[(1, 0.3, "G4", 50)]) for i in range(6)]
    rows.append(order("B", "CAS", "01/10/2026", lines=[(1, 0.3, "G4", 50)]))
    assert _ins.wip_board(rows)["jam"] == "Cut"
