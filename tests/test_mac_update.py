"""The Mac update: swapped in place after the app quits, then reopened -
and a failure leaves the old version working."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import updater as u                       # noqa: E402

# Stand-ins for the Mac-only tools, so the script runs on any build machine.
STANDINS = (("/usr/bin/ditto", "cp -R"), ("/usr/bin/xattr", "true"),
            ("/usr/bin/hdiutil", "true"), ("/usr/bin/open", "echo OPENED"),
            (" open ", " echo OPENED "))


def _sandbox(pid=999999, ditto=None):
    sp = Path(tempfile.mkdtemp())
    for folder, text in (("Apps", "old"), ("vol", "new")):
        app = sp / folder / "TAF Order Entry.app" / "Contents"
        app.mkdir(parents=True)
        (app / "v").write_text(text)
    script = u.mac_swap_script(sp / "vol/TAF Order Entry.app",
                               sp / "Apps/TAF Order Entry.app", sp / "vol",
                               sp / "x.dmg", pid, sp / "update.log")
    for a, b in STANDINS:
        script = script.replace(a, b)
    if ditto:
        script = script.replace("cp -R", ditto)
    (sp / "s.sh").write_text(script)
    return sp


def _version(sp):
    return (sp / "Apps/TAF Order Entry.app/Contents/v").read_text()


def test_the_script_is_valid_shell_even_with_quotes_in_a_path():
    script = u.mac_swap_script(Path("/Applications/Kai's TAF.app"),
                               Path("/Applications/TAF Order Entry.app"),
                               Path("/tmp/v"), Path("/tmp/x.dmg"), 1,
                               Path("/tmp/l"))
    path = Path(tempfile.mkdtemp()) / "s.sh"
    path.write_text(script)
    assert subprocess.run(["bash", "-n", str(path)]).returncode == 0


def test_the_new_version_replaces_the_old_and_reopens():
    sp = _sandbox()
    out = subprocess.run(["bash", str(sp / "s.sh")], timeout=30)
    assert out.returncode == 0 and _version(sp) == "new"
    assert sorted(p.name for p in (sp / "Apps").iterdir()) == \
        ["TAF Order Entry.app"]
    log = (sp / "update.log").read_text()
    assert "installed - reopening" in log
    assert "OPENED" in log and "Apps/TAF Order Entry.app" in log


def test_a_failed_copy_leaves_the_old_version_working():
    sp = _sandbox(ditto="false")
    out = subprocess.run(["bash", str(sp / "s.sh")], timeout=30)
    assert out.returncode == 1 and _version(sp) == "old"
    assert sorted(p.name for p in (sp / "Apps").iterdir()) == \
        ["TAF Order Entry.app"]
    assert "FAILED: copying the new version" in \
        (sp / "update.log").read_text()


def test_it_waits_for_the_app_to_quit_first():
    import threading
    app = subprocess.Popen(["sleep", "2"])
    # Reaped as soon as it ends, as macOS does for a quitting app; an
    # unreaped child still answers kill -0.
    threading.Thread(target=app.wait, daemon=True).start()
    sp = _sandbox(pid=app.pid)
    start = time.monotonic()
    subprocess.run(["bash", str(sp / "s.sh")], timeout=30)
    assert time.monotonic() - start >= 1.5 and _version(sp) == "new"


def test_where_the_new_version_goes():
    exe = "/Applications/TAF Order Entry.app/Contents/MacOS/TAFOrderEntry"
    bundle = u.current_bundle(exe)
    assert bundle == Path("/Applications/TAF Order Entry.app")
    assert u.install_target(bundle) == bundle
    # Run from the disk image, or translocated out of Downloads: Applications.
    for odd in ("/Volumes/TAF Order Entry/TAF Order Entry.app",
                "/private/var/folders/x/AppTranslocation/ABC/d/"
                "TAF Order Entry.app"):
        assert u.install_target(Path(odd)) == \
            Path("/Applications/TAF Order Entry.app")
    assert u.install_target(None) == Path("/Applications/TAF Order Entry.app")
    home = "/Users/kai/Applications/TAF Order Entry.app"
    assert u.install_target(Path(home)) == Path(home)


def test_https_uses_certifi_as_well_as_the_system():
    """A packaged Mac app has no system certificates where OpenSSL looks;
    without certifi every update check failed CERTIFICATE_VERIFY_FAILED."""
    import ssl
    from taf_order_app import tls
    assert ssl._create_default_https_context is tls.context
    import certifi
    ctx = tls.context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.cert_store_stats()["x509_ca"] > 0
    assert certifi.where()
