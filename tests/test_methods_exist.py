"""Every method the app calls on itself is one that was actually written.

v2.27.0 shipped with the Quotes tab calling self._price_data(), which never
existed - the method is _load_prices. Python only finds out when the line
runs, and that line only ran for a manager with something on the quote, so it
went out and reached the counter as an "Unexpected Error" box. The same scan
turned up a button that called self._show_po_inbox() behind a hasattr() and
so, instead of crashing, quietly did nothing at all.

The smoke test builds every screen but cannot press every button with every
kind of data behind it. This reads the source instead, so a name with nothing
behind it is caught however deep in a branch it sits.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SOURCES = [ROOT / "modern_order_gui.py", ROOT / "pdf_generator.py",
           ROOT / "template_filler.py",
           *sorted((ROOT / "taf_order_app").glob("*.py"))]


def _missing(src: str) -> list:
    """self._name(...) calls with no def _name and no self._name = ..."""
    called = set(re.findall(r"self\.(_[A-Za-z0-9_]+)\s*\(", src))
    defined = set(re.findall(r"def (_[A-Za-z0-9_]+)\s*\(", src))
    assigned = set(re.findall(r"self\.(_[A-Za-z0-9_]+)\s*=", src))
    assigned |= set(re.findall(r"^\s+(_[A-Za-z0-9_]+)\s*=", src, re.M))
    return sorted(called - defined - assigned)


def test_every_private_method_called_exists():
    bad = {}
    for path in SOURCES:
        if path.exists():
            gone = _missing(path.read_text(encoding="utf-8"))
            if gone:
                bad[path.name] = gone
    assert not bad, f"called but never written: {bad}"


def test_the_scan_would_have_caught_the_quotes_crash():
    """Held against the exact line that shipped, so the scan cannot be
    loosened into something that no longer sees it."""
    shipped = ("    def _load_prices(self, force=False):\n        pass\n\n"
               "    def _cost_data(self, force: bool = False):\n"
               "        self._price_data(force=force)\n")
    assert _missing(shipped) == ["_price_data"]


def test_a_button_is_not_quietly_switched_off_by_hasattr():
    """hasattr(self, "_something") around a call turns a missing method from
    a crash into a button that does nothing, which is harder to notice."""
    src = (ROOT / "modern_order_gui.py").read_text(encoding="utf-8")
    guarded = re.findall(r'hasattr\(self, "(_[A-Za-z0-9_]+)"\)', src)
    defined = set(re.findall(r"def (_[A-Za-z0-9_]+)\s*\(", src))
    defined |= set(re.findall(r"self\.(_[A-Za-z0-9_]+)\s*=", src))
    never = sorted(set(n for n in guarded
                       if n not in defined and f"self.{n}(" in src))
    assert not never, f"called behind hasattr but never written: {never}"
