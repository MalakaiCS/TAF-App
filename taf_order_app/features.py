"""Which of these are switched on.

Thirty things were asked for at once. Turning them all on together would
change every screen in the building on one afternoon, and the first one that
got in somebody's way would get all thirty blamed for it. So each one arrives
off, and a Director or an Admin turns it on when the company is ready.

Two rules this file exists to hold.

A switch never grants anything. Every one of these is about whether a screen
is offered, never about who may read or write what - that is row-level
security in the database and it does not have an off switch. Turning a
feature on for the company does not turn any permission on for anybody.

And a switch is only ever offered for something that exists. A feature in the
list below with built=False is shown so people can see it is coming, and
cannot be flipped: a switch that does nothing is worse than no switch,
because somebody will turn it on, see no change, and stop trusting the rest.
"""
from __future__ import annotations

from typing import Any, Dict, List

from . import db as _db


class Feature:
    """One thing that can be switched on, and whether it exists yet."""

    __slots__ = ("key", "name", "blurb", "group", "built")

    def __init__(self, key: str, name: str, blurb: str, group: str,
                 built: bool = False):
        self.key = key
        self.name = name
        self.blurb = blurb
        self.group = group
        self.built = built


# ── The thirty ───────────────────────────────────────────────────────────────
# In the order they were asked for, grouped by the part of the day they touch.
# `built` is the honest column: it says whether there is anything behind the
# switch yet, and only the app changes it - never the database.

CATALOGUE: List[Feature] = [

    # ── Making it ────────────────────────────────────────────────────────
    Feature("channel_calculator", "Filter calculator",
            "Work out the three ways to make each filter - U, sideways U or "
            "G - and say which gets the most out of a length of channel.",
            "Making it", built=True),
    Feature("cut_list_day", "The day's cut list",
            "Every filter due, grouped by depth and nested across sticks, as "
            "a list to work down at the saw.",
            "Making it", built=True),
    Feature("offcut_register", "Offcut register",
            "What is left on the rack and how long, checked before a new "
            "stick is opened.",
            "Making it", built=True),
    Feature("media_nesting", "Media nesting",
            "The same maths for the media roll as for the channel: roll "
            "width against filter face.",
            "Making it", built=True),
    Feature("cutting_plan", "Cutting plan for the week",
            "The whole week's channel and media laid out together, rather "
            "than a day at a time.",
            "Making it"),
    Feature("show_alternative", "Show what it rejected",
            "\"U, 7 per stick - G would be 5\", so the person at the saw can "
            "overrule it knowing what they are overruling.",
            "Making it", built=True),
    Feature("near_standard", "Near a size we already make",
            "Flags a 597 x 497 as 2mm off a size you run constantly, while "
            "there is still time to ring and ask.",
            "Making it", built=True),
    Feature("cutlist_on_worksheet", "Cut list on the worksheet",
            "The marks printed on the worksheet that already goes out with "
            "the job.",
            "Making it"),
    Feature("saw_screen", "A screen at the saw",
            "Next cut, tick, next - feeding the line-by-line progress the "
            "app already keeps.",
            "Making it"),
    Feature("batch_by_material", "Batch by material",
            "A production view grouped by media and depth rather than by "
            "customer, in the order to work it.",
            "Making it", built=True),
    Feature("wip_board", "Work in progress board",
            "Cut, assembled, pleated, finished - so you can see where the "
            "jam is instead of hearing about it.",
            "Making it", built=True),
    Feature("kits", "Kits",
            "An AHU that takes four panels and two bags entered as one line "
            "rather than six.",
            "Making it"),

    # ── Knowing where you stand ──────────────────────────────────────────
    Feature("site_schedules", "Site filter schedules",
            "What is actually installed at each site, so a service visit "
            "writes its own order.",
            "Knowing where you stand"),
    Feature("capacity", "What you can promise",
            "What is already promised this week against what you normally "
            "get through, before you agree to Friday.",
            "Knowing where you stand", built=True),
    Feature("scrap_rate", "Scrap rate per job",
            "What percentage of the stick became filter. The only way to "
            "know the nesting is doing anything.",
            "Knowing where you stand", built=True),
    Feature("planned_vs_actual", "Planned against actual",
            "What the calculator said it would use, against what stock "
            "actually moved.",
            "Knowing where you stand"),
    Feature("month_end", "End of month, in one press",
            "Sales by customer, by month, by product type, against last "
            "year.",
            "Knowing where you stand", built=True),
    Feature("search_all", "One search box",
            "Type anything - a customer, an order number, a part number, a "
            "site - and get what matches.",
            "Knowing where you stand", built=True),

    # ── Money ────────────────────────────────────────────────────────────
    Feature("job_cost_actual", "What a job actually cost",
            "Media actually used against what was charged, not what was "
            "quoted.",
            "Money"),
    Feature("labour_margin", "Labour in the margin",
            "A U with a separate cap is more handling than a G. Puts that "
            "into the figure.",
            "Money"),
    Feature("customer_pricing", "Per-customer pricing",
            "An agreed rate or discount against a customer, applied without "
            "anybody remembering to.",
            "Money"),
    Feature("xero_live", "Xero, connected",
            "Push the invoice and get back whether it has been paid, instead "
            "of exporting a file.",
            "Money"),
    Feature("purchasing", "Buying, not just knowing",
            "Turn a low-stock list into a purchase order to the supplier, "
            "emailed, with the quantity marked as on order.",
            "Money"),

    # ── The floor ────────────────────────────────────────────────────────
    Feature("backorders", "Backorders and part-dispatch",
            "Twenty ordered, twelve made - send the twelve, keep the rest "
            "live, invoice what went.",
            "The floor"),
    Feature("stocktake", "Stocktake mode",
            "A counting session: what has been counted, what has not, and "
            "the variance at the end.",
            "The floor"),
    Feature("channel_in_sticks", "Channel counted in sticks",
            "Channel is n full lengths plus these offcuts, not a number of "
            "metres.",
            "The floor"),
    Feature("returns", "Returns and rework",
            "A filter that comes back, recorded against the order it came "
            "from.",
            "The floor"),
    Feature("frame_preference", "Per-customer frame preference",
            "Some customers always want a G. Store it and stop it being a "
            "question.",
            "The floor", built=True),

    # ── Admin ────────────────────────────────────────────────────────────
    Feature("email_orders", "Orders straight from email",
            "A forwarding address that reads an emailed purchase order the "
            "way the app already reads a photographed one.",
            "Admin"),
    Feature("shutdown_calendar", "Shutdown calendar",
            "Christmas, public holidays and supplier lead times, so a due "
            "date never lands on a Monday that does not exist.",
            "Admin"),
]

BY_KEY: Dict[str, Feature] = {f.key: f for f in CATALOGUE}

GROUPS: List[str] = []
for _f in CATALOGUE:
    if _f.group not in GROUPS:
        GROUPS.append(_f.group)


# ── What is on ───────────────────────────────────────────────────────────────

_switches: Dict[str, bool] = {}
_loaded = False


def _really_on(value: Any) -> bool:
    """Only an unambiguous yes counts as on.

    The same strict reading the customer-email switch gets, and for the same
    reason: bool("no") is True in Python, and a row edited by hand in
    Supabase must not be able to turn a screen on for the whole company by
    being the wrong shape.
    """
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "on", "1")
    return False


def load() -> Dict[str, bool]:
    """Read every switch once, at start-up, with the rest of the shared
    settings. Off on any failure: a database that will not answer is not
    permission to start showing people screens they have never seen."""
    global _switches, _loaded
    out: Dict[str, bool] = {}
    try:
        resp = (_db.get_client().table("feature_switches")
                .select("key,enabled").execute())
        for row in resp.data or []:
            out[str(row.get("key", ""))] = _really_on(row.get("enabled"))
    except Exception:
        out = {}
    _switches = out
    _loaded = True
    return dict(out)


def is_on(key: str) -> bool:
    """Is this feature switched on for the company?

    False for anything not in the catalogue and anything not built yet, so a
    stray row in the table cannot light up a screen that does not exist.
    """
    feature = BY_KEY.get(key)
    if feature is None or not feature.built:
        return False
    return bool(_switches.get(key, False))


def state() -> Dict[str, bool]:
    """Every catalogued feature and whether it is on, for the settings list."""
    return {f.key: is_on(f.key) for f in CATALOGUE}


def can_change() -> bool:
    """Directors and Admins. Not managers: this decides how everybody works.

    The database enforces it as well - this only decides whether the switch
    is offered, and a locked switch on a screen is a courtesy, never a
    control.
    """
    try:
        return _db.role_level() >= 4
    except Exception:
        return False


def set_on(key: str, enabled: bool) -> bool:
    """Turn one on or off for everyone. Returns what it is now."""
    feature = BY_KEY.get(key)
    if feature is None:
        raise ValueError(f"There is no feature called {key!r}.")
    if not feature.built:
        raise ValueError(f"{feature.name} is not built yet, so there is "
                         f"nothing to switch on.")
    resp = _db.get_client().rpc("set_feature",
                                {"p_key": key, "p_on": bool(enabled)}).execute()
    now = resp.data
    if isinstance(now, list):
        now = now[0] if now else None
    if isinstance(now, dict):
        now = now.get("set_feature")
    now = _really_on(now)
    _switches[key] = now
    return now


# ── The workshop's own numbers ───────────────────────────────────────────────
# What a length of channel comes in at, what the blade takes, and the shortest
# offcut worth keeping. Shared, because a cut list worked out on one PC has to
# match the one worked out on the next.

WORKSHOP_DEFAULTS: Dict[str, float] = {
    "stick_length_mm":   2440.0,
    "kerf_mm":              0.0,
    "keep_offcut_mm":     400.0,
    "lip_mm":              20.0,
    "min_lip_mm":          10.0,
    "side_allowance_mm":    2.0,
}

_workshop: Dict[str, float] = dict(WORKSHOP_DEFAULTS)


def load_workshop() -> Dict[str, float]:
    """Read the workshop's numbers, falling back to the defaults."""
    global _workshop
    out = dict(WORKSHOP_DEFAULTS)
    try:
        resp = (_db.get_client().table("workshop_settings")
                .select("key,value").execute())
        for row in resp.data or []:
            key = str(row.get("key", ""))
            if key in WORKSHOP_DEFAULTS:
                try:
                    out[key] = float(row.get("value"))
                except (TypeError, ValueError):
                    pass          # a nonsense row keeps the default
    except Exception:
        pass
    _workshop = out
    return dict(out)


def workshop() -> Dict[str, float]:
    return dict(_workshop)


def set_workshop(key: str, value: float) -> None:
    """Change one of the workshop's numbers for everyone. Managers and above."""
    if key not in WORKSHOP_DEFAULTS:
        raise ValueError(f"There is no workshop setting called {key!r}.")
    number = float(value)
    if number < 0:
        raise ValueError("That cannot be a negative measurement.")
    import datetime as _dt
    _db.get_client().table("workshop_settings").upsert({
        "key": key, "value": number,
        "updated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }).execute()
    _workshop[key] = number
