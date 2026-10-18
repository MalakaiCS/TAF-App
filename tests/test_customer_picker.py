"""The list under Customer Name."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import customer_picker as cp              # noqa: E402

RECORDS = [
    {"id": "1", "name": "AC 1 PTY LTD", "short_name": "AAC001"},
    {"id": "2", "name": "Access Towing", "contact_person": "Kim",
     "email": "accounts@accesstowing.com.au"},
    {"id": "3", "name": "Pacific Coast"},
    {"id": "4", "name": "Bells Creek", "contact_person": "Zac"},
    {"id": "5", "name": "Acme Old", "is_active": False},
]


def test_initials_and_colour():
    assert cp.initials("AC 1 PTY LTD") == "A1P"
    assert cp.initials("Access Towing") == "AT"
    assert cp.initials("") == "?"
    assert cp.badge_colour("Access Towing") == cp.badge_colour("ACCESS TOWING")


def test_best_matches_first_and_no_inactive():
    names = [r["name"] for r in cp.matches(RECORDS, "ac")]
    assert names == ["AC 1 PTY LTD", "Access Towing", "Pacific Coast",
                     "Bells Creek"]


def test_the_typed_part_is_bold():
    assert cp.segments("Access Towing", "ac") == [("Ac", True),
                                                  ("cess Towing", False)]
    assert cp.segments("Pacific", "AC") == [("P", False), ("ac", True),
                                            ("ific", False)]
    assert cp.segments("x", "") == [("x", False)]


def test_subtitle_and_exact_match():
    assert cp.subtitle(RECORDS[1]) == \
        "Kim • accounts@accesstowing.com.au"
    assert cp.subtitle(RECORDS[0]) == "AAC001"
    assert cp.find_exact(RECORDS, " bells creek ")["id"] == "4"
    assert cp.find_exact(RECORDS, "aac001")["id"] == "1"
    assert cp.find_exact(RECORDS, "bells") is None
    assert cp.create_label("AC") == '+ Create "AC" as a new customer'
