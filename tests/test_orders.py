"""Due dates and delivery runs."""
import datetime

from taf_order_app import delivery


def _order(status="Complete", due="", region="Local", order_no="PO1",
           customer="CAS - Bells Creek", items=3):
    return {"status": status, "date_due": due, "location": region,
            "order_no": order_no, "customer": customer, "n_items": items}


def _days(n):
    return (datetime.date.today() + datetime.timedelta(days=n)).strftime("%d/%m/%Y")


# ── What is ready to go out ─────────────────────────────────────────────────

def test_only_completed_work_is_ready_to_load():
    orders = [_order(status="Complete"), _order(status="Pending"),
              _order(status="In Production"), _order(status="Dispatched")]
    ready = delivery.ready_for_delivery(orders)
    assert len(ready) == 1 and ready[0]["status"] == "Complete"


def test_planning_ahead_can_include_work_still_being_made():
    orders = [_order(status="Complete"), _order(status="In Production"),
              _order(status="Dispatched")]
    ready = delivery.ready_for_delivery(orders, include_in_production=True)
    assert len(ready) == 2
    assert all(o["status"] != "Dispatched" for o in ready)


def test_the_oldest_promise_is_loaded_first():
    orders = [_order(due=_days(5), order_no="LATER"),
              _order(due=_days(-3), order_no="OVERDUE"),
              _order(due="", order_no="NODATE"),
              _order(due="ASAP", order_no="ASAP")]
    got = [o["order_no"] for o in delivery.ready_for_delivery(orders)]
    assert got[0] == "ASAP"          # "now" beats every date
    assert got[1] == "OVERDUE"
    assert got[-1] == "NODATE"       # undated sinks to the bottom


# ── Grouping a run ──────────────────────────────────────────────────────────

def test_regions_come_out_in_run_order():
    orders = [_order(region="Freight"), _order(region="Pick Up"),
              _order(region="Local"), _order(region="Gold Coast")]
    regions = [name for name, _rows in
               delivery.group_by_region(delivery.ready_for_delivery(orders))]
    assert regions == ["Pick Up", "Local", "Gold Coast", "Freight"]


def test_an_empty_region_is_not_printed():
    grouped = delivery.group_by_region([_order(region="Local")])
    assert [name for name, _ in grouped] == ["Local"]


def test_an_order_with_no_region_still_gets_delivered():
    grouped = delivery.group_by_region([_order(region=""), _order(region="Local")])
    names = [name for name, _ in grouped]
    assert "Unassigned" in names and "Local" in names


def test_the_region_can_come_from_the_saved_header():
    order = _order(region="")
    order["db_header"] = {"Location": "Sunshine Coast"}
    assert delivery.region_of(order) == "Sunshine Coast"


def test_region_matching_ignores_capitals():
    assert delivery.region_of(_order(region="sunshine coast")) == "Sunshine Coast"


# ── Late work ───────────────────────────────────────────────────────────────

def test_overdue_and_asap():
    assert delivery.is_overdue(_order(due=_days(-1)))
    assert not delivery.is_overdue(_order(due=_days(1)))
    assert not delivery.is_overdue(_order(due=_days(0)))
    assert delivery.is_overdue(_order(due="ASAP"))
    assert not delivery.is_overdue(_order(due=""))
    assert not delivery.is_overdue(_order(due="whenever"))


def test_run_summary_reads_sensibly():
    grouped = delivery.group_by_region(
        [_order(region="Local"), _order(region="Local"), _order(region="North")])
    assert delivery.run_summary(grouped) == "3 orders across 2 regions"
    assert delivery.run_summary([]) == "Nothing is ready to go out."


def test_item_count_survives_rubbish():
    assert delivery.item_count({"n_items": 4}) == 4
    assert delivery.item_count({"n_items": None}) == 0
    assert delivery.item_count({"n_items": "x"}) == 0


# ── The customer quote link ─────────────────────────────────────────────────

def test_a_quote_link_carries_the_token_and_the_key():
    from urllib.parse import urlparse, parse_qs
    base = "https://malakaics.github.io/TAF-App/quote/"
    token = "a" * 64
    link = base + "?" + __import__("urllib.parse", fromlist=["urlencode"]).urlencode(
        {"t": token, "k": "sb_publishable_example"})
    q = parse_qs(urlparse(link).query)
    assert q["t"] == [token]
    assert q["k"] == ["sb_publishable_example"]
    assert urlparse(link).path.endswith("/quote/")


def test_the_portal_page_exists_and_is_not_indexable():
    from pathlib import Path
    page = Path(__file__).resolve().parent.parent / "docs" / "quote" / "index.html"
    assert page.exists(), "docs/quote/index.html is what the link points at"
    html = page.read_text(encoding="utf-8")
    # A quote is private even behind an unguessable address.
    assert 'name="robots"' in html and "noindex" in html
    # It must talk to the two locked-down functions, never the table.
    assert "quote_public_view" in html and "quote_public_respond" in html
    assert "/rest/v1/quotes" not in html


# ── The customer portal ─────────────────────────────────────────────────────

def _portal_page():
    from pathlib import Path
    return (Path(__file__).resolve().parent.parent / "docs" / "portal"
            / "index.html").read_text(encoding="utf-8")


def test_the_portal_page_exists_and_is_locked_down():
    html = _portal_page()
    assert 'name="robots"' in html and "noindex" in html
    # It may only call the three functions written for it, never a table.
    for fn in ("portal_account", "portal_orders", "portal_quotes"):
        assert fn in html
    assert "/rest/v1/orders" not in html
    assert "/rest/v1/customers" not in html
    assert "/rest/v1/quotes" not in html
    # The token must not be left sitting in the address bar.
    assert "history.replaceState" in html


def test_the_portal_reads_australian_dates():
    # Orders carry dd/mm/yy, which Date() would read as American - 05/09/26 is
    # September, not May, and getting it backwards mislabels work as late.
    html = _portal_page()
    assert "function auDate" in html
    assert "auDate(o.date_due)" in html


def test_every_order_stage_the_database_can_return_has_a_colour():
    """The SQL and the page have to agree on the stage wording."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    sql = (root / "migrate_customer_portal.sql").read_text(encoding="utf-8")
    html = _portal_page()
    import re
    # Every stage the CASE can yield, whether it follows THEN or ELSE.
    stages = {s for s in re.findall(r"(?:THEN|ELSE)\s+'([^']+)'", sql)
              if s[:1].isupper()}
    assert {"Received", "Being made", "Ready for delivery",
            "Ready for pick up", "Delivered", "Collected"} <= stages, stages
    for stage in stages:
        assert '"' + stage + '"' in html, f"{stage} has no colour on the page"


def test_the_portal_sql_never_opens_a_table_to_anonymous():
    from pathlib import Path
    sql = (Path(__file__).resolve().parent.parent
           / "migrate_customer_portal.sql").read_text(encoding="utf-8")
    # Access is via functions only; no policy should hand anon a table.
    assert "CREATE POLICY" not in sql.upper()
    # The row-returning helper must not be callable by a visitor directly.
    assert "GRANT EXECUTE ON FUNCTION public.portal_customer" not in sql
    flat = " ".join(sql.split())          # the SQL pads columns to line up
    for fn in ("portal_account", "portal_orders", "portal_quotes"):
        assert f"REVOKE ALL ON FUNCTION public.{fn}(text) FROM public;" in flat
    # Definer-rights functions must pin their search_path.
    assert sql.count("SET search_path = public, pg_temp") >= 4


def test_the_staff_migration_closes_the_open_policies():
    from pathlib import Path
    sql = (Path(__file__).resolve().parent.parent
           / "migrate_staff_access.sql").read_text(encoding="utf-8")
    # Existing staff must not be locked out by running it.
    assert "UPDATE profiles SET approved = true" in sql
    # New accounts must not be staff by default.
    assert "ALTER COLUMN approved SET DEFAULT false" in sql
    assert "is_staff()" in sql and "is_manager()" in sql
    assert sql.count("SET search_path = public, pg_temp") >= 2


# ── Trust and comfort on the customer-facing pages ──────────────────────────

def _pages():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "docs"
    return {name: (root / name / "index.html").read_text(encoding="utf-8")
            for name in ("portal", "quote")}


def test_both_pages_show_who_we_are_and_how_to_reach_us():
    # A page asking someone to act on an emailed link, with no logo and no
    # phone number, is indistinguishable from a phishing message.
    for name, html in _pages().items():
        assert "company.js" in html, name
        assert "taf-shared.js" in html, name
        assert 'TAF.footer(' in html, name
        assert 'TAF.logo(' in html, name


def test_the_contact_details_are_baked_in_not_fetched():
    from pathlib import Path
    shared = (Path(__file__).resolve().parent.parent / "docs"
              / "taf-shared.js").read_text(encoding="utf-8")
    # They must show on a broken link, where there is no token to fetch with.
    assert "fetch(" not in shared
    assert "never ask for card or bank details" in shared


def test_a_blank_company_detail_is_never_printed_as_a_placeholder():
    from pathlib import Path
    shared = (Path(__file__).resolve().parent.parent / "docs"
              / "taf-shared.js").read_text(encoding="utf-8")
    # `line()` returns early on an empty value, so half-filled config still
    # renders correctly rather than showing an empty label.
    assert "if (!has(text)) { return; }" in shared


def test_the_company_file_ships_with_nothing_invented():
    from pathlib import Path
    cfg = (Path(__file__).resolve().parent.parent / "docs"
           / "company.js").read_text(encoding="utf-8")
    import re
    # Every contact field must ship empty — a wrong phone number on a
    # customer page is worse than no phone number.
    for field in ("phone", "email", "website", "abn", "address"):
        assert re.search(field + r':\s*"",', cfg), f"{field} must ship blank"


def test_an_order_can_be_opened_for_tracking_and_delays():
    html = _pages()["portal"]
    assert "portal_order" in html
    assert "function openOrder" in html
    assert "Track this consignment" in html
    assert "class='empty'" in html or 'class="empty"' in html


def test_signing_in_needs_both_an_email_and_an_order_number():
    from pathlib import Path
    sql = (Path(__file__).resolve().parent.parent
           / "migrate_portal_signin.sql").read_text(encoding="utf-8")
    flat = " ".join(sql.split())
    # Either alone would open an account to a stranger: an email address is on
    # their letterhead, an order number is short enough to count through.
    assert "IF v_email = '' OR v_order = '' THEN" in flat
    assert "portal_enabled = true" in flat
    # And the failure must not say which half was wrong.
    assert flat.count("'no_match'") >= 1
    assert "'wrong_email'" not in flat and "'wrong_order'" not in flat
    # Guessing has to be slow.
    assert "portal_signin_attempts" in flat and "interval '15 minutes'" in flat
    assert "SET search_path = public, pg_temp" in sql


def test_the_signin_page_gives_one_answer_for_any_failure():
    html = _pages()["portal"]
    assert "could not match those details" in html
    assert "function doSignIn" in html
