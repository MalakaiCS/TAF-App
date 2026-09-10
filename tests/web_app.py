"""The staff web app, driven in a real browser.

Everything this page does, it does by talking to Supabase over HTTP — so the
way to test it is to answer those requests with known data and then use the
page the way a person would: sign in, find an order, tick a line off, change a
status.

Nothing here reaches the real database. Every request is served by the stub
below, which also lets a test say "now refuse that one" and check the page
says so instead of quietly carrying on.

Run:  python tests/web_app.py
Needs Playwright and Chromium, which the build machine has. Skips cleanly
where they are missing, the way the GUI smoke test does.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "docs" / "app" / "index.html").as_uri() + "?k=test-anon-key"

FAILURES: list = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}" + (f"\n        {detail}" if detail else ""))
        FAILURES.append(label)


# ── What the stubbed database holds ─────────────────────────────────────────

PROFILE = {"id": "u1", "full_name": "Kai Brown", "username": "kai",
           "role": "Manager", "approved": True}

ORDERS = [
    {"id": "o1", "customer_name": "Bells Creek", "order_number": "PO-8842",
     "date_ordered": "01/09/2026", "date_due": "01/08/2026",
     "archived": False, "created_at": "2026-09-01T00:00:00Z",
     "n_items": 3, "n_made": 1, "full_name": "Kai Brown",
     "header": {"status": "In Production", "priority": True,
                "Job": "AHU 3",
                "order_notes": [{"ts": "01/09/2026 09:00", "author": "Kai",
                                 "text": "Ring the site before delivery"}]}},
    {"id": "o2", "customer_name": "CAS - Tweed", "order_number": "TAF-ON-0002",
     "date_ordered": "02/09/2026", "date_due": "ASAP",
     "archived": False, "created_at": "2026-09-02T00:00:00Z",
     "n_items": 2, "n_made": 2, "full_name": "Kai Brown",
     "header": {"status": "Complete"}},
    # Still being made. It must never appear on a delivery run, which is the
    # only thing keeping a driver from being sent out with an empty box.
    {"id": "o3", "customer_name": "Pelican Waters", "order_number": "PO-9100",
     "date_ordered": "03/09/2026", "date_due": "31/12/2026",
     "archived": False, "created_at": "2026-09-03T00:00:00Z",
     "n_items": 5, "n_made": 0, "full_name": "Kai Brown",
     "header": {"status": "Pending"}},
]

ITEMS = {
    "o1": [
        {"line_id": "L1", "Quantity": 2, "Filter Type": "V-form",
         "Short": 500, "Long": 600, "Channel": 45, "Media Type": "G4",
         "made": True},
        {"line_id": "L2", "Quantity": 1, "Filter Type": "Flat Panel",
         "Short": 300, "Long": 400, "Channel": 50, "Media Type": "F5"},
        {"line_id": "L3", "Quantity": 4, "Filter Type": "Flyscreen",
         "Short": 200, "Long": 200, "Channel": 25, "Media Type": "WASH"},
    ],
    "o2": [],
}


CUSTOMERS = [
    {"id": "c1", "name": "Bells Creek Pty Ltd", "short_name": "Bells Creek",
     "phone": "07 5555 1234", "email": "jobs@bellscreek.com.au",
     "address": "12 Industrial Ave", "suburb": "Caloundra",
     "region": "Sunshine Coast", "payment_terms": "Net 30"},
    {"id": "c2", "name": "CAS - Tweed", "short_name": "CAS - Tweed",
     "phone": "", "email": "", "region": "Northern NSW"},
]

STOCK = [
    {"id": "s1", "name": "G4 media roll 1m", "sku": "MED-G4-1M",
     "media_type": "G4", "unit": "m", "stock_on_hand": 42,
     "minimum_level": 20},
    {"id": "s2", "name": "F5 media roll 1m", "sku": "MED-F5-1M",
     "media_type": "F5", "unit": "m", "stock_on_hand": 6,
     "minimum_level": 25},          # low
]

RAISED: list = []      # orders the web app raised

QUOTES = [
    {"id": "q1", "quote_number": "Q-1041", "customer_name": "Bells Creek",
     "reference": "PO-9001", "status": "sent", "total": 1287.5,
     "unpriced_count": 1, "valid_until": "2026-10-31",
     "created_at": "2026-09-01T00:00:00Z", "notes": "Site access via gate 3",
     "items": [
         {"quantity": 4, "description": "V-form G4 500 x 600 x 45",
          "unit_price": 88.5, "line_total": 354.0},
         {"quantity": 2, "description": "Stepped Filter WASH",
          "unit_price": 0, "line_total": 0},
     ]},
    {"id": "q2", "quote_number": "Q-1042", "customer_name": "CAS - Tweed",
     "reference": "", "status": "draft", "total": 210.0, "unpriced_count": 0,
     "created_at": "2026-09-02T00:00:00Z", "items": []},
]


class Stub:
    """Answers what the page asks for, and remembers what it was asked."""

    def __init__(self):
        self.calls: list = []
        self.refuse: dict = {}      # rpc name -> message

    def route(self, route):
        req = route.request
        url = req.url
        body = {}
        if req.post_data:
            try:
                body = json.loads(req.post_data)
            except Exception:
                body = {}
        self.calls.append((url, body))

        def send(payload, status=200):
            route.fulfill(status=status, content_type="application/json",
                          headers={"Access-Control-Allow-Origin": "*"},
                          body=json.dumps(payload))

        if "/auth/v1/token" in url:
            if body.get("password") != "correct-horse":
                return send({"msg": "Invalid login credentials"}, 400)
            return send({"access_token": "tok", "refresh_token": "ref",
                         "user": {"id": "u1", "email": "kai@taf.local"}})
        if "/auth/v1/logout" in url:
            return send({})
        if "/rest/v1/profiles" in url:
            return send([PROFILE])
        if "/rest/v1/orders_list" in url:
            return send(ORDERS)
        if "/rest/v1/customers" in url:
            return send(CUSTOMERS)
        if "/rest/v1/stock_items" in url:
            return send(STOCK)
        if "/rest/v1/quotes" in url:
            return send(QUOTES)
        if "/rest/v1/orders" in url and req.method == "POST":
            row = dict(body)
            row["id"] = "new-" + str(len(ORDERS))
            row["order_number"] = row.get("order_number") or "TAF-ON-0009"
            RAISED.append(row)
            return send([row])
        if "/rest/v1/orders" in url:
            oid = ""
            for part in url.split("&"):
                if "id=eq." in part:
                    oid = part.split("id=eq.")[1].split("&")[0]
            row = next((o for o in ORDERS if o["id"] == oid), None)
            if row is None:
                return send([])
            return send([{"items": ITEMS.get(oid, []),
                          "header": row.get("header", {})}])
        if "/rest/v1/rpc/" in url:
            name = url.rsplit("/rpc/", 1)[1].split("?")[0]
            if name in self.refuse:
                return send({"message": self.refuse[name]}, 400)
            if name == "set_order_line_made":
                for it in ITEMS.get(body.get("p_order_id"), []):
                    if it.get("line_id") == body.get("p_line_id"):
                        it["made"] = bool(body.get("p_made"))
                        return send("o1")
                return send(None)
            if name == "adjust_stock_atomic":
                item = next((s for s in STOCK
                             if s["id"] == body.get("p_item_id")), None)
                if item is None:
                    return send(None)
                qty = float(body.get("p_quantity") or 0)
                kind = body.get("p_type")
                if kind == "count":
                    item["stock_on_hand"] = qty
                elif kind in ("use", "writeoff"):
                    item["stock_on_hand"] -= abs(qty)
                else:
                    item["stock_on_hand"] += abs(qty)
                return send([{"quantity_after": item["stock_on_hand"]}])
            if name == "merge_order_header":
                row = next((o for o in ORDERS
                            if o["id"] == body.get("p_order_id")), None)
                if row:
                    row.setdefault("header", {}).update(body.get("p_patch") or {})
                    return send(row["id"])
                return send(None)
            return send(None)
        return send([])


def run() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print(f"SKIP: Playwright is not available ({exc})")
        return 0

    with sync_playwright() as pw:
        # The build machine pins a Chromium that may not be the revision this
        # Playwright would download. Use the one that is actually installed
        # rather than fetching another copy on every run.
        installed = Path("/opt/pw-browsers/chromium")
        launch = {"executable_path": str(installed)} if installed.exists() else {}
        try:
            browser = pw.chromium.launch(**launch)
        except Exception as exc:
            print(f"SKIP: no browser to drive ({exc})")
            return 0
        page = browser.new_page(viewport={"width": 900, "height": 900})
        stub = Stub()
        page.route("**/rest/v1/**", stub.route)
        page.route("**/auth/v1/**", stub.route)

        # A thrown exception is a bug. A 400 in the console is not — two of
        # them are this test's own doing, refusing a password and refusing an
        # RPC on purpose, and the page is judged on how it handles those
        # rather than on whether they happened.
        errors: list = []
        page.on("pageerror", lambda e: errors.append("uncaught: " + str(e)))
        page.on("console", lambda m: errors.append("console: " + m.text)
                if (m.type == "error"
                    and "Failed to load resource" not in m.text) else None)

        print("\n── opening it on a phone, with no PC ──")
        # config.js is written by the "Publish the web app key" workflow, so
        # a bare bookmark works on any phone. It is not in the repo, so this
        # writes and removes one to test both states.
        bare = (ROOT / "docs" / "app" / "index.html").as_uri()
        cfg = ROOT / "docs" / "app" / "config.js"
        had_cfg = cfg.exists()
        if had_cfg:
            keep = cfg.read_text(encoding="utf-8")
        try:
            if had_cfg:
                cfg.unlink()
            page.goto(bare)
            page.wait_for_selector("#signin .err")
            check("with no key it names who can fix it",
                  "Publish the web app key"
                  in page.locator("#signin .err").inner_text())
            check("and does not offer a form that cannot work",
                  page.locator("#signin-form").is_hidden())

            cfg.write_text('window.TAF_KEY = "test-anon-key";\n', encoding="utf-8")
            page.goto(bare)
            page.wait_for_selector("#signin-form:not(.hidden)")
            check("once published, a bare bookmark is enough",
                  page.locator("#signin-form").is_visible())
            check("and nothing warns about set-up",
                  page.locator("#signin .err").count() == 0)

            page.evaluate("localStorage.clear()")
            page.goto(bare + "?k=from-the-link")
            page.wait_for_selector("#signin-form:not(.hidden)")
            check("a key on the link still wins",
                  page.evaluate("localStorage.getItem('taf_staff_key')")
                  == "from-the-link")
        finally:
            if had_cfg:
                cfg.write_text(keep, encoding="utf-8")
            elif cfg.exists():
                cfg.unlink()

        print("\n── the contact footer ──")
        # It used to depend on the page defining .taf-contact as a flex row.
        # The page that forgot ran the phone number, the email and the website
        # together into one unreadable line — on a phone, which is where these
        # are read, and next to a sentence telling people to ring us.
        page.goto(PAGE)
        page.wait_for_selector(".taf-footer")
        shape = page.evaluate("""() => {
          const c = document.querySelector('.taf-contact');
          const kids = [...c.children].map(k => k.getBoundingClientRect());
          return {
            display: getComputedStyle(c).display,
            touching: kids.some((k, i) => i && Math.abs(k.left - kids[i-1].right) < 2)
          };
        }""")
        check("the contact details are laid out, not run together",
              shape["display"] == "flex" and not shape["touching"], str(shape))
        check("the phone number is there to ring",
              "3800 3448" in page.locator(".taf-footer").inner_text())

        print("\n── signing in ──")
        page.wait_for_selector("#signin-form")
        check("the app does not show before signing in",
              page.locator("#app").is_hidden())

        # A wrong password must say so, and must not let anyone in.
        page.fill("#email", "kai@taf.local")
        page.fill("#password", "wrong")
        page.click("#signin-go")
        page.wait_for_selector("#signin .err")
        check("a wrong password is refused",
              "did not match" in page.locator("#signin .err").inner_text())
        check("and the app is still hidden", page.locator("#app").is_hidden())

        page.fill("#password", "correct-horse")
        page.click("#signin-go")
        page.wait_for_selector("#app:not(.hidden)", timeout=8000)
        check("the right password gets in", page.locator("#app").is_visible())
        check("it says who is signed in",
              page.locator("#who-name").inner_text() == "Kai Brown")
        check("the password is not left in the box",
              page.input_value("#password") == "")
        check("the key is taken out of the address bar",
              "k=" not in page.url, page.url)

        print("\n── today ──")
        page.wait_for_selector("#screen .card")
        text = page.locator("#screen").inner_text()
        check("an overdue order is counted", "Overdue" in text)
        check("the late one is named", "Bells Creek" in text)

        print("\n── raising an order ──")
        page.click('#tabs button[data-tab="new"]')
        page.wait_for_selector("#screen .card")

        # It must not save an order with no customer, and must not save one
        # with no lines — both are orders nobody can make.
        page.locator("#screen button", has_text="Save the order").click()
        page.wait_for_timeout(200)
        check("it refuses an order with no customer",
              "Which customer" in page.locator("#screen .err").inner_text())
        check("and saved nothing", len(RAISED) == 0)

        page.locator('#screen input').first.fill("Pelican Waters")
        page.locator("#screen button", has_text="Save the order").click()
        page.wait_for_timeout(200)
        check("it refuses an order with no lines",
              "no lines" in page.locator("#screen .err").inner_text())
        check("and still saved nothing", len(RAISED) == 0)

        page.locator("#screen button", has_text="Add a line").click()
        page.wait_for_selector("#sheet:not(.hidden)")
        lsheet = page.locator("#sheet-body")
        # A line with no measurements has nothing to derive a part number
        # from, so it must not be accepted.
        lsheet.locator('input[inputmode="numeric"]').first.fill("4")
        lsheet.locator("button", has_text="Add it").click()
        page.wait_for_timeout(200)
        check("a line with no measurements is refused",
              "measurements are needed" in lsheet.locator(".err").inner_text())

        nums = lsheet.locator('input[inputmode="numeric"]')
        nums.nth(1).fill("500")
        nums.nth(2).fill("600")
        nums.nth(3).fill("45")
        lsheet.locator("select").first.select_option("V-form")
        lsheet.locator("button", has_text="Add it").click()
        page.wait_for_selector("#sheet.hidden", state="attached")
        check("the line is added", "500 × 600 × 45"
              in page.locator("#screen").inner_text(),
              page.locator("#screen").inner_text()[:250])

        page.locator("#screen button", has_text="Save the order").click()
        page.wait_for_timeout(400)
        check("the order reaches the database", len(RAISED) == 1)
        if RAISED:
            saved = RAISED[0]
            check("with the customer on it",
                  saved.get("customer_name") == "Pelican Waters")
            check("and the line's real measurements",
                  saved["items"][0]["Short"] == 500
                  and saved["items"][0]["Long"] == 600
                  and saved["items"][0]["Channel"] == 45)
            # The whole point of the split: the web does not invent these.
            check("and no part number invented in the browser",
                  not saved["items"][0].get("Part Number"))
            check("it starts as Pending, not made",
                  saved["header"]["status"] == "Pending")
            check("and it says where to finish it",
                  "desktop" in page.locator("#screen .ok").inner_text(),
                  page.locator("#screen .ok").inner_text())
            check("the form is cleared for the next one",
                  page.locator('#screen input').first.input_value() == "")

        print("\n── the order list ──")
        page.click('#tabs button[data-tab="orders"]')
        page.wait_for_selector("#screen table")
        rows = page.locator("#screen tbody tr")
        check("every order is listed", rows.count() == 3, str(rows.count()))
        check("progress shows as a fraction",
              "1/3" in page.locator("#screen").inner_text())
        check("a finished order shows a tick",
              "✓ 2" in page.locator("#screen").inner_text())
        check("the overdue row is flagged",
              page.locator("#screen tbody tr.late").count() == 1)

        page.fill('#screen input[type="search"]', "tweed")
        page.wait_for_timeout(150)
        check("search narrows the list",
              page.locator("#screen tbody tr").count() == 1)
        page.fill('#screen input[type="search"]', "")
        page.wait_for_timeout(150)

        print("\n── one order ──")
        page.locator("#screen tbody tr", has_text="Bells Creek").first.click()
        page.wait_for_selector("#sheet:not(.hidden)")
        # The sheet opens straight away and fills in when the lines arrive.
        # Counting rows before then is a race, and it loses about half the
        # time on a fast machine.
        page.wait_for_selector("#sheet-body button.tick")
        sheet = page.locator("#sheet-body")
        check("the lines are shown", sheet.locator("tbody tr").count() == 3)
        check("it says how many are made",
              "1 of 3 lines made" in sheet.inner_text(), sheet.inner_text()[:200])
        check("the note is there",
              "Ring the site before delivery" in sheet.inner_text())

        # Tick the second line off.
        ticks = sheet.locator("button.tick")
        check("a made line is already ticked",
              ticks.nth(0).get_attribute("aria-pressed") == "true")
        ticks.nth(1).click()
        page.wait_for_timeout(300)
        check("ticking a line writes it to the database",
              ITEMS["o1"][1]["made"] is True)
        check("the box fills",
              ticks.nth(1).get_attribute("aria-pressed") == "true")
        check("the count follows",
              "2 of 3 lines made" in sheet.inner_text())
        check("it recorded who made it",
              any(b.get("p_by") == "Kai Brown" for _u, b in stub.calls
                  if b.get("p_line_id") == "L2"))

        # Untick it again.
        ticks.nth(1).click()
        page.wait_for_timeout(300)
        check("unticking works too", ITEMS["o1"][1]["made"] is False)

        print("\n── when the database says no ──")
        stub.refuse["set_order_line_made"] = (
            "new row violates row-level security policy for table \"orders\"")
        ticks.nth(2).click()
        page.wait_for_timeout(400)
        check("a refused tick is reported",
              sheet.locator(".err").count() == 1,
              sheet.inner_text()[:200])
        check("and says it was not allowed",
              "not allowed" in sheet.locator(".err").inner_text(),
              sheet.locator(".err").inner_text())
        check("the box does not fill on a refusal",
              ticks.nth(2).get_attribute("aria-pressed") == "false")
        check("and nothing was written",
              ITEMS["o1"][2].get("made") is not True)
        stub.refuse.clear()

        print("\n── changing status ──")
        page.locator("#sheet-body button", has_text="Complete").first.click()
        page.wait_for_timeout(300)
        check("the status is written",
              ORDERS[0]["header"]["status"] == "Complete")
        check("and confirmed on screen",
              sheet.locator(".ok").count() == 1)
        check("the heading shows the new status, not the old one",
              sheet.locator(".pill").first.inner_text() == "Complete",
              sheet.locator(".pill").first.inner_text())
        check("and Complete is no longer on offer",
              sheet.locator("button", has_text="Complete").count() == 0)
        page.locator("#sheet-body button", has_text="Close").first.click()
        page.wait_for_selector("#sheet.hidden", state="attached")

        print("\n── delivery ──")
        page.click('#tabs button[data-tab="delivery"]')
        page.wait_for_selector("#screen .card")
        text = page.locator("#screen").inner_text()
        # Only Complete work is ready to go — the same rule the run sheet is
        # built on, so the driver's sheet and this screen cannot disagree.
        check("completed work is on the run", "CAS - Tweed" in text)
        check("work still being made is not",
              "Pelican Waters" not in text, text[:250])

        print("\n── quotes ──")
        page.click('#tabs button[data-tab="quotes"]')
        page.wait_for_selector("#screen table")
        check("quotes are listed",
              page.locator("#screen tbody tr").count() == 2)
        page.locator("#screen tbody tr", has_text="Q-1041").first.click()
        page.wait_for_selector("#sheet:not(.hidden)")
        qsheet = page.locator("#sheet-body")
        check("its lines are shown", qsheet.locator("tbody tr").count() == 2)
        check("an unpriced line says so, rather than showing nothing",
              "to be confirmed" in qsheet.inner_text())
        check("and the quote warns how many were left out",
              "1 line has no price" in qsheet.inner_text(),
              qsheet.inner_text()[:300])
        page.locator("#sheet-body button", has_text="Close").first.click()
        page.wait_for_selector("#sheet.hidden", state="attached")

        print("\n── customers ──")
        page.click('#tabs button[data-tab="customers"]')
        page.wait_for_selector("#screen table")
        check("customers are listed",
              page.locator("#screen tbody tr").count() == 2)
        page.fill('#screen input[type="search"]', "caloundra")
        page.wait_for_timeout(150)
        check("search reaches the suburb, not just the name",
              page.locator("#screen tbody tr").count() == 1)
        page.locator("#screen tbody tr").first.click()
        page.wait_for_selector("#sheet:not(.hidden)")
        csheet = page.locator("#sheet-body")
        check("their details are shown",
              "jobs@bellscreek.com.au" in csheet.inner_text())
        check("and their orders", "PO-8842" in csheet.inner_text())
        page.locator("#sheet-body button", has_text="Close").first.click()
        page.wait_for_selector("#sheet.hidden", state="attached")

        print("\n── stock ──")
        page.click('#tabs button[data-tab="stock"]')
        page.wait_for_selector("#screen table")
        check("stock is listed", page.locator("#screen tbody tr").count() == 2)
        check("what is low is flagged",
              page.locator("#screen tbody tr.late").count() == 1)
        page.check('#screen input[type="checkbox"]')
        page.wait_for_timeout(150)
        check("and can be shown on its own",
              page.locator("#screen tbody tr").count() == 1)

        page.locator("#screen tbody tr").first.click()
        page.wait_for_selector("#sheet:not(.hidden)")
        ssheet = page.locator("#sheet-body")
        before = STOCK[1]["stock_on_hand"]
        page.select_option("#sheet-body select", "receive")
        page.fill('#sheet-body input[inputmode="decimal"]', "30")
        page.locator("#sheet-body button", has_text="Save the adjustment").click()
        page.wait_for_timeout(400)
        check("an adjustment reaches the database",
              STOCK[1]["stock_on_hand"] == before + 30,
              str(STOCK[1]["stock_on_hand"]))
        check("and the new figure is shown back",
              str(before + 30) in ssheet.inner_text())
        check("every adjustment carries a reference, so a double tap "
              "cannot double-count",
              all(b.get("p_client_ref") for _u, b in stub.calls
                  if "p_item_id" in b))
        page.locator("#sheet-body button", has_text="Close").first.click()
        page.wait_for_selector("#sheet.hidden", state="attached")

        print("\n── signing out ──")
        check("nothing is left covering the app",
              page.locator("#sheet").is_hidden())
        page.click("#signout")
        page.wait_for_selector("#signin-form", timeout=8000)
        check("signing out returns to the login page",
              page.locator("#app").is_hidden())
        check("and the session is forgotten",
              page.evaluate("localStorage.getItem('taf_staff_session')") is None)

        real_errors = [e for e in errors if "favicon" not in e.lower()]
        check("no script errors anywhere", not real_errors,
              "\n        ".join(real_errors[:4]))
        browser.close()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: " + ", ".join(FAILURES))
        return 1
    print("Web app passed — signed in, listed, ticked and refused.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
