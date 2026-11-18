"""Merging duplicate customer accounts: what is suggested, what must be
decided, and that the app hands the database everything it needs.

The merge itself - the transaction, the locks, the permission check, the
undo - is in the database and is checked against a real Postgres by
tests/db_rules.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import customer_merge as cm               # noqa: E402

TWEED = {"id": "a", "name": "CAS - Tweed Heads", "short_name": "CAS Tweed",
         "legal_name": "Complete Air Supply Pty Ltd", "abn": "11 111 111 111",
         "phone": "07 5513 1044", "email": "tweed@cas.com.au",
         "delivery_address1": "3A/38 Enterprise Avenue",
         "delivery_city": "Tweed Heads", "delivery_postcode": "2486",
         "payment_terms": "Net 30"}
TWEED_AGAIN = {"id": "b", "name": "Complete Air Supply Tweed",
               "short_name": "", "legal_name": "Complete Air Supply",
               "abn": "", "phone": "+61 7 5513 1044", "email": "",
               "delivery_address1": "Rear 40 Enterprise Ave",
               "delivery_city": "Tweed Heads", "delivery_postcode": "2486",
               "payment_terms": "Net 14"}
BELLS = {"id": "d", "name": "CAS - Bells Creek", "short_name": "CAS Bells",
         "legal_name": "Complete Air Supply Pty Ltd", "abn": "11 111 111 111",
         "phone": "07 5437 0000", "email": "bells@cas.com.au",
         "delivery_address1": "19 Fred Chaplin Circuit",
         "delivery_city": "Bells Creek", "delivery_postcode": "4551"}
OTHER = {"id": "c", "name": "Total Comfort Air", "abn": "22 222 222 222",
         "phone": "07 3000 0000", "delivery_address1": "1 Other St",
         "delivery_city": "Logan", "delivery_postcode": "4114"}


def test_the_same_phone_suggests_a_duplicate():
    groups = cm.suggest_duplicates([TWEED, TWEED_AGAIN, BELLS, OTHER])
    assert len(groups) == 1
    assert set(groups[0]["ids"]) == {"a", "b"}
    assert any("same phone" in r for r in groups[0]["reasons"])


def test_branches_of_one_company_are_not_duplicates():
    """Same legal name, same ABN, different place: two branches."""
    groups = cm.suggest_duplicates([TWEED, BELLS])
    assert groups == []


def test_unrelated_companies_stay_apart():
    assert cm.suggest_duplicates([TWEED, OTHER]) == []


def test_a_merged_account_is_never_suggested_again():
    gone = dict(TWEED_AGAIN, merged_into="a")
    assert cm.suggest_duplicates([TWEED, gone]) == []


def test_different_abns_are_called_out():
    clash = dict(TWEED_AGAIN, abn="99 999 999 999")
    groups = cm.suggest_duplicates([TWEED, clash])
    assert groups and groups[0]["abn_conflict"] is True
    assert cm.abn_conflict([TWEED, clash])
    assert not cm.abn_conflict([TWEED, TWEED_AGAIN])      # blank is not a clash


def test_every_disagreement_has_to_be_chosen():
    c = cm.conflicts([TWEED, TWEED_AGAIN])
    assert c["payment_terms"] == ["Net 30", "Net 14"]
    assert "abn" not in c                                 # only one has one
    todo = cm.check_ready([TWEED, TWEED_AGAIN], "a", {"name": "CAS - Tweed"},
                          {})
    assert any("payment terms" in t for t in todo)
    assert any("delivery address1" in t for t in todo)
    chosen = {k: v[0] for k, v in c.items()}
    assert cm.check_ready([TWEED, TWEED_AGAIN], "a", chosen, {}) == []


def test_agreed_prices_on_both_accounts_must_be_chosen():
    prices = [{"customer_id": "a", "part_number": "FPFG425-040"},
              {"customer_id": "b", "part_number": "fpfg425-040 "},
              {"customer_id": "b", "part_number": "PPFG450-060"},
              {"customer_id": "c", "part_number": "PPFG450-060"}]
    assert cm.price_conflicts(prices, "a", ["b"]) == ["FPFG425-040"]
    chosen = {k: v[0] for k, v in cm.conflicts([TWEED, TWEED_AGAIN]).items()}
    todo = cm.check_ready([TWEED, TWEED_AGAIN], "a", chosen, {}, prices)
    assert any("FPFG425-040" in t for t in todo)
    assert cm.check_ready([TWEED, TWEED_AGAIN], "a", chosen,
                          {"FPFG425-040": "survivor"}, prices) == []


def test_merging_into_itself_or_twice_is_not_ready():
    assert cm.check_ready([TWEED], "a", {"name": "x"}, {})
    assert any("twice" in t for t in
               cm.check_ready([TWEED, TWEED], "a", {"name": "x"}, {}))
    assert any("already been merged" in t for t in cm.check_ready(
        [TWEED, dict(TWEED_AGAIN, merged_into="z")], "a",
        {"name": "x", "payment_terms": "Net 30",
         "delivery_address1": "x"}, {}))


def test_decisions_carry_the_name_and_never_a_blank_one():
    d = cm.decisions(TWEED, {"name": "  CAS - Tweed Heads ",
                             "payment_terms": "Net 14", "bogus": 1},
                     {"FPFG425-040": "survivor"})
    assert d["set"]["name"] == "CAS - Tweed Heads"
    assert d["set"]["payment_terms"] == "Net 14" and "bogus" not in d["set"]
    assert d["prices"] == {"FPFG425-040": "survivor"}
    try:
        cm.decisions({"name": ""}, {"name": " "})
    except cm.MergeError:
        pass
    else:
        raise AssertionError("a merge without a name was allowed")


def test_xero_contacts_are_listed_not_touched():
    notes = cm.external_ids([TWEED, TWEED_AGAIN], "CAS - Tweed Heads")
    assert any("Complete Air Supply Tweed" in n and "Xero" in n
               for n in notes)
    assert all("CAS - Tweed Heads\"" not in n for n in notes)


def test_a_new_customer_that_already_exists_is_warned_about():
    new = {"name": "Complete Air Supply Tweed Heads", "phone": "0755131044"}
    hits = cm.likely_matches(new, [TWEED, BELLS, OTHER])
    assert hits and hits[0]["customer"]["id"] == "a"
    assert cm.likely_matches({"name": "Brand New Pty Ltd"},
                             [TWEED, BELLS, OTHER]) == []


def test_the_merge_call_is_safe_to_retry():
    calls = []

    class Resp:
        data = "merge-id-1"

    class Client:
        def rpc(self, name, body):
            calls.append((name, body))
            return self

        def execute(self):
            return Resp()

    from taf_order_app import db as _db
    was = _db.get_client
    _db.get_client = lambda: Client()
    try:
        rid = cm.new_request_id()
        a = cm.merge(rid, "a", ["b"], {"set": {"name": "x"}})
        b = cm.merge(rid, "a", ["b"], {"set": {"name": "x"}})
    finally:
        _db.get_client = was
    assert a == b == "merge-id-1"
    assert calls[0][0] == "merge_customers"
    assert calls[0][1]["p_request_id"] == calls[1][1]["p_request_id"] == rid
    assert cm.new_request_id() != rid


def test_former_names_find_the_survivor():
    from taf_order_app import db as _db

    class Resp:
        def __init__(self, data):
            self.data = data

    class Q:
        def __init__(self, table):
            self.table_name = table

        def select(self, *_a):
            return self

        def order(self, *_a):
            return self

        def eq(self, *_a):
            return self

        def execute(self):
            if self.table_name == "customer_aliases":
                return Resp([{"survivor_id": "a",
                              "former_name": "Complete Air Supply Tweed",
                              "former_short_name": ""}])
            return Resp([TWEED, OTHER])

    class Client:
        def table(self, name):
            return Q(name)

    was = _db.get_client
    _db.get_client = lambda: Client()
    try:
        hits = _db.get_customers("supply tweed")
    finally:
        _db.get_client = was
    assert [c["id"] for c in hits] == ["a"]


def test_the_database_does_the_merge_in_one_transaction():
    sql = (ROOT / "migrate_packing_and_merge.sql").read_text()
    body = sql.split("FUNCTION public.merge_customers(")[1].split("$$;")[0]
    assert "public.is_manager()" in body
    assert "FOR UPDATE" in body and "ORDER BY id" in body
    assert "request_id" in body and "RETURN existing.id" in body
    assert "header" not in body.split("SET customer_id = p_survivor, "
                                      "customer_name = v_link")[1][:200]
