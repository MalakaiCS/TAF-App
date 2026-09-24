"""Getting the customer's screen onto the right monitor.

The first version guessed. Tk reports one desktop the width of every monitor
side by side, so "is there a second screen, and where" was worked out from how
wide that came out — fine on a PC with two identical screens in a row, wrong
on most other arrangements.

Wrong matters more here than it looks. The failure is not a window in an odd
place: it is the customer's quote opening on the screen the customer cannot
see, or straddling both, while they stand at the counter waiting. So each
platform is asked properly, the person picks from what was found, and the
last option on the list works whatever the detection did.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import monitors as _mon      # noqa: E402

GUI = (ROOT / "modern_order_gui.py").read_text(encoding="utf-8")

TWO_SCREENS = """Screen 0: minimum 320 x 200, current 3840 x 1080, maximum 16384 x 16384
eDP-1 connected primary 1920x1080+0+0 (normal left inverted) 344mm x 193mm
HDMI-1 connected 1920x1080+1920+0 (normal left inverted) 598mm x 336mm
DP-2 disconnected (normal left inverted)
DP-3 connected (normal left inverted) 0mm x 0mm
"""


# ── Reading what the machine says ────────────────────────────────────────────

def test_both_screens_are_found_with_their_positions():
    got = _mon.parse_xrandr(TWO_SCREENS)
    assert len(got) == 2, got
    assert got[0]["primary"] and got[0]["x"] == 0
    assert not got[1]["primary"] and got[1]["x"] == 1920


def test_a_screen_with_nowhere_to_put_a_window_is_not_offered():
    """Two ways a monitor appears in that list without being usable: nothing
    plugged in (DP-2), and plugged in with no mode set — switched off at the
    monitor, or never configured (DP-3). The second has the word "connected"
    on its line and no geometry at all, so a window sent there goes nowhere
    and the person who picked it thinks the feature is broken."""
    names = [m["name"] for m in _mon.parse_xrandr(TWO_SCREENS)]
    assert names == ["eDP-1", "HDMI-1"], names


def test_a_screen_to_the_left_is_described_as_being_to_the_left():
    """Not everybody puts the second monitor on the right, and "second
    screen" tells somebody with three of them nothing."""
    left = """eDP-1 connected primary 1920x1080+1920+0 (normal) 344mm x 193mm
HDMI-1 connected 1920x1080+0+0 (normal) 598mm x 336mm
"""
    got = _mon.parse_xrandr(left)
    other = [m for m in got if not m["primary"]][0]
    assert "left" in _mon.describe(other, got), _mon.describe(other, got)


def test_a_screen_above_is_not_called_a_screen_to_the_right():
    stacked = """eDP-1 connected primary 1920x1080+0+1080 (normal) 344mm x 193mm
HDMI-1 connected 1920x1080+0+0 (normal) 598mm x 336mm
"""
    got = _mon.parse_xrandr(stacked)
    other = [m for m in got if not m["primary"]][0]
    assert "above" in _mon.describe(other, got), _mon.describe(other, got)


def test_nonsense_from_the_machine_is_no_screens_not_a_crash():
    assert _mon.parse_xrandr("") == []
    assert _mon.parse_xrandr("total gibberish\nwith no geometry") == []


def test_the_mac_reports_its_displays():
    data = {"SPDisplaysDataType": [{"spdisplays_ndrvs": [
        {"_name": "Built-in Retina Display",
         "_spdisplays_resolution": "3024 x 1964",
         "spdisplays_main": "spdisplays_yes"},
        {"_name": "DELL U2419H", "_spdisplays_resolution": "1920 x 1080"},
    ]}]}
    got = _mon.parse_system_profiler(data)
    assert [m["name"] for m in got] == ["Built-in Retina Display", "DELL U2419H"]
    assert got[0]["primary"] and not got[1]["primary"]
    assert got[1]["x"] == 3024, "the second screen is on top of the first"


def test_a_mac_display_with_no_resolution_is_skipped():
    data = {"SPDisplaysDataType": [{"spdisplays_ndrvs": [
        {"_name": "Mystery", "spdisplays_main": "spdisplays_yes"}]}]}
    assert _mon.parse_system_profiler(data) == []


def test_an_empty_answer_is_no_screens():
    assert _mon.parse_system_profiler({}) == []
    assert _mon.parse_system_profiler(None) == []


# ── The guess, when nothing would answer ─────────────────────────────────────

def test_a_wide_desktop_still_implies_a_second_screen():
    """The old guess is kept as the last resort, not thrown away — on a PC
    where none of the proper routes work it is better than nothing."""
    got = _mon.from_tk(3840, 1080, 1920, 1080)
    assert len(got) == 2 and got[1]["x"] == 1920


def test_one_screen_is_not_reported_as_two():
    assert len(_mon.from_tk(1920, 1080, 1920, 1080)) == 1


def test_a_sliver_of_extra_width_is_not_a_monitor():
    """A desktop a few pixels wider than the main screen is a rounding
    difference or a taskbar, not somewhere to put a window."""
    assert len(_mon.from_tk(1960, 1080, 1920, 1080)) == 1


def test_asking_with_nothing_to_go_on_returns_nothing():
    """Rather than inventing a screen. The chooser then offers the window
    somebody drags, which works regardless."""
    assert _mon.list_monitors() == [] or _mon.list_monitors()


# ── Which one to suggest ─────────────────────────────────────────────────────

def test_the_one_other_screen_is_the_obvious_choice():
    got = _mon.parse_xrandr(TWO_SCREENS)
    assert _mon.second_screen(got)["name"] == "HDMI-1"


def test_with_three_screens_nothing_is_obvious():
    """Two candidates means asking, not picking. Guessing between them is
    how the quote ends up on the workshop monitor."""
    three = TWO_SCREENS + "DP-3 connected 1280x1024+3840+0 (normal) 1mm x 1mm\n"
    assert _mon.second_screen(_mon.parse_xrandr(three)) is None


def test_one_screen_alone_is_never_the_second_screen():
    only = _mon.parse_xrandr(
        "eDP-1 connected primary 1920x1080+0+0 (normal) 1mm x 1mm\n")
    assert _mon.second_screen(only) is None


# ── Landing the window on it ─────────────────────────────────────────────────

def test_the_geometry_lands_on_that_screen_not_the_first_one():
    mon = _mon.parse_xrandr(TWO_SCREENS)[1]
    assert _mon.geometry(mon, fill=True) == "1920x1080+1920+0"


def test_a_window_to_be_dragged_is_not_flush_into_the_corner():
    """With no title bar showing there is nothing to drag it by."""
    mon = _mon.parse_xrandr(TWO_SCREENS)[1]
    g = _mon.geometry(mon, fill=False)
    x, y = (int(n) for n in re.search(r"\+(\d+)\+(\d+)", g).groups())
    assert x > mon["x"] and y > mon["y"], g


def test_it_moves_before_it_fills():
    """Asking for full screen first fills whichever screen the window
    happens to be on, which is the one the customer cannot see."""
    fn = GUI.split("def put_on(self, monitor")[1].split("\n    def ")[0]
    assert fn.index("self.geometry") < fn.index("fullscreen(True)")


# ── What somebody is actually offered ────────────────────────────────────────

def test_the_button_says_what_it_does():
    assert "Enable Second Screen Display" in GUI


def test_the_button_says_how_to_turn_it_off_once_it_is_on():
    fn = GUI.split("def _set_counter_button")[1].split("\n    def ")[0]
    assert "Turn Off Second Screen" in fn


def test_it_asks_which_screen_rather_than_guessing():
    fn = GUI.split("def _toggle_counter_display")[1].split("\n    def ")[0]
    assert "ScreenChooser" in fn
    assert "to_second_screen" not in fn, "the old guess is still in the path"


def test_there_is_always_an_option_that_works():
    """However the detection went. A dialog whose every option depends on
    detection having worked is a dead end on the PC where it did not."""
    cls = GUI.split("class ScreenChooser")[1].split("\nclass ")[0]
    assert 'value="window"' in cls
    assert "drag it where it goes" in cls


def test_a_screen_plugged_in_after_the_dialog_opened_can_be_found():
    """The likeliest moment to discover the monitor is off is when this
    dialog says there is only one. Making somebody close it, plug the cable
    in and start again is a dialog that does not know what it is for."""
    cls = GUI.split("class ScreenChooser")[1].split("\nclass ")[0]
    assert "Refresh" in cls
    fn = GUI.split("def _toggle_counter_display")[1].split("\n    def ")[0]
    assert "refresh" in fn and "continue" in fn


def test_cancelling_opens_nothing():
    fn = GUI.split("def _toggle_counter_display")[1].split("\n    def ")[0]
    cancel = fn.split("if not dlg.result:")[1].split("\n")[1]
    assert cancel.strip().startswith("return"), cancel


def test_the_choice_is_remembered():
    """The counter PC has the same two screens tomorrow. Asking every time
    is a dialog between a customer and their quote, every time."""
    fn = GUI.split("def _toggle_counter_display")[1].split("\n    def ")[0]
    assert '_settings["counter_screen"]' in fn
    assert "_save_settings" in fn
    cls = GUI.split("class ScreenChooser")[1].split("\nclass ")[0]
    assert "remembered" in cls, "it is saved but never used again"


def test_it_can_be_found_in_the_menu_with_everything_else_new():
    """It was reachable only from a button on one tab, which is why nobody
    found it."""
    menu = GUI.split("FEATURE_SCREENS = [")[1].split("\n    ]")[0]
    assert '"customer_display"' in menu
    assert "_customer_screen_from_menu" in menu


def test_the_menu_route_opens_the_tab_it_belongs_to():
    """Otherwise the screen turns on and the quote it is showing is on a tab
    nobody is looking at."""
    fn = GUI.split("def _customer_screen_from_menu")[1].split("\n    def ")[0]
    assert '_show_tab("quotes")' in fn
