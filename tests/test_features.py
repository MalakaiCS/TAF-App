"""Which features are switched on, and who gets to decide.

Thirty things were asked for at once. The switchboard is what stops that
landing on the factory in one afternoon - but a switchboard has two ways of
going quietly wrong, and these are about both.

A switch that grants something. Every one of these decides whether a screen
is offered, never who may read or write what. If turning a feature on ever
turns a permission on, the switchboard has become a way around row-level
security and the whole shape of the app is wrong.

And a switch with nothing behind it. Somebody turns it on, sees no change,
and stops believing the other twenty-nine.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import db as _db              # noqa: E402
from taf_order_app import features as _feat      # noqa: E402

SQL = (ROOT / "migrate_features.sql").read_text(encoding="utf-8")


# ── The catalogue ────────────────────────────────────────────────────────────

def test_all_thirty_are_there():
    assert len(_feat.CATALOGUE) == 30, \
        f"{len(_feat.CATALOGUE)} features, not the thirty that were asked for"


def test_no_two_share_a_key():
    keys = [f.key for f in _feat.CATALOGUE]
    assert len(keys) == len(set(keys)), \
        f"duplicated: {sorted(k for k in keys if keys.count(k) > 1)}"


def test_every_one_says_what_it_does():
    for f in _feat.CATALOGUE:
        assert f.name and f.blurb and f.group, f.key
        assert len(f.blurb) > 30, f"{f.key}: nobody can decide from that"


def test_a_key_is_a_key_not_a_sentence():
    for f in _feat.CATALOGUE:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", f.key), f.key


# ── Off until somebody says otherwise ────────────────────────────────────────

def test_nothing_is_on_by_default():
    _feat._switches = {}
    assert not any(_feat.state().values()), \
        "something is on before anybody turned it on"


def test_a_switch_with_nothing_behind_it_cannot_be_flipped():
    """All thirty are built today, so this stands one of them down for the
    length of the test. The rule has to survive the next thing anybody adds
    to the catalogue, not only the state the catalogue happens to be in."""
    victim = _feat.CATALOGUE[0]
    was = victim.built
    victim.built = False
    try:
        _feat.set_on(victim.key, True)
    except ValueError as exc:
        assert "not built" in str(exc)
    else:
        raise AssertionError("it switched on something that does not exist")
    finally:
        victim.built = was


def test_an_unbuilt_feature_reads_as_off_even_with_a_row_saying_yes():
    """A stray row in the table must not light up a screen that is not
    there. The app decides what exists, never the database."""
    victim = _feat.CATALOGUE[0]
    was = victim.built
    victim.built = False
    _feat._switches = {victim.key: True}
    try:
        assert _feat.is_on(victim.key) is False
    finally:
        victim.built = was
        _feat._switches = {}


def test_a_key_nobody_has_heard_of_is_off():
    _feat._switches = {"rm_-rf": True}
    assert _feat.is_on("rm_-rf") is False
    _feat._switches = {}


def test_anything_that_is_not_a_clear_yes_is_off():
    """bool("no") is True in Python. A row edited by hand in Supabase must
    not be able to turn a screen on for the whole company by being the wrong
    shape."""
    built = [f for f in _feat.CATALOGUE if f.built][0]
    for value in ("", "no", None, 0, "false", "FALSE", [], {}):
        _feat._switches = {built.key: _feat._really_on(value)}
        assert _feat.is_on(built.key) is False, value
    for value in (True, "true", "Yes", "on", "1"):
        _feat._switches = {built.key: _feat._really_on(value)}
        assert _feat.is_on(built.key) is True, value
    _feat._switches = {}


def test_a_database_that_will_not_answer_leaves_everything_off():
    """Not permission to start showing people screens they have never seen."""
    def boom():
        raise RuntimeError("no connection")
    _db.get_client = boom
    assert _feat.load() == {}
    assert not any(_feat.state().values())


# ── Who decides ──────────────────────────────────────────────────────────────

def test_only_a_director_or_an_admin_can_change_one():
    """Not a manager. This decides how everybody works, which is a different
    kind of decision from the ones a manager makes day to day."""
    for role, allowed in (("Director", True), ("Admin", True),
                          ("Manager", False), ("Employee", False)):
        _db.role_level = lambda r=role: _db.ROLE_LEVEL.get(r, 1)
        assert _feat.can_change() is allowed, role


def test_the_database_says_the_same_thing():
    """The screen hiding a switch is a courtesy. This is the control."""
    assert "role IN ('Director', 'Admin')" in SQL
    for policy in ("Admins add feature switches",
                   "Admins change feature switches",
                   "Admins remove feature switches"):
        block = SQL.split(f'CREATE POLICY "{policy}"')[1].split(";")[0]
        assert "public.is_admin()" in block, policy
        assert "is_manager" not in block, f"{policy} lets a manager in"


def test_everyone_can_read_which_are_on():
    """The app has to know which screens to draw, and hiding the list from
    the people it affects buys nothing."""
    block = SQL.split('CREATE POLICY "Staff read feature switches"')[1].split(";")[0]
    assert "public.is_staff()" in block


def test_the_helper_cannot_be_used_as_the_guard():
    """set_feature is a convenience. A guard living inside the function is
    walked around by writing to the table directly."""
    body = SQL.split("CREATE OR REPLACE FUNCTION public.set_feature")[1]
    assert "SECURITY INVOKER" in body.split("AS $$")[0]
    assert "SECURITY DEFINER" not in body.split("AS $$")[0]


def test_is_admin_is_definer_with_a_pinned_path():
    """It reads profiles regardless of the policies on profiles, so nothing
    may be shadowed out from under it."""
    body = SQL.split("CREATE OR REPLACE FUNCTION public.is_admin")[1].split("$$")[0]
    assert "SECURITY DEFINER" in body
    assert "SET search_path = public, pg_temp" in body


def test_the_switches_are_shared_not_per_pc():
    """One machine showing a screen the others do not is how two people end
    up doing the same job two different ways."""
    assert "CREATE TABLE IF NOT EXISTS public.feature_switches" in SQL
    assert "key        text PRIMARY KEY" in SQL


# ── The workshop's numbers ───────────────────────────────────────────────────

def test_the_workshop_numbers_have_sane_defaults():
    assert _feat.WORKSHOP_DEFAULTS["stick_length_mm"] == 2440
    assert _feat.WORKSHOP_DEFAULTS["keep_offcut_mm"] == 400
    assert _feat.WORKSHOP_DEFAULTS["lip_mm"] == 20
    assert _feat.WORKSHOP_DEFAULTS["side_allowance_mm"] == 2


def test_the_calculator_and_the_settings_agree_on_the_defaults():
    """Two sets of defaults drifting apart would have the calculator working
    to numbers nobody can see on any screen."""
    from taf_order_app import cutting as _cut
    assert _cut.DEFAULTS == _feat.WORKSHOP_DEFAULTS


def test_a_measurement_cannot_be_negative():
    try:
        _feat.set_workshop("kerf_mm", -1)
    except ValueError as exc:
        assert "negative" in str(exc)
    else:
        raise AssertionError("it accepted a negative blade")


def test_a_setting_nobody_has_heard_of_is_refused():
    try:
        _feat.set_workshop("free_money", 10)
    except ValueError as exc:
        assert "no workshop setting" in str(exc)
    else:
        raise AssertionError("it wrote a setting that means nothing")


def test_a_manager_can_change_the_blade_without_finding_a_director():
    """The blade gets changed and the supplier's stick length changes, and
    neither should wait for a director to be in the building."""
    for policy in ("Managers add workshop settings",
                   "Managers set workshop settings"):
        block = SQL.split(f'CREATE POLICY "{policy}"')[1].split(";")[0]
        assert "public.is_manager()" in block, policy


def test_re_running_never_overwrites_what_the_workshop_set():
    """Somebody measures the kerf properly, then the migration is re-run and
    puts 3mm back. Every cut list after that is quietly wrong."""
    seed = SQL.split("INSERT INTO public.workshop_settings")[1]
    assert "ON CONFLICT (key) DO NOTHING" in seed


# ── The offcut rack ──────────────────────────────────────────────────────────

def test_anyone_at_the_saw_can_write_an_offcut_down():
    """The moment to do it is the moment it comes off the stick. Making that
    a manager's job is how it stops happening, and then the same channel gets
    bought twice."""
    block = SQL.split('CREATE POLICY "Staff add offcuts"')[1].split(";")[0]
    assert "public.is_staff()" in block
    assert "is_manager" not in block


def test_a_used_offcut_is_marked_not_deleted():
    """"Where did that 1300 go" is a question somebody asks, and a row that
    vanished cannot answer it."""
    assert "used       boolean" in SQL
    assert "used_by    text" in SQL
    block = SQL.split('CREATE POLICY "Managers bin offcuts"')[1].split(";")[0]
    assert "public.is_manager()" in block, \
        "anyone can delete the record of a piece of channel"


def test_an_offcut_cannot_be_no_length_at_all():
    assert "CHECK (length_mm > 0)" in SQL


# ── Which way a customer wants them ──────────────────────────────────────────

def test_a_customer_with_no_preference_gets_whichever_is_cheapest():
    assert "frame_preference text NOT NULL DEFAULT ''" in SQL


def test_only_a_real_way_of_making_one_can_be_stored():
    from taf_order_app import db as _real_db
    try:
        _real_db.set_frame_preference("c1", "sideways")
    except ValueError as exc:
        assert "not a way of making a filter" in str(exc)
    else:
        raise AssertionError("it stored a method that does not exist")


# ── What the menu offers ─────────────────────────────────────────────────────

def test_every_screen_in_the_menu_belongs_to_a_real_feature():
    """A menu entry keyed to a feature that does not exist would be an entry
    nobody can ever switch on."""
    import re as _re
    src = (ROOT / "modern_order_gui.py").read_text(encoding="utf-8")
    block = src.split("FEATURE_SCREENS = [")[1].split("]")[0]
    for key, method in _re.findall(r'\("([a-z_]+)",\s*"[^"]*",\s*"(_[a-z_]+)"',
                                   block):
        assert key in _feat.BY_KEY, f"the menu offers {key}, which is not a feature"
        assert _feat.BY_KEY[key].built, f"{key} is in the menu but not built"
        assert f"def {method}(self" in src, f"{method} is in the menu and missing"



def test_all_thirty_are_actually_built():
    """The thing that was asked for: thirty features, every one of them with
    something behind its switch."""
    missing = [f.key for f in _feat.CATALOGUE if not f.built]
    assert not missing, f"still to build: {missing}"


def test_every_built_feature_is_reachable():
    """A feature switched on that appears nowhere is a switch that does
    nothing, which is the thing the catalogue exists to prevent. Either it
    has a screen in the menu, or the app reads its switch somewhere."""
    src = (ROOT / "modern_order_gui.py").read_text(encoding="utf-8")
    others = "\n".join(
        (ROOT / name).read_text(encoding="utf-8")
        for name in ("taf_order_app/order_service.py",
                     "taf_order_app/features.py", "docs/app/screens.js"))
    menu = src.split("FEATURE_SCREENS = [")[1].split("\n    ]")[0]
    for f in _feat.CATALOGUE:
        if not f.built:
            continue
        assert (f'"{f.key}"' in menu
                or f'is_on("{f.key}")' in src
                or f'is_on("{f.key}")' in others), \
            f"{f.key} is built but nothing ever looks at its switch"