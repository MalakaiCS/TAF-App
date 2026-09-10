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

import functools
import http.server
import json
import socketserver
import sys
import threading
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
FILES: list = []       # photos and signatures kept against an order
UPLOADED: list = []    # what actually reached Storage

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
        # post_data itself throws on a binary body — an uploaded photo is not
        # text and asking Playwright to decode it as such raises.
        body = {}
        try:
            raw = req.post_data
        except Exception:
            raw = None
        if raw:
            try:
                body = json.loads(raw)
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
        if "/rest/v1/order_files" in url and req.method == "POST":
            row = dict(body)
            row["id"] = "f" + str(len(FILES))
            row["created_at"] = "2026-09-10T00:00:00Z"
            FILES.append(row)
            return send([row])
        if "/rest/v1/order_files" in url:
            oid = ""
            for part in url.replace("?", "&").split("&"):
                if part.startswith("order_id=eq."):
                    oid = part.split("eq.", 1)[1]
            return send([f for f in FILES if f["order_id"] == oid])
        if "/storage/v1/object/sign/" in url:
            return send({"signedURL": "/object/signed/fake.png?token=x"})
        if "/storage/v1/object/" in url:
            UPLOADED.append(url.rsplit("/object/", 1)[1])
            return send({"Key": "ok"})
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
            if name == "resolve_scan":
                code = str(body.get("p_code") or "").strip().upper()
                hits = []
                for s in STOCK:
                    if str(s.get("sku") or "").upper() == code:
                        hits.append({"kind": "stock", "ref": s["id"],
                                     "label": s["name"], "detail": "Rack A",
                                     "extra": {}})
                for o in ORDERS:
                    if str(o.get("order_number") or "").upper() == code:
                        hits.append({"kind": "order", "ref": o["id"],
                                     "label": o["customer_name"],
                                     "detail": o["header"].get("status", ""),
                                     "extra": {}})
                return send(hits)
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
        page.route("**/storage/v1/**", stub.route)

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

        print("\n── photos and proof of delivery ──")
        check("it starts with nothing kept",
              "Nothing kept against this order" in sheet.inner_text())

        # A photo, the way a phone gives one: through the file input.
        sheet.locator('input[type="file"]').set_input_files({
            "name": "plantroom.jpg", "mimeType": "image/jpeg",
            "buffer": b"\xff\xd8\xff\xe0 not really a jpeg, but a file"})
        page.wait_for_timeout(600)
        check("the photo reaches Storage", len(UPLOADED) == 1, str(UPLOADED))
        check("filed under the order it belongs to",
              UPLOADED and UPLOADED[0].startswith("order-files/o1/"),
              str(UPLOADED))
        check("and a row says what it is",
              len(FILES) == 1 and FILES[0]["kind"] == "photo")
        check("with who took it",
              FILES and FILES[0]["taken_by"] == "Kai Brown")
        check("and it appears against the order",
              sheet.locator("button.filetile").count() == 1)

        # A signature, drawn on the pad.
        sheet.locator("button", has_text="Signed for").click()
        page.wait_for_selector("#sheet-body canvas")
        sign = page.locator("#sheet-body")
        sign.locator("button", has_text="Keep it").click()
        page.wait_for_timeout(250)
        check("an unsigned pad is refused",
              "Nothing has been signed" in sign.locator(".err").inner_text())

        pad = sign.locator("canvas")
        box = pad.bounding_box()
        page.mouse.move(box["x"] + 40, box["y"] + 90)
        page.mouse.down()
        page.mouse.move(box["x"] + 150, box["y"] + 130)
        page.mouse.move(box["x"] + 240, box["y"] + 70)
        page.mouse.up()
        sign.locator("button", has_text="Keep it").click()
        page.wait_for_timeout(250)
        check("a signature with no name is refused",
              "Whose signature" in sign.locator(".err").inner_text())
        check("and nothing was uploaded on a refusal", len(UPLOADED) == 1)

        sign.locator('input[type="text"]').first.fill("D. Nguyen")
        sign.locator("button", has_text="Keep it").click()
        page.wait_for_timeout(800)
        check("the signature is kept", len(FILES) == 2)
        if len(FILES) == 2:
            check("as a signature, with the name",
                  FILES[1]["kind"] == "signature"
                  and FILES[1]["signed_by"] == "D. Nguyen")
        # Closing the pad has to go back to the order, not shut everything.
        check("it steps back to the order underneath",
              "Bells Creek" in page.locator("#sheet-body").inner_text(),
              page.locator("#sheet-body").inner_text()[:120])
        check("and the order shows both",
              page.locator("#sheet-body button.filetile").count() == 2)

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

        print("\n── scanning a code ──")

        def newest():
            """The card for the code most recently scanned."""
            return page.locator("#scans .card").first

        page.click('#tabs button[data-tab="scan"]')
        page.wait_for_selector("#screen .code")
        page.fill("#screen input.code", "PO-8842")
        page.press("#screen input.code", "Enter")
        page.wait_for_selector("#screen button.hit")
        check("a scanned order number finds the order",
              "Bells Creek" in newest().inner_text())
        page.click("#screen button.hit")
        page.wait_for_selector("#sheet:not(.hidden)")
        check("and opens it, ready to tick off",
              "Bells Creek" in page.locator("#sheet-body h2").first.inner_text())
        page.locator("#sheet-body button", has_text="Close").first.click()
        page.wait_for_selector("#sheet.hidden", state="attached")

        page.fill("#screen input.code", "MED-G4-1M")
        page.press("#screen input.code", "Enter")
        page.wait_for_timeout(300)
        check("a scanned rack label finds the stock item",
              "G4 media roll" in newest().inner_text())

        page.fill("#screen input.code", "NOT-A-CODE")
        page.press("#screen input.code", "Enter")
        page.wait_for_timeout(300)
        check("a code that means nothing says so, rather than nothing at all",
              "Nothing here answers to that code" in newest().inner_text())

        # Every iPhone today, and Firefox. The camera button must not sit
        # there doing nothing with no explanation.
        page.evaluate("window.__BD = window.BarcodeDetector;"
                      "delete window.BarcodeDetector;")
        page.click('#tabs button[data-tab="orders"]')
        page.click('#tabs button[data-tab="scan"]')
        page.wait_for_selector("#screen .code")
        check("a browser that cannot read barcodes says what to do instead",
              "cannot read a barcode" in page.locator("#screen").inner_text())
        check("and does not offer a camera button that would do nothing",
              page.locator('#screen button:has-text("Use the camera")')
              .is_disabled())

        print("\n── the camera ──")
        # A stubbed detector and a canvas for a camera: the point being
        # tested is the loop around them, not Chromium's barcode support.
        page.evaluate("""() => {
          window.BarcodeDetector = function () {
            this.detect = function () {
              return Promise.resolve([{ rawValue: "TAF-ON-0002" }]);
            };
          };
          window.BarcodeDetector.getSupportedFormats =
            () => Promise.resolve(["code_128"]);
          // A fresh stream each time it is asked for, all of them kept, so
          // a camera left running on the second go cannot hide behind the
          // first one having been stopped.
          window.__streams = [];
          navigator.mediaDevices.getUserMedia = function () {
            const c = document.createElement("canvas");
            c.width = 320; c.height = 240;
            const s = c.captureStream(5);
            window.__streams.push(s);
            return Promise.resolve(s);
          };
        }""")
        ended = ("window.__streams.length === %d && window.__streams.every("
                 "s => s.getTracks().every(t => t.readyState === 'ended'))")
        page.click('#tabs button[data-tab="orders"]')
        page.click('#tabs button[data-tab="scan"]')
        page.wait_for_selector('#screen button:not([disabled]):has-text("Use the camera")')
        scans_before = len([1 for u, _b in stub.calls if "resolve_scan" in u])
        page.click('#screen button:has-text("Use the camera")')
        page.wait_for_selector('#scans .card:has-text("TAF-ON-0002")',
                               timeout=6000)
        check("the camera reads a code and looks it up",
              "CAS - Tweed" in newest().inner_text())
        # It sees the same label thirty times a second. Every frame must not
        # become a request.
        page.wait_for_timeout(1500)
        scans = len([1 for u, _b in stub.calls if "resolve_scan" in u]) - scans_before
        check("one label held in front of it is one lookup, not thirty",
              scans <= 2, f"{scans} lookups in 1.8 seconds")
        page.click('#screen button:has-text("Stop the camera")')
        page.wait_for_timeout(200)
        check("stopping it puts the camera down", page.evaluate(ended % 1))
        # Leaving the tab must do the same, or the light on the back of the
        # phone stays on for the rest of the day.
        page.click('#screen button:has-text("Use the camera")')
        page.wait_for_timeout(500)
        page.click('#tabs button[data-tab="orders"]')
        page.wait_for_timeout(300)
        check("and so does walking away from the tab",
              page.evaluate(ended % 2),
              page.evaluate("window.__streams.map(s =>"
                            " s.getTracks().map(t => t.readyState).join())"
                            ".join(' | ')"))

        print("\n── no signal ──")
        page.wait_for_selector("#screen table")
        page.locator("#screen tbody tr", has_text="Bells Creek").first.click()
        page.wait_for_selector("#sheet-body button.tick")
        ticks = page.locator("#sheet-body button.tick")
        was = ITEMS["o1"][1].get("made")

        # The wifi at the back of the factory, as the browser sees it: the
        # request never arrives anywhere.
        page.route("**/rest/v1/rpc/set_order_line_made*",
                   lambda r: r.abort("internetdisconnected"))
        ticks.nth(1).click()
        page.wait_for_timeout(400)
        check("a tick out of signal says it is kept, not that it failed",
              "Kept on this phone" in page.locator("#sheet-body").inner_text())
        check("the line shows as ticked all the same",
              ticks.nth(1).get_attribute("aria-pressed") == "true")
        check("and marked as not gone yet",
              "waiting" in (ticks.nth(1).get_attribute("class") or ""))
        check("nothing reached the database",
              ITEMS["o1"][1].get("made") == was)
        check("the bar under the tabs says one change is waiting",
              "1 change waiting" in page.locator("#state").inner_text())

        page.locator("#sheet-body button", has_text="Close").first.click()
        page.wait_for_selector("#sheet.hidden", state="attached")

        # The signal comes back, but nothing has been flushed yet. A change
        # made now must go behind what is already waiting, not overtake it —
        # a tick and the untick that followed it arriving the wrong way round
        # would leave the order saying the opposite of what happened.
        page.unroute("**/rest/v1/rpc/set_order_line_made*")
        page.locator("#screen tbody tr", has_text="Bells Creek").first.click()
        page.wait_for_selector("#sheet-body button.tick")
        page.locator("#sheet-body button.tick").nth(2).click()
        page.wait_for_timeout(400)
        check("with signal back, a new change still goes behind the queue",
              "2 changes waiting" in page.locator("#state").inner_text(),
              page.locator("#state").inner_text())
        check("and does not reach the database ahead of it",
              ITEMS["o1"][2].get("made") is not True)
        page.locator("#sheet-body button", has_text="Close").first.click()
        page.wait_for_selector("#sheet.hidden", state="attached")

        page.locator('#state button:has-text("Send now")').click()
        page.wait_for_timeout(600)
        check("back in signal, what was waiting goes through",
              ITEMS["o1"][1].get("made") is True
              and ITEMS["o1"][2].get("made") is True)
        check("and the bar goes away", page.locator("#state").is_hidden())

        print("\n── what the phone remembers ──")
        page.route("**/rest/v1/orders_list*",
                   lambda r: r.abort("internetdisconnected"))
        page.evaluate("TAFAPP._stale()")
        page.click('#tabs button[data-tab="dashboard"]')
        page.click('#tabs button[data-tab="orders"]')
        page.wait_for_selector("#screen table")
        check("with no signal the last list it saw is still there",
              page.locator("#screen tbody tr").count() >= 3)
        check("and it says so, rather than passing it off as today's",
              "what the phone last saw" in page.locator("#screen").inner_text())
        page.unroute("**/rest/v1/orders_list*")

        page.route("**/rest/v1/rpc/resolve_scan*",
                   lambda r: r.abort("internetdisconnected"))
        page.click('#tabs button[data-tab="scan"]')
        page.wait_for_selector("#screen .code")
        page.fill("#screen input.code", "MED-G4-1M")
        page.press("#screen input.code", "Enter")
        page.wait_for_timeout(300)
        check("a rack label still resolves with no signal at all",
              "G4 media roll" in page.locator("#scans .card").first.inner_text())
        page.unroute("**/rest/v1/rpc/resolve_scan*")

        print("\n── signing out ──")
        check("nothing is left covering the app",
              page.locator("#sheet").is_hidden())
        page.click("#signout")
        page.wait_for_selector("#signin-form", timeout=8000)
        check("signing out returns to the login page",
              page.locator("#app").is_hidden())
        check("and the session is forgotten",
              page.evaluate("localStorage.getItem('taf_staff_session')") is None)

        print("\n── kept on the phone ──")
        # A service worker needs a real origin, and file:// has none — so
        # this last part is served over http out of the same folder GitHub
        # Pages serves, which is the only way to prove the thing the whole
        # feature rests on: that the app opens with the network off.
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):    # noqa: D102 - a silent test server
                pass

        handler = functools.partial(Quiet, directory=str(ROOT / "docs"))
        httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        crashes: list = []
        try:
            ctx = browser.new_context()
            p2 = ctx.new_page()
            p2.on("pageerror", lambda e: crashes.append(str(e)))
            p2.route("**/rest/v1/**", stub.route)
            p2.route("**/auth/v1/**", stub.route)
            p2.goto(f"http://127.0.0.1:{port}/app/index.html?k=test-anon-key")
            p2.wait_for_function(
                "navigator.serviceWorker && navigator.serviceWorker.controller",
                timeout=20000)
            check("the app puts itself on the phone", True)

            paths = p2.evaluate("""async () => {
              const names = await caches.keys();
              const c = await caches.open(names[0]);
              return (await c.keys()).map(r => new URL(r.url).pathname);
            }""")
            need = ["/app/index.html", "/app/screens.js", "/app/offline.js",
                    "/app/data.js", "/app/ui.js", "/company.js",
                    "/taf-shared.js", "/app/manifest.webmanifest",
                    "/app/icon-192.png"]
            check("everything it is made of is kept there",
                  all(f in paths for f in need),
                  "missing " + str([f for f in need if f not in paths]))
            # The one thing that must never be cached. A stock figure served
            # from yesterday looks exactly like today's and is not.
            check("and nothing from the database is",
                  not any("/rest/" in p or "/auth/" in p or "/storage/" in p
                          for p in paths), str(paths))

            ctx.set_offline(True)
            # A plain reload proves nothing: Chromium would serve that out of
            # its own HTTP cache whether or not any of this works. An address
            # it has never fetched cannot come from there, so if this opens,
            # the worker is what opened it.
            opened, why = True, ""
            try:
                p2.goto(f"http://127.0.0.1:{port}/app/index.html?fresh=1")
                p2.wait_for_selector("#signin-form", timeout=20000)
            except Exception as exc:
                opened, why = False, str(exc).splitlines()[0]
            check("with the network off it still opens", opened, why)
            if opened:
                check("styled and working, not a page of raw text",
                      p2.evaluate("typeof TAFSYNC") == "object"
                      and p2.evaluate("typeof TAFAPP") == "object")
                check("and its scripts come from the phone, not the cupboard",
                      p2.evaluate("() => fetch('screens.js',"
                                  " {cache: 'no-store'}).then(r => r.ok)"
                                  ".catch(() => false)"))
            check("and the worker did not throw on the way", not crashes,
                  "; ".join(crashes[:3]))
            ctx.set_offline(False)
            ctx.close()
        finally:
            httpd.shutdown()
            httpd.server_close()

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
