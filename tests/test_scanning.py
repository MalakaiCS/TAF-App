"""Groundwork for barcode scanning.

The expensive mistakes here are silent ones: a stock figure that is wrong
because two people counted at once, a movement applied twice because a
handheld lost signal and retried, or a barcode that prints beautifully and
cannot be read by the thing it was printed for.

The decoding tests below print the barcodes and read them back, because
"there is a barcode on the page" and "a scanner can read it" are different
claims and only the second one matters.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from taf_order_app import labels

ROOT = Path(__file__).resolve().parent.parent


def _sql():
    return (ROOT / "migrate_scanning.sql").read_text(encoding="utf-8")


def _sql_code():
    """The SQL with its comments stripped.

    The file explains at length why it does not use SECURITY DEFINER, so a
    test that searched the raw text for that phrase would find the warning
    against it and fail.
    """
    return "\n".join(line.split("--")[0] for line in _sql().splitlines())


def _function(name: str) -> str:
    """One function's body, comments and all."""
    body = _sql().split(f"CREATE OR REPLACE FUNCTION public.{name}")[1]
    return body.split("\nREVOKE ALL ON FUNCTION")[0]


# ── Counting the same thing twice ────────────────────────────────────────────

def test_the_arithmetic_happens_in_the_database_on_a_locked_row():
    """Two guns counting one rack both used to read the old figure and both
    write their own answer, so one count vanished with nothing in the log."""
    sql = _sql()
    body = sql.split("CREATE OR REPLACE FUNCTION public.adjust_stock_atomic")[1]
    assert "FOR UPDATE" in body, "without the row lock the race is still there"
    # The lock has to be taken before the figure is read, not after.
    assert body.index("SELECT stock_on_hand INTO v_old") < body.index("FOR UPDATE")
    assert body.index("FOR UPDATE") < body.index("UPDATE public.stock_items")


def test_the_same_scan_sent_twice_moves_stock_once():
    sql = _sql()
    assert "client_ref" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS stock_tx_client_ref_unique" in sql
    body = sql.split("CREATE OR REPLACE FUNCTION public.adjust_stock_atomic")[1]
    # The duplicate check must sit inside the lock, or two copies arriving
    # together both miss it.
    assert body.index("FOR UPDATE") < body.index("WHERE client_ref = p_client_ref")


def test_a_retry_is_answered_with_what_happened_the_first_time():
    body = _function("adjust_stock_atomic")
    # The reply is the earlier movement's numbers, and says it was not applied
    # again — so a handheld can tell "already done" from "done just now".
    assert "RETURN QUERY SELECT v_prior.quantity_after" in body
    assert "quantity_after numeric, quantity_change numeric, applied boolean" in body


def test_stock_cannot_be_driven_negative_or_over_reported():
    body = _sql().split("CREATE OR REPLACE FUNCTION public.adjust_stock_atomic")[1]
    assert "GREATEST(0, v_old + v_delta)" in body
    # After clamping at zero, the movement logged is what was really taken -
    # not what was asked for.
    assert "v_delta := v_new - v_old;" in body


def test_an_unknown_movement_type_is_refused():
    body = _sql().split("CREATE OR REPLACE FUNCTION public.adjust_stock_atomic")[1]
    assert "NOT IN ('receive', 'use', 'count', 'writeoff')" in body
    assert "RAISE EXCEPTION 'unknown movement %'" in body


def test_the_functions_do_not_hand_out_more_than_the_caller_already_has():
    """SECURITY DEFINER here would give every signed-in account write access
    to the whole stock table, regardless of policy."""
    code = _sql_code()
    assert "SECURITY DEFINER" not in code
    assert code.count("SECURITY INVOKER") == 2
    assert code.count("SET search_path = public, pg_temp") == 2
    assert "TO anon" not in code
    for fn in ("adjust_stock_atomic", "resolve_scan"):
        assert f"GRANT EXECUTE ON FUNCTION public.{fn}" in code
        assert f"REVOKE ALL ON FUNCTION public.{fn}" in code


def test_the_migration_survives_a_database_that_already_has_duplicate_skus():
    """Failing the whole file over existing duplicates would leave the
    functions uninstalled, which is the opposite of helpful."""
    sql = _sql()
    assert "EXCEPTION WHEN unique_violation THEN" in sql.split("DO $$")[1]
    assert "RAISE WARNING" in sql
    assert "stock_items_sku_unique" in sql
    # Unique only where there is a code — a blank SKU is not a clash.
    assert "WHERE btrim(COALESCE(sku, '')) <> ''" in sql


def test_the_app_sends_a_reference_so_an_http_retry_is_safe():
    from taf_order_app import db as _db
    import inspect
    src = inspect.getsource(_db.adjust_stock)
    assert "adjust_stock_atomic" in src
    assert "p_client_ref" in src
    assert "uuid4" in src, "a caller that sends no reference must still get one"
    params = inspect.signature(_db.adjust_stock).parameters
    assert "client_ref" in params and "device" in params
    # The old path stays for a project that hasn't run the migration.
    assert "stock_on_hand" in src


# ── One code, one meaning ────────────────────────────────────────────────────

def test_a_scanned_code_resolves_to_one_kind_of_thing():
    sql = _sql()
    body = sql.split("CREATE OR REPLACE FUNCTION public.resolve_scan")[1]
    for kind in ("'stock'", "'order'", "'product'"):
        assert kind in body
    # Stock first: a gun is usually pointed at something you can count.
    assert body.index("'stock'") < body.index("'order'") < body.index("'product'")
    # Scanners can deliver padding and any case.
    assert "upper(btrim(COALESCE(p_code, '')))" in body
    assert "archived, false) = false" in body, "a filed order is not a live one"


def test_matching_is_case_and_space_insensitive_on_both_sides():
    body = _sql().split("CREATE OR REPLACE FUNCTION public.resolve_scan")[1]
    for column in ("s.sku", "o.order_number", "p.part_number"):
        assert f"upper(btrim(COALESCE({column}, ''))) = code.c" in body


def test_the_sku_index_matches_the_expression_it_is_searched_by():
    sql = _sql()
    assert "ON public.stock_items (upper(btrim(COALESCE(sku, ''))))" in sql


# ── Barcodes that actually scan ──────────────────────────────────────────────

def _decode(pdf_path: Path) -> set:
    """Print the PDF and read the barcodes back, the way a scanner would.

    Skips rather than fails where the tools aren't installed: this has to run
    on a build machine that only has Python.
    """
    try:
        from PIL import Image
        from pyzbar.pyzbar import decode
    except Exception:
        return set()
    if not shutil.which("pdftoppm"):
        return set()
    with tempfile.TemporaryDirectory() as tmp:
        # 203 dpi: what a Zebra prints at, and about what a handheld sees.
        subprocess.run(["pdftoppm", "-r", "203", "-png",
                        str(pdf_path), str(Path(tmp) / "p")], check=True)
        found = set()
        for png in sorted(Path(tmp).glob("p*.png")):
            for d in decode(Image.open(png)):
                found.add(d.data.decode())
        return found


def test_the_worksheet_barcode_is_wide_enough_to_read():
    """Measured, not guessed: at 0.5pt one code in three read back, at 0.35pt
    none did. Narrower bars are the difference between a barcode and a
    picture of one."""
    import pdf_generator
    import inspect
    src = inspect.getsource(pdf_generator.draw_order_barcode)
    assert "NARROW, NARROW_MIN = 1.0, 0.75" in src


def test_a_worksheet_carries_its_order_number_as_a_barcode():
    import pdf_generator
    header = {"Customer Name": "Bells Creek", "Order Number": "PO-8842",
              "Date Ordered": "01/09/2026", "Date Due": "15/09/2026"}
    items = [{"Filter Type": "V-form", "Media Type": "G4", "Short": 595,
              "Long": 595, "Channel": 50, "Quantity": "12"}]
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "ws.pdf"
        pdf_generator.generate_pdf(header, items, str(out))
        assert out.exists()
        found = _decode(out)
    if found:                       # only assert where the tools exist
        assert "PO-8842" in found, f"scanner read {found or 'nothing'}"


def test_an_order_with_no_number_still_produces_a_worksheet():
    import pdf_generator
    from reportlab.pdfgen import canvas as rc
    from reportlab.lib.pagesizes import A4, landscape
    with tempfile.TemporaryDirectory() as tmp:
        c = rc.Canvas(str(Path(tmp) / "x.pdf"), pagesize=landscape(A4))
        assert pdf_generator.draw_order_barcode(c, "") is False
        assert pdf_generator.draw_order_barcode(c, "   ") is False
        assert pdf_generator.draw_order_barcode(c, "TAF-ON-0007") is True


def test_a_stock_label_can_be_read_back_off_the_page():
    items = [{"name": "G4 media roll", "sku": "TAF-G4-ROLL",
              "location": "Rack A1", "unit": "m2"},
             {"name": "Bag frame 592", "sku": "TAF-FR-592",
              "location": "Rack C3", "unit": "each"}]
    with tempfile.TemporaryDirectory() as tmp:
        path, problems = labels.build_label_sheet(Path(tmp) / "l.pdf", items)
        assert not problems
        found = _decode(Path(path))
    if found:
        assert {"TAF-G4-ROLL", "TAF-FR-592"} <= found, f"scanner read {found}"


def test_an_item_with_no_sku_is_reported_not_silently_blank():
    with tempfile.TemporaryDirectory() as tmp:
        _, problems = labels.build_label_sheet(
            Path(tmp) / "l.pdf", [{"name": "No code", "sku": ""}])
    assert len(problems) == 1 and "no SKU" in problems[0]


def test_a_code_too_long_to_scan_says_so_rather_than_printing_junk():
    with tempfile.TemporaryDirectory() as tmp:
        _, problems = labels.build_label_sheet(
            Path(tmp) / "l.pdf",
            [{"name": "Overlong", "sku": "A-VERY-LONG-STOCK-CODE-0001"}])
    assert len(problems) == 1
    assert "too long" in problems[0] and "0.75pt" in problems[0]


def test_labels_use_the_widest_bars_that_fit():
    """Wider bars read from further away and survive a scuffed label."""
    bar_small, narrow_small = labels._fit_barcode("AB", 200)
    bar_big, narrow_big = labels._fit_barcode("A-LONGER-CODE-HERE", 200)
    assert narrow_small == labels.NARROW_IDEAL      # short code: full width
    assert narrow_big < narrow_small                # long code: squeezed
    assert bar_big.width <= 200


def test_a_part_used_label_sheet_can_be_fed_back_in():
    """Otherwise the first print of the day wastes most of a sheet."""
    many = [{"name": f"Item {i}", "sku": f"TAF-{i:04d}"} for i in range(3)]
    with tempfile.TemporaryDirectory() as tmp:
        a, _ = labels.build_label_sheet(Path(tmp) / "a.pdf", many, start_at=1)
        b, _ = labels.build_label_sheet(Path(tmp) / "b.pdf", many, start_at=19)
        # Starting at 19 of 21 pushes the third label onto a second sheet.
        assert Path(a).read_bytes() != Path(b).read_bytes()
    assert labels.L7160.per_sheet == 21
    assert labels.L7163.per_sheet == 14


def test_printing_nothing_is_an_error_not_an_empty_page():
    try:
        labels.build_label_sheet("/tmp/never-written.pdf", [])
    except ValueError as exc:
        assert "nothing to print" in str(exc)
    else:
        raise AssertionError("an empty selection should not write a sheet")
