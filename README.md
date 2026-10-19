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
  presets (add / edit / remove your own; a preset can hold panel filters,
  bag filters and mounting frames — its bags come out as bag lines, halved
  for a REP/FIL order like the panels), duplicate-order warning, live
  worksheet + order-PDF generation.
- **Every order is for a customer account** — typing in Customer Name lists
  the accounts it could mean (initials badge, the typed part in bold, short
  name, contact and email underneath), with **+ Create "…" as a new
  customer** at the top. Generate refuses a name that is no account and
  offers to make it. Each account is given its **Location** — Local, North,
  Logan, Gold Coast, Sunshine Coast, Ipswich, Freight or Pick Up — and that
  is what goes in the order's Location; the delivery address is only for the
  labels. An account with no Location is asked for one when it is picked.
- **Bag headers** — off by default; tick Header on any bag filter and the header gets its
  own page on the filter worksheet: 15 mm smaller than the bag each way and
  25 deep (a 610 × 610 bag takes a 595 × 595 header), with a wire cut 15 mm
  smaller again on a wire header (bag On Wire): 580 × 580. The header's size
  and the wire's can each be edited on the line without touching the bag,
  and every bag on wire shows its wire size on the bag worksheet. **Custom Bag Filter**
  is ordered by its header size, pockets and pocket depth — 855 × 570 × 5
  pockets, 480 deep, framed 20 mm: an 855 × 570 × 20 header, wire 840 × 555.
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
- **Delivery dockets** — a docket per customer rather than per order, so
  somebody collecting five orders at once signs once for the lot. Each order
  number is listed with its own filters underneath, so a query about one order
  doesn't put the other four in doubt. Two copies: the **customer copy** they
  keep, and the **office copy** they sign and we keep — the only thing that
  settles "we never received those" weeks later. A pick-up prints as a
  COLLECTION docket asking who collected it, a drop as a DELIVERY docket
  asking who received it. Prints the selected orders, or the whole run when
  nothing is selected.
- **Order Supplies** and the **bell** — anyone on the floor presses **New
  order**, on the desktop or a phone, and picks from the stock list (searched,
  or **Add everything low** at once) or types something that isn't on it.
  Each line comes with how many gets it back to its minimum and its preferred
  supplier; there is a note and an "urgent" tick. It goes as one order and
  every manager is told once: the bell next to the profile picture turns red
  with the number waiting (1, 2, 3 … and 99+ past ninety-nine). The list
  shows one row per order, opened to see its lines, the way Previous Orders
  shows a job. Managers mark an order (or one line of it) Ordered, Received
  or Declined; the person who asked can cancel it while it's still waiting.
  Once nothing on an order is waiting it comes off every manager's bell
  (step 43). The database does the telling, so nobody can send a
  notification, ask as somebody else, or have a request filed twice when a
  phone loses signal. Managers turn the requests into **purchase orders**
  sent through Xero (see *Buying through Xero*).
- **The factory floor** (step 44, each part switched on in Settings →
  Features):
  - **Production board on the TV** — open the web app on the TV with
    `?board=tv` (the link is under *Production board on the TV…*) and sign in
    once as staff. Four columns — To cut, Making, Packed, Out the door —
    big enough to read across the factory, refreshed every 30 seconds, never
    signing itself out, the screen kept awake. Late jobs are red, today's
    amber, priority jobs starred.
  - **Job timer** — ▶ Start / ■ Stop on a line in the phone app (one running
    per person; starting another stops the first). *How long things take…*
    shows minutes a filter by type, from the last six months.
  - **QC checklist** — managers set a few checks per filter type (or for
    every type) in *QC checklists…*; they are ticked on the phone or PC
    before a line can be marked made, and kept on the line with who and when.
  - **Fault and rework log** — ⚠ on a line (or *Record a fault…*): what was
    wrong, where it was found, who made it, a photo. *Faults and rework…*
    adds them up by reason, filter type and person.
  - **Photo of the finished job** — *Finished job photo* on an order in the
    phone app. With the switch on, the database will not let an order be
    marked Complete (or go out) without one, from any screen; the customer
    sees it on their portal.
- **Planning** (step 45, switched on in Settings → Features):
  - **Staff roster and leave** — *Staff roster and leave…*: who makes
    filters on which days and for how many hours, who is away and when, and
    *the next fortnight*: who is in and away each day, what the day can take
    and what is already booked (red when it is over).
  - **Warn when a day is full** — on the desktop and the phone, a new order
    due on a day that cannot take it says so before it is saved ("Friday
    16/10 is already full: 7.3 h booked, and this order adds 1 h, against
    8 h with 2 in. Monday 19/10 has room."). Booked is what is still to make
    on the orders due that day, at the job timer's minutes a filter (15 until
    a type has been timed); a day can take the rostered hours of those in,
    times the share of a day spent making (80%), and nothing on a shutdown
    day.
  - **Order again** — *Customer ▾ → Order again…* on the desktop, or *Order
    again* on any order (and *Order their last one again* on a customer) on
    the phone: the same lines on a new order, nothing made, ready for a new
    order number.
- **Winning the work** (step 46, switched on in Settings → Features):
  - **Quotes to chase** — quotes with no answer a week after they were sent
    (and not chased in the last week) on Today, desktop and phone. *Chase*
    opens an email to the customer, ready to send, with the link to their
    quote in it, and counts the chase.
  - **Why quotes are lost** — *Mark lost…* with the reason (price, lead
    time, went elsewhere, no longer needed, no reply, other); *Why quotes are
    lost…* adds them up with the win rate, and lists declined quotes still
    without a reason.
  - **Filter-change reminders** — *Customer ▾ → Filter change every…* sets
    how often a customer's filters are changed. Those due within a fortnight
    (or late) show on Today and in *Due for a filter change…*, with *Quote
    it* (their last order on a quote), *Order again* and *Snooze 2 weeks*.
  - **Change prices** — *Change prices…*: everything, the part numbers or the
    square-metre rates, optionally only those containing some text, chosen
    tiers, by a percent, now or from a date. Preview first; applied once (a
    scheduled one by the first manager's PC to start on the day). Quotes
    already sent keep their prices.
  - **Who owes what** — unpaid invoices from Xero by customer, aged (not
    due, 1-30, 31-60, 61-90, over 90 days), with a statement PDF and an
    email to send it with.
- **Stock you can trust** (step 47, switched on in Settings → Features):
  - **Stocktake on the phone** — with *Stocktake mode* on, the phone has a
    *Stocktake* tab: start a count, find each item (a scanner that types the
    label goes straight to it), type what is on the shelf. Counts made out of
    signal wait on the phone and go in when it is back. *Finish* lists what
    is not what the system says, and a manager sets stock to what was
    counted.
  - **Stock spoken for** — what the open orders will take of each item, by
    the same rules stock is deducted by, worked out when the Stock page
    refreshes. Cards say "12 on 2 jobs · 28 free", desktop and phone.
  - **What suppliers have charged** — *Item ▾ → What we've paid…* (and on a
    stock item on the phone): every price from a purchase order sent, by
    supplier and date, with the change against that supplier's last price.
  - **Order before it runs out** — *Order before it runs out…*: stock that
    will be under its minimum before a new order could arrive, from how fast
    it has been used over 60 days and how long its supplier takes (sent to
    received, from the last 18 months; a week until known), with how many to
    order.
- **Out the door, and what it made** (step 48, switched on in Settings →
  Features):
  - **Proof of delivery emails** — when the customer signs on the driver's
    phone (*Signed for* on an order), the order is marked Delivered and the
    customer is emailed straight away: what was delivered, who signed and
    when, with the signature and the photos taken at the drop attached. One
    signature is sent once. The order on the PC says who signed and when it
    was emailed. Needs the `proof-of-delivery` function (below).
  - **Route order for the run** — *Plan the route…* (Delivery → Run ▾, or
    on the phone's Delivery screen as *Today's run*): today's stops in the
    order the van goes, suggested by region and postcode, moved up and down
    and saved - the PC, the phone and the printed run sheet all follow it.
    *Open in Google Maps* gives directions from the base round every stop and
    back (split into parts past nine stops, which is as many as Maps takes).
  - **Job profitability** — *What jobs made…* (managers): every job finished
    in the last 90 days - sold (ex GST, with delivery), less materials (the
    costs kept for quote margins) and labour (the job timer's minutes at the
    workshop's rate per hour; the usual minutes for a type when a line was
    not timed) - least made first, then by customer and by filter type.
  - **Owner's report** — *Owner's report…*: a month on one page - orders and
    their value against the month before and the target, biggest customers,
    quotes won and lost and why, jobs finished and how many on time, hours
    timed, faults, stock under its minimum. *Look at it* or *Email it to me*
    from the PC; emailed to every director and admin on the 1st once the
    schedule at the bottom of `migrate_delivery_money.sql` is set up. Needs
    the `owner-report` function (below).
  - **Sales targets** — *Sales targets…*: a target for each month (a manager
    double-clicks a month); Today on the PC and the phone shows how far
    through it the month's orders are and what each working day left needs.
    What an order is worth (priced lines plus delivery, ex GST) is worked out
    in the database, so every screen and the report agree.
- **How we do things, and talking to each other** (steps 49 and 50 - part of
  the app, with no switch):
  - **How-to library** — *How-to library…* on the PC and *How to* on the
    phone: a procedure for each job or filter type, with the words, a video
    link and a file (PDF, photo). Managers add and change them; changing what
    one says makes a new version. *I've read this* signs off the version
    there now, and a manager sees who has read the latest, who read an older
    one and who has not read it at all. A line on an order on the phone
    offers 📘 how to make that filter type.
  - **Messages** — the speech bubble beside the bell, on the PC and the
    phone, with a count of what you have not read (and a word on screen when
    something comes in); also *Messages* under your name on the PC and in
    the phone's tabs. One noticeboard everybody reads, group chats only
    their members see, and private messages: *Message someone* to anybody on
    staff, which only the two of you can read (one conversation per pair).
    Pinned messages stay at the top. Who may do what is a minimum role for
    each, set by a director or admin in *Who can do what…*:

    | | Out of the box |
    |---|---|
    | Post on the noticeboard | Managers and above |
    | Pin a message | Directors and admins |
    | Start a group chat | Managers and above |
    | Take down anybody's message | Directors and admins |

    Everybody can take down their own. A group also says who can post in it
    (everybody in it, or managers and above, or directors and admins);
    whoever started it, or an admin, changes who is in it. The database
    holds all of these rules - a message cannot be posted, pinned or taken
    down around them from any screen.
- **Delivery labels** — one A4 landscape sheet per wrapped bundle, with the
  TAF logo, the company's base address as From, the delivery address, filter
  size, the quantity in that wrap (and the line's ordered quantity), the
  wrap's weight and its wrap page: `1 of 2`, `2 of 2` for a one-line order;
  `1A/2`, `1B/2`, `2/2` across several lines (after Z comes AA). The order
  number appears once, as Order Number; Job Number shows N/A when there is
  no job. They print with the worksheets when you press Generate Output;
  reprint from Previous Orders → View Order → Actions → Delivery labels, or
  the Delivery tab's Run ▾ menu for a whole run. If a label can't be made
  yet (no customer account with a delivery address, say), the order still
  goes through and the Done message says why. Switch them off for everyone
  (Settings → Weights, packing and delivery labels) or for one customer
  (Customers → Customer ▾ → Turn delivery labels off, or the tick in their
  account); labels asked for from View Order still print. Needs step 35.
- **Merged or renamed customers on past orders** — after a merge, every
  past order and quote of the account and of the accounts merged into it
  shows the name it kept: in Previous Orders and inside the order, which
  View Order and reprints read. Renaming a customer offers the same, and
  Customers → Customer ▾ → Put this name on their past orders does it any
  time. Needs step 36, which also puts right merges already made.
- **Bag filters get no delivery labels** — how a bag is wrapped is not known
  until it is. On an order with panels too, the panels keep their numbers
  (the panel on line 3 of 3 is still 3/3).
- **Channel for the whole order** — each worksheet's FILTER CALCULATOR says
  how much channel the order takes per depth, and where two pages' frames
  fit on one length it says so: "cut G 1312 from one end, then page 2's
  G 1112 from the other end". The New Order screen shows the total too.
- **Due date on the bag worksheet** — large and bold at the foot of every
  bag page.
- **Pallet labels** — for an order going out on pallets: say how many
  pallets and how many of each line go on each (or spread them evenly), and
  each pallet gets an A4 sheet: `Pallet 1 of 3`, the filters on it, the
  customer, delivery address, order and job number. View Order → Actions →
  Pallet labels…, or the Delivery tab's Run ▾ menu. Several orders going to
  the same address can share the pallets: select them together in the run,
  or press **+ Add another order…** — each line then shows its order number.
- **Packing by weight** — every wrapped bundle is 10 kg at most, wrapping
  included, and a size can carry a handling limit (412 × 412 × 90: five a
  wrap). Lines are planned automatically, or the office sets the plan
  exactly as a customer asked — filters per wrap, number of wraps, or each
  wrap's quantity, optionally split into customer areas ("Area A = 10;
  Area B = 10"). A plan that breaks a limit is shown with a suggested one
  next to it, never quietly changed. Wraps can be weighed and the weight
  recorded; a re-pack starts fresh wraps and keeps the old ones in history.
  View Order → Actions → Packing and weights.
- **Wrapping Instructions and Filter Calculator on the worksheet** — two
  boxes under Notes: how to wrap each line, e.g. `(Wrap 5 Filters x 2 + Wrap
  2 Filters x 1)`, with the label codes; and, on Flat Panel and Pleated
  Panel (V-form) sheets, what to mark the filter as — `MARK AS U`, `MARK AS
  SIDEWAYS U` or `MARK AS G` — with the row of marks on the sheet that is
  (top row, FLIPPED or REVERSED) and the lip when it is trimmed to fit one
  more on a length. It is the filter calculator's answer, and it follows a
  customer's frame preference when that is switched on. Notes keeps exactly
  what was typed. BRACE REQ? now shows the answer.
- **Bracing notices** — worked out as a line is typed (desktop and web) and
  printed on the worksheet. Flat panels: both sides over 700 mm, one brace;
  long side over 1300 mm, two in Cross Format. V-forms: long over 1300 and
  short over 700. Flyscreens: short side 150 mm or under, or over 650 mm,
  "use brace in filter"; long over 1300, "consider bracing".
- **Weight calculator** — wire and media cut sizes and weights from the
  stock TAF buys (rates worked out from the weighed rolls, never typed),
  bracing, and mounting frames. It gives a complete filter weight only when
  every part is known, and says exactly what is missing otherwise. The same
  calculator runs on the desktop, the web app, and the
  `filter-calculator` API for other programs.
- **Merge duplicate customers** — Customers → ⇄ Merge duplicates (managers).
  Suggestions say why they were made and never merge on their own; every
  disagreement is chosen, agreed prices included; orders, quotes, sites,
  returns, recurring jobs and prices move in one transaction; the others are
  archived, still found by their old names, and the whole merge can be
  undone. Creating a customer that looks like an existing one warns first.
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
- **The TAF badge** — top left of the desktop app and the phone app, with
  the name beside it; click it and it gives a full turn. After signing in, a
  white screen with the badge turning shows until the first screen has its
  data, then fades away. On the phone and in a browser, cards fade and rise
  into place as they scroll into view. None of it moves for anybody whose
  computer or phone is set to reduce motion (macOS: Accessibility → Display
  → Reduce motion; Windows: Accessibility → Visual effects → Animation
  effects).
- **Stock** — items with images, on-hand / minimum levels, adjustments &
  history, and optional automatic deduction as orders are generated. Channel
  items show what the channel on hand weighs. Shown as square cards — the item's photo
  (whole, never cropped), name, a line or two of description, stock and MOQ
  (the minimum kept on hand) in the item's units, and what we pay for one ex
  GST (the preferred supplier's price, or Xero's) — five across on a wide
  screen, four, three, then two and one on a phone, by the room there is.
  Click a card to pick it for Open Item, Adjust Stock and the Item menu
  (Ctrl/⌘-click for several); double-click to open it. The phone and browser
  app's Stock page shows the same cards. On the phone a manager makes stock
  items too - **＋ New stock item**: name, SKU, type, unit, on hand, minimum,
  location, supplier, description, and a photo straight from the camera
  (made small before it goes up) - and **Add / Change photo** on an item's
  card. An item with the same name or SKU as one already there is asked
  about first.
- **C-channel weights** — every channel from 10 to 250 mm deep: its actual
  size (23 × centre × 23 × 2440 mm), what one length weighs and what stacks
  of 1, 2, 5, 10 or any number weigh, rounded up to the next 0.1 kg. Search,
  filter by how sure the width is, copy, export to CSV. Stock tab →
  C-channel weights…, or Settings → Open weights and packing → C-channel.
- **Customers** — full customer database with delivery/billing details.
- **Filter calculator** — the four ways to bend a frame (U, sideways U, G,
  and L: long side, short side, lip, cut twice for one filter), which one
  gets the most filters out of a 2440 length of channel, and the
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
- **A screen facing the customer** — press **Enable Second Screen Display** on
  the Quotes tab (or find it under Testable Features) and pick which monitor
  faces the customer. It shows the quote as it's built: every line, its price,
  the line total, the delivery and the total. F11 fills the screen, Escape
  leaves full screen, and the monitor you pick is remembered.
  It never shows a cost or a margin: what goes on it is worked out from prices
  alone, in its own module, so there's no path from the margin figures to that
  screen. Which screens exist is read from the machine — EnumDisplayMonitors on
  Windows, xrandr on Linux, system_profiler on a Mac — rather than guessed at
  from how wide Tk says the desktop is, and there's always a "just open a
  window I'll drag" option for when none of that works.
- **Learns from corrections** — when someone fixes a line in the import review
  screen ("V Filter" was read as unknown and they picked V-form; "MERV 8" was
  swapped for G4), the wording and what it meant are remembered and shared
  with every PC, so the next order that says the same thing is read correctly.
- **Invoice to Xero** — a dispatched order, or a whole delivery run, priced
  from the price list and written as a Xero sales-invoice import file. Xero
  splits one file into one invoice per order. Anything it couldn't price is
  listed before the file is written, so a line is never quietly dropped off
  an invoice.
- **Xero, linked** (optional, see *Link Xero* below) — connected once by a
  manager, for everyone. It starts as a **trial**: on an order, **Send to
  Xero & invoice customer** makes the invoice, approves it, has Xero email it
  to the customer and marks the order Complete; **Send draft to Xero** makes
  a draft to check. When the trial is done a manager **publishes** it to
  automatic: every order becomes a draft by itself, approved and emailed when
  its job is marked Complete. A line with no price never goes out on an
  invoice. Part numbers Xero doesn't have yet are made items in Xero.
- **Prices on the work order, in three tiers** — each customer is on Tier 1,
  2 or 3, and every product and rate has a price per tier. Each line on the
  work order shows its unit price and line total, filled in from the
  customer's tier (or typed by hand, marked ✎), and the order shows its total
  ex GST. Prices are on screen and on the invoice only — never on the
  workshop's worksheets.
- **Invoice wording** — what each kind of filter says on the customer's
  invoice ("Galvanised Pleated Panel Filter in G4 / Size: 595 x 595 x 45mm"),
  set once on the Xero screen; any line can say something else.
- **Delivery fees** — a customer can carry a delivery charge (set by a
  manager on the customer card). It fills in on every order for them, shows
  in the order's total, and goes on the invoice as its own Delivery line.
- **Correcting a saved order** — in View Order, double-click a line to
  correct it in the same window it was entered with, or its Unit $ / Line $
  to change the price; **Dates, job & delivery…** corrects the order date,
  due date, job number and delivery fee. An order already invoiced in Xero
  says so first, because its invoice won't follow the change.
- **A customer's Xero contact** — Customers → Customer ▾ → **Open in Xero**
  goes straight to their contact in Xero; **Link to a Xero contact…** picks
  it when the names differ, and their invoices go to that contact.
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
| 32 | `migrate_supply_requests.sql` | Asking for supplies, and the bell that tells managers (needs step 16 first) | recommended |
| 33 | `migrate_packing_and_merge.sql` | Weights, packing, delivery labels and merging customers (needs step 16 first) | recommended |
| 34 | `migrate_c_channel.sql` | C-channel weights: material, centre widths and measured weights saved with the other settings (needs step 33) | recommended |
| 35 | `migrate_label_switches.sql` | Switching delivery labels off for a customer, or for everyone (needs step 33) | recommended |
| 36 | `migrate_merge_names.sql` | A merged (or renamed) account's name follows onto its past orders and quotes - and fixes merges already made (needs step 33) | recommended |
| 37 | `migrate_xero_link.sql` | Xero linked for good: every order becomes a draft invoice, approved and emailed when the job is complete. Keeps the Xero sign-in where no app account can read it | recommended |
| 38 | `migrate_price_tiers.sql` | Three price tiers: each customer on Tier 1, 2 or 3, and a price per tier for every product and rate | recommended |
| 39 | `migrate_customer_xero_delivery.sql` | A customer's Xero contact (opened from Customers → Customer ▾) and a delivery fee every order of theirs carries | recommended |
| 40 | `migrate_purchasing.sql` | Buying through Xero: suppliers and items pulled from Xero, several items in one supply request, purchase orders received into stock (needs steps 16 and 31) | recommended |
| 41 | `migrate_stock_images.sql` | The storage bucket for pictures of stock items (stock_schema.sql only said to make it by hand) | recommended |
| 42 | `migrate_stock_suppliers.sql` | Where each stock item comes from: its suppliers, their codes and prices, so Order Supplies offers stock items and low stock becomes purchase orders (needs step 40) | recommended |
| 43 | `migrate_supply_bell.sql` | The bell only shows supply requests still waiting: once everything on a request has been ordered, received, declined or cancelled, it comes off every manager's bell (needs steps 32 and 40) | recommended |
| 44 | `migrate_floor.sql` | The factory floor: when an order changed status (for the TV board), a job timer, QC checklists, faults found in QC, and finished-job photos the customer sees on their portal (needs steps 16, 32 and the order-files, features and portal steps). Everything arrives switched off | recommended |
| 45 | `migrate_planning.sql` | Staff roster and leave, so a new order due on a day that is already full says so - and names the next day with room (needs steps 16 and the features step) | recommended |
| 46 | `migrate_sales.sql` | Winning the work: when a quote was chased and why one was lost, how often a customer's filters are changed (for reminders), and price changes previewed and applied once from a date (needs the quotes, quote portal, pricing and price tier steps) | recommended |
| 47 | `migrate_stock_insight.sql` | Stock you can trust: counting on the phone during a stocktake, what open orders have spoken for, what each supplier has charged, and how long each takes (needs steps 3, 40 and the more-features step) | recommended |
| 48 | `migrate_delivery_money.sql` | Out the door, and what it made: the order the van goes round in, which proof of delivery was emailed, what each order is worth, monthly sales targets, and which owner's report went out | recommended |
| 49 | `migrate_staff_board.sql` | How we do things, and talking to each other: the how-to library with "I've read this" per version, the noticeboard and group chats, and who may post, pin, start groups and take messages down | recommended |
| 50 | `migrate_direct_messages.sql` | Private messages: a conversation between any two people on staff, only they can see it - one per pair (needs step 49) | recommended |
| 51 | `migrate_cash_sales.sql` | Cash sales: the account walk-in buyers go under, whose invoices are emailed to an address asked for each time, not the one on file (needs step 39) | recommended |
| 52 | `migrate_part_links.sql` | The part number each product sells as: a code the app makes for a line (a 3-Peak bag's, say) linked to the part number in the price list and Xero | recommended |

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

### Proof of delivery and the owner's report (optional)

Two more functions on the same mail provider key - nothing new to configure
if the emails above already work:

```bash
supabase functions deploy proof-of-delivery
supabase functions deploy owner-report
```

No terminal? **Edge Functions → Deploy a new function**, once for each, with
`supabase/functions/proof-of-delivery/index.ts` and
`supabase/functions/owner-report/index.ts`. Both read their switch (Settings →
Features) on every call, so deploying them sends nothing until it is on.
The owner's report on the 1st is a pg_cron schedule, written out at the
bottom of `migrate_delivery_money.sql`; only that schedule (holding the
service-role key, from Vault) can send to every director.

### Link Xero (optional)

One connection for the whole company, made once by a manager. Staff never
sign in to Xero themselves, so Xero's two-factor sign-in is only ever asked
of that manager, once, in the browser — the app keeps the connection alive
from then on.

It runs one of two ways:

- **Trial** (where it starts) — nothing goes to Xero by itself. On an order
  (View Order, or Previous Orders → Order ▾): **Send to Xero & invoice
  customer** makes the invoice, approves it dated today, has Xero email it to
  the contact on file, and marks the order **Complete**. **Send draft to
  Xero** makes a draft to look at in Xero, with nothing sent to the customer.
- **Automatic** — once a manager presses **Publish: automatic** on the Xero
  screen. Every order raised from then on becomes a **draft** invoice in
  Xero, dated the day on the work order and kept up to date while it's a
  draft. When the job is marked **Complete** (or Dispatched) — on any PC,
  phone or screen — the invoice is dated that day, **approved**, and
  **emailed by Xero** to the contact on file, due on that contact's payment
  terms in Xero. **Back to trial** undoes it.

After **Send to Xero & invoice customer**, one PDF is put together in the
app's `invoices` folder and opened: the invoice as Xero prints it, then our
**collection slip** for an order whose Location is *Pick Up*, or **delivery
slip** for one going out (the docket - the customer's copy and the copy they
sign). Invoice several orders at once and they all go into **one PDF**,
`Invoices <date time> (<n> orders).pdf`, each invoice followed by its slip,
to print in one go; each order's own PDF is kept beside it as well.
View Order → Actions → **Invoice & packing slip (PDF)** makes it again
for an order already invoiced. (It opens for now, while it is being tried;
switching `INVOICE_PAPERWORK_PRINTS` on sends it straight to the printer.)

**Every customer in Xero.** Make a new customer and the app asks whether they
already have an account in Xero: *Yes* finds it (by their legal name, name or
short name) to link; *No* makes their contact in Xero from everything the app
has - legal name, email, contact person, ABN, phone, delivery and postal
address, payment terms - and links it; *Cancel* is not now. Pick a customer
on a new order who isn't linked and the same question comes up, once a
session for each. When a customer is linked to a contact that already
exists, anything that contact is **missing** in Xero is filled in from the
app (nothing Xero already has is changed), and their **payment terms** come
back from Xero - their own, or Xero's default when they have none - in words
like "Net 30" or "20th of the following month". **Customer ▾ → Payment terms
from Xero (everyone)** does the terms for every linked customer at once;
**Customer ▾ → Make them in Xero…** makes the selected one there.

**Cash sales** (step 51): tick *Cash sale account* on the customer walk-in
and one-off buyers go under (managers only). **Send to Xero & invoice
customer** on one of its orders then asks who to email the invoice to -
every time, offering the address already on that order - and keeps it on the
order. The invoice is the same Xero invoice and email as anybody else's: just
before Xero sends it, the cash sale contact's email in Xero is set to that
buyer's, so it never goes to whoever bought last. Cancel the question and
that order is not invoiced. An order of that account invoiced any other way
(automatic mode, say) with no email on it is approved in Xero but sent to
nobody, and says so on the Xero screen; put the email on the order and press
Retry.

Xero numbers each invoice itself, carrying on from its own sequence, and the
order number on the worksheet (the customer's purchase order) goes in the
invoice's **Reference**. Previous Orders shows each order's Xero invoice
number beside its order number (and finds an order by it).

Each line goes across at its price on the work order (or the customer's
tier price, for a line without one), worded with the **invoice wording**
(Xero screen → Invoice wording…), never the worksheet's description. A part
number Xero has no item for is made an item in Xero, so every line carries
an item code.

The Xero client secret is a function secret, and the sign-in to Xero is kept
in a table no app account can read — only the `xero` function can. Neither is
ever on a PC.

1. Run `migrate_xero_link.sql` (step 37) and `migrate_price_tiers.sql`
   (step 38).
2. At [developer.xero.com](https://developer.xero.com/app/manage) make a
   **Web app**. Its redirect URI is
   `https://<your-project>.supabase.co/functions/v1/xero`.
3. Set its details as function secrets and deploy:

   ```bash
   supabase secrets set XERO_CLIENT_ID=... XERO_CLIENT_SECRET=...
   supabase secrets set XERO_REDIRECT_URI=https://<your-project>.supabase.co/functions/v1/xero
   supabase functions deploy xero --no-verify-jwt
   ```

   `--no-verify-jwt` because Xero sends you back to the function in a
   browser; the function checks every other request itself. Optional:
   `XERO_ACCOUNT_CODE` (default `200`, Sales), `XERO_TAX_TYPE` (default
   `OUTPUT`, GST on Income), `XERO_CREATE_ITEMS=false` to stop part numbers
   being made items, and `XERO_SCOPES` to ask Xero for a different set of
   permissions.
4. A Director or Admin switches on **Xero, connected** (Settings → Features). A
   manager opens **Xero…** (under your name → Testable Features), presses
   **Connect**, signs in to Xero (with its two-factor code) and picks the
   organisation. That is the only time.

The connection asks Xero for invoices and purchase orders
(`accounting.invoices`), contacts (`accounting.contacts`) and items and
settings (`accounting.settings`) up front, so making customers and purchase
orders in Xero later won't need connecting again. These are Xero's granular
scopes: an app made since March 2026 is refused the old broad
`accounting.transactions` with `invalid_scope`.

**What it needs from Xero.** Each customer must be a contact in Xero under the
same name as in the app (its legal name, name or short name — case doesn't
matter), with the email address their invoices go to. One that isn't is
listed on the Xero screen with what to fix, and goes through by itself once
it's fixed. Part numbers that are item codes in Xero are sent as item codes;
any that aren't are made items in Xero first (a code Xero can't take — over
30 characters — goes as a plain line rather than failing the invoice).

**What holds an invoice back.** A line nothing could price goes on the draft
at $0 marked *NO PRICE*, and that invoice is not approved or emailed until the
price is on the order. A contact with no email address gets approved but not
emailed — fix it in Xero and press **Retry**. An invoice somebody approves,
voids or deletes by hand in Xero is left alone from then on. Deleting an order
takes its draft back out of Xero.

**Staying linked.** Xero ends a sign-in that isn't used for 60 days. Any PC
with the app open renews it, at least once a week, so it doesn't lapse; if it
ever does (or someone disconnects the app in Xero), the Xero screen says so
and a manager presses **Connect** again — orders taken meanwhile still go.

Once automatic, drafts are priced on a PC, because the price list and
part-number rules live in the desktop app: any PC with the app open sends
them within a few minutes, and straight away for orders it saves. Approvals go the moment a job is
marked complete; to have them go even when no PC is on, schedule the sweep
— the recipe is at the bottom of `migrate_xero_link.sql`.

### Delivery fees and Xero contacts

Run `migrate_customer_xero_delivery.sql` (step 39). Then:

- **Delivery fee** — a manager enters it on the customer card (ex GST; empty
  for none). Picking that customer on New Order fills in **Delivery Fee**,
  which only a manager can change on the order; it is added to the order's
  total and goes on the invoice (Xero and the CSV) as a **Delivery** line
  with item code `DELIVERY`. Orders entered before the fee existed, or on a
  phone, take the customer's fee when invoiced.
- **Xero contact** — Customers → Customer ▾ → **Open in Xero** opens the
  customer's contact in Xero, finding and linking it by name the first time.
  When their name in Xero is different, **Link to a Xero contact…** searches
  Xero and links the one you pick; their invoices then go to that contact.
  The customer card has the same search under **Xero**: type part of their
  name, pick them from the list, and Save.

### Buying through Xero

Run `migrate_purchasing.sql` (step 40), and update the `xero` function. Then
a manager opens **Purchase orders…** (Order Supplies, or Buying…):

- **Suppliers → Pull suppliers from Xero** brings in every Xero contact
  marked as a supplier, with their email. **Change…** sets the address
  purchase orders go to and how their codes start (`FDG` for FD Greenwood).
- **Xero items → Pull items from Xero** brings in every item with what we pay
  for it. Items whose code starts with a supplier's prefix are put with that
  supplier; **Supplier…** and **Stock item…** link the rest (select several
  with Ctrl-click). An item linked to a stock item goes into stock when it
  arrives.
- **Stock items** (step 42, `migrate_stock_suppliers.sql`) says where each
  stock item comes from: **Add or change a supplier…** adds a supplier with
  their code for it and, optionally, an agreed price (empty uses what Xero
  says we pay for that code); one of them can be preferred (★). Channel from
  FD Greenwood and from Air Diffusion is two suppliers on the one stock item.
  Linking a Xero item to a stock item does this for you. On Order Supplies,
  New order then fills in each stock item's preferred supplier and their
  code for it.
- **Order what is low…** makes a purchase order for everything below its
  minimum — what is already on order counted — to each item's preferred
  supplier, with their codes and prices filled in, ready to check and send.
- **Make purchase order…** (Order Supplies, with requests selected) makes one
  purchase order per supplier. A request's size is matched to the supplier's
  item code (45mm channel → `FDG-C45-…`); a size with no code of its own is
  priced from the sizes either side (a 47 between the 45 and the 50) and
  marked *estimated* in orange to check. Prices and lines can be changed
  before it goes.
- **Approve & send to supplier** makes the purchase order in Xero, approved
  (Xero numbers it), and emails Xero's own PDF of it to the supplier from the
  company's Gmail — the address on the order, or the supplier's email in
  Xero. Xero's API can email an invoice but not a purchase order, so the app
  sends it; the supplier gets the same PDF, from your address, and it is in
  that account's Sent folder. Without Gmail set up, the order is opened in
  Xero to press **Email** there. **Open in Xero** opens one again later. The
  requests on it show the PO number.
- **What arrived…** ticks off how many of each line came. Lines linked to a
  stock item are booked into stock; when everything is in, the order and its
  requests are received, otherwise it is *Part received*.

**Sending purchase orders from Gmail** (Google Workspace):

1. Sign in to Google as the account POs should come from (e.g. orders@…).
   2-Step Verification must be on for it (Google Account → Security).
2. Go to <https://myaccount.google.com/apppasswords>, make an app password
   called "TAF Order Entry", and copy the 16 letters. (If the page says app
   passwords are not available, a Workspace admin turns them on under Admin
   console → Security → Authentication → 2-Step Verification.)
3. In Supabase → Edge Functions → Secrets add `GMAIL_USER` (that address) and
   `GMAIL_APP_PASSWORD` (the 16 letters). The password stays in Supabase; it
   is never on a PC or in the installer.

Optional function secrets: `XERO_PURCHASE_ACCOUNT` (default `310`, Cost of Goods Sold) and
`XERO_PURCHASE_TAX` (default `INPUT`). To have the app email purchase orders
itself instead of Xero, set `PO_EMAIL_VIA=app` with `RESEND_API_KEY` and
`MAIL_FROM` (optionally `MAIL_REPLY_TO` and `COMPANY_NAME`).

### The part number each product sells as

The app makes a code for every line from its type, media and size - a full
long G4 3-Peak bag is `3PG4-610610570`, an F7 8-pocket MPHE
`MPHE-F78P595595560`. When that is the part number in your price list (and
Xero), the line is priced as it is. When it is not, link it once (step 52):

- **Products → 🔗 Part numbers…** lists every standard bag and roll in each
  media, and every code used on an order, under *Not in the price list -
  link these*, *Linked to a part number* and *Already in the price list as
  they are*. A manager double-clicks one and picks the part it sells as
  from the price list (or takes the link off).
- On a bag line, under its part number, the dialog says what it sells as
  and at what price - or that it is not in the price list, with *Link to a
  part number…* right there for a manager.

From then on every line with that code is priced, costed and sent to Xero as
the linked part. The worksheet keeps the code the floor knows.

**Anything else you sell** - clips, gaskets, a bought-in filter, a part -
goes on the price list as a product (**Products → ＋ Add Product**: part
number, name, price for each tier, cost) and onto an order from **New Order
→ ＋ Add Line → From the price list…**: search by part number or name, pick
it, and it comes at the customer's tier price. A manager who can't find it
presses **＋ New product…** right there, adds it to Products, and it goes on
the line. Those lines print on the docket with the bags (quantity,
description and P/N) - never on the filter worksheet - and are invoiced in
Xero under their part number. Quotes have had the same line all along; a
quote's product lines now print on the docket too when it becomes an order.

### Price tiers

Run `migrate_price_tiers.sql` (step 38). Then:

- **Customers** — a manager sets each customer's **Price tier** (Tier 1, 2
  or 3) on the customer card. Everyone starts on Tier 1. Only a manager can
  change it; the database refuses anyone else.
- **Products and rates** — each has a Tier 1 price (the price it always had)
  and optional Tier 2 and Tier 3 prices; an empty one charges the Tier 1
  price. Edit them on Products, or import them: a price file with columns
  headed *Tier 1*, *Tier 2* and *Tier 3* (or *Tier 2 Price* and so on
  beside the usual price column) fills all three.
- **The work order** — each line shows **Unit $** and **Line $**, filled in
  from the customer's tier as lines are added and when the customer changes.
  Type a price on a line (its *Price & invoice* box) to set it by hand; it is
  marked ✎ and stays as typed. A price agreed with one customer (Per-customer
  pricing) wins over their tier. Unit $ and Line $ can also be typed
  straight into the table (double-click the cell; a line total sets the
  price each from it). The order's total ex GST is above the lines. None of
  it is printed on the worksheets.

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

**The CSV and the link.** The CSV import needs no app registration and no
stored credentials, and Xero previews the whole batch before creating
anything: import it under **Business → Invoices → Import**, and check the
account code and tax rate on the preview. It keeps working whether or not Xero
is linked — it is what you fall back to on the afternoon Xero is down. Once
Xero is linked (below), orders go across by themselves and you will rarely
need it.

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

### Weights, packing and delivery labels (recommended)

Run step 33. Then, under Settings → How the workshop cuts → **Open weights
and packing…** (managers change these; everyone sees them):

- **Company** — the base address every delivery label prints as From.
  Starts as Unit 1/19 Tradelink Road, Hillcrest Queensland 4118 Australia.
  Changing it changes every label generated afterwards, old orders included.
- **Wire and media** — filled in from the supplied stock. LARGE_WIRE (25 ×
  25 mesh, 1.24 mm, 1200 × 30000 mm roll, 24.87 kg) and SMALL_WIRE (12 × 12,
  0.80 mm, 19.30 kg) are 0.6908… and 0.5361… kg/m². WASHABLE 0.240, F5 0.350,
  G4 0.300, "180" 0.180 and GREY 0.150 kg/m² come from their stock mass and
  area. BLACK has never been weighed, so it follows GREY (9.45 kg for its
  63 m² is derived, not measured) until a weighed BLACK roll is entered.
- **Packing** — the wrapping's own weight (until it is confirmed, label
  weights stay blank to be written in), whether calculated label weights are
  rounded up to 0.1 kg, and handling limits by size.
- **Frames and braces** — what one metre of each thickness of steel
  channel weighs (e.g. `25 = 0.62`), the flyscreen frame per metre, and one
  brace with its fixings. A frame's channel is worked out from its size:
  every side 2 mm under, plus the two 20 mm lips of a U and its cap.
- **Steel, Wire choice, Cut profiles, Mounting frames** —
  verified numbers only. Every change is a new version kept in
  `calc_settings_history`, and every calculation says which versions it used.

**What is reused.** The worksheet's own wire and media formulas — the ones
printed on every sheet for years — are the built-in cut profiles: flat panels
(wire 10 mm under each side, two pieces; media at the filter size), V-forms at
30–60, 65–80 and 85–100 mm deep (wire 15 or 10 mm under the short side by
1.36, 1.55 or 1.785 × the long side, two pieces; media 60 and 40 mm over the
wire), and flyscreens (media 20 mm over each side). The worksheet's columns now
read from these same profiles; their printed values are unchanged. The
existing mounting-frame sizes (610 × 610 and every compressor-pack frame) are
listed for profiles to be entered against.

**Nothing has to be entered first.** Every filter is weighed from what TAF
supplied: the wire and media rates, the worksheet's own wire and media cuts
(which stay in the filter whole), large wire for flat panels and headers, and
V-forms by depth (30–60 small, 65–110 large, 115+ small; a depth between the
bands, or past the worksheet's, takes the nearest band's wire and cut). The
wrapping counts as 0 kg until it is weighed. So every line is packed by weight
(10 kg a wrap) and the handling limits, and every label prints with its weight.

A line that cannot be weighed at all — a bag, a catalogue item — is wrapped
five at a time and its labels leave the weight to write in.

Anything entered later is added in, never needed first: the steel channel's kg
per metre and brace weights (Frames and braces), the flyscreen frame, the
wrapping's weight (Packing), mounting-frame profiles. A manager who would
rather hold weights back until the frame is entered can make it required in
`required_components`.

Measured cut pieces and measured wrap weights can be entered at any time
(View Order → Actions → Packing and weights → Weight calculator / Record
weight) and are used exactly as entered.

### C-channel

One calculator (`taf_order_app/cchannel.py`, with the same arithmetic in
`docs/app/calc.js` for the web app and the API) answers for frames, stock,
delivery labels and the weight table.

**The channel.** G2 Z275 galvanised steel, 0.55 mm, 7850 kg/m³, 2440 mm
lengths, 23 mm flanges — all editable (Settings → Open weights and packing →
C-channel), each change versioned. Material code `C_CHANNEL_G2_Z275_055`.

**Centre widths.** TAF's measured channels (13, 18, 22, 28, 33, 38, 44, 48,
53, 58, 63, 68, 74, 78, 84, 89, 94, 98 mm) are matched in order to nominal
depths 15–100. That matching is inferred from the sequence, so they show as
*Supplied, unconfirmed* until a manager marks them verified. Every other depth
is *Estimated* at depth less 2 mm (10 mm is a *Provisional estimate* of 10 mm).
A verified width always wins; nothing estimated is ever shown as verified.

**The weight.** `(left + centre + right flange) × length × thickness ×
density / 1e9` — 23 × 44 × 23 × 2440 at 0.55 mm is 0.948123 kg. That is base
steel: the Z275 zinc is only added once the steel's base-metal thickness is
entered (or the 0.55 is marked as coated), so it is never counted twice. A
verified measured weight for a profile is used instead of the sum, and every
result says which it is. Bend corrections and a calibration factor are
optional settings.

**Stacks and packages** are worked out from the unrounded weight of one
length and rounded up to the next 0.1 kg once, at the end: 1.0, 1.9, 4.8 and
9.5 kg for 1, 2, 5 and 10 of the 45 mm channel.

**Frames.** A filter does not take a whole length: its frame weighs the
strips the filter calculator cuts — a U's strip and cap, a G's one strip, an
L's two — at the channel for its depth. The rest of the length is offcut, not
filter. Corner notches and trimmed lip flanges are not deducted (their size
is not confirmed), so a frame weight errs heavy. Flat panels, headers and
V-forms are weighed this way automatically; a kg-per-metre entered under
Frames and braces overrides it for that thickness.

**Orders and labels.** Each line's weight is kept with the order when it is
generated, with the settings versions it came from, so changing a setting
later does not change a label reprinted for an old order. Order lines selling
channel ("Channel", "CH45", "45mm channel 2440") are weighed by the length and
labelled by what they are; anything that cannot be weighed is labelled by its
description with the weight left to write in.

**Still to confirm:** which nominal depth each measured width belongs to;
centre widths for 105–250 mm and 10 mm; whether 0.55 mm is base-metal or
coated thickness; and the size of the corner notches and lip trims.

**For other programs**: `supabase functions deploy filter-calculator`, then
`POST /functions/v1/filter-calculator` with a signed-in staff token and a body
such as `{"action": "calculate", "item": {...order line...}}`,
`{"action": "pack", "quantity": 60, "width_mm": 412, "height_mm": 412,
"depth_mm": 90}`, `{"action": "labels", "order": {...}}`, or the C-channel
actions `c_channel_weight`, `c_channel_table`, `c_channel_frame` and
`c_channel_stock`. The function's
header comment lists every action.

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

Updates from inside the app handle all of that themselves. The app
downloads the right image for the machine, quits, swaps the new version in
over the old one (a small script, `updater.mac_swap_script`, waits for it to
close) and reopens it — nothing to drag. A copy run straight off the disk
image or from Downloads is moved into Applications. If the copy fails the
old version is put back and the disk image is opened to drag across instead;
what happened is in `update.log` in the app's data folder.

The app's own web requests (the update check, the download, profile photos)
use certifi's certificates as well as the system's (`taf_order_app/tls.py`):
a packaged Mac app has none where OpenSSL looks, and every check failed with
`CERTIFICATE_VERIFY_FAILED`.

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
  invoice_wording.py       What each kind of filter says on a Xero invoice
  xero.py                  Talking to the xero function; the background sync
  quote_pdf.py             The quote PDF
  stock_usage.py           What an order takes out of stock
  delivery.py              Run sheets and what's ready to go out
  dockets.py               The docket a customer signs for what they got
  supplies.py              Asking for supplies, and the number on the bell
  materials.py             Wire and media rates from the weighed stock
  filter_calc.py           Cut sizes and weights; the worksheet's profiles
  bracing.py               When a filter needs a brace
  mounting_frames.py       What a 2 mm steel mounting frame weighs
  packing.py               Wraps: 10 kg, handling limits, codes, wording
  order_packing.py         Packing plans saved on order lines; wrap weights
  delivery_labels.py       The label data contract and the A4 label PDF
  worksheet_blocks.py      Wrapping Instructions and Filter Calculator text
  cchannel.py              C-channel sizes, weights, stacks, frames, stock
  calc_settings.py         The shared, versioned settings behind all of it
  customer_merge.py        Suggesting, checking and running a merge
  backup.py                The dated zip of spreadsheets
  labels.py                Barcode labels for stock, on Avery sheets
tests/                     Rule tests — `python tests/run.py`, run by CI
  smoke_gui.py             Builds every screen for real — also run by CI
  db_rules.py              Checks the database rules on a real Postgres
  web_app.py               Drives the web app in a real browser
  api_function.py          Serves the filter-calculator function and calls it
  xero_function.py         Serves the xero function against a stand-in Xero
  user_management.py       Roles & user admin
  models.py / validation.py
fonts/                     Bundled Public Sans (OFL)
price_lists/               The priced catalogue (import under Settings)
*.sql                      Schema + migrations
docs/phone/index.html      The page phones open (served by GitHub Pages)
docs/app/                  The staff web app — orders, scanning, works offline
docs/app/calc.js           The calculator for the web app and the API (kept
                           answer-for-answer with the Python by a test)
docs/sw.js                 Keeps the web app on the phone with no signal
docs/quote/index.html      The quote page customers open
docs/portal/index.html     The customer portal (orders, quotes, account)
docs/company.js            Phone, email, address, hours — fill this in
supabase/functions/        Edge Functions (order reading, email, the
                           morning summary, filter-calculator)
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
python tests/db_rules.py  # runs migrations on a throwaway Postgres and tries to break them
python tests/web_app.py   # drives the web app in Chromium (needs Playwright)
python tests/api_function.py  # serves the filter-calculator function with Deno
python tests/xero_function.py # the xero function, an order from draft to emailed
```

`tests/test_calc_parity.py` (part of `run.py`) sends the same requests through
the Python and the JavaScript calculators and compares every field of every
answer; it needs Node, which CI provides.

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
- **Start-up and speed:** the window is built in about a tenth of a second.
  Nothing slow happens before it appears: the database connects in the
  background while the sign-in screen is drawn, the one-off table check is
  remembered once it passes, the logos are shipped at screen size, Excel and
  Word are no longer started at boot, openpyxl and python-docx load on first
  use, the other tabs are built one at a time after the window is up, and the
  profile photo loads in the background (cached on disk). The audit log is
  written by a background thread. Search boxes wait for typing to pause.
  The build is not UPX-compressed.
- **Staying signed in:** the sign-in token lasts an hour and the database
  library renews it on one timer that gives up after a failed attempt or
  two (asleep, offline), after which every request failed "JWT expired"
  until you signed in again. `taf_order_app/db_session.py` wraps where every
  database request is sent: it renews the token when under five minutes
  are left, renews and resends once on an expired-token reply, resends once
  on a stale connection (a write only when it cannot have arrived), and a
  watchdog renews every minute it is due until it succeeds.
- **No command prompt windows:** every program the app starts on Windows
  (PowerShell, schtasks, Word) runs hidden - `taf_order_app/quiet.py`.
- **Threads:** background work hands results back with `.after()` or by
  setting a Tk variable; either, called from a background thread, is queued
  and run on the window's thread (`_install_ui_pump`), because Tk on Windows
  can crash when touched from another thread.
