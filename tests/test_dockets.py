"""The paperwork that goes out with the filters, and the copy that comes back.

The run sheet is for the driver. A docket is for one customer: what they are
being handed, and their name and signature saying they got it. That signed
sheet is the only thing that settles "we never received those" three weeks
later, so the things worth testing here are the ones that would make it
useless as evidence.

An order missing from the list somebody signed. A total that does not match
what is on the pallet. Lines that failed to load printing as though the order
were empty. And the signature block ending up on the copy the customer walks
out with.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import dockets as _dk        # noqa: E402

GUI = (ROOT / "modern_order_gui.py").read_text(encoding="utf-8")

FILTER = {"item_kind": "filter", "Filter Type": "V-form", "Media Type": "G4",
          "Short": 595, "Long": 595, "Channel": 50, "Quantity": "12",
          "Part Number": "PPF50-1.8-G4"}
PANEL = {"item_kind": "filter", "Filter Type": "Flat Panel",
         "Media Type": "F7", "Short": 495, "Long": 495, "Channel": 48,
         "Quantity": "4", "Part Number": "FPF48-0.24-F7"}

# One customer collecting five orders at once, which is the case this was
# asked for, plus somebody else being delivered to.
FIVE = [{"order_no": f"PO-90{n}", "customer": "Bells Creek",
         "date_due": "15/09/2026", "location": "Pick Up"} for n in range(1, 6)]
OTHER = {"order_no": "TAF-ON-0002", "customer": "CAS - Tweed",
         "date_due": "20/09/2026", "location": "Local"}


def _items(order):
    return [dict(FILTER)] if order["order_no"].endswith(("1", "3", "5")) \
        else [dict(FILTER), dict(PANEL)]


def _build(orders):
    return _dk.build_dockets(_dk.group_by_customer(orders), _items)


# ── One docket per customer, not per order ───────────────────────────────────

def test_five_orders_for_one_customer_make_one_docket():
    """Somebody who collects five at once signs once. Five separate sheets
    is five signatures to chase and four chances to lose one."""
    built = _build(FIVE)
    assert len(built) == 1, [d["customer"] for d in built]
    assert built[0]["order_count"] == 5


def test_every_order_number_is_on_it_with_its_own_filters_under_it():
    """The thing that was asked for. A dispute about one order must not put
    the other four in doubt, and it will if they are run together."""
    docket = _build(FIVE)[0]
    assert [e["order_no"] for e in docket["orders"]] == \
        [o["order_no"] for o in FIVE]
    for entry in docket["orders"]:
        assert entry["lines"], f"{entry['order_no']} has nothing under it"
        for line in entry["lines"]:
            assert line["description"] and line["quantity"]


def test_two_customers_get_two_dockets():
    built = _build(FIVE + [OTHER])
    assert [d["customer"] for d in built] == ["Bells Creek", "CAS - Tweed"]


def test_customers_come_out_in_a_settled_order():
    """Printing the same run twice must not shuffle the pile."""
    a = [d["customer"] for d in _build(FIVE + [OTHER])]
    b = [d["customer"] for d in _build([OTHER] + list(reversed(FIVE)))]
    assert a == b


def test_an_order_with_no_customer_still_gets_a_docket():
    """It is still going out of the door. Dropping it means handing
    somebody goods with no paperwork at all."""
    built = _build([{"order_no": "PO-1", "customer": "", "location": "Local"}])
    assert len(built) == 1
    assert built[0]["customer"] == "(no customer)"


def test_two_spellings_of_one_customer_are_not_quietly_merged():
    """They would produce two dockets, which is wrong — and is exactly what
    the order list says. Inventing a match here would hide it instead."""
    built = _build([dict(OTHER, customer="CAS - Tweed"),
                    dict(OTHER, order_no="PO-2", customer="CAS Tweed")])
    assert len(built) == 2


# ── What it says was handed over ─────────────────────────────────────────────

def test_the_total_counts_filters_not_lines():
    """"16 items" has to mean sixteen filters on the pallet. Counting lines
    would say two, and somebody would sign for two."""
    docket = _build([FIVE[0]])[0]           # one line, quantity 12
    assert docket["item_count"] == 12


def test_a_quantity_nobody_filled_in_counts_as_one():
    docket = _dk.build_dockets(
        _dk.group_by_customer([FIVE[0]]),
        lambda _o: [dict(FILTER, Quantity="")])[0]
    assert docket["item_count"] == 1


def test_lines_that_could_not_be_read_say_so():
    """Printing the order with nothing under it reads as "this order is
    empty", and somebody signs for goods that are not listed."""
    def boom(_order):
        raise RuntimeError("no connection")
    docket = _dk.build_dockets(_dk.group_by_customer([FIVE[0]]), boom)[0]
    entry = docket["orders"][0]
    assert entry["lines"] == []
    assert "could not be read" in entry["note"]


def test_an_order_that_really_has_no_lines_says_that_instead():
    docket = _dk.build_dockets(_dk.group_by_customer([FIVE[0]]),
                               lambda _o: [])[0]
    assert "No lines recorded" in docket["orders"][0]["note"]


def test_an_order_that_failed_is_still_on_the_docket():
    """Leaving it off hands somebody a sheet to sign that is missing an
    order they are being given."""
    docket = _dk.build_dockets(
        _dk.group_by_customer(FIVE),
        lambda o: None if o["order_no"] == "PO-903" else _items(o))[0]
    assert len(docket["orders"]) == 5
    assert [e["order_no"] for e in docket["orders"]].count("PO-903") == 1


# ── Collected, or delivered ──────────────────────────────────────────────────

def test_a_pick_up_is_not_described_as_a_delivery():
    """The wording on a signed docket is the wording read back to you
    later. "Delivered to" about something collected from the counter is
    a document arguing against itself."""
    assert _dk.handover(FIVE) == _dk.COLLECTED
    assert _dk.handover([OTHER]) == _dk.DELIVERED


def test_a_mix_says_both_rather_than_picking_one():
    assert _dk.handover(FIVE + [OTHER]) == _dk.BOTH


def test_nothing_at_all_is_treated_as_a_delivery():
    assert _dk.handover([]) == _dk.DELIVERED


# ── The two copies ───────────────────────────────────────────────────────────

def _pages_without_pypdf(path):
    """The text of each page, using nothing but the standard library.

    pypdf is a real dependency and is what this uses when it works, but it
    pulls in a compiled crypto library that is broken on some machines — and
    "the PDF checks did not run" must not be indistinguishable from "the PDF
    checks passed". So there is a second way in.

    ReportLab writes one content stream per page, in page order, ASCII85
    encoded and then deflated, with the visible text in (...)Tj operators.
    """
    import base64
    import re as _re
    import zlib

    raw = Path(path).read_bytes()
    pages = []
    for chunk in _re.findall(rb"stream\r?\n(.*?)endstream", raw, _re.S):
        body = chunk.strip()
        try:
            body = zlib.decompress(base64.a85decode(body, adobe=True))
        except Exception:
            continue                    # a font or an image, not a page
        words = [w.decode("latin-1") for w in
                 _re.findall(rb"\((.*?)\)\s*Tj", body)]
        pages.append("\n".join(words))
    return pages


def _pdf_pages(dockets):
    with tempfile.TemporaryDirectory() as tmp:
        out = _dk.build_dockets_pdf(Path(tmp) / "d.pdf", dockets)
        try:
            import pypdf
        except (Exception, BaseException) as exc:
            # BaseException on purpose. A mismatched compiled crypto library
            # does not raise ImportError, it panics out of Rust as a
            # PanicException, which is not an Exception and sails straight
            # through a normal guard.
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            return _pages_without_pypdf(out)
        reader = pypdf.PdfReader(out)
        return [p.extract_text() for p in reader.pages]


def test_there_are_two_pages_per_customer():
    pages = _pdf_pages(_build(FIVE + [OTHER]))
    assert len(pages) == 4, len(pages)


def test_one_is_theirs_and_one_is_ours():
    pages = _pdf_pages(_build(FIVE))
    assert _dk.CUSTOMER_COPY in pages[0]
    assert _dk.OFFICE_COPY in pages[1]


def test_only_the_copy_we_keep_is_signed():
    """A signature block on the customer's copy gets signed by mistake and
    walks out of the door, which leaves us with nothing."""
    theirs, ours = _pdf_pages(_build(FIVE))
    assert "Signature" in ours
    assert "Signature" not in theirs
    assert "keep it" in theirs


def test_both_copies_list_exactly_the_same_orders():
    """They are the same document. A customer copy that differs from the
    signed one is worse than having no copy at all."""
    theirs, ours = _pdf_pages(_build(FIVE))
    for order in FIVE:
        assert order["order_no"] in theirs, order["order_no"]
        assert order["order_no"] in ours, order["order_no"]


def test_the_filters_are_printed_under_their_order_number():
    page = _pdf_pages(_build([FIVE[1]]))[0]      # PO-902: two lines
    assert "Order PO-902" in page
    assert "PPF50-1.8-G4" in page and "FPF48-0.24-F7" in page
    assert page.index("Order PO-902") < page.index("PPF50-1.8-G4")


def test_a_collection_docket_asks_who_collected_it():
    ours = _pdf_pages(_build(FIVE))[1]
    assert "Collected by" in ours
    delivered = _pdf_pages(_build([OTHER]))[1]
    assert "Received by" in delivered


def test_printing_nothing_produces_a_page_that_says_so():
    """Rather than a zero-page PDF, or a crash, when somebody prints with
    an empty run."""
    pages = _pdf_pages([])
    assert len(pages) == 1
    assert "Nothing was selected" in pages[0]


# ── Reaching it from the Delivery tab ────────────────────────────────────────

def test_the_button_is_on_the_delivery_tab():
    fn = GUI.split("def _build_delivery_tab")[1].split("\n    def ")[0]
    assert "Print Delivery Dockets" in fn
    assert "_print_dockets" in fn


def test_selecting_nothing_prints_the_whole_run():
    """Loading the van in the morning is the whole run; one customer at the
    counter is a selection. Making somebody select all of it first is a
    step that gets skipped and then the wrong thing prints."""
    fn = GUI.split("def _print_dockets")[1].split("\n    def ")[0]
    assert "_selected_delivery_orders" in fn
    assert "_run_grouped" in fn


def test_the_lines_are_fetched_off_the_main_thread():
    """One database round trip per order, with somebody standing at the
    counter. A window that stops responding there is the counter stopping."""
    fn = GUI.split("def _print_dockets")[1].split("\n    def ")[0]
    assert "threading.Thread" in fn
    assert "daemon=True" in fn


def test_a_failure_is_reported_rather_than_a_silent_nothing():
    fn = GUI.split("def _print_dockets")[1].split("\n    def ")[0]
    assert "showerror" in fn


def test_printing_dockets_is_written_down():
    """Who printed what, for the same reason the docket exists at all."""
    fn = GUI.split("def _print_dockets")[1].split("\n    def ")[0]
    assert 'log_action("dockets_printed"' in fn


def test_a_printer_that_refuses_still_leaves_the_pdf_openable():
    fn = GUI.split("def _send_dockets_to_printer")[1].split("\n    def ")[0]
    assert "_open_path" in fn
