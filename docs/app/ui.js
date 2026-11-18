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

  // Controls whose clicks are their own. A click on one of these that sits
  // inside a clickable row belongs to the control: opening a dropdown in a
  // row must not also open the order the row stands for.
  var CONTROLS = "select, option, input, textarea, button, a, label";

  function ownClick(node, handler) {
    return function (e) {
      var hit = e.target && e.target.closest ? e.target.closest(CONTROLS)
                                             : null;
      if (hit && hit !== node && node.contains(hit)) { return; }
      return handler.call(this, e);
    };
  }

  function el(tag, opts) {
    var node = document.createElement(tag);
    var o = opts || {};
    if (o.text !== undefined) { node.textContent = String(o.text); }
    if (o.cls) { node.className = o.cls; }
    if (o.on) {
      Object.keys(o.on).forEach(function (k) {
        // Every clickable container gets the guard, so no screen has to
        // remember it. A control's own click handler is left alone.
        var guard = k === "click" && !/^(SELECT|OPTION|INPUT|TEXTAREA|BUTTON|A|LABEL)$/
          .test(node.tagName);
        node.addEventListener(k, guard ? ownClick(node, o.on[k]) : o.on[k]);
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

  /* One choice, one action. A <select> fires "input" and then "change" for
     the same choice, so a screen that listened for both did everything
     twice - including tearing the list down and drawing it again under the
     pointer. Text boxes still update as they are typed in; dropdowns,
     ticks and dates act once, when the value has actually changed. */
  function onPick(nodes, fn) {
    (nodes || []).forEach(function (node) {
      var typed = node.tagName === "TEXTAREA" ||
        (node.tagName === "INPUT" &&
         !/^(checkbox|radio|date|range|color|file)$/i.test(node.type || ""));
      var last = typed ? null : node.value;
      node.addEventListener(typed ? "input" : "change", function (e) {
        if (!typed) {
          var now = node.type === "checkbox" || node.type === "radio"
            ? String(node.checked) + node.value : node.value;
          if (now === last) { return; }
          last = now;
        }
        fn(e);
      });
    });
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
    // Each cell carries its column's heading, which a phone shows above the
    // value once the table has become a list of rows.
    var labels = headings.map(function (h) {
      return typeof h === "string" ? h : ((h && h.text) || "");
    });
    (rows || []).forEach(function (r) {
      Array.prototype.forEach.call(r.children || [], function (td, i) {
        if (labels[i] && !td.hasAttribute("data-label")) {
          td.setAttribute("data-label", labels[i]);
        }
      });
      tbody.appendChild(r);
    });
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
    swipeToClose(wrap);
    STACK.push(build);
    var body = clear(document.getElementById("sheet-body"));
    build(body, closeSheet);
    wrap.classList.remove("hidden");
    wrap.onclick = function (e) { if (e.target === wrap) { closeSheet(); } };
    document.addEventListener("keydown", escClose);
    return body;
  }

  function escClose(e) { if (e.key === "Escape") { closeSheet(); } }

  /* The handle at the top of a sheet does what it looks like it does: pull
     it down and the sheet follows the finger; let go far enough (or flick)
     and it closes, otherwise it springs back. From anywhere on the sheet,
     too, once it is scrolled to the top - but never from a signature pad,
     a text box or a list being scrolled, which want the finger for
     themselves. */
  function swipeToClose(wrap) {
    if (wrap._swipe) { return; }
    wrap._swipe = true;
    var panel = wrap.firstElementChild;
    var start = null, dy = 0, t0 = 0, dragging = false;

    function reset(animate) {
      panel.style.transition = animate && motionOK() ? "transform .2s ease" : "";
      panel.style.transform = "";
      wrap.style.background = "";
    }

    panel.addEventListener("touchstart", function (e) {
      if (e.touches.length !== 1) { start = null; return; }
      var target = e.target;
      if (target.closest && target.closest("canvas, input, textarea, select")) {
        start = null; return;
      }
      var r = panel.getBoundingClientRect();
      var onHandle = e.touches[0].clientY - r.top < 44;
      if (!onHandle && panel.scrollTop > 0) { start = null; return; }
      start = e.touches[0].clientY;
      dy = 0; t0 = Date.now(); dragging = false;
      panel.style.transition = "";
    }, { passive: true });

    panel.addEventListener("touchmove", function (e) {
      if (start === null) { return; }
      dy = e.touches[0].clientY - start;
      if (!dragging) {
        if (dy < 6) { if (dy < -6) { start = null; } return; }
        dragging = true;
      }
      e.preventDefault();               // the sheet moves, not the page
      panel.style.transform = "translateY(" + Math.max(0, dy) + "px)";
      wrap.style.background = "rgba(15,23,42," + Math.max(0, .45 - dy / 900) + ")";
    }, { passive: false });

    function end() {
      if (start === null) { return; }
      start = null;
      if (!dragging) { return; }
      var fast = dy > 40 && dy / Math.max(1, Date.now() - t0) > 0.6;
      if (dy > Math.min(160, panel.offsetHeight * 0.3) || fast) {
        panel.style.transition = motionOK() ? "transform .18s ease-in" : "";
        panel.style.transform = "translateY(100%)";
        setTimeout(function () { reset(false); closeSheet(); }, motionOK() ? 170 : 0);
      } else {
        reset(true);
      }
    }
    panel.addEventListener("touchend", end);
    panel.addEventListener("touchcancel", end);
  }

  /* A word at the top of the screen for a moment - a message has come in -
     that does something when tapped. */
  function toast(text, onTap) {
    var old = document.getElementById("toast");
    if (old) { old.remove(); }
    var t = el("button", { cls: "toast", text: text,
                           attr: { id: "toast", type: "button" } });
    t.addEventListener("click", function () { t.remove(); if (onTap) { onTap(); } });
    document.body.appendChild(t);
    setTimeout(function () { if (t.parentNode) { t.remove(); } }, 6000);
    return t;
  }

  /* No pinch-zooming the app, and no zooming in when a box is tapped. The
     viewport says so, and Safari - which ignores that in the browser -
     is told again by refusing its zoom gesture. Text boxes are 16px, the
     size below which an iPhone zooms in on one when it is tapped. */
  (function noZoom() {
    ["gesturestart", "gesturechange", "gestureend"].forEach(function (n) {
      document.addEventListener(n, function (e) { e.preventDefault(); },
                                { passive: false });
    });
    document.addEventListener("touchmove", function (e) {
      if (e.touches && e.touches.length > 1) { e.preventDefault(); }
    }, { passive: false });
    // A double tap is a tap: the stylesheet's touch-action: manipulation
    // stops it zooming without swallowing a second quick press.
  })();

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

  /* ── Motion ─────────────────────────────────────────────────────────
     Everything that moves goes through here, and none of it moves for
     anybody whose phone or computer is set to reduce motion - checked each
     time, so changing the setting takes effect without a reload. */

  function motionOK() {
    return !(window.matchMedia &&
             window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  // What fades and rises into view as the page scrolls: the cards a screen
  // is made of, and the stock cards and search results inside them.
  var REVEAL = ".card, .stock-card, .hit";
  var revealer = null;

  // Can the browser drive the animation from the scroll position itself?
  // Then the stylesheet does it all, and nothing here has to watch.
  var SCROLL_DRIVEN = !!(window.CSS && CSS.supports &&
                         CSS.supports("animation-timeline: view()"));

  function reveal(node, delay) {
    if (!motionOK()) { return; }
    if (SCROLL_DRIVEN) {
      node.classList.add("reveal");
      return;
    }
    if (!("IntersectionObserver" in window)) { return; }
    if (!revealer) {
      revealer = new IntersectionObserver(function (seen) {
        seen.forEach(function (e) {
          if (e.isIntersecting) {
            e.target.classList.add("in");
            revealer.unobserve(e.target);
          }
        });
      }, { rootMargin: "0px 0px -6% 0px" });
    }
    node.classList.add("reveal");
    // A grid arriving at once comes in one after another, briefly.
    node.style.transitionDelay = (delay || 0) + "ms";
    revealer.observe(node);
  }

  /* Watch an area of the page: anything matching REVEAL that is put in it
     from now on is revealed as it scrolls into view. The screens need do
     nothing - they draw as they always have. */
  function autoReveal(root) {
    if (!root || !("MutationObserver" in window)) { return; }
    new MutationObserver(function (changes) {
      if (!motionOK()) { return; }
      var n = 0;
      changes.forEach(function (c) {
        Array.prototype.forEach.call(c.addedNodes, function (added) {
          if (added.nodeType !== 1) { return; }
          var found = added.matches && added.matches(REVEAL) ? [added] : [];
          found = found.concat(Array.prototype.slice.call(
            added.querySelectorAll(REVEAL)));
          found.forEach(function (node) {
            if (!node.classList.contains("reveal")) {
              reveal(node, Math.min(n++, 8) * 35);
            }
          });
        });
      });
    }).observe(root, { childList: true, subtree: true });
  }

  /* One full turn of the TAF badge. A click while it is turning starts the
     turn again rather than queueing another. */
  function spin(img) {
    if (!img || !motionOK()) { return; }
    img.classList.remove("spin");
    void img.offsetWidth;            // restart the animation
    img.classList.add("spin");
  }

  return {
    motionOK: motionOK, reveal: reveal, autoReveal: autoReveal, spin: spin,
    el: el, clear: clear, onPick: onPick, card: card, table: table, cell: cell,
    button: button, pill: pill, empty: empty, notice: notice,
    parseDate: parseDate, dueBucket: dueBucket, today: today, money: money,
    openSheet: openSheet, closeSheet: closeSheet, toast: toast,
    closeAllSheets: closeAllSheets, sheetOpen: sheetOpen
  };
})();
