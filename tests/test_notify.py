"""Being told what needs doing, instead of going to look.

The morning summary is the first thing this system does that arrives
unasked. Three things follow from that, and they are what these check.

Off until two separate people have said yes: the company, and you. Neither
switch on its own sends anything.

Never guessed. Anything that is not clearly a yes is a no, including a
database that will not answer - nobody is harmed by a summary that did not
arrive, and the reverse is how a system loses people's trust for good.

And one address per message. A summary of the whole factory bcc'd to
everybody is one wrong address away from being a list of every customer's
late job sitting in a stranger's inbox.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import db as _db          # noqa: E402
from taf_order_app import emails as _emails  # noqa: E402
from taf_order_app import notify as _notify  # noqa: E402

FUNCTION = ROOT / "supabase" / "functions" / "daily-summary" / "index.ts"


def _fn() -> str:
    return FUNCTION.read_text(encoding="utf-8")


# ── The company switch ───────────────────────────────────────────────────────

def test_it_is_off_until_somebody_turns_it_on():
    _db.get_catalog_map = lambda: {}
    assert _notify.is_on() is False


def test_anything_that_is_not_true_is_off():
    """The same strict reading the customer emails get. bool("no") is True in
    Python, and a row edited by hand in Supabase must not be able to start
    mailing the company by accident."""
    for value in ("", "no", None, 0, "false", "FALSE", [], {}):
        _db.get_catalog_map = lambda v=value: {
            _emails.SETTINGS_KEY: {_notify.KEY: v}}
        assert _notify.is_on() is False, value
    for value in (True, "true", "Yes", "on", "1"):
        _db.get_catalog_map = lambda v=value: {
            _emails.SETTINGS_KEY: {_notify.KEY: v}}
        assert _notify.is_on() is True, value


def test_it_shares_one_row_with_the_customer_emails():
    """Two rows would be two things to keep in step, and one PC quietly
    disagreeing with the others is what the shared row is for."""
    saved = {}
    _db.get_catalog_map = lambda: {
        _emails.SETTINGS_KEY: {"order_received": True, "reply_to": "kai@taf"}}
    _db.set_catalog_value = lambda k, v: saved.update({k: v})
    _notify.set_on(True)
    assert list(saved) == [_emails.SETTINGS_KEY]
    row = saved[_emails.SETTINGS_KEY]
    assert row[_notify.KEY] is True
    assert row["order_received"] is True, "it wiped the customer email switch"
    assert row["reply_to"] == "kai@taf", "it wiped the reply-to address"


def test_turning_the_summary_off_leaves_the_customer_emails_alone():
    saved = {}
    _db.get_catalog_map = lambda: {
        _emails.SETTINGS_KEY: {"order_received": True, _notify.KEY: True}}
    _db.set_catalog_value = lambda k, v: saved.update({k: v})
    _notify.set_on(False)
    assert saved[_emails.SETTINGS_KEY][_notify.KEY] is False
    assert saved[_emails.SETTINGS_KEY]["order_received"] is True


# ── Your own switch ──────────────────────────────────────────────────────────

def test_a_database_that_will_not_answer_is_a_no():
    def boom():
        raise RuntimeError("no connection")
    _db.current_user = boom
    assert _notify.mine() is False


def test_nobody_signed_in_is_a_no():
    _db.current_user = lambda: None
    assert _notify.mine() is False


def test_your_own_switch_is_written_by_the_database_not_by_the_app():
    """set_my_daily_summary takes the account from the session, so there is
    no user id to pass wrongly - or on purpose, to sign somebody else up."""
    sql = (ROOT / "migrate_notifications.sql").read_text(encoding="utf-8")
    body = sql.split("CREATE OR REPLACE FUNCTION public.set_my_daily_summary")[1]
    assert "auth.uid()" in body
    assert "p_user" not in body, "it takes a user id as an argument"
    assert "SECURITY INVOKER" in body


def test_one_person_cannot_read_or_write_another_person_being_signed_up():
    sql = (ROOT / "migrate_notifications.sql").read_text(encoding="utf-8")
    for policy in ("Read my notify settings", "Write my notify settings",
                   "Change my notify settings"):
        block = sql.split(f'CREATE POLICY "{policy}"')[1].split(";")[0]
        assert "user_id = auth.uid()" in block, policy
    # Managers may see who is on, so somebody can answer "who gets these?".
    # They may not turn anybody on: a manager who thinks you should be
    # getting one can ask you.
    assert 'CREATE POLICY "Managers see who is on"' in sql
    seen = sql.split('CREATE POLICY "Managers see who is on"')[1].split(";")[0]
    assert "FOR SELECT" in seen


# ── The function that sends it ───────────────────────────────────────────────

def test_only_the_schedule_can_mail_everybody():
    """Being able to send to the whole company is not something an ordinary
    signed-in account should have."""
    src = _fn()
    assert "token === serviceKey" in src
    assert "everyone && !scheduled" in src
    assert re.search(r"everyone && !scheduled[\s\S]{0,200}?403", src), \
        "asking for everybody without the schedule's key is not refused"


def test_the_switch_is_checked_where_the_mail_actually_leaves():
    """The app checks it too, so the button is greyed out — but a desktop
    open since yesterday is working from yesterday's answer."""
    src = _fn()
    assert "catalog_lists" in src
    assert "settings.daily_summary !== true" in src
    assert src.index("settings.daily_summary !== true") < \
           src.index("api.resend.com"), "it sends before checking the switch"


def test_one_address_per_message():
    src = _fn()
    # The field, not the word — the comment explaining why there is no bcc
    # is not a bcc.
    assert not re.search(r'["\s]bcc\s*:', src), "a bcc of the whole company"
    assert "to: [person.email]" in src, "it does not send to one person at a time"


def test_a_refused_address_does_not_lose_everybody_elses():
    src = _fn()
    assert "refused.push" in src
    assert "sent, refused" in src


def test_the_mail_key_never_leaves_the_function():
    """It is a function secret for the same reason the Anthropic key is: an
    installer anybody can download must not carry a key that sends mail as
    Total Air Filtration."""
    assert 'Deno.env.get("RESEND_API_KEY")' in _fn()
    for path in list(ROOT.glob("*.py")) + list((ROOT / "taf_order_app").glob("*.py")) \
            + list((ROOT / "docs").rglob("*.js")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "RESEND_API_KEY" not in text or "secret" in text.lower(), path
        assert not re.search(r"re_[A-Za-z0-9]{16,}", text), \
            f"what looks like a live mail key in {path.name}"


def test_the_summary_reads_a_due_date_the_way_the_app_does():
    """An email that calls an order late when the app does not is worse than
    no email. The two copies are held to being the same text, because a due
    date is dd/mm/yyyy typed by a person and there is no second way to get
    that right."""
    ui = (ROOT / "docs" / "app" / "ui.js").read_text(encoding="utf-8")
    fn = _fn()

    def grab(src, name):
        start = src.index(f"function {name}(")
        depth, i, seen = 0, start, False
        while i < len(src):
            if src[i] == "{":
                depth += 1
                seen = True
            elif src[i] == "}":
                depth -= 1
                if seen and depth == 0:
                    return re.sub(r"\s+", " ", src[start:i + 1])
            i += 1
        raise AssertionError(f"{name} is not in there at all")

    for name in ("parseDate", "dueBucket"):
        assert grab(ui, name) == grab(fn, name), (
            f"{name} has drifted between the app and the morning summary")
    assert re.sub(r"\s+", " ", 'var DONE = ["Complete", "Dispatched", '
                               '"Delivered", "Collected"];') in \
        re.sub(r"\s+", " ", fn), "the list of finished statuses has drifted"


def test_a_project_without_the_repeat_jobs_table_still_gets_a_summary():
    src = _fn()
    where = src.index('.from("recurring_jobs")')
    assert "try {" in src[where - 400:where], \
        "one optional table missing takes the whole email with it"
