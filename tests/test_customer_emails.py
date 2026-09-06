"""Telling a customer we have their order.

Two things matter more than the email itself.

It ships off. A system that starts writing to a company's customers the day
it is installed is a system nobody trusts again, and the switch is set for
the whole company rather than per PC — one machine quietly disagreeing with
the others is the kind of thing nobody notices for a month.

And it never stops an order being raised. An order that could not be
confirmed by email is still an order; a customer who has to be rung instead
is a far smaller problem than a job that did not get made.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import db as _db          # noqa: E402
from taf_order_app import emails as _emails  # noqa: E402


# ── The switch ───────────────────────────────────────────────────────────────

def test_it_is_off_until_somebody_turns_it_on():
    assert _emails.DEFAULTS["order_received"] is False


def test_a_project_with_nothing_stored_is_off_not_broken():
    def boom():
        raise RuntimeError("catalog_lists does not exist")
    _db.get_catalog_map = boom
    assert _emails.is_on() is False


def test_the_stored_setting_wins():
    _db.get_catalog_map = lambda: {_emails.SETTINGS_KEY: {"order_received": True}}
    assert _emails.is_on() is True
    _db.get_catalog_map = lambda: {_emails.SETTINGS_KEY: {"order_received": False}}
    assert _emails.is_on() is False


def test_anything_that_is_not_true_is_off():
    """A half-written setting must not be read as permission to send mail."""
    for value in ("", "no", None, 0, "false"):
        _db.get_catalog_map = lambda v=value: {
            _emails.SETTINGS_KEY: {"order_received": v}}
        assert _emails.is_on() is False, value


def test_turning_it_on_keeps_the_other_settings():
    saved = {}
    _db.get_catalog_map = lambda: {
        _emails.SETTINGS_KEY: {"order_received": False, "reply_to": "kai@taf"}}
    _db.set_catalog_value = lambda k, v: saved.update({k: v})
    _emails.set_on(True)
    assert saved[_emails.SETTINGS_KEY]["order_received"] is True
    assert saved[_emails.SETTINGS_KEY]["reply_to"] == "kai@taf", \
        "turning the switch on wiped the rest of the settings"


def test_the_setting_is_shared_not_per_pc():
    """In the database, not in this machine's settings file."""
    src = (ROOT / "taf_order_app" / "emails.py").read_text(encoding="utf-8")
    fn = src.split("def set_on")[1].split("\ndef ")[0]
    assert "set_catalog_value" in fn


# ── Sending ──────────────────────────────────────────────────────────────────

def test_nothing_is_sent_without_being_signed_in():
    class NoSession:
        class auth:
            @staticmethod
            def get_session():
                return None
    _db.get_client = lambda: NoSession()
    out = _emails.send_order_received("O1")
    assert out["sent"] is False
    assert "signed in" in out["reason"].lower()


def test_no_order_means_no_call():
    out = _emails.send_order_received("")
    assert out["sent"] is False


def test_a_missing_function_is_explained_not_a_stack_trace():
    """Most people will run the build before deploying the function."""
    import urllib.error
    import urllib.request

    class Session:
        access_token = "tok"

    class Client:
        class auth:
            @staticmethod
            def get_session():
                return Session()
    _db.get_client = lambda: Client()
    _db.current_anon_key = lambda: "anon"

    def not_found(*_a, **_k):
        raise urllib.error.HTTPError("u", 404, "Not Found", None, None)
    real, urllib.request.urlopen = urllib.request.urlopen, not_found
    try:
        out = _emails.send_order_received("O1")
    finally:
        urllib.request.urlopen = real
    assert out["sent"] is False
    assert "not deployed" in out["reason"]


def test_a_customer_with_no_address_is_not_a_failure():
    """The function answers 200 with sent:false. Plenty of customers have no
    address on file and an order must never fail because of it."""
    import io
    import urllib.request

    class Session:
        access_token = "tok"

    class Client:
        class auth:
            @staticmethod
            def get_session():
                return Session()
    _db.get_client = lambda: Client()
    _db.current_anon_key = lambda: "anon"

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    body = b'{"sent": false, "reason": "No email address on file for this customer."}'
    real, urllib.request.urlopen = urllib.request.urlopen, lambda *a, **k: Resp(body)
    try:
        out = _emails.send_order_received("O1")
    finally:
        urllib.request.urlopen = real
    assert out["sent"] is False
    assert "No email address" in out["reason"]


# ── Never in the way of an order ─────────────────────────────────────────────

def test_generating_an_order_does_not_wait_on_the_network_to_do_nothing():
    """The switch is read from the copy loaded at start-up. Asking the
    database mid-generation, only to decide not to send anything, would put a
    round trip in front of every order for no reason."""
    src = (ROOT / "modern_order_gui.py").read_text(encoding="utf-8")
    fn = src.split("def _email_order_received")[1].split("\n    def ")[0]
    assert 'EMAIL_SETTINGS.get("order_received")' in fn
    assert "_emails.is_on()" not in fn


def test_a_send_that_fails_is_a_note_not_an_exception():
    src = (ROOT / "modern_order_gui.py").read_text(encoding="utf-8")
    fn = src.split("def _email_order_received")[1].split("\n    def ")[0]
    assert "except Exception" in fn and "return f\"Could not send" in fn


def test_the_slip_goes_out_after_the_order_is_saved():
    """Not before. Nothing should be able to tell a customer their order is
    in before it is actually in."""
    src = (ROOT / "modern_order_gui.py").read_text(encoding="utf-8")
    block = src.split("new_order_id = _db.save_order(")[1][:900]
    assert "_email_order_received" in block


# ── The key never ships ──────────────────────────────────────────────────────

def test_no_mail_provider_key_anywhere_in_the_app():
    """It lives as a Supabase function secret. Anything in the installer can
    be pulled back out and used to send mail as Total Air Filtration."""
    import re
    for path in list((ROOT / "taf_order_app").glob("*.py")) + \
            [ROOT / "modern_order_gui.py"]:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"re_[A-Za-z0-9]{20,}", text), \
            f"what looks like a Resend key is in {path.name}"
        assert "RESEND_API_KEY" not in text, \
            f"{path.name} reaches for the mail key; only the function may"


def test_the_function_refuses_when_the_switch_is_off():
    """The app checks too, so the button greys out — but a desktop left open
    since yesterday is working from yesterday's answer. The switch that
    decides whether mail actually leaves has to be the one at the server."""
    fn = (ROOT / "supabase" / "functions" / "send-order-email" /
          "index.ts").read_text(encoding="utf-8")
    assert "settings.order_received !== true" in fn
    off_at = fn.index("settings.order_received !== true")
    send_at = fn.index("api.resend.com")
    assert off_at < send_at, "it sends before checking whether it is switched on"


def test_the_function_reads_the_order_as_the_caller():
    """Service-role reads bypass row-level security. A signed-in account that
    cannot read an order must not be able to have its contents emailed."""
    fn = (ROOT / "supabase" / "functions" / "send-order-email" /
          "index.ts").read_text(encoding="utf-8")
    block = fn.split('.from("orders")')[0][-400:]
    assert "asCaller" in block
