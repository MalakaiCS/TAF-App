"""How we do things, and talking to each other.

The how-to library (what a procedure says, and who has read the version
there now) and the noticeboard and group chats (who may post, pin, start a
group or take a message down). Pure, so it is tested on its own.

The rules themselves are held by the database - migrate_staff_board.sql
(step 49) - and nothing here can grant anything. This is what the screens
use to decide which buttons to offer. docs/app/screens.js has the same
rules (chatMay, messageTime, readState, sopsForType), held to these by
tests/web_app.py.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, Iterable, List, Optional

# The same ladder as db.ROLE_LEVEL and role_rank() in step 49.
RANK = {"Employee": 1, "Manager": 3, "Admin": 4, "Director": 4}

# What a rule can be set to, and how it reads.
WHO = {"Employee": "Everybody", "Manager": "Managers and above",
       "Admin": "Directors and admins"}

# Each rule, what it means, and what it is out of the box.
RULES = {
    "post_board": ("Post on the noticeboard", "Manager"),
    "pin":        ("Pin a message", "Admin"),
    "make_group": ("Start a group chat", "Manager"),
    "remove_any": ("Take down anybody's message", "Admin"),
}


def rank(role: Any) -> int:
    return RANK.get(str(role or ""), 0)


def may(action: str, role: Any, rules: Optional[Dict[str, str]] = None) -> bool:
    """Whether somebody with `role` may do `action` under `rules`
    ({action: least role}). An action nobody has a rule for is for
    directors and admins only."""
    need = (rules or {}).get(action) or RULES.get(action, ("", "Admin"))[1]
    return rank(role) > 0 and rank(role) >= rank(need)


def rules_with_defaults(rows: Iterable[Dict[str, Any]]) -> Dict[str, str]:
    """{action: least role} from chat_rules rows, defaults filled in."""
    out = {k: v[1] for k, v in RULES.items()}
    for r in rows or []:
        if r.get("action") in out and r.get("min_role") in WHO:
            out[r["action"]] = r["min_role"]
    return out


def _when(value: Any) -> Optional[_dt.datetime]:
    try:
        d = _dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone() if d.tzinfo else d


def message_time(stamp: Any, now: _dt.datetime) -> str:
    """"10:42" today, "Mon 10:42" in the last week, "17/10/2026" before."""
    d = _when(stamp)
    if d is None:
        return ""
    d = d.replace(tzinfo=None)
    now = now.replace(tzinfo=None)
    if d.date() == now.date():
        return d.strftime("%H:%M")
    if 0 < (now.date() - d.date()).days < 7:
        return d.strftime("%a %H:%M")
    return d.strftime("%d/%m/%Y")


# ── The how-to library ───────────────────────────────────────────────────────

def read_state(sop: Dict[str, Any], mine: Optional[Dict[str, Any]]) -> str:
    """"new" (never read), "changed" (read an older version) or "read"."""
    if not mine:
        return "new"
    try:
        return "read" if int(mine.get("version") or 0) >= int(sop.get("version") or 1) \
            else "changed"
    except (TypeError, ValueError):
        return "new"


def sops_for_type(sops: Iterable[Dict[str, Any]], filter_type: Any) -> List[Dict[str, Any]]:
    """The how-tos for making a filter type, in title order."""
    want = str(filter_type or "").strip().lower()
    if not want:
        return []
    return sorted((s for s in sops or [] if not s.get("archived")
                   and str(s.get("filter_type") or "").strip().lower() == want),
                  key=lambda s: str(s.get("title") or "").lower())


def by_category(sops: Iterable[Dict[str, Any]]) -> List[tuple]:
    """[(category, [how-tos])], categories A-Z with the unfiled last."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for s in sops or []:
        if s.get("archived"):
            continue
        groups.setdefault(str(s.get("category") or "").strip() or "Other", []).append(s)
    names = sorted(groups, key=lambda n: (n == "Other", n.lower()))
    return [(n, sorted(groups[n], key=lambda s: str(s.get("title") or "").lower()))
            for n in names]


def sign_offs(sop: Dict[str, Any], reads: Iterable[Dict[str, Any]],
              people: Iterable[str]) -> Dict[str, List[str]]:
    """Who has read the version there now, who read an older one, and who
    has not read it at all - from sop_reads and the names of everybody on
    staff."""
    version = int(sop.get("version") or 1)
    done, behind = [], []
    seen = set()
    for r in reads or []:
        if str(r.get("sop_id")) != str(sop.get("id")):
            continue
        name = str(r.get("person") or "")
        seen.add(name)
        (done if int(r.get("version") or 0) >= version else behind).append(name)
    missing = [p for p in people or [] if p and p not in seen]
    return {"read": sorted(done), "behind": sorted(behind), "not": sorted(missing)}


def video_ok(url: Any) -> bool:
    text = str(url or "").strip().lower()
    return text.startswith("https://") or text.startswith("http://")
