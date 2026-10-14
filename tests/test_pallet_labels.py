"""Pallet labels: how many pallets, what is on each, and who it is for."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import pallet_labels as pl                # noqa: E402

ITEMS = [
    {"Filter Type": "Flat Panel", "Short": 595, "Long": 595, "Channel": 25,
     "Quantity": 40, "Media Type": "F5"},
    {"Filter Type": "V-form", "Short": 592, "Long": 592, "Channel": 45,
     "Quantity": 12, "Media Type": "G4"},
    {"item_kind": "bag", "product_type": "Bag Filter", "width": 592,
     "height": 592, "depth": 600, "media": "F7", "quantity": 6},
    {"item_kind": "catalogue", "Product Type": "Channel",
     "Part Number": "CH45", "Description": "45mm channel 2440",
     "Quantity": 10},
]
CUSTOMER = {"name": "Complete Air Supply - Tweed Heads",
            "delivery_address1": "3A/38 Enterprise Avenue",
            "delivery_address2": "", "delivery_city": "Tweed Heads",
            "delivery_state": "New South Wales",
            "delivery_postcode": "2486", "phone": "07 5513 1044"}
ORDER = {"order_number": "57920", "header": {"Job": "  "}}


def test_each_pallet_lists_what_is_on_it():
    grid = [[14, 13, 13], [12, 0, 0], [0, 6, 0], [0, 0, 10]]
    labels, warnings = pl.build(ORDER, ITEMS, CUSTOMER, 3, grid)
    assert warnings == []
    assert [l["pallet_text"] for l in labels] == ["1 of 3", "2 of 3",
                                                  "3 of 3"]
    first = labels[0]
    assert [(r["line"], r["quantity"], r["ordered"]) for r in first["items"]] \
        == [(1, 14, 40), (2, 12, 12)]
    assert first["items"][0]["text"] == "595 × 595 × 25 mm Flat Panel F5"
    assert labels[1]["items"][1]["text"] == "592 × 592 × 600 mm Bag Filter F7"
    assert labels[2]["items"][1]["text"] == "CH45 - 45mm channel 2440"
    assert [l["filters_on_pallet"] for l in labels] == [26, 19, 23]


def test_who_it_is_for_comes_from_the_customer_account():
    labels, _ = pl.build(ORDER, ITEMS, CUSTOMER, 1, [[40], [12], [6], [10]])
    lab = labels[0]
    assert lab["customer_name"] == "Complete Air Supply - Tweed Heads"
    assert lab["address_lines"] == ["3A/38 Enterprise Avenue"]
    assert lab["locality"] == "Tweed Heads  NSW  2486"
    assert lab["order_number"] == "57920" and lab["job_number"] == "N/A"
    assert lab["pallet_text"] == "1 of 1"


def test_what_cannot_print_is_said():
    cases = [
        (0, [[40]] * 4, "number of pallets"),
        (2, [[40, 1], [12, 0], [6, 0], [10, 0]], "41 on pallets but 40"),
        (2, [[40, 0], [12, 0], [6, 0], [10, 0]], "pallet 2 has nothing"),
        (1, [["x"], [12], [6], [10]], "a whole number"),
        (1, [[2.5], [12], [6], [10]], "a whole number"),
        (1, [[-1], [12], [6], [10]], "a whole number"),
    ]
    for n, grid, words in cases:
        try:
            pl.build(ORDER, ITEMS, CUSTOMER, n, grid)
        except pl.PalletError as exc:
            assert any(words in p for p in exc.problems), (words, exc.problems)
        else:
            raise AssertionError(f"printed: {words}")
    try:
        pl.build(ORDER, ITEMS, {"name": "No address"}, 1,
                 [[40], [12], [6], [10]])
    except pl.PalletError as exc:
        assert "delivery address" in exc.problems[0]
    else:
        raise AssertionError("printed with no address")


def test_part_of_an_order_on_pallets_is_a_warning_not_a_refusal():
    labels, warnings = pl.build(ORDER, ITEMS, CUSTOMER, 1,
                                [[30], [12], [""], [None]])
    assert len(labels) == 1
    assert warnings == ["line 1: 10 of 40 not on a pallet",
                        "line 3: 6 of 6 not on a pallet",
                        "line 4: 10 of 10 not on a pallet"]


def test_spread_shares_a_line_evenly():
    assert pl.spread(40, 3) == [14, 13, 13]
    assert pl.spread(2, 3) == [1, 1, 0]
    assert pl.spread(0, 2) == [0, 0]
    assert sum(pl.spread(97, 7)) == 97


def test_a_long_pallet_runs_onto_another_sheet():
    many = [{"Filter Type": "Flat Panel", "Short": 300 + i, "Long": 600,
             "Channel": 25, "Quantity": 1, "Media Type": "F5"}
            for i in range(30)]
    labels, _ = pl.build(ORDER, many, CUSTOMER, 1, [[1]] * 30)
    path = Path(tempfile.mkdtemp()) / "p.pdf"
    pl.render_pdf(labels, str(path))
    import re
    data = path.read_bytes()
    assert data.startswith(b"%PDF")
    # Nine lines to a sheet at the size the label is printed: 30 is four.
    pages = len(re.findall(rb"/Type /Page(?!s)", data))
    assert pages == 4, pages
    one, _ = pl.build(ORDER, many[:3], CUSTOMER, 1, [[1]] * 3)
    pl.render_pdf(one, str(path))
    assert len(re.findall(rb"/Type /Page(?!s)", path.read_bytes())) == 1


def test_each_line_carries_its_job_number():
    """A line's own job (a preset, or a line given its own job) wins; else
    the order's job; else nothing - and the top says which."""
    items = [dict(ITEMS[0], item_job="Housing L11"),
             dict(ITEMS[1], item_job="Housing L15-L22"),
             dict(ITEMS[2])]
    order = {"order_number": "57920", "header": {"Job": "J-4410"}}
    labels, _ = pl.build(order, items, CUSTOMER, 2,
                         [[40, 0], [12, 0], [0, 6]])
    assert [(r["line"], r["job"]) for r in labels[0]["items"]] == \
        [(1, "Housing L11"), (2, "Housing L15-L22")]
    assert labels[0]["job_number"] == "See each line"
    assert labels[1]["items"][0]["job"] == "J-4410"
    assert labels[1]["job_number"] == "J-4410"
    # No job anywhere: N/A, never the order number.
    labels, _ = pl.build({"order_number": "57920", "header": {}}, items[2:3],
                         CUSTOMER, 1, [[6]])
    assert labels[0]["items"][0]["job"] == ""
    assert labels[0]["job_number"] == "N/A"
    path = Path(tempfile.mkdtemp()) / "jobs.pdf"
    pl.render_pdf(pl.build(order, items, CUSTOMER, 1,
                           [[40], [12], [6]])[0], str(path))
    assert path.read_bytes().startswith(b"%PDF")
