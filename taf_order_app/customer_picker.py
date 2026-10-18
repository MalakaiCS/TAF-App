"""The customer list under the order form's Customer Name.

An order is always for a customer account: the name typed is looked up, the
accounts it could mean are listed - a coloured badge of initials, the name
with what was typed in bold, and a grey line with the short name, contact
and email - and the first row offers to make the account when it is not
there yet.

Nothing here touches Tk, so the matching is tested on its own.
"""
from __future__ import annotations

import re

# Badge colours: dark enough for white initials, far enough apart to tell
# neighbouring rows apart.
BADGE_COLOURS = ("#2E86C1", "#28B463", "#AF601A", "#8E44AD", "#C0392B",
                 "#117A65", "#B9770E", "#1F618D", "#6C3483", "#239B56",
                 "#A04000", "#2874A6")

# Searched as well as the name, in this order for the grey line.
SUBTITLE_FIELDS = ("short_name", "contact_person", "email")
SEARCH_FIELDS = ("name", "short_name", "legal_name", "contact_person",
                 "email", "abn")
LIMIT = 40


def _text(value) -> str:
    return str(value or "").strip()


def initials(name: str) -> str:
    """"AC 1 PTY LTD" -> "A1P", "Access Towing" -> "AT": the first letter or
    digit of up to three words."""
    words = [w for w in re.split(r"[^0-9A-Za-z]+", _text(name)) if w]
    return "".join(w[0] for w in words[:3]).upper() or "?"


def badge_colour(name: str) -> str:
    """The same account gets the same colour every time it is listed."""
    key = _text(name).upper()
    return BADGE_COLOURS[sum(ord(c) for c in key) % len(BADGE_COLOURS)]


def segments(text: str, typed: str) -> list:
    """`text` cut into (piece, bold) runs, bold wherever `typed` appears,
    ignoring case: "Access Towing", "ac" -> [("Ac", True), ("cess Towing",
    False)]."""
    text = text or ""
    typed = (typed or "").strip()
    if not typed:
        return [(text, False)] if text else []
    out, at = [], 0
    for m in re.finditer(re.escape(typed), text, re.IGNORECASE):
        if m.start() > at:
            out.append((text[at:m.start()], False))
        out.append((m.group(0), True))
        at = m.end()
    if at < len(text):
        out.append((text[at:], False))
    return out


def subtitle(rec: dict) -> str:
    """The grey second line: short name, contact and email, as known."""
    name = _text(rec.get("name")).upper()
    parts = []
    for key in SUBTITLE_FIELDS:
        value = _text(rec.get(key))
        if value and value.upper() != name and value not in parts:
            parts.append(value)
    return " • ".join(parts)


def is_active(rec: dict) -> bool:
    return rec.get("is_active", True) is not False


def _rank(rec: dict, typed_up: str):
    """Smaller is better; None when the account does not match at all."""
    name = _text(rec.get("name")).upper()
    if name == typed_up or _text(rec.get("short_name")).upper() == typed_up:
        return 0
    if name.startswith(typed_up):
        return 1
    if any(w.startswith(typed_up) for w in re.split(r"[^0-9A-Z]+", name)):
        return 2
    if typed_up in name:
        return 3
    for key in SEARCH_FIELDS[1:]:
        if typed_up in _text(rec.get(key)).upper():
            return 4
    return None


def matches(records, typed: str, limit: int = LIMIT) -> list:
    """Active accounts `typed` could mean, best first: the name exactly,
    then names starting with it, a word starting with it, the name holding
    it, and last the short name, legal name, contact, email or ABN holding
    it. Alphabetical within each."""
    typed_up = _text(typed).upper()
    if not typed_up:
        return []
    ranked = []
    for rec in records or []:
        if not is_active(rec):
            continue
        r = _rank(rec, typed_up)
        if r is not None:
            ranked.append((r, _text(rec.get("name")).upper(), rec))
    ranked.sort(key=lambda t: (t[0], t[1]))
    return [rec for _r, _n, rec in ranked[:limit]]


def find_exact(records, typed: str):
    """The account whose name or short name is exactly what was typed
    (ignoring case and the spaces round it), or None. An active account wins
    over an inactive one of the same name."""
    typed_up = _text(typed).upper()
    if not typed_up:
        return None
    hits = [rec for rec in records or []
            if typed_up in (_text(rec.get("name")).upper(),
                            _text(rec.get("short_name")).upper())]
    hits.sort(key=lambda rec: not is_active(rec))
    return hits[0] if hits else None


def create_label(typed: str) -> str:
    return f'+ Create "{_text(typed)}" as a new customer'
