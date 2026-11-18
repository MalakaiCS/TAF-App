"""Folding duplicate customer accounts into one.

The database does the merge (merge_customers in migrate_packing_and_merge.sql)
in one transaction, with the manager check, the locks and the undo record.
This module is everything around it that a person needs to decide well:

  * suggest_duplicates() - accounts that look like the same company, with
    the reason each one was suggested. A suggestion is never acted on by
    itself: two branches of one company share a legal name and are NOT
    duplicates, and fuzzy name matches are how a Bells Creek order ended up
    in Tweed before. Branches only pair up when something that identifies a
    place or a person (address, phone, email) matches too.
  * conflicts() - every field the accounts disagree on, so each one is
    chosen rather than defaulted. Different ABNs are called out on their
    own: they usually mean two companies.
  * external_ids() - what an outside system knows these accounts as. Xero
    finds contacts by name, so each former name is listed as something to
    tidy up in Xero by hand; nothing here renames or joins a Xero contact,
    and nothing touches an invoice that has already been posted.
  * likely_matches() - asked when somebody creates a new customer, so the
    duplicate is caught before it exists.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, Iterable, List, Optional, Sequence

MERGEABLE_FIELDS = (
    "name", "legal_name", "short_name", "abn", "website", "contact_person",
    "contact_role", "phone", "email", "delivery_address1", "delivery_address2",
    "delivery_city", "delivery_state", "delivery_postcode", "delivery_country",
    "billing_address1", "billing_address2", "billing_city", "billing_state",
    "billing_postcode", "billing_country", "payment_terms", "currency",
    "notes", "region", "job_number_label", "frame_preference",
)

_NOISE = {"pty", "ltd", "limited", "the", "and", "co", "company", "inc",
          "australia", "group", "services", "service"}


class MergeError(ValueError):
    pass


def _words(text: Any) -> str:
    words = re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).split()
    return " ".join(w for w in words if w not in _NOISE)


def _digits(text: Any) -> str:
    return re.sub(r"\D", "", str(text or ""))


def _email(text: Any) -> str:
    return str(text or "").strip().lower()


def _address(c: Dict[str, Any]) -> str:
    return _words(" ".join(str(c.get(k) or "") for k in (
        "delivery_address1", "delivery_city", "delivery_postcode")))


def keys(c: Dict[str, Any]) -> Dict[str, str]:
    """What an account can be recognised by, normalised."""
    phone = _digits(c.get("phone"))
    if phone.startswith("61") and len(phone) == 11:
        phone = "0" + phone[2:]
    return {
        "name": _words(c.get("name")),
        "short_name": _words(c.get("short_name")),
        "legal_name": _words(c.get("legal_name")),
        "abn": _digits(c.get("abn")),
        "email": _email(c.get("email")),
        "phone": phone if len(phone) >= 8 else "",
        "address": _address(c),
    }


def _pair_reasons(a: Dict[str, Any], b: Dict[str, Any]) -> List[str]:
    ka, kb = keys(a), keys(b)
    place = []
    if ka["email"] and ka["email"] == kb["email"]:
        place.append(f"same email ({a.get('email')})")
    if ka["phone"] and ka["phone"] == kb["phone"]:
        place.append(f"same phone ({a.get('phone')})")
    if ka["address"] and len(ka["address"]) > 6 and ka["address"] == kb["address"]:
        place.append("same delivery address")
    names = {v for v in (ka["name"], ka["short_name"]) if v}
    other = {v for v in (kb["name"], kb["short_name"]) if v}
    same_name = bool(names & other)
    same_abn = bool(ka["abn"]) and ka["abn"] == kb["abn"]
    same_company = (ka["legal_name"] and ka["legal_name"] == kb["legal_name"]) \
        or same_abn
    reasons = []
    if same_name:
        reasons.append("same name")
    if same_company and place:
        reasons.append("same company" + (" (ABN)" if same_abn else ""))
    reasons += place
    # The same company with nothing tying the two to one place is two
    # branches, not one account twice.
    if not same_name and not place:
        return []
    return reasons


def suggest_duplicates(customers: Iterable[Dict[str, Any]]
                       ) -> List[Dict[str, Any]]:
    """Groups of accounts that may be one company, likeliest first.

    Returns [{"ids", "accounts", "reasons", "abn_conflict"}]. Nothing in a
    group has been merged - it is a list for somebody to look at.
    """
    live = [c for c in customers or []
            if c.get("id") and not c.get("merged_into")]
    parent: Dict[str, str] = {c["id"]: c["id"] for c in live}
    reasons: Dict[frozenset, List[str]] = {}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(live):
        for b in live[i + 1:]:
            why = _pair_reasons(a, b)
            if why:
                reasons[frozenset((a["id"], b["id"]))] = why
                parent[find(a["id"])] = find(b["id"])
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for c in live:
        groups.setdefault(find(c["id"]), []).append(c)
    out = []
    for members in groups.values():
        if len(members) < 2:
            continue
        ids = {m["id"] for m in members}
        why = sorted({r for pair, rs in reasons.items() if pair <= ids
                      for r in rs})
        abns = {keys(m)["abn"] for m in members} - {""}
        out.append({"ids": [m["id"] for m in members], "accounts": members,
                    "reasons": why, "abn_conflict": len(abns) > 1})
    out.sort(key=lambda g: (-len(g["reasons"]), -len(g["ids"])))
    return out


def likely_matches(new: Dict[str, Any], customers: Iterable[Dict[str, Any]],
                   limit: int = 5) -> List[Dict[str, Any]]:
    """Existing accounts a new customer might already be. [{"customer",
    "reasons"}]. Shown as a warning; creating it anyway is allowed."""
    out = []
    for c in customers or []:
        if c.get("merged_into"):
            continue
        why = _pair_reasons(new, c)
        kn, kc = keys(new), keys(c)
        if not why and kn["name"] and kc["name"] and (
                kn["name"] in kc["name"] or kc["name"] in kn["name"]) \
                and len(min(kn["name"], kc["name"], key=len)) >= 5:
            why = ["similar name"]
        if why:
            out.append({"customer": c, "reasons": why})
    out.sort(key=lambda r: -len(r["reasons"]))
    return out[:limit]


def conflicts(accounts: Sequence[Dict[str, Any]]) -> Dict[str, List[str]]:
    """{field: [the different values]} for every field that disagrees."""
    out: Dict[str, List[str]] = {}
    for field in MERGEABLE_FIELDS:
        values = []
        for a in accounts:
            v = str(a.get(field) or "").strip()
            if v and v not in values:
                values.append(v)
        if len(values) > 1:
            out[field] = values
    return out


def abn_conflict(accounts: Sequence[Dict[str, Any]]) -> bool:
    return len({keys(a)["abn"] for a in accounts} - {""}) > 1


def price_conflicts(prices: Iterable[Dict[str, Any]], survivor: str,
                    merged: Sequence[str]) -> List[str]:
    """Part numbers with an agreed price on more than one of the accounts."""
    owners: Dict[str, set] = {}
    for p in prices or []:
        cid = p.get("customer_id")
        if cid != survivor and cid not in merged:
            continue
        part = str(p.get("part_number") or "").strip().upper()
        owners.setdefault(part, set()).add(cid)
    return sorted(part for part, who in owners.items() if len(who) > 1)


def external_ids(accounts: Sequence[Dict[str, Any]], survivor_name: str
                 ) -> List[str]:
    """What has to be tidied by hand outside the program."""
    notes = []
    for a in accounts:
        for field in ("name", "short_name"):
            name = str(a.get(field) or "").strip()
            if name and name.lower() != survivor_name.strip().lower():
                notes.append(f"Xero contact named \"{name}\" - Xero matches "
                             "contacts by name. Merge or rename it in Xero; "
                             "posted invoices there are not changed from here.")
    if any(a.get("portal_enabled") for a in accounts[1:]):
        notes.append("Customer-portal links for the merged accounts stop "
                     "working; send the customer the surviving account's "
                     "link.")
    return list(dict.fromkeys(notes))


def decisions(survivor: Dict[str, Any], chosen: Dict[str, Any],
              prices: Optional[Dict[str, str]] = None,
              confirm_different_abn: bool = False) -> Dict[str, Any]:
    """The decisions the database needs. Every field that disagreed must be
    in `chosen`; the survivor's own values fill the rest."""
    name = str(chosen.get("name") or survivor.get("name") or "").strip()
    if not name:
        raise MergeError("Choose the company name the merged account keeps.")
    out_set = {k: v for k, v in chosen.items() if k in MERGEABLE_FIELDS}
    out_set["name"] = name
    if "payment_terms" not in out_set and survivor.get("payment_terms"):
        out_set["payment_terms"] = survivor["payment_terms"]
    return {"set": out_set, "prices": dict(prices or {}),
            "confirm_different_abn": bool(confirm_different_abn)}


def check_ready(accounts: Sequence[Dict[str, Any]], survivor_id: str,
                chosen: Dict[str, Any], price_choices: Dict[str, str],
                prices: Iterable[Dict[str, Any]] = (),
                confirm_different_abn: bool = False) -> List[str]:
    """Everything still to decide, in words. Empty means ready."""
    todo = []
    ids = [a.get("id") for a in accounts]
    if survivor_id not in ids:
        todo.append("Choose the account that stays.")
    if len(ids) < 2:
        todo.append("Choose at least two accounts.")
    if len(set(ids)) != len(ids):
        todo.append("An account is listed twice.")
    if any(a.get("merged_into") for a in accounts):
        todo.append("One of these has already been merged.")
    for field, values in conflicts(accounts).items():
        if field not in chosen and field != "name":
            todo.append(f"Choose the {field.replace('_', ' ')}: "
                        + " / ".join(values))
    if not str(chosen.get("name") or "").strip():
        todo.append("Choose the company name to keep.")
    if abn_conflict(accounts) and not confirm_different_abn:
        todo.append("These accounts have different ABNs. Confirm they are "
                    "the same company before merging.")
    merged = [i for i in ids if i != survivor_id]
    for part in price_conflicts(prices, survivor_id, merged):
        if part not in price_choices:
            todo.append(f"Choose which agreed price stays for "
                        f"{part or 'the across-the-board discount'}.")
    return todo


# ── Talking to the database ─────────────────────────────────────────────────

def new_request_id() -> str:
    return "merge-" + uuid.uuid4().hex


def preview(ids: Sequence[str]) -> List[Dict[str, Any]]:
    from . import db as _db
    resp = _db.get_client().rpc("customer_merge_preview",
                                {"p_ids": list(ids)}).execute()
    return list(resp.data or [])


def merge(request_id: str, survivor_id: str, merged_ids: Sequence[str],
          decided: Dict[str, Any],
          expected: Optional[Dict[str, str]] = None) -> str:
    """Run the merge. The same request id sent again returns the same merge,
    so a retry after a dropped connection is safe."""
    from . import db as _db
    resp = _db.get_client().rpc("merge_customers", {
        "p_request_id": request_id, "p_survivor": survivor_id,
        "p_merged": list(merged_ids), "p_decisions": decided,
        "p_expected": expected}).execute()
    data = resp.data
    if isinstance(data, list):
        data = data[0] if data else None
    if not data:
        raise MergeError("The database did not confirm the merge.")
    return str(data)


def undo(merge_id: str) -> Dict[str, Any]:
    from . import db as _db
    resp = _db.get_client().rpc("undo_customer_merge",
                                {"p_merge_id": merge_id}).execute()
    data = resp.data
    if isinstance(data, list):
        data = data[0] if data else {}
    return dict(data or {})


def sync_order_names(customer_id: str) -> Optional[int]:
    """Put an account's name on all its past orders and quotes - and on
    those of every account merged into it (step 36). The number of orders
    changed, or None when step 36 has not been run yet."""
    from . import db as _db
    try:
        resp = _db.get_client().rpc("sync_customer_order_names",
                                    {"p_id": customer_id}).execute()
    except Exception as exc:
        if "sync_customer_order_names" in str(exc):
            return None
        raise
    data = resp.data
    if isinstance(data, list):
        data = data[0] if data else 0
    try:
        return int(data or 0)
    except (TypeError, ValueError):
        return 0


STEP_36 = ("Run migrate_merge_names.sql (step 36) in Supabase so past "
           "orders show the new name.")


def recent_merges(limit: int = 20) -> List[Dict[str, Any]]:
    from . import db as _db
    resp = (_db.get_client().table("customer_merges")
            .select("id,survivor_id,merged_ids,merged_by_name,merged_at,"
                    "undone_at,decisions")
            .order("merged_at", desc=True).limit(limit).execute())
    return list(resp.data or [])
