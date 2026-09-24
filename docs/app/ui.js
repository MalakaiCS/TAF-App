/*
  Building the page. No framework and no build step, matching the customer
  portal and the phone uploader — this is served straight off GitHub Pages and
  has to keep working with nothing installed.

  Everything that puts data on the page goes through here, and everything here
  sets textContent rather than innerHTML. A customer name is typed by a person
  and an order note can say anything; neither should ever be able to become
  markup.
*/
"use strict";

var TAFUI = (function () {

  function el(tag, opts) {
    var node = document.createElement(tag);
    var o = opts || {};
    if (o.text !== undefined) { node.textContent = String(o.text); }
    if (o.cls) { node.className = o.cls; }
    if (o.on) {
      Object.keys(o.on).forEach(function (k) {
        node.addEventListener(k, o.on[k]);
      });
    }
    if (o.attr) {
      Object.keys(o.attr).forEach(function (k) {
        if (o.attr[k] !== null && o.attr[k] !== undefined) {
          node.setAttribute(k, o.attr[k]);
        }
      });
    }
    (o.kids || []).forEach(function (kid) { if (kid) { node.appendChild(kid); } });
    return node;
  }

  function clear(node) {
    while (node && node.firstChild) { node.removeChild(node.firstChild); }
    return node;
  }

  function card(title, kids) {
    var box = el("div", { cls: "card" });
    if (title) { box.appendChild(el("h2", { text: title })); }
    (kids || []).forEach(function (k) { if (k) { box.appendChild(k); } });
    return box;
  }

  function table(headings, rows) {
    var thead = el("thead", {
      kids: [el("tr", {
        kids: headings.map(function (h) {
          return el("th", {
            text: typeof h === "string" ? h : h.text,
            cls: (h && h.num) ? "num" : ""
          });
        })
      })]
    });
    var tbody = el("tbody");
    (rows || []).forEach(function (r) { tbody.appendChild(r); });
    return el("div", {
      cls: "wrap",
      kids: [el("table", { kids: [thead, tbody] })]
    });
  }

  function cell(value, opts) {
    var o = opts || {};
    var td = el("td", { cls: o.num ? "num" : "" });
    if (o.node) { td.appendChild(o.node); }
    else { td.textContent = (value === null || value === undefined) ? "" : String(value); }
    return td;
  }

  function button(text, onClick, cls) {
    return el("button", {
      text: text, cls: "btn " + (cls || ""),
      attr: { type: "button" }, on: { click: onClick }
    });
  }

  function pill(status) {
    var key = String(status || "Pending").replace(/\s+/g, "");
    return el("span", { cls: "pill s-" + key, text: status || "Pending" });
  }

  function empty(text, hint) {
    return el("div", {
      cls: "empty",
      kids: [el("div", { text: text }),
             hint ? el("div", { cls: "muted", text: hint }) : null]
    });
  }

  /* A message that stays until it is replaced. Errors do not disappear on
     their own — somebody has to be able to read one that appeared while they
     were looking at the bench. */
  function notice(parent, text, kind) {
    var old = parent.querySelector(".err, .ok");
    if (old) { old.remove(); }
    if (!text) { return null; }
    var box = el("div", { cls: kind === "ok" ? "ok" : "err", text: text });
    parent.insertBefore(box, parent.firstChild);
    return box;
  }

  /* ── Dates ───────────────────────────────────────────────────────────
     Orders carry dd/mm/yyyy or dd/mm/yy, written by people. */

  function parseDate(text) {
    var s = String(text || "").trim();
    if (!s || /^asap$/i.test(s)) { return null; }
    var m = s.match(/^(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{2,4})$/);
    if (m) {
      var year = parseInt(m[3], 10);
      if (year < 100) { year += 2000; }
      var d = new Date(year, parseInt(m[2], 10) - 1, parseInt(m[1], 10));
      return isNaN(d.getTime()) ? null : d;
    }
    m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (m) {
      return new Date(parseInt(m[1], 10), parseInt(m[2], 10) - 1,
                      parseInt(m[3], 10));
    }
    return null;
  }

  function today() {
    var d = new Date(); d.setHours(0, 0, 0, 0); return d;
  }

  /* The same buckets the desktop app uses, and for the same reason: an order
     that is finished or gone is not due, whatever its date says. */
  var DONE = ["Complete", "Dispatched", "Delivered", "Collected"];

  function dueBucket(row) {
    var status = String((row && row.status) || "");
    if (DONE.indexOf(status) !== -1) { return "done"; }
    var due = parseDate(row && row.date_due);
    if (!due) { return "none"; }
    var now = today();
    var days = Math.round((due - now) / 86400000);
    if (days < 0) { return "overdue"; }
    if (days === 0) { return "today"; }
    if (days <= 7) { return "week"; }
    return "later";
  }

  function money(value) {
    var n = Number(value || 0);
    return "$" + n.toLocaleString(undefined, {
      minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  /* ── The sheet that slides over the list ─────────────────────────────
     A stack, not one panel. Signing for a delivery opens over the order it
     belongs to, and closing that has to go back to the order rather than
     throwing away the screen the person was working on. */

  var STACK = [];

  function openSheet(build) {
    var wrap = document.getElementById("sheet");
    STACK.push(build);
    var body = clear(document.getElementById("sheet-body"));
    build(body, closeSheet);
    wrap.classList.remove("hidden");
    wrap.onclick = function (e) { if (e.target === wrap) { closeSheet(); } };
    document.addEventListener("keydown", escClose);
    return body;
  }

  function escClose(e) { if (e.key === "Escape") { closeSheet(); } }

  function closeSheet() {
    STACK.pop();
    var back = STACK[STACK.length - 1];
    if (back) {
      // Rebuilt rather than remembered, so what it shows is what is true
      // now — a photo added underneath is there when you come back to it.
      var body = clear(document.getElementById("sheet-body"));
      back(body, closeSheet);
      return;
    }
    document.getElementById("sheet").classList.add("hidden");
    document.removeEventListener("keydown", escClose);
  }

  function closeAllSheets() {
    STACK.length = 0;
    document.getElementById("sheet").classList.add("hidden");
    document.removeEventListener("keydown", escClose);
  }

  function sheetOpen() {
    return !document.getElementById("sheet").classList.contains("hidden");
  }

  return {
    el: el, clear: clear, card: card, table: table, cell: cell,
    button: button, pill: pill, empty: empty, notice: notice,
    parseDate: parseDate, dueBucket: dueBucket, today: today, money: money,
    openSheet: openSheet, closeSheet: closeSheet,
    closeAllSheets: closeAllSheets, sheetOpen: sheetOpen
  };
})();
