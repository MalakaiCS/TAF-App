"""
Run the tests with nothing installed but Python.

    python tests/run.py

pytest works too if you have it (`pytest tests`), but CI uses this so a
release can never be blocked on a test runner failing to install.
"""
from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODULES = ["tests.test_rules", "tests.test_db_and_updates", "tests.test_orders",
           "tests.test_invoicing_and_backup", "tests.test_scanning",
           "tests.test_migrations", "tests.test_quoting"]


def main() -> int:
    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    for name in MODULES:
        try:
            module = importlib.import_module(name)
        except Exception:
            failed.append((name, traceback.format_exc()))
            continue
        for attr in sorted(vars(module)):
            if not attr.startswith("test_"):
                continue
            func = getattr(module, attr)
            if not callable(func):
                continue
            label = f"{name.split('.')[-1]}.{attr}"
            try:
                func()
                passed.append(label)
            except Exception:
                failed.append((label, traceback.format_exc()))

    for label, tb in failed:
        print(f"\nFAIL  {label}\n{tb}")
    total = len(passed) + len(failed)
    print(f"\n{len(passed)}/{total} passed", end="")
    print(f", {len(failed)} FAILED" if failed else " — all good")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
