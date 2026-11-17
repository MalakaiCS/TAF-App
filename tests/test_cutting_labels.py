"""Wire and media cutting labels: 3" x 2", one for each worksheet line, with
the same cut sizes the worksheet prints."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import cutting_labels as cl     # noqa: E402

HEADER = {"Customer Name": "Air Diffusion - Acacia Ridge",
          "Order Number": "865486", "Date Due": "10/11/26"}
VFORM = {"Filter Type": "V-form", "Media Type": "G4", "Short": 260,
         "Long": 440, "Channel": 50, "Quantity": 4}


def test_a_label_says_what_the_worksheet_says():
    import pdf_generator
    wire, media = cl.cuts_for(VFORM)          # separate labels
    sheet = pdf_generator._wire_media(260, 440, 50, "V50", 4)
    assert wire["kind"] == "WIRE" and media["kind"] == "MEDIA"
    assert f"{wire['cut'][0]}*{wire['cut'][1]}" == sheet["wc"] == "245*598"
    assert wire["cut"][2] == sheet["wq"] == 8
    assert f"{media['cut'][0]}*{media['cut'][1]}" == sheet["mc"] == "305*638"
    assert media["cut"][2] == sheet["mq"] == 4


def test_every_kind_of_line():
    wire, media = cl.cuts_for(dict(VFORM, **{"Filter Type": "Flat Panel",
                                             "Short": 495, "Long": 595,
                                             "Channel": 25, "Quantity": 10}))
    assert wire["cut"] == (485, 585, 20) and media["cut"] == (495, 595, 10)
    # Flyscreens are left out altogether.
    assert cl.cuts_for({"Filter Type": "Flyscreen", "Short": 500, "Long": 600,
                        "Channel": 9, "Quantity": 2}) == []
    # A stepped filter: only the V-form inside it.
    stepped = cl.cuts_for(dict(VFORM, **{"Filter Type": "Stepped Filter",
                                         "Short": 595, "Long": 595,
                                         "Channel": 70, "Quantity": 1}))
    assert [(s["kind"], s["title"]) for s in stepped] == [
        ("WIRE", "Stepped - inner V60"), ("MEDIA", "Stepped - inner V60")]
    header = cl.cuts_for({"Bag Header": True, "Channel": 25, "Quantity": 3,
                          "Header Wire Cut": "580*580", "Header Wire Qty": 3})
    assert [(h["kind"], h["cut"]) for h in header] == [("WIRE", (580, 580, 3))]
    # Nothing to cut: a stock V-form, a header-only line.
    assert cl.cuts_for(dict(VFORM, **{"Use Stock V-form": True})) == []
    assert cl.cuts_for(dict(VFORM, Header=True)) == []


def test_one_three_by_two_inch_page_per_label():
    fly = {"Filter Type": "Flyscreen", "Short": 500, "Long": 600, "Quantity": 2}
    labs = cl.labels_for_order(HEADER, [VFORM, fly, dict(VFORM, Short=300)],
                               page_start=2, grand_total=5)
    assert [(l["line"], l["kind"]) for l in labs] == [
        ("2 of 5", "WIRE"), ("2 of 5", "MEDIA"), ("4 of 5", "WIRE"),
        ("4 of 5", "MEDIA")]
    assert labs[0]["order_number"] == "865486"
    with tempfile.TemporaryDirectory() as tmp:
        out = cl.render_pdf(labs, str(Path(tmp) / "c.pdf"))
        try:
            from pypdf import PdfReader
        except Exception:
            return
        pages = PdfReader(out).pages
        assert len(pages) == 4
        box = pages[0].mediabox
        assert (round(float(box.width)), round(float(box.height))) == (216, 144)
        wire = " ".join(pages[0].extract_text().split())
        media = " ".join(pages[1].extract_text().split())
        for words in ("865486", "LINE 2 of 5", "WIRE", "245 × 598", "x 8",
                      "DUE TUE 10 NOV 2026"):
            assert words in wire, (words, wire)
        assert "305 × 638" not in wire
        for words in ("MEDIA G4", "305 × 638", "x 4"):
            assert words in media, (words, media)
        assert "245 × 598" not in media
    try:
        cl.render_pdf([], "/nonexistent/x.pdf")
        raise AssertionError("an empty set of labels was printed")
    except ValueError:
        pass
