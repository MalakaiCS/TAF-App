"""Quoting anything this business sells, not just a made-to-measure filter.

A quote could only ever carry filter lines. A bag filter, a roll of media, a
freight charge or an hour of labour had nowhere to go — so those went out on
paper, or not at all.
"""
from __future__ import annotations

import re
from pathlib import Path

from taf_order_app import part_numbers as pn, pricing

ROOT = Path(__file__).resolve().parent.parent

BAG = {"item_kind": "catalogue", "Product Type": "Bag Filter",
       "Part Number": "BAG-592-6P",
       "Description": "Bag filter 592x592, 6 pocket, F7",
       "Quantity": 8, "Unit": "each", "Unit Price": 47.25}

ROLL = {"item_kind": "catalogue", "Product Type": "Media Roll",
        "Description": "G4 media roll 20m x 2m",
        "Quantity": 3, "Unit": "roll", "Unit Price": 186.0}

FILTER = {"item_kind": "filter", "Filter Type": "V-form", "Media Type": "G4",
          "Short": 595, "Long": 595, "Channel": 50, "Quantity": "12",
          "Part Number": "PPF50-1.8-G4"}


def test_a_bought_in_product_carries_its_own_price():
    """It came off the price list with a price attached. Working one back from
    dimensions a bag filter hasn't got would only lose it."""
    unit, source = pricing.price_for_item(BAG, {})
    assert unit == 47.25
    assert source == "list"


def test_a_mixed_quote_totals_correctly():
    lines = pricing.quote_lines([FILTER, BAG, ROLL], {"PPF50-1.8-G4": 48.5})
    assert [l["line_total"] for l in lines] == [582.00, 378.00, 558.00]
    totals = pricing.quote_totals(lines)
    assert totals["subtotal"] == 1518.00
    assert totals["gst"] == 151.80
    assert totals["total"] == 1669.80


def test_a_product_line_reads_as_itself_on_the_quote():
    assert pricing.describe_item(BAG) == "Bag filter 592x592, 6 pocket, F7"
    # The kind is worth prefixing when the description doesn't already say it.
    assert pricing.describe_item(
        {"item_kind": "catalogue", "Product Type": "Freight",
         "Description": "Brisbane metro"}) == "Freight - Brisbane metro"
    # A line with only a part number still has something to show.
    assert pricing.describe_item(
        {"item_kind": "catalogue", "Part Number": "X-1"}) == "X-1"


def test_a_picked_part_number_is_not_overwritten():
    """Deriving a part number from dimensions a bought-in product doesn't
    have would blank the one it was chosen by."""
    stamped = pn.apply_derived_fields(dict(BAG), {})
    assert stamped["Part Number"] == "BAG-592-6P"
    # And the filter path still derives one as it always did.
    derived = pn.apply_derived_fields(
        {k: v for k, v in FILTER.items() if k != "Part Number"}, {})
    assert derived["Part Number"]


def test_an_unpriced_product_says_why_in_its_own_terms():
    """'no filter type, so no part number' is meaningless on a labour line."""
    labour = {"item_kind": "catalogue", "Product Type": "Labour",
              "Description": "Site install", "Quantity": 4, "Unit Price": 0}
    assert pricing.why_unpriced(labour) == "no price entered for this line"
    missing = {"item_kind": "catalogue", "Part Number": "NOSUCH-1",
               "Description": "Thing", "Quantity": 1, "Unit Price": 0}
    assert "not in the price list" in pricing.why_unpriced(missing, {"A": 1.0})


def test_an_unpriced_product_is_kept_and_excluded_not_dropped():
    lines = pricing.quote_lines([BAG, {"item_kind": "catalogue",
                                       "Description": "Site install",
                                       "Quantity": 4, "Unit Price": 0}], {})
    assert len(lines) == 2, "the line must still appear on the quote"
    assert pricing.quote_totals(lines)["subtotal"] == 378.00
    assert len(pricing.unpriced(lines)) == 1


def test_a_product_line_invoices_to_xero():
    rows, missing = pricing.invoice_for_order(
        {"Order Number": "PO-1", "Customer Name": "X",
         "Date Ordered": "01/09/2026"}, [BAG, ROLL])
    assert len(rows) == 2 and not missing
    assert rows[0]["InventoryItemCode"] == "BAG-592-6P"
    assert rows[0]["*UnitAmount"] == "47.25"
    assert rows[0]["*Quantity"] == "8"


# ── The screen ───────────────────────────────────────────────────────────────

def _gui_source() -> str:
    return (ROOT / "modern_order_gui.py").read_text(encoding="utf-8")


def test_add_line_offers_every_kind_of_product():
    src = _gui_source()
    menu = src.split("def _quote_add_menu")[1].split("\n    def ")[0]
    for label in ("Filter", "Bag filter or media roll",
                  "From the price list", "Manage product types"):
        assert label in menu, f"Add Line does not offer: {label}"


def test_editing_a_line_opens_the_dialog_it_was_made_in():
    """Editing a media roll in the filter dialog would ask for a channel
    depth it hasn't got."""
    src = _gui_source()
    edit = src.split("def _edit_quote_item")[1].split("\n    def ")[0]
    assert 'kind == "catalogue"' in edit
    assert 'kind == "bag"' in edit
    assert "BagLineItemDialog" in edit and "LineItemDialog" in edit


def test_the_product_picker_searches_the_whole_price_list():
    src = _gui_source()
    look = src.split("def _price_list_lookup")[1].split("\n    def ")[0]
    assert "get_price_rows" in look, "it must search the shared price list"
    assert "except Exception" in look, "and still work offline"


def test_product_types_are_shared_not_stuck_on_one_pc():
    """A product type added on the office PC is no use if the person writing
    quotes on another one cannot pick it."""
    src = _gui_source()
    assert '_persist_catalog_key("product_types"' in src
    assert '"product_types":   PRODUCT_TYPES' in src   # local cache too
    assert 'data.get("product_types")' in src          # and read back


def test_the_product_types_shipped_cover_what_is_actually_sold():
    # Read from the source rather than importing: this suite runs in CI before
    # the dependencies (Tk included) are installed, on purpose.
    src = _gui_source()
    block = src.split("DEFAULT_PRODUCT_TYPES = [")[1].split("]")[0]
    names = dict(re.findall(r'"name":\s*"([^"]+)",\s*"unit":\s*"([^"]+)"',
                            block))
    for expected in ("Bag Filter", "Media Roll"):
        assert expected in names, f"{expected} should be there out of the box"
    assert names["Media Roll"] == "roll"
    assert names["Labour"] == "hour"


def test_an_unknown_product_type_still_has_a_unit():
    src = _gui_source()
    fn = src.split("def product_type_unit")[1].split("\ndef ")[0]
    assert 'return "each"' in fn, "an unknown type must not come back blank"


def test_a_product_line_cannot_be_saved_blank():
    src = _gui_source()
    save = src.split("class CatalogueLineDialog")[1].split("def _save")[1]
    assert "Quantity must be more than zero" in save
    assert "Nothing to quote" in save, \
        "a line with no description and no part number shows as blank"


# ── The look of it ───────────────────────────────────────────────────────────

def test_an_empty_table_says_what_it_means():
    """A blank white rectangle says nothing — not whether the list is empty,
    still loading, or filtered down to nothing."""
    src = _gui_source()
    assert "def attach_empty_state" in src
    fn = src.split("def attach_empty_state")[1].split("\ndef ")[0]
    # It keeps itself in step by hooking the tree's own insert and delete, so
    # no caller has to remember to.
    assert 'for name in ("insert", "delete")' in fn
    assert "place_forget()" in fn and "panel.place(" in fn
    # Which tables it is attached to, whatever the indentation happens to be.
    attached = {t.strip() for t in
                re.findall(r"attach_empty_state\(\s*([\w.]+),", src)}
    for table in ("self.tree", "self.quote_tree", "self.orders_tree",
                  "self.delivery_tree", "self.products_tree",
                  "self._stock_tree"):
        assert table in attached, f"{table} has no empty state"


def test_nothing_still_draws_a_hard_black_border():
    """relief=solid with bd=1 draws BLACK in Tk whatever the widget colours
    are — that was the hard outline round the notes box and every panel."""
    src = _gui_source()
    assert 'relief="solid", bd=1' not in src
    assert 'bd=1, relief="solid"' not in src


def test_the_window_declares_itself_dpi_aware_before_tk_starts():
    """Said after the first window exists, it has no effect at all."""
    src = _gui_source()
    start = src.split("def _start_app")[1]
    assert start.index("_enable_hidpi()") < start.index("root = tk.Tk()")
    assert "_apply_ui_scale(root)" in start


def test_measurements_in_pixels_scale_with_the_screen():
    """A row sized for 96 DPI clips its own text at 150%."""
    src = _gui_source()
    assert "rowheight=px(" in src
    assert "def px(" in src
    # Column widths too: these clipped "Qty" to "Qt)" at 150%.
    import re
    assert not re.search(r"\.column\([^)]*\bwidth=\d", src), \
        "a table column still has an unscaled pixel width"


# ── Getting around ───────────────────────────────────────────────────────────

def test_every_tab_has_a_number_and_they_match_the_bar():
    """Ctrl+1..0 must land on the tab that is actually in that position, so
    both come off one list."""
    src = _gui_source()
    assert "_TAB_ORDER = list(_TAB_LABELS)" in src
    assert "tabs = [(k, self._TAB_LABELS[k]) for k in self._TAB_ORDER]" in src
    labels = re.search(r"_TAB_LABELS = \{(.*?)\n    \}", src, re.S).group(1)
    keys = re.findall(r'"(\w+)":', labels)
    assert keys[0] == "dashboard" and len(keys) == 10, keys
    # Ctrl+0 is the tenth, the way a browser numbers its tabs.
    assert "digit = (i + 1) % 10" in src


def test_a_shortcut_cannot_fire_behind_an_open_dialog():
    """bind_all reaches every window, dialogs included — without the guard,
    Ctrl+N inside the line-item dialog starts an order behind it."""
    src = _gui_source()
    fn = src.split("def _shortcut")[1].split("\n    def ")[0]
    assert "grab_current() is not None" in fn
    assert 'return "break"' in fn


def test_delete_is_bound_to_the_tables_not_the_whole_window():
    """A global Delete would eat a line while someone edited a field."""
    src = _gui_source()
    assert 'bind_all("<Delete>' not in src
    for tree in ("self.tree", "self.quote_tree"):
        assert f'{tree}.bind("<Delete>"' in src, f"{tree} has no Delete key"


def test_the_shortcut_list_matches_what_is_actually_bound():
    """A list that drifts from the bindings is worse than no list."""
    src = _gui_source()
    binder = src.split("def _bind_shortcuts")[1].split("\n    def ")[0]
    listed = src.split("SHORTCUTS = [")[1].split("\n    ]")[0]
    for combo, doc in (("Control-n", "Ctrl+N"), ("Control-f", "Ctrl+F"),
                       ("Control-s", "Ctrl+S"), ("Control-p", "Ctrl+P"),
                       ("<F5>", "F5"), ("<F1>", "F1")):
        assert combo in binder, f"{doc} is documented but not bound"
        assert doc in listed, f"{combo} is bound but not documented"


def test_starting_an_order_takes_you_to_the_order():
    """Ctrl+N from the Dashboard used to clear a form you could not see."""
    src = _gui_source()
    fn = src.split("def _new_order(self)")[1].split("\n    def ")[0]
    assert '_show_tab("new_order")' in fn


def test_a_pristine_form_is_not_treated_as_unsaved_work():
    """A fresh form starts with Date Due = ASAP; counting that as data made
    New Order ask 'clear the current order?' when there was nothing to
    clear."""
    src = _gui_source()
    fn = src.split("def _new_order(self)")[1].split("\n    def ")[0]
    assert 'key == "Date Due" and v.get().strip() == "ASAP"' in fn


def test_enter_saves_the_dialogs_used_all_day():
    src = _gui_source()
    for cls in ("LineItemDialog", "BagLineItemDialog"):
        body = src.split(f"class {cls}(tk.Toplevel)")[1].split("\nclass ")[0]
        assert '.bind("<Return>", lambda _e: self._save())' in body, \
            f"{cls} still needs the mouse to save"


def test_escape_closes_every_dialog():
    src = _gui_source()
    missing = []
    for m in re.finditer(r"^class (\w+)\(tk\.Toplevel\)", src, re.M):
        name = m.group(1)
        if name in ("_ProgressDialog", "JobNumberHighlighter", "CalendarPicker"):
            continue          # a progress bar and a canvas tool, not forms
        body = src[m.start():]
        nxt = re.search(r"\nclass ", body[10:])
        body = body[:nxt.start() + 10] if nxt else body
        if '"<Escape>"' not in body:
            missing.append(name)
    assert not missing, f"Escape does not close: {missing}"


def test_the_shortcuts_can_be_found_without_knowing_them():
    src = _gui_source()
    assert "⌨  Shortcuts" in src, "there is no way in but the shortcut itself"
    assert "def _show_shortcuts" in src


# ── Clutter ──────────────────────────────────────────────────────────────────

def _tab_button_count(src: str, tab: str) -> int:
    m = re.search(rf"    def _build_{tab}_tab\(self\)", src)
    body = src[m.start():]
    nxt = re.search(r"\n    def ", body[10:])
    body = body[:nxt.start() + 10] if nxt else body
    return len(re.findall(r"flat_btn\(|menu_btn\(", body))


def test_no_working_screen_is_a_wall_of_buttons():
    """Previous Orders had seventeen. Nothing stood out, and the two things
    anyone actually does were lost among fifteen they don't."""
    src = _gui_source()
    for tab, limit in (("prev_orders", 8), ("quotes", 8), ("customers", 7),
                       ("stock", 6), ("delivery", 5)):
        n = _tab_button_count(src, tab)
        assert n <= limit, f"{tab} is back up to {n} buttons"


def test_the_menu_decides_what_applies_when_it_opens():
    """Send and Convert only mean something once a quote is saved. Built at
    start-up they would be wrong the moment anything changed."""
    src = _gui_source()
    fn = src.split("def menu_btn")[1].split("\ndef ")[0]
    assert "items() if callable(items) else items" in fn
    assert 'state="normal" if command else "disabled"' in fn
    # And the quote menu uses that, rather than enabling buttons by hand.
    assert "def _quote_actions()" in src
    assert "self._share_quote_link if saved else None" in src


def test_destructive_actions_are_not_next_to_harmless_ones():
    """Delete sat one button along from Print."""
    src = _gui_source()
    body = src[src.index("def _build_prev_orders_tab"):]
    body = body[:body.index("\n    def _refresh_orders_list")]
    assert "_delete_prev_order" not in re.sub(r"menu_btn\(.*?\], bg=", "",
                                              body, flags=re.S), \
        "deleting an order is a bare button again"


def test_an_empty_quote_does_not_say_so_twice():
    src = _gui_source()
    assert "No lines yet." not in src, \
        "the table's own empty state already says this"
