"""Bag headers: their size, their wire, and the worksheet page they get."""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import bag_headers as bh                  # noqa: E402
from taf_order_app import bag_filler as bf                   # noqa: E402
from taf_order_app import part_numbers as pn                 # noqa: E402
from taf_order_app import worksheet_blocks as wb             # noqa: E402
from taf_order_app.validation import validate_items          # noqa: E402

BAG = {"item_kind": "bag", "product_type": "3-Peak", "width": 610,
       "height": 610, "depth": 570, "media": "F7", "quantity": 4,
       "on_wire": True, "header": True}
CUSTOM = {"item_kind": "bag", "product_type": "Custom Bag Filter",
          "width": 855, "height": 570, "depth": 480, "pockets": 5,
          "media": "F7", "quantity": 2, "on_wire": True, "header": True,
          "header_depth": 20}


def test_a_610_bag_takes_a_595_header_and_580_wire():
    assert bh.header_size(BAG) == (595, 595, 25)
    assert bh.wire_size(bh.header_size(BAG)) == (580, 580)
    assert pn.header_panel_for_bag(610, 610) == (595, 595, 25)


def test_a_custom_bag_is_ordered_by_its_header_size():
    # "2 x Framed (20mm) Pocket Filter 855mm x 570mm x 5 Pockets ...":
    # the measurements are the header; the wire is 840 x 555.
    assert bh.header_size(CUSTOM) == (855, 570, 20)
    assert bh.wire_size(bh.header_size(CUSTOM)) == (840, 555)


def test_the_header_can_be_nudged_without_the_bag():
    nudged = dict(BAG, header_width=597, header_height=594, header_depth=25,
                  header_custom=True)
    assert bh.header_size(nudged) == (597, 594, 25)
    assert bh.wire_size(bh.header_size(nudged)) == (582, 579)
    assert bh.is_edited(nudged) and not bh.is_edited(BAG)
    assert nudged["width"] == 610                        # the bag is as it was
    assert bh.header_size(dict(BAG, header=False)) is None


def test_only_a_wire_header_gets_a_wire_cut():
    line = bh.header_line(BAG, page=3)
    assert line["Filter Type"] == "Header" and line["Bag Header"]
    assert (line["Short"], line["Long"], line["Channel"]) == (595, 595, 25)
    assert line["Header Wire Cut"] == "580*580" and line["Quantity"] == 4
    assert "(PAGE 3)" in line["Notes"]
    plain = bh.header_line(dict(BAG, on_wire=False))
    assert plain["Header Wire Cut"] == ""
    assert bh.header_text(BAG) == "Header 595x595x25mm, wire 580x580"


def test_headers_go_after_the_filters_and_count_in_the_total():
    flt = {"item_kind": "filter", "Filter Type": "Flat Panel", "Short": 595,
           "Long": 595, "Channel": 25, "Quantity": 2, "Media Type": "G4"}
    no_hdr = dict(BAG, header=False)
    filters, bags, total = bh.worksheet_split([flt, BAG, no_hdr, CUSTOM])
    assert [f.get("Bag Header", False) for f in filters] == [False, True, True]
    assert len(bags) == 3 and total == 6
    # Bags follow the 1 filter + 2 header pages: on pages 4, 5 and 6.
    assert "(PAGE 4)" in filters[1]["Notes"]
    assert "(PAGE 6)" in filters[2]["Notes"]
    validate_items(filters)              # no media on a header is fine


def test_a_header_has_no_wrap_and_takes_no_code():
    flt = {"item_kind": "filter", "Filter Type": "Flat Panel", "Short": 595,
           "Long": 595, "Channel": 25, "Quantity": 2, "Media Type": "G4"}
    hdr = bh.header_line(BAG)
    ctx = wb.order_context([flt, hdr, dict(flt)])
    assert ctx[1]["packed_with_bag"] and ctx[1]["wraps"] == []
    assert "packed with it" in wb.wrapping_lines(ctx[1])[0][0]
    alone = wb.order_context([flt, dict(flt)])
    codes = lambda c: [w.get("code") for w in c["wraps"]]
    assert codes(ctx[0]) == codes(alone[0])
    assert codes(ctx[2]) == codes(alone[1])


def test_the_worksheet_prints_a_header_page():
    from pdf_generator import generate_pdf
    filters, _bags, total = bh.worksheet_split([BAG])
    path = Path(tempfile.mkdtemp()) / "h.pdf"
    generate_pdf({"Customer Name": "Bells Creek", "Order Number": "PO-1",
                  "Date Ordered": "14/10/26", "Date Due": "ASAP"},
                 filters, str(path), grand_total=total)
    data = path.read_bytes()
    assert data.startswith(b"%PDF")
    assert len(re.findall(rb"/Type /Page(?!s)", data)) == 1


def test_custom_bag_filter_on_the_docket():
    assert "Custom Bag Filter" in bf.BAG_PRODUCT_TYPES
    assert bf.build_dims_line(CUSTOM) == \
        "855mm x 570mm x 5 Pockets, 480mm pocket depth"
    assert bf.build_label_line(CUSTOM).startswith(
        "2 x Custom Bag Filter F7 / ON WIRE")
    assert bf.generate_part_number(CUSTOM) == "CBFF7-855570480-5PWH"
    assert "Header 855x570x20mm, wire 840x555" in bf._build_bag_options(CUSTOM)
    assert bf.item_summary_short(CUSTOM) == "855×570×480 5P"
