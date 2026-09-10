"""The web app with no signal, and the phone as a scanner.

The browser test drives all of this for real, but it only runs where there is
a Chromium to drive. These are the rules that are worth holding on every
machine, because getting any of them wrong is quiet: nothing throws, nothing
looks broken, and somebody finds out a week later that a stock count went in
twice or that half the app does not open at the back of the factory.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "docs" / "app"


def _read(*parts) -> str:
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def _sw() -> str:
    return _read("docs", "sw.js")


def _screens() -> str:
    return _read("docs", "app", "screens.js")


# ── What the worker keeps ───────────────────────────────────────────────────

def test_the_worker_never_answers_for_another_origin():
    """Supabase must fall straight through to the network. A cached answer
    from the database is a stale answer wearing a fresh one's clothes: an
    hour-old stock figure looks exactly like this minute's and is not."""
    body = _sw().split("addEventListener(\"fetch\"", 1)[1]
    guard = body.split("respondWith", 1)[0]
    assert "url.origin !== self.location.origin" in guard, \
        "the fetch handler answers before checking the origin"


def test_the_worker_only_answers_for_what_it_put_there():
    """It sits at the top of the site so company.js is inside its scope,
    which also puts the customer portal inside its scope. Those pages must
    carry on being served by GitHub Pages, untouched."""
    sw = _sw()
    assert "MINE.indexOf(path) === -1" in sw, \
        "the worker does not check the request against its own list"


def test_every_script_the_page_loads_is_one_the_worker_keeps():
    """A script added to the page and forgotten here is the worst kind of
    half-working: online it is fine, and offline the app loads to a blank
    screen with one file missing."""
    page = _read("docs", "app", "index.html")
    srcs = re.findall(r'<script src="([^"]+)"', page)
    sw = _sw()
    missing = []
    for src in srcs:
        name = src.split("/")[-1]
        if name == "config.js":
            continue          # deliberately network-first, see below
        wanted = ("app/" + name) if not src.startswith("..") else name
        if f'"{wanted}"' not in sw:
            missing.append(src)
    assert not missing, f"the worker does not keep: {missing}"


def test_the_home_screen_icon_is_there_with_no_signal():
    """Added to a home screen the app opens without a browser's address bar,
    which is the difference between a tool and a tab somebody closes. A
    manifest icon that only exists online is a broken square on the phone."""
    import json

    manifest = APP / "manifest.webmanifest"
    assert manifest.exists(), "there is no web app manifest"
    spec = json.loads(manifest.read_text(encoding="utf-8"))
    assert spec.get("display") == "standalone"
    sw = _sw()
    assert '"app/manifest.webmanifest"' in sw
    for icon in spec.get("icons", []):
        src = icon["src"]
        assert (APP / src).exists(), f"the manifest names {src}, which is not there"
        assert f'"app/{src}"' in sw, f"{src} is not kept for offline"


def test_the_key_is_fetched_fresh_rather_than_kept():
    """If the publishable key is ever rotated, a cached copy leaves every
    phone in the company holding an app that looks fine and cannot sign in."""
    sw = _sw()
    assert 'var CONFIG = "app/config.js"' in sw
    body = sw.split("addEventListener(\"fetch\"", 1)[1]
    assert "freshFirst(req)" in body, "config.js is not asked for fresh"
    assert body.index("freshFirst(req)") < body.index("cachedFirst(req)"), \
        "the general rule catches config.js before the rule for config.js"


def test_the_worker_is_not_registered_from_a_file_url():
    """Opened straight off disk there is no origin to scope one to, and
    calling register() there throws in the console for no reason."""
    page = _read("docs", "app", "index.html")
    assert 'location.protocol !== "file:"' in page


# ── What goes in the queue ──────────────────────────────────────────────────

# The three things the app writes out of signal. Every one of them has to be
# safe to send twice, because a phone can send a write, lose the signal
# before the answer arrives, and send it again.
#
#   set_order_line_made  sets a line to made. Twice is the same as once.
#   merge_order_header   merges a patch into the header. Same.
#   adjust_stock_atomic  is NOT, on its own - it moves a figure. It is safe
#                        only because of the client reference, which is why
#                        the test below insists on one.
REPEATABLE = {"set_order_line_made", "merge_order_header",
              "adjust_stock_atomic"}


def _queued_calls() -> list:
    """Every TAFSYNC.send({...}) in the app, as its text."""
    src = _screens()
    out = []
    for m in re.finditer(r"S\.send\(\{", src):
        depth, i = 0, m.end() - 1
        while i < len(src):
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
                if depth == 0:
                    out.append(src[m.start():i + 1])
                    break
            i += 1
    return out


def test_the_app_actually_queues_its_writes():
    calls = _queued_calls()
    assert len(calls) >= 3, f"only {len(calls)} writes go through the queue"


def test_nothing_goes_in_the_queue_that_cannot_be_sent_twice():
    for call in _queued_calls():
        name = re.search(r'rpc:\s*"([^"]+)"', call)
        assert name, f"a queued write with no function name:\n{call}"
        assert name.group(1) in REPEATABLE, (
            f"{name.group(1)} is queued but is not known to be safe to send "
            "twice. Either it is, and belongs in REPEATABLE with the reason "
            "written down, or it must not be queued.")


def test_a_queued_stock_movement_always_carries_a_reference():
    """It is the only thing keeping a replayed count from being counted
    twice - adjust_stock_atomic checks it while holding the row lock."""
    for call in _queued_calls():
        if "adjust_stock_atomic" in call:
            assert "p_client_ref" in call, \
                "a stock movement is queued without a client reference"
            return
    raise AssertionError("stock adjustments no longer go through the queue")


def test_a_write_whose_row_vanished_is_reported_rather_than_counted():
    """set_order_line_made answers with the order's id only when the line was
    actually found. Sent from a queue days later, nothing coming back means
    the line is gone - and silently calling that 'sent' would leave somebody
    certain they had ticked something they had not."""
    for call in _queued_calls():
        if "set_order_line_made" in call or "merge_order_header" in call:
            assert "needs_row: true" in call, \
                f"a queued write that can silently change nothing:\n{call}"


def test_the_queue_is_capped():
    src = _read("docs", "app", "offline.js")
    assert re.search(r"LIMIT\s*=\s*\d+", src), "the outbox has no ceiling"
    assert "already waiting" in src, \
        "hitting the ceiling has to say so, not fail quietly"


def test_the_queue_sends_in_the_order_things_happened():
    """A tick and the untick that followed it arriving the wrong way round
    leaves the order saying the opposite of what happened."""
    src = _read("docs", "app", "offline.js")
    assert "if (!online() || pending())" in src, \
        "a new write can overtake one that is already waiting"


def test_no_signal_and_refused_are_told_apart():
    """One is worth keeping and sending later. The other has to be shown to
    somebody now, and retrying it forever would wedge everything behind it."""
    data = _read("docs", "app", "data.js")
    assert "err.offline = true" in data
    assert "err.signedOut = true" in data
    box = _read("docs", "app", "offline.js")
    assert "err.offline || err.signedOut" in box, \
        "the flush does not hold on to work it could still send"


def test_a_dropout_does_not_sign_anybody_out():
    """Throwing the session away because the wifi went would put somebody at
    the back of the factory on a login screen they cannot get past, with
    unsent work sitting on the phone."""
    data = _read("docs", "app", "data.js")
    guard = data.split("refreshing = fetch", 1)[1]
    assert "if (!err || !err.offline) { remember(null); }" in guard


def test_signing_out_does_not_hand_on_somebody_elses_work():
    """The next person to sign in on a shared phone must not send the last
    person's ticks under their own account."""
    src = _screens()
    assert "if (S.pending()) { leaving(); return; }" in src


# ── Scanning ────────────────────────────────────────────────────────────────

def test_a_code_is_resolved_by_the_database_not_by_the_page():
    """One place decides what a code means, so the handheld, this page and
    the desktop can never disagree about which order PO-8842 is."""
    src = _screens()
    assert 'D.rpc("resolve_scan"' in src


def test_the_camera_is_put_down_when_it_is_not_being_used():
    src = _screens()
    assert "t.stop()" in src, "the camera stream is never stopped"
    assert 'active === "scan" && key !== "scan"' in src, \
        "leaving the tab leaves the camera running"


def test_one_label_is_not_thirty_lookups():
    """A camera sees the same barcode every frame."""
    src = _screens()
    assert "SCAN.last" in src and "SCAN.at" in src, \
        "nothing stops one label becoming a lookup per frame"


def test_there_is_a_way_in_without_a_camera():
    """Every iPhone today has no BarcodeDetector, and a handheld scanner in
    keyboard mode types into a text box anyway."""
    src = _screens()
    assert "cannot read a barcode through the" in src
    assert 'cls: "code"' in src, "there is no box to type or scan a code into"


if __name__ == "__main__":
    # Also runnable on its own, because a change to docs/ never reaches the
    # Windows build where the rest of the suite runs.
    import sys

    bad = []
    for name in sorted(n for n in dir() if n.startswith("test_")):
        try:
            globals()[name]()
            print(f"  PASS  {name}")
        except AssertionError as exc:
            print(f"  FAIL  {name}\n        {exc}")
            bad.append(name)
    print(f"\n{len(bad)} FAILED" if bad else "\nOffline rules hold.")
    sys.exit(1 if bad else 0)
