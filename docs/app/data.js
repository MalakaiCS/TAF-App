/*
  Talking to Supabase from the staff web app.

  The same accounts as the desktop app, and the same rules: every table has
  row-level security on it, so what a signed-in account can read and change is
  decided by the database, not by this file. Nothing here is a permission
  check - hiding a button is a courtesy to the person using it, never a
  control. If the rules are wrong, hiding buttons will not save us.

  The publishable key below is public by design. It is already inside the
  Windows installer and in the customer portal, and on its own it opens
  nothing: the anonymous role has no access to any table.
*/
"use strict";

var TAFDATA = (function () {

  var URLBASE = "https://djexdkwohkylunnwbxpf.supabase.co";
  var KEY = "";                      // set by boot(), see index.html
  var SESSION = null;                // { access_token, refresh_token, user }
  var STORE = "taf_staff_session";

  function boot(url, key) {
    if (url) { URLBASE = url.replace(/\/+$/, ""); }
    KEY = key || "";
    try {
      var raw = localStorage.getItem(STORE);
      if (raw) { SESSION = JSON.parse(raw); }
    } catch (e) { SESSION = null; }
    return SESSION;
  }

  function remember(session) {
    SESSION = session;
    try {
      if (session) { localStorage.setItem(STORE, JSON.stringify(session)); }
      else { localStorage.removeItem(STORE); }
    } catch (e) { /* private window, or storage full */ }
  }

  function signedIn() { return !!(SESSION && SESSION.access_token); }

  function whoami() {
    return (SESSION && SESSION.user) || {};
  }

  function headers(extra) {
    var h = {
      "apikey": KEY,
      "Authorization": "Bearer " + (signedIn() ? SESSION.access_token : KEY),
      "Content-Type": "application/json"
    };
    if (extra) {
      Object.keys(extra).forEach(function (k) { h[k] = extra[k]; });
    }
    return h;
  }

  /* ── Signing in ─────────────────────────────────────────────────────────
     Deliberately vague on failure. "That email is not registered" tells
     someone which addresses exist, and this page is on the open internet. */

  function signIn(email, password) {
    return fetch(URLBASE + "/auth/v1/token?grant_type=password", {
      method: "POST",
      headers: { "apikey": KEY, "Content-Type": "application/json" },
      body: JSON.stringify({ email: email, password: password })
    }).then(function (r) {
      return r.json().then(function (body) {
        if (!r.ok) {
          throw new Error(r.status === 400
            ? "That email and password did not match."
            : (body.msg || body.error_description || "Could not sign in."));
        }
        remember({
          access_token: body.access_token,
          refresh_token: body.refresh_token,
          user: body.user || {}
        });
        return profile();
      });
    });
  }

  function signOut() {
    var token = signedIn() ? SESSION.access_token : "";
    remember(null);
    PROFILE = null;
    if (!token) { return Promise.resolve(); }
    return fetch(URLBASE + "/auth/v1/logout", {
      method: "POST",
      headers: { "apikey": KEY, "Authorization": "Bearer " + token }
    }).catch(function () { /* the local session is gone either way */ });
  }

  /* An access token lasts an hour. Somebody who opens this on a tablet in the
     morning and picks it up after lunch must not be thrown back to the login
     screen - refresh once, quietly, and retry what they were doing. */
  var refreshing = null;

  function refresh() {
    if (!SESSION || !SESSION.refresh_token) {
      return Promise.reject(new Error("Signed out."));
    }
    if (refreshing) { return refreshing; }
    refreshing = fetch(URLBASE + "/auth/v1/token?grant_type=refresh_token", {
      method: "POST",
      headers: { "apikey": KEY, "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: SESSION.refresh_token })
    }).then(function (r) {
      if (!r.ok) { throw new Error("Signed out."); }
      return r.json();
    }).then(function (body) {
      remember({
        access_token: body.access_token,
        refresh_token: body.refresh_token,
        user: body.user || (SESSION && SESSION.user) || {}
      });
      refreshing = null;
      return SESSION;
    }).catch(function (err) {
      refreshing = null;
      remember(null);
      throw err;
    });
    return refreshing;
  }

  /* ── Asking the database for things ─────────────────────────────────── */

  function request(path, options, retried) {
    var opts = options || {};
    return fetch(URLBASE + path, {
      method: opts.method || "GET",
      headers: headers(opts.headers),
      body: opts.body ? JSON.stringify(opts.body) : undefined
    }).then(function (r) {
      if (r.status === 401 && !retried && SESSION && SESSION.refresh_token) {
        return refresh().then(function () {
          return request(path, options, true);
        });
      }
      if (!r.ok) {
        return r.text().then(function (text) {
          var detail = text;
          try { detail = (JSON.parse(text).message || text); } catch (e) {}
          throw new Error(friendly(r.status, detail));
        });
      }
      if (r.status === 204) { return null; }
      return r.text().then(function (text) {
        return text ? JSON.parse(text) : null;
      });
    });
  }

  /* Postgres speaks in constraint names. A person needs to know whether to
     ring someone or try again. */
  function friendly(status, detail) {
    var text = String(detail || "");
    if (/row-level security/i.test(text)) {
      return "Your account is not allowed to do that.";
    }
    if (/JWT|token is expired/i.test(text)) {
      return "You have been signed out. Sign in again.";
    }
    if (status === 404) { return "That is not there any more."; }
    if (status >= 500) {
      return "The database is not answering. Try again in a moment.";
    }
    return text || ("Something went wrong (" + status + ").");
  }

  function qs(params) {
    var parts = [];
    Object.keys(params || {}).forEach(function (k) {
      if (params[k] === undefined || params[k] === null) { return; }
      parts.push(encodeURIComponent(k) + "=" + encodeURIComponent(params[k]));
    });
    return parts.length ? "?" + parts.join("&") : "";
  }

  function select(table, params) {
    return request("/rest/v1/" + table + qs(params)).then(function (rows) {
      return rows || [];
    });
  }

  function rpc(name, body) {
    return request("/rest/v1/rpc/" + name, { method: "POST", body: body || {} });
  }

  function insert(table, row) {
    return request("/rest/v1/" + table, {
      method: "POST", body: row,
      headers: { "Prefer": "return=representation" }
    });
  }

  function update(table, match, patch) {
    return request("/rest/v1/" + table + qs(match), {
      method: "PATCH", body: patch,
      headers: { "Prefer": "return=representation" }
    });
  }

  function remove(table, match) {
    return request("/rest/v1/" + table + qs(match), {
      method: "DELETE",
      headers: { "Prefer": "return=representation" }
    });
  }

  /* ── Who is signed in ───────────────────────────────────────────────────
     The profile row, not the auth user: the name, the role and whether they
     have been approved all live there. */

  var PROFILE = null;

  function profile(force) {
    if (PROFILE && !force) { return Promise.resolve(PROFILE); }
    var id = whoami().id;
    if (!id) { return Promise.resolve(null); }
    return select("profiles", { "id": "eq." + id, "select": "*" })
      .then(function (rows) {
        PROFILE = (rows && rows[0]) || {};
        return PROFILE;
      })
      .catch(function () { PROFILE = {}; return PROFILE; });
  }

  function cachedProfile() { return PROFILE || {}; }

  /* The desktop app's ladder, kept in step: Employee 1, Manager 3,
     Admin 4, Director 5. Used only to decide what to show. */
  var ROLE_LEVEL = {
    "employee": 1, "staff": 1, "manager": 3, "admin": 4, "director": 5
  };

  function roleLevel() {
    var role = String(cachedProfile().role || "").trim().toLowerCase();
    return ROLE_LEVEL[role] || 1;
  }

  function canManagePrices() { return roleLevel() >= 3; }
  function canManageStock() { return roleLevel() >= 3; }
  function canManageStaff() { return roleLevel() >= 4; }

  return {
    boot: boot, signIn: signIn, signOut: signOut, signedIn: signedIn,
    refresh: refresh, whoami: whoami, profile: profile,
    cachedProfile: cachedProfile, roleLevel: roleLevel,
    canManagePrices: canManagePrices, canManageStock: canManageStock,
    canManageStaff: canManageStaff,
    select: select, rpc: rpc, insert: insert, update: update, remove: remove,
    request: request, friendly: friendly,
    _session: function () { return SESSION; }
  };
})();
