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
  // The first four shown are the phone's bottom bar; the rest are under
  // More. On anything wider they are all in the sidebar.
  var TABS = [
    { key: "dashboard",   label: "Today",     icon: "home" },
    { key: "orders",      label: "Orders",    icon: "list" },
    { key: "new",         label: "New order", icon: "plus" },
    { key: "scan",        label: "Scan",      icon: "scan" },
    { key: "delivery",    label: "Delivery",  icon: "truck" },
    { key: "quotes",      label: "Quotes",    icon: "doc" },
    { key: "customers",   label: "Customers", icon: "people" },
    { key: "stock",       label: "Stock",     icon: "box" },
    { key: "supplies",    label: "Supplies",  icon: "bag" },
    { key: "board",       label: "Board",     icon: "board", feature: "tv_board" },
    { key: "count",       label: "Stocktake", icon: "count", feature: "stocktake" },
    { key: "chat",        label: "Messages",  icon: "chat" },
    { key: "howto",       label: "How to",    icon: "book" },
    { key: "log",         label: "Log",       icon: "clock", from: 3 }
  ];
  var BAR = 4;

  // Line icons, drawn here rather than fetched: a tab bar that waits on the
  // network for its pictures is a tab bar with gaps in it out of signal.
  var ICONS = {
    home:   ["M3 10.5 12 3l9 7.5", "M5 9.5V21h14V9.5", "M10 21v-6h4v6"],
    list:   ["M9 3.5h6v3H9z", "M7 5H5.5v16h13V5H17", "M9 11h6", "M9 15h6"],
    plus:   ["M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z", "M12 8v8", "M8 12h8"],
    scan:   ["M4 8V5h4", "M16 5h4v3", "M20 16v3h-4", "M8 19H4v-3", "M4 12h16"],
    truck:  ["M2 6h11v10H2z", "M13 9h4l4 4v3h-8z",
             "M8 18a1.6 1.6 0 1 1-3.2 0 1.6 1.6 0 0 1 3.2 0Z",
             "M19 18a1.6 1.6 0 1 1-3.2 0 1.6 1.6 0 0 1 3.2 0Z"],
    doc:    ["M14 3H6v18h12V7z", "M14 3v4h4", "M9 12.5h6", "M9 16.5h4"],
    people: ["M16 20v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1",
             "M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z",
             "M22 20v-1a4 4 0 0 0-3-3.9", "M16 3.2a4 4 0 0 1 0 7.6"],
    box:    ["M21 7.5 12 3 3 7.5 12 12z", "M3 7.5v9L12 21l9-4.5v-9", "M12 12v9"],
    bag:    ["M5.5 8h13l-1 12.5h-11z", "M9 8V7a3 3 0 0 1 6 0v1"],
    clock:  ["M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z", "M12 7v5l3.5 2"],
    board:  ["M3 4h18v13H3z", "M8 21h8", "M12 17v4", "M8 8v5", "M12 8v3",
             "M16 8v6"],
    count:  ["M9 3.5h6v3H9z", "M7 5H5.5v16h13V5H17", "M9 13l2 2 4-4"],
    chat:   ["M4 5h16v11H9l-5 4z", "M8 9.5h8", "M8 12.5h5"],
    book:   ["M4 4.5h6a2 2 0 0 1 2 2V20a2 2 0 0 0-2-2H4z",
             "M20 4.5h-6a2 2 0 0 0-2 2V20a2 2 0 0 1 2-2h6z"],
    more:   ["M5 12h.01", "M12 12h.01", "M19 12h.01"]
  };

  function icon(name) {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    (ICONS[name] || []).forEach(function (d) {
      var path = document.createElementNS(ns, "path");
      path.setAttribute("d", d);
      if (name === "more") { path.setAttribute("stroke-width", "3.4"); }
      svg.appendChild(path);
    });
    return svg;
  }

  function shownTabs() {
    // A tab nobody below a manager can read anything on is a tab that only
    // ever shows an empty table and a permission error. The database is
    // still what decides - this only stops us offering it.
    return TABS.filter(function (t) {
      return !(t.from && D.roleLevel() < t.from)
          && !(t.feature && !feature(t.feature));
    });
  }

  /* The things that run out. The same list as SUPPLY ITEMS in
     taf_order_app/supplies.py - a test holds the two together, so a phone
     and a PC never offer different things to ask for. */
  var SUPPLY_ITEMS = ["Rivets", "Tape", "Media", "Mesh Wire", "Channel",
                      "Other"];
  var SUPPLY_HINTS = {
    "Rivets":    "Which rivets? Size or type",
    "Tape":      "Which tape? Foil, duct, width",
    "Media":     "Which grade? G4, F7, carbon…",
    "Mesh Wire": "Which mesh? Gauge, galv or stainless",
    "Channel":   "Which depth? 25, 45, 50…",
    "Other":     "What do you need?"
  };
  var SUPPLY_STATUS = {
    open: "Waiting", ordered: "Ordered", received: "Received",
    declined: "Declined", cancelled: "Cancelled"
  };
  // What a manager can move a request to, from where it is.
  var SUPPLY_NEXT = {
    open: ["ordered", "received", "declined"],
    ordered: ["received"]
  };
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

    document.getElementById("brand-badge")
      .addEventListener("click", function () {
        U.spin(this.querySelector("img"));
      });
    U.autoReveal(document.getElementById("screen"));

    if (D.signedIn()) {
      // Signed in from last time: straight to the loading screen while it
      // checks, not a flash of the sign-in form.
      showBoot();
      // A remembered session might have expired overnight. Ask the database
      // who we are rather than trusting what is in storage.
      D.profile(true).then(function (p) {
        if (p && p.id) { showApp(); }
        else { showSignIn(); }
      }).catch(showSignIn);
    } else {
      showSignIn();
    }

    function showSignIn() {
      hideBoot(true);
      signin.classList.remove("hidden");
    }
    function showApp() {
      showBoot();
      signin.classList.add("hidden");
      app.classList.remove("hidden");
      buildTabs();
      whoBar();
      // Once, however many times somebody signs in and out of this tab.
      // Wiring these up twice means two idle timers and a sheet that opens
      // on top of itself.
      document.getElementById("who").onclick = meSheet;
      document.getElementById("bell").onclick = bellSheet;
      document.getElementById("chat-btn").onclick = function () {
        U.closeAllSheets();
        show("chat");
      };
      if (!showApp._wired) {
        showApp._wired = true;
        S.onChange(stateBar);
        S.start();
        watchIdle();
        watchBell();
      }
      pollBell();
      stateBar();
      // The TV: opened with ?board=tv, it is the production board and
      // nothing else.
      if (/[?&]board=tv\b/.test(location.search)) {
        document.body.classList.add("tv");
        active = "board";
        keepAwake();
      }
      show(active);
      hideBootWhenLoaded();
      // The switches decide which tabs and buttons there are; the screen
      // is redrawn once they are known.
      loadFeatures().then(function () {
        buildTabs();
        if (active === "board" || active === "orders") { show(active); }
      });
    }
    start._showApp = showApp;
  }

  /* ── The loading screen ──────────────────────────────────────────────
     White, the badge turning, from signing in until the first screen has
     its data - then it fades. Up for at least a moment so it never just
     flickers, and never more than twelve seconds whatever happens. */

  var bootShownAt = 0;

  function showBoot() {
    var boot = document.getElementById("boot");
    if (!boot.classList.contains("hidden") && !boot.classList.contains("out")) {
      return;
    }
    bootShownAt = Date.now();
    boot.classList.remove("hidden", "out");
  }

  function hideBoot(now) {
    var boot = document.getElementById("boot");
    if (boot.classList.contains("hidden")) { return; }
    if (now || !U.motionOK()) {
      boot.classList.add("hidden");
      return;
    }
    boot.classList.add("out");
    setTimeout(function () {
      if (boot.classList.contains("out")) { boot.classList.add("hidden"); }
    }, 500);
  }

  function hideBootWhenLoaded() {
    var main = document.getElementById("screen");
    var timer = setInterval(function () {
      var waited = Date.now() - bootShownAt;
      // The screen has drawn once its "Loading…" placeholder is gone.
      var drawn = main.firstChild && !main.querySelector(".loading-ph");
      if ((drawn && waited >= 600) || waited >= 12000) {
        clearInterval(timer);
        hideBoot();
      }
    }, 100);
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

  /* One line in the log, for something that went straight through. Anything
     that can be queued carries its entry on the job instead, so it is
     written when the change actually lands rather than when it was tapped. */
  function logIt(action, details) {
    var me = D.cachedProfile();
    D.insert("audit_log", {
      user_id: D.whoami().id,
      username: me.username || me.full_name || "",
      action: action,
      details: details || ""
    }, true).catch(function () { /* the log is a bonus, never a blocker */ });
  }

  /* ── You ─────────────────────────────────────────────────────────────
     Behind your own name, top right. The only thing on a phone that is
     yours rather than the company's: whether the morning summary comes to
     you. Off until you say otherwise, and it stays off unless a manager has
     also turned the whole thing on. */

  function meSheet() {
    U.openSheet(function (body, close) {
      var me = D.cachedProfile();
      body.appendChild(U.el("h2", { cls: "title",
        text: me.full_name || me.username || "You" }));
      body.appendChild(U.el("div", { cls: "muted",
        text: [me.role || "", D.whoami().email || ""]
              .filter(Boolean).join("   ·   ") }));

      var box = U.el("input", { attr: { type: "checkbox" } });
      var note = U.el("div", { cls: "muted",
        text: "Reading whether you have this on…" });
      var card = U.card("A morning summary", [
        U.el("div", {
          text: "What is overdue, what is due today, what is low on stock "
              + "and which repeat jobs have come round — emailed to you each "
              + "weekday morning." }),
        U.el("label", {
          attr: { style: "display:flex;gap:10px;align-items:center;"
                       + "margin:12px 0 0;font-size:15px" },
          kids: [box, U.el("span", { text: "Email one to me" })] }),
        note
      ]);
      body.appendChild(card);

      box.disabled = true;
      D.select("notify_settings", {
        "user_id": "eq." + D.whoami().id, "select": "daily_summary"
      }).then(function (rows) {
        box.checked = !!(rows && rows[0] && rows[0].daily_summary);
        box.disabled = false;
        note.textContent = box.checked
          ? "You are on the list. It only arrives if a manager has the "
            + "company switch on as well."
          : "You are not on the list.";
      }).catch(function (err) {
        // Not a tick left half on: a switch nobody could read must not look
        // like a switch that is off, or somebody turns off a thing they
        // never had and believes they have dealt with it.
        note.textContent = /not there any more|does not exist/i
          .test(err.message || "")
          ? "This needs migrate_notifications.sql running against the "
            + "database first."
          : err.message;
      });

      box.addEventListener("change", function () {
        var want = box.checked;
        box.disabled = true;
        D.rpc("set_my_daily_summary", { p_on: want }).then(function (out) {
          var now = Array.isArray(out) ? out[0] : out;
          if (now && typeof now === "object") { now = now.set_my_daily_summary; }
          box.checked = !!now;
          note.textContent = box.checked
            ? "You are on the list." : "You are not on the list.";
        }).catch(function (err) {
          box.checked = !want;
          note.textContent = err.message;
        }).then(function () { box.disabled = false; });
      });

      body.appendChild(U.el("div", { cls: "row-actions", kids: [
        U.button("Send mine now", function (e) {
          var btn = e.target;
          btn.disabled = true;
          U.notice(body, "Sending…", "ok");
          D.callFunction("daily-summary", {}).then(function (out) {
            U.notice(body, out.sent
              ? "Sent. Check your inbox."
              : (out.reason || "Nothing was sent."), out.sent ? "ok" : "err");
          }).catch(function (err) {
            U.notice(body, err.message);
          }).then(function () { btn.disabled = false; });
        }, "quiet"),
        S.pending()
          ? U.button(S.pending() + " waiting to send", function () {
              U.closeSheet(); outbox();
            }, "quiet")
          : null,
        U.button("Close", close, "quiet")
      ].filter(Boolean) }));
      // On a phone the header has no room for it, so it is here as well.
      body.appendChild(U.el("div", { cls: "row-actions", kids: [
        U.button("Sign out", function () {
          close();
          document.getElementById("signout").click();
        }, "quiet")] }));
    });
  }

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
    var name = String(p.full_name || p.username || D.whoami().email || "?");
    document.getElementById("who-initials").textContent =
      name.split(/[\s@._-]+/).filter(Boolean).slice(0, 2)
        .map(function (w) { return w.charAt(0).toUpperCase(); }).join("") || "?";
  }

  function buildTabs() {
    var nav = U.clear(document.getElementById("tabs"));
    var tabs = shownTabs();
    tabs.forEach(function (t, i) {
      nav.appendChild(U.el("button", {
        cls: i < BAR ? "" : "extra",
        attr: { role: "tab", type: "button",
                "aria-selected": String(t.key === active),
                "data-tab": t.key },
        kids: [icon(t.icon), U.el("span", { text: t.label })].concat(
          t.key === "chat" && CHAT_UNREAD
            ? [U.el("b", { cls: "tab-count", text: String(CHAT_UNREAD) })] : []),
        on: { click: function () { show(t.key); } }
      }));
    });
    // The phone's fifth button: everything that is not in the bar.
    var under = tabs.slice(BAR).some(function (t) { return t.key === active; });
    nav.appendChild(U.el("button", {
      attr: { id: "tab-more", type: "button", "aria-selected": String(under),
              "aria-label": "More" },
      kids: [icon("more"), U.el("span", { text: "More" })],
      on: { click: moreSheet }
    }));
    var here = tabs.filter(function (t) { return t.key === active; })[0];
    document.getElementById("app-here").textContent =
      here ? here.label : "Total Air Filtration";
  }

  function moreSheet() {
    U.openSheet(function (body) {
      body.appendChild(U.el("h2", { cls: "title", text: "More" }));
      body.appendChild(U.el("div", { cls: "more-grid",
        kids: shownTabs().slice(BAR).map(function (t) {
          return U.el("button", {
            attr: { type: "button", "aria-selected": String(t.key === active),
                    "data-more": t.key },
            kids: [icon(t.icon), U.el("span", { text: t.label })],
            on: { click: function () { U.closeAllSheets(); show(t.key); } }
          });
        }) }));
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
    // The stock cards use the width of a wide screen; the rest read better
    // narrower.
    main.classList.toggle("wide", key === "stock");
    var draw = SCREENS[key];
    if (!draw) { return; }
    main.appendChild(U.el("div", { cls: "muted loading-ph", text: "Loading…" }));
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
      var grid = U.el("div", { cls: "stat-grid" });
      tiles.forEach(function (t) {
        grid.appendChild(U.el("div", {
          cls: "card stat stat-" + t[2] + (t[1] ? "" : " zero"),
          attr: { role: "button", tabindex: "0" },
          on: { click: function () { show("orders"); filterTo(t[2]); } },
          kids: [
            U.el("div", { cls: "stat-n", text: String(t[1]) }),
            U.el("div", { cls: "stat-l", text: t[0] })
          ]
        }));
      });
      main.appendChild(U.el("h2", { text: todayLine() }));
      main.appendChild(grid);
      main.appendChild(U.card("What is late", lateList(rows)));
      if (feature("sales_targets")) { targetCard(main); }
      if (feature("quote_chase")) { chaseCard(main); }
      if (feature("service_reminders")) { serviceCard(main, rows); }
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
      U.onPick([search, due, status], redraw);

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

      reportFault._order = row;
      Promise.all([
        D.select("orders", { "id": "eq." + row.id, "select": "items,header" }),
        loadRunning()
      ]).then(function (got) { return got[0]; })
        .then(function (rows) {
          var order = (rows && rows[0]) || {};
          row._items = order.items || [];
          drawLines(lines, row, order.items || [], body);
          drawCutPlan(body, order.header || {});
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

    // Timing a line and recording a fault each want a button on the line,
    // when they are switched on.
    var extras = feature("job_timer") || feature("fault_log")
      || (feature("sops") && items.some(function (it) {
        return sopsForType(SOPS || [], it["Filter Type"]).length > 0; }));
    var rows = items.map(function (it, idx) {
      var tick = U.el("button", {
        cls: "tick", text: it.made ? "✓" : "",
        attr: { type: "button", "aria-pressed": String(!!it.made),
                "aria-label": "Mark line " + (idx + 1) + " as made" }
      });
      var more = U.el("div", { cls: "line-acts" });
      drawTimer(more, row, it);
      var howtos = feature("sops") ? sopsForType(SOPS || [], it["Filter Type"]) : [];
      if (howtos.length) {
        more.appendChild(U.button("📘", function () { openSop(howtos[0]); },
                                  "quiet howto"));
        more.lastChild.setAttribute("aria-label", "How to make line " + (idx + 1));
      }
      if (feature("fault_log")) {
        more.appendChild(U.button("⚠", function () {
          reportFault(row, it, items);
        }, "quiet fault"));
        more.lastChild.setAttribute("aria-label", "Record a fault on line "
                                                  + (idx + 1));
      }
      var cells = [U.cell(null, { node: tick }),
                   U.cell(it.Quantity || it.quantity || ""),
                   U.cell(lineName(it)),
                   U.cell(lineSize(it)),
                   U.cell(it["Media Type"] || it.media || "")];
      if (extras) { cells.push(U.cell(null, { node: more })); }
      var tr = U.el("tr", { cls: it.made ? "made" : "", kids: cells });
      tick.addEventListener("click", function () {
        var want = !it.made;
        tick.disabled = true;
        if (!want) { markMade(false); return; }
        // With QC on: its checks first, kept on the line, then made.
        qcBeforeMade(it).then(function (qc) {
          if (qc === null) { tick.disabled = false; return; }
          if (!Object.keys(qc).length) { markMade(true); return; }
          S.send({
            rpc: "set_order_line_qc",
            label: (row.customer || "Order") + " · line " + (idx + 1) + " checked",
            needs_row: true,
            gone: "That line is not on the order any more.",
            body: { p_order_id: row.id, p_line_id: it.line_id || "", p_qc: qc }
          }).then(function () {
            it.qc = qc;
            markMade(true);
          }).catch(function (err) {
            U.notice(body, err.message);
            tick.disabled = false;
          });
        });
      });

      function markMade(want) {
        // The filter is made whether or not the wifi reaches this corner of
        // the factory. Setting a line to made is the same done twice as
        // done once, so this is safe to keep and send later.
        S.send({
          rpc: "set_order_line_made",
          label: (row.customer || "Order") + " · line " + (idx + 1)
               + (want ? " made" : " not made"),
          needs_row: true,
          gone: "That line is not on the order any more.",
          log: {
            action: want ? "line_made" : "line_unmade",
            details: "O/N: " + (row.order_no || "") + " | Customer: "
                   + (row.customer || "") + " | Line " + (idx + 1) + ": "
                   + lineName(it) + " " + lineSize(it)
          },
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
      }
      return tr;
    });

    var heads = [" ", { text: "Qty" }, "Item", "Size (mm)", "Media"];
    if (extras) { heads.push(""); }
    into.appendChild(U.card("Lines", [U.table(heads, rows), count]));
    var packing = packingNotes(items);
    if (packing) { into.appendChild(packing); }
    tally();
    void made;
  }

  /* How each line is wrapped (from the plan the office saved, which is what
     the worksheet and the delivery labels print) and whether it needs a
     brace (worked out here with the shared rules). */
  function packingNotes(items) {
    var C = window.TAFCALC;
    if (!C) { return null; }
    var notes = items.map(function (it, idx) {
      var plan = it.Packing;
      var wrap = plan && plan.wraps && plan.wraps.length
        ? C.planInstructions(plan).join("  ")
        : "Wrapping not set yet - the office sets it before packing";
      var kind = C.constructionOf(it["Filter Type"]);
      var b = kind ? C.bracing(kind, it.Short, it.Long) : null;
      var line = U.el("div", { cls: "pack-row" + (b && b.required
                                                 ? " required" : ""),
        attr: { "data-line": String(idx + 1) } });
      line.appendChild(U.el("strong", { text: "Line " + (idx + 1) + ": " }));
      line.appendChild(U.el("span", { text: wrap }));
      if (b && b.status === "ok") {
        line.appendChild(U.el("span", { cls: "muted",
                                        text: "  ·  " + b.message }));
      }
      return line;
    });
    return U.card("Wrapping and bracing", notes);
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

  /* ── Feature switches ────────────────────────────────────────────────
     The same switches the desktop turns on (Settings → Features), so a
     thing is on for everybody or for nobody. Remembered for no signal. */

  var FEATURES = {};

  // Messages and the how-to library are part of the app, not switches -
  // the same as features.ALWAYS_ON.
  var ALWAYS_ON = { sops: true, staff_chat: true };
  function feature(key) { return !!(ALWAYS_ON[key] || FEATURES[key]); }

  function loadFeatures() {
    return D.select("feature_switches", { "select": "key,enabled" })
      .then(function (rows) {
        var on = {};
        (rows || []).forEach(function (r) { if (r.enabled) { on[r.key] = true; } });
        FEATURES = on;
        S.remember("features", on);
        return on;
      }).catch(function () {
        var box = S.recall("features");
        FEATURES = (box && box.v) || {};
        return FEATURES;
      });
  }

  /* ── The production board, and the TV ────────────────────────────────
     Four columns somebody at the far end of the factory can read. The same
     rules as floor.py's board_column and production_board - a test holds
     the two together. */

  var BOARD_COLUMNS = [["to_cut", "To cut"], ["making", "Making"],
                       ["packed", "Packed"], ["out", "Out the door"]];
  var GONE = ["Dispatched", "Delivered", "Collected"];

  function pad2(n) { return (n < 10 ? "0" : "") + n; }
  function ymd(d) {
    return d ? d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-"
               + pad2(d.getDate()) : "";
  }

  // The day, here, of a time the database stamped in UTC.
  function stampDay(text) {
    var s = String(text || "").trim();
    if (!s) { return null; }
    var d = new Date(s);
    if (isNaN(d.getTime())) { return null; }
    d.setHours(0, 0, 0, 0);
    return d;
  }

  function stageReached(h) {
    var got = h.stages, reached = "";
    if (got && typeof got === "object") {
      ["marked", "cut", "drilled", "assembled", "packed"].forEach(function (k) {
        if (got[k]) { reached = k; }
      });
    }
    return reached;
  }

  function boardColumn(row, today) {
    if (row.archived) { return ""; }
    var h = row.header || {};
    var status = String(h.status || row.status || "Pending");
    if (GONE.indexOf(status) >= 0) {
      var went = stampDay(h.status_at) || U.parseDate(row.date_due);
      return went && ymd(went) === ymd(today) ? "out" : "";
    }
    if (status === "Complete") { return "packed"; }
    var reached = stageReached(h);
    if (reached === "packed") { return "packed"; }
    var made = parseInt(row.n_made, 10) || 0;
    if (["cut", "drilled", "assembled"].indexOf(reached) >= 0 || made > 0
        || status === "In Production") { return "making"; }
    return "to_cut";
  }

  function workingDaysOn(day, n) {
    var d = new Date(day.getTime()), left = Math.max(0, n | 0);
    while (left) {
      d.setDate(d.getDate() + 1);
      if (d.getDay() !== 0 && d.getDay() !== 6) { left--; }
    }
    return d;
  }

  function productionBoard(rows, today, ahead) {
    var horizon = workingDaysOn(today, ahead === undefined ? 1 : ahead);
    var cols = {};
    BOARD_COLUMNS.forEach(function (c) {
      cols[c[0]] = { key: c[0], label: c[1], cards: [] };
    });
    (rows || []).forEach(function (row) {
      var col = boardColumn(row, today);
      if (!col) { return; }
      var due = U.parseDate(row.date_due);
      if (col === "to_cut" && (!due || due > horizon)) { return; }
      var h = row.header || {};
      cols[col].cards.push({
        id: row.id,
        customer: String(row.customer_name || row.customer || ""),
        order_no: String(row.order_number || row.order_no || ""),
        due: due ? ymd(due) : "",
        late: !!(due && due < today && col !== "out"),
        today: !!(due && ymd(due) === ymd(today)),
        priority: !!h.priority,
        made: parseInt(row.n_made, 10) || 0,
        lines: parseInt(row.n_items, 10) || 0
      });
    });
    BOARD_COLUMNS.forEach(function (c) {
      cols[c[0]].cards.sort(function (a, b) {
        if (a.priority !== b.priority) { return a.priority ? -1 : 1; }
        var da = a.due || "9999-12-31", db = b.due || "9999-12-31";
        if (da !== db) { return da < db ? -1 : 1; }
        var ca = a.customer.toLowerCase(), cb = b.customer.toLowerCase();
        return ca < cb ? -1 : (ca > cb ? 1 : 0);
      });
    });
    return BOARD_COLUMNS.map(function (c) { return cols[c[0]]; });
  }

  var boardTimer = null;
  var BOARD_AHEAD = "taf_board_ahead";

  SCREENS.board = function (main) {
    if (!feature("tv_board")) {
      U.clear(main);
      main.appendChild(U.empty("The production board is switched off.",
        "A director or admin turns it on in the desktop app: Settings → "
        + "Features → Production board on the TV."));
      return;
    }
    var tv = document.body.classList.contains("tv");
    var ahead = 1;
    try { ahead = parseInt(localStorage.getItem(BOARD_AHEAD), 10) || 1; }
    catch (e) { ahead = 1; }

    function draw() {
      loadOrders(true).then(function (rows) {
        if (active !== "board") { return; }
        U.clear(main);
        var today = U.today();
        var cols = productionBoard(rows, today, ahead);
        var now = new Date();
        var head = U.el("div", { cls: "board-head", kids: [
          U.el("h2", { text: "Production board" }),
          U.el("span", { cls: "board-clock",
                         text: now.toLocaleDateString(undefined, {
                           weekday: "long", day: "numeric", month: "long" })
                       + "  ·  " + pad2(now.getHours()) + ":"
                       + pad2(now.getMinutes()) })] });
        if (!tv) {
          var span = U.el("select", { attr: { id: "board-ahead",
                                              "aria-label": "How far ahead" },
            kids: [[1, "Due today and next working day"], [2, "Next 2 working days"],
                   [5, "Next week"]].map(function (o) {
              return U.el("option", { text: o[1], attr: { value: String(o[0]) } });
            }) });
          span.value = String(ahead);
          span.addEventListener("change", function () {
            ahead = parseInt(span.value, 10) || 1;
            try { localStorage.setItem(BOARD_AHEAD, String(ahead)); } catch (e) {}
            draw();
          });
          head.appendChild(span);
          head.appendChild(U.button("Show on the TV", enterTv, "go"));
        } else {
          head.appendChild(U.button("⛶", function () {
            var el = document.documentElement;
            if (el.requestFullscreen) { el.requestFullscreen().catch(function () {}); }
          }, "quiet board-full"));
        }
        main.appendChild(head);
        main.appendChild(U.el("div", { cls: "board", kids: cols.map(function (c) {
          return U.el("section", { cls: "board-col", attr: { "data-col": c.key },
            kids: [U.el("h3", { kids: [U.el("span", { text: c.label }),
                                       U.el("b", { text: String(c.cards.length) })] }),
                   U.el("div", { cls: "board-cards", kids: c.cards.length
                     ? c.cards.map(boardCard)
                     : [U.el("div", { cls: "board-none", text: "—" })] })] });
        }) }));
      }).catch(function (err) {
        if (active === "board") { U.notice(main, err.message); }
      });
    }

    function boardCard(c) {
      var pct = c.lines ? Math.round(100 * c.made / c.lines) : 0;
      return U.el("article", {
        cls: "board-card" + (c.late ? " late" : "") + (c.today ? " today" : "")
           + (c.priority ? " prio" : ""),
        attr: { "data-order": c.id },
        kids: [U.el("div", { cls: "who", text: (c.priority ? "★ " : "") + c.customer }),
               U.el("div", { cls: "meta", text: [c.order_no ? "O/N " + c.order_no : "",
                 c.due ? (c.late ? "LATE " : "Due ")
                   + c.due.slice(8, 10) + "/" + c.due.slice(5, 7) : ""]
                 .filter(Boolean).join("  ·  ") }),
               c.lines ? U.el("div", { cls: "bar", kids: [U.el("i", {
                 attr: { style: "width:" + pct + "%" } })],
                 attr: { title: c.made + " of " + c.lines + " lines made" } })
                       : U.el("span")]
      });
    }

    draw();
    clearInterval(boardTimer);
    // Every half minute while it is on the screen.
    boardTimer = setInterval(function () {
      if (active !== "board") { clearInterval(boardTimer); boardTimer = null; return; }
      if (!document.hidden) { draw(); }
    }, 30000);
  };

  // A phone or PC showing the board becomes the TV: no bars, big type, the
  // screen kept awake.
  function enterTv() {
    document.body.classList.add("tv");
    var el = document.documentElement;
    if (el.requestFullscreen) { el.requestFullscreen().catch(function () {}); }
    keepAwake();
    if (!enterTv._wired) {
      enterTv._wired = true;
      // Escape puts a PC back to normal; the TV itself never needs to.
      document.addEventListener("keydown", function (e) {
        if (e.key !== "Escape" || !document.body.classList.contains("tv")
            || /[?&]board=tv\b/.test(location.search) || U.sheetOpen()) { return; }
        document.body.classList.remove("tv");
        if (document.fullscreenElement && document.exitFullscreen) {
          document.exitFullscreen().catch(function () {});
        }
        show("board");
      });
    }
    show("board");
  }

  var wakeLock = null;
  function keepAwake() {
    if (!("wakeLock" in navigator)) { return; }
    function ask() {
      if (!document.body.classList.contains("tv") || document.hidden) { return; }
      navigator.wakeLock.request("screen").then(function (lock) {
        wakeLock = lock;
      }).catch(function () {});
    }
    ask();
    if (!keepAwake._wired) {
      keepAwake._wired = true;
      document.addEventListener("visibilitychange", ask);
    }
  }

  /* ── Quality checks ──────────────────────────────────────────────────
     The same lookup as floor.checks_for: the filter type's own list, or
     the list for every type ('*'). */

  function checksFor(type, lists) {
    var want = String(type || "").trim().toLowerCase();
    var keys = Object.keys(lists || {});
    function clean(list) {
      return (list || []).map(String).filter(function (c) { return c.trim(); });
    }
    for (var i = 0; i < keys.length; i++) {
      if (want && keys[i].trim().toLowerCase() === want) {
        return clean(lists[keys[i]]);
      }
    }
    return clean((lists || {})["*"]);
  }

  var QC_LISTS = null;
  function loadQcLists() {
    if (QC_LISTS) { return Promise.resolve(QC_LISTS); }
    return D.select("qc_checklists", { "select": "filter_type,checks" })
      .then(function (rows) {
        var out = {};
        (rows || []).forEach(function (r) { out[r.filter_type] = r.checks || []; });
        QC_LISTS = out;
        S.remember("qc_lists", out);
        return out;
      }).catch(function () {
        var box = S.recall("qc_lists");
        return (box && box.v) || {};
      });
  }

  // Resolves with what to keep on the line ({} for nothing to check), or
  // null when it was not passed.
  function qcBeforeMade(it) {
    if (!feature("qc_checklist")) { return Promise.resolve({}); }
    return loadQcLists().then(function (lists) {
      var checks = checksFor(it["Filter Type"] || it.product_type, lists);
      if (!checks.length) { return {}; }
      return new Promise(function (resolve) {
        var settled = false;
        function done(v) { if (!settled) { settled = true; resolve(v); } }
        U.openSheet(function (body, close) {
          body.appendChild(U.el("h2", { cls: "title",
            text: "Quality check: " + (it["Filter Type"] || "this line") }));
          body.appendChild(U.el("div", { cls: "muted",
            text: "Tick each one before it is marked made." }));
          var boxes = checks.map(function (c, i) {
            var box = U.el("input", { attr: { type: "checkbox",
                                              "data-check": String(i) } });
            body.appendChild(U.el("label", { cls: "qc-check", kids: [
              box, U.el("span", { text: c })] }));
            return box;
          });
          var ok = U.button("All checked - mark made", function () {
            if (!boxes.every(function (b) { return b.checked; })) {
              U.notice(body, "Tick every check - or if one fails, press It failed.");
              return;
            }
            done({ passed: true, checks: checks,
                   by: D.cachedProfile().full_name || D.cachedProfile().username || "",
                   at: stamp() });
            close();
          }, "go");
          ok.setAttribute("id", "qc-pass");
          var failed = U.button("It failed", function () {
            done(null);
            close();
            if (feature("fault_log")) { reportFault(null, it); }
          }, "quiet");
          failed.setAttribute("id", "qc-failed");
          body.appendChild(U.el("div", { cls: "row-actions", kids: [
            ok, failed, U.button("Cancel", function () { done(null); close(); }, "quiet")] }));
        });
      });
    });
  }

  /* ── Faults ──────────────────────────────────────────────────────────
     A filter that failed QC, or came back: which order and line, what was
     wrong, who made it, and a photo. The same reasons as floor.FAULT_REASONS. */

  var FAULT_REASONS = ["Wrong size", "Media damaged", "Frame or channel fault",
                       "Gaps or poor seal", "Wrong media", "Brace missing",
                       "Damaged in transit", "Other"];

  function reportFault(row, it, items) {
    row = row || reportFault._order || {};
    U.openSheet(function (body, close) {
      body.appendChild(U.el("h2", { cls: "title", text: "Record a fault" }));
      body.appendChild(U.el("div", { cls: "muted", text: [row.customer,
        row.order_no ? "O/N " + row.order_no : ""].filter(Boolean).join("  ·  ") }));
      var lines = (items || (it ? [it] : [])).filter(Boolean);
      var which = U.el("select", { attr: { id: "fault-line" },
        kids: lines.map(function (l, i) {
          return U.el("option", { text: "Line " + (i + 1) + ": " + lineName(l) + " "
                                       + lineSize(l), attr: { value: String(i) } });
        }) });
      if (it) { which.value = String(Math.max(0, lines.indexOf(it))); }
      var reason = U.el("select", { attr: { id: "fault-reason" },
        kids: FAULT_REASONS.map(function (r) {
          return U.el("option", { text: r, attr: { value: r } });
        }) });
      var found = U.el("select", { attr: { id: "fault-found" }, kids: [
        U.el("option", { text: "Found in QC", attr: { value: "qc" } }),
        U.el("option", { text: "Came back", attr: { value: "returned" } }),
        U.el("option", { text: "Found on site", attr: { value: "site" } })] });
      var qty = U.el("input", { attr: { type: "text", inputmode: "decimal",
                                        id: "fault-qty", value: "1" } });
      var detail = U.el("input", { attr: { type: "text", id: "fault-detail",
                                           placeholder: "What exactly (optional)" } });
      var photo = U.el("input", { attr: { type: "file", accept: "image/*",
                                          capture: "environment", id: "fault-photo" } });
      if (lines.length) {
        body.appendChild(U.el("label", { cls: "f", kids: [
          U.el("span", { text: "Which line" }), which] }));
      }
      [["What was wrong", reason], ["Where", found], ["How many", qty],
       ["More detail", detail], ["Photo", photo]].forEach(function (p) {
        body.appendChild(U.el("label", { cls: "f", kids: [
          U.el("span", { text: p[0] }), p[1]] }));
      });
      var save = U.button("Save", function () {
        var n = parseFloat(qty.value);
        if (!(n > 0)) { U.notice(body, "How many should be a number."); return; }
        var line = lines[parseInt(which.value, 10)] || it || {};
        save.disabled = true;
        var file = photo.files && photo.files[0];
        var sending = file
          ? D.upload(FILE_BUCKET, "faults/" + newId() + "."
                     + ((file.type || "").split("/")[1] || "jpg").split("+")[0],
                     file, file.type)
          : Promise.resolve("");
        sending.then(function (path) {
          return D.insert("returns", {
            order_id: row.id || null, order_number: row.order_no || "",
            customer_name: row.customer || "", quantity: n,
            reason: reason.value, detail: detail.value.trim(), found: found.value,
            line_id: line.line_id || "", filter_type: lineName(line) === "Filter"
              ? "" : lineName(line), made_by: line.made_by || "",
            photo_path: path || "",
            created_by: D.cachedProfile().full_name || D.cachedProfile().username || ""
          }, true);
        }).then(function () {
          D.insert("audit_log", {
            user_id: (D.whoami() || {}).id,
            username: D.cachedProfile().username || D.cachedProfile().full_name || "",
            action: "fault_recorded",
            details: "O/N: " + (row.order_no || "") + " | " + reason.value
          }, true).catch(function () {});
          close();
        }).catch(function (err) {
          save.disabled = false;
          U.notice(body, err.message);
        });
      }, "go");
      save.setAttribute("id", "fault-save");
      body.appendChild(U.el("div", { cls: "row-actions", kids: [
        save, U.button("Cancel", close, "quiet")] }));
    });
  }

  function newId() {
    if (window.crypto && crypto.randomUUID) { return crypto.randomUUID(); }
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 12);
  }

  /* ── The job timer ───────────────────────────────────────────────────
     Start on a line, Stop when it is done. Kept by the database with its
     own clock, so it needs signal - a timer that guessed would teach the
     wrong times. */

  function drawTimer(into, row, it) {
    if (!feature("job_timer") || !it.line_id) { return; }
    var btn = U.button("", null, "quiet timer");
    function paint() {
      var mine = RUNNING && RUNNING.order_id === row.id
                 && RUNNING.line_id === it.line_id;
      btn.textContent = mine ? "■ Stop" : "▶ Start";
      btn.classList.toggle("on", !!mine);
      btn.setAttribute("aria-label", (mine ? "Stop timing " : "Start timing ")
                       + lineName(it));
    }
    btn.addEventListener("click", function () {
      var mine = RUNNING && RUNNING.order_id === row.id
                 && RUNNING.line_id === it.line_id;
      btn.disabled = true;
      (mine ? D.rpc("stop_job_timer", {})
            : D.rpc("start_job_timer", { p_order_id: row.id, p_line_id: it.line_id }))
        .then(function (out) {
          var got = Array.isArray(out) ? out[0] : out;
          RUNNING = mine ? null : got;
          document.querySelectorAll("button.timer").forEach(function (b) {
            if (b._paint) { b._paint(); }
          });
          if (mine && got && got.minutes !== undefined) {
            U.notice(document.getElementById("sheet-body"),
                     "Took " + got.minutes + " min.", "ok");
          }
        }).catch(function (err) {
          U.notice(document.getElementById("sheet-body"), err.offline
            ? "The timer needs signal - it keeps the time itself." : err.message);
        }).then(function () { btn.disabled = false; });
    });
    btn._paint = paint;
    paint();
    into.appendChild(btn);
  }

  var RUNNING = null;
  function loadRunning() {
    if (!feature("job_timer")) { return Promise.resolve(null); }
    var me = (D.whoami() || {}).id;
    return D.select("job_times", { "select": "*", "user_id": "eq." + me,
                                   "stopped_at": "is.null", "limit": 1 })
      .then(function (rows) { RUNNING = (rows && rows[0]) || null; return RUNNING; })
      .catch(function () { return RUNNING; });
  }

  /* ── Is there room on the day it is due? ─────────────────────────────
     The same rules as planning.py (check_due and describe) - a test holds
     the two together. */

  var DONE_STATUSES = ["Complete", "Dispatched", "Delivered", "Collected"];
  var DAY_LONG = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday",
                  "Friday", "Saturday"];

  function num(v, d) {
    var n = parseFloat(String(v === undefined || v === null ? "" : v)
                       .replace(/,/g, "").trim());
    return isFinite(n) ? n : (d || 0);
  }

  function rateMap(rates) {
    var out = {};
    (rates || []).forEach(function (r) {
      var m = num(r.minutes_each);
      if (m > 0) { out[String(r.filter_type || "").trim().toLowerCase()] = m; }
    });
    return out;
  }

  function lineMinutes(it, rates, def) {
    if (it.made) { return 0; }
    if (String(it.item_kind || "filter") === "catalogue") { return 0; }
    var qty = num(it.Quantity !== undefined ? it.Quantity : it.quantity);
    var kind = String(it["Filter Type"] || it.product_type || "").trim().toLowerCase();
    return Math.max(0, qty) * (rates[kind] !== undefined ? rates[kind] : def);
  }

  function orderMinutes(items, rates, def) {
    return (items || []).reduce(function (t, it) {
      return t + (it && typeof it === "object" ? lineMinutes(it, rates, def) : 0);
    }, 0);
  }

  function sameDay(a, b) { return !!(a && b) && ymd(a) === ymd(b); }

  function asDay(v) {
    if (v instanceof Date) { return v; }
    return U.parseDate(v);
  }

  function bookedMinutes(orders, day, rates, def, skipId) {
    return (orders || []).reduce(function (t, o) {
      var h = o.header || {};
      var status = String(h.status || o.status || "Pending");
      if (DONE_STATUSES.indexOf(status) >= 0 || o.archived) { return t; }
      if (skipId !== undefined && skipId !== null && String(o.id) === String(skipId)) {
        return t;
      }
      if (!sameDay(asDay(o.date_due), day)) { return t; }
      return t + orderMinutes(o.items || [], rates, def);
    }, 0);
  }

  function onLeave(person, day, leave) {
    return (leave || []).some(function (l) {
      if (String(l.person || "").trim().toLowerCase()
          !== String(person).trim().toLowerCase()) { return false; }
      var a = asDay(l.first_day), b = asDay(l.last_day);
      return !!(a && b && a <= day && day <= b);
    });
  }

  function shutOn(day, shutdowns) {
    var hit = (shutdowns || []).filter(function (s) { return sameDay(asDay(s.day), day); })[0];
    return hit ? String(hit.name || "Shut") : "";
  }

  function availableOn(day, roster, leave, shutdowns, share) {
    var shut = shutOn(day, shutdowns), inn = [], away = [], minutes = 0;
    var iso = day.getDay() === 0 ? 7 : day.getDay();
    (roster || []).forEach(function (r) {
      if (r.makes === false || r.active === false) { return; }
      var days = (r.days || []).map(function (d) { return parseInt(d, 10); });
      if (days.indexOf(iso) < 0) { return; }
      var name = String(r.person || "");
      if (onLeave(name, day, leave)) { away.push(name); return; }
      inn.push(name);
      minutes += num(r.hours) * 60 * share;
    });
    if (shut) { minutes = 0; }
    return { minutes: minutes, "in": inn, away: away, shut: shut };
  }

  function checkDue(dayText, items, orders, rates, roster, leave, shutdowns,
                    workshop, skipId, lookAhead) {
    var due = asDay(dayText);
    roster = (roster || []).filter(function (r) {
      return r.makes !== false && r.active !== false;
    });
    if (!due || !roster.length) { return null; }
    var byType = rateMap(rates);
    var def = num((workshop || {}).minutes_per_filter, 15) || 15;
    var share = num((workshop || {}).making_share, 0.8) || 0.8;
    var need = orderMinutes(items, byType, def);
    function on(d) {
      var room = availableOn(d, roster, leave, shutdowns, share);
      room.booked = bookedMinutes(orders, d, byType, def, skipId);
      return room;
    }
    var here = on(due);
    var full = here.booked + need > here.minutes;
    var next = null;
    if (full) {
      var d = new Date(due.getTime());
      for (var i = 0; i < (lookAhead || 15); i++) {
        d.setDate(d.getDate() + 1);
        var room = on(d);
        if (room.minutes && room.booked + need <= room.minutes) {
          next = new Date(d.getTime());
          break;
        }
      }
    }
    return { day: due, need: need, booked: here.booked, minutes: here.minutes,
             "in": here["in"], away: here.away, shut: here.shut, full: full,
             next_free: next };
  }

  function hrs(m) { return String(Math.round(m / 60 * 10) / 10) + " h"; }
  function dayName(d) {
    return DAY_LONG[d.getDay()] + " " + pad2(d.getDate()) + "/" + pad2(d.getMonth() + 1);
  }

  function describeFull(r) {
    var name = dayName(r.day), head;
    if (r.shut) {
      head = name + " is a shutdown day (" + r.shut + ").";
    } else if (!r.minutes) {
      head = "Nobody is rostered to make filters on " + name + ".";
    } else {
      head = name + " is already full: " + hrs(r.booked) + " booked, and this "
           + "order adds " + hrs(r.need) + ", against " + hrs(r.minutes)
           + " with " + r["in"].length + " in"
           + (r.away.length ? " (" + r.away.join(", ") + " away)." : ".");
    }
    if (r.next_free) { head += " " + dayName(r.next_free) + " has room."; }
    return head;
  }

  // Everything check_due needs, fetched together. Resolves with "" when the
  // day fits or there is nothing to measure against.
  function capacityWarning(dayText, items) {
    if (!feature("capacity_check") || !U.parseDate(dayText)) {
      return Promise.resolve("");
    }
    var keys = ["minutes_per_filter", "making_share"];
    return Promise.all([
      D.select("staff_roster", { "select": "*" }),
      D.select("staff_leave", { "select": "*" }),
      D.select("shutdown_days", { "select": "day,name" }).catch(function () { return []; }),
      D.select("job_rates", { "select": "*" }).catch(function () { return []; }),
      D.select("workshop_settings", { "select": "key,value",
                                      "key": "in.(" + keys.join(",") + ")" })
        .catch(function () { return []; }),
      // Only what is still to make: no status yet, or one not finished.
      D.select("orders", { "select": "id,date_due,header,items,archived",
                           "archived": "eq.false", "limit": 1000,
                           "or": "(header->>status.is.null,header->>status.not.in.("
                                 + DONE_STATUSES.join(",") + "))" })
    ]).then(function (got) {
      var ws = {};
      (got[4] || []).forEach(function (r) { ws[r.key] = r.value; });
      var r = checkDue(dayText, items, got[5], got[3], got[0], got[1], got[2], ws);
      return r && r.full ? describeFull(r) : "";
    }).catch(function () { return ""; });   // never stop an order over a check
  }

  /* ── Winning the work ────────────────────────────────────────────────
     The same rules as sales.py (to_chase, chase_email, service_due) - a
     test holds the two together. */

  var CHASE_AFTER = 7;
  var LOST_REASONS = ["Price", "Lead time", "Went elsewhere", "No longer needed",
                      "No reply", "Other"];

  function daysBetween(a, b) {
    return Math.round((b.getTime() - a.getTime()) / 86400000);
  }

  function toChase(quotes, today, after) {
    after = after || CHASE_AFTER;
    return (quotes || []).filter(function (q) {
      if (["sent", "viewed"].indexOf(String(q.status || "")) < 0) { return false; }
      var sent = U.parseDate(q.sent_at);
      if (!sent || daysBetween(sent, today) < after) { return false; }
      var chased = U.parseDate(q.chased_at);
      return !(chased && daysBetween(chased, today) < after);
    }).map(function (q) {
      return Object.assign({}, q, { waited: daysBetween(U.parseDate(q.sent_at), today) });
    }).sort(function (a, b) {
      if (a.waited !== b.waited) { return b.waited - a.waited; }
      var na = String(a.quote_number || ""), nb = String(b.quote_number || "");
      return na < nb ? -1 : (na > nb ? 1 : 0);
    });
  }

  function money2(n) {
    return Number(n).toLocaleString("en-AU", { minimumFractionDigits: 2,
                                               maximumFractionDigits: 2 });
  }

  function chaseEmail(q, link, company, contact) {
    company = company || "Total Air Filtration";
    var number = String(q.quote_number || "").trim();
    var first = String(contact || "").trim().split(/\s+/)[0];
    var hello = first ? "Hi " + first + "," : "Hi,";
    var worth = Number(q.total || 0) > 0 ? " ($" + money2(q.total) + " inc GST)" : "";
    return {
      subject: ("Quote " + number + " from " + company).replace(/  /g, " ").trim(),
      body: hello + "\n\nJust following up on our quote " + number + worth
          + ". You can read it and accept it online here:\n\n" + link + "\n\n"
          + "If anything needs changing - sizes, quantities or timing - reply "
          + "to this email and we'll sort it out.\n\nThanks,\n" + company
    };
  }

  function mailtoLink(to, subject, body) {
    return "mailto:" + encodeURIComponent(String(to || "").trim())
                         .replace(/%40/g, "@").replace(/%2C/g, ",")
         + "?subject=" + encodeURIComponent(subject)
         + "&body=" + encodeURIComponent(body);
  }

  function serviceDue(customers, orders, today, ahead) {
    ahead = ahead === undefined ? 14 : ahead;
    var last = {};
    (orders || []).forEach(function (o) {
      var name = String(o.customer_name || o.customer || "").trim().toLowerCase();
      var d = U.parseDate(o.date_ordered) || U.parseDate(o.created_at);
      if (name && d && (!last[name] || d > last[name])) { last[name] = d; }
    });
    var out = [];
    (customers || []).forEach(function (c) {
      var weeks = parseInt(c.service_weeks, 10) || 0;
      if (weeks <= 0) { return; }
      var snoozed = U.parseDate(c.service_snoozed_until);
      if (snoozed && snoozed > today) { return; }
      var seen = ["name", "short_name"].map(function (k) {
        return last[String(c[k] || "").trim().toLowerCase()];
      }).filter(Boolean);
      if (!seen.length) { return; }
      var prev = new Date(Math.max.apply(null, seen.map(function (d) { return d.getTime(); })));
      var due = new Date(prev.getTime());
      due.setDate(due.getDate() + 7 * weeks);
      var limit = new Date(today.getTime());
      limit.setDate(limit.getDate() + ahead);
      if (due > limit) { return; }
      out.push({ customer: c, last: prev, due: due,
                 late: due < today ? daysBetween(due, today) : 0 });
    });
    return out.sort(function (a, b) {
      if (a.due.getTime() !== b.due.getTime()) { return a.due - b.due; }
      var na = String(a.customer.name || ""), nb = String(b.customer.name || "");
      return na < nb ? -1 : (na > nb ? 1 : 0);
    });
  }

  // Hands the email to the phone's mail app. A variable so a test can
  // watch what would have been sent.
  var openMail = function (link) { window.location.href = link; };

  function quoteLinkFor(token) {
    var base = new URL("../quote/", location.href).href;
    return base + "?t=" + encodeURIComponent(token) + "&k="
         + encodeURIComponent(D.anonKey());
  }

  // Today: quotes to chase, each with an email ready to send.
  function chaseCard(main) {
    var card = U.card("Quotes to chase", [U.el("div", { cls: "muted", text: "Loading…" })]);
    card.setAttribute("id", "chase-card");
    main.appendChild(card);
    D.select("quotes", { "select": "id,quote_number,customer_id,customer_name,"
                         + "status,total,sent_at,chased_at,public_token",
                         "status": "in.(sent,viewed)", "limit": 300 })
      .then(function (rows) {
        var list = toChase(rows, U.today());
        while (card.childNodes.length > 1) { card.removeChild(card.lastChild); }
        if (!list.length) {
          card.appendChild(U.empty("Nothing to chase.",
            "Quotes with no answer after a week show here."));
          return;
        }
        list.slice(0, 10).forEach(function (q) {
          var go = U.button("Chase", function () { chase(q, go); }, "quiet");
          card.appendChild(U.el("div", { cls: "chase-row",
            attr: { "data-quote": q.id }, kids: [
              U.el("div", { kids: [
                U.el("b", { text: (q.quote_number || "Quote") + " · "
                                  + (q.customer_name || "") }),
                U.el("div", { cls: "muted", text: "Waiting " + q.waited + " days"
                  + (q.total ? " · $" + money2(q.total) : "") })] }),
              go] }));
        });
      }).catch(function () { card.remove(); });
  }

  function chase(q, btn) {
    btn.disabled = true;
    (q.customer_id
      ? D.select("customers", { "select": "email,contact_name",
                                "id": "eq." + q.customer_id })
      : Promise.resolve([])).then(function (rows) {
      var c = (rows && rows[0]) || {};
      var mail = chaseEmail(q, quoteLinkFor(q.public_token || ""), null, c.contact_name);
      chase._last = mailtoLink(c.email || "", mail.subject, mail.body);
      D.rpc("quote_chased", { p_id: q.id }).catch(function () {});
      openMail(chase._last);
      btn.textContent = "Chased";
    }).catch(function () { btn.disabled = false; });
  }

  // Today: customers due a filter change.
  function serviceCard(main, orders) {
    var card = U.card("Due for a filter change", [
      U.el("div", { cls: "muted", text: "Loading…" })]);
    card.setAttribute("id", "service-card");
    main.appendChild(card);
    D.select("customers", { "select": "*", "service_weeks": "not.is.null" })
      .then(function (custs) {
        var list = serviceDue(custs, orders, U.today());
        while (card.childNodes.length > 1) { card.removeChild(card.lastChild); }
        if (!list.length) {
          card.appendChild(U.empty("Nobody is due in the next fortnight."));
          return;
        }
        list.slice(0, 10).forEach(function (r) {
          var kids = [U.el("div", { kids: [
            U.el("b", { text: r.customer.name || "" }),
            U.el("div", { cls: "muted", text: (r.late ? r.late + " days late"
              : "Due " + pad2(r.due.getDate()) + "/" + pad2(r.due.getMonth() + 1))
              + " · every " + r.customer.service_weeks + " weeks" })] })];
          if (feature("order_again")) {
            kids.push(U.button("Order again", function () {
              var name = String(r.customer.name || "").trim().toLowerCase();
              var short = String(r.customer.short_name || "").trim().toLowerCase();
              var last = ORDERS.filter(function (o) {
                var n = String(o.customer || "").trim().toLowerCase();
                return n === name || (short && n === short);
              })[0];
              if (!last) { return; }
              D.select("orders", { "id": "eq." + last.id, "select": "items,header" })
                .then(function (rows) {
                  var o = (rows && rows[0]) || {};
                  orderAgain(last, o.items || [], o.header || last.header);
                });
            }, "quiet"));
          }
          card.appendChild(U.el("div", { cls: "chase-row",
            attr: { "data-customer": r.customer.id }, kids: kids }));
        });
      }).catch(function () { card.remove(); });
  }

  /* ── Stocktake on the phone ──────────────────────────────────────────
     The count session the desktop runs (records.py): walk the racks, find
     each item (or scan its label with a gun that types), type what is on
     the shelf. Each count goes through count_stock, which is the same done
     twice as once, so a phone with no signal keeps them and sends them
     later. A manager finishes it - applying the differences or not. */

  SCREENS.count = function (main) {
    if (!feature("stocktake")) {
      U.clear(main);
      main.appendChild(U.empty("Stocktakes are switched off.",
        "A director or admin turns them on in the desktop app: Settings → "
        + "Features → Stocktake mode."));
      return;
    }
    D.select("stocktakes", { "select": "*", "finished_at": "is.null",
                             "order": "started_at.desc", "limit": 1 })
      .then(function (rows) {
        var take = (rows || [])[0];
        if (!take) { return noCount(main); }
        return Promise.all([
          loadKept("stock", function () {
            return D.select("stock_items", { "select": "*", "order": "name",
                                             "limit": 2000 });
          }),
          D.select("stocktake_counts", { "select": "item_id,counted,was,counted_by",
                                         "stocktake_id": "eq." + take.id,
                                         "limit": 5000 }).catch(function () { return []; })
        ]).then(function (got) { counting(main, take, got[0].rows, got[1]); });
      }).catch(function (err) {
        U.clear(main);
        U.notice(main, err.message);
      });
  };

  function noCount(main) {
    U.clear(main);
    var name = U.el("input", { attr: { type: "text", id: "count-name",
                                       placeholder: "e.g. Back racks, October" } });
    var go = U.button("Start a count", function () {
      go.disabled = true;
      D.insert("stocktakes", { name: name.value.trim() || ymd(new Date()),
        started_by: D.cachedProfile().full_name || D.cachedProfile().username || "" })
        .then(function () { show("count"); })
        .catch(function (err) { go.disabled = false; U.notice(main, err.message); });
    }, "go");
    go.setAttribute("id", "count-start");
    main.appendChild(U.card("No count going", [
      U.el("div", { cls: "muted", text: "Start one, and everybody counting "
        + "adds to the same count - on phones and PCs." }),
      U.el("label", { cls: "f", kids: [U.el("span", { text: "Name it" }), name] }),
      U.el("div", { cls: "row-actions", kids: [go] })]));
  }

  function counting(main, take, stock, counts) {
    var done = {};
    (counts || []).forEach(function (c) { done[c.item_id] = c; });
    U.clear(main);
    var head = U.el("div", { cls: "muted" });
    var find = U.el("input", { attr: { type: "search", id: "count-find",
      placeholder: "Find an item, or scan its label", autocomplete: "off" } });
    var list = U.el("div", { cls: "count-list", attr: { id: "count-list" } });
    var acts = U.el("div", { cls: "row-actions" });
    if (D.roleLevel() >= 3) {
      var fin = U.button("Finish the count…", function () {
        finishCount(take, stock, done);
      }, "quiet");
      fin.setAttribute("id", "count-finish");
      acts.appendChild(fin);
    }
    main.appendChild(U.card(take.name || "Stocktake", [head, find, list, acts]));

    function matches(s, words) {
      var hay = [s.name, s.sku, s.location, s.product_type].map(function (v) {
        return String(v || ""); }).join(" ").toLowerCase();
      return words.every(function (w) { return hay.indexOf(w) >= 0; });
    }

    function draw() {
      var words = find.value.toLowerCase().split(/\s+/).filter(Boolean);
      var hits = stock.filter(function (s) { return matches(s, words); });
      // Not counted first, then the rest - each by where it is kept.
      hits.sort(function (a, b) {
        var ca = done[a.id] ? 1 : 0, cb = done[b.id] ? 1 : 0;
        if (ca !== cb) { return ca - cb; }
        var la = String(a.location || "") + String(a.name || "");
        var lb = String(b.location || "") + String(b.name || "");
        return la < lb ? -1 : (la > lb ? 1 : 0);
      });
      var n = Object.keys(done).length;
      var out = Object.keys(done).filter(function (k) {
        return Number(done[k].counted) !== Number(done[k].was);
      }).length;
      head.textContent = n + " of " + stock.length + " counted"
        + (out ? "  ·  " + out + " not what the system says" : "");
      U.clear(list);
      hits.slice(0, 80).forEach(function (s) {
        var c = done[s.id];
        var off = c && Number(c.counted) !== Number(c.was);
        list.appendChild(U.el("button", {
          cls: "count-row" + (c ? " done" : "") + (off ? " off" : ""),
          attr: { type: "button", "data-stock": s.id },
          on: { click: function () { countOne(s); } },
          kids: [U.el("span", { cls: "nm", text: s.name || "" }),
                 U.el("span", { cls: "muted", text: [s.sku, s.location]
                   .filter(Boolean).join(" · ") }),
                 U.el("b", { text: c ? qtyText(c.counted) + (off ? " (system "
                   + qtyText(c.was) + ")" : " ✓") : "—" })]
        }));
      });
      if (!hits.length) {
        list.appendChild(U.empty("Nothing matches.", "Try fewer words."));
      }
    }

    // A gun that types the label and presses Enter: straight to that item.
    find.addEventListener("keydown", function (e) {
      if (e.key !== "Enter") { return; }
      var code = find.value.trim().toLowerCase();
      var hit = stock.filter(function (s) {
        return String(s.sku || "").toLowerCase() === code;
      })[0];
      if (hit) { e.preventDefault(); find.value = ""; draw(); countOne(hit); }
    });
    find.addEventListener("input", draw);

    function countOne(s) {
      U.openSheet(function (body, close) {
        body.appendChild(U.el("h2", { cls: "title", text: s.name || "Item" }));
        body.appendChild(U.el("div", { cls: "muted", text: [s.sku, s.location,
          "The system says " + qtyText(s.stock_on_hand) + " "
          + unitLabel(s.unit, s.stock_on_hand)].filter(Boolean).join(" · ") }));
        var n = U.el("input", { attr: { type: "text", inputmode: "decimal",
          id: "count-qty", placeholder: "How many on the shelf",
          value: done[s.id] ? String(done[s.id].counted) : "" } });
        body.appendChild(U.el("label", { cls: "f big-number", kids: [
          U.el("span", { text: "Counted (" + unitLabel(s.unit, 2) + ")" }), n] }));
        var save = U.button("Save the count", function () {
          var v = parseFloat(String(n.value).trim());
          if (!(v >= 0)) { U.notice(body, "How many, as a number."); return; }
          save.disabled = true;
          S.send({
            rpc: "count_stock",
            label: "Count · " + (s.name || "item") + " = " + v,
            needs_row: true,
            gone: "That count has been finished, so it was not added.",
            body: { p_stocktake: take.id, p_item: s.id, p_counted: v,
                    p_by: D.cachedProfile().full_name || D.cachedProfile().username || "" }
          }).then(function (res) {
            done[s.id] = { item_id: s.id, counted: v, was: s.stock_on_hand,
                           queued: !!res.queued };
            close();
            draw();
            find.focus();
          }).catch(function (err) {
            save.disabled = false;
            U.notice(body, err.message);
          });
        }, "go");
        save.setAttribute("id", "count-save");
        n.addEventListener("keydown", function (e) {
          if (e.key === "Enter") { e.preventDefault(); save.click(); }
        });
        body.appendChild(U.el("div", { cls: "row-actions", kids: [
          save, U.button("Cancel", close, "quiet")] }));
        setTimeout(function () { n.focus(); }, 50);
      });
    }

    draw();
  }

  function finishCount(take, stock, done) {
    var byId = {};
    stock.forEach(function (s) { byId[s.id] = s; });
    U.openSheet(function (body, close) {
      body.appendChild(U.el("h2", { cls: "title", text: "Finish the count" }));
      var off = Object.keys(done).filter(function (k) {
        return Number(done[k].counted) !== Number(done[k].was);
      });
      body.appendChild(U.el("div", { cls: "muted", text: Object.keys(done).length
        + " counted, " + (stock.length - Object.keys(done).length)
        + " not counted, " + off.length + " not what the system says." }));
      if (off.length) {
        body.appendChild(U.table(["Item", { text: "System", num: true },
                                  { text: "Counted", num: true }],
          off.map(function (k) {
            return U.el("tr", { kids: [U.cell((byId[k] || {}).name || ""),
              U.cell(qtyText(done[k].was), { num: true }),
              U.cell(qtyText(done[k].counted), { num: true })] });
          })));
      }
      function finish(apply) {
        var who = D.cachedProfile().full_name || D.cachedProfile().username || "";
        (apply ? D.rpc("apply_stocktake", { p_stocktake: take.id })
               : Promise.resolve(null)).then(function () {
          return D.update("stocktakes", { "id": "eq." + take.id },
                          { finished_at: new Date().toISOString(), finished_by: who });
        }).then(function () {
          close();
          show("count");
        }).catch(function (err) { U.notice(body, err.message); });
      }
      var apply = U.button("Finish, and set stock to what was counted",
                           function () { finish(true); }, "go");
      apply.setAttribute("id", "count-apply");
      body.appendChild(U.el("div", { cls: "row-actions", kids: [apply,
        U.button("Finish without changing stock", function () { finish(false); },
                 "quiet"),
        U.button("Not yet", close, "quiet")] }));
    });
  }

  /* ── Order again ─────────────────────────────────────────────────────
     The same lines on a new order: nothing made or checked, no old line
     ids (planning.repeat_items). */

  function repeatItems(items) {
    return (items || []).filter(function (it) { return it && typeof it === "object"; })
      .map(function (it) {
        var out = {};
        Object.keys(it).forEach(function (k) {
          if (k.indexOf("made") === 0 || k === "qc" || k === "line_id") { return; }
          out[k] = it[k];
        });
        return out;
      });
  }

  function orderAgain(row, items, header) {
    var h = header || row.header || {};
    DRAFT = { header: { "Customer Name": row.customer || "",
                        "Job": h.Job || "", "Attention": h.Attention || "",
                        "Location": h.Location || "", "Date Due": "ASAP" },
              items: repeatItems(items) };
    U.closeAllSheets();
    show("new");
    U.notice(document.getElementById("screen"),
      "The lines from " + (row.order_no ? "order " + row.order_no : "their last order")
      + " are on a new order - put in their order number and save it.", "ok");
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
      if (f.kind === "finished") { return "✅  Finished job"; }
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
    // The finished job: what the customer sees on their portal, and - with
    // the switch on - what lets it be marked Complete.
    if (feature("finished_photo")) {
      var done = U.el("input", {
        attr: { type: "file", accept: "image/*", capture: "environment",
                style: "display:none", id: "finished-pick" } });
      done.addEventListener("change", function () {
        var file = done.files && done.files[0];
        if (!file) { return; }
        sendFinished(row, file, body).then(function (ok) { if (ok) { reload(); } });
        done.value = "";
      });
      wrap.appendChild(done);
      var btn = U.button("✅  Finished job photo", function () { done.click(); }, "go");
      btn.setAttribute("id", "finished-photo");
      wrap.appendChild(btn);
    }
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

  // Into the public job-photos bucket under a name nobody can guess, so the
  // customer's portal can show it without a sign-in.
  function sendFinished(row, blob, body) {
    var ext = ((blob.type || "").split("/")[1] || "jpg").split("+")[0];
    var path = row.id + "/" + newId() + "." + ext;
    U.notice(body, "Sending…", "ok");
    return D.upload("job-photos", path, blob, blob.type).then(function () {
      return D.insert("order_files", {
        order_id: row.id, kind: "finished", path: path, bucket: "job-photos",
        caption: "Finished job",
        taken_by: D.cachedProfile().full_name || D.cachedProfile().username || ""
      });
    }).then(function () {
      U.notice(body, "Finished-job photo kept - the customer sees it on "
                   + "their portal.", "ok");
      return true;
    }).catch(function (err) {
      U.notice(body, err.message);
      return false;
    });
  }

  function openFile(f, body) {
    (f.bucket === "job-photos"
      ? Promise.resolve(D.publicUrl("job-photos", f.path))
      : D.signedUrl(FILE_BUCKET, f.path, 3600)).then(function (url) {
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
                if (!ok) { return; }
                if (feature("pod_email")) { proofOfDelivery(row, body); }
                closeInner();
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

  /* Signed for: it has been delivered. The order says so, and the customer
     is emailed the signature and the photos from the drop (the
     proof-of-delivery function, which reads the switch for itself and sends
     one signature once). */
  function proofOfDelivery(row, body) {
    var already = ["Delivered", "Collected"].indexOf(row.status) !== -1;
    (already ? Promise.resolve(true)
      : D.rpc("merge_order_header", {
          p_order_id: row.id, p_patch: { status: "Delivered" } })
        .then(function () {
          row.status = "Delivered";
          loadedAt = 0;
          xeroNudge("Delivered");
        })
    ).then(function () {
      return D.callFunction("proof-of-delivery", { order_id: row.id });
    }).then(function (out) {
      U.notice(body, out.sent
        ? "Delivered - the signature and photos are emailed to " + out.to + "."
        : "Delivered. " + (out.reason || ""), "ok");
    }).catch(function (err) {
      U.notice(body, "Signature kept, but: " + err.message);
    });
  }

  /* ── The screen at the saw ───────────────────────────────────────────
     The marks the desktop worked out, shown on the phone that is already in
     somebody's hand at the machine. Deliberately only a display: the maths
     lives in Python, and a second copy of it here would eventually give a
     different answer on a Tuesday. If no plan has been worked out, this
     says nothing at all rather than guessing at one. */

  function drawCutPlan(body, header) {
    var plan = header.cut_plan;
    if (!plan || !plan.lengths || !plan.lengths.length) { return; }
    var rows = plan.lengths.map(function (b) {
      return U.el("tr", { kids: [
        U.cell(b.size || ""),
        U.cell(b.how || ""),
        U.cell(b.off || 1, { num: true }),
        U.cell((b.marks || []).join("   "), { }),
        U.cell(b.lip && b.lip !== 20 ? b.lip + "mm" : "")
      ] });
    });
    var note = plan.sticks
      ? plan.sticks + " length" + (plan.sticks === 1 ? "" : "s")
        + " of channel" + (plan.at ? ", worked out " + plan.at : "")
      : "";
    var kids = [U.table(["Size", "As", { text: "Off", num: true },
                         "Mark at", "Lip"], rows)];
    if (note) { kids.push(U.el("div", { cls: "muted", text: note })); }
    if (plan.used) {
      kids.push(U.el("div", { cls: "muted",
        text: "It actually took " + plan.used + "." }));
    }
    body.appendChild(U.card("How to cut it", kids));
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
  /* A finished job's invoice is approved and emailed by the xero function.
     The database has already noted the day it was finished, and a PC or the
     scheduled sweep would get to it within minutes; asking now just means it
     goes now. Nothing is said either way: it is not this screen's job, and
     Xero not being linked is not a fault. */
  function xeroNudge(status) {
    if (["Complete", "Dispatched", "Delivered"].indexOf(status) === -1) { return; }
    D.callFunction("xero?do=sweep", {}).catch(function () {});
  }

  function drawStatus(actions, row, body, pill, close) {
    U.clear(actions);
    if (feature("fault_log")) {
      actions.appendChild(U.button("⚠  Record a fault", function () {
        reportFault(row, null, row._items || []);
      }, "quiet"));
    }
    if (feature("order_again") && (row._items || []).length) {
      var again = U.button("↻  Order again", function () {
        orderAgain(row, row._items, row.header);
      }, "quiet");
      again.setAttribute("id", "order-again");
      actions.appendChild(again);
    }
    ["In Production", "Complete", "Dispatched"].forEach(function (want) {
      if (row.status === want) { return; }
      actions.appendChild(U.button(want, function () {
        var gone = ["Complete", "Dispatched", "Delivered", "Collected"];
        if (feature("finished_photo") && gone.indexOf(want) >= 0
            && gone.indexOf(row.status) < 0) {
          D.select("order_files", { "select": "id", "order_id": "eq." + row.id,
                                    "kind": "eq.finished", "limit": 1 })
            .then(function (got) {
              if (got && got.length) { setStatus(); return; }
              U.notice(body, "Take a photo of the finished job first - "
                           + "press Finished job photo above.");
            }).catch(setStatus);       // no signal: let it queue, as before
          return;
        }
        setStatus();
      }, want === "Complete" ? "go" : "quiet"));

      function setStatus() {
        // merge_order_header patches the header rather than writing a whole
        // one back, so the same patch arriving twice leaves the same status
        // and nobody's notes are lost on the way.
        S.send({
          rpc: "merge_order_header",
          label: (row.customer || "Order") + " → " + want,
          needs_row: true,
          gone: "That order is not there any more.",
          log: {
            action: "order_status",
            details: "O/N: " + (row.order_no || "") + " | Customer: "
                   + (row.customer || "") + " | Status: " + row.status
                   + " → " + want
          },
          body: { p_order_id: row.id, p_patch: { status: want } }
        }).then(function (out) {
          row.status = want;
          pill.className = "pill s-" + want.replace(/\s+/g, "");
          pill.textContent = want;
          loadedAt = 0;
          drawStatus(actions, row, body, pill, close);
          if (!out.queued) { xeroNudge(want); }
          U.notice(body, out.queued
            ? "Set to " + want + " on this phone, and waiting for signal."
            : "Status set to " + want + ".", "ok");
        }).catch(function (err) { U.notice(body, err.message); });
      }
    });
    actions.appendChild(U.button("Close", close, "quiet"));
  }

  /* ── Who did what ────────────────────────────────────────────────────
     The same audit_log the desktop's Audit Log tab reads, and the same
     wording in it, so one day's work reads as one list whichever screen
     each thing was done on. Managers and above only, which the database
     enforces — the tab is simply not offered below that. */

  SCREENS.log = function (main) {
    D.select("audit_log", {
      "select": "*", "order": "created_at.desc", "limit": 500
    }).then(function (rows) {
      U.clear(main);
      var search = U.el("input", {
        attr: { type: "search", placeholder: "Order number, customer, action" }
      });
      var people = [];
      rows.forEach(function (r) {
        var who = r.username || "";
        if (who && people.indexOf(who) === -1) { people.push(who); }
      });
      people.sort();
      var who = U.el("select", {
        kids: ["Everyone"].concat(people).map(function (t) {
          return U.el("option", { text: t });
        })
      });
      var when = U.el("select", {
        kids: ["Today", "Last 7 days", "Everything"].map(function (t) {
          return U.el("option", { text: t });
        })
      });

      var out = U.el("div");

      function redraw() {
        var q = search.value.trim().toLowerCase();
        var cut = 0;
        if (when.value === "Today") { cut = U.today().getTime(); }
        else if (when.value === "Last 7 days") {
          cut = U.today().getTime() - 6 * 86400000;
        }
        var list = rows.filter(function (r) {
          if (who.value !== "Everyone" && (r.username || "") !== who.value) {
            return false;
          }
          if (cut && new Date(r.created_at).getTime() < cut) { return false; }
          if (!q) { return true; }
          return [r.username, r.action, r.details].join(" ")
                 .toLowerCase().indexOf(q) !== -1;
        });
        U.clear(out);
        if (!list.length) {
          out.appendChild(U.card(null, [U.empty("Nothing here",
            "Nobody has done anything matching that.")]));
          return;
        }
        out.appendChild(U.card(list.length + " entr"
          + (list.length === 1 ? "y" : "ies"),
          [U.table(["When", "Who", "What", "Details"],
            list.slice(0, 400).map(function (r) {
              return U.el("tr", {
                kids: [U.cell(stampOf(r.created_at)),
                       U.cell(r.username || "—"),
                       U.cell(wording(r.action)),
                       U.cell(r.details || "")]
              });
            }))]));
      }

      U.onPick([search, who, when], redraw);
      main.appendChild(U.card(null, [
        U.el("div", { cls: "filters", kids: [
          U.el("label", { cls: "f", kids: [
            U.el("span", { text: "Search" }), search] }),
          U.el("label", { cls: "f", kids: [
            U.el("span", { text: "Who" }), who] }),
          U.el("label", { cls: "f", kids: [
            U.el("span", { text: "When" }), when] })
        ] })
      ]));
      main.appendChild(out);
      redraw();
    }).catch(function (err) {
      U.clear(main);
      U.notice(main, /not allowed/i.test(err.message || "")
        ? "Only a manager can read the log."
        : err.message);
    });
  };

  function stampOf(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) { return String(iso || "").slice(0, 16); }
    function two(n) { return (n < 10 ? "0" : "") + n; }
    var day = two(d.getDate()) + "/" + two(d.getMonth() + 1);
    var time = two(d.getHours()) + ":" + two(d.getMinutes());
    return d >= U.today() ? time : day + "  " + time;
  }

  /* order_status becomes "Order status". The desktop does the same, and the
     two lists sit next to each other on somebody's desk. */
  function wording(action) {
    var text = String(action || "").replace(/_/g, " ").trim();
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
  }

  /* ── A phone left on the bench ───────────────────────────────────────
     These are shared. One gets put down next to a machine with somebody
     signed in, and the next person to pick it up is them as far as the log
     is concerned. So after half an hour of nothing at all it asks, and then
     signs out.

     It will not sign out over unsent work: that would strand it on the
     phone under an account nobody can send it with. In that case it says so
     and stays put, which out of signal is the honest answer anyway. */

  var IDLE_MS = 30 * 60 * 1000;
  var GRACE_S = 60;
  var touched = Date.now();
  var asking = false;

  function watchIdle() {
    ["pointerdown", "keydown", "touchstart", "focus"].forEach(function (e) {
      window.addEventListener(e, function () {
        if (!asking) { touched = Date.now(); }
      }, true);
    });
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden && !asking) { touched = Date.now(); }
    });
    // Checked against the clock rather than counted down, so a phone that
    // slept for an hour comes back knowing it slept for an hour.
    setInterval(function () {
      // The TV is nobody's phone: nobody touches it, and it should not sign
      // itself out at morning tea.
      if (document.body.classList.contains("tv")) { touched = Date.now(); }
      if (!asking && Date.now() - touched > IDLE_MS) { stillThere(); }
    }, 15000);
  }

  function stillThere() {
    asking = true;
    stopCamera();
    var left = GRACE_S;
    var timer = null;

    U.openSheet(function (body, close) {
      var count = U.el("div", { cls: "muted" });
      body.appendChild(U.el("h2", { cls: "title", text: "Still there?" }));
      body.appendChild(U.el("div", {
        text: "This has not been touched for half an hour. It will sign "
            + (D.cachedProfile().full_name || "you") + " out, so that "
            + "whoever picks the phone up next is not signed in as them."
      }));
      body.appendChild(count);
      body.appendChild(U.el("div", { cls: "row-actions", kids: [
        U.button("I am still here", function () {
          clearInterval(timer);
          asking = false;
          touched = Date.now();
          close();
        }, "go"),
        U.button("Sign me out", function () {
          clearInterval(timer);
          goodnight(body);
        }, "quiet")
      ] }));

      function tick() {
        count.textContent = "Signing out in " + left + " second"
                          + (left === 1 ? "" : "s") + ".";
        if (left <= 0) { clearInterval(timer); goodnight(body); return; }
        left -= 1;
      }
      tick();
      timer = setInterval(tick, 1000);
    });
  }

  function goodnight(body) {
    if (!S.pending()) {
      U.closeAllSheets();
      D.signOut().then(function () { location.reload(); });
      return;
    }
    S.flush().then(function (out) {
      if (!out.kept) {
        U.closeAllSheets();
        D.signOut().then(function () { location.reload(); });
        return;
      }
      throw new Error(out.kept + " change"
        + (out.kept === 1 ? "" : "s") + " still cannot be sent, so you are "
        + "being left signed in. Get back into signal, then sign out.");
    }).catch(function (err) {
      asking = false;
      touched = Date.now();
      U.notice(body, err.message);
      stateBar();
    });
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

      // Bracing, worked out as the size is typed, with the same rules the
      // desktop and the worksheet use.
      var brace = U.el("div", { cls: "brace-note", attr: { id: "brace-note" } });
      body.appendChild(brace);
      function showBrace() {
        brace.textContent = "";
        brace.className = "brace-note";
        var C = window.TAFCALC;
        if (!C || !String(v.Short.value).trim() || !String(v.Long.value).trim()) {
          return;
        }
        var b = C.bracing(C.constructionOf(v["Filter Type"].value),
                          v.Short.value, v.Long.value);
        brace.textContent = "Bracing: " + b.message;
        if (b.required) { brace.className = "brace-note required"; }
        else if (b.advisory) { brace.className = "brace-note advisory"; }
      }
      U.onPick([v.Short, v.Long, v["Filter Type"]], showBrace);

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
    // Is there room on the day it is due? Asked once; saying save anyway
    // saves it.
    if (feature("capacity_check") && !saveDraft._asked) {
      capacityWarning(h["Date Due"], DRAFT.items).then(function (warn) {
        btn.disabled = false;
        if (warn && !window.confirm(warn + "\n\nSave it for that day anyway?")) {
          U.notice(main, warn + " Change the due date, or save it anyway.");
          return;
        }
        saveDraft._asked = true;
        try { saveDraft(main); } finally { saveDraft._asked = false; }
      });
      return;
    }
    var count = DRAFT.items.length;      // DRAFT is emptied on the way back
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
      // Same wording the desktop writes, so one log reads as one log
      // whichever screen the order was raised on.
      logIt("order_created",
            "O/N: " + (made.order_number || h["Order Number"] || "")
            + " | Customer: " + h["Customer Name"]
            + " | " + count + " line" + (count === 1 ? "" : "s")
            + " | Raised on the web");
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
      if (feature("route_order")) { runCard(main, ready); }
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
        xeroNudge("Dispatched");
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

  /* ── The order the van goes round in ────────────────────────────────
     The same three rules as taf_order_app/delivery.py (suggest_route,
     apply_route, maps_links), held to them by tests/web_app.py. Saved for
     the day in delivery_runs, so the PC's run sheet follows it too. */

  var RUN_ORDER = ["Pick Up", "Local", "Logan", "Ipswich", "North",
                   "Gold Coast", "Sunshine Coast", "Freight"];
  var MAPS = "https://www.google.com/maps/dir/?api=1";
  var BASE_ADDRESS = "Unit 1/19 Tradelink Road, Hillcrest Queensland 4118 Australia";
  var STOPS_PER_LINK = 9;

  function addressText(c) {
    c = c || {};
    function joined(keys, sep) {
      return keys.map(function (k) { return String(c[k] || "").trim(); })
                 .filter(Boolean).join(sep);
    }
    return [joined(["delivery_address1", "delivery_address2"], ", "),
            joined(["delivery_city", "delivery_state", "delivery_postcode"], " ")]
      .filter(Boolean).join(", ");
  }

  function postcodeOf(text) {
    var words = String(text || "").replace(/,/g, " ").split(/\s+/)
      .filter(function (w) { return /^\d{4}$/.test(w); });
    return words.length ? parseInt(words[words.length - 1], 10) : 99999;
  }

  function suggestRoute(stops) {
    function rank(s) {
      var i = RUN_ORDER.indexOf(String(s.region || ""));
      return i === -1 ? RUN_ORDER.length : i;
    }
    return (stops || []).filter(function (s) { return s.region !== "Pick Up"; })
      .slice().sort(function (a, b) {
        var an = String(a.customer || "").toLowerCase(),
            bn = String(b.customer || "").toLowerCase();
        return rank(a) - rank(b) || postcodeOf(a.address) - postcodeOf(b.address)
          || (an < bn ? -1 : an > bn ? 1 : 0);
      });
  }

  function applyRoute(stops, saved) {
    stops = (stops || []).filter(function (s) { return s.region !== "Pick Up"; });
    var byId = {}, seen = {}, out = [];
    stops.forEach(function (s) { byId[String(s.id)] = s; });
    (saved || []).forEach(function (id) {
      id = String(id);
      if (byId[id] && !seen[id]) { out.push(byId[id]); seen[id] = true; }
    });
    suggestRoute(stops).forEach(function (s) {
      if (!seen[String(s.id)]) { out.push(s); }
    });
    return out;
  }

  // encodeURIComponent is what Python's quote(safe="!*'()-_.~") gives.
  function mapsLinks(base, addresses) {
    var route = (addresses || []).map(function (a) { return String(a || "").trim(); })
      .filter(Boolean);
    if (!route.length) { return []; }
    var points = route.concat([base]), links = [], start = base;
    while (points.length) {
      var leg = points.splice(0, STOPS_PER_LINK + 1);
      var end = leg[leg.length - 1], via = leg.slice(0, -1);
      var url = MAPS + "&origin=" + encodeURIComponent(start) + "&destination="
              + encodeURIComponent(end) + "&travelmode=driving";
      if (via.length) { url += "&waypoints=" + encodeURIComponent(via.join("|")); }
      links.push(url);
      start = end;
    }
    return links;
  }

  function runCard(main, ready) {
    var card = U.card("Today's run", [U.el("div", { cls: "muted", text: "Loading…" })]);
    card.setAttribute("id", "run-card");
    main.appendChild(card);
    var day = ymd(U.today()), stops = [];
    Promise.all([
      D.select("delivery_runs", { "select": "stops", "run_date": "eq." + day })
        .catch(function () { return []; }),
      D.select("customers", { "select": "name,short_name,delivery_address1,"
        + "delivery_address2,delivery_city,delivery_state,delivery_postcode" })
        .catch(function () { return []; }),
      D.select("calc_settings", { "select": "value", "key": "eq.company" })
        .catch(function () { return []; })
    ]).then(function (got) {
      var saved = (got[0][0] || {}).stops || [];
      var byName = {};
      got[1].forEach(function (c) {
        [c.name, c.short_name].forEach(function (n) {
          n = String(n || "").trim().toLowerCase();
          if (n && !byName[n]) { byName[n] = c; }
        });
      });
      // The company's base address, as the PC's run sheet and labels use it.
      var base = String(((got[2][0] || {}).value || {}).base_address || "").trim()
        || BASE_ADDRESS;
      stops = applyRoute(ready.map(function (r) {
        return { id: r.id, region: (r.location || "").trim(), customer: r.customer,
                 order_no: r.order_no, row: r,
                 address: addressText(byName[String(r.customer || "").trim().toLowerCase()]) };
      }), saved);
      draw(base, saved.length > 0);
    });

    function draw(base, saved) {
      while (card.childNodes.length > 1) { card.removeChild(card.lastChild); }
      if (!stops.length) {
        card.appendChild(U.empty("Only pick-ups today", "Nothing goes in the van."));
        return;
      }
      var list = U.el("div", { cls: "run-list" });
      stops.forEach(function (s, i) {
        list.appendChild(U.el("div", { cls: "run-row", attr: { "data-order": s.id }, kids: [
          U.el("b", { cls: "run-n", text: String(i + 1) }),
          U.el("div", { cls: "run-what", kids: [
            U.el("b", { text: s.customer + (s.order_no ? " · " + s.order_no : "") }),
            U.el("div", { cls: "muted", text: s.address || "No address on the account" })] }),
          U.button("▲", function () { move(i, -1, base); }, "quiet"),
          U.button("▼", function () { move(i, 1, base); }, "quiet"),
          U.button("Open", function () { openOrder(s.row); }, "quiet")] }));
      });
      card.appendChild(list);
      var links = mapsLinks(base, stops.map(function (s) { return s.address; }));
      var maps = U.el("div", { cls: "row-actions" });
      links.forEach(function (url, i) {
        maps.appendChild(U.el("a", { cls: "btn go maps-link", text: links.length > 1
          ? "Maps, part " + (i + 1) : "Open in Google Maps",
          attr: { href: url, target: "_blank", rel: "noopener" } }));
      });
      var save = U.button(saved ? "Saved" : "Save the run", function () {
        save.disabled = true;
        D.upsert("delivery_runs", {
          run_date: ymd(U.today()), stops: stops.map(function (s) { return s.id; }),
          updated_at: new Date().toISOString(),
          updated_by: D.cachedProfile().full_name || D.cachedProfile().username || ""
        }).then(function () {
          save.textContent = "Saved";
        }).catch(function (err) {
          save.disabled = false;
          U.notice(card, err.message);
        });
      }, saved ? "quiet" : "go");
      save.setAttribute("id", "run-save");
      maps.appendChild(save);
      card.appendChild(maps);
    }

    function move(i, by, base) {
      var j = Math.max(0, Math.min(stops.length - 1, i + by));
      var t = stops[i]; stops[i] = stops[j]; stops[j] = t;
      draw(base, false);
    }
  }

  /* ── The month's target ──────────────────────────────────────────────
     The same sums as taf_order_app/money.py (target_progress, target_text),
     held to them by tests/web_app.py. What an order is worth comes from the
     order_values view, so this, the PC and the owner's report agree. */

  var MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
                     "July", "August", "September", "October", "November",
                     "December"];

  function workingDays(first, last) {
    var n = 0, d = new Date(first.getFullYear(), first.getMonth(), first.getDate());
    while (d <= last) {
      var w = d.getDay();
      if (w !== 0 && w !== 6) { n += 1; }
      d.setDate(d.getDate() + 1);
    }
    return n;
  }

  function round2(n) { return Math.round(n * 100) / 100; }

  function targetProgress(sold, target, today) {
    target = Number(target) || 0;
    if (target <= 0) { return null; }
    sold = round2(Number(sold) || 0);
    var first = new Date(today.getFullYear(), today.getMonth(), 1);
    var last = new Date(today.getFullYear(), today.getMonth() + 1, 0);
    var total = workingDays(first, last) || 1;
    var done = workingDays(first, today);
    var tomorrow = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1);
    var left = workingDays(tomorrow, last);
    var short = Math.max(0, round2(target - sold));
    var expected = round2(target * done / total);
    return { sold: sold, target: round2(target),
             percent: Math.floor(sold / target * 100),
             short: short, days_left: left,
             per_day: left ? round2(short / left) : short,
             expected: expected, ahead: round2(sold - expected),
             made_it: sold >= target };
  }

  function dollars(n) {
    return "$" + String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  function targetText(p, month) {
    var name = MONTH_NAMES[month.getMonth()];
    if (!p) { return "No target set for " + name + "."; }
    var head = name + ": " + dollars(p.sold) + " of " + dollars(p.target)
             + " (" + p.percent + "%).";
    if (p.made_it) { return head + " Target made."; }
    if (!p.days_left) {
      return head + " " + dollars(p.short) + " short, and no working days left.";
    }
    return head + " " + dollars(p.per_day) + " a day for the " + p.days_left
         + " working day" + (p.days_left === 1 ? "" : "s") + " left.";
  }

  function targetCard(main) {
    var today = U.today();
    var first = ymd(new Date(today.getFullYear(), today.getMonth(), 1));
    var card = U.card("This month", [U.el("div", { cls: "muted", text: "Loading…" })]);
    card.setAttribute("id", "target-card");
    main.appendChild(card);
    Promise.all([
      D.select("sales_targets", { "select": "target", "month": "eq." + first }),
      D.select("order_values", { "select": "value", "ordered_on": "gte." + first,
                                 "limit": 20000 })
    ]).then(function (got) {
      var target = (got[0][0] || {}).target || 0;
      if (!target) { card.remove(); return; }
      var sold = got[1].reduce(function (t, r) { return t + (Number(r.value) || 0); }, 0);
      var p = targetProgress(sold, target, today);
      while (card.childNodes.length > 1) { card.removeChild(card.lastChild); }
      var bar = U.el("div", { cls: "target-bar", kids: [
        U.el("span", { attr: { style: "width:" + Math.min(100, p.percent) + "%" } })] });
      if (p.ahead < 0) { bar.classList.add("behind"); }
      card.appendChild(U.el("div", { cls: "target-n", text: p.percent + "%" }));
      card.appendChild(bar);
      card.appendChild(U.el("div", { cls: "muted", text: targetText(p, today) }));
    }).catch(function () { card.remove(); });
  }

  /* ── How-tos ─────────────────────────────────────────────────────────
     The same rules as taf_order_app/staff_board.py (read_state,
     sops_for_type, by_category), held to them by tests/web_app.py. */

  var SOPS = null;

  function loadSops() {
    return D.select("sops", { "select": "*", "archived": "eq.false",
                              "order": "title.asc" }).then(function (rows) {
      SOPS = rows || [];
      return SOPS;
    });
  }

  function lower(s) { return String(s || "").trim().toLowerCase(); }
  function byTitle(a, b) {
    var x = lower(a.title), y = lower(b.title);
    return x < y ? -1 : x > y ? 1 : 0;
  }

  function readState(sop, mine) {
    if (!mine) { return "new"; }
    return Number(mine.version || 0) >= Number(sop.version || 1) ? "read" : "changed";
  }

  function sopsForType(sops, type) {
    var want = lower(type);
    if (!want) { return []; }
    return (sops || []).filter(function (s) {
      return !s.archived && lower(s.filter_type) === want;
    }).sort(byTitle);
  }

  function byCategory(sops) {
    var groups = {};
    (sops || []).forEach(function (s) {
      if (s.archived) { return; }
      var c = String(s.category || "").trim() || "Other";
      (groups[c] = groups[c] || []).push(s);
    });
    return Object.keys(groups).sort(function (a, b) {
      var x = a === "Other", y = b === "Other";
      if (x !== y) { return x ? 1 : -1; }
      return lower(a) < lower(b) ? -1 : lower(a) > lower(b) ? 1 : 0;
    }).map(function (c) { return [c, groups[c].sort(byTitle)]; });
  }

  var READ_TEXT = { "new": "Not read", changed: "Changed since you read it",
                    read: "✓ Read" };

  function myReads() {
    var me = (D.whoami() || {}).id;
    return D.select("sop_reads", { "select": "sop_id,version,user_id",
                                   "user_id": "eq." + me })
      .catch(function () { return []; }).then(function (rows) {
        var out = {};
        rows.forEach(function (r) { out[r.sop_id] = r; });
        return out;
      });
  }

  SCREENS.howto = function (main) {
    Promise.all([loadSops(), myReads()]).then(function (got) {
      var mine = got[1];
      U.clear(main);
      var find = U.el("input", { attr: { type: "search", id: "howto-find",
                                         placeholder: "Find a how-to" } });
      var out = U.el("div");
      main.appendChild(U.card(null, [find]));
      main.appendChild(out);
      function draw() {
        var q = lower(find.value);
        U.clear(out);
        var groups = byCategory(SOPS.filter(function (s) {
          return !q || [s.title, s.category, s.filter_type, s.body].join(" ")
            .toLowerCase().indexOf(q) !== -1;
        }));
        if (!groups.length) {
          out.appendChild(U.card(null, [U.empty(q ? "Nothing matches"
            : "No how-tos yet", "A manager adds them on the PC.")]));
          return;
        }
        groups.forEach(function (g) {
          out.appendChild(U.card(g[0], g[1].map(function (s) {
            var state = readState(s, mine[s.id]);
            return U.el("div", { cls: "howto-row " + state, attr: { "data-sop": s.id },
              on: { click: function () { openSop(s, mine); } },
              kids: [U.el("b", { text: s.title }),
                     U.el("div", { cls: "muted", text: [s.filter_type,
                       READ_TEXT[state]].filter(Boolean).join(" · ") })] });
          })));
        });
      }
      find.addEventListener("input", draw);
      draw();
    }).catch(function (err) { U.clear(main); U.notice(main, err.message); });
  };

  function openSop(sop, mine) {
    U.openSheet(function (body, close) {
      body.appendChild(U.el("h2", { cls: "title", text: sop.title }));
      body.appendChild(U.el("div", { cls: "muted", text: [sop.category, sop.filter_type,
        "version " + (sop.version || 1)].filter(Boolean).join(" · ") }));
      body.appendChild(U.el("div", { cls: "sop-body",
                                     text: sop.body || "Nothing written yet." }));
      var acts = U.el("div", { cls: "row-actions" });
      if (/^https?:\/\//i.test(sop.video_url || "")) {
        acts.appendChild(U.el("a", { cls: "btn quiet", text: "▶  Watch the video",
          attr: { href: sop.video_url, target: "_blank", rel: "noopener" } }));
      }
      if (sop.file_path) {
        acts.appendChild(U.button("📄  Open the file", function () {
          D.signedUrl("sops", sop.file_path, 3600).then(function (url) {
            window.open(url, "_blank", "noopener");
          }).catch(function (err) { U.notice(body, err.message); });
        }, "quiet"));
      }
      var read = U.button("I've read this", function () {
        read.disabled = true;
        D.rpc("read_sop", { p_id: sop.id }).then(function (v) {
          if (mine) { mine[sop.id] = { sop_id: sop.id, version: v }; }
          U.notice(body, "Signed off - version " + v + ".", "ok");
        }).catch(function (err) {
          read.disabled = false;
          U.notice(body, err.message);
        });
      }, "go");
      read.setAttribute("id", "sop-read");
      acts.appendChild(read);
      acts.appendChild(U.button("Close", close, "quiet"));
      body.appendChild(acts);
    });
  }

  /* ── The noticeboard and group chats ─────────────────────────────────
     The same rules as taf_order_app/staff_board.py (may, message_time),
     held to them by tests/web_app.py. The database holds the real ones
     (step 49): these only decide which buttons to offer. */

  var CHAT_UNREAD = 0;
  var CHAT_SEEN = false;      // the first look after signing in is not "new"
  var RANK = { Employee: 1, Manager: 3, Admin: 4, Director: 4 };
  var WHO = { Employee: "Everybody", Manager: "Managers and above",
              Admin: "Directors and admins" };
  var CHAT_DEFAULTS = { post_board: "Manager", pin: "Admin", make_group: "Manager",
                        remove_any: "Admin" };
  var DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

  function rulesWithDefaults(rows) {
    var out = Object.assign({}, CHAT_DEFAULTS);
    (rows || []).forEach(function (r) {
      if (out.hasOwnProperty(r.action) && WHO.hasOwnProperty(r.min_role)) {
        out[r.action] = r.min_role;
      }
    });
    return out;
  }

  function chatMay(action, role, rules) {
    var need = (rules || {})[action] || CHAT_DEFAULTS[action] || "Admin";
    var mine = RANK[role] || 0;
    return mine > 0 && mine >= (RANK[need] || 0);
  }

  function messageTime(iso, now) {
    var d = new Date(String(iso || "").replace(/\+00:00$/, "Z"));
    if (isNaN(d.getTime())) { return ""; }
    now = now || new Date();
    var day = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    var days = Math.round((today - day) / 86400000);
    var hm = pad2(d.getHours()) + ":" + pad2(d.getMinutes());
    if (days === 0) { return hm; }
    if (days > 0 && days < 7) { return DAY_NAMES[d.getDay()] + " " + hm; }
    return pad2(d.getDate()) + "/" + pad2(d.getMonth() + 1) + "/" + d.getFullYear();
  }

  function pollChats() {
    return D.rpc("my_chats", {}).then(function (rows) {
      rows = rows || [];
      var n = rows.reduce(function (t, c) { return t + (c.unread || 0); }, 0);
      if (n > CHAT_UNREAD && CHAT_SEEN && active !== "chat") {
        var c = rows.filter(function (x) { return x.unread; })[0];
        if (c) {
          U.toast("💬  " + (c.last_author || c.name) + (c.kind === "direct" ? ""
                  : " in " + c.name) + ": " + String(c.last_body || "").slice(0, 80),
                  function () { show("chat"); openChat(c, null); });
        }
      }
      CHAT_SEEN = true;
      if (n !== CHAT_UNREAD) { CHAT_UNREAD = n; buildTabs(); }
      setChatBadge(n);
      return rows;
    }).catch(function () { return []; });
  }

  function setChatBadge(n) {
    var btn = document.getElementById("chat-btn");
    var badge = document.getElementById("chat-badge");
    if (!btn || !badge) { return; }
    btn.classList.toggle("has", n > 0);
    badge.classList.toggle("hidden", !n);
    badge.textContent = n > 99 ? "99+" : String(n);
    btn.setAttribute("aria-label", n ? n + " unread message" + (n === 1 ? "" : "s")
                                     : "Messages");
  }

  function myRole() { return D.cachedProfile().role || "Employee"; }

  SCREENS.chat = function (main) {
    Promise.all([pollChats(),
                 D.select("chat_rules", { "select": "action,min_role" })
                   .catch(function () { return []; })]).then(function (got) {
      var chats = got[0], rules = rulesWithDefaults(got[1]);
      CHAT_RULES = rules;
      U.clear(main);
      var top = U.el("div", { cls: "row-actions" });
      var dm = U.button("💬  Message someone", function () { messageSomeone(rules); }, "go");
      dm.setAttribute("id", "chat-dm");
      top.appendChild(dm);
      if (chatMay("make_group", myRole(), rules)) {
        var add = U.button("+  New group", function () { newGroup(rules); }, "quiet");
        add.setAttribute("id", "chat-new");
        top.appendChild(add);
      }
      main.appendChild(top);
      var list = U.el("div", { attr: { id: "chat-list" } });
      chats.forEach(function (c) {
        list.appendChild(U.el("div", { cls: "chat-row", attr: { "data-chat": c.id },
          on: { click: function () { openChat(c, rules); } },
          kids: [U.el("div", { cls: "chat-what", kids: [
                   U.el("b", { text: ({ board: "📌 ", direct: "💬 " }[c.kind] || "👥 ")
                                     + c.name }),
                   U.el("div", { cls: "muted", text: c.last_body
                     ? (c.last_author ? c.last_author + ": " : "") + c.last_body
                     : "Nothing yet" })] }),
                 c.unread ? U.el("b", { cls: "tab-count", text: String(c.unread) })
                          : U.el("span")] }));
      });
      main.appendChild(U.card(null, chats.length ? [list]
        : [U.empty("No chats", "The noticeboard appears once step 49 is run.")]));
    }).catch(function (err) { U.clear(main); U.notice(main, err.message); });
  };

  function openChat(chat, rules) {
    rules = rules || CHAT_RULES || rulesWithDefaults([]);
    U.openSheet(function (body, close) {
      body.appendChild(U.el("h2", { cls: "title", text: chat.name }));
      var pinned = U.el("div", { attr: { id: "chat-pinned" } });
      var list = U.el("div", { attr: { id: "chat-msgs" } });
      body.appendChild(pinned);
      body.appendChild(list);
      var role = myRole(), me = (D.whoami() || {}).id;
      if (chat.can_post) {
        var text = U.el("textarea", { attr: { id: "chat-text", rows: "2",
                                              placeholder: "Write a message" } });
        var send = U.button("Send", function () {
          var words = text.value.trim();
          if (!words) { return; }
          send.disabled = true;
          D.insert("chat_messages", { channel_id: chat.id, body: words.slice(0, 4000),
                                      user_id: me }).then(function () {
            text.value = "";
            load();
          }).catch(function (err) { U.notice(body, err.message); })
            .then(function () { send.disabled = false; });
        }, "go");
        send.setAttribute("id", "chat-send");
        body.appendChild(U.el("div", { cls: "chat-compose", kids: [text, send] }));
      } else {
        var who = chat.kind === "board" ? WHO[rules.post_board] : WHO[chat.post_min_role];
        body.appendChild(U.el("div", { cls: "muted", attr: { id: "chat-readonly" },
          text: who ? "Only " + who.toLowerCase() + " can post here." : "You cannot post here." }));
      }
      body.appendChild(U.el("div", { cls: "row-actions",
                                     kids: [U.button("Close", close, "quiet")] }));

      function act(name, args) {
        D.rpc(name, args).then(load).catch(function (err) { U.notice(body, err.message); });
      }

      function message(m) {
        var gone = !!m.removed_at;
        var kids = [U.el("div", { cls: "muted", text: (m.author || "") + " · "
                      + messageTime(m.created_at) }),
                    U.el("div", { cls: "chat-body", text: gone
                      ? "Taken down" + (m.removed_by ? " by " + m.removed_by : "") : m.body })];
        var acts = U.el("div", { cls: "chat-acts" });
        if (!gone && chatMay("pin", role, rules)) {
          acts.appendChild(U.button(m.pinned ? "Unpin" : "📌 Pin", function () {
            act("pin_message", { p_id: m.id, p_on: !m.pinned });
          }, "quiet msg-pin"));
        }
        if (!gone && (m.user_id === me || chatMay("remove_any", role, rules))) {
          acts.appendChild(U.button("Take down", function () {
            if (window.confirm("Take this message down?")) {
              act("remove_message", { p_id: m.id });
            }
          }, "quiet msg-remove"));
        }
        if (acts.childNodes.length) { kids.push(acts); }
        return U.el("div", { cls: "chat-msg" + (m.pinned ? " pinned" : "")
                               + (gone ? " gone" : "") + (m.user_id === me ? " mine" : ""),
                             attr: { "data-msg": m.id }, kids: kids });
      }

      function load() {
        return D.select("chat_messages", { "select": "*", "channel_id": "eq." + chat.id,
                                           "order": "created_at.desc", "limit": 200 })
          .then(function (rows) {
            rows = (rows || []).slice().reverse();
            U.clear(pinned);
            U.clear(list);
            var pins = rows.filter(function (m) { return m.pinned; });
            if (pins.length) {
              pinned.appendChild(U.card("Pinned", pins.map(message)));
            }
            rows.forEach(function (m) { list.appendChild(message(m)); });
            if (!rows.length) { list.appendChild(U.empty("Nothing said yet")); }
            D.rpc("mark_chat_read", { p_channel: chat.id }).then(pollChats)
              .catch(function () {});
          }).catch(function (err) { U.notice(body, err.message); });
      }
      load();
      // New messages while it is open; stops when the sheet is closed.
      var timer = setInterval(function () {
        if (!document.body.contains(body)) { clearInterval(timer); return; }
        var t = document.getElementById("chat-text");
        if (!t || !t.value) { load(); }
      }, 10000);
    });
  }

  var CHAT_RULES = null;

  // Anybody on staff, privately. One conversation between two people: the
  // database opens the one there is, or starts it.
  function messageSomeone(rules) {
    D.select("profiles", { "select": "id,full_name,username,role,approved",
                           "approved": "eq.true", "order": "full_name.asc" })
      .then(function (people) {
        var me = (D.whoami() || {}).id;
        people = people.filter(function (p) { return p.id !== me; });
        U.openSheet(function (body, close) {
          body.appendChild(U.el("h2", { cls: "title", text: "Message someone" }));
          var find = U.el("input", { attr: { type: "search", id: "dm-find",
                                             placeholder: "Find somebody" } });
          var list = U.el("div", { attr: { id: "dm-people" } });
          body.appendChild(find);
          body.appendChild(list);
          function draw() {
            var q = lower(find.value);
            U.clear(list);
            people.filter(function (p) {
              return !q || lower(p.full_name || p.username).indexOf(q) !== -1;
            }).forEach(function (p) {
              list.appendChild(U.el("div", { cls: "chat-row", attr: { "data-person": p.id },
                on: { click: function () { start(p); } },
                kids: [U.el("div", { cls: "chat-what", kids: [
                  U.el("b", { text: p.full_name || p.username }),
                  U.el("div", { cls: "muted", text: p.role || "" })] })] }));
            });
          }
          function start(p) {
            D.rpc("open_direct", { p_user: p.id }).then(function (id) {
              return pollChats().then(function (rows) {
                var chat = rows.filter(function (c) { return c.id === id; })[0]
                  || { id: id, name: p.full_name || p.username, kind: "direct",
                       can_post: true };
                close();
                openChat(chat, rules);
              });
            }).catch(function (err) { U.notice(body, err.message); });
          }
          find.addEventListener("input", draw);
          draw();
          body.appendChild(U.el("div", { cls: "row-actions",
                                         kids: [U.button("Cancel", close, "quiet")] }));
        });
      }).catch(function (err) { U.notice(document.getElementById("screen"), err.message); });
  }

  function newGroup(rules) {
    D.select("profiles", { "select": "id,full_name,username,role,approved",
                           "approved": "eq.true", "order": "full_name.asc" })
      .then(function (people) {
        var me = (D.whoami() || {}).id;
        U.openSheet(function (body, close) {
          body.appendChild(U.el("h2", { cls: "title", text: "New group" }));
          var name = U.el("input", { attr: { type: "text", id: "group-name",
                                             placeholder: "Name" } });
          var who = U.el("select", { attr: { id: "group-who" },
            kids: Object.keys(WHO).map(function (k) {
              return U.el("option", { text: WHO[k], attr: { value: k } }); }) });
          body.appendChild(U.el("label", { cls: "f", kids: [
            U.el("span", { text: "Name" }), name] }));
          body.appendChild(U.el("label", { cls: "f", kids: [
            U.el("span", { text: "Who can post in it" }), who] }));
          var boxes = U.el("div", { cls: "group-people" });
          people.filter(function (p) { return p.id !== me; }).forEach(function (p) {
            boxes.appendChild(U.el("label", { cls: "check", kids: [
              U.el("input", { attr: { type: "checkbox", value: p.id } }),
              U.el("span", { text: (p.full_name || p.username) + "  (" + p.role + ")" })] }));
          });
          body.appendChild(boxes);
          var make = U.button("Start it", function () {
            if (!name.value.trim()) { U.notice(body, "Give the group a name."); return; }
            var ids = Array.prototype.slice.call(
              boxes.querySelectorAll("input:checked")).map(function (b) { return b.value; });
            D.rpc("make_group", { p_name: name.value.trim(), p_members: ids,
                                  p_post_min_role: who.value }).then(function () {
              close();
              show("chat");
            }).catch(function (err) { U.notice(body, err.message); });
          }, "go");
          make.setAttribute("id", "group-make");
          body.appendChild(U.el("div", { cls: "row-actions",
                                         kids: [make, U.button("Cancel", close, "quiet")] }));
        });
      }).catch(function (err) { U.notice(document.getElementById("screen"), err.message); });
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
      U.onPick([search, state], redraw);
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

      // Lost: why, so the pattern shows (sales.lost_report).
      if (feature("lost_reasons") && (["sent", "viewed", "draft"].indexOf(q.status) >= 0
          || (["declined", "expired"].indexOf(q.status) >= 0 && !q.lost_reason))) {
        var why = U.el("select", { attr: { id: "lost-reason" },
          kids: LOST_REASONS.map(function (r) {
            return U.el("option", { text: r, attr: { value: r } }); }) });
        var lost = U.button("Mark lost", function () {
          lost.disabled = true;
          var patch = { lost_reason: why.value, updated_at: new Date().toISOString() };
          if (["declined", "expired"].indexOf(q.status) < 0) {
            patch.status = "declined";
            patch.responded_at = q.responded_at || patch.updated_at;
          }
          D.update("quotes", { "id": "eq." + q.id }, patch).then(function (rows) {
            if (!rows || !rows.length) { throw new Error("That didn't change anything."); }
            q.status = rows[0].status; q.lost_reason = why.value;
            U.notice(body, "Marked lost: " + why.value + ".", "ok");
            lost.remove(); why.remove();
          }).catch(function (err) {
            lost.disabled = false;
            U.notice(body, err.message);
          });
        }, "quiet");
        lost.setAttribute("id", "mark-lost");
        body.appendChild(U.card("Lost it?", [why, U.el("div", { cls: "row-actions",
                                                                kids: [lost] })]));
      }

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
      var acts = [U.button("Close", close, "quiet")];
      if (feature("order_again") && theirs.length) {
        var again = U.button("↻  Order their last one again", function () {
          var last = theirs[0];
          D.select("orders", { "id": "eq." + last.id, "select": "items,header" })
            .then(function (rows) {
              var o = (rows && rows[0]) || {};
              orderAgain(last, o.items || [], o.header || last.header);
            }).catch(function (err) { U.notice(body, err.message); });
        }, "go");
        again.setAttribute("id", "customer-again");
        acts.unshift(again);
      }
      body.appendChild(U.el("div", { cls: "row-actions", kids: acts }));
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
          // minimum_on_hand is what the column is actually called, in
          // stock_schema.sql and in the desktop app. This used to read
          // minimum_level, which is nothing, so nothing was ever low.
          var min = Number(s.minimum_on_hand || 0);
          return min > 0 && Number(s.stock_on_hand || 0) <= min;
        }
        // What we pay for each, ex GST: the preferred supplier's price, or
        // Xero's for their code (steps 40 and 42). Cards show "No price yet"
        // until it is known, and fill in when it is.
        var links = [], xeroItems = [];
        Promise.all([
          D.select("stock_item_suppliers", { "select": "*" })
            .catch(function () { return []; }),
          D.select("xero_items", { "select": "code,purchase_price,stock_item_id",
                                   "limit": 5000 })
            .catch(function () { return []; })
        ]).then(function (got) {
          links = got[0] || []; xeroItems = got[1] || [];
          if (links.length || xeroItems.length) { redraw(); }
        });
        function priceOf(s) {
          var mine = links.filter(function (l) { return l.stock_item_id === s.id; })
            .sort(function (a, b) { return (b.preferred ? 1 : 0) - (a.preferred ? 1 : 0); });
          var i, hit;
          for (i = 0; i < mine.length; i++) {
            if (mine[i].unit_price !== null && mine[i].unit_price !== undefined
                && mine[i].unit_price !== "") { return Number(mine[i].unit_price); }
          }
          for (i = 0; i < mine.length; i++) {
            var code = String(mine[i].supplier_code || "").toUpperCase();
            hit = xeroItems.filter(function (x) {
              return code && String(x.code || "").toUpperCase() === code
                     && x.purchase_price !== null && x.purchase_price !== undefined;
            })[0];
            if (hit) { return Number(hit.purchase_price); }
          }
          hit = xeroItems.filter(function (x) {
            return x.stock_item_id === s.id && x.purchase_price !== null
                   && x.purchase_price !== undefined;
          })[0];
          return hit ? Number(hit.purchase_price) : null;
        }
        function card(s) {
          var state = Number(s.stock_on_hand || 0) <= 0 ? "out"
                    : (isLow(s) ? "low" : "");
          var price = priceOf(s);
          var least = Number(s.minimum_on_hand || 0);
          var ph = U.el("div", { cls: "ph" });
          if (s.image_url) {
            var img = U.el("img", { attr: { src: s.image_url, alt: s.name || "",
                                            loading: "lazy", decoding: "async" } });
            img.addEventListener("error", function () {
              U.clear(ph); ph.appendChild(U.el("span", { text: "No photo" }));
            });
            ph.appendChild(img);
          } else {
            ph.appendChild(U.el("span", { text: "No photo" }));
          }
          var el = U.el("div", {
            cls: "stock-card", attr: { role: "button", tabindex: "0",
                                       "data-stock": s.id },
            on: { click: function () { openStock(s, rows); },
                  keydown: function (e) {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault(); openStock(s, rows);
                    }
                  } },
            kids: [ph, U.el("div", { cls: "bd", kids: [
              U.el("div", { cls: "nm", text: s.name || "",
                            attr: { title: s.name || "" } }),
              U.el("div", { cls: "ds",
                            text: s.description || s.product_type || "" }),
              U.el("div", { cls: "nums", kids: [
                U.el("b", { cls: state,
                            text: "Stock " + qtyText(s.stock_on_hand) + " "
                                  + unitLabel(s.unit, s.stock_on_hand) }),
                U.el("span", { text: least > 0
                  ? "MOQ " + qtyText(least) + " " + unitLabel(s.unit, least)
                  : "MOQ —" })] }),
              U.el("div", { cls: price === null ? "pr none" : "pr",
                            text: price === null ? "No price yet"
                : "$" + price.toFixed(2) + " ex GST / " + unitLabel(s.unit, 1) })
            ] })]
          });
          return el;
        }
        function redraw() {
          var q = search.value.trim().toLowerCase();
          var list = rows.filter(function (s) {
            if (lowOnly.checked && !isLow(s)) { return false; }
            return !q || [s.name, s.sku, s.media_type, s.description]
              .join(" ").toLowerCase().indexOf(q) !== -1;
          });
          U.clear(out);
          if (!list.length) {
            out.appendChild(U.card(null, [U.empty("Nothing matches")]));
            return;
          }
          out.appendChild(U.el("div", { cls: "muted",
            attr: { style: "margin:0 0 10px" },
            text: list.length + " item" + (list.length === 1 ? "" : "s") }));
          out.appendChild(U.el("div", { cls: "stock-wrap", kids: [
            U.el("div", { cls: "stock-grid",
                          kids: list.slice(0, 400).map(card) })] }));
        }
        U.onPick([search, lowOnly], redraw);
        // A manager makes stock items here as on the PC (the same rule as
        // db.can_manage_stock); the database lets approved staff write them.
        if (D.roleLevel() >= 3) {
          var add = U.button("＋  New stock item", function () {
            newStockItem(rows);
          }, "go");
          add.setAttribute("id", "stock-new");
          main.appendChild(U.el("div", { cls: "row-actions", kids: [add] }));
        }
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

  // "rolls", "lengths", "pieces", "m²" - as taf_order_app/stock_cards.py.
  var UNITS = { each: ["piece", "pieces"], ea: ["piece", "pieces"],
    pc: ["piece", "pieces"], pcs: ["piece", "pieces"], piece: ["piece", "pieces"],
    pieces: ["piece", "pieces"], m2: ["m²", "m²"], sqm: ["m²", "m²"],
    "m²": ["m²", "m²"], "square metre": ["m²", "m²"], "square metres": ["m²", "m²"],
    roll: ["roll", "rolls"], rolls: ["roll", "rolls"],
    length: ["length", "lengths"], lengths: ["length", "lengths"],
    box: ["box", "boxes"], boxes: ["box", "boxes"], m: ["m", "m"],
    metre: ["m", "m"], metres: ["m", "m"], kg: ["kg", "kg"],
    sheet: ["sheet", "sheets"], sheets: ["sheet", "sheets"],
    bag: ["bag", "bags"], bags: ["bag", "bags"], pack: ["pack", "packs"],
    packs: ["pack", "packs"] };
  function unitLabel(unit, qty) {
    var raw = String(unit || "").trim();
    var pair = UNITS[raw.toLowerCase()] || [raw || "piece", raw || "pieces"];
    return Number(qty) === 1 ? pair[0] : pair[1];
  }
  function qtyText(n) {
    n = Number(n || 0);
    return n === Math.round(n) ? String(n)
         : n.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
  }

  /* ── New order (Order Supplies) ──────────────────────────────────────
     Stock items picked from a list, each with how many and who from, sent
     to the managers in one go. The same rules as purchasing.py's
     search_stock, new_order_pick, low_picks and stock_request_line - a
     test holds the two together. */

  function stockState(s) {
    var held = Number(s.stock_on_hand || 0), least = Number(s.minimum_on_hand || 0);
    if (held <= 0) { return "out"; }
    return least > 0 && held < least ? "low" : "ok";
  }

  function searchStock(rows, text) {
    var words = String(text || "").toLowerCase().split(/\s+/).filter(Boolean);
    var rank = { out: 0, low: 1 };
    return (rows || []).filter(function (r) {
      var hay = [r.name, r.product_type, r.description].map(function (v) {
        return String(v || "");
      }).join(" ").toLowerCase();
      return words.every(function (w) { return hay.indexOf(w) >= 0; });
    }).sort(function (a, b) {
      var ra = rank[stockState(a)], rb = rank[stockState(b)];
      ra = ra === undefined ? 2 : ra; rb = rb === undefined ? 2 : rb;
      if (ra !== rb) { return ra - rb; }
      var na = String(a.name || "").toLowerCase(), nb = String(b.name || "").toLowerCase();
      return na < nb ? -1 : (na > nb ? 1 : 0);
    });
  }

  function suppliersOf(id, links) {
    return (links || []).filter(function (l) {
      return String(l.stock_item_id) === String(id);
    }).sort(function (a, b) {
      if (!!a.preferred !== !!b.preferred) { return a.preferred ? -1 : 1; }
      var ca = String(a.supplier_code || ""), cb = String(b.supplier_code || "");
      return ca < cb ? -1 : (ca > cb ? 1 : 0);
    });
  }

  function shortfallOf(s, onOrder) {
    var want = Number(s.minimum_on_hand || 0), held = Number(s.stock_on_hand || 0);
    if (!(want > 0)) { return 0; }
    return Math.max(0, Math.ceil(want - held - (Number(onOrder) || 0)));
  }

  function newOrderPick(s, links, onOrder) {
    var need = shortfallOf(s, onOrder);
    var theirs = suppliersOf(s.id, links);
    return { stock: s, quantity: need > 0 ? qtyText(need) : "",
             supplier_id: theirs.length ? String(theirs[0].supplier_id || "") : "" };
  }

  function lowPicks(rows, links, onOrder) {
    onOrder = onOrder || {};
    return searchStock(rows, "").map(function (s) {
      return newOrderPick(s, links, onOrder[String(s.id)] || 0);
    }).filter(function (p) { return !!p.quantity; });
  }

  function supplyItemFor(s) {
    var words = (String(s.product_type || "") + " " + String(s.name || "")).toLowerCase();
    var kinds = SUPPLY_ITEMS.filter(function (k) { return k !== "Other"; });
    for (var i = 0; i < kinds.length; i++) {
      var key = kinds[i].toLowerCase();
      if (words.indexOf(key) >= 0 || words.indexOf(key.replace(/s+$/, "")) >= 0
          || words.indexOf(key.split(" ")[0]) >= 0) { return kinds[i]; }
    }
    return "Other";
  }

  function stockRequestLine(s, quantity, supplierId, links) {
    var qty = String(quantity || "").trim();
    if (/^\d+(\.\d+)?$/.test(qty)) { qty = qty + " " + unitLabel(s.unit, qty); }
    var link = supplierId ? (links || []).filter(function (l) {
      return String(l.stock_item_id) === String(s.id)
             && String(l.supplier_id) === String(supplierId);
    })[0] : null;
    return { item: supplyItemFor(s),
             detail: String(s.name || "").trim().slice(0, 200),
             quantity: qty.slice(0, 60), supplier_id: supplierId || "",
             item_code: link ? String(link.supplier_code || "") : "",
             stock_item_id: String(s.id || "") };
  }

  // Something not on the stock list, as purchasing.other_request_line.
  function otherRequestLine(text, quantity, supplierId) {
    var said = String(text || "").split(/\s+/).filter(Boolean).join(" ").slice(0, 200);
    return { item: supplyItemFor({ name: said }), detail: said,
             quantity: String(quantity || "").trim().slice(0, 60),
             supplier_id: supplierId || "", item_code: "", stock_item_id: "" };
  }

  // What is on a purchase order and not yet here, by stock item - the same
  // as records.quantities_on_order.
  function onOrderOf(pos) {
    var out = {};
    (pos || []).forEach(function (po) {
      if (po.status === "received" || po.status === "cancelled") { return; }
      (po.lines || []).forEach(function (l) {
        var key = String((l && (l.item_id || l.stock_item_id)) || "");
        if (!key) { return; }
        var left = Number(l.quantity || 0) - Number(l.received || 0);
        if (left > 0) { out[key] = (out[key] || 0) + left; }
      });
    });
    return out;
  }

  // One New order at a time, kept while it is open: a stock photo looked
  // at from it, or the phone turned, comes back to the same list.
  var NEW_ORDER = null;

  function openNewOrder(done) {
    if (!NEW_ORDER) {
      NEW_ORDER = { lines: [], find: "", note: "", urgent: false,
                    stock: null, links: [], suppliers: [], onOrder: {},
                    stale: 0, error: "" };
      var o = NEW_ORDER;
      Promise.all([
        loadKept("stock", function () {
          return D.select("stock_items", { "select": "*", "order": "name",
                                           "limit": 2000 });
        }).catch(function (err) { o.error = err.message; return { rows: [], at: 0 }; }),
        D.select("stock_item_suppliers", { "select": "*" })
          .catch(function () { return []; }),
        D.select("suppliers", { "select": "id,name", "active": "eq.true",
                                "order": "name" }).catch(function () { return []; }),
        D.select("purchase_orders", { "select": "status,lines",
                                      "status": "in.(draft,sent,part_received)" })
          .catch(function () { return []; })
      ]).then(function (got) {
        if (NEW_ORDER !== o) { return; }
        o.stock = got[0].rows || []; o.stale = got[0].at;
        o.links = got[1] || []; o.suppliers = got[2] || [];
        o.onOrder = onOrderOf(got[3]);
        if (o.redraw) { o.redraw(); }
      });
    }
    U.openSheet(function (body, close) {
      var o = NEW_ORDER;
      if (!o) { close(); return; }
      var names = {};
      o.suppliers.forEach(function (s) { names[s.id] = s.name; });

      body.appendChild(U.el("h2", { cls: "title", text: "New order" }));
      body.appendChild(U.el("div", { cls: "muted",
        text: "Pick from the stock list, or type what isn't on it - how many "
            + "and who from are filled in where we know." }));

      var find = U.el("input", { attr: { type: "search", id: "no-find",
        placeholder: "Search stock", value: o.find, autocomplete: "off" } });
      var low = U.button("Add everything low", function () {
        var picks = lowPicks(o.stock || [], o.links, o.onOrder);
        if (!add(picks)) {
          U.notice(pickCard, picks.length ? "Everything low is on it already."
            : "Nothing is below its minimum - or it is already coming.", "ok");
        }
      }, "quiet");
      low.setAttribute("id", "no-low");
      var results = U.el("div", { cls: "no-results", attr: { id: "no-results" } });
      // Anything that is not a stock item - spray paint, a drill bit.
      var other = U.el("input", { attr: { type: "text", id: "no-other",
        maxlength: "200", placeholder: "e.g. white spray paint",
        autocomplete: "off" } });
      var otherAdd = U.button("Add", function () { addOther(); }, "quiet");
      otherAdd.setAttribute("id", "no-other-add");
      other.addEventListener("keydown", function (e) {
        if (e.key === "Enter") { e.preventDefault(); addOther(); }
      });
      var pickCard = U.card("Stock", [find, U.el("div", { cls: "row-actions",
                                                           kids: [low] }), results,
        U.el("label", { cls: "f no-other", kids: [
          U.el("span", { text: "Not on the stock list?" }),
          U.el("div", { cls: "no-other-row", kids: [other, otherAdd] })] })]);

      var linesBox = U.el("div", { cls: "no-lines", attr: { id: "no-lines" } });
      var orderCard = U.card("The order", [linesBox]);
      var note = U.el("input", { attr: { type: "text", id: "no-note",
        maxlength: "500", placeholder: "Optional", value: o.note } });
      note.addEventListener("input", function () { o.note = note.value; });
      var urgent = U.el("input", { attr: { type: "checkbox", id: "no-urgent" } });
      urgent.checked = o.urgent;
      urgent.addEventListener("change", function () { o.urgent = urgent.checked; });
      orderCard.appendChild(U.el("label", { cls: "f", kids: [
        U.el("span", { text: "Note" }), note] }));
      orderCard.appendChild(U.el("label", { cls: "f",
        attr: { style: "color:#8A2A1E" }, kids: [
          urgent, document.createTextNode("  Urgent - work has stopped")] }));
      var send = U.button("Send to managers", function () { sendIt(); }, "go");
      send.setAttribute("id", "no-send");
      var cancel = U.button("Cancel", function () { NEW_ORDER = null; close(); },
                            "quiet");
      orderCard.appendChild(U.el("div", { cls: "row-actions",
                                          kids: [cancel, send] }));
      body.appendChild(pickCard);
      body.appendChild(orderCard);

      function have(id) {
        return o.lines.some(function (l) {
          return l.stock && String(l.stock.id) === String(id);
        });
      }

      function lineKey(l, i) { return l.stock ? String(l.stock.id) : "other-" + i; }

      function addOther() {
        var said = other.value.split(/\s+/).filter(Boolean).join(" ");
        if (!said) { other.focus(); return; }
        o.lines.push({ stock: null, text: said, qty: "", sup: "" });
        other.value = "";
        drawLines();
        var input = linesBox.querySelector('[data-line="other-'
                                           + (o.lines.length - 1) + '"] input');
        if (input) { input.focus(); }
      }

      function add(picks) {
        var added = 0;
        picks.forEach(function (p) {
          if (have(p.stock.id)) { return; }
          o.lines.push({ stock: p.stock, qty: p.quantity, sup: p.supplier_id });
          added++;
        });
        if (added) { drawLines(); drawResults(); }
        return added;
      }

      function drawResults() {
        U.clear(results);
        if (o.stock === null) {
          results.appendChild(U.el("div", { cls: "muted", text: "Loading stock…" }));
          return;
        }
        if (o.stale) { results.appendChild(staleNote(o.stale)); }
        var hits = searchStock(o.stock, o.find);
        if (!hits.length) {
          results.appendChild(U.el("div", { cls: "muted", text: o.error
            || (o.stock.length ? "Nothing matches." : "No stock items yet.") }));
          return;
        }
        hits.slice(0, 60).forEach(function (s) {
          var state = stockState(s);
          var on = have(s.id);
          var least = Number(s.minimum_on_hand || 0);
          var ph = U.el("div", { cls: "ph" });
          if (s.image_url) {
            ph.appendChild(U.el("img", { attr: { src: s.image_url, alt: "",
              loading: "lazy", decoding: "async", width: "44", height: "44" } }));
          }
          var row = U.el("button", {
            cls: "no-pick" + (on ? " on" : ""),
            attr: { type: "button", "data-stock": s.id,
                    "aria-label": (on ? "On the order: " : "Add ") + (s.name || "") },
            on: { click: function () {
              if (have(s.id)) { return; }
              add([newOrderPick(s, o.links, o.onOrder[String(s.id)] || 0)]);
              var input = linesBox.querySelector('[data-line="' + s.id + '"] input');
              if (input && !input.value) { input.focus(); }
            } },
            kids: [ph, U.el("span", { cls: "nm", text: s.name || "" }),
                   U.el("span", { cls: "held st-" + state,
                     text: qtyText(s.stock_on_hand) + (least ? " / " + qtyText(least) : "")
                           + " " + unitLabel(s.unit, s.stock_on_hand) }),
                   U.el("span", { cls: "plus", text: on ? "✓" : "+" })]
          });
          results.appendChild(row);
        });
      }

      function drawLines() {
        U.clear(linesBox);
        if (!o.lines.length) {
          linesBox.appendChild(U.empty("Nothing on it yet.",
            "Tap stock above, or Add everything low."));
          return;
        }
        o.lines.forEach(function (l, i) {
          var name = l.stock ? (l.stock.name || "") : l.text;
          // A stock item: a number, in its own unit. Typed: "3 rolls".
          var qty = U.el("input", { attr: { type: "text",
            inputmode: l.stock ? "decimal" : "text",
            placeholder: l.stock ? "" : "e.g. 3 cans",
            maxlength: l.stock ? "20" : "60", value: l.qty,
            "aria-label": "How many " + name } });
          qty.addEventListener("input", function () { l.qty = qty.value; });
          var sup = U.el("select", { attr: { "aria-label": "From" },
            kids: [U.el("option", { text: "Supplier - not sure", attr: { value: "" } })] });
          var theirs = (l.stock ? suppliersOf(l.stock.id, o.links) : [])
            .map(function (k) { return String(k.supplier_id); })
            .filter(function (id) { return names[id]; });
          var rest = o.suppliers.map(function (s) { return String(s.id); })
            .filter(function (id) { return theirs.indexOf(id) < 0; });
          theirs.concat(rest).forEach(function (id) {
            sup.appendChild(U.el("option", { text: names[id], attr: { value: id } }));
          });
          sup.value = l.sup || "";
          sup.addEventListener("change", function () { l.sup = sup.value; });
          var off = U.button("✕", function () {
            o.lines.splice(i, 1); drawLines(); drawResults();
          }, "quiet");
          off.setAttribute("aria-label", "Take off " + name);
          linesBox.appendChild(U.el("div", { cls: "no-line" + (l.stock ? "" : " typed"),
            attr: { "data-line": lineKey(l, i) }, kids: [
              U.el("div", { cls: "nm", text: name }),
              U.el("div", { cls: "q", kids: l.stock ? [qty, U.el("span", {
                text: unitLabel(l.stock.unit, 2) })] : [qty] }),
              o.suppliers.length ? sup : U.el("span"),
              off] }));
        });
      }

      function sendIt() {
        if (!o.lines.length) {
          U.notice(orderCard, "Put something on it first.");
          return;
        }
        var at = -1;
        o.lines.forEach(function (l, i) {
          if (at < 0 && !String(l.qty).trim()) { at = i; }
        });
        if (at >= 0) {
          var missing = o.lines[at];
          U.notice(orderCard, "Say how many "
            + (missing.stock ? (missing.stock.name || "of it") : missing.text) + ".");
          var input = linesBox.querySelector('[data-line="' + lineKey(missing, at)
                                             + '"] input');
          if (input) { input.focus(); }
          return;
        }
        var lines = o.lines.map(function (l) {
          return l.stock ? stockRequestLine(l.stock, l.qty, l.sup, o.links)
                         : otherRequestLine(l.text, l.qty, l.sup);
        });
        var label = lines.length === 1 ? describeRequest(lines[0])
                                       : lines.length + " things";
        var details = lines.map(function (l) {
          return describeRequest(l) + ", " + l.quantity;
        }).join("; ").slice(0, 500);
        send.disabled = true;
        // The step 40 way files the supplier and stock item and tells the
        // managers once. Before step 40, one request each.
        var sending = o.suppliers.length ? S.send({
          rpc: "request_supplies", label: "New order · " + label,
          body: { p_lines: lines, p_urgent: !!o.urgent, p_note: o.note.trim(),
                  p_client_ref: S.newRef() },
          log: { action: "supply_requested", details: details }
        }) : lines.reduce(function (prev, l) {
          return prev.then(function (res) {
            return S.send({
              rpc: "request_supply", label: "New order · " + describeRequest(l),
              body: { p_item: l.item, p_detail: l.detail, p_quantity: l.quantity,
                      p_urgent: !!o.urgent, p_note: o.note.trim(),
                      p_client_ref: S.newRef() },
              log: { action: "supply_requested",
                     details: describeRequest(l) + ", " + l.quantity }
            }).then(function (r) { return { queued: (res && res.queued) || r.queued }; });
          });
        }, Promise.resolve(null));
        sending.then(function (res) {
          NEW_ORDER = null;
          close();
          if (done) { done(res || {}); }
        }).catch(function (err) {
          send.disabled = false;
          U.notice(orderCard, notSetUp(err) ? NOT_SET_UP : err.message);
        });
      }

      find.addEventListener("input", function () {
        o.find = find.value; drawResults();
      });
      o.redraw = function () {
        if (document.body.contains(results)) {
          names = {};
          o.suppliers.forEach(function (s) { names[s.id] = s.name; });
          drawResults(); drawLines();
        }
      };
      drawResults();
      drawLines();
    });
  }

  /* ── Making a stock item on the phone ────────────────────────────────
     The same fields and the same choices as the desktop's Add Stock Item
     (db.STOCK_PRODUCT_TYPES, db.STOCK_UNITS - tests/web_app.py holds the
     two lists together), and a photo straight from the camera, made small
     before it goes up as the desktop does (photos.py). */

  var STOCK_TYPES = ["Stepped Filter", "V-form Filter", "Panel Filter",
    "Bag Filter", "Flyscreen", "Media Roll", "Wire", "Channel", "Spline",
    "Flyscreen Corner", "Frame / Housing", "Hardware / Fasteners",
    "Consumables", "Other"];
  var STOCK_UNITS = ["each", "m2", "metre", "roll", "kg", "box", "pack",
    "sheet", "pair", "set"];
  var PHOTO_SIDE = 1600;

  // A camera photo is 4000 pixels and several megabytes; a stock card needs
  // a fraction of that. Anything the browser cannot draw goes up as it is.
  function shrinkPhoto(file) {
    return new Promise(function (resolve) {
      if (!file || !/^image\//.test(file.type || "")) { resolve(file); return; }
      var url = URL.createObjectURL(file);
      var img = new Image();
      img.onload = function () {
        var scale = Math.min(1, PHOTO_SIDE / Math.max(img.width, img.height));
        var c = document.createElement("canvas");
        c.width = Math.max(1, Math.round(img.width * scale));
        c.height = Math.max(1, Math.round(img.height * scale));
        c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
        URL.revokeObjectURL(url);
        c.toBlob(function (blob) { resolve(blob || file); }, "image/jpeg", 0.85);
      };
      img.onerror = function () { URL.revokeObjectURL(url); resolve(file); };
      img.src = url;
    });
  }

  // The photo up to stock-images as <id>.jpg, and the item pointed at it -
  // with ?v= so every phone and PC shows the new one, not one it kept.
  function sendStockPhoto(id, file) {
    return shrinkPhoto(file).then(function (blob) {
      var path = id + ".jpg";
      return D.upload("stock-images", path, blob, "image/jpeg").then(function () {
        var url = D.publicUrl("stock-images", path) + "?v=" + Math.floor(Date.now() / 1000);
        return D.update("stock_items", { "id": "eq." + id },
                        { image_url: url, updated_at: new Date().toISOString() })
          .then(function () { return url; });
      });
    });
  }

  function stockDuplicate(rows, name, sku) {
    var n = lower(name), k = lower(sku);
    return (rows || []).filter(function (s) {
      return (n && lower(s.name) === n) || (k && lower(s.sku) === k);
    })[0] || null;
  }

  function newStockItem(rows) {
    U.openSheet(function (body, close) {
      body.appendChild(U.el("h2", { cls: "title", text: "New stock item" }));
      function field(label, input) {
        body.appendChild(U.el("label", { cls: "f", kids: [
          U.el("span", { text: label }), input] }));
        return input;
      }
      function select(id, values, chosen) {
        return U.el("select", { attr: { id: id }, kids: values.map(function (v) {
          var o = U.el("option", { text: v, attr: { value: v } });
          if (v === chosen) { o.selected = true; }
          return o;
        }) });
      }
      var name = field("Name *", U.el("input", { attr: { type: "text", id: "ns-name",
        placeholder: "e.g. G4 media roll 1m" } }));
      var sku = field("SKU / barcode", U.el("input", { attr: { type: "text", id: "ns-sku" } }));
      var type = field("Type", select("ns-type", STOCK_TYPES, "Other"));
      var unit = field("Counted in", select("ns-unit", STOCK_UNITS, "each"));
      var row = U.el("div", { cls: "ns-two" });
      body.appendChild(row);
      var onHand = U.el("input", { attr: { type: "number", id: "ns-on", inputmode: "decimal",
                                           min: "0", step: "any", value: "0" } });
      var least = U.el("input", { attr: { type: "number", id: "ns-min", inputmode: "decimal",
                                          min: "0", step: "any", value: "0" } });
      row.appendChild(U.el("label", { cls: "f", kids: [U.el("span", { text: "On hand" }), onHand] }));
      row.appendChild(U.el("label", { cls: "f", kids: [U.el("span", { text: "Minimum" }), least] }));
      var where = field("Location", U.el("input", { attr: { type: "text", id: "ns-loc",
        placeholder: "e.g. Rack A1" } }));
      var supplier = field("Supplier", U.el("input", { attr: { type: "text", id: "ns-sup" } }));
      var desc = field("Description", U.el("textarea", { attr: { id: "ns-desc", rows: "2" } }));

      var picked = { file: null };
      var pick = U.el("input", { attr: { type: "file", accept: "image/*",
        capture: "environment", id: "ns-photo", style: "display:none" } });
      var preview = U.el("div", { cls: "ns-preview" });
      pick.addEventListener("change", function () {
        picked.file = pick.files && pick.files[0];
        U.clear(preview);
        if (picked.file) {
          preview.appendChild(U.el("img", { attr: { alt: "",
            src: URL.createObjectURL(picked.file) } }));
        }
      });
      body.appendChild(pick);
      body.appendChild(U.el("div", { cls: "row-actions", kids: [
        U.button("📷  Take a photo", function () { pick.click(); }, "quiet")] }));
      body.appendChild(preview);

      var save = U.button("Save item", function () {
        var n = name.value.trim();
        if (!n) { U.notice(body, "Give it a name."); name.focus(); return; }
        var on = Number(onHand.value || 0), min = Number(least.value || 0);
        if (!isFinite(on) || !isFinite(min) || on < 0 || min < 0) {
          U.notice(body, "On hand and minimum are numbers, nought or more.");
          return;
        }
        var same = stockDuplicate(rows, n, sku.value.trim());
        if (same && !window.confirm("There is already a stock item \"" + same.name
            + "\"" + (same.sku ? " (SKU " + same.sku + ")" : "")
            + ". Make another one anyway?")) {
          return;
        }
        save.disabled = true;
        var who = D.cachedProfile().full_name || D.cachedProfile().username || "";
        D.insert("stock_items", {
          name: n, sku: sku.value.trim(), product_type: type.value,
          unit: unit.value, stock_on_hand: on, minimum_on_hand: min,
          location: where.value.trim(), supplier: supplier.value.trim(),
          description: desc.value.trim(), created_by_name: who,
          updated_at: new Date().toISOString()
        }).then(function (made) {
          var item = (made && made[0]) || {};
          D.insert("audit_log", { user_id: (D.whoami() || {}).id, username: who,
            action: "stock_created", details: ("Item: " + n + "  Type: " + type.value
            + "  (from a phone)").slice(0, 500) }, true).catch(function () {});
          if (!picked.file || !item.id) { return item; }
          return sendStockPhoto(item.id, picked.file).then(function (url) {
            item.image_url = url;
            return item;
          }).catch(function (err) {
            U.notice(body, "Saved, but the photo did not go up: " + err.message);
            return item;
          });
        }).then(function (item) {
          close();
          show("stock");
          U.toast("Made " + (item.name || n) + ".");
        }).catch(function (err) {
          save.disabled = false;
          U.notice(body, err.message);
        });
      }, "go");
      save.setAttribute("id", "ns-save");
      body.appendChild(U.el("div", { cls: "row-actions", kids: [
        save, U.button("Cancel", close, "quiet")] }));
      name.focus();
    });
  }

  function openStock(item, all) {
    U.openSheet(function (body, close) {
      body.appendChild(U.el("h2", { cls: "title",
        text: item.name || "Stock item" }));
      body.appendChild(U.el("div", { cls: "muted",
        text: [item.sku ? "SKU " + item.sku : "",
               item.media_type ? "Media " + item.media_type : "",
               item.unit ? "Per " + item.unit : ""]
              .filter(Boolean).join("   ·   ") }));
      if (item.image_url) {
        body.appendChild(U.el("img", { cls: "stock-photo",
          attr: { src: item.image_url, alt: item.name || "" } }));
      }
      if (D.roleLevel() >= 3) {
        // A manager photographs the item where it sits.
        var snap = U.el("input", { attr: { type: "file", accept: "image/*",
          capture: "environment", id: "stock-photo-pick", style: "display:none" } });
        snap.addEventListener("change", function () {
          var file = snap.files && snap.files[0];
          if (!file) { return; }
          U.notice(body, "Sending the photo…", "ok");
          sendStockPhoto(item.id, file).then(function (url) {
            item.image_url = url;
            U.closeAllSheets();
            show("stock");
            U.toast("Photo saved for " + (item.name || "the item") + ".");
          }).catch(function (err) { U.notice(body, err.message); });
        });
        body.appendChild(snap);
        var change = U.button(item.image_url ? "📷  Change photo" : "📷  Add a photo",
                              function () { snap.click(); }, "quiet");
        change.setAttribute("id", "stock-photo");
        body.appendChild(U.el("div", { cls: "row-actions", kids: [change] }));
      }
      if (item.description) {
        body.appendChild(U.el("p", { text: item.description,
                                     attr: { style: "margin:8px 0 12px" } }));
      }

      var onHand = U.el("div", {
        text: String(item.stock_on_hand || 0),
        attr: { style: "font-size:30px;font-weight:700" } });
      var onHandCard = U.card("On hand", [onHand,
        U.el("div", { cls: "muted",
          text: "Minimum " + (item.minimum_on_hand || 0) })]);
      body.appendChild(onHandCard);
      // What open orders have spoken for (worked out by the desktop).
      if (feature("stock_reserve")) {
        D.select("stock_reserved", { "select": "reserved,orders",
                                     "item_id": "eq." + item.id })
          .then(function (rows) {
            var r = (rows || [])[0];
            if (!r || !Number(r.reserved)) { return; }
            onHandCard.appendChild(U.el("div", { cls: "spoken",
              attr: { id: "stock-spoken" },
              text: qtyText(r.reserved) + " on " + r.orders + " job"
                  + (r.orders === 1 ? "" : "s") + " · "
                  + qtyText(Number(item.stock_on_hand || 0) - Number(r.reserved))
                  + " free" }));
          }).catch(function () {});
      }
      if (feature("price_history")) {
        D.select("supplier_prices", { "select": "bought_at,supplier,unit_price,po_number",
                                      "stock_item_id": "eq." + item.id,
                                      "order": "bought_at.desc", "limit": 6 })
          .then(function (rows) {
            if (!rows || !rows.length) { return; }
            onHandCard.parentNode.insertBefore(U.card("What we've paid", [
              U.table(["When", "Supplier", { text: "Each", num: true }],
                rows.map(function (r) {
                  return U.el("tr", { kids: [
                    U.cell(String(r.bought_at || "").slice(0, 10)),
                    U.cell(r.supplier || ""),
                    U.cell("$" + money2(r.unit_price), { num: true })] });
                }))]), onHandCard.nextSibling);
          }).catch(function () {});
      }

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

  /* ── The bell ──────────────────────────────────────────────────────────
     Same rules as the desktop's: nothing at all when nothing is unread, the
     number up to 99, then "99+". Asked every half minute, and again the
     moment the phone is picked back up - a phone that slept through the
     morning should not show the morning's count for another thirty
     seconds. */

  var BELL_EVERY = 30000;
  var bellTimer = null;

  function badgeText(n) {
    n = parseInt(n, 10);
    if (!isFinite(n) || n <= 0) { return ""; }
    return n > 99 ? "99+" : String(n);
  }

  function setBell(n) {
    var bell = document.getElementById("bell");
    var badge = document.getElementById("bell-badge");
    if (!bell || !badge) { return; }
    var text = badgeText(n);
    badge.textContent = text;
    badge.classList.toggle("hidden", !text);
    bell.classList.toggle("has", !!text);
    bell.setAttribute("aria-label", text
      ? text + " new notification" + (text === "1" ? "" : "s")
      : "Notifications");
  }

  function pollBell() {
    if (!D.signedIn()) { return; }
    // Out of signal, or before the migration is run, the bell keeps what
    // it last knew rather than flashing an error every thirty seconds.
    D.rpc("my_unread_count", {}).then(function (n) {
      setBell(n);
    }).catch(function () {});
    if (feature("staff_chat")) { pollChats(); }
    if (feature("sops") && SOPS === null) { loadSops().catch(function () {}); }
  }

  function watchBell() {
    if (bellTimer) { return; }
    bellTimer = setInterval(pollBell, BELL_EVERY);
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) { pollBell(); }
    });
  }

  function ago(iso) {
    var t = Date.parse(iso || "");
    if (!isFinite(t)) { return ""; }
    var secs = Math.max(0, Math.floor((Date.now() - t) / 1000));
    if (secs < 60) { return "just now"; }
    if (secs < 3600) { return Math.floor(secs / 60) + " min ago"; }
    if (secs < 86400) { return Math.floor(secs / 3600) + " h ago"; }
    return Math.floor(secs / 86400) + " d ago";
  }

  /* A missing table is a setup step, not a fault. Said as what to do. */
  function notSetUp(err) {
    return /not there any more|does not exist|could not find/i
      .test((err && err.message) || "");
  }
  var NOT_SET_UP = "Supply requests are not switched on yet. Somebody "
                 + "needs to run migrate_supply_requests.sql in Supabase.";

  function bellSheet() {
    U.openSheet(function (body, close) {
      body.appendChild(U.el("h2", { text: "Notifications" }));
      var list = U.el("div", { kids: [U.el("div", { cls: "muted",
                                                    text: "Loading…" })] });
      body.appendChild(list);
      var actions = U.el("div", { cls: "row-actions" });
      body.appendChild(actions);

      D.select("notifications", {
        "select": "*", "order": "created_at.desc", "limit": 40
      }).then(function (rows) {
        U.clear(list);
        var unread = rows.filter(function (r) { return !r.read_at; });
        if (!rows.length) {
          list.appendChild(U.empty("Nothing here yet.",
            "When somebody asks for supplies, managers are told here."));
        }
        rows.forEach(function (r) {
          list.appendChild(U.el("button", {
            cls: "note-row" + (r.read_at ? "" : " new"),
            attr: { type: "button", "data-note": r.id },
            on: { click: function () { openNote(r, close); } },
            kids: [
              U.el("span", { cls: "when", text: ago(r.created_at) }),
              U.el("strong", { text: r.title || "" }),
              r.body ? U.el("span", { cls: "muted", text: r.body }) : null
            ]
          }));
        });
        U.clear(actions);
        if (unread.length) {
          actions.appendChild(U.button("Mark all read", function () {
            D.rpc("mark_notifications_read", { p_ids: null })
              .then(function () { setBell(0); close(); })
              .catch(function (err) { U.notice(body, err.message); });
          }, "quiet"));
        }
        actions.appendChild(U.button("Open Supplies", function () {
          close(); show("supplies");
        }, "quiet"));
        actions.appendChild(U.button("Close", close, "quiet"));
      }).catch(function (err) {
        U.clear(list);
        U.notice(body, notSetUp(err) ? NOT_SET_UP : err.message);
        actions.appendChild(U.button("Close", close, "quiet"));
      });
    });
  }

  function openNote(row, close) {
    close();
    show("supplies");
    if (!row.read_at) {
      D.rpc("mark_notifications_read", { p_ids: [row.id] })
        .then(pollBell).catch(function () {});
    }
  }

  /* ── Supplies ──────────────────────────────────────────────────────────
     Ask here and every manager's bell goes red. The list is everybody's,
     so the second person out of tape sees it is already on its way. */

  function sortRequests(rows) {
    var rank = { open: 0, ordered: 1, received: 2, declined: 3,
                 cancelled: 4 };
    return rows.slice().sort(function (a, b) {
      var ua = (a.status === "open" && a.urgent) ? 0 : 1;
      var ub = (b.status === "open" && b.urgent) ? 0 : 1;
      if (ua !== ub) { return ua - ub; }
      var ra = rank[a.status] === undefined ? 9 : rank[a.status];
      var rb = rank[b.status] === undefined ? 9 : rank[b.status];
      if (ra !== rb) { return ra - rb; }
      var ta = String(a.created_at || ""), tb = String(b.created_at || "");
      // Waiting: the one waiting longest first. Everything else: newest.
      if (a.status === "open") { return ta < tb ? -1 : (ta > tb ? 1 : 0); }
      return ta > tb ? -1 : (ta < tb ? 1 : 0);
    });
  }

  function describeRequest(r) {
    var text = (r.item || "") + (r.detail ? " - " + r.detail : "");
    return text;
  }

  /* Everything asked for in one New order is one order on the list, the
     way Orders shows a job: one card, its lines in it, moved along all at
     once. The same rules as supplies.py's group_requests, order_label and
     lines_to_move - a test holds the two together. */

  function orderStatus(lines) {
    var have = {};
    lines.forEach(function (l) { have[l.status || "open"] = true; });
    var order = ["open", "ordered", "received", "declined"];
    for (var i = 0; i < order.length; i++) {
      if (have[order[i]]) { return order[i]; }
    }
    return "cancelled";
  }

  function groupRequests(rows) {
    var byKey = {}, keys = [];
    (rows || []).forEach(function (r) {
      var key = String(r.batch_id || r.id || "");
      if (!byKey[key]) { byKey[key] = []; keys.push(key); }
      byKey[key].push(r);
    });
    return sortRequests(keys.map(function (key) {
      var lines = byKey[key].slice().sort(function (a, b) {
        var ka = String(a.client_ref || "") + "|" + String(a.created_at || "");
        var kb = String(b.client_ref || "") + "|" + String(b.created_at || "");
        return ka < kb ? -1 : (ka > kb ? 1 : 0);
      });
      var first = lines[0];
      var handled = lines.filter(function (l) { return l.handled_by_name; })[0];
      return {
        key: key, lines: lines, status: orderStatus(lines),
        urgent: lines.some(function (l) {
          return !!l.urgent && (l.status || "open") === "open";
        }),
        created_at: lines.map(function (l) { return String(l.created_at || ""); })
                         .sort()[0],
        requested_by: first.requested_by,
        requested_by_name: first.requested_by_name || "",
        handled_by_name: handled ? handled.handled_by_name : "",
        note: first.note || ""
      };
    }));
  }

  function orderLabel(order) {
    var lines = order.lines, status = order.status;
    var label = SUPPLY_STATUS[status] || status;
    var moved = lines.filter(function (l) { return (l.status || "open") !== status; });
    if (moved.length && lines.length > 1) {
      if (status === "open") {
        label += " - " + moved.length + " of " + lines.length + " dealt with";
      } else if (status === "ordered") {
        var here = lines.filter(function (l) { return l.status === "received"; }).length;
        if (here) { label += " - " + here + " of " + lines.length + " here"; }
      }
    } else if (status !== "open" && order.handled_by_name) {
      label += " - " + order.handled_by_name;
    }
    return label;
  }

  function orderSummary(order, most) {
    most = most || 2;
    var names = order.lines.map(describeRequest);
    var text = names.slice(0, most).join(", ");
    if (names.length > most) { text += " + " + (names.length - most) + " more"; }
    return text;
  }

  function linesToMove(lines, to) {
    return lines.filter(function (l) {
      return (SUPPLY_NEXT[l.status || "open"] || []).indexOf(to) >= 0;
    });
  }

  function linesToCancel(lines, me) {
    return lines.filter(function (l) {
      return (l.status || "open") === "open"
             && String(l.requested_by || "") === String(me || "");
    });
  }

  SCREENS.supplies = function (main) {
    var showDone = !!SCREENS.supplies._showDone;

    // Who each line comes from, by name.
    var suppliers = {};
    D.select("suppliers", { "select": "id,name", "active": "eq.true",
                            "order": "name" }).then(function (rows) {
      (rows || []).forEach(function (r) { suppliers[r.id] = r.name; });
      if ((rows || []).length && lastRows) { draw(lastRows); }
    }).catch(function () { /* step 40 not run */ });
    var lastRows = null;

    // ── Asking: New order, from the stock list or typed ───────────────
    var newOrder = U.button("+  New order", function () {
      openNewOrder(function (res) {
        U.notice(listCard, res.queued
          ? "Kept on this phone. It goes when the signal is back, and the "
            + "managers are told then."
          : "Sent - the managers have been told.", "ok");
        if (!res.queued) { loadList(); }
      });
    }, "go");
    newOrder.setAttribute("id", "supply-new-order");
    var top = U.el("div", { cls: "supply-top", kids: [
      U.el("div", { kids: [
        U.el("b", { text: "Need something?" }),
        U.el("div", { cls: "muted",
          text: "Pick from the stock list, or type what isn't on it. "
              + "Every manager is told." })] }),
      newOrder] });

    // ── What has been asked for ───────────────────────────────────────
    var listCard = U.card("Asked for", []);
    var toggle = U.button(showDone ? "Hide finished" : "Show finished",
      function () {
        SCREENS.supplies._showDone = !showDone;
        show("supplies");
      }, "quiet");
    var listBody = U.el("div", { kids: [U.el("div", { cls: "muted",
                                                      text: "Loading…" })] });
    listCard.appendChild(listBody);
    listCard.appendChild(U.el("div", { cls: "row-actions", kids: [toggle] }));

    U.clear(main);
    main.appendChild(top);
    main.appendChild(listCard);

    function loadList() {
      var params = { "select": "*", "order": "created_at.desc",
                     "limit": 200 };
      if (!showDone) { params.status = "in.(open,ordered)"; }
      D.select("supply_requests", params).then(function (rows) {
        lastRows = rows || [];
        draw(lastRows);
      }).catch(function (err) {
        U.clear(listBody);
        U.notice(listCard, notSetUp(err) ? NOT_SET_UP : err.message);
      });
    }

    function draw(rows) {
      U.clear(listBody);
      var orders = groupRequests(rows);
      if (!orders.length) {
        listBody.appendChild(U.empty("Nothing waiting.",
          "Press New order to ask for anything - it shows here until it "
          + "has arrived."));
        return;
      }
      var me = (D.whoami() || {}).id;
      var manager = D.roleLevel() >= 3;
      orders.forEach(function (order) {
        var status = order.status;
        var waiting = status === "open";
        var acts = U.el("div", { cls: "acts" });
        // The buttons are a courtesy. The database refuses anybody who is
        // not a manager, and anybody cancelling what is not theirs.
        if (manager) {
          ["ordered", "received", "declined"].forEach(function (to) {
            if (!linesToMove(order.lines, to).length) { return; }
            acts.appendChild(U.button(
              { ordered: "Ordered", received: "Received",
                declined: "Decline" }[to],
              function () { move(order, linesToMove(order.lines, to), to); },
              "quiet"));
          });
        }
        var mine = linesToCancel(order.lines, me);
        if (mine.length) {
          acts.appendChild(U.button("Cancel", function () {
            if (window.confirm("Cancel the request for "
                               + (mine.length === 1 ? describeRequest(mine[0])
                                  : "these " + mine.length + " things") + "?")) {
              move(order, mine, "cancelled");
            }
          }, "quiet"));
        }
        var label = orderLabel(order);
        var one = order.lines.length === 1;
        var lines = U.el("ul", { cls: "sup-lines" });
        order.lines.forEach(function (l) {
          var st = l.status || "open";
          lines.appendChild(U.el("li", {
            cls: st === "open" || st === "ordered" ? "" : "done",
            attr: { "data-request": l.id },
            kids: [U.el("span", { cls: "nm", text: describeRequest(l) }),
                   U.el("span", { cls: "q", text: l.quantity || "" }),
                   U.el("span", { cls: "from",
                                  text: suppliers[l.supplier_id] || "" }),
                   // Only where a line is somewhere other than its order.
                   st !== status
                     ? U.el("span", { cls: "pill s-" + (SUPPLY_STATUS[st] || st),
                                      text: SUPPLY_STATUS[st] || st })
                     : U.el("span")]
          }));
        });
        listBody.appendChild(U.el("div", {
          cls: "sup-order" + (order.urgent ? " urgent"
                              : (waiting || status === "ordered" ? "" : " done")),
          attr: { "data-order": order.key },
          kids: [
            U.el("div", { cls: "hd", kids: [
              U.el("b", { text: (order.urgent ? "URGENT  " : "")
                + (order.lines.length > 1
                   ? order.lines.length + " items" : orderSummary(order)) }),
              U.el("span", { cls: "pill s-" + (SUPPLY_STATUS[status] || status),
                             text: label })] }),
            // One thing on it: how many and who from go up here rather
            // than under the same words again.
            one ? U.el("div", { cls: "qty", text: [order.lines[0].quantity,
              suppliers[order.lines[0].supplier_id]
                ? "from " + suppliers[order.lines[0].supplier_id] : ""]
              .filter(Boolean).join("  ·  ") }) : U.el("span"),
            U.el("div", { cls: "meta", text: [order.requested_by_name,
              ago(order.created_at), order.note].filter(Boolean).join(" · ") }),
            one ? U.el("span") : lines,
            acts.childNodes.length ? acts : U.el("span")
          ] }));
      });
    }

    function move(order, lines, to) {
      // No row back means nothing changed - row-level security refuses by
      // matching nothing, not by raising. Said, rather than shown as done.
      Promise.all(lines.map(function (l) {
        return D.update("supply_requests", { "id": "eq." + l.id }, { status: to });
      })).then(function (got) {
        var changed = got.filter(function (rows) { return rows && rows.length; });
        if (!changed.length) {
          throw new Error("That didn't change anything - it may have "
                        + "been dealt with already, or it isn't yours "
                        + "to change.");
        }
        D.insert("audit_log", {
          user_id: (D.whoami() || {}).id,
          username: D.cachedProfile().username
                 || D.cachedProfile().full_name || "",
          action: "supply_" + to,
          details: lines.map(describeRequest).join("; ").slice(0, 500)
        }, true).catch(function () {});
        loadList();
        pollBell();
      }).catch(function (err) {
        U.notice(listCard, err.message);
        loadList();
      });
    }

    loadList();
  };

  return {
    start: start,
    updateReady: updateReady,
    _screens: SCREENS,
    _badgeText: badgeText,
    _setBell: setBell,
    _supplyItems: SUPPLY_ITEMS,
    _sales: { toChase: function (q, today) {
                return toChase(q, U.parseDate(today)).map(function (x) {
                  return { id: x.id, waited: x.waited }; });
              },
              chaseEmail: chaseEmail, mailto: mailtoLink,
              serviceDue: function (c, o, today, ahead) {
                return serviceDue(c, o, U.parseDate(today), ahead).map(function (r) {
                  return { name: r.customer.name, last: ymd(r.last),
                           due: ymd(r.due), late: r.late }; });
              },
              lostReasons: LOST_REASONS,
              watchMail: function (fn) { openMail = fn; } },
    _planning: { checkDue: function () {
                   var r = checkDue.apply(null, arguments);
                   return r && Object.assign({}, r, { day: ymd(r.day),
                     next_free: r.next_free ? ymd(r.next_free) : null });
                 },
                 describeFull: function (r) {
                   return describeFull(Object.assign({}, r, {
                     day: U.parseDate(r.day),
                     next_free: r.next_free ? U.parseDate(r.next_free) : null }));
                 },
                 repeatItems: repeatItems },
    _board: { may: chatMay, rulesWithDefaults: rulesWithDefaults,
              messageTime: function (iso, now) {
                return messageTime(iso, new Date(now)); },
              readState: readState,
              sopsForType: function (s, t) {
                return sopsForType(s, t).map(function (x) { return x.id; }); },
              byCategory: function (s) {
                return byCategory(s).map(function (g) {
                  return [g[0], g[1].map(function (x) { return x.id; })]; }); },
              forgetSops: function () { SOPS = null; },
              pollChats: pollChats },
    _stock: { types: STOCK_TYPES, units: STOCK_UNITS, duplicate: function (r, n, k) {
                var hit = stockDuplicate(r, n, k); return hit ? hit.id : null; } },
    _route: { suggest: function (s) { return suggestRoute(s).map(function (x) { return x.id; }); },
              apply: function (s, saved) {
                return applyRoute(s, saved).map(function (x) { return x.id; }); },
              mapsLinks: mapsLinks, addressText: addressText },
    _money: { progress: function (sold, target, today) {
                return targetProgress(sold, target, U.parseDate(today)); },
              text: function (sold, target, today) {
                var d = U.parseDate(today);
                return targetText(targetProgress(sold, target, d), d); } },
    _floor: { boardColumn: boardColumn, productionBoard: productionBoard,
              checksFor: checksFor, workingDaysOn: workingDaysOn,
              faultReasons: FAULT_REASONS, feature: feature,
              setFeatures: function (on) { FEATURES = on || {}; } },
    _supplyOrders: { group: groupRequests, label: orderLabel,
                     summary: orderSummary, status: orderStatus,
                     toMove: linesToMove, toCancel: linesToCancel },
    _newOrder: { searchStock: searchStock, newOrderPick: newOrderPick,
                 lowPicks: lowPicks, supplyItemFor: supplyItemFor,
                 stockRequestLine: stockRequestLine, onOrderOf: onOrderOf,
                 otherRequestLine: otherRequestLine,
                 open: openNewOrder, reset: function () { NEW_ORDER = null; } },
    _sortRequests: sortRequests,
    _stateBar: stateBar,
    _lookUp: lookUp,
    _outbox: outbox,
    _idle: function () { touched = 0; },      // for the tests
    _stillThere: stillThere,
    _progressCell: progressCell,
    _shapeOrder: shapeOrder,
    _openOrder: openOrder,
    _orders: function () { return ORDERS; },
    _stale: function () { loadedAt = 0; }
  };
})();
