"""Who did what on the web, and a phone left on a bench.

The browser test drives both for real. These are the two rules underneath
them that are worth holding everywhere, because both fail quietly: an audit
entry that is never written looks exactly like a day when nobody did
anything, and a shared phone left signed in looks exactly like a phone.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(*parts) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


# ── The log ─────────────────────────────────────────────────────────────────

def test_the_log_is_written_without_asking_to_read_it_back():
    """audit_log lets everyone write and only managers read. Asking for the
    row back on the way in is asking to read something you may not read, and
    PostgREST refuses the whole statement - so the entry is never written at
    all, and only for the people whose work most needs recording."""
    data = _read("docs", "app", "data.js")
    assert 'quiet ? "return=minimal"' in data, \
        "there is no way to insert without reading the row back"
    for where, src in (("offline.js", _read("docs", "app", "offline.js")),
                       ("screens.js", _read("docs", "app", "screens.js"))):
        for m in re.finditer(r'insert\(\s*"audit_log"', src):
            tail = src[m.start():m.start() + 400]
            call = tail.split("catch", 1)[0]
            assert re.search(r"\}\s*,\s*true\s*\)", call), \
                f"{where} writes to audit_log asking for the row back"


def test_a_queued_change_is_logged_when_it_lands():
    """Logging it when it was tapped would put a tick in the log that the
    database never received."""
    box = _read("docs", "app", "offline.js")
    assert "trail(job, false)" in box, "a write that went straight through"
    assert "trail(job, true)" in box, "a write that was sent from the queue"
    assert "sent when the signal" in box, \
        "a change sent late does not say it was made earlier"


def test_the_log_never_stops_anybody_working():
    """The change went through. Failing to write the note about it must not
    turn a done job into an error on somebody's screen."""
    for name in ("offline.js", "screens.js"):
        src = _read("docs", "app", name)
        for m in re.finditer(r'insert\(\s*"audit_log"', src):
            tail = src[m.start():m.start() + 500]
            assert ".catch(" in tail, f"{name}: an unswallowed audit write"


def test_the_web_and_the_desktop_write_the_same_words():
    """The two lists sit next to each other on the same manager's screen. A
    tick logged as line_made on one and something else on the other reads as
    two different things happening."""
    web = _read("docs", "app", "screens.js")
    desk = _read("modern_order_gui.py")
    for action in ("line_made", "line_unmade", "order_status",
                   "order_created"):
        assert f'"{action}"' in web, f"the web never logs {action}"
        assert f'"{action}"' in desk, f"the desktop never logs {action}"


def test_the_log_is_not_offered_to_people_who_cannot_read_it():
    """The database refuses them either way. This is about not putting up a
    tab whose only possible content is a permission error."""
    src = _read("docs", "app", "screens.js")
    assert re.search(r'key:\s*"log".*from:\s*3', src), \
        "the Log tab is not held to a role"
    assert "D.roleLevel() < t.from" in src, \
        "nothing acts on the role a tab is held to"


# ── A phone left on the bench ───────────────────────────────────────────────

def test_it_asks_before_signing_anybody_out():
    src = _read("docs", "app", "screens.js")
    assert "Still there?" in src
    assert "I am still here" in src


def test_it_will_not_sign_out_over_work_that_has_not_been_sent():
    """Stranded on the phone under an account nobody else can send it with."""
    src = _read("docs", "app", "screens.js")
    body = src.split("function goodnight", 1)[1].split("\n  }", 1)[0]
    assert "S.pending()" in body
    assert "still cannot be sent" in body


def test_idleness_is_measured_against_the_clock():
    """A phone that slept for an hour has to come back knowing it slept for
    an hour, which a countdown ticking down in a background tab does not."""
    src = _read("docs", "app", "screens.js")
    assert "Date.now() - touched > IDLE_MS" in src


if __name__ == "__main__":
    import sys

    bad = []
    for name in sorted(n for n in dir() if n.startswith("test_")):
        try:
            globals()[name]()
            print(f"  PASS  {name}")
        except AssertionError as exc:
            print(f"  FAIL  {name}\n        {exc}")
            bad.append(name)
    print(f"\n{len(bad)} FAILED" if bad else "\nThe log and the bench hold.")
    sys.exit(1 if bad else 0)
