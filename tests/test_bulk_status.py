"""Marking a batch of orders complete.

The bug this file exists for: every one of the functions that changed a field
of an order's header ended in `except Exception: pass`. A write the database
refused looked exactly like a write that worked. The app counted it, said
"Status set to 'Complete' on 12 orders", reloaded the list, and showed the
twelve orders still sitting at Pending. Nothing said why, or which.

The second bug, which had not bitten yet but would have: changing one key by
reading the whole header, editing it in Python and writing it all back is a
read-modify-write with no lock. Mark twenty orders complete while someone
adds a note to one of them and the note is overwritten.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import db as _db          # noqa: E402


# ── A stand-in for the Supabase client ───────────────────────────────────────

class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, client, kind):
        self.client, self.kind = client, kind
        self.payload = None

    def select(self, *_a):
        return self

    def eq(self, *_a, **_k):
        return self

    def single(self):
        return self

    def update(self, payload):
        self.kind = "update"
        self.payload = payload
        return self

    def execute(self):
        if self.kind == "update":
            self.client.updates.append(self.payload)
            if self.client.refuse:
                raise RuntimeError(self.client.refuse)
            if self.client.silently_matches_nothing:
                return _Resp([])
            return _Resp([{"id": "order-1"}])
        return _Resp(dict(self.client.header))


class FakeClient:
    """The database. `refuse` makes it reject writes the way a row-level
    security policy does; `has_rpc` says whether migrate_bulk_status.sql has
    been run."""

    def __init__(self, refuse="", has_rpc=True,
                 silently_matches_nothing=False):
        self.header = {"status": "Pending", "order_notes": ["an existing note"]}
        self.updates: list = []
        self.rpc_calls: list = []
        self.refuse = refuse
        self.has_rpc = has_rpc
        self.silently_matches_nothing = silently_matches_nothing

    def table(self, _name):
        return _Query(self, "select")

    def rpc(self, name, params):
        client = self

        class _R:
            def execute(self):
                if not client.has_rpc:
                    raise RuntimeError(
                        'Could not find the function public.merge_order_header'
                        '(p_order_id, p_patch) in the schema cache')
                client.rpc_calls.append((name, params))
                if client.refuse:
                    raise RuntimeError(client.refuse)
                if client.silently_matches_nothing:
                    return _Resp(None)
                return _Resp("order-1")
        return _R()


def _with(client):
    _db.get_client = lambda: client
    return client


# ── The bug ──────────────────────────────────────────────────────────────────

def test_a_refused_write_is_not_reported_as_a_saved_one():
    """This is the whole bug. It used to return None either way."""
    _with(FakeClient(refuse='new row violates row-level security policy'))
    try:
        _db.set_order_status("order-1", "Complete")
    except Exception as exc:
        assert "row-level security" in str(exc)
    else:
        raise AssertionError(
            "the database refused the write and set_order_status said nothing")


def test_an_update_that_matches_no_row_is_not_success():
    """An UPDATE matching nothing is not an error in Postgres. The order may
    have been deleted, or the policy may filter it out of sight."""
    _with(FakeClient(silently_matches_nothing=True))
    try:
        _db.set_order_status("order-1", "Complete")
    except Exception as exc:
        assert "did not change" in str(exc)
    else:
        raise AssertionError("changing nothing was reported as changing it")


def test_it_still_raises_without_the_migration():
    """The fallback path is the old code. It must not bring the old silence
    back with it — most people will run this build before the migration."""
    _with(FakeClient(has_rpc=False,
                     refuse='new row violates row-level security policy'))
    try:
        _db.set_order_status("order-1", "Complete")
    except Exception as exc:
        assert "row-level security" in str(exc)
    else:
        raise AssertionError("the fallback path swallowed the failure")


def test_the_fallback_is_only_for_a_missing_function():
    """A refusal must not be mistaken for "migration not run" and retried as
    a read-modify-write — that would turn one refused write into two."""
    c = _with(FakeClient(refuse="JWT expired"))
    try:
        _db.set_order_status("order-1", "Complete")
    except Exception:
        pass
    assert not c.updates, \
        "a refused RPC fell through to the read-modify-write and tried again"


# ── Not clobbering the rest of the header ────────────────────────────────────

def test_only_the_keys_given_are_sent():
    """`header || patch` in the database, not the whole header from Python.
    Whatever else is in there is not this write's business."""
    c = _with(FakeClient())
    _db.set_order_status("order-1", "Complete")
    assert c.rpc_calls, "it did not use the server-side merge"
    name, params = c.rpc_calls[0]
    assert name == "merge_order_header"
    assert params["p_patch"] == {"status": "Complete"}, params["p_patch"]
    assert not c.updates, "it wrote the whole header back as well"


def test_the_note_someone_else_added_is_not_overwritten():
    """The read-modify-write's failure mode, stated as a test: a patch that
    only carries `status` cannot remove notes, because it never sends them."""
    c = _with(FakeClient())
    _db.set_order_status("order-1", "Complete")
    _, params = c.rpc_calls[0]
    assert "order_notes" not in params["p_patch"]


def test_a_note_that_cannot_be_saved_says_so():
    """Typed, accepted, silently dropped is the worst of the three."""
    _with(FakeClient(refuse="JWT expired"))
    try:
        _db.append_order_note("order-1", "Rang the customer", "Kai")
    except Exception as exc:
        assert "JWT" in str(exc)
    else:
        raise AssertionError("the note vanished and nothing was said")


# ── The batch ────────────────────────────────────────────────────────────────

def test_one_bad_order_does_not_stop_the_rest():
    """Stopping at the first failure leaves you not knowing which half of the
    batch went through."""
    c = _with(FakeClient())
    attempted = []

    def flaky(order_id, patch):
        attempted.append(order_id)
        if order_id == "bad":
            raise RuntimeError("not allowed")

    real, _db.merge_order_header = _db.merge_order_header, flaky
    try:
        problems = _db.set_order_status_bulk(["a", "bad", "c"], "Complete")
    finally:
        _db.merge_order_header = real

    assert attempted == ["a", "bad", "c"], "it gave up part-way"
    assert [oid for oid, _ in problems] == ["bad"]
    assert "not allowed" in problems[0][1], "it did not say why"
    del c


def test_a_batch_that_all_works_reports_nothing_wrong():
    _with(FakeClient())
    assert _db.set_order_status_bulk(["a", "b"], "Complete") == []
