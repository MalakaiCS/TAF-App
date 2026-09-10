/*
  The screens.

  What is here mirrors the Windows app deliberately - the same words, the same
  buckets, the same order of things - because the two are used by the same
  people on the same day, and a web page that renames "Due this week" or sorts
  the list differently makes them think one of the two is wrong.

  What is NOT here is generating worksheets. Those are made by driving Excel
  and Word through COM, which runs on Windows and nowhere else, so an order's
  paperwork stays on the desktop app.
*/
"use strict";

var TAFAPP = (function () {

  var U = TAFUI, D = TAFDATA, S = TAFSYNC;
  var TABS = [
    { key: "dashboard",   label: "Today" },
    { key: "new",         label: "New order" },
    { key: "orders",      label: "Orders" },
    { key: "scan",        label: "Scan" },
    { key: "delivery",    label: "Delivery" },
    { key: "quotes",      label: "Quotes" },
    { key: "customers",   label: "Customers" },
    { key: "stock",       label: "Stock" }
  ];
  var active = "dashboard";
  var ORDERS = [];              // the loaded list, newest first
  var loadedAt = 0;
  var ordersFrom = 0;           // when the list on screen was last true
  var newVersion = false;

  /* ── Starting up ─────────────────────────────────────────────────────── */

  function start(key) {
    var signin = document.getElementById("signin");
    var app = document.getElementById("app");

    if (window.TAF) {
      TAF.logo(document.getElementById("signin-head"), "../");
      TAF.footer(document.getElementById("signin-foot"));
    }

    if (!key) {
      // Nothing the person holding the phone can do about this, so tell
      // whoever they are about to ring what to do instead of telling them.
      U.notice(document.getElementById("signin").querySelector(".card"),
        "This site has not been set up yet. Someone with access to the "
        + "GitHub repository needs to run the \"Publish the web app key\" "
        + "action once. Until then, opening it from the desktop app "
        + "(your name, top right → Open on a phone) also works.");
      document.getElementById("signin-form").classList.add("hidden");
      return;
    }

    document.getElementById("signin-form")
      .addEventListener("submit", function (e) {
        e.preventDefault();
        doSignIn();
      });
    document.getElementById("signout")
      .addEventListener("click", function () {
        // Work waiting on the phone belongs to whoever did it. Handing the
        // phone on with somebody else's ticks still queued would send them
        // under the next person's account, so this stops here.
        if (S.pending()) { leaving(); return; }
        stopCamera();
        D.signOut().then(function () { location.reload(); });
      });

    if (D.signedIn()) {
      // A remembered session might have expired overnight. Ask the database
      // who we are rather than trusting what is in storage.
      D.profile(true).then(function (p) {
        if (p && p.id) { showApp(); }
        else { showSignIn(); }
      }).catch(showSignIn);
    } else {
      showSignIn();
    }

    function showSignIn() { signin.classList.remove("hidden"); }
    function showApp() {
      signin.classList.add("hidden");
      app.classList.remove("hidden");
      buildTabs();
      whoBar();
      S.onChange(stateBar);
      S.start();
      stateBar();
      show(active);
    }
    start._showApp = showApp;
  }

  /* ── The bar under the tabs ──────────────────────────────────────────
     Three things it can have to say, and it says the most pressing one:
     something did not save, there is no signal, or there is a new version
     sitting on the phone waiting for a reload. Nothing to say and it is not
     there at all - a permanent status bar becomes wallpaper within a day. */

  function stateBar() {
    var bar = document.getElementById("state");
    if (!bar) { return; }
    U.clear(bar);
    bar.className = "";

    var bad = S.failed(), n = S.pending(), off = !S.online();
    var text = "", act = null;

    if (bad.length) {
      bar.classList.add("bad");
      text = bad.length + (bad.length === 1 ? " change was" : " changes were")
           + " not saved";
      act = ["See what", function () { outbox(); }];
    } else if (n) {
      text = n + (n === 1 ? " change waiting" : " changes waiting")
           + (off ? " · no signal" : " to send");
      act = off ? ["See what", function () { outbox(); }]
                : ["Send now", function () { S.flush().then(stateBar); }];
    } else if (off) {
      text = "No signal. You can carry on — what you do is kept and sent "
           + "when it comes back.";
    } else if (newVersion) {
      bar.classList.add("new");
      text = "There is a newer version of this app on the phone.";
      act = ["Reload", function () { location.reload(); }];
    } else {
      bar.classList.add("hidden");
      return;
    }

    bar.appendChild(U.el("span", { cls: "grow", text: text }));
    if (act) {
      bar.appendChild(U.el("button", {
        text: act[0], attr: { type: "button" },
        on: { click: function (e) { e.stopPropagation(); act[1](); } }
      }));
    }
    bar.onclick = function () { outbox(); };
  }

  function updateReady() { newVersion = true; stateBar(); }

  function leaving() {
    U.openSheet(function (body, close) {
      var n = S.pending();
      body.appendChild(U.el("h2", { cls: "title", text: "Not sent yet" }));
      body.appendChild(U.el("div", {
        text: n + (n === 1 ? " change has" : " changes have") + " not reached "
            + "the database. They are yours, under your account — if you "
            + "sign out and somebody else signs in on this phone, they "
            + "cannot be sent."
      }));
      body.appendChild(U.el("div", { cls: "row-actions", kids: [
        U.button("Send them now", function () {
          U.notice(body, "Sending…", "ok");
          S.flush().then(function (out) {
            stateBar();
            if (out.kept) {
              U.notice(body, out.kept + " still will not go. There is no "
                           + "signal — stay signed in until there is.");
              return;
            }
            U.closeAllSheets();
            D.signOut().then(function () { location.reload(); });
          }).catch(function (err) { U.notice(body, err.message); });
        }, "go"),
        U.button("Stay signed in", close, "quiet"),
        U.button("Throw them away", function () {
          if (!window.confirm("Throw away " + n + " unsent "
                + (n === 1 ? "change" : "changes") + "? They will not "
                + "happen at all.")) { return; }
          S.discard();
          U.closeAllSheets();
          D.signOut().then(function () { location.reload(); });
        }, "quiet")
      ] }));
    });
  }

  /* What is actually waiting, and what went wrong with anything that failed.
     A number in a bar is not enough to act on: somebody has to be able to
     see that it was the tick on Bells Creek that the database refused. */
  function outbox() {
    U.openSheet(function (body, close) {
      body.appendChild(U.el("h2", { cls: "title", text: "Waiting to send" }));

      var bad = S.failed();
      if (bad.length) {
        body.appendChild(U.card("Not saved", [
          U.table(["What", "Why"], bad.map(function (f) {
            return U.el("tr", { kids: [U.cell(f.label), U.cell(f.why)] });
          })),
          U.el("div", { cls: "muted",
            text: "These were refused by the database, so they did not "
                + "happen. Do them again, or ask a manager why." }),
          U.el("div", { cls: "row-actions", kids: [
            U.button("Clear the list", function () {
              S.forget(); U.closeSheet(); outbox();
            }, "quiet")] })
        ]));
      }

      var queue = S.waiting();
      body.appendChild(U.card("Queued (" + queue.length + ")",
        queue.length
          ? [U.table(["What", "When"], queue.map(function (j) {
              return U.el("tr", {
                kids: [U.cell(j.label || j.rpc),
                       U.cell(String(j.at || "").replace("T", " ").slice(0, 16))]
              });
            }))]
          : [U.empty("Nothing is waiting.",
                     "Everything you have done has gone through.")]));

      body.appendChild(U.el("div", { cls: "row-actions", kids: [
        queue.length
          ? U.button("Try sending now", function () {
              U.notice(body, "Sending…", "ok");
              S.flush().then(function (out) {
                stateBar();
                U.notice(body, out.kept
                  ? out.kept + " still waiting."
                  : "All sent.", out.kept ? "err" : "ok");
              }).catch(function (err) { U.notice(body, err.message); });
            }, "go")
          : null,
        U.button("Close", close, "quiet")
      ].filter(Boolean) }));
    });
  }

  function doSignIn() {
    var box = document.getElementById("signin").querySelector(".card");
    var go = document.getElementById("signin-go");
    var email = document.getElementById("email").value.trim();
    var password = document.getElementById("password").value;
    U.notice(box, "");
    go.disabled = true;
    go.textContent = "Signing in…";
    D.signIn(email, password).then(function (p) {
      // The desktop app checks this too. Somebody who has registered but not
      // been approved must not get in, and must be told why rather than
      // being shown an empty app.
      if (p && p.approved === false) {
        throw new Error("Your account is waiting to be approved. Ask a "
                        + "manager to approve it.");
      }
      document.getElementById("password").value = "";
      start._showApp();
    }).catch(function (err) {
      U.notice(box, err.message || "Could not sign in.");
    }).then(function () {
      go.disabled = false;
      go.textContent = "Sign in";
    });
  }

  function whoBar() {
    var p = D.cachedProfile();
    document.getElementById("who-name").textContent =
      p.full_name || p.username || D.whoami().email || "Signed in";
    document.getElementById("who-role").textContent = p.role || "";
  }

  function buildTabs() {
    var nav = U.clear(document.getElementById("tabs"));
    TABS.forEach(function (t) {
      nav.appendChild(U.el("button", {
        text: t.label,
        attr: { role: "tab", "aria-selected": String(t.key === active),
                "data-tab": t.key },
        on: { click: function () { show(t.key); } }
      }));
    });
  }

  function show(key) {
    // Leaving the Scan tab has to put the camera down. Clearing the screen
    // removes the picture but not the stream: the light on the back of the
    // phone stays on, and so does the battery drain.
    if (active === "scan" && key !== "scan") { stopCamera(); }
    active = key;
    buildTabs();
    var main = U.clear(document.getElementById("screen"));
    var draw = SCREENS[key];
    if (!draw) { return; }
    main.appendChild(U.el("div", { cls: "muted", text: "Loading…" }));
    draw(main);
  }

  /* ── Orders, loaded once and reused ──────────────────────────────────── */

  function loadOrders(force) {
    var fresh = (Date.now() - loadedAt) < 60000;
    if (ORDERS.length && fresh && !force) { return Promise.resolve(ORDERS); }
    // orders_list leaves the line items in the database - it is a list, and
    // the lines are the bulk of an order. n_made rides along beside n_items
    // so "3/8" costs nothing.
    return D.select("orders_list", {
      "select": "*", "archived": "eq.false",
      "order": "created_at.desc", "limit": 1000
    }).then(function (rows) {
      return settle(rows);
    }).catch(function (err) {
      // A project without migrate_performance.sql has no orders_list view.
      if (/not there any more|does not exist|relation/i.test(err.message || "")) {
        return D.select("orders", {
          "select": "id,customer_name,order_number,date_ordered,date_due,"
                  + "header,order_type,created_at,archived,full_name",
          "archived": "eq.false", "order": "created_at.desc", "limit": 1000
        }).then(settle);
      }
      // No signal. Whatever this phone was last shown is better than a blank
      // screen, as long as nobody is left thinking it is today's list - so
      // ordersFrom is set and every screen drawn from it says when it is
      // from. The 300 is a phone's storage, not a judgement about how many
      // orders matter: the list is newest first.
      if (err && err.offline) {
        var box = S.recall("orders");
        if (box) {
          ORDERS = box.v.map(shapeOrder);
          loadedAt = Date.now();
          ordersFrom = box.at;
          return ORDERS;
        }
      }
      throw err;
    });

    function settle(rows) {
      ORDERS = rows.map(shapeOrder);
      loadedAt = Date.now();
      ordersFrom = 0;
      S.remember("orders", rows.slice(0, 300));
      return ORDERS;
    }
  }

  /* A list that has to be usable with no signal. Fetched when it can be and
     remembered afterwards; out of range, the remembered copy is handed back
     with the time it was taken, so the screen can say so. */
  function loadKept(key, get) {
    return get().then(function (rows) {
      S.remember(key, rows.slice(0, 400));
      return { rows: rows, at: 0 };
    }).catch(function (err) {
      var box = (err && err.offline) ? S.recall(key) : null;
      if (box) { return { rows: box.v, at: box.at }; }
      throw err;
    });
  }

  /* Said once, the same way, wherever a list might be a remembered one. */
  function staleNote(at) {
    if (!at) { return null; }
    return U.el("div", {
      cls: "err",
      text: "No signal. This is what the phone last saw, " + S.since(at)
          + " — it may have moved on since."
    });
  }

  function shapeOrder(row) {
    var header = row.header || {};
    return {
      id: row.id,
      customer: row.customer_name || header["Customer Name"] || "",
      order_no: row.order_number || header["Order Number"] || "",
      date_ordered: row.date_ordered || header["Date Ordered"] || "",
      date_due: row.date_due || header["Date Due"] || "",
      status: header.status || "Pending",
      priority: !!header.priority,
      job: header["Job"] || "",
      location: header["Location"] || "",
      n_items: row.n_items,
      n_made: row.n_made,
      created_by: row.full_name || "",
      header: header
    };
  }

  /* How far along, in the width of a column. Same rule as the desktop:
     nothing started reads as the plain count it always did. */
  function progressCell(total, made) {
    total = total || 0;
    if (!total || made === null || made === undefined) { return String(total); }
    if (made <= 0) { return String(total); }
    if (made >= total) { return "✓ " + total; }
    return made + "/" + total;
  }

  /* ── Screens ─────────────────────────────────────────────────────────── */

  var SCREENS = {};

  SCREENS.dashboard = function (main) {
    loadOrders().then(function (rows) {
      U.clear(main);
      var stale = staleNote(ordersFrom);
      if (stale) { main.appendChild(stale); }
      var counts = { overdue: 0, today: 0, week: 0 };
      rows.forEach(function (r) {
        var b = U.dueBucket(r);
        if (counts[b] !== undefined) { counts[b] += 1; }
      });
      var ready = rows.filter(function (r) {
        return r.status === "Complete";
      }).length;

      var tiles = [
        ["Overdue", counts.overdue, "overdue"],
        ["Due today", counts.today, "today"],
        ["Due this week", counts.overdue + counts.today + counts.week, "week"],
        ["Ready to go out", ready, "ready"]
      ];
      var grid = U.el("div", {
        attr: { style: "display:grid;gap:10px;"
                     + "grid-template-columns:repeat(auto-fit,minmax(150px,1fr))" }
      });
      tiles.forEach(function (t) {
        grid.appendChild(U.el("div", {
          cls: "card",
          attr: { style: "margin:0;cursor:pointer" },
          on: { click: function () { show("orders"); filterTo(t[2]); } },
          kids: [
            U.el("div", { text: String(t[1]),
                          attr: { style: "font-size:26px;font-weight:700" } }),
            U.el("div", { cls: "muted", text: t[0] })
          ]
        }));
      });
      main.appendChild(U.el("h2", { text: todayLine() }));
      main.appendChild(grid);
      main.appendChild(U.card("What is late", lateList(rows)));
    }).catch(function (err) {
      U.clear(main);
      U.notice(main, err.message);
    });
  };

  function todayLine() {
    var d = new Date();
    return d.toLocaleDateString(undefined, {
      weekday: "long", day: "numeric", month: "long" });
  }

  function lateList(rows) {
    var late = rows.filter(function (r) { return U.dueBucket(r) === "overdue"; })
                   .slice(0, 12);
    if (!late.length) { return [U.empty("Nothing is overdue.")]; }
    return [U.table(
      ["Customer", "Order #", "Due", { text: "Lines", num: true }],
      late.map(function (r) {
        return U.el("tr", {
          cls: "row late",
          on: { click: function () { openOrder(r); } },
          kids: [U.cell(r.customer), U.cell(r.order_no),
                 U.cell(r.date_due),
                 U.cell(progressCell(r.n_items, r.n_made), { num: true })]
        });
      })
    )];
  }

  var pendingFilter = "";

  function filterTo(bucket) { pendingFilter = bucket; }

  SCREENS.orders = function (main) {
    loadOrders().then(function (rows) {
      U.clear(main);
      var stale = staleNote(ordersFrom);
      if (stale) { main.appendChild(stale); }
      var search = U.el("input", {
        attr: { type: "search", placeholder: "Customer, order number or job" }
      });
      var due = U.el("select", {
        kids: ["All", "Overdue", "Due today", "Due this week", "No due date"]
          .map(function (t) { return U.el("option", { text: t }); })
      });
      var status = U.el("select", {
        kids: ["All", "Pending", "In Production", "Complete", "Dispatched"]
          .map(function (t) { return U.el("option", { text: t }); })
      });
      if (pendingFilter === "overdue") { due.value = "Overdue"; }
      else if (pendingFilter === "today") { due.value = "Due today"; }
      else if (pendingFilter === "week") { due.value = "Due this week"; }
      else if (pendingFilter === "ready") { status.value = "Complete"; }
      pendingFilter = "";

      var out = U.el("div");
      function redraw() { drawOrders(out, rows, search.value, due.value,
                                     status.value); }
      [search, due, status].forEach(function (node) {
        node.addEventListener("input", redraw);
        node.addEventListener("change", redraw);
      });

      main.appendChild(U.card(null, [
        U.el("div", { cls: "filters", kids: [
          U.el("label", { cls: "f", kids: [
            U.el("span", { text: "Search" }), search] }),
          U.el("label", { cls: "f", kids: [
            U.el("span", { text: "Due" }), due] }),
          U.el("label", { cls: "f", kids: [
            U.el("span", { text: "Status" }), status] })
        ] })
      ]));
      main.appendChild(out);
      redraw();
    }).catch(function (err) {
      U.clear(main);
      U.notice(main, err.message);
    });
  };

  function drawOrders(into, rows, query, dueFilter, statusFilter) {
    U.clear(into);
    var q = String(query || "").trim().toLowerCase();
    var list = rows.filter(function (r) {
      if (q && [r.customer, r.order_no, r.job].join(" ").toLowerCase()
               .indexOf(q) === -1) { return false; }
      if (statusFilter && statusFilter !== "All" && r.status !== statusFilter) {
        return false;
      }
      if (dueFilter && dueFilter !== "All") {
        var b = U.dueBucket(r);
        if (dueFilter === "Overdue" && b !== "overdue") { return false; }
        if (dueFilter === "Due today" && b !== "today") { return false; }
        if (dueFilter === "Due this week"
            && ["overdue", "today", "week"].indexOf(b) === -1) { return false; }
        if (dueFilter === "No due date" && b !== "none") { return false; }
      }
      return true;
    });

    if (!list.length) {
      into.appendChild(U.card(null, [U.empty(
        "No orders match", "Clear the search and the filters to see everything.")]));
      return;
    }

    into.appendChild(U.card(list.length + " order" + (list.length === 1 ? "" : "s"),
      [U.table(
        ["Customer", "Order #", "Due", "Status", { text: "Lines", num: true }],
        list.slice(0, 300).map(function (r) {
          var bucket = U.dueBucket(r);
          return U.el("tr", {
            cls: "row " + (bucket === "overdue" ? "late"
                           : bucket === "today" ? "today" : ""),
            on: { click: function () { openOrder(r); } },
            kids: [
              U.cell((r.priority ? "🚨 " : "") + r.customer),
              U.cell(r.order_no),
              U.cell((bucket === "overdue" ? "⚠ " : "") + (r.date_due || "—")),
              U.cell(null, { node: U.pill(r.status) }),
              U.cell(progressCell(r.n_items, r.n_made), { num: true })
            ]
          });
        })
      )]));
  }

  /* ── One order ───────────────────────────────────────────────────────── */

  function openOrder(row) {
    U.openSheet(function (body, close) {
      var pill = U.pill(row.status);
      body.appendChild(U.el("h2", {
        cls: "title",
        kids: [U.el("span", { text: row.customer || "Order" }), pill]
      }));
      body.appendChild(U.el("div", {
        cls: "muted",
        text: [row.order_no ? "O/N " + row.order_no : "",
               row.date_ordered ? "Ordered " + row.date_ordered : "",
               row.date_due ? "Due " + row.date_due : "",
               row.job ? "Job " + row.job : ""]
              .filter(Boolean).join("   ·   ")
      }));

      var lines = U.el("div");
      body.appendChild(lines);
      lines.appendChild(U.el("div", { cls: "muted", text: "Loading lines…" }));

      // Built now, but not put on the page until the notes are, so the
      // buttons finish the window instead of interrupting it half way down.
      var actions = U.el("div", { cls: "row-actions" });

      var files = U.el("div");
      body.appendChild(files);

      D.select("orders", { "id": "eq." + row.id, "select": "items,header" })
        .then(function (rows) {
          var order = (rows && rows[0]) || {};
          drawLines(lines, row, order.items || [], body);
          drawNotes(body, row, order.header || {});
          drawFiles(files, row, body);
          body.appendChild(actions);
          drawStatus(actions, row, body, pill, close);
        })
        .catch(function (err) {
          U.clear(lines);
          U.notice(body, err.message);
        });
    });
  }

  function drawLines(into, row, items, body) {
    U.clear(into);
    if (!items.length) {
      into.appendChild(U.card("Lines", [U.empty("No lines on this order")]));
      return;
    }
    var made = items.filter(function (i) { return i.made; }).length;
    var count = U.el("div", { cls: "muted" });

    function tally() {
      var n = items.filter(function (i) { return i.made; }).length;
      count.textContent = n === items.length
        ? "All " + items.length + " lines made"
        : n + " of " + items.length + " lines made  ·  "
          + (items.length - n) + " to go";
    }

    var rows = items.map(function (it, idx) {
      var tick = U.el("button", {
        cls: "tick", text: it.made ? "✓" : "",
        attr: { type: "button", "aria-pressed": String(!!it.made),
                "aria-label": "Mark line " + (idx + 1) + " as made" }
      });
      var tr = U.el("tr", {
        cls: it.made ? "made" : "",
        kids: [U.cell(null, { node: tick }),
               U.cell(it.Quantity || it.quantity || ""),
               U.cell(lineName(it)),
               U.cell(lineSize(it)),
               U.cell(it["Media Type"] || it.media || "")]
      });
      tick.addEventListener("click", function () {
        var want = !it.made;
        tick.disabled = true;
        // The filter is made whether or not the wifi reaches this corner of
        // the factory. Setting a line to made is the same done twice as
        // done once, so this is safe to keep and send later.
        S.send({
          rpc: "set_order_line_made",
          label: (row.customer || "Order") + " · line " + (idx + 1)
               + (want ? " made" : " not made"),
          needs_row: true,
          gone: "That line is not on the order any more.",
          body: {
            p_order_id: row.id,
            p_line_id: it.line_id || "",
            p_made: want,
            p_by: D.cachedProfile().full_name
               || D.cachedProfile().username || "",
            p_at: want ? stamp() : ""
          }
        }).then(function (out) {
          it.made = want;
          tick.textContent = want ? "✓" : "";
          tick.setAttribute("aria-pressed", String(want));
          tr.className = want ? "made" : "";
          if (out.queued) { tick.classList.add("waiting"); }
          tally();
          U.notice(body, out.queued
            ? "Kept on this phone. It will send itself when the signal is "
              + "back — you can carry on."
            : "", out.queued ? "ok" : "");
          loadedAt = 0;                 // the list's count is now stale
        }).catch(function (err) {
          U.notice(body, err.message);
        }).then(function () { tick.disabled = false; });
      });
      return tr;
    });

    into.appendChild(U.card("Lines", [
      U.table([" ", { text: "Qty" }, "Item", "Size (mm)", "Media"], rows),
      count
    ]));
    tally();
    void made;
  }

  function stamp() {
    var d = new Date();
    function two(n) { return (n < 10 ? "0" : "") + n; }
    return two(d.getDate()) + "/" + two(d.getMonth() + 1) + "/"
         + d.getFullYear() + " " + two(d.getHours()) + ":" + two(d.getMinutes());
  }

  function lineName(it) {
    var kind = it.item_kind || "filter";
    if (kind === "bag") { return it.product_type || "Bag / Roll"; }
    if (kind === "catalogue") {
      return it.Description || it["Part Number"] || "Item";
    }
    return it["Filter Type"] || "Filter";
  }

  function lineSize(it) {
    var kind = it.item_kind || "filter";
    if (kind === "bag") {
      return [it.roll_width, it.roll_length].filter(Boolean).join(" × ")
          || [it.width, it.height, it.depth].filter(Boolean).join(" × ");
    }
    if (kind === "catalogue") { return ""; }
    return [it.Short, it.Long, it.Channel].filter(Boolean).join(" × ");
  }

  /* ── Photos, and proof that it arrived ───────────────────────────────
     The same shape for both: a file against the order, with who and when.
     A photo of the plant room and a signature at the drop are the same
     thing to the database and different things to whoever looks later. */

  var FILE_BUCKET = "order-files";

  function drawFiles(into, row, body) {
    U.clear(into);
    var card = U.el("div");
    into.appendChild(card);

    function load() {
      D.select("order_files", {
        "order_id": "eq." + row.id, "select": "*",
        "order": "created_at.desc"
      }).then(function (rows) { render(rows); })
        .catch(function (err) {
          // No migration yet, or no permission. Neither is worth a red box
          // on an order somebody opened to tick a line off.
          render([], err.message);
        });
    }

    function render(rows, why) {
      U.clear(card);
      var kids = [];
      if (rows.length) {
        var grid = U.el("div", {
          attr: { style: "display:grid;gap:8px;"
                       + "grid-template-columns:repeat(auto-fill,minmax(110px,1fr))" }
        });
        rows.forEach(function (f) {
          var tile = U.el("button", {
            cls: "filetile",
            attr: { type: "button",
                    title: f.caption || f.kind },
            kids: [U.el("div", { cls: "muted", text: label(f) })]
          });
          tile.addEventListener("click", function () { openFile(f, body); });
          grid.appendChild(tile);
        });
        kids.push(grid);
      } else {
        kids.push(U.empty(why ? "No photos yet" : "Nothing kept against this order",
                          why ? "" : "Photograph the filters, the plant room "
                                   + "or the damage."));
      }
      kids.push(addRow(row, load, body));
      card.appendChild(U.card("Photos and proof (" + rows.length + ")", kids));
    }

    function label(f) {
      if (f.kind === "signature") {
        return "✍  " + (f.signed_by || "Signed");
      }
      return "📷  " + (f.caption || "Photo");
    }
    load();
  }

  function addRow(row, reload, body) {
    var wrap = U.el("div", { cls: "row-actions" });

    // A file input rather than getUserMedia: on a phone this opens the
    // camera, and on a PC it opens the file picker, which is what each of
    // them wants without asking which one is being used.
    var pick = U.el("input", {
      attr: { type: "file", accept: "image/*", capture: "environment",
              style: "display:none" }
    });
    pick.addEventListener("change", function () {
      var file = pick.files && pick.files[0];
      if (!file) { return; }
      sendFile(row, file, "photo", "", "", body).then(function (ok) {
        if (ok) { reload(); }
      });
      pick.value = "";
    });
    wrap.appendChild(pick);
    wrap.appendChild(U.button("📷  Add a photo", function () { pick.click(); },
                              "quiet"));
    wrap.appendChild(U.button("✍  Signed for", function () {
      signFor(row, reload, body);
    }, "quiet"));
    return wrap;
  }

  /* Returns a promise, because the caller has to be able to wait. Closing a
     signature pad before the upload lands would send the order underneath
     off to redraw itself from a database that does not have the file yet,
     and the signature somebody just took would not be there. */
  function sendFile(row, blob, kind, caption, signedBy, body) {
    var ext = kind === "signature" ? "png"
            : ((blob.type || "").split("/")[1] || "jpg").split("+")[0];
    var path = row.id + "/" + Date.now() + "-" + kind + "." + ext;
    U.notice(body, "Sending…", "ok");
    return D.upload(FILE_BUCKET, path, blob, blob.type).then(function () {
      return D.insert("order_files", {
        order_id: row.id, kind: kind, path: path,
        caption: caption || "", signed_by: signedBy || "",
        taken_by: D.cachedProfile().full_name
               || D.cachedProfile().username || ""
      });
    }).then(function () {
      U.notice(body, kind === "signature"
        ? "Signature kept against this order." : "Photo kept against this order.",
        "ok");
      return true;
    }).catch(function (err) {
      U.notice(body, err.message);
      return false;
    });
  }

  function openFile(f, body) {
    D.signedUrl(FILE_BUCKET, f.path, 3600).then(function (url) {
      if (!url) { throw new Error("That file could not be opened."); }
      U.openSheet(function (inner, closeInner) {
        inner.appendChild(U.el("h2", {
          text: f.kind === "signature"
            ? "Signed by " + (f.signed_by || "—") : (f.caption || "Photo") }));
        inner.appendChild(U.el("div", { cls: "muted",
          text: [f.taken_by, (f.created_at || "").slice(0, 10)]
                .filter(Boolean).join(" · ") }));
        inner.appendChild(U.el("img", {
          attr: { src: url, alt: f.caption || f.kind,
                  style: "width:100%;border-radius:10px;margin-top:10px;"
                       + "background:#fff" } }));
        inner.appendChild(U.el("div", { cls: "row-actions",
          kids: [U.button("Close", closeInner, "quiet")] }));
      });
    }).catch(function (err) { U.notice(body, err.message); });
  }

  /* A signature drawn with a finger. The run sheet has had a column for one
     for years; it just went back to the office in a ute. */
  function signFor(row, reload, body) {
    U.openSheet(function (inner, closeInner) {
      inner.appendChild(U.el("h2", { text: "Signed for" }));
      inner.appendChild(U.el("div", { cls: "muted",
        text: "Have them sign below, and put their name to it." }));

      var who = U.el("input", { attr: { type: "text",
                                        placeholder: "Their name" } });
      inner.appendChild(U.el("label", { cls: "f", kids: [
        U.el("span", { text: "Name" }), who] }));

      var pad = U.el("canvas", {
        attr: { width: "600", height: "260",
                style: "width:100%;height:200px;background:#fff;"
                     + "border:1px solid var(--line);border-radius:10px;"
                     + "touch-action:none" } });
      inner.appendChild(pad);
      var ctx = pad.getContext("2d");
      ctx.lineWidth = 3; ctx.lineCap = "round"; ctx.strokeStyle = "#1F2933";
      var drawing = false, drew = false;

      function at(e) {
        var r = pad.getBoundingClientRect();
        var p = e.touches ? e.touches[0] : e;
        return { x: (p.clientX - r.left) * (pad.width / r.width),
                 y: (p.clientY - r.top) * (pad.height / r.height) };
      }
      function down(e) { e.preventDefault(); drawing = true; drew = true;
                         var p = at(e); ctx.beginPath(); ctx.moveTo(p.x, p.y); }
      function move(e) { if (!drawing) { return; } e.preventDefault();
                         var p = at(e); ctx.lineTo(p.x, p.y); ctx.stroke(); }
      function up() { drawing = false; }
      ["mousedown", "touchstart"].forEach(function (n) {
        pad.addEventListener(n, down, { passive: false }); });
      ["mousemove", "touchmove"].forEach(function (n) {
        pad.addEventListener(n, move, { passive: false }); });
      ["mouseup", "mouseleave", "touchend"].forEach(function (n) {
        pad.addEventListener(n, up); });

      inner.appendChild(U.el("div", { cls: "row-actions", kids: [
        U.button("Keep it", function () {
          if (!drew) {
            U.notice(inner, "Nothing has been signed yet.");
            return;
          }
          if (!who.value.trim()) {
            U.notice(inner, "Whose signature is it?");
            return;
          }
          pad.toBlob(function (blob) {
            sendFile(row, blob, "signature", "", who.value.trim(), inner)
              .then(function (ok) {
                // Only step back to the order once it is actually saved, so
                // the order redraws from a database that has it.
                if (ok) { closeInner(); }
              });
          }, "image/png");
        }, "go"),
        U.button("Clear", function () {
          ctx.clearRect(0, 0, pad.width, pad.height); drew = false;
        }, "quiet"),
        U.button("Cancel", closeInner, "quiet")
      ] }));
    });
  }

  function drawNotes(body, row, header) {
    var notes = header.order_notes || [];
    if (typeof notes === "string") {
      notes = notes ? [{ ts: "", author: "", text: notes }] : [];
    }
    var list = U.el("div");
    notes.forEach(function (n) {
      list.appendChild(U.el("div", {
        attr: { style: "border-bottom:1px solid var(--line);padding:8px 0" },
        kids: [
          U.el("div", { text: n.text || "" }),
          U.el("div", { cls: "muted",
                        text: [n.author, n.ts].filter(Boolean).join(" · ") })
        ]
      }));
    });
    if (!notes.length) { list.appendChild(U.empty("Nothing noted yet.")); }
    body.appendChild(U.card("Notes (" + notes.length + ")", [list]));
  }

  /* Redrawn after every change, so the window shows the result rather than
     the state it opened with — the same rule the desktop's View Order
     follows. Leaving "Complete" on offer after an order has been completed
     is how somebody presses it twice and wonders which one took. */
  function drawStatus(actions, row, body, pill, close) {
    U.clear(actions);
    ["In Production", "Complete", "Dispatched"].forEach(function (want) {
      if (row.status === want) { return; }
      actions.appendChild(U.button(want, function () {
        // merge_order_header patches the header rather than writing a whole
        // one back, so the same patch arriving twice leaves the same status
        // and nobody's notes are lost on the way.
        S.send({
          rpc: "merge_order_header",
          label: (row.customer || "Order") + " → " + want,
          needs_row: true,
          gone: "That order is not there any more.",
          body: { p_order_id: row.id, p_patch: { status: want } }
        }).then(function (out) {
          row.status = want;
          pill.className = "pill s-" + want.replace(/\s+/g, "");
          pill.textContent = want;
          loadedAt = 0;
          drawStatus(actions, row, body, pill, close);
          U.notice(body, out.queued
            ? "Set to " + want + " on this phone, and waiting for signal."
            : "Status set to " + want + ".", "ok");
        }).catch(function (err) { U.notice(body, err.message); });
      }, want === "Complete" ? "go" : "quiet"));
    });
    actions.appendChild(U.button("Close", close, "quiet"));
  }

  /* ── Scanning ────────────────────────────────────────────────────────
     The barcodes are the ones the desktop app already prints: Code 128 on a
     worksheet and on a rack label. One place decides what a code means -
     resolve_scan, in the database - so a phone, a handheld gun and the
     desktop can never disagree about which order PO-8842 is.

     Two ways in, because a factory has both. The camera, where the browser
     can read one; and a plain text box, which is what a Zebra handheld in
     keyboard mode types into anyway - it sends the digits and an Enter, so
     the box below works with a gun without knowing a gun exists. That box is
     also the answer on any browser without BarcodeDetector, which today
     means every iPhone. */

  var SCAN = { stop: null, last: "", at: 0, recent: [] };

  SCREENS.scan = function (main) {
    U.clear(main);
    var out = U.el("div", { attr: { id: "scans" } });

    var box = U.el("div", { cls: "scanbox hidden", kids: [
      U.el("video", { attr: { playsinline: "", muted: "", autoplay: "" } }),
      U.el("div", { cls: "reticle" })
    ] });
    var camMsg = U.el("div", { cls: "muted" });
    var camBtn = U.button("📷  Use the camera", function () {
      if (SCAN.stop) { stopCamera(); camBtn.textContent = "📷  Use the camera"; }
      else {
        camBtn.textContent = "Stop the camera";
        startCamera(box, camMsg, function (code) { lookUp(code, out); });
      }
    });

    var typed = U.el("input", {
      attr: { type: "text", autocapitalize: "characters", autocorrect: "off",
              spellcheck: "false", placeholder: "e.g. PO-8842 or MED-G4-1M" },
      cls: "code"
    });
    var form = U.el("form", { on: { submit: function (e) {
      e.preventDefault();
      lookUp(typed.value, out);
      typed.value = "";
      typed.focus();
    } } });
    form.appendChild(U.el("label", { cls: "f", kids: [
      U.el("span", { text: "Code" }), typed] }));
    form.appendChild(U.el("div", { cls: "row-actions", kids: [
      U.el("button", { cls: "btn", text: "Look it up",
                       attr: { type: "submit" } })] }));

    main.appendChild(U.card("Point it at a code", [box, camMsg,
      U.el("div", { cls: "row-actions", kids: [camBtn] })]));
    main.appendChild(U.card("Or type it in", [form,
      U.el("div", { cls: "muted",
        text: "A handheld scanner types into this box on its own — tap it "
            + "once so it has the cursor, then scan." })]));
    main.appendChild(out);
    drawRecent(out);
    if (!window.BarcodeDetector) {
      camMsg.textContent = "This browser cannot read a barcode through the "
        + "camera, so type the code in below or use a handheld scanner.";
      camBtn.disabled = true;
    }
    typed.focus();
  };

  function startCamera(box, msg, found) {
    var Detector = window.BarcodeDetector;
    if (!Detector) { return; }
    msg.textContent = "Opening the camera…";
    var media = navigator.mediaDevices;
    if (!media || !media.getUserMedia) {
      msg.textContent = "This browser will not hand over the camera. Type "
                      + "the code in instead.";
      return;
    }
    media.getUserMedia({ video: { facingMode: { ideal: "environment" } } })
      .then(function (stream) {
        var video = box.querySelector("video");
        video.srcObject = stream;
        box.classList.remove("hidden");
        msg.textContent = "Hold the code inside the box.";
        var play = video.play();
        if (play && play.catch) { play.catch(function () {}); }
        return formats(Detector).then(function (want) {
          var det = want.length ? new Detector({ formats: want })
                                : new Detector();
          var timer = setInterval(function () {
            det.detect(video).then(function (hits) {
              if (!hits || !hits.length) { return; }
              var code = String(hits[0].rawValue || "").trim();
              // A camera sees the same label thirty times a second. Without
              // this, one barcode becomes thirty lookups and the screen
              // never settles long enough to read.
              if (code && (code !== SCAN.last
                           || Date.now() - SCAN.at > 2500)) {
                SCAN.last = code;
                SCAN.at = Date.now();
                if (navigator.vibrate) { navigator.vibrate(40); }
                found(code);
              }
            }).catch(function () { /* a blurred frame is not an error */ });
          }, 300);
          SCAN.stop = function () {
            clearInterval(timer);
            stream.getTracks().forEach(function (t) { t.stop(); });
            video.srcObject = null;
            box.classList.add("hidden");
            SCAN.stop = null;
          };
        });
      })
      .catch(function (err) {
        msg.textContent = "The camera did not open (" + (err.message || err)
          + "). Type the code in instead.";
      });
  }

  function stopCamera() { if (SCAN.stop) { SCAN.stop(); } }

  var WANTED = ["code_128", "code_39", "qr_code", "ean_13"];

  function formats(Detector) {
    if (!Detector.getSupportedFormats) { return Promise.resolve([]); }
    return Detector.getSupportedFormats().then(function (have) {
      return WANTED.filter(function (f) { return have.indexOf(f) !== -1; });
    }).catch(function () { return []; });
  }

  /* One code in, one answer out. Out of signal it is answered from what the
     phone was last shown, which covers the two things a code is nearly
     always for - which rack this is, and which order this worksheet is. */
  function lookUp(code, into) {
    code = String(code || "").trim();
    if (!code) { return; }
    if (!S.online()) { show_(remembered(code), code, true); return; }
    D.rpc("resolve_scan", { p_code: code }).then(function (rows) {
      show_(rows && rows.length ? rows : remembered(code), code,
            !(rows && rows.length));
    }).catch(function (err) {
      if (err && err.offline) { show_(remembered(code), code, true); return; }
      U.clear(into);
      U.notice(into, err.message);
    });

    function show_(hits, forCode, fromPhone) {
      SCAN.recent = [{ code: forCode, hits: hits }]
        .concat(SCAN.recent.filter(function (r) { return r.code !== forCode; }))
        .slice(0, 8);
      drawRecent(into);
    }
  }

  function remembered(code) {
    var want = code.toUpperCase();
    var hits = [];
    var stock = S.recall("stock");
    (stock ? stock.v : []).forEach(function (s) {
      if (String(s.sku || "").trim().toUpperCase() === want) {
        hits.push({ kind: "stock", ref: s.id, label: s.name || "Stock item",
                    detail: s.location || "No location", row: s });
      }
    });
    var orders = S.recall("orders");
    (orders ? orders.v : []).forEach(function (o) {
      if (String(o.order_number || "").trim().toUpperCase() === want) {
        hits.push({ kind: "order", ref: o.id,
                    label: o.customer_name || "Order",
                    detail: (o.header && o.header.status) || "Pending",
                    row: o });
      }
    });
    return hits;
  }

  function drawRecent(into) {
    U.clear(into);
    if (!SCAN.recent.length) {
      into.appendChild(U.card(null, [U.empty("Nothing scanned yet.",
        "A code opens the rack it labels or the order it belongs to.")]));
      return;
    }
    SCAN.recent.forEach(function (r, i) {
      var kids = [];
      if (!r.hits.length) {
        kids.push(U.empty("Nothing here answers to that code.",
          S.online() ? "Check it against the label."
                     : "There is no signal, so only what this phone has "
                       + "already seen can be looked up."));
      }
      r.hits.forEach(function (h) {
        var btn = U.el("button", {
          cls: "hit", attr: { type: "button" },
          kids: [U.el("strong", { text: h.label || h.ref }),
                 U.el("span", { cls: "muted",
                                text: kindOf(h) + " · " + (h.detail || "") })]
        });
        btn.addEventListener("click", function () { openHit(h, into); });
        kids.push(btn);
      });
      into.appendChild(U.card((i ? "" : "Scanned  ") + r.code, kids));
    });
  }

  function kindOf(h) {
    if (h.kind === "stock")   { return "Stock"; }
    if (h.kind === "order")   { return "Order"; }
    if (h.kind === "product") { return "Price list"; }
    return h.kind || "";
  }

  function openHit(h, into) {
    if (h.kind === "order") {
      var known = ORDERS.filter(function (o) { return o.id === h.ref; })[0];
      if (known) { openOrder(known); return; }
      if (h.row) { openOrder(shapeOrder(h.row)); return; }
      loadOrders(true).then(function (rows) {
        var one = rows.filter(function (o) { return o.id === h.ref; })[0];
        if (one) { openOrder(one); }
        else { U.notice(into, "That order is not in the list any more."); }
      }).catch(function (err) { U.notice(into, err.message); });
      return;
    }
    if (h.kind === "stock") {
      if (h.row) { openStock(h.row, []); return; }
      D.select("stock_items", { "id": "eq." + h.ref, "select": "*" })
        .then(function (rows) {
          if (rows && rows[0]) { openStock(rows[0], rows); }
          else { U.notice(into, "That stock item is not there any more."); }
        }).catch(function (err) { U.notice(into, err.message); });
      return;
    }
    // A price-list code is a thing we sell, not a thing to open. Say what it
    // is and what it costs, which is what somebody with the label in their
    // hand is asking.
    U.openSheet(function (body, close) {
      body.appendChild(U.el("h2", { cls: "title", text: h.label || h.ref }));
      body.appendChild(U.el("div", { cls: "muted", text: h.detail || "" }));
      var price = h.extra && h.extra.unit_price;
      body.appendChild(U.card("Price list", [
        U.el("div", { attr: { style: "font-size:26px;font-weight:700" },
                      text: price ? U.money(price) : "No price set" }),
        U.el("div", { cls: "muted", text: "Part number " + (h.ref || "") })
      ]));
      body.appendChild(U.el("div", { cls: "row-actions",
        kids: [U.button("Close", close, "quiet")] }));
    });
  }

  /* ── Raising an order ────────────────────────────────────────────────
     This saves the dimensions somebody typed and nothing worked out from
     them. Part numbers and square metreage come from a thousand lines of
     rules that live in Python, and a second copy of those in JavaScript
     would put different part numbers on Xero invoices depending on which
     screen the order happened to be raised on.

     So the desktop fills them in when it opens the order — which it has to
     do anyway, because the worksheets are made by driving Excel and Word
     and that only runs on Windows. Nothing is lost: an order raised here is
     always finished there. */

  var DRAFT = { header: {}, items: [] };

  SCREENS["new"] = function (main) {
    U.clear(main);
    var f = {};
    function field(label, key, opts) {
      var o = opts || {};
      var input = U.el("input", {
        attr: { type: "text", value: DRAFT.header[key] || "",
                placeholder: o.hint || "", inputmode: o.inputmode || null }
      });
      input.addEventListener("input", function () {
        DRAFT.header[key] = input.value;
      });
      f[key] = input;
      return U.el("label", { cls: "f", kids: [
        U.el("span", { text: label }), input] });
    }

    main.appendChild(U.card("Who it is for", [
      field("Customer name", "Customer Name", { hint: "As it goes on the order" }),
      field("Their order number", "Order Number", { hint: "Leave blank for one of ours" }),
      field("Date due", "Date Due", { hint: "dd/mm/yyyy, or ASAP" }),
      field("Attention", "Attention"),
      field("Job", "Job"),
      field("Location", "Location", { hint: "Delivery region" })
    ]));

    var lines = U.el("div");
    main.appendChild(lines);

    var notes = U.el("textarea", { attr: { rows: "3" } });
    notes.value = DRAFT.header.Notes || "";
    notes.addEventListener("input", function () {
      DRAFT.header.Notes = notes.value;
    });
    main.appendChild(U.card("Notes", [notes]));

    var save = U.button("Save the order", function () { saveDraft(main); }, "go");
    main.appendChild(U.el("div", { cls: "row-actions", kids: [
      save,
      U.button("Start again", function () {
        if (!DRAFT.items.length && !DRAFT.header["Customer Name"]) { return; }
        if (!window.confirm("Throw this order away and start again?")) { return; }
        DRAFT = { header: {}, items: [] };
        show("new");
      }, "quiet")
    ] }));

    drawDraftLines(lines, main);
    SCREENS["new"]._save = save;
  };

  function drawDraftLines(into, main) {
    U.clear(into);
    var rows = DRAFT.items.map(function (it, i) {
      return U.el("tr", { kids: [
        U.cell(it.Quantity),
        U.cell(it["Filter Type"]),
        U.cell([it.Short, it.Long, it.Channel].filter(Boolean).join(" × ")),
        U.cell(it["Media Type"]),
        U.cell(null, { node: U.el("button", {
          cls: "btn quiet", text: "Remove",
          attr: { type: "button" },
          on: { click: function () {
            DRAFT.items.splice(i, 1);
            drawDraftLines(into, main);
          } }
        }) })
      ] });
    });
    into.appendChild(U.card(
      "Lines (" + DRAFT.items.length + ")",
      [rows.length
        ? U.table([{ text: "Qty" }, "Type", "Size (mm)", "Media", " "], rows)
        : U.empty("Nothing on this order yet"),
       U.el("div", { cls: "row-actions", kids: [
         U.button("Add a line", function () { addLine(into, main); })] })]));
  }

  var FILTER_TYPES = ["V-form", "Flat Panel", "Stepped Filter", "Flyscreen",
                      "Header"];
  var MEDIA_TYPES = ["G4", "180", "WASH", "F5", "GREY", "E-MESH"];

  function addLine(into, main) {
    U.openSheet(function (body, close) {
      body.appendChild(U.el("h2", { text: "Add a line" }));
      var v = {};
      function pick(label, key, values) {
        var sel = U.el("select", { kids: values.map(function (t) {
          return U.el("option", { text: t });
        }) });
        v[key] = sel;
        return U.el("label", { cls: "f", kids: [
          U.el("span", { text: label }), sel] });
      }
      function num(label, key, hint) {
        var input = U.el("input", {
          attr: { type: "text", inputmode: "numeric", placeholder: hint || "" }
        });
        v[key] = input;
        return U.el("label", { cls: "f", kids: [
          U.el("span", { text: label }), input] });
      }
      body.appendChild(U.card(null, [
        num("Quantity", "Quantity", "e.g. 4"),
        pick("Filter type", "Filter Type", FILTER_TYPES),
        pick("Media", "Media Type", MEDIA_TYPES),
        num("Short side (mm)", "Short"),
        num("Long side (mm)", "Long"),
        num("Depth (mm)", "Channel"),
        U.el("label", { cls: "f", kids: [
          U.el("span", { text: "Notes" }),
          U.el("input", { attr: { type: "text" } })] })
      ]));
      var noteInput = body.querySelectorAll("input")[
        body.querySelectorAll("input").length - 1];

      body.appendChild(U.el("div", { cls: "muted",
        text: "The part number and square metreage are worked out by the "
            + "desktop app when it opens this order to make the worksheets." }));

      body.appendChild(U.el("div", { cls: "row-actions", kids: [
        U.button("Add it", function () {
          var qty = parseInt(String(v.Quantity.value).trim(), 10);
          if (!(qty > 0)) {
            U.notice(body, "How many? Give a whole number above zero.");
            return;
          }
          var dims = ["Short", "Long", "Channel"].map(function (k) {
            return parseFloat(String(v[k].value).trim());
          });
          if (dims.some(function (d) { return !isFinite(d) || d <= 0; })) {
            U.notice(body,
              "All three measurements are needed — they are what the part "
              + "number and the square metreage are worked out from.");
            return;
          }
          DRAFT.items.push({
            item_kind: "filter",
            Quantity: qty,
            "Filter Type": v["Filter Type"].value,
            "Media Type": v["Media Type"].value,
            Short: dims[0], Long: dims[1], Channel: dims[2],
            Notes: noteInput.value || "",
            "Pleat Insert": false, Header: false,
            "Use Stock V-form": false, "Use Stock Flyscreen": false
          });
          close();
          drawDraftLines(into, main);
        }, "go"),
        U.button("Cancel", close, "quiet")
      ] }));
    });
  }

  function saveDraft(main) {
    var h = DRAFT.header;
    if (!String(h["Customer Name"] || "").trim()) {
      U.notice(main, "Which customer is this for?");
      return;
    }
    if (!DRAFT.items.length) {
      U.notice(main, "There are no lines on this order.");
      return;
    }
    var btn = SCREENS["new"]._save;
    btn.disabled = true;
    var now = new Date();
    function two(n) { return (n < 10 ? "0" : "") + n; }
    var ordered = two(now.getDate()) + "/" + two(now.getMonth() + 1) + "/"
                + String(now.getFullYear()).slice(2);
    h["Date Ordered"] = h["Date Ordered"] || ordered;
    h["Date Due"] = String(h["Date Due"] || "").trim() || "ASAP";
    h.status = "Pending";

    var who = D.cachedProfile();
    D.insert("orders", {
      user_id: D.whoami().id,
      user_email: D.whoami().email || "",
      username: who.username || "",
      full_name: who.full_name || "",
      customer_name: h["Customer Name"],
      order_number: h["Order Number"] || "",
      date_ordered: h["Date Ordered"],
      date_due: h["Date Due"],
      attention: h["Attention"] || "",
      job: h["Job"] || "",
      location: h["Location"] || "",
      notes: h["Notes"] || "",
      order_type: "filter",
      header: h,
      items: DRAFT.items
    }).then(function (rows) {
      var made = (rows && rows[0]) || {};
      DRAFT = { header: {}, items: [] };
      loadedAt = 0;
      show("new");
      U.notice(document.getElementById("screen"),
        "Saved. Open it on the desktop app to print the worksheets — that is "
        + "where the part numbers are filled in."
        + (made.order_number ? " Order " + made.order_number + "." : ""), "ok");
    }).catch(function (err) {
      U.notice(main, err.message);
    }).then(function () { btn.disabled = false; });
  }

  /* ── Delivery ────────────────────────────────────────────────────────
     Only work somebody has marked Complete is ready to go, and the oldest
     promise is loaded first — the same two rules the run sheet is built on,
     so the driver's sheet and this screen never disagree. */

  SCREENS.delivery = function (main) {
    loadOrders().then(function (rows) {
      U.clear(main);
      var ready = rows.filter(function (r) { return r.status === "Complete"; })
                      .sort(function (a, b) {
        return dueSort(a) - dueSort(b) ||
               String(a.customer).localeCompare(String(b.customer));
      });
      if (!ready.length) {
        main.appendChild(U.card(null, [U.empty(
          "Nothing is ready to go out",
          "Orders appear here once they are marked Complete.")]));
        return;
      }
      var byRegion = {};
      ready.forEach(function (r) {
        var region = (r.location || "").trim() || "Unassigned";
        (byRegion[region] = byRegion[region] || []).push(r);
      });
      Object.keys(byRegion).sort().forEach(function (region) {
        var list = byRegion[region];
        main.appendChild(U.card(
          region + "  ·  " + list.length + " order"
          + (list.length === 1 ? "" : "s"),
          [U.table(["Customer", "Order #", "Due", { text: "Lines", num: true }],
            list.map(function (r) {
              return U.el("tr", {
                cls: "row " + (U.dueBucket(r) === "overdue" ? "late" : ""),
                on: { click: function () { openOrder(r); } },
                kids: [U.cell(r.customer), U.cell(r.order_no),
                       U.cell(r.date_due || "—"),
                       U.cell(progressCell(r.n_items, r.n_made), { num: true })]
              });
            })),
           dispatchAll(region, list, main)]));
      });
    }).catch(function (err) { U.clear(main); U.notice(main, err.message); });
  };

  function dueSort(row) {
    var raw = String(row.date_due || "").trim();
    if (/^asap$/i.test(raw)) { return -Infinity; }   // asap goes first
    var d = U.parseDate(raw);
    return d ? d.getTime() : Infinity;
  }

  function dispatchAll(region, list, main) {
    var wrap = U.el("div", { cls: "row-actions" });
    wrap.appendChild(U.button("Mark this run dispatched", function () {
      if (!window.confirm("Mark " + list.length + " order"
          + (list.length === 1 ? "" : "s") + " in " + region
          + " as dispatched?")) { return; }
      var problems = [];
      // One at a time, and it keeps going. Stopping at the first failure
      // leaves nobody knowing which half of the run went through.
      var chain = Promise.resolve();
      list.forEach(function (r) {
        chain = chain.then(function () {
          return D.rpc("merge_order_header", {
            p_order_id: r.id, p_patch: { status: "Dispatched" }
          }).then(function (out) {
            if (!out) { throw new Error("not changed"); }
          }).catch(function (err) {
            problems.push(r.order_no + ": " + err.message);
          });
        });
      });
      chain.then(function () {
        loadedAt = 0;
        if (problems.length) {
          U.notice(main, (list.length - problems.length) + " of " + list.length
                   + " dispatched. These did not: " + problems.join("; "));
        } else {
          U.notice(main, region + " marked dispatched.", "ok");
          show("delivery");
        }
      });
    }, "go"));
    return wrap;
  }

  /* ── Quotes ──────────────────────────────────────────────────────────
     Read here, written on the desktop. Pricing a line means deriving a
     part number and an area from its dimensions, which lives in Python
     today — a second copy of that in JavaScript would put different part
     numbers on Xero invoices depending on which screen someone used. */

  var QUOTE_STATE = ["All", "draft", "sent", "accepted", "declined", "expired"];

  SCREENS.quotes = function (main) {
    D.select("quotes", {
      "select": "id,quote_number,customer_name,reference,status,total,"
              + "unpriced_count,valid_until,created_at,items,notes,"
              + "created_by_name",
      "order": "created_at.desc", "limit": 500
    }).then(function (rows) {
      U.clear(main);
      var state = U.el("select", {
        kids: QUOTE_STATE.map(function (s) {
          return U.el("option", { text: s === "All" ? "All" : titled(s),
                                  attr: { value: s } });
        })
      });
      var search = U.el("input", {
        attr: { type: "search", placeholder: "Customer, quote or reference" }
      });
      var out = U.el("div");
      function redraw() {
        var q = search.value.trim().toLowerCase();
        var list = rows.filter(function (r) {
          if (state.value !== "All" && r.status !== state.value) { return false; }
          return !q || [r.customer_name, r.quote_number, r.reference]
            .join(" ").toLowerCase().indexOf(q) !== -1;
        });
        U.clear(out);
        if (!list.length) {
          out.appendChild(U.card(null, [U.empty("No quotes match")]));
          return;
        }
        out.appendChild(U.card(list.length + " quote"
          + (list.length === 1 ? "" : "s"),
          [U.table(["Customer", "Quote #", "Status",
                    { text: "Total", num: true }],
            list.slice(0, 300).map(function (r) {
              return U.el("tr", {
                cls: "row",
                on: { click: function () { openQuote(r); } },
                kids: [U.cell(r.customer_name || ""),
                       U.cell(r.quote_number || ""),
                       U.cell(titled(r.status)),
                       U.cell(U.money(r.total), { num: true })]
              });
            }))]));
      }
      [search, state].forEach(function (n) {
        n.addEventListener("input", redraw);
        n.addEventListener("change", redraw);
      });
      main.appendChild(U.card(null, [U.el("div", { cls: "filters", kids: [
        U.el("label", { cls: "f", kids: [
          U.el("span", { text: "Search" }), search] }),
        U.el("label", { cls: "f", kids: [
          U.el("span", { text: "Status" }), state] })
      ] })]));
      main.appendChild(out);
      redraw();
    }).catch(function (err) { U.clear(main); U.notice(main, err.message); });
  };

  function titled(s) {
    s = String(s || "");
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : "";
  }

  function openQuote(q) {
    U.openSheet(function (body, close) {
      body.appendChild(U.el("h2", { cls: "title",
        text: q.customer_name || "Quote" }));
      body.appendChild(U.el("div", { cls: "muted",
        text: [q.quote_number ? "Quote " + q.quote_number : "",
               q.reference ? "Their ref " + q.reference : "",
               titled(q.status),
               q.valid_until ? "Valid until " + q.valid_until : ""]
              .filter(Boolean).join("   ·   ") }));

      var items = q.items || [];
      body.appendChild(U.card("Lines", items.length
        ? [U.table([{ text: "Qty" }, "Item", { text: "Each", num: true },
                    { text: "Total", num: true }],
            items.map(function (l) {
              var priced = Number(l.unit_price || 0) > 0;
              return U.el("tr", { kids: [
                U.cell(l.quantity || ""),
                U.cell(l.description || ""),
                U.cell(priced ? U.money(l.unit_price) : "to be confirmed",
                       { num: true }),
                U.cell(priced ? U.money(l.line_total) : "—", { num: true })
              ] });
            })),
           U.el("div", { attr: { style: "text-align:right;margin-top:10px;"
                                      + "font-weight:700" },
                         text: "Total " + U.money(q.total) })]
        : [U.empty("No lines on this quote")]));

      if (q.unpriced_count) {
        U.notice(body, q.unpriced_count + " line"
          + (q.unpriced_count === 1 ? " has" : "s have")
          + " no price and are left out of the total.");
      }
      if (String(q.notes || "").trim()) {
        body.appendChild(U.card("Notes", [
          U.el("div", { text: q.notes })]));
      }
      body.appendChild(U.el("div", { cls: "muted",
        text: "Quotes are written on the desktop app — pricing a line needs "
            + "the part number worked out from its size." }));
      body.appendChild(U.el("div", { cls: "row-actions",
        kids: [U.button("Close", close, "quiet")] }));
    });
  }

  /* ── Customers ───────────────────────────────────────────────────────── */

  SCREENS.customers = function (main) {
    loadKept("customers", function () {
      return D.select("customers",
        { "select": "*", "order": "name", "limit": 2000 });
    })
      .then(function (got) {
        var rows = got.rows;
        U.clear(main);
        var stale = staleNote(got.at);
        if (stale) { main.appendChild(stale); }
        var search = U.el("input", {
          attr: { type: "search", placeholder: "Name, suburb or email" }
        });
        var out = U.el("div");
        function redraw() {
          var q = search.value.trim().toLowerCase();
          var list = rows.filter(function (c) {
            return !q || [c.name, c.short_name, c.email, c.suburb, c.address]
              .join(" ").toLowerCase().indexOf(q) !== -1;
          });
          U.clear(out);
          if (!list.length) {
            out.appendChild(U.card(null, [U.empty("No customers match")]));
            return;
          }
          out.appendChild(U.card(list.length + " customer"
            + (list.length === 1 ? "" : "s"),
            [U.table(["Name", "Phone", "Email"],
              list.slice(0, 400).map(function (c) {
                return U.el("tr", {
                  cls: "row",
                  on: { click: function () { openCustomer(c); } },
                  kids: [U.cell(c.short_name || c.name || ""),
                         U.cell(c.phone || ""), U.cell(c.email || "")]
                });
              }))]));
        }
        search.addEventListener("input", redraw);
        main.appendChild(U.card(null, [U.el("label", { cls: "f", kids: [
          U.el("span", { text: "Search" }), search] })]));
        main.appendChild(out);
        redraw();
      }).catch(function (err) { U.clear(main); U.notice(main, err.message); });
  };

  function openCustomer(c) {
    U.openSheet(function (body, close) {
      body.appendChild(U.el("h2", { cls: "title",
        text: c.name || c.short_name || "Customer" }));
      var rows = [
        ["Trading name", c.short_name], ["Legal name", c.legal_name],
        ["Phone", c.phone], ["Email", c.email],
        ["Address", c.address], ["Suburb", c.suburb],
        ["Region", c.region], ["Payment terms", c.payment_terms],
        ["Notes", c.notes]
      ].filter(function (r) { return String(r[1] || "").trim(); });
      body.appendChild(U.card(null, rows.length
        ? [U.table(["", ""], rows.map(function (r) {
            return U.el("tr", { kids: [U.cell(r[0]), U.cell(r[1])] });
          }))]
        : [U.empty("Nothing recorded against this customer.")]));

      // Their orders, from the list already in hand.
      var theirs = ORDERS.filter(function (o) {
        return String(o.customer || "").trim().toLowerCase()
             === String(c.name || "").trim().toLowerCase()
            || String(o.customer || "").trim().toLowerCase()
             === String(c.short_name || "").trim().toLowerCase();
      }).slice(0, 20);
      body.appendChild(U.card("Their orders (" + theirs.length + ")",
        theirs.length
          ? [U.table(["Order #", "Due", "Status"], theirs.map(function (o) {
              return U.el("tr", {
                cls: "row",
                on: { click: function () { close(); openOrder(o); } },
                kids: [U.cell(o.order_no), U.cell(o.date_due || "—"),
                       U.cell(null, { node: U.pill(o.status) })]
              });
            }))]
          : [U.empty("No orders loaded for them.")]));
      body.appendChild(U.el("div", { cls: "row-actions",
        kids: [U.button("Close", close, "quiet")] }));
    });
  }

  /* ── Stock ───────────────────────────────────────────────────────────── */

  SCREENS.stock = function (main) {
    loadKept("stock", function () {
      return D.select("stock_items",
        { "select": "*", "order": "name", "limit": 2000 });
    })
      .then(function (got) {
        var rows = got.rows;
        U.clear(main);
        var stale = staleNote(got.at);
        if (stale) { main.appendChild(stale); }
        var search = U.el("input", {
          attr: { type: "search", placeholder: "Item, SKU or media" }
        });
        var lowOnly = U.el("input", { attr: { type: "checkbox" } });
        var out = U.el("div");

        function isLow(s) {
          var min = Number(s.minimum_level || s.min_level || 0);
          return min > 0 && Number(s.stock_on_hand || 0) <= min;
        }
        function redraw() {
          var q = search.value.trim().toLowerCase();
          var list = rows.filter(function (s) {
            if (lowOnly.checked && !isLow(s)) { return false; }
            return !q || [s.name, s.sku, s.media_type]
              .join(" ").toLowerCase().indexOf(q) !== -1;
          });
          U.clear(out);
          if (!list.length) {
            out.appendChild(U.card(null, [U.empty("Nothing matches")]));
            return;
          }
          out.appendChild(U.card(list.length + " item"
            + (list.length === 1 ? "" : "s"),
            [U.table(["Item", "SKU", { text: "On hand", num: true },
                      { text: "Minimum", num: true }],
              list.slice(0, 400).map(function (s) {
                return U.el("tr", {
                  cls: "row " + (isLow(s) ? "late" : ""),
                  on: { click: function () { openStock(s, rows); } },
                  kids: [U.cell(s.name || ""), U.cell(s.sku || ""),
                         U.cell(s.stock_on_hand, { num: true }),
                         U.cell(s.minimum_level || s.min_level || "",
                                { num: true })]
                });
              }))]));
        }
        [search, lowOnly].forEach(function (n) {
          n.addEventListener("input", redraw);
          n.addEventListener("change", redraw);
        });
        main.appendChild(U.card(null, [
          U.el("label", { cls: "f", kids: [
            U.el("span", { text: "Search" }), search] }),
          U.el("label", {
            attr: { style: "display:flex;gap:8px;align-items:center;"
                         + "font-size:14px;color:var(--muted)" },
            kids: [lowOnly, U.el("span", { text: "Only what is low" })] })
        ]));
        main.appendChild(out);
        redraw();
      }).catch(function (err) { U.clear(main); U.notice(main, err.message); });
  };

  function openStock(item, all) {
    U.openSheet(function (body, close) {
      body.appendChild(U.el("h2", { cls: "title",
        text: item.name || "Stock item" }));
      body.appendChild(U.el("div", { cls: "muted",
        text: [item.sku ? "SKU " + item.sku : "",
               item.media_type ? "Media " + item.media_type : "",
               item.unit ? "Per " + item.unit : ""]
              .filter(Boolean).join("   ·   ") }));

      var onHand = U.el("div", {
        text: String(item.stock_on_hand || 0),
        attr: { style: "font-size:30px;font-weight:700" } });
      body.appendChild(U.card("On hand", [onHand,
        U.el("div", { cls: "muted",
          text: "Minimum " + (item.minimum_level || item.min_level || 0) })]));

      if (!D.canManageStock()) {
        body.appendChild(U.el("div", { cls: "muted",
          text: "Only a manager can adjust stock." }));
        body.appendChild(U.el("div", { cls: "row-actions",
          kids: [U.button("Close", close, "quiet")] }));
        return;
      }

      var kind = U.el("select", { kids: [
        U.el("option", { text: "Used", attr: { value: "use" } }),
        U.el("option", { text: "Received", attr: { value: "receive" } }),
        U.el("option", { text: "Counted (set to)", attr: { value: "count" } }),
        U.el("option", { text: "Written off", attr: { value: "writeoff" } })
      ] });
      var qty = U.el("input", { attr: { type: "text", inputmode: "decimal",
                                        placeholder: "e.g. 4" } });
      var note = U.el("input", { attr: { type: "text",
                                         placeholder: "What for (optional)" } });
      var go = U.button("Save the adjustment", function () {
        var n = parseFloat(String(qty.value).trim());
        if (!isFinite(n)) {
          U.notice(body, "Give the amount as a number.");
          return;
        }
        go.disabled = true;
        // The same reference twice is applied once, so a tap that looked
        // like it did nothing and got tapped again cannot double-count -
        // and neither can a queued movement that was sent, lost its answer
        // to a dropout, and got sent again.
        var ref = S.newRef();
        var what = kind.options[kind.selectedIndex].text;
        S.send({
          rpc: "adjust_stock_atomic",
          label: (item.name || "Stock") + " · " + what + " " + n,
          body: {
            p_item_id: item.id, p_type: kind.value, p_quantity: n,
            p_notes: note.value || "", p_client_ref: ref,
            p_username: D.cachedProfile().username
                     || D.cachedProfile().full_name || "",
            p_device: "web"
          }
        }).then(function (res) {
          qty.value = ""; note.value = "";
          if (res.queued) {
            // Deliberately not guessing the new figure. Two people counting
            // the same rack out of signal would both be shown a number that
            // is right about their own count and wrong about the shelf.
            U.notice(body, "Kept on this phone. The count will go through "
                         + "when the signal is back, and the figure above "
                         + "will be right once it has.", "ok");
            onHand.textContent = String(item.stock_on_hand || 0) + " ?";
            return;
          }
          var row = Array.isArray(res.out) ? res.out[0] : res.out;
          var after = row && row.quantity_after;
          if (after === null || after === undefined) {
            throw new Error("The database did not report a new figure. "
                            + "Check the count before adjusting again.");
          }
          item.stock_on_hand = after;
          onHand.textContent = String(after);
          U.notice(body, "Now " + after + " on hand.", "ok");
          void all;
        }).catch(function (err) {
          U.notice(body, err.message);
        }).then(function () { go.disabled = false; });
      }, "go");

      body.appendChild(U.card("Adjust it", [
        U.el("label", { cls: "f", kids: [
          U.el("span", { text: "What happened" }), kind] }),
        U.el("label", { cls: "f", kids: [
          U.el("span", { text: "How much" }), qty] }),
        U.el("label", { cls: "f", kids: [
          U.el("span", { text: "Note" }), note] })
      ]));
      body.appendChild(U.el("div", { cls: "row-actions",
        kids: [go, U.button("Close", close, "quiet")] }));
    });
  }

  return {
    start: start,
    updateReady: updateReady,
    _screens: SCREENS,
    _stateBar: stateBar,
    _lookUp: lookUp,
    _outbox: outbox,
    _progressCell: progressCell,
    _shapeOrder: shapeOrder,
    _openOrder: openOrder,
    _orders: function () { return ORDERS; },
    _stale: function () { loadedAt = 0; }
  };
})();
