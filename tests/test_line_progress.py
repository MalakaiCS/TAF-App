"""Ticking an order off one line at a time.

An order is not one thing that is either made or not. It is eight filters,
and by Tuesday afternoon three of them are done. Nothing in the app could
record which three, which is why the customer could not be told anything
useful and why a scanning gun would have had nothing to scan at.

Lines live in a JSON array on the order, so the two things that can go wrong
are both about identity and about who saved last.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import db as _db          # noqa: E402


# ── Naming a line ────────────────────────────────────────────────────────────

def test_every_line_gets_an_id():
    lines = _db.with_line_ids([{"Quantity": 1}, {"Quantity": 2}])
    ids = [l[_db.LINE_ID] for l in lines]
    assert all(ids), "a line came back without an id"
    assert len(set(ids)) == 2, "two lines were given the same id"


def test_an_id_a_line_already_has_is_kept():
    """Otherwise every read renames every line, and a tick written against
    the old name lands nowhere."""
    lines = _db.with_line_ids([{_db.LINE_ID: "keep-me", "Quantity": 1}])
    assert lines[0][_db.LINE_ID] == "keep-me"


def test_giving_ids_does_not_change_the_line():
    before = {"Quantity": 3, "Filter Type": "V-form", "Media Type": "G4"}
    after = _db.with_line_ids([dict(before)])[0]
    after.pop(_db.LINE_ID)
    assert after == before


def test_the_id_is_what_names_a_line_not_its_position():
    """Insert a line at the top and every line below it shifts down. If a
    tick were held against position 2 it would now be on the wrong filter."""
    lines = _db.with_line_ids([{"Quantity": 1}, {"Quantity": 2}])
    second = lines[1][_db.LINE_ID]
    reordered = [{"Quantity": 9, _db.LINE_ID: "new"}] + lines
    assert reordered[2][_db.LINE_ID] == second, \
        "the line moved and took a different id with it"


# ── Counting ─────────────────────────────────────────────────────────────────

def test_progress_counts_what_is_made():
    assert _db.line_progress([{"made": True}, {}, {"made": True}]) == (2, 3)
    assert _db.line_progress([]) == (0, 0)
    assert _db.line_progress(None) == (0, 0)


# ── Saving a tick ────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, client):
        self.client = client
        self.kind = "select"

    def select(self, *_a):
        return self

    def eq(self, *_a, **_k):
        return self

    def single(self):
        return self

    def update(self, payload):
        self.kind = "update"
        self.client.updates.append(payload)
        return self

    def execute(self):
        if self.kind == "update":
            if self.client.refuse:
                raise RuntimeError(self.client.refuse)
            return _Resp([{"id": "order-1"}])
        return _Resp({"items": [dict(i) for i in self.client.items]})


class FakeClient:
    def __init__(self, items, has_rpc=True, refuse="", line_missing=False):
        self.items = items
        self.has_rpc = has_rpc
        self.refuse = refuse
        self.line_missing = line_missing
        self.updates: list = []
        self.rpc_calls: list = []

    def table(self, _name):
        return _Query(self)

    def rpc(self, name, params):
        client = self

        class _R:
            def execute(self):
                if not client.has_rpc:
                    raise RuntimeError(
                        "Could not find the function public.set_order_line_made"
                        " in the schema cache")
                client.rpc_calls.append((name, params))
                if client.refuse:
                    raise RuntimeError(client.refuse)
                if client.line_missing:
                    return _Resp(None)
                return _Resp("order-1")
        return _R()


def _with(client):
    _db.get_client = lambda: client
    return client


def test_a_tick_is_saved_by_id_in_the_database():
    c = _with(FakeClient([{"line_id": "L1"}, {"line_id": "L2"}]))
    _db.set_line_made("order-1", "L2", True, by="Kai")
    assert c.rpc_calls, "it did not use the server-side update"
    name, params = c.rpc_calls[0]
    assert name == "set_order_line_made"
    assert params["p_line_id"] == "L2"
    assert params["p_made"] is True
    assert params["p_by"] == "Kai"
    assert not c.updates, "it rewrote the whole array as well"


def test_two_benches_ticking_two_lines_do_not_erase_each_other():
    """The reason this goes through the database rather than being done here:
    read the array, change one entry, write it all back, and whoever saves
    second erases the other's tick. Only the line's id is sent."""
    c = _with(FakeClient([{"line_id": "L1"}, {"line_id": "L2"}]))
    _db.set_line_made("order-1", "L1", True, by="Kai")
    _, params = c.rpc_calls[0]
    assert "items" not in params and "p_items" not in params, \
        "the whole line array was sent, which is what overwrites the other tick"


def test_a_line_that_is_not_there_is_not_reported_as_saved():
    """An UPDATE matching nothing is not an error in Postgres."""
    _with(FakeClient([{"line_id": "L1"}], line_missing=True))
    try:
        _db.set_line_made("order-1", "gone", True)
    except Exception as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("saving nothing was reported as saving it")


def test_a_refused_tick_says_so():
    _with(FakeClient([{"line_id": "L1"}],
                     refuse="new row violates row-level security policy"))
    try:
        _db.set_line_made("order-1", "L1", True)
    except Exception as exc:
        assert "row-level security" in str(exc)
    else:
        raise AssertionError("the database refused it and nothing was said")


def test_it_still_works_without_the_migration():
    """Most people will run this build before they run the SQL."""
    c = _with(FakeClient([{"line_id": "L1"}, {"line_id": "L2"}], has_rpc=False))
    _db.set_line_made("order-1", "L2", True, by="Kai")
    assert c.updates, "the fallback did not write anything"
    written = c.updates[0]["items"]
    assert written[1]["made"] is True and written[1]["made_by"] == "Kai"
    assert not written[0].get("made"), "it marked a line nobody asked for"


def test_the_fallback_still_raises_when_refused():
    c = _with(FakeClient([{"line_id": "L1"}], has_rpc=False,
                         refuse="JWT expired"))
    try:
        _db.set_line_made("order-1", "L1", True)
    except Exception as exc:
        assert "JWT" in str(exc)
    else:
        raise AssertionError("the fallback swallowed the failure")
    del c


def test_unmaking_a_line_clears_who_made_it():
    c = _with(FakeClient([{"line_id": "L1", "made": True, "made_by": "Kai"}],
                         has_rpc=False))
    _db.set_line_made("order-1", "L1", False)
    written = c.updates[0]["items"][0]
    assert written["made"] is False
    assert not written["made_by"], "it still says who made a line that is not made"


# ── Old orders ───────────────────────────────────────────────────────────────

def test_an_old_order_gets_ids_written_back_once():
    """Ids made up fresh on every read would be different every time, and a
    tick would go looking for one the database has never seen."""
    c = _with(FakeClient([{"Quantity": 1}, {"Quantity": 2}]))
    items = _db.get_order_items("order-1")
    assert all(i.get(_db.LINE_ID) for i in items)
    assert c.updates, "the ids were handed out but never saved"
    saved = c.updates[0]["items"]
    assert [i[_db.LINE_ID] for i in saved] == [i[_db.LINE_ID] for i in items], \
        "it saved different ids from the ones it gave the screen"


def test_an_order_that_already_has_ids_is_not_rewritten():
    c = _with(FakeClient([{"line_id": "L1"}, {"line_id": "L2"}]))
    _db.get_order_items("order-1")
    assert not c.updates, "it wrote to the database for nothing"


# ── The column in the list ───────────────────────────────────────────────────

def test_the_list_column_says_how_far_along_an_order_is():
    assert _db.progress_cell(8, 3) == "3/8"
    assert _db.progress_cell(8, 8) == "✓ 8"
    # Nothing started, and databases without the migration, read as before.
    assert _db.progress_cell(8, 0) == "8"
    assert _db.progress_cell(8, None) == "8"
    assert _db.progress_cell(0, None) == "0"


def test_the_window_and_the_list_agree_on_the_wording():
    """Two places working out separately what "half made" looks like is how
    they end up disagreeing."""
    src = (ROOT / "modern_order_gui.py").read_text(encoding="utf-8")
    fn = src.split("def _items_cell")[1].split("\ndef ")[0]
    assert "progress_cell" in fn, "the list has its own copy of the rule"


# ── An order raised on the web ───────────────────────────────────────────────
# The web app saves the dimensions somebody typed and nothing worked out from
# them: deriving a part number takes a thousand lines of rules that live in
# Python, and a second copy of those in JavaScript would put different part
# numbers on Xero invoices depending on which screen an order was raised on.
#
# So the desktop fills them in when it opens the order. If it did not, a
# web-raised order would reach Xero with no item code on its lines and the
# invoice would be wrong in a way nobody would notice until the customer rang.

def test_the_desktop_fills_in_what_the_web_could_not():
    src = (ROOT / "modern_order_gui.py").read_text(encoding="utf-8")
    fn = src.split("def _order_header_items")[1].split("\n    def ")[0]
    assert "needs_part_number" in fn and "_stamp_item" in fn, \
        "nothing derives a part number for an order raised on the web"


def test_it_only_fills_in_what_is_missing():
    """Re-deriving a part number already on a line would quietly rewrite the
    codes on old orders every time the media list changed."""
    src = (ROOT / "modern_order_gui.py").read_text(encoding="utf-8")
    fn = src.split("def _order_header_items")[1].split("\n    def ")[0]
    assert "if _pn.needs_part_number(it):" in fn


def test_a_web_raised_line_really_does_get_a_part_number():
    """Not a claim about the code — run a line shaped the way the web app
    saves one through the real derivation and check what comes out."""
    from taf_order_app import part_numbers as _pn
    line = {"item_kind": "filter", "Quantity": 4, "Filter Type": "V-form",
            "Media Type": "G4", "Short": 500, "Long": 600, "Channel": 45,
            "Notes": ""}
    assert _pn.needs_part_number(line), \
        "the web's shape is not recognised as needing a part number"
    _pn.apply_derived_fields(line, {})
    # Exactly what a 500 x 600 x 45 V-form in G4 is: 0.3 m², PPFG4 at 45mm.
    assert line.get("Part Number") == "PPFG445-030", line.get("Part Number")
    assert float(line.get("Square Metres") or 0) == 0.3, line.get("Square Metres")
