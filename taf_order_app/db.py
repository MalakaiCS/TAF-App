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

def save_order(header: dict, items: list, order_type: str) -> None:
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
        get_client().table("orders").insert(
            {**data, "created_by_role": prof.get("role", "Employee")}
        ).execute()
    except Exception as exc:
        if "created_by_role" in str(exc) or "archived" in str(exc):
            # Migration not yet run — insert without new columns
            get_client().table("orders").insert(data).execute()
        else:
            raise


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

STOCK_UNITS = ["each", "metre", "roll", "kg", "box", "pack", "sheet", "pair", "set"]


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
