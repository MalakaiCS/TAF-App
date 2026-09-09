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

  var U = TAFUI, D = TAFDATA;
  var TABS = [
    { key: "dashboard",   label: "Today" },
    { key: "orders",      label: "Orders" },
    { key: "delivery",    label: "Delivery" },
    { key: "customers",   label: "Customers" },
    { key: "stock",       label: "Stock" }
  ];
  var active = "dashboard";
  var ORDERS = [];              // the loaded list, newest first
  var loadedAt = 0;

  /* ── Starting up ─────────────────────────────────────────────────────── */

  function start(key) {
    var signin = document.getElementById("signin");
    var app = document.getElementById("app");

    if (window.TAF) {
      TAF.logo(document.getElementById("signin-head"), "../");
      TAF.footer(document.getElementById("signin-foot"));
    }

    if (!key) {
      U.notice(document.getElementById("signin").querySelector(".card"),
        "This link is missing its set-up key. Open the web app from the "
        + "desktop app once and it will be remembered on this device.");
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
      show(active);
    }
    start._showApp = showApp;
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
      ORDERS = rows.map(shapeOrder);
      loadedAt = Date.now();
      return ORDERS;
    }).catch(function (err) {
      // A project without migrate_performance.sql has no orders_list view.
      if (/not there any more|does not exist|relation/i.test(err.message || "")) {
        return D.select("orders", {
          "select": "id,customer_name,order_number,date_ordered,date_due,"
                  + "header,order_type,created_at,archived,full_name",
          "archived": "eq.false", "order": "created_at.desc", "limit": 1000
        }).then(function (rows) {
          ORDERS = rows.map(shapeOrder);
          loadedAt = Date.now();
          return ORDERS;
        });
      }
      throw err;
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

      D.select("orders", { "id": "eq." + row.id, "select": "items,header" })
        .then(function (rows) {
          var order = (rows && rows[0]) || {};
          drawLines(lines, row, order.items || [], body);
          drawNotes(body, row, order.header || {});
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
        D.rpc("set_order_line_made", {
          p_order_id: row.id,
          p_line_id: it.line_id || "",
          p_made: want,
          p_by: D.cachedProfile().full_name || D.cachedProfile().username || "",
          p_at: want ? stamp() : ""
        }).then(function (out) {
          if (!out) {
            throw new Error("That line was not found on the order. "
                            + "Close this and open it again.");
          }
          it.made = want;
          tick.textContent = want ? "✓" : "";
          tick.setAttribute("aria-pressed", String(want));
          tr.className = want ? "made" : "";
          tally();
          U.notice(body, "");
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
        D.rpc("merge_order_header", {
          p_order_id: row.id, p_patch: { status: want }
        }).then(function (out) {
          if (!out) { throw new Error("That order was not changed."); }
          row.status = want;
          pill.className = "pill s-" + want.replace(/\s+/g, "");
          pill.textContent = want;
          loadedAt = 0;
          drawStatus(actions, row, body, pill, close);
          U.notice(body, "Status set to " + want + ".", "ok");
        }).catch(function (err) { U.notice(body, err.message); });
      }, want === "Complete" ? "go" : "quiet"));
    });
    actions.appendChild(U.button("Close", close, "quiet"));
  }

  /* Not built yet — say so rather than showing an empty screen. */
  ["delivery", "customers", "stock"].forEach(function (key) {
    SCREENS[key] = function (main) {
      U.clear(main);
      main.appendChild(U.card(null, [U.empty(
        "Not on the web yet",
        "This screen is still only in the Windows app.")]));
    };
  });

  return {
    start: start,
    _screens: SCREENS,
    _progressCell: progressCell,
    _shapeOrder: shapeOrder,
    _openOrder: openOrder,
    _orders: function () { return ORDERS; },
    _stale: function () { loadedAt = 0; }
  };
})();
