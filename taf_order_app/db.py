"""
Supabase database + auth wrapper for TAF Order App.
"""
from __future__ import annotations

SUPABASE_URL = "https://djexdkwohkylunnwbxpf.supabase.co"

ROLE_LEVEL = {"Director": 4, "Admin": 4, "Manager": 3, "Employee": 1}

_client = None
_current_user   = None
_current_profile: dict | None = None   # {"username", "full_name", "role", ...}


def init(anon_key: str) -> None:
    global _client
    from supabase import create_client
    _client = create_client(SUPABASE_URL, anon_key)


def is_ready() -> bool:
    return _client is not None


def get_client():
    if _client is None:
        raise RuntimeError("Database not initialised — configure the API key first.")
    return _client


# ── Auth ──────────────────────────────────────────────────────────────────────

def sign_in(email: str, password: str):
    global _current_user, _current_profile
    resp = get_client().auth.sign_in_with_password({"email": email, "password": password})
    _current_user = resp.user
    try:
        _current_profile = _load_profile(str(resp.user.id))
    except Exception:
        _current_profile = None

    # Auto-create a minimal profile on first login if none exists yet
    if not _current_profile:
        try:
            # Derive a sensible display name from the email local part
            local = email.split("@")[0]
            base  = local.capitalize()
            username = generate_username(base)
            _current_profile = create_profile(
                str(resp.user.id), email, base, username, "Employee"
            )
        except Exception:
            _current_profile = {}

    return resp.user


def sign_up(email: str, password: str):
    global _current_user
    resp = get_client().auth.sign_up({"email": email, "password": password})
    # If email confirmation is disabled Supabase returns a live session immediately.
    # Set it so that auth.uid() works for the RLS check on profile insert.
    if resp.session:
        get_client().auth.set_session(
            resp.session.access_token,
            resp.session.refresh_token,
        )
        _current_user = resp.user
    return resp.user


def reset_password_for_email(email: str) -> None:
    get_client().auth.reset_password_for_email(email)


def sign_out() -> None:
    global _current_user, _current_profile
    try:
        get_client().auth.sign_out()
    except Exception:
        pass
    _current_user   = None
    _current_profile = None


def current_user():
    return _current_user


def current_email() -> str:
    return _current_user.email if _current_user else ""


def current_profile() -> dict:
    return _current_profile or {}


def is_approved() -> bool:
    """Whether this account has been approved as staff.

    Being signed in is not the same as being staff: the publishable key is
    public, so anyone holding it can create an account. Approval is what
    actually grants access, and the database enforces it — this only decides
    what the app says rather than letting it fail with empty screens.

    A database that predates migrate_staff_access.sql has no `approved`
    column; there, everyone signed in is treated as staff, exactly as before.
    """
    profile = current_profile() or {}
    if "approved" not in profile:
        return True
    return bool(profile.get("approved"))


def current_role() -> str:
    return current_profile().get("role", "Employee")


def current_username() -> str:
    return current_profile().get("username", current_email())


def current_full_name() -> str:
    return current_profile().get("full_name", "")


def role_level(role: str | None = None) -> int:
    return ROLE_LEVEL.get(role or current_role(), 1)


def can_manage_roles() -> bool:
    """Managers and above can assign roles."""
    return role_level() >= 3


# ── Profiles ──────────────────────────────────────────────────────────────────

def _load_profile(user_id: str) -> dict | None:
    resp = get_client().table("profiles").select("*").eq("id", user_id).single().execute()
    return resp.data


def generate_username(full_name: str) -> str:
    """First letter of first name + last name, deduplicated against DB."""
    parts = full_name.strip().split()
    if len(parts) >= 2:
        base = parts[0][0].upper() + parts[-1].capitalize()
    elif parts:
        base = parts[0].capitalize()
    else:
        base = "User"

    existing = {
        r["username"].lower()
        for r in (get_client().table("profiles").select("username").execute().data or [])
    }
    username = base
    counter  = 2
    while username.lower() in existing:
        username = f"{base}{counter}"
        counter += 1
    return username


def create_profile(user_id: str, email: str, full_name: str,
                   username: str, role: str = "Employee") -> dict:
    data = {
        "id":        user_id,
        "email":     email,
        "full_name": full_name,
        "username":  username,
        "role":      role,
    }
    resp = get_client().table("profiles").upsert(data).execute()
    return resp.data[0] if resp.data else data


def get_all_profiles() -> list:
    resp = (
        get_client()
        .table("profiles")
        .select("*")
        .order("full_name")
        .execute()
    )
    return resp.data or []


def update_user_profile(target_user_id: str, full_name: str, username: str) -> None:
    """Update name and username — tries RPC first, falls back to direct update."""
    try:
        get_client().rpc("update_user_profile", {
            "target_id":    target_user_id,
            "new_name":     full_name,
            "new_username": username,
        }).execute()
    except Exception:
        # RPC function not present — update the profiles table directly
        get_client().table("profiles").update({
            "full_name": full_name,
            "username":  username,
        }).eq("id", target_user_id).execute()


def delete_user_account(target_user_id: str) -> None:
    try:
        get_client().rpc("delete_user_account", {
            "target_user_id": target_user_id,
        }).execute()
    except Exception:
        get_client().table("profiles").delete().eq("id", target_user_id).execute()


def set_user_approved(target_user_id: str, approved: bool) -> None:
    """Let a new account in, or shut one out.

    Approval is the whole of the staff boundary: an unapproved account can
    sign in and see nothing. Directors and Admins decide.
    """
    get_client().table("profiles").update(
        {"approved": bool(approved)}).eq("id", target_user_id).execute()


def pending_staff_count() -> int:
    """Accounts waiting to be approved."""
    try:
        resp = (get_client().table("profiles")
                .select("id", count="exact").eq("approved", False)
                .limit(1).execute())
        return int(resp.count or 0)
    except Exception:
        return 0          # column not there yet — nothing is pending


def update_user_role(target_user_id: str, new_role: str) -> None:
    """Update role — tries RPC first (enforces hierarchy), falls back to direct update."""
    try:
        get_client().rpc("update_profile_role", {
            "target_id": target_user_id,
            "new_role":  new_role,
        }).execute()
    except Exception:
        # RPC function not present — update the profiles table directly
        get_client().table("profiles").update({
            "role": new_role,
        }).eq("id", target_user_id).execute()


def create_user_account(email: str, password: str, full_name: str,
                        role: str = "Employee") -> dict:
    """
    Create a new user without disturbing the current session.
    Uses a temporary separate client so the current user stays logged in.
    """
    from supabase import create_client as _create_client

    # Temporary client — does NOT affect the main _client session
    anon_key = get_client().supabase_key
    tmp = _create_client(SUPABASE_URL, anon_key)
    resp = tmp.auth.sign_up({"email": email, "password": password})

    if not (resp.user and resp.user.id):
        raise RuntimeError("Sign-up returned no user — email may be already registered.")

    new_id = str(resp.user.id)

    # If email confirmation is disabled, tmp has a session — use it to create profile.
    # Otherwise we create the profile using the current (director/admin) session.
    username = generate_username(full_name)

    try:
        # Try with tmp session first (works when email conf disabled)
        if resp.session:
            tmp.auth.set_session(resp.session.access_token, resp.session.refresh_token)
            tmp.table("profiles").upsert({
                "id": new_id, "email": email,
                "full_name": full_name, "username": username, "role": role,
            }).execute()
        else:
            # Fall back to main authenticated client
            get_client().table("profiles").upsert({
                "id": new_id, "email": email,
                "full_name": full_name, "username": username, "role": role,
            }).execute()
    except Exception:
        # Profile will be auto-created on first login
        pass

    return {"id": new_id, "email": email, "username": username,
            "full_name": full_name, "role": role}


def reload_profile() -> None:
    global _current_profile
    if _current_user:
        _current_profile = _load_profile(str(_current_user.id))


# ── Orders ────────────────────────────────────────────────────────────────────

LINE_ID = "line_id"


def with_line_ids(items: list) -> list:
    """Give every line an id of its own, keeping any it already has.

    Lines live in a JSON array on the order, so the only thing naming one is
    where it sits in that list. That is fine until someone edits the order —
    insert a line at the top and every line below it is now a different
    line, which would move a tick from the item that was made to the one
    that wasn't. An id is the line, wherever it ends up in the list.
    """
    import uuid as _uuid
    out = []
    for item in items or []:
        line = dict(item)
        if not line.get(LINE_ID):
            line[LINE_ID] = _uuid.uuid4().hex
        out.append(line)
    return out


def line_progress(items: list) -> tuple:
    """(made, total) for one order's lines."""
    lines = items or []
    return sum(1 for i in lines if i.get("made")), len(lines)


def progress_cell(n_items, n_made) -> str:
    """How far along an order is, in the width of a table column.

    Lives here rather than in the window because the customer portal will
    want to say the same thing about the same order, and two places deciding
    separately what "half made" looks like is how they end up disagreeing.

    Nothing started reads as the plain count it always did — so does a
    database without the migration, where n_made comes back as None.
    """
    total = n_items or 0
    if not total or n_made is None:
        return str(total)
    if n_made <= 0:
        return str(total)
    if n_made >= total:
        return f"✓ {total}"
    return f"{n_made}/{total}"


def set_line_made(order_id: str, line_id: str, made: bool = True,
                  by: str = "") -> None:
    """Mark one line of an order as made, or unmake it.

    Server-side, by id, for the same reason the header merge is: two people
    on two benches ticking two different lines of the same order is the
    normal case, not a rare one. Read the whole array, change one entry and
    write it all back, and whoever saves second erases the other's tick.

    Falls back to doing it here when migrate_line_progress.sql has not been
    run — still raising if it does not land, which is the half that matters.
    """
    import datetime as _dt
    stamp = _dt.datetime.utcnow().strftime("%d/%m/%Y %H:%M") if made else ""
    try:
        resp = get_client().rpc("set_order_line_made", {
            "p_order_id": str(order_id),
            "p_line_id":  str(line_id),
            "p_made":     bool(made),
            "p_by":       by,
            "p_at":       stamp,
        }).execute()
        if resp.data:
            return
        raise RuntimeError(
            "That line was not found on the order. It may have been "
            "changed or removed since this screen was opened.")
    except Exception as exc:
        if "set_order_line_made" not in str(exc):
            raise
        # PostgREST doesn't know the function: migration not applied yet.

    resp = (get_client().table("orders")
            .select("items").eq("id", order_id).single().execute())
    items = list((resp.data or {}).get("items") or [])
    hit = False
    for line in items:
        if str(line.get(LINE_ID)) == str(line_id):
            line["made"] = bool(made)
            line["made_by"] = by if made else ""
            line["made_at"] = stamp
            hit = True
    if not hit:
        raise RuntimeError(
            "That line was not found on the order. It may have been "
            "changed or removed since this screen was opened.")
    out = (get_client().table("orders")
           .update({"items": items}).eq("id", order_id).execute())
    if not (out.data or []):
        raise RuntimeError(
            "The database did not change that order. It may have been "
            "deleted, or your account may not be allowed to change it.")


def save_order(header: dict, items: list, order_type: str) -> "str | None":
    """Insert an order and return its new id (or None if it can't be read)."""
    user = _current_user
    if not user:
        raise RuntimeError("Not logged in.")
    items = with_line_ids(items)
    prof = current_profile()
    data = {
        "user_id":       str(user.id),
        "user_email":    user.email,
        "username":      prof.get("username", ""),
        "full_name":     prof.get("full_name", ""),
        "customer_name": header.get("Customer Name", ""),
        "order_number":  header.get("Order Number", ""),
        "date_ordered":  header.get("Date Ordered", ""),
        "date_due":      header.get("Date Due", ""),
        "attention":     header.get("Attention", ""),
        "job":           header.get("Job", ""),
        "location":      header.get("Location", ""),
        "notes":         header.get("Notes", ""),
        "order_type":    order_type,
        "header":        header,
        "items":         items,
    }
    # Add new columns only if migration has been run (graceful degradation)
    try:
        resp = get_client().table("orders").insert(
            {**data, "created_by_role": prof.get("role", "Employee")}
        ).execute()
    except Exception as exc:
        if "created_by_role" in str(exc) or "archived" in str(exc):
            # Migration not yet run — insert without new columns
            resp = get_client().table("orders").insert(data).execute()
        else:
            raise
    try:
        return (resp.data or [{}])[0].get("id")
    except Exception:
        return None


def item_signature(items: list) -> str:
    """Stable fingerprint of an order's line items, for duplicate detection.

    Only the fields that define *what is being made* participate — notes,
    part-number overrides etc. don't stop two orders being duplicates.
    """
    import hashlib
    import json as _json
    core = []
    for it in (items or []):
        if (it.get("item_kind") or "filter") == "bag":
            key = {k: it.get(k) for k in ("product_type", "quantity", "media",
                                          "width", "height", "depth")}
        else:
            key = {k: it.get(k) for k in ("Quantity", "Short", "Long",
                                          "Channel", "Filter Type", "Media Type")}
        core.append(_json.dumps(key, sort_keys=True, default=str))
    return hashlib.sha1("|".join(sorted(core)).encode("utf-8")).hexdigest()


def find_potential_duplicates(customer: str, order_number: str,
                              items: list, days: int = 14) -> list:
    """Return existing orders that look like duplicates of the one described.

    Two signals, checked against the shared database:
      • an order with the same order number already exists; or
      • the same customer has an order with identical line items created in
        the last `days` days (two people keying the same job at once).
    Each returned row carries a human-readable "duplicate_reason".
    """
    import datetime as _dt
    c = get_client()
    matches: dict = {}

    on = (order_number or "").strip()
    if on:
        try:
            resp = (c.table("orders")
                    .select("id, customer_name, order_number, full_name, username, created_at")
                    .ilike("order_number", on.replace("%", "\\%"))
                    .execute())
            for r in resp.data or []:
                r["duplicate_reason"] = "same order number"
                matches[r["id"]] = r
        except Exception:
            pass

    cust = (customer or "").strip()
    if cust and items:
        sig = item_signature(items)
        since = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)).isoformat()
        try:
            resp = (c.table("orders")
                    .select("id, customer_name, order_number, full_name, username, created_at, items")
                    .ilike("customer_name", cust.replace("%", "\\%"))
                    .gte("created_at", since)
                    .execute())
            for r in resp.data or []:
                if item_signature(r.get("items") or []) != sig:
                    continue
                r.pop("items", None)
                if r["id"] in matches:
                    matches[r["id"]]["duplicate_reason"] = \
                        "same order number and identical items"
                else:
                    r["duplicate_reason"] = "identical items for this customer"
                    matches[r["id"]] = r
        except Exception:
            pass

    return list(matches.values())


def mark_order_printed(order_id: str) -> None:
    """Flag an order as printed (stored in the header JSON — no migration)."""
    import datetime as _dt
    merge_order_header(order_id, {
        "printed":    True,
        "printed_at": _dt.datetime.now().strftime("%d/%m/%Y %H:%M"),
    })


def tables_exist() -> tuple[bool, bool]:
    """Returns (profiles_ok, orders_ok)."""
    c = get_client()
    try:
        c.table("profiles").select("id").limit(1).execute()
        p = True
    except Exception:
        p = False
    try:
        c.table("orders").select("id").limit(1).execute()
        o = True
    except Exception:
        o = False
    return p, o


def _page_through(build_query, step: int = 1000, limit: int = 0) -> list:
    """Read every row a query matches, a page at a time.

    PostgREST returns at most 1000 rows and says nothing about the rest, so a
    single request silently truncates — which is how the price list came back
    as its first thousand entries, and how orders past the thousandth stopped
    appearing in Previous Orders.
    """
    out: list = []
    while True:
        resp = build_query().range(len(out), len(out) + step - 1).execute()
        batch = resp.data or []
        out.extend(batch)
        if len(batch) < step or (limit and len(out) >= limit):
            break
    return out[:limit] if limit else out


def get_order_list(limit: int = 0) -> list:
    """Orders for a list screen: everything except the line items.

    The lines are the bulk of an order and no list shows them — only a count —
    so they stay in the database until something opens one. Falls back to the
    old whole-row query when migrate_performance.sql hasn't been run.
    """
    try:
        rows = _page_through(
            lambda: (get_client().table("orders_list").select("*")
                     .eq("archived", False).order("created_at", desc=True)),
            limit=limit)
        for r in rows:
            r["items"] = None          # not fetched; ask for them if needed
        return rows
    except Exception:
        return get_all_orders(limit=limit)


def get_order(order_id: str) -> "dict | None":
    """One order in full, lines included.

    Used where a screen needs to show what an action just did — re-reading
    the whole list to find one order is a lot of wire for one row.
    """
    try:
        resp = (get_client().table("orders").select("*")
                .eq("id", order_id).single().execute())
        return resp.data or None
    except Exception:
        return None


def get_order_items(order_id: str) -> list:
    """One order's line items, fetched when something actually needs them.

    Orders written before lines had ids get them here, so an order taken
    last month can still be ticked off line by line. The ids are written
    back the first time, once: an id made up fresh on every read would be a
    different id every time, and a tick would go looking for one the
    database has never seen.
    """
    try:
        resp = (get_client().table("orders")
                .select("items").eq("id", order_id).single().execute())
        stored = (resp.data or {}).get("items") or []
    except Exception:
        return []

    items = with_line_ids(stored)
    if any(not line.get(LINE_ID) for line in stored):
        try:
            get_client().table("orders").update(
                {"items": items}).eq("id", order_id).execute()
        except Exception:
            # Read-only account, or no connection. The lines still come back
            # with ids so the screen draws; a tick will say it could not find
            # the line, which is true and tells them to reopen it.
            pass
    return items


def media_usage_since(since) -> dict:
    """How much of each media grade has been used since a date.

    Counted in the database. The Dashboard used to do it by walking every
    line of every order it had already downloaded.
    """
    try:
        resp = get_client().rpc(
            "media_usage_since", {"p_since": str(since)}).execute()
        return {r["media_type"]: int(r["used"] or 0)
                for r in (resp.data or []) if r.get("media_type")}
    except Exception:
        return {}


def get_all_orders(limit: int = 0) -> list:
    try:
        return _page_through(
            lambda: (get_client().table("orders").select("*")
                     .eq("archived", False).order("created_at", desc=True)),
            limit=limit)
    except Exception as exc:
        if "archived" in str(exc):
            # Migration not yet run — fetch without archived filter
            return _page_through(
                lambda: (get_client().table("orders").select("*")
                         .order("created_at", desc=True)),
                limit=limit)
        raise


def delete_order(order_id: str) -> None:
    get_client().rpc("delete_order_by_role", {"order_id": order_id}).execute()


def archive_order(order_id: str) -> None:
    get_client().rpc("archive_order_by_role", {"order_id": order_id}).execute()


def can_delete_order(order_row: dict) -> bool:
    my_lvl = role_level()
    if my_lvl >= 4:
        return True
    if my_lvl >= 3:
        order_lvl = ROLE_LEVEL.get(order_row.get("created_by_role", "Employee"), 1)
        return order_lvl <= 3
    return str(order_row.get("user_id", "")) == str(_current_user.id if _current_user else "")


def can_archive_order() -> bool:
    return role_level() >= 4


# ── Media Types ───────────────────────────────────────────────────────────────

def get_media_codes() -> dict:
    """{media name: part-number code} for every custom media type.

    Carbon -> CARB, so a flat panel becomes FPFCARB25-020. Missing codes fall
    back to a value derived from the name (see part_numbers.default_media_code),
    and an empty dict is returned if the column hasn't been migrated yet.
    """
    try:
        resp = get_client().table("media_types").select("name, code").execute()
        return {r["name"]: (r.get("code") or "") for r in (resp.data or [])}
    except Exception:
        return {}


def set_media_code(name: str, code: str) -> None:
    get_client().table("media_types").update(
        {"code": (code or "").strip().upper()}).eq("name", name).execute()


def get_custom_media_types() -> list[str]:
    """Return custom media type names in sort order from the DB."""
    try:
        resp = (
            get_client()
            .table("media_types")
            .select("name")
            .order("sort_order")
            .order("name")
            .execute()
        )
        return [r["name"] for r in (resp.data or [])]
    except Exception:
        return []


def add_media_type(name: str) -> None:
    existing = get_custom_media_types()
    sort_order = len(existing)
    get_client().table("media_types").insert(
        {"name": name, "sort_order": sort_order}
    ).execute()


def remove_media_type(name: str) -> None:
    get_client().table("media_types").delete().eq("name", name).execute()


def rename_media_type(old_name: str, new_name: str) -> None:
    get_client().table("media_types").update(
        {"name": new_name}
    ).eq("name", old_name).execute()


def reorder_media_types(names: list[str]) -> None:
    """Save new sort order for all custom media types."""
    for i, name in enumerate(names):
        get_client().table("media_types").update(
            {"sort_order": i}
        ).eq("name", name).execute()


def can_manage_media_types() -> bool:
    return role_level() >= 3


# ── Shared catalogue (dedicated filter presets & filter types) ────────────────
# One row per list in catalog_lists (key text, value jsonb). The app falls
# back to its built-in defaults when the table is missing or unreachable.

def get_catalog_map() -> dict:
    """Return {key: value} for every stored catalogue list. Raises on failure
    so callers can fall back to local caches / built-in defaults."""
    resp = get_client().table("catalog_lists").select("key, value").execute()
    return {r["key"]: r["value"] for r in (resp.data or [])}


def set_catalog_value(key: str, value) -> None:
    """Create or replace one catalogue list (value is JSON-serialisable)."""
    import datetime as _dt
    get_client().table("catalog_lists").upsert({
        "key":        key,
        "value":      value,
        "updated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }).execute()


def can_manage_catalog() -> bool:
    return role_level() >= 3


# ── Audit Log ─────────────────────────────────────────────────────────────────

def log_action(action: str, details: str = "") -> None:
    """Write one row to audit_log. Silently swallowed on any error."""
    if not (is_ready() and _current_user):
        return
    try:
        get_client().table("audit_log").insert({
            "user_id":  str(_current_user.id),
            "username": current_username(),
            "action":   action,
            "details":  details,
        }).execute()
    except Exception:
        pass


def get_audit_log(limit: int = 500) -> list:
    """Return most recent audit_log rows, newest first. Managers+ only."""
    try:
        resp = (
            get_client()
            .table("audit_log")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception:
        return []


# ── Stock Alerts ──────────────────────────────────────────────────────────────

def get_stock_alerts() -> list:
    """Return all rows from stock_alerts."""
    try:
        resp = get_client().table("stock_alerts").select("*").order("media_type").execute()
        return resp.data or []
    except Exception:
        return []


def upsert_stock_alert(media_type: str, threshold: int) -> None:
    get_client().table("stock_alerts").upsert(
        {"media_type": media_type, "threshold": threshold},
        on_conflict="media_type",
    ).execute()


def delete_stock_alert(media_type: str) -> None:
    get_client().table("stock_alerts").delete().eq("media_type", media_type).execute()


def can_manage_stock_alerts() -> bool:
    return role_level() >= 3


# ── Changing one field of an order's header ───────────────────────────────────

def merge_order_header(order_id: str, patch: dict) -> None:
    """Change some keys of an order's header JSON, leaving the rest alone.

    Two things this fixes, both of which showed up when marking a batch of
    orders complete.

    It raises. Every one of these used to end in `except Exception: pass`, so
    a write the database refused — a row-level security policy, an expired
    session, a dropped connection — looked exactly like a write that worked.
    The app counted it as done, said so, then reloaded the list and showed
    the old status. Nothing anywhere said why.

    And it merges server-side. Reading the whole header, changing one key in
    Python and writing the whole thing back takes two round trips and loses
    anything anyone else changed in between: mark twenty orders complete
    while someone adds a note to one of them, and the note goes. `header ||
    patch` in the database is one statement and only touches the keys given.

    Falls back to the read-modify-write if migrate_bulk_status.sql has not
    been run — still raising, which is the half that matters.
    """
    try:
        resp = get_client().rpc("merge_order_header", {
            "p_order_id": str(order_id),
            "p_patch":    patch,
        }).execute()
        if resp.data:                      # the RPC returns the updated id
            return
        raise RuntimeError(
            "The database did not change that order. It may have been "
            "deleted, or your account may not be allowed to change it.")
    except Exception as exc:
        if "merge_order_header" not in str(exc):
            raise
        # PostgREST doesn't know the function: migration not applied yet.

    resp = (get_client().table("orders")
            .select("header").eq("id", order_id).single().execute())
    header = dict((resp.data or {}).get("header") or {})
    header.update(patch)
    out = (get_client().table("orders")
           .update({"header": header}).eq("id", order_id).execute())
    if not (out.data or []):
        raise RuntimeError(
            "The database did not change that order. It may have been "
            "deleted, or your account may not be allowed to change it.")


# ── Priority ──────────────────────────────────────────────────────────────────

def set_order_priority(order_id: str, priority: bool) -> None:
    """Set or clear the priority flag stored in the order's header JSON."""
    merge_order_header(order_id, {"priority": priority})


# ── Order Status ──────────────────────────────────────────────────────────────

ORDER_STATUS_VALUES = [
    "Pending", "In Production", "Complete",
    "Dispatched",
]


def set_order_status(order_id: str, status: str) -> None:
    """Set the order status stored in the order's header JSON."""
    merge_order_header(order_id, {"status": status})


def set_order_status_bulk(order_ids, status: str) -> list:
    """Set the status on several orders. Returns [(order_id, reason), …] for
    the ones that did not change.

    Bulk work that stops at the first failure is worse than useless — you are
    left not knowing which half of the batch went through. This does every
    one it can and hands back what didn't, so the app can say so.
    """
    problems = []
    for oid in order_ids:
        try:
            set_order_status(str(oid), status)
        except Exception as exc:
            problems.append((str(oid), str(exc)))
    return problems


# Carriers TAF books freight with, and where a consignment can be followed.
# {number} is replaced with the consignment number.
FREIGHT_CARRIERS = {
    "":              "",
    "TNT":           "https://www.tnt.com/express/en_au/site/tracking.html?searchType=con&cons={number}",
    "Startrack":     "https://startrack.com.au/track/search?id={number}",
    "Australia Post": "https://auspost.com.au/mypost/track/#/details/{number}",
    "Followmont":    "https://www.followmont.com.au/track-and-trace/?consignment={number}",
    "Border Express": "https://www.borderexpress.com.au/track-and-trace/?connote={number}",
    "Northline":     "https://www.northline.com.au/track-trace/?con={number}",
    "Toll":          "https://www.mytoll.com/?externalSearchQuery={number}",
    "Other":         "",
}


def tracking_url(carrier: str, number: str, custom: str = "") -> str:
    """Where a customer can follow a consignment, or "" if nowhere.

    A link typed in by hand wins — carriers change their tracking pages, and
    a stale template should never override what someone has actually checked.
    """
    custom = (custom or "").strip()
    if custom:
        return custom
    number = (number or "").strip()
    template = FREIGHT_CARRIERS.get((carrier or "").strip(), "")
    if not template or not number:
        return ""
    from urllib.parse import quote
    return template.replace("{number}", quote(number, safe=""))


def set_order_freight(order_id: str, carrier: str = "", number: str = "",
                      url: str = "", note: str = "", expected: str = "") -> None:
    """Record how an order is travelling, and anything holding it up.

    All of it is shown to the customer on their portal, which is the point:
    "where is it" and "why is it late" are the two questions a delivery
    generates, and both are better answered before they are asked.
    """
    import datetime as _dt
    resp = (get_client().table("orders")
            .select("header").eq("id", order_id).single().execute())
    header = dict((resp.data or {}).get("header") or {})
    freight = {
        "carrier":   (carrier or "").strip(),
        "number":    (number or "").strip(),
        "url":       tracking_url(carrier, number, url),
        "note":      (note or "").strip(),
        "expected":  (expected or "").strip(),
        "updated_at": _dt.datetime.utcnow().isoformat(),
        "updated_by": current_full_name() or current_username(),
    }
    if not any((freight["carrier"], freight["number"], freight["note"],
                freight["expected"])):
        header.pop("freight", None)          # cleared
    else:
        header["freight"] = freight
    get_client().table("orders").update(
        {"header": header}).eq("id", order_id).execute()


def get_order_freight(order_id: str) -> dict:
    try:
        resp = (get_client().table("orders")
                .select("header").eq("id", order_id).single().execute())
        return dict(((resp.data or {}).get("header") or {}).get("freight") or {})
    except Exception:
        return {}


def append_order_note(order_id: str, note_text: str, author: str = "") -> None:
    """Append a timestamped note to the order's header JSON.

    Raises if it did not save. A note that is typed, accepted and silently
    dropped is worse than one that was never offered.
    """
    import datetime as _dt
    resp = (get_client().table("orders")
            .select("header").eq("id", order_id).single().execute())
    header = dict((resp.data or {}).get("header") or {})
    existing = header.get("order_notes") or []
    if isinstance(existing, str):
        existing = [{"ts": "", "author": "", "text": existing}] if existing else []
    ts = _dt.datetime.utcnow().strftime("%d/%m/%Y %H:%M")
    existing.append({"ts": ts, "author": author, "text": note_text})
    merge_order_header(order_id, {"order_notes": existing})


# ── Jobs that come round again ────────────────────────────────────────────────

REPEAT_INTERVALS = [("Every 3 months", 3), ("Every 6 months", 6),
                    ("Every 12 months", 12)]


def add_months(when, months: int):
    """The same day of the month, `months` later.

    Calendar arithmetic, not 90 days: a job done on the 15th is due on the
    15th, and "every 3 months" from 30 November is the end of February, not
    the 2nd of March. Days are clamped to the length of the target month for
    the same reason — there is no 31st of the month after a 31st.
    """
    import calendar as _cal
    total = when.month - 1 + int(months)
    year = when.year + total // 12
    month = total % 12 + 1
    return when.replace(year=year, month=month,
                        day=min(when.day, _cal.monthrange(year, month)[1]))


def list_recurring_jobs(include_paused: bool = False) -> list:
    """Every standing job, soonest due first."""
    try:
        q = get_client().table("recurring_jobs").select("*")
        if not include_paused:
            q = q.eq("active", True)
        return (q.order("next_due").execute().data) or []
    except Exception:
        return []          # migrate_recurring_jobs.sql not run yet


def recurring_jobs_due(on_date=None) -> list:
    """The ones due on or before a date — today, unless told otherwise.

    Due *or overdue*: a job nobody raised last month has not stopped being
    due, and dropping it off the list the day after is how it gets missed
    for a year.
    """
    import datetime as _dt
    when = on_date or _dt.date.today()
    out = []
    for job in list_recurring_jobs():
        due = as_date(job.get("next_due"))
        if due and due <= when:
            out.append(job)
    return out


def as_date(value):
    """A date out of the database, whatever shape it arrives in."""
    import datetime as _dt
    if isinstance(value, _dt.date):
        return value
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return _dt.datetime.strptime(str(value)[:10], fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def save_recurring_job(job: dict) -> "str | None":
    """Create or update a standing job. Returns its id."""
    import datetime as _dt
    data = {
        "customer_name":     job.get("customer_name", ""),
        "job":               job.get("job", ""),
        "location":          job.get("location", ""),
        "every_months":      int(job.get("every_months") or 3),
        "next_due":          str(job.get("next_due") or _dt.date.today()),
        "template_order_id": job.get("template_order_id") or None,
        "active":            bool(job.get("active", True)),
        "note":              job.get("note", ""),
    }
    if job.get("id"):
        resp = (get_client().table("recurring_jobs")
                .update(data).eq("id", job["id"]).execute())
        if not (resp.data or []):
            raise RuntimeError(
                "That repeating job was not changed. It may have been "
                "removed, or your account may not be allowed to change it.")
        return job["id"]
    data["created_by"] = current_full_name() or current_username()
    resp = get_client().table("recurring_jobs").insert(data).execute()
    rows = resp.data or []
    if not rows:
        raise RuntimeError("The repeating job was not saved.")
    return rows[0].get("id")


def delete_recurring_job(job_id: str) -> None:
    resp = (get_client().table("recurring_jobs")
            .delete().eq("id", job_id).execute())
    if not (resp.data or []):
        raise RuntimeError(
            "That repeating job was not removed. It may already be gone, or "
            "your account may not be allowed to remove it.")


def mark_recurring_raised(job_id: str, every_months: int, when=None) -> str:
    """Move a job on to its next turn, and say when that is.

    Counted from the date it was due, not from today: a quarterly job raised
    a fortnight late is still due at the end of that quarter, and measuring
    from today would walk the whole schedule later every time anyone was
    busy. If it has slipped so far that the next date is already behind us,
    it keeps stepping until it isn't.
    """
    import datetime as _dt
    today = when or _dt.date.today()
    months = max(1, int(every_months or 3))

    resp = (get_client().table("recurring_jobs")
            .select("next_due").eq("id", job_id).single().execute())
    due = as_date((resp.data or {}).get("next_due")) or today

    nxt = add_months(due, months)
    while nxt <= today:
        nxt = add_months(nxt, months)

    out = (get_client().table("recurring_jobs")
           .update({"next_due": str(nxt), "last_raised": str(today)})
           .eq("id", job_id).execute())
    if not (out.data or []):
        raise RuntimeError(
            "The order was raised, but the repeating job was not moved on. "
            "Check its next date, or it will show as due again.")
    return str(nxt)


# ── Customer Database ─────────────────────────────────────────────────────────

PAYMENT_TERMS = ["Net 7", "Net 14", "Net 30", "Net 60", "COD", "EOM", "Prepaid"]
AU_STATES     = ["ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"]


def get_customers(search: str = "", active_only: bool = True) -> list:
    try:
        q = get_client().table("customers").select("*").order("name")
        if active_only:
            q = q.eq("is_active", True)
        resp  = q.execute()
        items = resp.data or []
        if search:
            s     = search.lower()
            items = [c for c in items
                     if s in (c.get("name") or "").lower()
                     or s in (c.get("legal_name") or "").lower()
                     or s in (c.get("abn") or "").lower()
                     or s in (c.get("email") or "").lower()
                     or s in (c.get("contact_person") or "").lower()
                     or s in (c.get("delivery_city") or "").lower()]
        return items
    except Exception:
        return []


def get_customer(customer_id: str) -> "dict | None":
    try:
        resp = (get_client().table("customers")
                .select("*").eq("id", customer_id).single().execute())
        return resp.data
    except Exception:
        return None


def create_customer(data: dict) -> dict:
    import datetime as _dt
    data = dict(data)
    data.setdefault("created_by_name", current_username())
    data["updated_at"] = _dt.datetime.utcnow().isoformat()
    resp = get_client().table("customers").insert(data).execute()
    return resp.data[0] if resp.data else {}


def update_customer(customer_id: str, data: dict) -> None:
    import datetime as _dt
    data = dict(data)
    data["updated_at"] = _dt.datetime.utcnow().isoformat()
    get_client().table("customers").update(data).eq("id", customer_id).execute()


def delete_customer(customer_id: str) -> None:
    get_client().table("customers").delete().eq("id", customer_id).execute()


# ── Matching a purchase order to a customer branch ───────────────────────────
# A purchase order says "Complete Air Supply Pty Ltd" at "19-27 Fred Chaplin
# Circuit, Bells Creek". The order should say "CAS - Bells Creek" in
# "Sunshine Coast". Each branch is its own profile; these helpers find the
# right one and remember the wording so the next order matches without asking.

def _norm(text: str) -> str:
    import re as _re
    return _re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def is_company_name(value: str, customers: list | None = None) -> bool:
    """True when `value` is a legal name shared by every branch of a company.

    "Complete Air Supply Pty Ltd" identifies a company; "CAS - Bells Creek"
    identifies a branch. Only the second is safe to record against a profile
    or to match an order on.
    """
    v = _norm(value)
    if not v:
        return False
    try:
        people = customers if customers is not None else get_customers(active_only=False)
    except Exception:
        return False
    return any(_norm(c.get("legal_name") or "") == v for c in people)


def match_customer(po_name: str, po_address: str = "",
                   customers: list | None = None) -> "dict | None":
    """Find the branch a purchase order belongs to, or None to ask.

    The rule throughout: a match has to identify a BRANCH, not just a company.
    Branches of one company share a legal name, so anything that only proves
    "this is Complete Air Supply" proves nothing about which depot the order
    is for — and picking the wrong one sends the work to the wrong place under
    the wrong short name. Company-level evidence therefore only counts when an
    address backs it up, and if two branches both look plausible, neither is
    chosen.
    """
    people = customers if customers is not None else get_customers(active_only=True)
    name_n = _norm(po_name)
    addr_n = _norm(po_address)
    if not name_n and not addr_n:
        return None

    # Every legal name on file. A wording that is one of these names a
    # company, not a branch — whichever profile it happens to sit on. Taking
    # the whole list, rather than just the profile being tested, catches the
    # branch whose own legal name was left blank or typed differently.
    company_names = {_norm(c.get("legal_name") or "") for c in people}
    company_names.discard("")

    def _company_level(c: dict, value: str) -> bool:
        """True when `value` is just the company name every branch shares."""
        return value in company_names

    def _address_agrees(c: dict) -> bool:
        if not addr_n:
            return False
        for part in (c.get("delivery_address1"), c.get("delivery_city"),
                     c.get("delivery_postcode")):
            p = _norm(part or "")
            if p and len(p) > 3 and p in addr_n:
                return True
        return False

    def _identifies(c: dict) -> bool:
        # 1. Wording already recorded against this branch. An alias that is
        #    only the company name is ignored: earlier versions saved those,
        #    and acting on one is what matched a Bells Creek order to Tweed.
        for alias in (c.get("po_aliases") or []):
            a = _norm(str(alias))
            if not a or _company_level(c, a):
                continue
            if a == name_n:
                return True
            # Substring only for wordings long enough to mean something: a
            # three-letter alias would otherwise land inside half the list.
            if len(a) > 3 and ((addr_n and a in addr_n) or (name_n and a in name_n)):
                return True

        # 2. Its own short name or trading name — unless that is just the
        #    company name again.
        if name_n:
            for field in ("short_name", "name"):
                v = _norm(c.get(field) or "")
                if v and v == name_n and not _company_level(c, v):
                    return True

        # 3. Same company by legal name, which only counts with an address.
        if addr_n:
            legal = _norm(c.get("legal_name") or "")
            if legal and (legal == name_n or legal in name_n or name_n in legal) \
                    and _address_agrees(c):
                return True
        return False

    matches = [c for c in people if _identifies(c)]
    # Exactly one branch, or none: two candidates means ask rather than guess.
    return matches[0] if len(matches) == 1 else None


def _words(text: str) -> set:
    """The words in a piece of text, minus the ones every company prints."""
    noise = {"pty", "ltd", "limited", "the", "and", "co", "company", "inc",
             "australia", "au", "unit", "street", "st", "road", "rd", "drive",
             "dr", "avenue", "ave", "court", "ct", "qld", "nsw", "vic", "sa",
             "wa", "nt", "act", "po", "box"}
    return {w for w in _norm(text).split() if len(w) > 2 and w not in noise}


def suggest_customers(po_name: str, po_address: str = "",
                      customers: list | None = None,
                      limit: int = 8) -> list:
    """Branches this purchase order might belong to, likeliest first.

    match_customer answers "can I be certain"; this answers "who should a
    person be shown". They are different questions and must stay different
    functions - the moment a suggestion is allowed to pick, the Bells Creek
    order goes to Tweed again. Nothing here decides anything. It puts the
    likely ones at the top of a list somebody still has to choose from.

    Returns [{"customer", "score", "why"}], never a bare list of profiles,
    because a name offered with no reason attached is a name somebody clicks
    without reading.
    """
    people = customers if customers is not None else get_customers(active_only=True)
    name_w = _words(po_name)
    addr_w = _words(po_address)
    if not name_w and not addr_w:
        return []

    out = []
    for c in people:
        score = 0
        why = []

        for alias in (c.get("po_aliases") or []):
            shared = _words(str(alias)) & (name_w | addr_w)
            if shared:
                score += 4 * len(shared)
                why.append(f'seen before as "{alias}"')
                break

        for field, points, label in (("short_name", 5, "short name"),
                                     ("name", 4, "name"),
                                     ("legal_name", 2, "company name")):
            shared = _words(c.get(field) or "") & name_w
            if shared:
                score += points * len(shared)
                why.append(f"{label} matches {' '.join(sorted(shared))}")

        # An address is the only thing that tells two branches of one company
        # apart - the name is identical on both and cannot order them - so it
        # is weighted above every name field.
        for field in ("delivery_city", "delivery_postcode", "delivery_address1"):
            shared = _words(c.get(field) or "") & addr_w
            if shared:
                score += 6 * len(shared)
                why.append(f"delivers to {' '.join(sorted(shared))}")
                break

        if score:
            out.append({"customer": c, "score": score,
                        "why": "; ".join(why[:3])})

    out.sort(key=lambda r: (-r["score"],
                            (r["customer"].get("short_name") or "").lower()))
    return out[:limit]


def link_po_to_customer(customer_id: str, po_name: str,
                        po_address: str = "") -> list:
    """Remember that a purchase order reading like this is that branch.

    The whole point of saying "this is an existing customer" once is never
    being asked again, and that only happens if the wording is written down.

    What is deliberately NOT written down is the company's legal name. Every
    branch of the company prints it, so recording it against one profile is
    exactly what sent a Bells Creek order to the Tweed branch - and doing it
    from here, where somebody is correcting that very mistake, would be worse
    than not learning at all.

    Returns the wordings actually remembered, so a screen can say so.
    """
    if not customer_id:
        return []
    kept = []
    for wording in (po_name, po_address):
        wording = (wording or "").strip()
        if not wording:
            continue
        try:
            if is_company_name(wording):
                continue
            add_customer_alias(customer_id, wording)
            kept.append(wording)
        except Exception:
            pass
    return kept


def add_customer_alias(customer_id: str, alias: str) -> None:
    """Remember a name or address as belonging to this branch.

    Refuses anything that is only the company's legal name: every branch
    shares it, so recording it would make the next order from any other
    branch match this one.
    """
    alias = (alias or "").strip()
    if not alias:
        return
    try:
        resp = (get_client().table("customers")
                .select("po_aliases").eq("id", customer_id)
                .single().execute())
        aliases = list((resp.data or {}).get("po_aliases") or [])
    except Exception:
        aliases = []
    if any(_norm(a) == _norm(alias) for a in aliases):
        return
    if is_company_name(alias):
        return          # company-wide wording, not this branch
    aliases.append(alias)
    get_client().table("customers").update(
        {"po_aliases": aliases}).eq("id", customer_id).execute()


# ── The customer portal (see migrate_customer_portal.sql) ───────────────────
# A customer follows a link with a random token and sees their own orders,
# quotes and account. The token belongs to the customer rather than to a
# person, so it can be turned off or replaced — which invalidates every link
# ever sent for that account.

def customer_portal_token(customer_id: str, rotate: bool = False) -> str:
    """The customer's portal token, creating or replacing it as asked.

    `rotate` issues a new one, which is how a link that has gone somewhere it
    shouldn't is dealt with: every old link stops working at once.
    """
    import secrets
    row = get_customer(customer_id) or {}
    token = (row.get("portal_token") or "").strip()
    if token and not rotate:
        if not row.get("portal_enabled"):
            get_client().table("customers").update(
                {"portal_enabled": True}).eq("id", customer_id).execute()
        return token
    token = secrets.token_hex(32)
    get_client().table("customers").update({
        "portal_token": token, "portal_enabled": True,
    }).eq("id", customer_id).execute()
    return token


def set_customer_portal(customer_id: str, enabled: bool) -> None:
    """Turn a customer's portal on or off without changing their link."""
    get_client().table("customers").update(
        {"portal_enabled": bool(enabled)}).eq("id", customer_id).execute()


def can_manage_customers() -> bool:
    return role_level() >= 3


# ── Stock Management ──────────────────────────────────────────────────────────

STOCK_PRODUCT_TYPES = [
    "Stepped Filter",
    "V-form Filter",
    "Panel Filter",
    "Bag Filter",
    "Flyscreen",
    "Media Roll",
    "Wire",
    "Channel",
    "Spline",
    "Flyscreen Corner",
    "Frame / Housing",
    "Hardware / Fasteners",
    "Consumables",
    "Other",
]

# "m2" is what media has to be kept in for an order to deduct it by area —
# see stock_usage.py. A roll kept in metres can't be reduced by an area
# without knowing the roll's width.
STOCK_UNITS = ["each", "m2", "metre", "roll", "kg", "box", "pack", "sheet",
               "pair", "set"]


def get_stock_items(search: str = "", product_type: str = "") -> list:
    """Return all stock items, optionally filtered by type and search text."""
    try:
        q = get_client().table("stock_items").select("*").order("name")
        if product_type:
            q = q.eq("product_type", product_type)
        resp  = q.execute()
        items = resp.data or []
        if search:
            s     = search.lower()
            items = [i for i in items
                     if s in (i.get("name") or "").lower()
                     or s in (i.get("sku") or "").lower()
                     or s in (i.get("description") or "").lower()
                     or s in (i.get("location") or "").lower()]
        return items
    except Exception:
        return []


def get_stock_item(item_id: str) -> "dict | None":
    try:
        resp = (get_client().table("stock_items")
                .select("*").eq("id", item_id).single().execute())
        return resp.data
    except Exception:
        return None


def create_stock_item(data: dict) -> dict:
    import datetime as _dt
    data = dict(data)
    data.setdefault("created_by_name", current_username())
    data["updated_at"] = _dt.datetime.utcnow().isoformat()
    resp = get_client().table("stock_items").insert(data).execute()
    return resp.data[0] if resp.data else {}


def update_stock_item(item_id: str, data: dict) -> None:
    import datetime as _dt
    data = dict(data)
    data["updated_at"] = _dt.datetime.utcnow().isoformat()
    get_client().table("stock_items").update(data).eq("id", item_id).execute()


def delete_stock_item(item_id: str) -> None:
    get_client().table("stock_items").delete().eq("id", item_id).execute()


def adjust_stock(item_id: str, transaction_type: str,
                 quantity: float, notes: str = "",
                 client_ref: str = "", device: str = "") -> float:
    """
    Adjust stock_on_hand and record a transaction row.
    transaction_type:
        'receive'  → add quantity (positive delta)
        'use'      → subtract quantity (stored as negative delta)
        'count'    → set absolute value; delta = new - old
        'writeoff' → subtract quantity (negative delta), marks loss
    Returns new stock_on_hand.

    The arithmetic happens in the database, on a locked row — two people
    counting the same rack at once used to both read the old figure and both
    write their own answer, losing one of the counts with nothing in the log
    to show it.

    `client_ref` is the caller's own name for this one movement. Send the same
    one twice and it is applied once: a handheld that loses signal after the
    write lands but before the reply arrives cannot tell "it failed" from "it
    worked and I didn't hear", so it retries — and without this, the stock
    moves twice. One is generated per call when the caller doesn't supply one,
    which makes an HTTP-level retry safe without changing any caller.
    """
    import datetime as _dt
    import uuid as _uuid

    ref = (client_ref or "").strip() or f"app-{_uuid.uuid4()}"
    try:
        resp = get_client().rpc("adjust_stock_atomic", {
            "p_item_id":    item_id,
            "p_type":       transaction_type,
            "p_quantity":   quantity,
            "p_notes":      notes,
            "p_client_ref": ref,
            "p_username":   current_username(),
            "p_device":     device or "desktop",
        }).execute()
        rows = resp.data or []
        row  = rows[0] if isinstance(rows, list) and rows else rows
        if isinstance(row, dict) and row.get("quantity_after") is not None:
            return float(row["quantity_after"])
    except Exception:
        pass          # migrate_scanning.sql not run yet — fall through

    # Older database: the way it worked before, kept so the app still runs
    # against a project that hasn't had the migration applied.
    resp    = (get_client().table("stock_items")
               .select("stock_on_hand").eq("id", item_id).single().execute())
    current = float((resp.data or {}).get("stock_on_hand", 0))

    if transaction_type == "count":
        delta   = quantity - current
        new_qty = quantity
    elif transaction_type in ("use", "writeoff"):
        delta   = -abs(quantity)
        new_qty = max(0.0, current + delta)
    else:  # receive
        delta   = abs(quantity)
        new_qty = current + delta

    now = _dt.datetime.utcnow().isoformat()
    get_client().table("stock_items").update(
        {"stock_on_hand": new_qty, "updated_at": now}
    ).eq("id", item_id).execute()

    get_client().table("stock_transactions").insert({
        "stock_item_id":    item_id,
        "transaction_type": transaction_type,
        "quantity_change":  round(delta, 3),
        "quantity_after":   round(new_qty, 3),
        "notes":            notes,
        "username":         current_username(),
    }).execute()

    return new_qty


def resolve_scan(code: str) -> list:
    """What a scanned barcode is: a stock item, an order, or a part number.

    One place answers this so a handheld, the phone page and the desktop can
    never drift apart on what a code means. Returns a list because a code
    could in principle match more than one kind of thing; most specific first
    (a stock code is something you can count, which is what a gun is for).

    Falls back to a plain SKU lookup when migrate_scanning.sql hasn't been run.
    """
    code = (code or "").strip()
    if not code:
        return []
    try:
        resp = get_client().rpc("resolve_scan", {"p_code": code}).execute()
        rows = resp.data or []
        if rows:
            return rows
    except Exception:
        pass

    # Older database: the one lookup worth having without the migration.
    try:
        resp = (get_client().table("stock_items").select("*")
                .ilike("sku", code).limit(2).execute())
        return [{"kind": "stock", "ref": r.get("id"), "label": r.get("name", ""),
                 "detail": r.get("location") or "No location", "extra": r}
                for r in (resp.data or [])]
    except Exception:
        return []


def get_stock_transactions(item_id: str, limit: int = 150) -> list:
    try:
        resp = (get_client().table("stock_transactions")
                .select("*")
                .eq("stock_item_id", item_id)
                .order("created_at", desc=True)
                .limit(limit)
                .execute())
        return resp.data or []
    except Exception:
        return []


def get_low_stock_items() -> list:
    """Return items where stock_on_hand < minimum_on_hand (and minimum > 0)."""
    try:
        resp = get_client().table("stock_items").select("*").execute()
        return [
            i for i in (resp.data or [])
            if float(i.get("minimum_on_hand", 0)) > 0
            and float(i.get("stock_on_hand", 0)) < float(i.get("minimum_on_hand", 0))
        ]
    except Exception:
        return []


def upload_stock_image(item_id: str, image_path: str) -> str:
    """Upload a local image to the stock-images bucket. Returns the public URL."""
    import mimetypes
    from pathlib import Path as _P
    p    = _P(image_path)
    ext  = p.suffix.lower()
    name = f"{item_id}{ext}"
    mime = mimetypes.guess_type(str(p))[0] or "image/jpeg"
    data = p.read_bytes()
    try:
        get_client().storage.from_("stock-images").remove([name])
    except Exception:
        pass
    get_client().storage.from_("stock-images").upload(
        name, data,
        file_options={"content-type": mime, "upsert": "true"})
    return f"{SUPABASE_URL}/storage/v1/object/public/stock-images/{name}"


# ── Profile pictures ─────────────────────────────────────────────────────────

AVATAR_BUCKET = "avatars"


def upload_avatar(user_id: str, image_path: str) -> str:
    """Put a photo against an account and return the link to it.

    Named after the account rather than the file it came from, so replacing a
    picture replaces it rather than leaving the old one behind for ever.
    """
    import mimetypes
    from pathlib import Path as _P
    p = _P(image_path)
    ext = p.suffix.lower() or ".jpg"
    name = f"{user_id}{ext}"
    mime = mimetypes.guess_type(str(p))[0] or "image/jpeg"
    data = p.read_bytes()
    store = get_client().storage.from_(AVATAR_BUCKET)
    # A different extension would leave the old file sitting there.
    for old in (".jpg", ".jpeg", ".png", ".webp"):
        if old != ext:
            try:
                store.remove([f"{user_id}{old}"])
            except Exception:
                pass
    try:
        store.remove([name])
    except Exception:
        pass
    store.upload(name, data,
                 file_options={"content-type": mime, "upsert": "true"})
    # Cache-busted: the URL never changes when a picture is replaced, so
    # without this the old one keeps being served.
    import time as _t
    return (f"{SUPABASE_URL}/storage/v1/object/public/{AVATAR_BUCKET}/"
            f"{name}?v={int(_t.time())}")


def set_avatar(user_id: str, url: str) -> None:
    """Record the link on the profile. Falls back to a plain update on a
    database that hasn't had migrate_avatars.sql run."""
    try:
        get_client().rpc("set_avatar",
                         {"p_user_id": user_id, "p_url": url}).execute()
        return
    except Exception:
        pass
    get_client().table("profiles").update(
        {"avatar_url": url}).eq("id", user_id).execute()


def remove_avatar(user_id: str) -> None:
    """Take the picture off an account and out of storage."""
    store = get_client().storage.from_(AVATAR_BUCKET)
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        try:
            store.remove([f"{user_id}{ext}"])
        except Exception:
            pass
    set_avatar(user_id, "")


def current_avatar_url() -> str:
    return (current_profile() or {}).get("avatar_url") or ""


def refresh_current_profile() -> dict:
    """Re-read the signed-in account, after changing something on it."""
    global _current_profile
    user = current_user()
    if not user:
        return {}
    try:
        _current_profile = _load_profile(str(user.id)) or _current_profile
    except Exception:
        pass
    return _current_profile or {}


def can_manage_stock() -> bool:
    """Managers and above can create / edit / delete stock items."""
    return role_level() >= 3


# ── Pricing (see migrate_pricing.sql) ────────────────────────────────────────
# price_list is one price per part number, imported from the price
# spreadsheets. price_rates is a fallback per square metre, used only where a
# part number has no listed price.

def get_price_rows(search: str = "", limit: int = 0) -> list:
    """Every priced part number, or those matching `search`.

    Paged through in batches: PostgREST caps a response at 1000 rows, so a
    12,000-row price list would otherwise come back looking like 1,000.
    """
    def build():
        q = get_client().table("price_list").select("*")
        if search:
            s = search.replace(",", " ").strip()
            q = q.or_(f"part_number.ilike.%{s}%,name.ilike.%{s}%,"
                      f"description.ilike.%{s}%")
        return q.order("part_number")

    try:
        return _page_through(build, limit=limit)
    except Exception:
        return []


def count_prices() -> int:
    """How many part numbers are priced, without fetching them all."""
    try:
        resp = (get_client().table("price_list")
                .select("part_number", count="exact").limit(1).execute())
        return int(resp.count or 0)
    except Exception:
        return 0


def get_price_list() -> dict:
    """Part number → unit price."""
    out = {}
    for row in get_price_rows():
        part = (row.get("part_number") or "").strip().upper()
        if part:
            try:
                out[part] = float(row.get("unit_price") or 0)
            except (TypeError, ValueError):
                continue
    return out


def get_cost_list() -> dict:
    """Part number → what we pay for it.

    A part with no cost recorded is left out rather than stored as 0, so the
    difference between "costs nothing" and "nobody has said" survives all the
    way to the margin figure.
    """
    out = {}
    for row in get_price_rows():
        part = (row.get("part_number") or "").strip().upper()
        if not part:
            continue
        try:
            cost = float(row.get("unit_cost") or 0)
        except (TypeError, ValueError):
            continue
        if cost > 0:
            out[part] = cost
    return out


def upsert_prices(rows: list) -> int:
    """Save priced part numbers, replacing any that are already there.

    Sent in batches: a full price list runs to thousands of rows and a single
    request that size times out.
    """
    import datetime as _dt
    who, now = current_username(), _dt.datetime.utcnow().isoformat()
    payload = []
    for row in rows or []:
        part = (row.get("part_number") or "").strip().upper()
        if not part:
            continue
        entry = {
            "part_number":     part,
            "name":            (row.get("name") or "")[:300],
            "description":     (row.get("description") or "")[:500],
            "unit_price":      round(float(row.get("unit_price") or 0), 4),
            "updated_by_name": who,
            "updated_at":      now,
        }
        # Only sent when there is one, so importing a price spreadsheet with
        # no cost column can never wipe costs somebody has already entered.
        if row.get("unit_cost") not in (None, "", 0, 0.0):
            entry["unit_cost"] = round(float(row["unit_cost"]), 4)
        payload.append(entry)
    saved = 0
    for i in range(0, len(payload), 500):
        chunk = payload[i:i + 500]
        try:
            get_client().table("price_list").upsert(
                chunk, on_conflict="part_number").execute()
        except Exception as exc:
            if "unit_cost" not in str(exc):
                raise
            # migrate_margin.sql not run yet — save the prices, which is what
            # the app did before, rather than refusing the whole import.
            get_client().table("price_list").upsert(
                [{k: v for k, v in c.items() if k != "unit_cost"}
                 for c in chunk], on_conflict="part_number").execute()
        saved += len(chunk)
    return saved


def set_price(part_number: str, unit_price: float, name: str = "",
              description: str = "", unit_cost: float = 0.0) -> None:
    """Add or correct one priced part number."""
    upsert_prices([{"part_number": part_number, "unit_price": unit_price,
                    "name": name, "description": description,
                    "unit_cost": unit_cost}])


def delete_price(part_number: str) -> None:
    get_client().table("price_list").delete().eq(
        "part_number", (part_number or "").strip().upper()).execute()


def clear_price_list() -> None:
    """Remove every listed price. Used before a full re-import."""
    get_client().table("price_list").delete().neq("part_number", "").execute()


def get_price_rate_rows() -> list:
    try:
        resp = (get_client().table("price_rates")
                .select("*").order("filter_type").execute())
        return resp.data or []
    except Exception:
        return []


def set_price_rate(filter_type: str, media_type: str, rate: float,
                   cost: float = 0.0) -> None:
    import datetime as _dt
    row = {
        "filter_type":     (filter_type or "").strip(),
        "media_type":      (media_type or "").strip(),
        "rate_per_sqm":    round(float(rate or 0), 4),
        "updated_by_name": current_username(),
        "updated_at":      _dt.datetime.utcnow().isoformat(),
    }
    try:
        get_client().table("price_rates").upsert(
            {**row, "cost_per_sqm": round(float(cost or 0), 4)},
            on_conflict="filter_type,media_type").execute()
    except Exception as exc:
        if "cost_per_sqm" not in str(exc):
            raise
        # migrate_margin.sql not run yet: save the rate, which is what the
        # app did before, rather than refusing to save anything.
        get_client().table("price_rates").upsert(
            row, on_conflict="filter_type,media_type").execute()


def delete_price_rate(rate_id: str) -> None:
    get_client().table("price_rates").delete().eq("id", rate_id).execute()


def can_manage_prices() -> bool:
    """Managers and above. A wrong price goes out to a customer."""
    return role_level() >= 3


# ── Quotes (see migrate_quotes.sql) ──────────────────────────────────────────
# A quote is kept as the lines that were actually quoted, not as a reference
# to today's prices: what a customer was told does not change because the
# price list did.

# "viewed" is set by the customer portal when the link is first opened — the
# difference between "they haven't looked" and "they looked and haven't
# answered" is most of what following up is about.
QUOTE_STATUSES = ["draft", "sent", "viewed", "accepted", "declined", "expired"]
AWAITING_STATUSES = ("sent", "viewed")


def next_supplied_order_number() -> str:
    """Take the next TAF-ON- number from the shared counter.

    Straight to a Postgres sequence, so two people pressing the button at the
    same moment on different PCs cannot be handed the same number. Raises if
    the database is unreachable rather than inventing one locally: a
    duplicate order number is a worse problem than a delayed one.
    """
    resp = get_client().rpc("next_taf_order_number").execute()
    number = (resp.data or "")
    if isinstance(number, list):          # some clients wrap a scalar
        number = number[0] if number else ""
    number = str(number or "").strip()
    if not number:
        raise RuntimeError("The shared counter returned nothing.")
    return number


def next_quote_number() -> str:
    """The next quote number, as Q-0001. Falls back to a date-stamped one."""
    import datetime as _dt
    try:
        resp = (get_client().table("quotes")
                .select("quote_number")
                .like("quote_number", "Q-%")
                .order("quote_number", desc=True).limit(1).execute())
        rows = resp.data or []
        if rows:
            last = (rows[0].get("quote_number") or "").split("-")[-1]
            return f"Q-{int(last) + 1:04d}"
        return "Q-0001"
    except Exception:
        return f"Q-{_dt.datetime.now():%y%m%d-%H%M}"


def save_quote(data: dict) -> "dict | None":
    """Create a quote, or update one when `data` carries an id."""
    import datetime as _dt
    payload = {
        "quote_number":   (data.get("quote_number") or "").strip(),
        "customer_id":    data.get("customer_id") or None,
        "customer_name":  (data.get("customer_name") or "").strip(),
        "reference":      (data.get("reference") or "").strip(),
        "location":       (data.get("location") or "").strip(),
        "status":         (data.get("status") or "draft").strip(),
        "items":          data.get("items") or [],
        # The priced lines exactly as quoted, kept apart from `items` so what
        # the customer was shown is never re-rendered at today's prices.
        "lines":          data.get("lines") or [],
        "shipping":       round(float(data.get("shipping") or 0), 2),
        "subtotal":       round(float(data.get("subtotal") or 0), 2),
        "gst":            round(float(data.get("gst") or 0), 2),
        "total":          round(float(data.get("total") or 0), 2),
        "unpriced_count": int(data.get("unpriced_count") or 0),
        "valid_until":    data.get("valid_until") or None,
        "notes":          (data.get("notes") or "").strip(),
        "updated_at":     _dt.datetime.utcnow().isoformat(),
    }
    quote_id = data.get("id")
    if quote_id:
        get_client().table("quotes").update(payload).eq("id", quote_id).execute()
        return dict(payload, id=quote_id)
    payload["created_by_name"] = current_full_name() or current_username()
    resp = get_client().table("quotes").insert(payload).execute()
    return resp.data[0] if resp.data else None


def get_quotes(status: str = "", search: str = "", limit: int = 500) -> list:
    try:
        q = get_client().table("quotes").select("*")
        if status and status != "All":
            q = q.eq("status", status)
        resp = q.order("created_at", desc=True).limit(limit).execute()
        rows = resp.data or []
    except Exception:
        return []
    if search:
        s = search.lower()
        rows = [r for r in rows
                if s in (r.get("quote_number") or "").lower()
                or s in (r.get("customer_name") or "").lower()
                or s in (r.get("reference") or "").lower()]
    return rows


def get_quote(quote_id: str) -> "dict | None":
    try:
        resp = (get_client().table("quotes")
                .select("*").eq("id", quote_id).single().execute())
        return resp.data
    except Exception:
        return None


def set_quote_status(quote_id: str, status: str) -> None:
    import datetime as _dt
    get_client().table("quotes").update({
        "status": status,
        "updated_at": _dt.datetime.utcnow().isoformat(),
    }).eq("id", quote_id).execute()


def mark_quote_converted(quote_id: str, order_id: str = "") -> None:
    """Record that a quote became an order, so it can't be converted twice."""
    import datetime as _dt
    now = _dt.datetime.utcnow().isoformat()
    get_client().table("quotes").update({
        "status":             "accepted",
        "converted_order_id": order_id or None,
        "converted_at":       now,
        "updated_at":         now,
    }).eq("id", quote_id).execute()


def delete_quote(quote_id: str) -> None:
    get_client().table("quotes").delete().eq("id", quote_id).execute()


def can_delete_quotes() -> bool:
    return role_level() >= 3


# ── The customer quote portal (see migrate_quote_portal.sql) ────────────────
# A quote gets a random token; the link containing it is the only way in. The
# quotes table itself gives the anonymous role nothing — the page can call two
# functions and nothing else.

def ensure_quote_token(quote_id: str) -> str:
    """The quote's public token, creating one the first time it is shared.

    256 bits from `secrets`, so it cannot be guessed and does not need to be
    kept anywhere but in the link itself.
    """
    import secrets
    row = get_quote(quote_id) or {}
    existing = (row.get("public_token") or "").strip()
    if existing:
        return existing
    token = secrets.token_hex(32)
    get_client().table("quotes").update(
        {"public_token": token}).eq("id", quote_id).execute()
    return token


def mark_quote_sent(quote_id: str) -> None:
    """Record that the link went to the customer, so follow-up can start."""
    import datetime as _dt
    now = _dt.datetime.utcnow().isoformat()
    row = get_quote(quote_id) or {}
    payload = {"sent_at": row.get("sent_at") or now, "updated_at": now}
    # Only a quote nobody has answered moves to "sent".
    if (row.get("status") or "draft") in ("draft", "sent"):
        payload["status"] = "sent"
    get_client().table("quotes").update(payload).eq("id", quote_id).execute()


def quotes_awaiting_reply(days: int = 0) -> list:
    """Quotes sent to a customer that have had no answer.

    `days` keeps only those sent at least that long ago — the ones actually
    worth a phone call rather than the ones sent this morning.
    """
    import datetime as _dt
    try:
        resp = (get_client().table("quotes")
                .select("*")
                .in_("status", list(AWAITING_STATUSES))
                .order("sent_at", desc=False).limit(500).execute())
        rows = resp.data or []
    except Exception:
        return []
    if days <= 0:
        return rows
    cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=days)
    out = []
    for r in rows:
        stamp = (r.get("sent_at") or "")[:19]
        try:
            when = _dt.datetime.fromisoformat(stamp)
        except ValueError:
            continue          # never actually sent — nothing to chase
        if when <= cutoff:
            out.append(r)
    return out


# ── Phone upload page ────────────────────────────────────────────────────────
# The page phones open is NOT hosted on Supabase. Supabase serves anything it
# hosts as text/plain with "Content-Security-Policy: default-src 'none';
# sandbox" and X-Content-Type-Options: nosniff -- a deliberate anti-XSS policy
# -- so a page served from an Edge Function or from Storage arrives on the
# phone as unstyled source with every script blocked. It lives on GitHub Pages
# (docs/phone/index.html); the app only supplies the URL and key via the QR.


def current_anon_key() -> str:
    """The publishable key this app connected with (safe for the page)."""
    try:
        return get_client().supabase_key or ""
    except Exception:
        return ""


# ── Phone photo inbox (purchase orders sent from a phone) ────────────────────
# Layout in the private `po-inbox` bucket (see migrate_po_inbox.sql):
#     <batch-id>/01.jpg, 02.jpg, …
#     <batch-id>/_complete.json   ← written last by the phone page
# A batch without the marker is still uploading and must be left alone.

PO_INBOX_BUCKET = "po-inbox"
_PO_MARKER = "_complete.json"


def list_po_inbox_batches(skip: "set[str] | None" = None) -> list:
    """Return finished batches waiting to be read, oldest first.

    Each entry is {"batch", "photos": [names], "manifest": {...}}. Raises on a
    connection failure so the caller can stay quiet and retry later.

    `skip` names batches this PC has already read. Checking a batch costs a
    listing call plus a manifest download, and this runs on a timer, so a
    batch we are only going to discard is dropped before either of those.
    """
    skip = skip or set()
    store = get_client().storage.from_(PO_INBOX_BUCKET)
    folders = store.list("") or []
    batches = []
    for entry in folders:
        name = entry.get("name") or ""
        # Storage lists folders as entries with no id / metadata.
        if not name or entry.get("id") or name in skip:
            continue
        files = store.list(name) or []
        filenames = [f.get("name") or "" for f in files]
        if _PO_MARKER not in filenames:
            continue      # still uploading — leave it for the next sweep
        photos = sorted(n for n in filenames
                        if n and not n.startswith("_"))
        if not photos:
            continue
        manifest = {}
        try:
            import json as _json
            raw = store.download(f"{name}/{_PO_MARKER}")
            manifest = _json.loads(bytes(raw).decode("utf-8"))
        except Exception:
            pass
        batches.append({"batch": name, "photos": photos, "manifest": manifest})
    batches.sort(key=lambda b: b["batch"])
    return batches


def download_po_photo(batch: str, name: str) -> bytes:
    """Fetch one photo out of a batch."""
    return bytes(get_client().storage.from_(PO_INBOX_BUCKET)
                 .download(f"{batch}/{name}"))


def delete_po_batch(batch: str, names: list) -> None:
    """Remove a batch from the cloud once its photos are safely on this PC."""
    paths = [f"{batch}/{n}" for n in names] + [f"{batch}/{_PO_MARKER}"]
    try:
        get_client().storage.from_(PO_INBOX_BUCKET).remove(paths)
    except Exception:
        pass


# ── Customer list (for autocomplete) ─────────────────────────────────────────

def get_known_customers() -> list[str]:
    """Return sorted unique customer names from all orders."""
    try:
        resp = get_client().table("orders").select("customer_name").execute()
        seen, result = set(), []
        for r in (resp.data or []):
            name = (r.get("customer_name") or "").strip()
            key  = name.upper()
            if name and key not in seen:
                seen.add(key)
                result.append(name)
        return sorted(result, key=str.upper)
    except Exception:
        return []


# ── The offcut rack (see migrate_features.sql) ───────────────────────────────
# Channel that came off a stick and is long enough to be worth keeping. The
# calculator works the rack before it opens anything new, which is the whole
# point: a 900mm piece nobody reaches for is a 900mm piece that gets thrown
# out, and the same channel gets bought twice.

def list_offcuts(profile: str = "", on_rack: bool = True) -> list:
    """What is on the rack, longest first."""
    try:
        q = (get_client().table("channel_offcuts").select("*")
             .order("length_mm", desc=True).limit(500))
        if on_rack:
            q = q.eq("used", False)
        if profile:
            q = q.eq("profile", profile)
        return q.execute().data or []
    except Exception:
        return []


def add_offcut(length_mm: float, profile: str = "", note: str = "") -> dict:
    """Write one down. The moment to do it is the moment it comes off the
    stick, which is why anyone at the saw may, not only a manager."""
    length = float(length_mm)
    if length <= 0:
        raise ValueError("An offcut has to be longer than nothing.")
    resp = get_client().table("channel_offcuts").insert({
        "length_mm":  length,
        "profile":    str(profile or "").strip(),
        "note":       str(note or "").strip(),
        "created_by": current_full_name() or current_username(),
    }).execute()
    rows = resp.data or []
    return rows[0] if rows else {}


def use_offcut(offcut_id: str, used: bool = True) -> None:
    """Mark one as taken off the rack, or put it back.

    Marked, never deleted: "where did that 1300 go" is a question somebody
    asks, and a row that vanished cannot answer it.
    """
    import datetime as _dt
    get_client().table("channel_offcuts").update({
        "used":    bool(used),
        "used_at": _dt.datetime.now(_dt.timezone.utc).isoformat() if used else None,
        "used_by": (current_full_name() or current_username()) if used else "",
    }).eq("id", str(offcut_id)).execute()


def offcut_lengths(profile: str = "") -> list:
    """Just the lengths, for handing to the calculator."""
    return [float(r.get("length_mm") or 0)
            for r in list_offcuts(profile) if r.get("length_mm")]


# ── Which way a customer's filters get made ──────────────────────────────────

def frame_preference(customer_name: str) -> str:
    """'u', 'sideways_u', 'g', or '' for whichever is cheapest that day."""
    name = str(customer_name or "").strip()
    if not name:
        return ""
    try:
        resp = (get_client().table("customers")
                .select("frame_preference,name,short_name").execute())
        wanted = name.upper()
        for row in resp.data or []:
            if wanted in (str(row.get("name") or "").strip().upper(),
                          str(row.get("short_name") or "").strip().upper()):
                pref = str(row.get("frame_preference") or "").strip().lower()
                return pref if pref in ("u", "sideways_u", "g") else ""
    except Exception:
        pass
    return ""


def set_frame_preference(customer_id: str, preference: str) -> None:
    pref = str(preference or "").strip().lower()
    if pref not in ("", "u", "sideways_u", "g"):
        raise ValueError(f"{preference!r} is not a way of making a filter.")
    get_client().table("customers").update(
        {"frame_preference": pref}).eq("id", str(customer_id)).execute()


# ── Sizes we already make ────────────────────────────────────────────────────

def made_sizes(limit: int = 400) -> list:
    """Every filter size that has been ordered, and how often.

    Used to spot a 597 x 497 that is two millimetres off something we run
    every week, while somebody is still typing rather than after the channel
    has been cut.
    """
    try:
        resp = (get_client().table("orders").select("items")
                .eq("archived", False)
                .order("created_at", desc=True).limit(limit).execute())
    except Exception:
        return []
    counts: dict = {}
    for row in resp.data or []:
        for item in (row.get("items") or []):
            if not isinstance(item, dict):
                continue
            if str(item.get("item_kind", "filter")) != "filter":
                continue
            try:
                short = float(item.get("Short") or 0)
                long = float(item.get("Long") or 0)
            except (TypeError, ValueError):
                continue
            if short <= 0 or long <= 0:
                continue
            if short > long:
                short, long = long, short
            key = (short, long)
            counts[key] = counts.get(key, 0) + 1
    return [{"short": s, "long": l, "seen": n}
            for (s, l), n in sorted(counts.items(), key=lambda kv: -kv[1])]


# ── Where a job has got to (see the worksheet's own tick boxes) ──────────────
# Marked channel, cut channel, drilled channel, assembled, packed. These are
# not stages invented for a screen - they are the five boxes already printed
# down the side of every worksheet, so a board built on them matches what
# somebody is already ticking with a pen.

STAGES = [
    ("marked",    "Marked channel"),
    ("cut",       "Cut channel"),
    ("drilled",   "Drilled channel"),
    ("assembled", "Assembled"),
    ("packed",    "Packed"),
]

STAGE_KEYS = [k for k, _ in STAGES]


def order_stages(header: dict) -> dict:
    """Which boxes are ticked on one order."""
    got = (header or {}).get("stages") or {}
    if not isinstance(got, dict):
        return {k: False for k in STAGE_KEYS}
    return {k: bool(got.get(k)) for k in STAGE_KEYS}


def stage_reached(header: dict) -> str:
    """The furthest box ticked, or '' for nothing started.

    Furthest rather than "the first one not ticked": somebody who ticks
    Assembled without ticking Drilled has still assembled it, and a board
    that put that job back at the saw would be arguing with the person who
    did the work.
    """
    got = order_stages(header)
    reached = ""
    for key in STAGE_KEYS:
        if got.get(key):
            reached = key
    return reached


def set_order_stage(order_id: str, stage: str, done: bool = True) -> str:
    """Tick or untick one box, without touching anything else on the header.

    Through merge_order_header for the usual reason: two benches ticking two
    different boxes on the same job is the normal case, and a read-change-
    write from here would have whoever saved second wipe the other's tick.
    """
    if stage not in STAGE_KEYS:
        raise ValueError(f"There is no stage called {stage!r}.")
    header = {}
    try:
        resp = (get_client().table("orders").select("header")
                .eq("id", str(order_id)).limit(1).execute())
        rows = resp.data or []
        header = (rows[0].get("header") or {}) if rows else {}
    except Exception:
        header = {}
    stages = order_stages(header)
    stages[stage] = bool(done)
    stages["at"] = _now_stamp()
    stages["by"] = current_full_name() or current_username()
    return merge_order_header(str(order_id), {"stages": stages})


def _now_stamp() -> str:
    import datetime as _dt
    d = _dt.datetime.now()
    return f"{d.day:02d}/{d.month:02d}/{d.year} {d.hour:02d}:{d.minute:02d}"


# ── Part-dispatched orders (backorders) ──────────────────────────────────────
# Twenty on the order, twelve made, and the customer wants those twelve now.
# At the moment that is an order nothing can honestly be marked on: Complete
# is a lie and Pending stops it going out.
#
# What has gone lives on the header rather than on each line, and is written
# through merge_order_header for the same reason line ticks are: two people
# packing two lines of the same order is normal, and a read-change-write from
# here would have whoever saved second wipe the other's work.

def sent_quantities(header: dict) -> dict:
    """{line_id: how many have gone}."""
    got = (header or {}).get("sent") or {}
    if not isinstance(got, dict):
        return {}
    out = {}
    for key, value in got.items():
        if key in ("at", "by"):
            continue
        try:
            out[str(key)] = max(0, int(float(value)))
        except (TypeError, ValueError):
            continue
    return out


def set_line_sent(order_id: str, line_id: str, qty: int) -> str:
    """Record how many of one line have actually gone out."""
    if not str(line_id or "").strip():
        raise ValueError("That line has no id, so nothing can be recorded "
                         "against it. Open the order once on a PC with "
                         "line ticking switched on first.")
    header = {}
    try:
        resp = (get_client().table("orders").select("header")
                .eq("id", str(order_id)).limit(1).execute())
        rows = resp.data or []
        header = (rows[0].get("header") or {}) if rows else {}
    except Exception:
        header = {}
    sent = sent_quantities(header)
    sent[str(line_id)] = max(0, int(qty))
    sent["at"] = _now_stamp()
    sent["by"] = current_full_name() or current_username()
    return merge_order_header(str(order_id), {"sent": sent})


def outstanding_lines(items: list, header: dict) -> list:
    """Every line with what is still owed on it.

    Nothing here decides a status. A part-dispatched order is still open, and
    whether it gets closed is a decision for a person who can see how much is
    left - which is the number this exists to produce.
    """
    sent = sent_quantities(header)
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        try:
            want = int(float(item.get("Quantity") or item.get("quantity") or 0))
        except (TypeError, ValueError):
            want = 0
        gone = sent.get(str(item.get(LINE_ID) or ""), 0)
        out.append({
            "item": item,
            "line_id": str(item.get(LINE_ID) or ""),
            "ordered": want,
            "sent": min(gone, want),
            "left": max(0, want - gone),
        })
    return out
