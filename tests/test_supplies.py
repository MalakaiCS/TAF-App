"""Asking for supplies, and the number on the bell.

The rules that have to hold for this are in the database, and
tests/db_rules.py checks those against a real Postgres. These are about the
apps: that the bell says the right thing, that the phone and the PC offer the
same things to ask for, that a change the database quietly refused is not
shown as done, and that nothing either app sends could let somebody ask as
somebody else.
"""
from __future__ import annotations

import datetime as _dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import supplies as _sup      # noqa: E402

GUI = (ROOT / "modern_order_gui.py").read_text(encoding="utf-8")
WEB = (ROOT / "docs" / "app" / "screens.js").read_text(encoding="utf-8")
SQL = (ROOT / "migrate_supply_requests.sql").read_text(encoding="utf-8")


# ── The number on the bell ───────────────────────────────────────────────────

def test_nothing_unread_shows_nothing_at_all():
    """A bell that always says 0 is a bell nobody looks at."""
    assert _sup.badge_text(0) == ""


def test_the_count_is_shown_up_to_99():
    for n in (1, 2, 3, 9, 10, 42, 99):
        assert _sup.badge_text(n) == str(n)


def test_past_99_it_says_99_plus():
    for n in (100, 101, 150, 5000):
        assert _sup.badge_text(n) == "99+", n


def test_nonsense_is_no_badge_rather_than_a_crash():
    """It is asked every thirty seconds; one bad answer must not stop it."""
    for n in (None, "", "lots", -1, -50):
        assert _sup.badge_text(n) == "", n


def test_the_phone_and_the_pc_count_the_same_way():
    fn = WEB.split("function badgeText(n)")[1].split("\n  }")[0]
    assert "n <= 0" in fn and 'return ""' in fn
    assert 'n > 99 ? "99+"' in fn


def test_a_failed_poll_is_a_quiet_bell_not_an_error_box():
    """A dropped connection must not become an error every thirty seconds."""
    def boom():
        raise RuntimeError("no connection")
    was = _sup._db.get_client
    _sup._db.get_client = boom
    try:
        assert _sup.unread_count() == 0
    finally:
        _sup._db.get_client = was


def test_the_bell_sits_next_to_the_profile_picture():
    """Packed straight after the profile and on the same side, which is what
    puts it beside the picture rather than out past the shortcuts."""
    hdr = GUI.split("def _build_header(self)")[1].split("\n    def ")[0]
    assert hdr.index("self._profile_anchor = prof") < hdr.index("NotificationBell(")
    assert hdr.index("NotificationBell(") < hdr.index("Shortcuts")
    assert 'self._bell.pack(side="right"' in hdr


def test_the_bell_turns_red_when_there_is_something():
    cls = GUI.split("class NotificationBell")[1].split("\nclass ")[0]
    assert 'colour = self.RED if self._count else CMU' in cls
    web_css = (ROOT / "docs" / "app" / "index.html").read_text(encoding="utf-8")
    assert "header .bell.has svg" in web_css and "#E5484D" in web_css


def test_the_badge_is_sized_from_the_text_not_guessed():
    """Guessed widths let "99+" spill out of both ends of the badge."""
    cls = GUI.split("class NotificationBell")[1].split("\nclass ")[0]
    assert "font.measure(text)" in cls
    assert "{1: 13, 2: 17}" not in cls


def test_the_bell_is_asked_every_half_minute_and_off_the_main_thread():
    assert "_BELL_EVERY_MS = 30 * 1000" in GUI
    poll = GUI.split("def _poll_notifications(self)")[1].split("\n    def ")[0]
    assert "threading.Thread" in poll
    assert "var BELL_EVERY = 30000;" in WEB


def test_the_phone_asks_again_when_it_is_picked_up():
    """A phone that slept through the morning should not show the morning's
    count for another thirty seconds."""
    fn = WEB.split("function watchBell()")[1].split("\n  }")[0]
    assert "visibilitychange" in fn


def test_dark_mode_redraws_the_bell():
    """The colour walk reaches the canvas but not what is drawn on it."""
    fn = GUI.split("def _toggle_dark_mode(self)")[1].split("\n    def ")[0]
    assert "bell.redraw()" in fn


# ── What can be asked for ────────────────────────────────────────────────────

def test_the_list_is_what_was_asked_for():
    for item in ("Rivets", "Tape", "Media", "Mesh Wire", "Channel", "Other"):
        assert item in _sup.ITEMS, item


def test_the_phone_and_the_pc_offer_exactly_the_same_things():
    m = re.search(r"var SUPPLY_ITEMS = \[([^\]]*)\]", WEB)
    web = re.findall(r'"([^"]+)"', m.group(1))
    assert web == _sup.ITEMS, f"phone {web} / pc {_sup.ITEMS}"


def test_every_item_says_what_to_say_about_it():
    """"Tape" on its own is not something a manager can order."""
    for item in _sup.ITEMS:
        assert _sup.DETAIL_HINTS.get(item), item
        assert f'"{item}":' in WEB.split("var SUPPLY_HINTS")[1], item


def test_other_has_to_say_what_it_is():
    try:
        _sup.clean_request("Other", "   ")
    except _sup.SupplyError as exc:
        assert "Other" in str(exc)
    else:
        raise AssertionError("an empty Other was accepted")
    assert "CHECK (item <> 'Other' OR length(trim(detail)) > 0)" in SQL


def test_something_not_on_the_list_is_refused():
    try:
        _sup.clean_request("Coffee")
    except _sup.SupplyError:
        pass
    else:
        raise AssertionError("it accepted something not on the list")


def test_what_is_typed_is_trimmed_and_kept_to_a_sensible_length():
    row = _sup.clean_request("Tape", "  foil  ", " 3 rolls ", True,
                             "x" * 900)
    assert row["detail"] == "foil" and row["quantity"] == "3 rolls"
    assert row["urgent"] is True and len(row["note"]) == 500


# ── Who asked ────────────────────────────────────────────────────────────────

def test_neither_app_says_who_is_asking():
    """The database writes the signed-in account. An app that sent a name
    would be one edit away from letting somebody ask as somebody else."""
    fn = (ROOT / "taf_order_app" / "supplies.py").read_text(encoding="utf-8")
    body = fn.split("def request_supply(")[1].split("\ndef ")[0]
    code = "\n".join(l for l in body.split("\n")
                     if not l.strip().startswith("#")
                     and '"""' not in l)
    assert "requested_by" not in code.split('"""')[-1]
    web = WEB.split('rpc: "request_supply"')[1].split("})")[0]
    assert "requested_by" not in web


def test_both_apps_ask_through_the_one_function():
    """One way in, so "sent twice" becomes "filed once" in one place."""
    assert 'rpc("request_supply"' in \
        (ROOT / "taf_order_app" / "supplies.py").read_text(encoding="utf-8")
    assert 'rpc: "request_supply"' in WEB
    assert '.table("supply_requests").insert' not in \
        (ROOT / "taf_order_app" / "supplies.py").read_text(encoding="utf-8")


def test_the_desktop_sends_its_own_reference_too():
    calls = {}

    class Resp:
        data = {"id": "r1", "item": "Tape"}

    class Client:
        def rpc(self, name, body):
            calls["name"], calls["body"] = name, body
            return self

        def execute(self):
            return Resp()

    was = _sup._db.get_client
    _sup._db.get_client = lambda: Client()
    try:
        out = _sup.request_supply("Tape", "foil", "3")
    finally:
        _sup._db.get_client = was
    assert calls["name"] == "request_supply"
    assert calls["body"]["p_client_ref"].startswith("desk-")
    assert out["id"] == "r1"


# ── Moving a request along ───────────────────────────────────────────────────

def test_a_change_that_matched_nothing_is_not_reported_as_done():
    """Row-level security refuses an update by matching no rows, not by
    raising. Without this check, cancelling somebody else's request looks
    cancelled on your screen and is still open for everyone else."""
    class Resp:
        data = []

    class Client:
        def table(self, _n):
            return self

        def update(self, _p):
            return self

        def eq(self, *_a):
            return self

        def execute(self):
            return Resp()

    was = _sup._db.get_client
    _sup._db.get_client = lambda: Client()
    try:
        _sup.set_status("r1", "cancelled")
    except _sup.SupplyError as exc:
        assert "didn't change anything" in str(exc)
    else:
        raise AssertionError("a refused change was reported as done")
    finally:
        _sup._db.get_client = was
    assert "if (!rows || !rows.length)" in WEB, "the phone does not check"


def test_only_a_manager_is_offered_the_buttons():
    tab = GUI.split("def _build_supplies_tab(self)")[1].split("\n    def ")[0]
    assert "_db.can_handle_supplies()" in tab
    assert "var manager = D.roleLevel() >= 3;" in WEB


def test_received_and_declined_are_the_end_of_the_road():
    assert "received" not in _sup.NEXT and "declined" not in _sup.NEXT
    assert _sup.NEXT["ordered"] == ["received"]


# ── The order it is shown in ─────────────────────────────────────────────────

def test_urgent_and_waiting_is_at_the_top():
    rows = [
        {"id": "a", "status": "ordered", "created_at": "2026-09-24T09:00"},
        {"id": "b", "status": "open", "created_at": "2026-09-24T08:00"},
        {"id": "c", "status": "open", "urgent": True,
         "created_at": "2026-09-24T10:00"},
        {"id": "d", "status": "open", "created_at": "2026-09-24T07:00"},
        {"id": "e", "status": "received", "created_at": "2026-09-24T11:00"},
    ]
    got = [r["id"] for r in _sup.sort_requests(rows)]
    # Urgent first; then the ones waiting, longest-waiting first; then on
    # order; then finished.
    assert got == ["c", "d", "b", "a", "e"], got


def test_the_phone_sorts_them_the_same_way():
    fn = WEB.split("function sortRequests(rows)")[1].split("\n  }")[0]
    assert 'a.status === "open" && a.urgent' in fn
    assert "open: 0, ordered: 1, received: 2" in fn


# ── Wording ──────────────────────────────────────────────────────────────────

def test_a_request_reads_the_way_somebody_would_say_it():
    assert _sup.describe({"item": "Tape", "detail": "50mm foil",
                          "quantity": "3 rolls"}) == "Tape - 50mm foil, 3 rolls"
    assert _sup.describe({"item": "Rivets"}) == "Rivets"


def test_how_long_ago():
    now = _dt.datetime(2026, 9, 24, 12, 0, tzinfo=_dt.timezone.utc)
    assert _sup.ago("2026-09-24T11:59:30Z", now) == "just now"
    assert _sup.ago("2026-09-24T11:55:00Z", now) == "5 min ago"
    assert _sup.ago("2026-09-24T09:00:00Z", now) == "3 h ago"
    assert _sup.ago("2026-09-22T12:00:00Z", now) == "2 d ago"
    assert _sup.ago("", now) == "" and _sup.ago("garbage", now) == ""


def test_a_migration_not_run_is_told_as_a_setup_step():
    assert _sup.is_missing_table(Exception(
        'relation "public.supply_requests" does not exist'))
    assert _sup.is_missing_table(Exception(
        "Could not find the function public.my_unread_count"))
    assert not _sup.is_missing_table(Exception("connection reset"))


def test_the_desktop_does_not_show_python_to_people():
    """"'NoneType' object has no attribute 'table'" was on the screen once,
    in the status line under the list."""
    fn = GUI.split("def _refresh_supplies(self)")[1].split("\n    def ")[0]
    assert "Couldn't load supply requests - check the " in fn
    assert 'f"Couldn\'t load supply requests: {exc}"' not in fn


# ── The database side, in outline ────────────────────────────────────────────

def test_no_app_can_write_a_notification():
    assert "REVOKE INSERT, DELETE ON public.notifications" in SQL
    assert 'FOR INSERT' not in SQL.split("CREATE TABLE IF NOT EXISTS "
                                         "public.notifications")[1] \
        .split("── Telling every manager")[0]


def test_managers_are_told_by_the_database_not_by_an_app():
    assert "AFTER INSERT ON public.supply_requests" in SQL
    body = SQL.split("FUNCTION public.notify_managers_of_supply_request")[1]
    assert "SECURITY DEFINER" in body.split("AS $$")[0]
    assert "SET search_path = public, pg_temp" in body.split("AS $$")[0]
    assert "p.approved = true" in body


def test_it_is_checked_against_a_real_database():
    """The line-by-line rules are in tests/db_rules.py, and CI runs it where
    Postgres is available rather than letting it skip."""
    wf = (ROOT / ".github" / "workflows" / "database.yml").read_text(
        encoding="utf-8")
    assert "python tests/db_rules.py" in wf
    assert 'REQUIRE_POSTGRES: "1"' in wf
