"""Jobs that come round again.

Three or four sites are done on a cycle - the same filters, every three or
six months. The app has recorded every one of them for years and never used
that to say "this one is due". Somebody had to remember, and when they
didn't, the customer rang up instead.

Nearly all the risk here is in the date arithmetic. A schedule that drifts a
few days every cycle is worse than no schedule, because it looks right.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import db as _db          # noqa: E402


# ── Working out when it is next due ──────────────────────────────────────────

def test_three_months_on_is_the_same_day_of_the_month():
    """Calendar months, not 90 days. A job done on the 15th is due on the
    15th, and 90 days would walk it earlier every single cycle."""
    assert _db.add_months(dt.date(2026, 1, 15), 3) == dt.date(2026, 4, 15)
    assert _db.add_months(dt.date(2026, 8, 15), 6) == dt.date(2027, 2, 15)
    assert _db.add_months(dt.date(2026, 3, 1), 12) == dt.date(2027, 3, 1)


def test_a_day_that_does_not_exist_in_the_next_month_is_clamped():
    """There is no 30th of February. 30 November plus three months is the end
    of February, not the 2nd of March."""
    assert _db.add_months(dt.date(2026, 11, 30), 3) == dt.date(2027, 2, 28)
    assert _db.add_months(dt.date(2026, 10, 31), 6) == dt.date(2027, 4, 30)


def test_february_knows_about_leap_years():
    assert _db.add_months(dt.date(2027, 11, 30), 3) == dt.date(2028, 2, 29)
    assert _db.add_months(dt.date(2024, 11, 30), 3) == dt.date(2025, 2, 28)


def test_december_rolls_the_year():
    assert _db.add_months(dt.date(2026, 12, 31), 1) == dt.date(2027, 1, 31)


# ── Reading a date back ──────────────────────────────────────────────────────

def test_a_date_is_understood_however_it_comes_back():
    want = dt.date(2026, 9, 17)
    assert _db.as_date("2026-09-17") == want
    assert _db.as_date("2026-09-17T00:00:00+00:00") == want
    assert _db.as_date("17/09/2026") == want
    assert _db.as_date(want) == want
    assert _db.as_date("") is None
    assert _db.as_date(None) is None


# ── What counts as due ───────────────────────────────────────────────────────

class _Q:
    def __init__(self, client):
        self.client = client
        self.kind = "select"
        self.payload = None

    def select(self, *_a):
        return self

    def eq(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def single(self):
        return self

    def update(self, payload):
        self.kind = "update"
        self.payload = payload
        return self

    def insert(self, payload):
        self.kind = "insert"
        self.payload = payload
        return self

    def delete(self):
        self.kind = "delete"
        return self

    def execute(self):
        c = self.client
        if self.kind == "update":
            c.updates.append(self.payload)
            return type("R", (), {"data": [] if c.refuse_write else [{"id": "J1"}]})()
        if self.kind == "insert":
            c.inserts.append(self.payload)
            return type("R", (), {"data": [{"id": "new"}]})()
        if self.kind == "delete":
            return type("R", (), {"data": [] if c.refuse_write else [{"id": "J1"}]})()
        return type("R", (), {"data": c.rows if c.many else (c.rows[0] if c.rows else {})})()


class FakeClient:
    def __init__(self, rows, many=True, refuse_write=False):
        self.rows = rows
        self.many = many
        self.refuse_write = refuse_write
        self.updates: list = []
        self.inserts: list = []

    def table(self, _name):
        return _Q(self)


def _with(client):
    _db.get_client = lambda: client
    return client


def test_a_job_due_today_is_due():
    today = dt.date(2026, 9, 6)
    _with(FakeClient([{"id": "J1", "next_due": today.isoformat(),
                       "every_months": 3, "active": True}]))
    assert len(_db.recurring_jobs_due(today)) == 1


def test_a_job_that_was_missed_last_month_is_still_due():
    """Dropping it off the list the day after it was due is how a quarterly
    job gets missed for a year."""
    today = dt.date(2026, 9, 6)
    _with(FakeClient([{"id": "J1", "next_due": "2026-07-01",
                       "every_months": 3, "active": True}]))
    assert len(_db.recurring_jobs_due(today)) == 1


def test_a_job_due_next_month_is_not_due_yet():
    today = dt.date(2026, 9, 6)
    _with(FakeClient([{"id": "J1", "next_due": "2026-10-01",
                       "every_months": 3, "active": True}]))
    assert _db.recurring_jobs_due(today) == []


# ── Moving it on ─────────────────────────────────────────────────────────────

def test_the_next_one_is_counted_from_when_it_was_due():
    """Not from today. A quarterly job raised a fortnight late is still due
    at the end of that quarter — measuring from today would push the whole
    schedule later every time anyone was busy, and after a year of that a
    three-monthly job is happening twice a year."""
    c = _with(FakeClient([{"next_due": "2026-01-15"}], many=False))
    nxt = _db.mark_recurring_raised("J1", 3, when=dt.date(2026, 1, 29))
    assert nxt == "2026-04-15", nxt
    assert c.updates[0]["last_raised"] == "2026-01-29"


def test_a_job_left_for_a_year_catches_up_rather_than_landing_in_the_past():
    c = _with(FakeClient([{"next_due": "2026-01-15"}], many=False))
    nxt = _db.mark_recurring_raised("J1", 3, when=dt.date(2026, 9, 6))
    assert _db.as_date(nxt) > dt.date(2026, 9, 6), \
        "it was moved on to a date that has already been and gone"
    assert nxt == "2026-10-15", nxt
    del c


def test_being_told_it_did_not_move_on():
    """The order gets raised either way. Silently failing to move the
    schedule means it shows as due again tomorrow and nobody knows why."""
    _with(FakeClient([{"next_due": "2026-01-15"}], many=False, refuse_write=True))
    try:
        _db.mark_recurring_raised("J1", 3, when=dt.date(2026, 1, 29))
    except Exception as exc:
        assert "not moved on" in str(exc)
    else:
        raise AssertionError("it failed to move the job on and said nothing")


# ── Saving one ───────────────────────────────────────────────────────────────

def test_saving_a_new_job_records_who_set_it_up():
    c = _with(FakeClient([]))
    _db.current_full_name = lambda: "Kai Brown"
    _db.save_recurring_job({"customer_name": "Bells Creek", "job": "AHU 3",
                            "every_months": 6, "next_due": "2026-12-01"})
    assert c.inserts[0]["created_by"] == "Kai Brown"
    assert c.inserts[0]["every_months"] == 6


def test_a_change_that_did_not_save_says_so():
    _with(FakeClient([], refuse_write=True))
    try:
        _db.save_recurring_job({"id": "J1", "customer_name": "X"})
    except Exception as exc:
        assert "not changed" in str(exc)
    else:
        raise AssertionError("the change was refused and nothing was said")


def test_the_list_is_empty_rather_than_broken_without_the_migration():
    """Most people will run the build before they run the SQL."""
    class Missing:
        def table(self, _n):
            raise RuntimeError('relation "public.recurring_jobs" does not exist')
    _with(Missing())
    assert _db.list_recurring_jobs() == []
    assert _db.recurring_jobs_due() == []


# ── The screens ──────────────────────────────────────────────────────────────

def _gui_source() -> str:
    return (ROOT / "modern_order_gui.py").read_text(encoding="utf-8")


def test_a_repeat_starts_from_an_order_not_a_blank_form():
    """The order already knows the customer, the job, the site and every
    filter on it. There is nothing to re-enter and nothing to get wrong."""
    src = _gui_source()
    assert '("Repeat this job…",       self._repeat_this_job)' in src
    fn = src.split("def _repeat_this_job")[1].split("\n    def ")[0]
    assert "template_order_id" in fn and "db_id" in fn


def test_the_repeat_is_a_fresh_job_in_the_shop():
    """Copying the ticks across would say four filters were made before
    anyone had started."""
    src = _gui_source()
    fn = src.split("def _load_repeat_into_new_order")[1].split("\n    def ")[0]
    assert 'it.pop("made", None)' in fn
    assert "LINE_ID" in fn, "the old order's line ids would come with it"
    assert 'header["Order Number"] = ""' in fn


def test_the_buttons_are_not_pushed_off_the_bottom_of_the_window():
    """A Treeview asks for the height of its rows. Pack the footer last and
    it is the thing squeezed off the edge — which is the button the window
    exists for."""
    src = _gui_source()
    fn = src.split("def _show_jobs_due")[1].split("\n    def ")[0]
    foot_at = fn.index('foot.pack(side="bottom"')
    table_at = fn.index('wrap.pack(fill="both", expand=True')
    assert foot_at < table_at, "the table takes its space before the buttons do"


def test_the_tile_is_only_there_when_something_is_due():
    """A permanent zero next to the work that changes every morning is one
    more thing to look past."""
    src = _gui_source()
    fn = src.split("def _refresh_worklist")[1].split("\n    def ")[0]
    assert "if jobs_due:" in fn
