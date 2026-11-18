/*
  Work that was done before the signal came back.

  Ticking a line off is not a request, it is a fact: the filter is made,
  whatever the wifi is doing. So a write that cannot go now is kept on the
  phone and sent when it can, in the order it happened, and the person is
  told plainly that it is waiting rather than being shown a tick that went
  nowhere.

  Two rules make this safe rather than merely convenient.

  Order. Anything already waiting goes first, and a new write joins the back
  of the queue rather than overtaking it. Otherwise a tick and the untick that
  followed it arrive the wrong way round and the order ends up saying the
  opposite of what happened.

  Repeats. A queued write may well be sent twice - the phone can send it,
  lose the signal before the answer arrives, and try again. Every one of them
  has to be safe to repeat. Setting a line to "made" twice is the same as
  once. Merging the same patch into a header twice is the same as once. A
  stock movement is not, which is exactly what the client reference in
  adjust_stock_atomic is for, and why nothing goes in this queue without one.
*/
"use strict";

var TAFSYNC = (function () {

  var OUTBOX  = "taf_outbox";
  var BROKEN  = "taf_outbox_failed";
  var SEEN    = "taf_seen_";
  var LIMIT   = 400;              // a runaway queue is a bug, not a backlog

  var watchers = [];
  var sending  = null;

  /* ── The box itself ──────────────────────────────────────────────────── */

  function read(key) {
    try {
      var raw = localStorage.getItem(key);
      var list = raw ? JSON.parse(raw) : [];
      return Array.isArray(list) ? list : [];
    } catch (e) { return []; }
  }

  function write(key, list) {
    try { localStorage.setItem(key, JSON.stringify(list)); }
    catch (e) { /* private window, or full - see hold() */ }
  }

  function pending() { return read(OUTBOX).length; }
  function waiting() { return read(OUTBOX); }
  function failed()  { return read(BROKEN); }

  function forget() { write(BROKEN, []); changed(); }

  /* Only ever on purpose, and only ever with somebody told what they are
     throwing away. Signing out with work still queued is the one place it
     comes up: the next person to use the phone must not send the last
     person's ticks under their own name. */
  function discard() { write(OUTBOX, []); changed(); }

  function onChange(fn) { watchers.push(fn); }

  function changed() {
    watchers.forEach(function (fn) {
      try { fn(); } catch (e) { /* a broken watcher must not stop the rest */ }
    });
  }

  function online() { return navigator.onLine !== false; }

  function newRef() {
    return "web-" + Date.now() + "-" + Math.random().toString(16).slice(2, 8);
  }

  /* ── Sending one thing ───────────────────────────────────────────────── */

  function hold(job) {
    var list = read(OUTBOX);
    if (list.length >= LIMIT) {
      throw new Error("There are " + list.length + " changes already waiting "
                    + "to be sent. Get back into signal before doing more.");
    }
    list.push(job);
    write(OUTBOX, list);
    if (read(OUTBOX).length !== list.length) {
      throw new Error("This phone has no room to remember that. "
                    + "Get back into signal and try again.");
    }
    changed();
    return { sent: false, queued: true, job: job };
  }

  /* Try it now; keep it if the network is not there.

     `needs_row` says the function answers with the thing it changed, so
     nothing coming back means it changed nothing - a line that is no longer
     on the order. That has to be reported, not counted as sent. */
  function send(job) {
    job.id = job.id || newRef();
    job.at = job.at || new Date().toISOString();

    if (!online() || pending()) { return Promise.resolve(hold(job)); }

    return TAFDATA.rpc(job.rpc, job.body).then(function (out) {
      if (job.needs_row && empty(out)) {
        throw new Error(job.gone || "That is not there any more.");
      }
      trail(job, false);
      return { sent: true, out: out };
    }).catch(function (err) {
      if (err && err.offline) { return hold(job); }
      throw err;
    });
  }

  function empty(out) {
    if (out === null || out === undefined || out === "") { return true; }
    return Array.isArray(out) && out.length === 0;
  }

  /* ── Sending what is waiting ─────────────────────────────────────────── */

  function flush() {
    if (sending) { return sending; }
    if (!pending()) {
      return Promise.resolve({ sent: 0, kept: 0, failed: failed().length });
    }
    var sent = 0;

    function step() {
      var queue = read(OUTBOX);
      if (!queue.length) { return Promise.resolve(); }
      var job = queue[0];
      return TAFDATA.rpc(job.rpc, job.body).then(function (out) {
        drop();
        if (job.needs_row && empty(out)) {
          note(job, job.gone || "That is not there any more.");
        } else {
          trail(job, true);
          sent += 1;
        }
        return step();
      }).catch(function (err) {
        // No signal, or signed out: both are worth waiting for. Leave the
        // job where it is and stop - retrying the rest would only put them
        // through in the wrong order once it does come back.
        if (err && (err.offline || err.signedOut)) { return; }
        // The database said no. Keep going, or one refused change wedges
        // everything behind it forever, and say what happened.
        drop();
        note(job, err.message || "It was refused.");
        return step();
      });
    }

    sending = step().then(function () {
      sending = null;
      changed();
      return { sent: sent, kept: pending(), failed: failed().length };
    }, function (err) {
      sending = null;
      changed();
      throw err;
    });
    return sending;
  }

  /* One line in the log for what just went through.

     The database stamps the time, not the phone: a queue that has been
     waiting since the morning must not be able to rewrite the order of the
     day, and a phone with the wrong clock must not either. So when a change
     was made earlier than it was sent, that gap is written into the entry
     instead - visible, rather than smoothed over.

     Under the account signed in now, which is the same account that made
     the change: the app refuses to sign out while anything is still
     waiting, precisely so that stays true.

     Swallowed on failure. The change went through; the log is a bonus, and
     losing it must not turn a done job into an error on somebody's screen. */
  function trail(job, delayed) {
    if (!job.log) { return; }
    var me = TAFDATA.cachedProfile();
    var details = job.log.details || "";
    if (delayed && job.at) {
      details += "  ·  done " + clock(job.at) + ", sent when the signal "
               + "came back";
    }
    TAFDATA.insert("audit_log", {
      user_id: (TAFDATA.whoami() || {}).id,
      username: me.username || me.full_name || "",
      action: job.log.action,
      details: details
    }, true).catch(function () {});
  }

  function clock(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) { return String(iso); }
    function two(n) { return (n < 10 ? "0" : "") + n; }
    return two(d.getHours()) + ":" + two(d.getMinutes()) + " on "
         + two(d.getDate()) + "/" + two(d.getMonth() + 1);
  }

  function drop() {
    var list = read(OUTBOX);
    list.shift();
    write(OUTBOX, list);
  }

  function note(job, why) {
    var list = read(BROKEN);
    list.push({ label: job.label || job.rpc, why: why, at: job.at });
    write(BROKEN, list.slice(-50));
  }

  /* ── What was on the screen last time ────────────────────────────────
     Not a cache of the database - a note of what this phone was last shown,
     so it has something to put up while there is no signal. Everything drawn
     from it is labelled as remembered, because an order list from this
     morning presented as today's is how somebody gets sent out with the
     wrong pallet. */

  function remember(key, value) {
    try {
      localStorage.setItem(SEEN + key,
        JSON.stringify({ at: Date.now(), v: value }));
    } catch (e) {
      // Out of room. Half a list is still worth having; a quarter of one is
      // worth more than a blank screen.
      if (Array.isArray(value) && value.length > 20) {
        remember(key, value.slice(0, Math.floor(value.length / 2)));
      }
    }
  }

  function recall(key) {
    try {
      var raw = localStorage.getItem(SEEN + key);
      var box = raw ? JSON.parse(raw) : null;
      return (box && box.v !== undefined) ? box : null;
    } catch (e) { return null; }
  }

  function since(at) {
    var mins = Math.round((Date.now() - (at || 0)) / 60000);
    if (mins < 1)  { return "a moment ago"; }
    if (mins === 1) { return "a minute ago"; }
    if (mins < 60) { return mins + " minutes ago"; }
    var hrs = Math.round(mins / 60);
    if (hrs === 1) { return "an hour ago"; }
    if (hrs < 24)  { return hrs + " hours ago"; }
    return "yesterday or before";
  }

  /* ── Wiring ──────────────────────────────────────────────────────────── */

  function start() {
    window.addEventListener("online", function () {
      changed();
      flush().catch(function () { /* reported through the banner */ });
    });
    window.addEventListener("offline", changed);
    if (online() && pending()) {
      flush().catch(function () {});
    }
  }

  return {
    start: start, send: send, flush: flush, hold: hold,
    pending: pending, waiting: waiting, failed: failed, forget: forget,
    discard: discard,
    onChange: onChange, changed: changed, online: online, newRef: newRef,
    remember: remember, recall: recall, since: since
  };
})();
