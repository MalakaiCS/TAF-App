"""No command prompt windows.

The app is a windowed program, but every console program it starts -
PowerShell to list printers, schtasks for an update, Word's PDF export - gets
a black command prompt window of its own on Windows unless told not to, and
it flashes up over whatever you were doing. Each call can say so; this makes
it the default for every one, including any added later, so one forgotten
flag cannot bring the flashing back.

Imported first, by the app's entry point. Does nothing off Windows.
"""
from __future__ import annotations

import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000


def install() -> bool:
    if sys.platform != "win32" or getattr(subprocess, "_taf_quiet", False):
        return False
    original = subprocess.Popen.__init__

    def __init__(self, *args, **kwargs):
        if not kwargs.get("creationflags"):
            kwargs["creationflags"] = CREATE_NO_WINDOW
        if kwargs.get("startupinfo") is None:
            info = subprocess.STARTUPINFO()
            info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            info.wShowWindow = 0                       # SW_HIDE
            kwargs["startupinfo"] = info
        original(self, *args, **kwargs)

    subprocess.Popen.__init__ = __init__
    subprocess._taf_quiet = True
    return True


install()
