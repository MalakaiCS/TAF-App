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

def save_order(header: dict, items: list, order_type: str) -> "str | None":
    """Insert an order and return its new id (or None if it can't be read)."""
    user = _current_user
    if not user:
        raise RuntimeError("Not logged in.")
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
    try:
        resp = get_client().table("orders").select("header").eq("id", order_id).single().execute()
        header = dict(resp.data.get("header") or {})
        header["printed"]    = True
        header["printed_at"] = _dt.datetime.now().strftime("%d/%m/%Y %H:%M")
        get_client().table("orders").update({"header": header}).eq("id", order_id).execute()
    except Exception:
        pass


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


def get_all_orders() -> list:
    try:
        resp = (
            get_client()
            .table("orders")
            .select("*")
            .eq("archived", False)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as exc:
        if "archived" in str(exc):
            # Migration not yet run — fetch without archived filter
            resp = (
                get_client()
                .table("orders")
                .select("*")
                .order("created_at", desc=True)
                .execute()
            )
        else:
            raise
    return resp.data or []


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


# ── Priority ──────────────────────────────────────────────────────────────────

def set_order_priority(order_id: str, priority: bool) -> None:
    """Set or clear the priority flag stored in the order's header JSON."""
    try:
        resp = get_client().table("orders").select("header").eq("id", order_id).single().execute()
        header = dict(resp.data.get("header") or {})
        header["priority"] = priority
        get_client().table("orders").update({"header": header}).eq("id", order_id).execute()
    except Exception:
        pass


# ── Order Status ──────────────────────────────────────────────────────────────

ORDER_STATUS_VALUES = [
    "Pending", "In Production", "Complete",
    "Dispatched",
]


def set_order_status(order_id: str, status: str) -> None:
    """Set the order status stored in the order's header JSON."""
    try:
        resp = get_client().table("orders").select("header").eq("id", order_id).single().execute()
        header = dict(resp.data.get("header") or {})
        header["status"] = status
        get_client().table("orders").update({"header": header}).eq("id", order_id).execute()
    except Exception:
        pass


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
    """Append a timestamped note to the order's header JSON."""
    import datetime as _dt
    try:
        resp = get_client().table("orders").select("header").eq("id", order_id).single().execute()
        header = dict(resp.data.get("header") or {})
        existing = header.get("order_notes") or []
        if isinstance(existing, str):
            existing = [{"ts": "", "author": "", "text": existing}] if existing else []
        ts = _dt.datetime.utcnow().strftime("%d/%m/%Y %H:%M")
        existing.append({"ts": ts, "author": author, "text": note_text})
        header["order_notes"] = existing
        get_client().table("orders").update({"header": header}).eq("id", order_id).execute()
    except Exception:
        pass


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
                 quantity: float, notes: str = "") -> float:
    """
    Adjust stock_on_hand and record a transaction row.
    transaction_type:
        'receive'  → add quantity (positive delta)
        'use'      → subtract quantity (stored as negative delta)
        'count'    → set absolute value; delta = new - old
        'writeoff' → subtract quantity (negative delta), marks loss
    Returns new stock_on_hand.
    """
    import datetime as _dt
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
    out: list = []
    step = 1000
    try:
        while True:
            q = get_client().table("price_list").select("*")
            if search:
                s = search.replace(",", " ").strip()
                q = q.or_(f"part_number.ilike.%{s}%,name.ilike.%{s}%,"
                          f"description.ilike.%{s}%")
            resp = (q.order("part_number")
                    .range(len(out), len(out) + step - 1).execute())
            batch = resp.data or []
            out.extend(batch)
            if len(batch) < step or (limit and len(out) >= limit):
                break
    except Exception:
        pass
    return out[:limit] if limit else out


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
        payload.append({
            "part_number":     part,
            "name":            (row.get("name") or "")[:300],
            "description":     (row.get("description") or "")[:500],
            "unit_price":      round(float(row.get("unit_price") or 0), 4),
            "updated_by_name": who,
            "updated_at":      now,
        })
    saved = 0
    for i in range(0, len(payload), 500):
        chunk = payload[i:i + 500]
        get_client().table("price_list").upsert(
            chunk, on_conflict="part_number").execute()
        saved += len(chunk)
    return saved


def set_price(part_number: str, unit_price: float, name: str = "",
              description: str = "") -> None:
    """Add or correct one priced part number."""
    upsert_prices([{"part_number": part_number, "unit_price": unit_price,
                    "name": name, "description": description}])


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


def set_price_rate(filter_type: str, media_type: str, rate: float) -> None:
    import datetime as _dt
    get_client().table("price_rates").upsert({
        "filter_type":     (filter_type or "").strip(),
        "media_type":      (media_type or "").strip(),
        "rate_per_sqm":    round(float(rate or 0), 4),
        "updated_by_name": current_username(),
        "updated_at":      _dt.datetime.utcnow().isoformat(),
    }, on_conflict="filter_type,media_type").execute()


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


def list_po_inbox_batches() -> list:
    """Return finished batches waiting to be read, oldest first.

    Each entry is {"batch", "photos": [names], "manifest": {...}}. Raises on a
    connection failure so the caller can stay quiet and retry later.
    """
    store = get_client().storage.from_(PO_INBOX_BUCKET)
    folders = store.list("") or []
    batches = []
    for entry in folders:
        name = entry.get("name") or ""
        # Storage lists folders as entries with no id / metadata.
        if not name or entry.get("id"):
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
