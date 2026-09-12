"""Where this app is allowed to write.

The program used to say `%APPDATA%\\TAF Order Entry` in four separate places,
which was fine while Windows was the only thing it ran on. It is not any more,
and `%APPDATA%` is unset everywhere else - so all four quietly fell back to
dropping a folder called "TAF Order Entry" in somebody's home directory, next
to Documents and Downloads, where it looks like something they left there.

One answer, in one place:

    Windows   %APPDATA%\\TAF Order Entry
    macOS     ~/Library/Application Support/TAF Order Entry
    Linux     ~/.local/share/TAF Order Entry   (or $XDG_DATA_HOME)

Windows is unchanged on purpose. Every installed PC already has orders,
drafts and settings sitting in that folder, and moving them to be tidy would
lose somebody's work for no gain at all.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_FOLDER = "TAF Order Entry"


def user_data_dir(create: bool = False) -> Path:
    """The one writable folder this app owns on this machine."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home())
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    path = base / APP_FOLDER
    if create:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except Exception:
            # A read-only home, or a network profile that is not there yet.
            # The caller gets a path that does not exist rather than a crash
            # at import time, which would stop the app opening at all.
            pass
    return path
