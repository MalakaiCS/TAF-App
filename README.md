# TAF Order Entry

Desktop order-entry and worksheet/PDF generator for **Total Air Filtration** —
a Windows Tkinter app backed by Supabase (auth + shared database).

Staff create filter / bag orders, the app generates printable worksheets and
order PDFs, and everything is stored centrally with per-user roles, an audit
log, stock management and a customer database.

> **Version 2.0.0** — TAF-brand UI (Public Sans, rounded navy-header cards,
> pill buttons, Filter/Bags/Mixed type badges, split-panel login).

---

## Features

- **New Order** — filter & bag/roll line items, dedicated compressor-filter
  presets (add / edit / remove your own), duplicate-order warning, live
  worksheet + order-PDF generation.
- **Our own order numbers** — a customer with no purchase order number gets
  one of ours: `TAF-ON-0001` and up, from a shared counter, with nothing to do
  with invoice numbering. The **TAF #** button is next to Order Number on New
  Order and in the purchase-order review screen.
- **Import Purchase Order** — upload a PDF, photo, scan or emailed order and
  the app reads it, shows what it found for checking, then generates and
  prints the worksheets. Handles several purchase orders in one file.
- **Send from your phone** — scan a QR code to link a phone, photograph a
  purchase order, and it arrives in the office app ready to review — from
  anywhere.
- **Previous Orders** — search / filter, view items, reload, duplicate,
  regenerate, status tracking, priority flags, notes, per-order history.
- **What's due** — filter the order list by overdue / due today / due this
  week, with late work coloured and flagged in the list, and a Due panel on
  the Dashboard that opens straight into it.
- **Quotes** — its own tab. Pick the customer, add the lines (or pull them
  from a saved order), and each one is priced as it goes in. Save it, follow
  it up, and turn an accepted one into an order with the lines already there.
  Print a quote PDF and export a Xero sales-invoice CSV. A line nothing can
  price is shown as "to be confirmed", with the reason, rather than guessed at.
  **Delivery** is part of the quote, charged on top and taxed with the goods,
  so the number at the counter is the number on the invoice.
- **The customer can answer online** — send a link and they read the quote in
  a browser and press Accept or Decline, giving their name and their own order
  number. You see who answered and when, and Follow Up lists everything sent
  that nobody has replied to (and whether they've opened it).
- **Delivery** — what's finished and where it goes, grouped by region in run
  order. Print a run sheet for the driver (tick box, due date, signature
  column) and mark a whole run dispatched in one go.
- **Products** — the priced catalogue: search it, correct a price, add a
  product, import price spreadsheets. The part numbers here are the item codes
  in Xero.
- **Margin** — what a job costs next to what it sells for. A cost against a
  part number and a cost per square metre for the media, shown per product and
  totalled on a quote before it goes out. A line nobody has costed is reported
  as unknown, never as pure profit — and importing a price spreadsheet can't
  wipe costs already entered. Managers only: it's the one figure on that
  screen that must never reach a customer.
- **Customer portal** — send a customer a link and they see their own orders
  and what stage each is at (received / being made / ready for delivery /
  ready for pick up / delivered), their quotes, and their account details.
  Opening an order shows what's on it, the consignment number with a tracking
  link when it's gone out on freight, and anything holding it up. Customers
  who've lost their link can sign in with their company email plus one of
  their own order numbers.
- **Dashboard** — orders-per-week, order-type and busiest-customer charts, low
  stock alerts, and what's due.
- **Stock** — items with images, on-hand / minimum levels, adjustments &
  history, and optional automatic deduction as orders are generated.
- **Customers** — full customer database with delivery/billing details.
- **Filter calculator** — the three ways to bend a frame (U, sideways U, G),
  which one gets the most filters out of a 2440 length of channel, and the
  marks to strike off the tape. **The lip is part of the sum**: it's nominally
  20mm but anything down to 10mm still closes the filter, so where shortening
  it wins a whole extra frame it does — two G frames of a 295 × 310 are 2444
  against a 2440 stick, and 2mm off each lip makes them 2440 exactly with
  nothing on the floor. It never trims a lip for nothing, every length prints
  its own marks (a part-full one keeps the full 20), it works the offcut rack
  before opening new channel, and it says what it turned down and by how much.
  A cut list for a whole order comes off the Actions menu in View Order, and
  **Today's cut list** does every outstanding order at once, grouped by size.
- **The offcut rack** — what's left and how long, written down in ten seconds
  at the saw by whoever cut it. The calculator works the rack first. Used
  pieces are marked, never deleted.
- **How each customer wants them** — some always want a G. Stored against the
  customer and honoured, with what the preference costs reported rather than
  hidden.
- **The rest of the thirty**, each behind its own switch under **Testable
  Features**: today's cut list and the week's cutting · media across the roll ·
  near a size we already make · what it turned down · scrap rate · batch by
  material · where everything has got to (the worksheet's own five tick boxes)
  · what you can promise · end of month · one search box · what is still owed ·
  planned against actual · channel counted in lengths · labour in the margin ·
  kits · what is installed where · what came back · stocktake · buying ·
  what each customer pays · the shutdown calendar · the cut list on the printed
  worksheet · the cut list on a phone at the saw · what a job actually cost ·
  Xero connected properly · orders straight from email.
- **Thirty features, each behind its own switch** — all built, all off to
  start with, so the factory changes when you decide it does. A Director or an
  Admin turns one on for the whole company under Settings → Features, and
  everything new lives under **Testable Features** in the account menu — off
  ones greyed rather than hidden, so somebody who's been told about one can
  find out where to turn it on. Nothing there grants access to anything: what
  a person may read or change is row-level security in the database, which has
  no off switch.
- **Audit Log** — every significant action recorded, from the desktop and
  from the web app in the same words.
- **A morning summary** — what's overdue, what's due today, what's low on
  stock and which repeat jobs have come round, emailed each weekday morning.
  Off until the company switches it on *and* you ask for one; nobody is signed
  up by anybody else. **Send mine now** works straight away.
- **Part numbers & square metreage** — every filter line gets its area and a
  part number derived automatically (`FPFCARB25-020`, `PPFG495-040`,
  `STPPFW50-030`, `FPF09-040`), shown in the app and printed on the worksheet.
  These are the same codes as the item codes in Xero, so a quoted line finds
  its price with nothing matched up by hand.
- **Job number highlighter** — show the app one of a customer's purchase
  orders, drag a box around their job number, and it learns the wording to
  look for on every future order from them.
- **Saying which customer it is** — an imported order that matches nobody
  offers **Pick Customer** (the likely branches first, each with the reason
  it's suggested) and **Highlight on Order** (drag a box round their name and
  address on the page). Choosing one remembers how that order reads, so the
  next one from them matches on its own. Creating a new profile is the last
  option rather than the only one — which is how one customer used to end up
  with four.
- **A screen facing the customer** — a second monitor at the counter showing
  the quote as it's built: every line, its price, the line total, the delivery
  and the total. It never shows a cost or a margin: what goes on it is worked
  out from prices alone, in its own module, so there's no path from the
  margin figures to that screen.
- **Learns from corrections** — when someone fixes a line in the import review
  screen ("V Filter" was read as unknown and they picked V-form; "MERV 8" was
  swapped for G4), the wording and what it meant are remembered and shared
  with every PC, so the next order that says the same thing is read correctly.
- **Invoice to Xero** — a dispatched order, or a whole delivery run, priced
  from the price list and written as a Xero sales-invoice import file. Xero
  splits one file into one invoice per order. Anything it couldn't price is
  listed before the file is written, so a line is never quietly dropped off
  an invoice.
- **Backup & Export** — one button writes a dated zip of spreadsheets:
  every order, every line, customers, quotes, stock and prices. They open in
  Excel and need nothing else — not this app, not an account, not the
  internet. Sign-in details and portal tokens stay out of it.
- **Barcodes** — every worksheet page carries its order number as a Code 128
  barcode, and Stock prints sheets of barcode labels for the racking and the
  rolls. Groundwork for a scanning gun: stock movements are applied inside the
  database on a locked row, and a movement carrying the same reference twice
  is applied once, so a handheld that loses signal and resends cannot
  double-count.
- **Quote anything you sell** — Add Line covers a made-to-measure filter, a
  bag filter or media roll, or any of the twelve thousand priced part numbers,
  searched by code or description with the price coming along with it. Product
  types (Bag Filter, Media Roll, Freight, Labour…) are shared between PCs, so
  the next kind of thing you sell needs an entry rather than a new release.
- **View Order** — one window with everything about an order: what's on it,
  every note anyone has left with who and when, its status, priority and
  freight, and every action — add a note, change status, freight/delay,
  print, regenerate, duplicate, quote, invoice. It shows the result rather
  than the state it opened with.
- **Profile pictures** — a photo against each account, cropped and rounded
  automatically, falling back to initials when there isn't one.
- **The account menu** — click your name or picture, top right, for your
  picture and password, Products, Settings, staff accounts and sign out.
  Those were tabs in front of everyone all day; they are set-up work, so the
  bar now holds only the screens used to do the job.
- **Fewer buttons** — the common actions stay on the bar and the rest sit
  under a menu beside them. Previous Orders went from seventeen buttons to
  five, Quotes from thirteen to seven. Destructive actions live under their
  own menu rather than one slip of the mouse from Print.
- **Keyboard** — Ctrl+1…0 for the tabs, Ctrl+N new order, Ctrl+F search,
  Ctrl+S do the main thing on this tab, Ctrl+P print, F5 reload, F1 for the
  list. Enter opens a row, Delete removes a line, Esc closes a dialog. The
  cursor lands in the field you were going to type in anyway.
- **Settings** — media types (with their part-number codes), custom filter
  types, low-stock thresholds, user management, light/dark mode, change
  password, in-app software update.

## Tech stack

Python 3.11+ · Tkinter · Supabase (Postgres + Auth) · ReportLab · openpyxl /
python-docx (Excel/Word via COM on Windows, AppleScript or LibreOffice on a
Mac) · Pillow · tkcalendar · PyInstaller.

---

## Prerequisites

- **Windows or macOS.** Both are built and published on every release.
- **Python 3.11+** (to run from source or build it yourself).
- A **Supabase project** (free tier is fine).

Everything works on both, with one difference worth knowing. The filter
worksheet is an Excel template, and turning it into a PDF needs something
that can lay out a spreadsheet. Windows uses Excel; a Mac uses Excel too if
it is installed, and [LibreOffice](https://www.libreoffice.org/) if it is
not. With neither, the app still saves the `.xlsx` and opens it, and you
print it from there.

## Setup

```bash
# 1. Clone
git clone https://github.com/<you>/<repo>.git
cd <repo>

# 2. (recommended) virtual environment
python -m venv .venv
.venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

### Configure Supabase

1. Set your project URL in [`taf_order_app/db.py`](taf_order_app/db.py) —
   the `SUPABASE_URL` constant near the top.
2. Copy the settings template and add your **anon / publishable** key:
   ```bash
   copy settings.example.json settings.json
   ```
   ```json
   {
     "custom_media_types": [],
     "supabase_anon_key": "sb_publishable_xxxxxxxxxxxxxxxxx"
   }
   ```
   `settings.json` is git-ignored so your key is never committed.

### Create the database tables

**Not sure what you've already run?** Paste
[`check_migrations.sql`](check_migrations.sql) into the Supabase **SQL Editor**
and run it. It changes nothing — it reads what your project has and lists what
is still outstanding, most urgent first.

Otherwise, in the Supabase dashboard → **SQL Editor**, run these in this order.
Every one is safe to run again, so if you are unsure whether you did one,
just run it — nothing is lost and nothing is duplicated.

| # | File | What it gives you | |
|---|------|-------------------|---|
| 1 | `setup_database.sql` | Accounts and orders — the base tables | essential |
| 2 | `customers_schema.sql` | The customer list | essential |
| 3 | `stock_schema.sql` | Stock items and their movements | essential |
| 4 | `extra_columns_migration.sql` | Supplier email, short name | optional |
| 5 | `migrate_orders.sql` | Archiving, and delete by role | essential |
| 6 | `migrate_audit_log.sql` | Who did what, and when | recommended |
| 7 | `migrate_media_types.sql` | Media types shared between PCs | recommended |
| 8 | `migrate_stock_alerts.sql` | Low-stock thresholds on the Dashboard | optional |
| 9 | `migrate_user_management.sql` | Directors and Admins managing accounts | recommended |
| 10 | `migrate_catalog.sql` | Filter presets shared between PCs | recommended |
| 11 | `migrate_customer_profiles.sql` | Short names, regions, job-number rules | recommended |
| 12 | `migrate_po_inbox.sql` | Photos sent from a phone | optional |
| 13 | `migrate_pricing.sql` | Price list and rates per m² | recommended |
| 14 | `migrate_quotes.sql` | Saved quotes | recommended |
| 15 | `migrate_quote_portal.sql` | Customers accepting a quote online | optional |
| 16 | **`migrate_staff_access.sql`** | **Security — read this one** | **ESSENTIAL** |
| 17 | `migrate_customer_portal.sql` | Customers seeing their orders online | optional |
| 18 | `migrate_portal_signin.sql` | Signing in by email or PO number | optional |
| 19 | `migrate_supplied_order_numbers.sql` | Our own TAF-ON- order numbers | recommended |
| 20 | `migrate_performance.sql` | Speed, and orders past the thousandth | recommended |
| 21 | `migrate_scanning.sql` | Stock counts that can't be lost | recommended |
| 22 | `migrate_avatars.sql` | Profile pictures on accounts | optional |
| 23 | `migrate_bulk_status.sql` | Marking a batch of orders complete | recommended |
| 24 | `migrate_line_progress.sql` | Ticking an order off line by line | recommended |
| 25 | `migrate_recurring_jobs.sql` | Jobs that come round every 3 or 6 months | optional |
| 26 | `migrate_margin.sql` | What a job costs, next to what it sells for | optional |
| 27 | `migrate_order_files.sql` | Photos and a signature kept with an order | optional |
| 28 | `migrate_notifications.sql` | A morning summary of what needs doing | optional |
| 29 | `migrate_features.sql` | Switching new features on, and how the workshop cuts | recommended |
| 30 | `migrate_more_features.sql` | Kits, sites, returns, stocktakes, buying, agreed prices, shutdowns | optional |
| 31 | `migrate_quote_shipping.sql` | Delivery charged on a quote, so the counter and the invoice agree | recommended |

**Step 16 is the one that matters most.** Every policy in the older scripts is
`TO authenticated USING (true)` — meaning *anyone Supabase counts as signed
in*. The publishable key is public (it ships in the installer) and the login
window offers Create Account, so without this migration anyone holding that
key can register and read every order, customer, quote and price. It closes
that: staff means "has an **approved** profile", and every profile that
already exists is approved automatically, so nobody working today is locked
out.

A few notes on the rest:

- **20 (`migrate_performance.sql`)** also fixes a silent bug: the order list
  had no paging and PostgREST stops at 1000 rows, so past a thousand orders
  the oldest simply stopped appearing.
- **22 (`migrate_avatars.sql`)** adds profile pictures — an `avatar_url` on
  each profile and a public-read `avatars` bucket only staff can write to.
  Without it the app shows initials, exactly as it did before.
- **23 (`migrate_bulk_status.sql`)** makes changing one field of an order one
  statement in the database instead of a read of the whole header, an edit in
  the app and a write back. That halves the round trips when you tick twenty
  orders and mark the lot complete, and it stops a note someone adds
  mid-batch from being overwritten. Without it the app falls back to the old
  two-step write — still correct on its own, just slower and not safe against
  someone editing the same order at the same moment.
- **21 (`migrate_scanning.sql`)** must be run before anyone scans anything.
  Stock adjustments used to be read-modify-write, so two people counting the
  same rack at once lost a count. It also makes SKUs unique — if you already
  have duplicates it names them and installs everything else, so run it, read
  the warning, fix those SKUs and run it again.
- **12 (`migrate_po_inbox.sql`)** also needs the `po-inbox` Storage bucket,
  which the file creates.
- Order in the table is order of dependency — later files assume tables the
  earlier ones create. Running all 21 top to bottom on a fresh project, and
  again on one that already has them, is verified by `tests/test_migrations.py`.

### Enable purchase-order import (optional)

**Import Purchase Order** reads uploaded documents with Claude. The API key
lives in a Supabase Edge Function so it is never shipped inside the installer,
where anyone could extract it.

1. Get an Anthropic API key from [console.anthropic.com](https://console.anthropic.com).
2. Deploy the function and give it the key:

   ```bash
   supabase secrets set ANTHROPIC_API_KEY=sk-ant-...
   supabase functions deploy extract-orders
   ```

   No terminal? In the Supabase dashboard: **Edge Functions → Deploy a new
   function**, name it `extract-orders`, paste in
   `supabase/functions/extract-orders/index.ts`, then add `ANTHROPIC_API_KEY`
   under **Edge Functions → Secrets**.

Costs a few cents per page. Skip this and the rest of the app works normally —
the Import button just explains that the reader isn't set up yet.

### The web app (optional)

`docs/app/` is a staff web app served off GitHub Pages alongside the customer
portal — the same orders, on a phone or a tablet on the factory floor. Sign in
with the usual staff account; the database decides what each one can see.

Open it from the desktop app once: **your name, top right → Open on a phone**.
The link carries the publishable key the same way portal links do, the phone
remembers it, and after that it is a bookmark. Everyone still signs in
themselves.

Today, New order, Orders, Scan, Delivery, Quotes, Customers and Stock. You can
raise an order, tick its lines off as they're made, change a status, add stock
adjustments, photograph a job, take a signature at the drop, look anything up.

**It keeps working with no signal.** The app installs itself on the phone the
first time it's opened, so it starts at the back of the factory where the wifi
doesn't reach. Anything done out of range — a line ticked, a status changed, a
stock count — is kept on the phone and sent when the signal comes back; a bar
under the tabs says how many are waiting and gives you a **Send now**. A tick
that hasn't gone yet is drawn with a dashed box, so what's real and what's
still on the phone are never the same picture.

Lists you've already looked at (orders, customers, stock) come back out of
range too, and say when the phone last saw them rather than passing themselves
off as today's. Nothing from the database is ever cached silently: an hour-old
stock figure looks exactly like this minute's, and that is worse than an error
message.

Signing out with work still waiting stops and asks, because the next person to
use that phone must not send the last person's ticks under their own account.

**Log** (managers and above) is the same audit log the desktop's Audit Log tab
reads, filtered by person, by day and by search. Raising an order, changing a
status and ticking a line off are written there from either screen in the same
words, so one day's work reads as one list. Something done out of signal says
when it was actually done as well as when it reached the database — the
database still stamps the time, so a phone with a wrong clock can't reorder
anybody else's day.

**A phone left on a bench signs itself out.** After half an hour untouched it
asks, waits a minute, then signs out — so whoever picks it up next isn't
signed in as the last person. It won't do that over work that hasn't been
sent: that would strand it under an account nobody else can send it with.

**Scan** reads the Code 128 barcodes the app already prints — on a worksheet,
on a rack label — through the phone's camera, and opens the order or the stock
item it names. There's a box to type or scan a code into as well: a handheld
scanner in keyboard mode types straight into it, and it's the way in on any
browser without a barcode reader, which today means every iPhone. What a code
means is decided by `resolve_scan` in the database, so the handheld, the phone
and the desktop can't drift apart. Out of signal it still resolves anything the
phone has already seen.

It does **not** generate worksheets. Those are made by driving Excel and Word
through COM, which runs on Windows and nowhere else, so an order's paperwork
stays on the desktop app.

**An order raised on the web carries the dimensions and no part number.**
Working one out takes about a thousand lines of rules that live in Python, and
a second copy of those in JavaScript would put different part numbers on Xero
invoices depending on which screen an order happened to be raised on. The
desktop fills them in when it opens the order — which it has to do anyway to
print the worksheets — so there is one copy of the rules and nothing to drift.
Quoting stays on the desktop for the same reason: you can't price a line
without seeing its square metreage as you type.

**Run `migrate_staff_access.sql` before this goes live.** Without it anyone who
can register can read every order, customer, quote and price — which is bad on
a PC in the office and considerably worse with a login box on the open
internet.

Scan needs `migrate_scanning.sql`, ticking lines off needs
`migrate_line_progress.sql`, and photos and signatures need
`migrate_order_files.sql`. Run `check_migrations.sql` to see what's still
outstanding.

### Enable emails to customers (optional)

Sends a customer an order received slip when their order is generated, with a
link to follow the job in their portal. **It ships switched off**, and the
switch is company-wide — Settings → Emails to customers, manager only. Until
somebody turns it on, nothing is sent and generating an order is unchanged.

The mail provider's key lives as a function secret for the same reason the
Anthropic one does: anything in the installer can be pulled back out and used
to send mail as Total Air Filtration.

1. Get an API key from a mail provider — the function is written for
   [Resend](https://resend.com), whose free tier is ample for this. You'll need
   a domain you can verify, so the mail comes from your own address rather than
   a stranger's.
2. Deploy the function and give it the key:

   ```bash
   supabase secrets set RESEND_API_KEY=re_...
   supabase secrets set MAIL_FROM="Total Air Filtration <orders@yourdomain>"
   supabase secrets set PORTAL_URL="https://malakaics.github.io/TAF-App/portal/"
   supabase functions deploy send-order-email
   ```

   No terminal? **Edge Functions → Deploy a new function**, name it
   `send-order-email`, paste in
   `supabase/functions/send-order-email/index.ts`, then add the three secrets
   under **Edge Functions → Secrets**.
3. Turn it on in Settings when you're ready.

A customer with no email address on their record is skipped, and the order is
unaffected either way — an order that couldn't be confirmed by email is still
an order. The switch is checked again inside the function before anything is
sent, so a PC that has been left open since yesterday can't send on
yesterday's answer.

### Switching the new features on (recommended)

Thirty things were asked for at once. All thirty are built, each behind its
own switch and all off to start with, so the first one that gets in
somebody's way doesn't take the other twenty-nine down with it. Anything
asked for since is in the same list and works the same way.

Run `migrate_features.sql` and `migrate_more_features.sql`, then
**Settings → Features**. A **Director or an
Admin** flips a switch and it changes for the whole company — not a Manager,
because this decides how everybody works rather than how today goes. Anything
not built yet is listed and locked: a switch that does nothing is worse than
no switch.

The same screen holds **How the workshop cuts** — the length channel comes in
(2440), what the saw blade takes (0), the shortest offcut worth keeping (400),
the lip (20), the shortest lip that still closes a filter (10) and what's
taken off every side (2). A manager can change
those; the filter calculator works to them, and they're shared so a cut list
worked out on one PC matches the next. Re-running the migration never
overwrites what you've set.

**Kerf ships at nothing, deliberately.** A frame isn't cut into pieces at its
marks — the two 45° notches and the lip cut come off the flanges, not the
running length — so the only cut through the channel is the one separating one
strip from the next on the stick. Set it above zero only if your saw really
does eat into the next piece.

### A morning summary (optional)

What's overdue, what's due today, what's low on stock and which repeat jobs
have come round — emailed each weekday morning. Everything in it is already on
the Dashboard; the trouble with a Dashboard is that it only says anything to
somebody who opens it, and the morning it mattered most is the morning nobody
did.

**Two switches, and both have to be on.** The company one (Settings → Email,
manager only) decides whether this system sends staff mail at all. Each person
then decides whether they want one — on the desktop under Settings, on a phone
behind their own name, top right. Nobody is signed up by anybody else.

1. Run `migrate_notifications.sql`.
2. Deploy the function. It reuses the same mail provider key as the customer
   emails above, so if that's already set up there's nothing new to configure:

   ```bash
   supabase functions deploy daily-summary
   ```

   No terminal? **Edge Functions → Deploy a new function**, name it
   `daily-summary`, paste in `supabase/functions/daily-summary/index.ts`.
3. Turn the company switch on, tick your own, and press **Send mine now** —
   which works straight away and is how you find out today, rather than at
   seven tomorrow morning, whether the mail side is right.
4. To have it arrive by itself each morning, schedule it. That needs pg_cron
   and pg_net, and the service-role key in Vault rather than in a file — the
   whole recipe is written out at the bottom of `migrate_notifications.sql`.

Sending to everybody is something only that schedule can ask for: it's the
only caller holding the service-role key, and a signed-in account asking for
it is refused. Each person's copy goes to their address alone — a summary of
the whole factory bcc'd around is one wrong address away from being a list of
every customer's late job in a stranger's inbox.

### Enable sending from a phone (optional)

Lets staff photograph a purchase order on their phone and have it arrive in the
office app. Requires purchase-order import above.

1. Run `migrate_po_inbox.sql` in the **SQL Editor** — the private bucket the
   photos land in.
2. Turn on **GitHub Pages** once: repo → **Settings** → **Pages** → Source
   *Deploy from a branch*, branch `main`, folder **/docs** → Save. This hosts
   the page phones open, at
   `https://<owner>.github.io/<repo>/phone/`.
3. Link a phone: in the app, **New Order** → **Import Purchase Order** →
   **Photograph it on a phone**, and scan the QR code. Add the page to the
   phone's home screen and it behaves like an app. Staff sign in with their
   normal TAF login the first time.

The QR carries the project URL, the publishable key and a pairing id, so the
page itself holds no configuration and photos come back to the PC that showed
the code rather than to whichever office PC sweeps first. The phone remembers
all of it, and the app strips the query string from the address bar after the
first load.

**Why GitHub Pages and not Supabase?** Supabase serves anything it hosts as
`text/plain` with `Content-Security-Policy: default-src 'none'; sandbox` and
`X-Content-Type-Options: nosniff` — a deliberate anti-XSS policy. A page served
from an Edge Function or from Storage therefore arrives on the phone as
unstyled source with every script blocked, whatever content type the upload
asked for. Pages serves real HTML.

The office app sweeps for new photos every minute, reads them in the
background, and shows a **📱 Phone Inbox** button on the New Order tab when
orders are ready to review.

### Set up quoting (optional)

1. Run `migrate_pricing.sql` in the **SQL Editor** (safe to re-run).
2. **Products → Import Price Files**, and select all three files in
   [`price_lists/`](price_lists/) at once — 12,480 priced part numbers. The
   confirmation names the columns it read from; check the price column is the
   one you expect before saying yes.
3. Optionally set **Rates per m²** for a filter type and media, used only
   where a part number has no listed price.

Any spreadsheet works, not just those: it needs a heading row with a
part-number column (`Part No`, `Code`, `SKU`, `ItemCode`…) and a price column
(`Price`, `Sell`, `SalesUnitPrice`, `Rate`…). Every sheet in a workbook is
read separately, and where a file has both a sales and a purchases price, the
**sales** one is used — the headings are scored, and the choice is then
checked against the rows beneath it, because a heading can look right and the
column still be empty. Long paragraphs are never treated as headings, so a
Read Me sheet can't be mistaken for a catalogue.

Quote from the **Quotes** tab — add lines, or **Load from an Order** to pull a
saved one in. **Quote** on the New Order tab and on a saved order in Previous
Orders does the same for what is already in front of you.

**Why a CSV and not the Xero API?** The CSV import needs no app registration,
no OAuth callback and no stored credentials, and Xero previews the whole batch
for approval before creating anything. Import it in Xero under
**Business → Invoices → Import**, and check the account code and tax rate on
the preview.

### Turn on automatic stock deduction (optional)

**Settings → Stock** has a switch, off by default so stock can be counted
first. With it on, generating an order deducts:

- a stock item whose **SKU is the line's part number**, by the line quantity;
- **media kept in m²**, by the line's area.

Anything else is left alone and reported on the order's completion message —
the app never guesses at a bill of materials. Every movement is recorded as a
normal stock transaction, so a wrong one can be reversed by hand.

### Let customers accept quotes online (optional)

1. Run `migrate_quotes.sql` then `migrate_quote_portal.sql` in the **SQL
   Editor**.
2. GitHub Pages must be on (the same switch as the phone page above). The
   customer page is served at `https://<owner>.github.io/<repo>/quote/`.
3. In the app: **Quotes -> Save Quote -> Send to Customer**. The link is copied
   to your clipboard; paste it into an email.

**How it's kept private.** The link carries a random 64-character token. The
`quotes` table gives anonymous callers *no* access at all - the page can only
call two `SECURITY DEFINER` functions that take the token and return one
quote, so there is no query a visitor can shape and nothing to enumerate.
Without the token there is nothing to see, and the token can't be guessed. The
page is `noindex`, and it strips the token out of the address bar after
loading so it isn't left in a screenshot or a shared browser history.

The customer sees the lines, the totals, and anything not yet priced marked
"to be confirmed". They don't see internal notes, other quotes, or how a price
was arrived at. Accepting or declining is a one-way step: once answered, the
page won't change it - that's a phone call.

### Let customers see their orders online (optional)

1. Run `migrate_staff_access.sql`, `migrate_customer_portal.sql`, then
   `migrate_portal_signin.sql`.
2. **Fill in [`docs/company.js`](docs/company.js)** — phone, email, address,
   ABN, hours, and where customers collect a pick-up. Edit it on github.com
   and save; the pages pick it up straight away, no release needed. Anything
   left blank is simply not shown, so a half-filled file still looks right —
   but a customer asked to accept a quote with no phone number to ring is the
   thing to fix first.
3. In the app: **Customers**, pick one, **Customer Portal → Create Link**. The
   link is copied to your clipboard.
4. Record freight against an order with **🚚 Freight / Delay**, on Previous
   Orders or the Delivery tab. Carrier and consignment number become a
   tracking link on their portal; the note is shown to them in your words.

They see their orders with a stage on each — Received, Being made, Ready for
delivery, Ready for pick up, Delivered, Collected — their quotes (with a link
straight through to accept one), and their account details.

**How it's kept private.** Same shape as the quote page: a random
64-character token, no anonymous access to any table, and three
`SECURITY DEFINER` functions that take the token and return one customer's
data. **Turn Off** stops a link working; **New Link** replaces the token,
which invalidates every link ever sent for that account.

**Signing in without the link.** Company email **plus** one of their own
purchase order numbers. Both are asked for deliberately: an email address is
on their letterhead and an order number is short enough to count through, so
either alone would open an account to a stranger. Failures read the same
whichever half was wrong, so the form can't be used to discover which emails
or orders exist, and ten wrong tries in fifteen minutes stops the guessing.

Worth knowing: the link is the credential. Anyone it is forwarded to can see
that customer's orders — so it goes to the customer and nowhere else, and if
it goes astray you issue a new one.

### Create the first admin account

```bash
python create_default_account.py
```

Credentials are read from environment variables (or prompted if unset):

```bash
set TAF_ADMIN_EMAIL=you@example.com
set TAF_ADMIN_PASSWORD=your-strong-password
set TAF_ADMIN_NAME=Your Name
set TAF_ADMIN_ROLE=Director
```

---

## Run from source

```bash
python modern_order_gui.py
```

## Build the Windows executable

```bash
pyinstaller --noconfirm --clean TAFOrderEntry.spec
```

Output lands in `dist/TAFOrderEntry/` (onedir build; run `TAFOrderEntry.exe`).
Public Sans fonts and the logos are bundled automatically.

### Build the installer (optional)

Install [Inno Setup 6](https://jrsoftware.org/isinfo.php), then:

```bash
ISCC installer.iss
```

Produces `TAFOrderEntry_Setup.exe`.

## Build the Mac app

Has to be done on a Mac — PyInstaller cannot cross-compile, and an Intel Mac
and an Apple Silicon Mac need separate builds. CI does both on every release
(`macos-13` and `macos-14`) and attaches two disk images.

```bash
pip install -r requirements.txt
python make_mac_icon.py --icns
pyinstaller --noconfirm --clean TAFOrderEntry.spec
codesign --force --deep --sign - "dist/TAF Order Entry.app"
```

### Installing it

Download the disk image that matches the Mac — **AppleSilicon** for an M1 and
later, **Intel** for anything older (☰ → About This Mac says which). Then
drag the app onto Applications, **right-click it and choose Open**, and click
Open again.

That last bit is only needed the first time, and only because the app is not
signed with an Apple Developer certificate — a paid yearly subscription, for
an app that never leaves the company. macOS therefore does not know who made
it. If it says the app *"is damaged and can't be opened"* it is not damaged;
that is the same block wearing a different hat, and this clears it:

```bash
xattr -cr "/Applications/TAF Order Entry.app"
```

Updates from inside the app handle that themselves. The app downloads the
right image for the machine, clears the flag and opens it — the only manual
step left is dragging the new copy across.

---

## Project structure

```
modern_order_gui.py        Main UI (app shell, all tabs, widgets)
pdf_generator.py           Order-PDF generation (ReportLab)
template_filler.py         Excel worksheet filling (COM)
taf_order_app/
  db.py                    Supabase wrapper (auth, orders, stock, customers)
  login_window.py          Split-panel login / register / reset
  order_service.py         Order build/save orchestration
  paths.py                 The one folder this app writes to, per platform
  bag_filler.py            Word worksheet filling (COM)
  updater.py               In-app auto-update (APP_VERSION lives here)
  po_import.py             Purchase-order import + phone inbox
  part_numbers.py          Part numbers, square metres, filter-type rules
  pricing.py               Price lists, quote lines, Xero export
  quote_pdf.py             The quote PDF
  stock_usage.py           What an order takes out of stock
  delivery.py              Run sheets and what's ready to go out
  backup.py                The dated zip of spreadsheets
  labels.py                Barcode labels for stock, on Avery sheets
tests/                     Rule tests — `python tests/run.py`, run by CI
  smoke_gui.py             Builds every screen for real — also run by CI
  user_management.py       Roles & user admin
  models.py / validation.py
fonts/                     Bundled Public Sans (OFL)
price_lists/               The priced catalogue (import under Settings)
*.sql                      Schema + migrations
docs/phone/index.html      The page phones open (served by GitHub Pages)
docs/app/                  The staff web app — orders, scanning, works offline
docs/sw.js                 Keeps the web app on the phone with no signal
docs/quote/index.html      The quote page customers open
docs/portal/index.html     The customer portal (orders, quotes, account)
docs/company.js            Phone, email, address, hours — fill this in
supabase/functions/        Edge Functions (order reading, email, the
                           morning summary)
TAFOrderEntry.spec         PyInstaller build spec (Windows and macOS)
installer.iss              Inno Setup installer script
make_mac_icon.py           Builds the Mac app icon from the logo
```

## Working from anywhere (incl. your phone)

The whole release pipeline is cloud-based — you can edit code and ship updates
without a PC.

**Edit code:** open the repo on github.com and edit files inline, or press `.`
to open the browser VS Code editor (`github.dev`), or use the **GitHub mobile
app**. Commit straight to `main`.

**Cut a release (one button):** repo → **Actions** tab → **Build & Release** →
**Run workflow** → type the version (e.g. `2.0.3`) and optional notes → **Run**.
GitHub bumps the version, builds the Windows installer, and publishes the
Release. Installed clients then auto-update.

> ⚠️ A published release auto-updates **all** users immediately, and you can't
> run/test the Windows app on a phone. CI runs a syntax check **and the test
> suite** before building, so a broken rule won't ship — but the tests cover
> the rules (part numbers, prices, stock, due dates, delivery), not the
> Tkinter screens. Test UI changes on a Windows PC (install the release's
> `TAFOrderEntry_Setup.exe`) before relying on them.

## Our own order numbers

A customer who rings up without a purchase order number still needs the job
identified, so the **TAF #** button gives the order one of ours —
`TAF-ON-0001`, `TAF-ON-0002`, and so on. It sits beside Order Number on the
New Order tab and in the review screen when an imported document carried no
number.

Run `migrate_supplied_order_numbers.sql` once. It creates a Postgres
**sequence**, not a "find the highest and add one" query: two people on two
PCs press that button at the same moment often enough to matter, and
read-then-write hands them both the same number. The trade is gaps — a number
taken and then abandoned is not reissued — which is right for an order number,
where being unique matters far more than being consecutive.

That is also why it is **kept apart from invoice numbering**. An order number
names a job in the shop; an invoice number is an accounting record where a
missing number is a question from an auditor. Tying them together means
neither can change without disturbing the other.

Numbers already typed in by hand are picked up: the migration starts the
counter above the highest `TAF-ON-` number already on an order.

Taking a number needs a connection. Offline it says so rather than guessing
locally, because a duplicate order number is a worse problem than a delayed
one.

## Tests

```bash
python tests/run.py       # the rules. No dependencies; pytest also works
python tests/smoke_gui.py # starts the real window and builds every screen
```

Every test is a regression — something that went wrong in a shipped build and
reached the people using it. Add one whenever a bug gets out.

`tests/smoke_gui.py` is the second kind. It starts the actual app against a
stand-in database, builds every tab, opens every dialog and runs every export,
once as a manager and once as everyone else — rights decide which half of some
screens gets built. It is what catches a method that is called but was never
written, or two cards placed in the same grid cell so one draws on top of the
other: neither shows up in a diff, and both are obvious the moment the screen
is built. It needs a desktop to draw on, so it runs on Windows in CI and says
`SKIP` anywhere without one (on Linux, `xvfb-run python tests/smoke_gui.py`).

Both run in CI before the installer is built, so a broken build cannot be
published.

The barcode tests print the PDFs and read the barcodes back, because "there is
a barcode on the page" and "a scanner can read it" are different claims and
only the second one matters — the first version of the worksheet barcode drew
perfectly and decoded 0 times out of 4. That optical check needs `pdftoppm`
(poppler) and `pyzbar`, and skips where they aren't installed; CI has neither,
so what CI gates is the measured bar width the decoding established.

## Notes

- **Roles:** Director / Admin > Manager > Employee gate destructive actions and
  user management.
- **Auto-update:** the app checks the latest **GitHub Release** of this repo and
  self-updates by downloading and silently running the installer. To ship an
  update, run `python push_update.py 2.0.1 "release notes"` — it bumps the
  version, tags `v2.0.1`, and pushes; GitHub Actions then builds the installer
  and publishes the release. Requires the repo to be **public** (so the updater
  can read releases without a token) and the `SUPABASE_ANON_KEY` Actions secret.
- **Fonts:** Public Sans is bundled under the SIL Open Font License.
