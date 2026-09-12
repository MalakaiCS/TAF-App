"""Running on a Mac.

The app was written for Windows and it shows in small, specific ways - a
function that only exists there, an environment variable that is only set
there, a font that is only installed there. None of them announce themselves;
they each just stop working, usually in the middle of something.

These are about the ones that were found. A Mac build cannot be run here - it
has to be built on a Mac and opened by a person - so what these cover is
everything that can be checked without one: that nothing asks Windows for
something on a machine that is not Windows, that the release carries a file a
Mac can actually install, and that none of it changed what the factory's own
PCs do.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import paths as _paths        # noqa: E402
from taf_order_app import updater as _up         # noqa: E402

GUI = (ROOT / "modern_order_gui.py").read_text(encoding="utf-8")
SPEC = (ROOT / "TAFOrderEntry.spec").read_text(encoding="utf-8")
REQS = (ROOT / "requirements.txt").read_text(encoding="utf-8")
CI = (ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8")


# ── Where things are written ─────────────────────────────────────────────────

def test_windows_keeps_the_folder_it_already_has():
    """Every installed PC has orders, drafts and settings in %APPDATA%. Moving
    them somewhere tidier would lose somebody's work for nothing."""
    was_platform, was_appdata = sys.platform, os.environ.get("APPDATA")
    try:
        sys.platform = "win32"
        os.environ["APPDATA"] = r"C:\Users\Someone\AppData\Roaming"
        got = _paths.user_data_dir()
        assert str(got).endswith("TAF Order Entry")
        assert "Roaming" in str(got)
    finally:
        sys.platform = was_platform
        if was_appdata is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = was_appdata


def test_a_mac_uses_the_folder_a_mac_uses():
    """Not a folder called "TAF Order Entry" sitting in the home directory
    next to Documents, which is what falling back to $HOME gives you and what
    it looks like: something somebody left there."""
    was = sys.platform
    try:
        sys.platform = "darwin"
        got = _paths.user_data_dir()
        assert got.parent.name == "Application Support", got
        assert "Library" in str(got)
    finally:
        sys.platform = was


def test_nothing_relies_on_appdata_any_more():
    """It is unset on every machine that is not Windows, and the default
    everywhere it was used was silently wrong rather than loudly."""
    stragglers = []
    for name in ("modern_order_gui.py", "taf_order_app/order_service.py",
                 "taf_order_app/login_window.py", "taf_order_app/updater.py"):
        text = (ROOT / name).read_text(encoding="utf-8")
        if 'environ.get("APPDATA"' in text or "environ.get('APPDATA'" in text:
            stragglers.append(name)
    assert not stragglers, f"still reading APPDATA directly: {stragglers}"


# ── Opening a file ───────────────────────────────────────────────────────────

def test_only_one_place_calls_the_windows_opener():
    """os.startfile does not exist off Windows - not "returns False", it is
    not an attribute at all. Thirteen bare calls were thirteen ways to stop
    halfway through finishing an order."""
    hits = [ln for ln in GUI.split("\n") if "os.startfile(" in ln]
    assert len(hits) == 1, f"{len(hits)} calls, and only the helper may have one"
    assert "noqa: attr" in hits[0]


def test_the_opener_knows_all_three():
    body = GUI.split("def _open_path")[1].split("\n\n\n")[0]
    assert "os.startfile" in body
    assert '"open"' in body
    assert '"xdg-open"' in body


def test_it_lets_a_failure_out():
    """Several callers catch it and show the path in a message box instead,
    which is the right answer when nothing is associated with a .xlsx.
    Swallowing it here would turn that into nothing happening at all."""
    body = GUI.split("def _open_path")[1].split("\n\n\n")[0]
    assert "check=True" in body
    assert "except" not in body, "it is hiding the failure the callers need"


# ── Which file this machine can install ──────────────────────────────────────

MAC_RELEASE = ["TAFOrderEntry_Setup.exe",
               "TAFOrderEntry-2.23.0-Intel.dmg",
               "TAFOrderEntry-2.23.0-AppleSilicon.dmg"]


def _asset(platform_name: str, machine: str) -> str:
    was_platform = sys.platform
    was_machine = _up.platform.machine
    try:
        sys.platform = platform_name
        _up.platform.machine = lambda: machine
        return _up._wanted_asset(list(MAC_RELEASE))
    finally:
        sys.platform = was_platform
        _up.platform.machine = was_machine


def test_windows_gets_the_installer():
    assert _asset("win32", "AMD64") == "TAFOrderEntry_Setup.exe"


def test_an_m_series_mac_gets_the_m_series_build():
    """Handing it the Intel image is a download that ends in Rosetta being
    asked about, or nothing happening."""
    assert _asset("darwin", "arm64") == "TAFOrderEntry-2.23.0-AppleSilicon.dmg"


def test_an_intel_mac_gets_the_intel_build():
    assert _asset("darwin", "x86_64") == "TAFOrderEntry-2.23.0-Intel.dmg"


def test_a_mac_is_never_handed_the_exe():
    for machine in ("arm64", "x86_64"):
        assert not _asset("darwin", machine).endswith(".exe")


def test_an_older_release_with_one_image_still_works():
    """Releases already published have no .dmg at all, and the ones after
    that may have only one. Neither should make the app offer an .exe."""
    was_platform, was_machine = sys.platform, _up.platform.machine
    try:
        sys.platform = "darwin"
        _up.platform.machine = lambda: "arm64"
        assert _up._wanted_asset(["TAFOrderEntry_Setup.exe",
                                  "TAFOrderEntry-2.23.0.dmg"]) \
            == "TAFOrderEntry-2.23.0.dmg"
        assert _up._wanted_asset(["TAFOrderEntry_Setup.exe"]) == ""
    finally:
        sys.platform = was_platform
        _up.platform.machine = was_machine


def test_nothing_to_install_says_so_in_words_that_help():
    was = sys.platform
    try:
        sys.platform = "darwin"
        try:
            _up.download_and_install({"download_url": ""})
        except RuntimeError as exc:
            assert "Mac disk image" in str(exc)
        else:
            raise AssertionError("it carried on with no file to install")
    finally:
        sys.platform = was


def test_a_mac_is_not_told_to_run_an_installer_silently():
    """The Windows path hands off to Inno Setup and relaunches. A running .app
    cannot be swapped underneath itself, so the Mac path stops at opening the
    disk image and says what the last step is."""
    body = (ROOT / "taf_order_app/updater.py").read_text(encoding="utf-8")
    mac = body.split("def _install_mac")[1].split("\ndef ")[0]
    assert "powershell" not in mac.lower()
    assert "schtasks" not in mac.lower()
    assert "Applications" in mac, "nobody is told what to do with it"


def test_the_quarantine_flag_comes_off_the_download():
    """The app fetched its own next version. Leaving somebody to work out
    `xattr -cr` at a Terminal because of that is not an update."""
    body = (ROOT / "taf_order_app/updater.py").read_text(encoding="utf-8")
    mac = body.split("def _install_mac")[1].split("\ndef ")[0]
    assert "com.apple.quarantine" in mac


# ── What gets built ──────────────────────────────────────────────────────────

def test_pywin32_is_only_asked_for_on_windows():
    """There is no such package anywhere else. Unconditional, it fails the
    install before anything is built."""
    line = [ln for ln in REQS.split("\n") if ln.strip().startswith("pywin32")]
    assert line, "pywin32 has gone missing - Windows needs it"
    assert 'sys_platform == "win32"' in line[0], line[0]


def test_the_spec_does_not_name_pywin32_off_windows():
    assert "windows_imports = [" in SPEC
    assert "if WINDOWS else []" in SPEC
    block = SPEC.split("hiddenimports=[")[1].split("],")[0]
    assert "win32com" not in block, "a Windows-only import is unconditional again"


def test_the_printing_helper_is_not_bundled_into_a_mac_app():
    """SumatraPDF.exe is a Windows program. On a Mac the printing path is
    lpr, which is already there."""
    block = SPEC.split("pdf_helper_datas = ")[1].split("\n\n")[0]
    assert "WINDOWS and" in block


def test_upx_is_off_on_a_mac():
    """It rewrites the binaries, which breaks the ad-hoc signature every
    arm64 executable has to carry, and the app is then killed on launch
    rather than warned about."""
    assert "upx=True" not in SPEC, "UPX is unconditional again"
    assert SPEC.count("upx=WINDOWS") == 2


def test_there_is_something_to_drag_to_applications():
    assert "BUNDLE(" in SPEC
    assert "TAF Order Entry.app" in SPEC
    assert "bundle_identifier" in SPEC


def test_the_bundle_asks_for_a_retina_window():
    """Without it the whole window is drawn at half resolution and scaled up,
    which looks like a screenshot of itself."""
    assert re.search(r"'NSHighResolutionCapable':\s*True", SPEC)


def test_the_icon_starts_from_artwork_big_enough_to_be_one():
    """TAF_logo.ico holds a single 16x16 frame and a Dock icon is drawn at
    1024. Blown up from 16 it is a smear."""
    icon = (ROOT / "make_mac_icon.py").read_text(encoding="utf-8")
    assert "TAF_logo_circular.png" in icon
    assert "1024" in icon


def test_the_icon_is_cropped_before_it_is_squared():
    """The source is a wide canvas with the round logo in the middle. Squared
    without cropping, the icon is a small circle marooned in empty space."""
    from PIL import Image
    import make_mac_icon
    out = make_mac_icon.master(out=ROOT / "icon_master.png")
    img = Image.open(out)
    assert img.size == (1024, 1024)
    # The logo should fill most of its square, not float in the middle of it.
    box = img.getchannel("A").getbbox()
    assert box and (box[2] - box[0]) > 800, f"the artwork only covers {box}"


# ── The build itself ─────────────────────────────────────────────────────────

def test_both_kinds_of_mac_are_built():
    """Intel and Apple Silicon are different builds and neither runs the
    other's without Rosetta being involved."""
    runners = re.findall(r"- runner: (\S+)", CI)
    assert len(runners) == 2, runners
    assert any("intel" in r for r in runners), f"no Intel runner: {runners}"
    assert "Intel" in CI and "AppleSilicon" in CI


def test_the_build_does_not_ask_for_a_runner_that_no_longer_exists():
    """A retired label does not fail the job - it queues it forever. macos-13
    sat there while the Apple Silicon build finished in a minute, and the
    only sign was a job that never started."""
    runners = re.findall(r"- runner: (\S+)", CI)
    gone = [r for r in runners if r in ("macos-11", "macos-12", "macos-13",
                                        "macos-10.15")]
    assert not gone, f"retired runner labels: {gone}"


def test_the_mac_build_cannot_stop_the_windows_release():
    """The PCs on the factory floor auto-update. A Mac build breaking must
    never be the reason they do not."""
    mac = CI.split("\n  mac:")[1]
    assert "needs: release" in mac
    assert "fail-fast: false" in mac


def test_the_mac_build_uses_the_version_that_was_just_released():
    """The Windows job bumps the version and pushes it. Building off the
    branch as it was before that ships a .app that reports the old number and
    then offers itself an update forever."""
    mac = CI.split("\n  mac:")[1]
    assert "ref: ${{ needs.release.outputs.tag }}" in mac


def test_the_bundle_is_started_before_it_is_shipped():
    """PyInstaller's usual failure is a module that did not make it in, and
    that is invisible in a diff."""
    mac = CI.split("\n  mac:")[1]
    assert "--version" in mac
    assert "TAF Order Entry.app/Contents/MacOS/TAFOrderEntry" in mac


def test_asking_for_the_version_does_not_open_a_window():
    """Which is what makes the check above possible on a machine with nobody
    at it to close one."""
    body = GUI.split("def main():")[1]
    assert '"--version" in sys.argv' in body
    assert body.index("--version") < body.index("_start_app()")


def test_it_is_signed_so_it_can_run_at_all():
    """An unsigned binary on Apple Silicon is killed on launch, not warned
    about. Ad-hoc signing is the minimum that makes it start."""
    mac = CI.split("\n  mac:")[1]
    assert "codesign --force" in mac
    assert "codesign --verify" in mac, "signing that is never checked"


def test_the_disk_image_says_what_to_do_about_gatekeeper():
    """It is not signed by a registered developer, so the first open is
    blocked, and on Apple Silicon the message says "damaged" rather than
    anything about signing. Somebody has to be told that before they bin it."""
    mac = CI.split("\n  mac:")[1]
    assert "READ ME FIRST" in mac
    assert "xattr -cr" in mac
    assert "damaged" in mac


def test_there_is_an_applications_folder_to_drag_onto():
    mac = CI.split("\n  mac:")[1]
    assert "ln -s /Applications" in mac


def test_the_image_is_attached_to_the_same_release():
    """Two releases, one per platform, is how half the company ends up on a
    different version from the other half."""
    mac = CI.split("\n  mac:")[1]
    assert "gh release upload" in mac
    assert "needs.release.outputs.tag" in mac
