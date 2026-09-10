/*
  The staff app, kept on the phone.

  The factory has wifi in the office and not much of it by the back roller
  door, which is where the racks are and where somebody stands with a phone
  ticking lines off. Without this, walking twenty metres turns the app into a
  blank page with a dinosaur on it.

  What it caches: this site's own files, and only the handful the app is made
  of. It never touches Supabase - those are another origin, so they fall
  straight through to the network. That is deliberate and not just tidiness:
  a cached answer from the database is a stale answer wearing a fresh one's
  clothes, and stock figures that are quietly an hour old are worse than an
  error message. Data that is safe to show while offline is remembered by the
  app itself, clearly marked as remembered.

  It lives at the top of the site rather than inside app/ so that company.js
  and taf-shared.js, which sit one level up, are inside its scope - a worker
  can only answer for requests at or below its own folder. It still refuses to
  answer for anything it did not put there itself, so the customer portal and
  the quote pages carry on exactly as they did.
*/
"use strict";

// Only bumped when the shape of what is stored changes; day-to-day edits to
// the app do not need it. Each file is re-fetched in the background on every
// load, so a change lands on the next open by itself.
var CACHE = "taf-app-shell-v1";

var SHELL = [
  "app/",
  "app/index.html",
  "app/data.js",
  "app/ui.js",
  "app/offline.js",
  "app/screens.js",
  "app/manifest.webmanifest",
  "app/icon-192.png",
  "app/icon-512.png",
  "company.js",
  "taf-shared.js",
  "taf-logo.png"
];

// The publishable key, written by CI. Always asked for over the network
// first: if it is ever rotated, a cached copy would lock every phone out of
// an app that looks fine and cannot sign in.
var CONFIG = "app/config.js";

function absolute(list) {
  return list.map(function (p) {
    return new URL(p, self.location).pathname;
  });
}

var MINE = absolute(SHELL.concat([CONFIG]));

self.addEventListener("install", function (e) {
  e.waitUntil(
    caches.open(CACHE).then(function (c) {
      // One at a time and forgiving. addAll is all-or-nothing, so a single
      // missing file - config.js before CI has ever run - would leave the
      // phone with nothing cached at all.
      return Promise.all(SHELL.concat([CONFIG]).map(function (p) {
        return c.add(new Request(p, { cache: "reload" }))
                .catch(function () { /* it can be picked up on first use */ });
      }));
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (e) {
  e.waitUntil(
    caches.keys().then(function (names) {
      return Promise.all(names.map(function (n) {
        return n === CACHE ? null : caches.delete(n);
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("message", function (e) {
  if (e.data && e.data.type === "skip-waiting") { self.skipWaiting(); }
});

self.addEventListener("fetch", function (e) {
  var req = e.request;
  if (req.method !== "GET") { return; }

  var url;
  try { url = new URL(req.url); } catch (err) { return; }

  // Supabase, Storage, anything else at all: not ours to answer.
  if (url.origin !== self.location.origin) { return; }

  var path = url.pathname;
  if (path === new URL(CONFIG, self.location).pathname) {
    e.respondWith(freshFirst(req));
    return;
  }
  if (MINE.indexOf(path) === -1) { return; }
  e.respondWith(cachedFirst(req));
});

/* Served from the cache straight away, and replaced in the background for
   next time. The app opens at the speed of the phone rather than the speed
   of the signal, which on a bad day is the difference between working and
   not. */
function cachedFirst(req) {
  return caches.open(CACHE).then(function (c) {
    return c.match(req, { ignoreSearch: true }).then(function (hit) {
      var fresh = fetch(req).then(function (r) {
        if (r && r.ok && (r.type === "basic" || r.type === "default")) {
          announce(hit, r.clone());
          c.put(req, r.clone());
        }
        return r;
      });
      if (hit) {
        fresh.catch(function () { /* no signal; the cached copy stands */ });
        return hit;
      }
      return fresh;
    });
  });
}

function freshFirst(req) {
  return caches.open(CACHE).then(function (c) {
    return fetch(req).then(function (r) {
      if (r && r.ok) { c.put(req, r.clone()); }
      return r;
    }).catch(function () {
      return c.match(req, { ignoreSearch: true }).then(function (hit) {
        if (hit) { return hit; }
        throw new Error("offline");
      });
    });
  });
}

/* Tell the open page when a file it is running has changed underneath it, so
   it can offer a reload rather than waiting for somebody to close the tab -
   which on a phone that lives on a bench is never. */
function announce(old, fresh) {
  if (!old) { return; }
  var was = old.headers.get("ETag") || old.headers.get("Last-Modified") || "";
  var now = fresh.headers.get("ETag") || fresh.headers.get("Last-Modified") || "";
  if (!was || !now || was === now) { return; }
  self.clients.matchAll({ type: "window" }).then(function (all) {
    all.forEach(function (client) { client.postMessage({ type: "updated" }); });
  });
}
