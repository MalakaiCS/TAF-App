"""Pointing an imported purchase order at a customer we already have.

The complaint was that every purchase order looked like a new customer. It
was true, and it was not really the matching that caused it: when nothing
matched, the only button on the screen said "Create Profile", so that is what
got pressed. A company we had invoiced for years collected a profile per
layout change.

Three things had to be true to fix that, and these are about all three.

Somebody has to be able to say "no, it's this one" — and be shown the likely
ones rather than made to hunt a list of hundreds.

Saying it once has to stick. If the wording is not written down the next
order from the same branch fails to match again, the obvious button is
pressed again, and the duplicate gets made anyway.

And none of it may relax the rule the matching already had: branches of one
company share a name, so a name alone never identifies a branch. A convenience
that quietly takes that rule away is worse than no convenience.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import db as _db            # noqa: E402
from taf_order_app import po_import as _po     # noqa: E402


# Two branches of one company, and an unrelated business.
CAS_BELLS = {"id": "c1", "short_name": "CAS - Bells Creek",
             "name": "Complete Air Supply Bells Creek",
             "legal_name": "Complete Air Supply Pty Ltd",
             "region": "Sunshine Coast",
             "delivery_address1": "19-27 Fred Chaplin Circuit",
             "delivery_city": "Bells Creek", "delivery_postcode": "4551",
             "po_aliases": []}
CAS_TWEED = {"id": "c2", "short_name": "CAS - Tweed",
             "name": "Complete Air Supply Tweed",
             "legal_name": "Complete Air Supply Pty Ltd",
             "region": "Northern Rivers",
             "delivery_address1": "5 Machinery Drive",
             "delivery_city": "Tweed Heads South", "delivery_postcode": "2486",
             "po_aliases": []}
OTHER = {"id": "c3", "short_name": "Brisbane Compressors",
         "name": "Brisbane Compressors", "legal_name": "BC Holdings Pty Ltd",
         "region": "Brisbane", "delivery_city": "Rocklea",
         "delivery_postcode": "4106", "po_aliases": []}
PEOPLE = [CAS_BELLS, CAS_TWEED, OTHER]


# ── Being shown the likely ones ──────────────────────────────────────────────

def test_the_right_branch_is_suggested_first():
    got = _db.suggest_customers("Complete Air Supply Pty Ltd",
                                "19-27 Fred Chaplin Circuit, Bells Creek QLD 4551",
                                PEOPLE)
    assert got, "nothing suggested for an order we can clearly place"
    assert got[0]["customer"]["id"] == "c1", \
        [r["customer"]["short_name"] for r in got]


def test_the_address_is_what_separates_two_branches():
    """The name is identical on both, so it cannot order them. Without the
    address counted at all, which branch comes out top is an accident of how
    the list happened to be sorted."""
    got = _db.suggest_customers("Complete Air Supply Pty Ltd",
                                "5 Machinery Drive, Tweed Heads South",
                                PEOPLE)
    assert got[0]["customer"]["id"] == "c2"
    other = _db.suggest_customers("Complete Air Supply Pty Ltd",
                                  "19-27 Fred Chaplin Circuit, Bells Creek",
                                  PEOPLE)
    assert other[0]["customer"]["id"] == "c1", \
        "the same name with a different address gave the same answer"


def test_every_suggestion_says_why_it_is_being_suggested():
    """A name offered with no reason next to it is a name somebody clicks
    without reading, and the wrong branch sends the work to the wrong depot."""
    for row in _db.suggest_customers("Complete Air Supply Pty Ltd",
                                     "Bells Creek", PEOPLE):
        assert row["why"], row["customer"]["short_name"]


def test_a_wording_seen_before_puts_that_branch_top():
    taught = dict(CAS_TWEED, po_aliases=["CAS Tweed Heads Depot"])
    got = _db.suggest_customers("CAS Tweed Heads Depot", "",
                                [CAS_BELLS, taught, OTHER])
    assert got[0]["customer"]["id"] == "c2"
    assert "seen before" in got[0]["why"]


def test_nothing_to_go_on_suggests_nothing():
    """Rather than offering the whole customer list in an arbitrary order,
    which reads as a recommendation and is not one."""
    assert _db.suggest_customers("", "", PEOPLE) == []


def test_an_unrelated_company_is_not_offered():
    got = _db.suggest_customers("Complete Air Supply Pty Ltd", "Bells Creek",
                                PEOPLE)
    assert "c3" not in [r["customer"]["id"] for r in got]


def test_the_words_every_company_prints_are_not_evidence():
    """"Pty Ltd" and "Queensland" match everybody. A suggestion built on
    them is a list in alphabetical order wearing a rosette."""
    assert _db.suggest_customers("Pty Ltd", "", PEOPLE) == []
    assert _db.suggest_customers("", "QLD", PEOPLE) == []


def test_suggesting_is_not_deciding():
    """suggest_customers puts names in front of a person; match_customer is
    the one allowed to act on its own. If suggesting ever starts deciding,
    the Bells Creek order goes to Tweed again."""
    ambiguous = "Complete Air Supply Pty Ltd"
    assert _db.suggest_customers(ambiguous, "", PEOPLE), \
        "it should still offer both branches to choose between"
    assert _db.match_customer(ambiguous, "", PEOPLE) is None, \
        "the company name alone picked a branch"


# ── Saying it once, and it sticking ──────────────────────────────────────────

class _FakeDB:
    """Just enough Supabase to watch what gets written."""

    def __init__(self):
        self.written = {}

    def table(self, name):
        self._t = name
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def single(self):
        return self

    def update(self, data):
        self._update = data
        return self

    def execute(self):
        if hasattr(self, "_update"):
            self.written = dict(self._update)
            del self._update
            return type("R", (), {"data": {}})()
        return type("R", (), {"data": {"po_aliases": list(
            self.written.get("po_aliases", []))}})()


def _with_fake(fn):
    fake = _FakeDB()
    was_client, was_customers = _db.get_client, _db.get_customers
    _db.get_client = lambda: fake
    _db.get_customers = lambda **_k: PEOPLE
    try:
        return fn(fake)
    finally:
        _db.get_client, _db.get_customers = was_client, was_customers


def test_what_the_order_said_is_remembered():
    def go(fake):
        kept = _db.link_po_to_customer(
            "c1", "CAS Bells Creek Depot",
            "19-27 Fred Chaplin Circuit, Bells Creek")
        assert kept, "it linked the order and learned nothing"
        assert "CAS Bells Creek Depot" in fake.written.get("po_aliases", [])
    _with_fake(go)


def test_the_company_name_is_never_remembered_against_one_branch():
    """Every branch prints it. Recording it against one is exactly what sent
    a Bells Creek order to Tweed — and doing it from the screen where
    somebody is correcting that mistake would be worse than not learning."""
    def go(fake):
        kept = _db.link_po_to_customer("c1", "Complete Air Supply Pty Ltd", "")
        assert kept == [], f"it remembered {kept}"
        assert not fake.written.get("po_aliases"), fake.written
    _with_fake(go)


def test_an_address_still_gets_learned_even_when_the_name_cannot_be():
    """The usual case: the order prints the company name, which is useless,
    and the branch's own address, which is the whole answer."""
    def go(fake):
        kept = _db.link_po_to_customer(
            "c1", "Complete Air Supply Pty Ltd",
            "19-27 Fred Chaplin Circuit, Bells Creek QLD 4551")
        assert len(kept) == 1 and "Fred Chaplin" in kept[0], kept
    _with_fake(go)


def test_learning_it_makes_the_next_one_match_on_its_own():
    """The point of the whole exercise. Without this the next order fails to
    match, the obvious button gets pressed, and the duplicate is made."""
    before = _db.match_customer("CAS Bells Creek Depot", "", PEOPLE)
    assert before is None, "nothing to fix — this test proves nothing"
    taught = dict(CAS_BELLS, po_aliases=["CAS Bells Creek Depot"])
    after = _db.match_customer("CAS Bells Creek Depot", "",
                               [taught, CAS_TWEED, OTHER])
    assert after is not None and after["id"] == "c1"


def test_a_link_with_no_customer_writes_nothing():
    def go(fake):
        assert _db.link_po_to_customer("", "Anything", "Anywhere") == []
        assert fake.written == {}
    _with_fake(go)


def test_a_database_that_refuses_does_not_lose_the_link():
    """The order still gets pointed at the right branch on screen. Failing to
    write the wording down is a smaller problem than an import that stops."""
    def boom():
        raise RuntimeError("no connection")
    was = _db.get_client
    _db.get_client = boom
    try:
        assert _db.link_po_to_customer("c1", "CAS Bells Creek", "") == []
    finally:
        _db.get_client = was


# ── Reading the highlighted piece ────────────────────────────────────────────

def test_the_name_and_the_address_come_back_separately():
    """Branches of one company share a name and are told apart only by the
    address. A reader that merged them would hand back the single field that
    cannot resolve a branch."""
    sent = {}

    def fake(mode, data, media_type="image/png", timeout=120):
        sent["mode"] = mode
        return {"name": "Complete Air Supply Pty Ltd",
                "address": "19-27 Fred Chaplin Circuit, Bells Creek",
                "confidence": "high"}

    was = _po._read_highlight
    _po._read_highlight = fake
    try:
        got = _po.read_customer_name(b"not really a png")
        assert sent["mode"] == "customer"
        assert got["name"] == "Complete Air Supply Pty Ltd"
        assert "Fred Chaplin" in got["address"]
        assert got["confidence"] == "high"
    finally:
        _po._read_highlight = was


def test_a_reader_that_found_nothing_says_so_rather_than_inventing():
    was = _po._read_highlight
    _po._read_highlight = lambda *a, **k: {}
    try:
        got = _po.read_customer_name(b"x")
        assert got["name"] == "" and got["address"] == ""
        assert got["confidence"] == "medium"
    finally:
        _po._read_highlight = was


def test_the_job_number_reader_still_works_after_the_refactor():
    """Both readers share one request now. The older one has been in use for
    months and must not have changed behaviour."""
    sent = {}

    def fake(mode, data, media_type="image/png", timeout=120):
        sent["mode"] = mode
        return {"label": "Our Reference:", "value": "12576",
                "confidence": "high"}

    was = _po._read_highlight
    _po._read_highlight = fake
    try:
        got = _po.read_job_label(b"x")
        assert sent["mode"] == "label"
        assert got["label"] == "Our Reference:" and got["value"] == "12576"
    finally:
        _po._read_highlight = was


def test_the_function_knows_the_new_mode():
    """The app asking for something the deployed function has never heard of
    would fall through to reading the crop as a whole purchase order."""
    fn = (ROOT / "supabase/functions/extract-orders/index.ts").read_text(
        encoding="utf-8")
    assert 'mode?: "orders" | "label" | "customer"' in fn
    assert 'if (body.mode === "customer")' in fn
    assert "readCustomerName" in fn


def test_the_reader_is_told_it_is_not_the_customer():
    """Total Air Filtration's own name and address are printed on every
    purchase order it receives. A reader that picks those has found the one
    company that can never be the answer."""
    fn = (ROOT / "supabase/functions/extract-orders/index.ts").read_text(
        encoding="utf-8")
    system = fn.split("CUSTOMER_SYSTEM = `")[1].split("`;")[0]
    assert "Total Air Filtration" in system
    assert "never the customer" in system


# ── Which page gets opened ───────────────────────────────────────────────────

def test_the_photos_a_batch_was_read_from_can_be_found_again():
    """"Highlight it on the order" has to open the order. Asking somebody to
    go and find the file is how a feature stops being used."""
    import tempfile, json as _json
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("b.jpg", "a.png", "orders.json", "notes.txt"):
            (Path(tmp) / name).write_text("x")
        got = _po.batch_images({"dir": tmp})
        assert [Path(p).name for p in got] == ["a.png", "b.jpg"], got


def test_a_batch_with_no_folder_asks_for_nothing():
    assert _po.batch_images({}) == []
    assert _po.batch_images({"dir": "/nowhere/at/all"}) == []
