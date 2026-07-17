"""
Auto-update support for TAF Order App.

Check:   check_for_update()  → dict or None
Install: download_and_install(info, progress_cb)
"""
from __future__ import annotations
import os, sys, subprocess, tempfile, threading
from pathlib import Path

APP_VERSION = "2.0.0"


def _parse_version(v: str) -> tuple:
    try:
        return tuple(int(x) for x in str(v).strip().split("."))
    except Exception:
        return (0,)


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    return _parse_version(remote) > _parse_version(local)


def check_for_update() -> dict | None:
    """
    Returns {"version": str, "download_url": str, "release_notes": str}
    if a newer version is available, else None.
    Returns the info even if download_url is empty — the banner handles that case.
    """
    from taf_order_app import db
    if not db.is_ready() or not db.current_user():
        return None
    try:
        resp = db.get_client().table("app_versions").select("*").eq("id", 1).single().execute()
        info = resp.data
        if not info:
            return None
        if is_newer(info["version"]):
            return info
        return None
    except Exception:
        return None


def get_current_remote_version() -> str:
    """Return the version string from the DB, or APP_VERSION on error."""
    from taf_order_app import db
    try:
        resp = db.get_client().table("app_versions").select("version").eq("id", 1).single().execute()
        return resp.data.get("version", APP_VERSION)
    except Exception:
        return APP_VERSION


def cleanup_old_exe() -> None:
    """Delete TAFOrderEntry_old.exe left over from a previous auto-update (if any)."""
    if not getattr(sys, "frozen", False):
        return
    try:
        old = Path(sys.executable).parent / "TAFOrderEntry_old.exe"
        if old.exists():
            old.unlink()
    except Exception:
        pass


def download_and_install(info: dict, progress_cb=None) -> None:
    """
    Download the new EXE, swap it in via rename (no batch file needed),
    and relaunch using ShellExecuteW — identical to the user double-clicking.

    Why rename instead of copy?
      Windows lets you rename a running exe.  Renaming is atomic; copying
      over a running file is not — and copy via cmd/PowerShell sets up a
      different process environment that breaks DLL loading.

    Why ShellExecuteW?
      It launches the exe exactly as Explorer would (correct DLL search path,
      correct environment).  cmd.exe and PowerShell launch the exe in a
      shell-child context that can cause python3xx.dll to fail to load.
    """
    import urllib.request
    import ctypes

    url      = info["download_url"]
    exe_path = Path(sys.executable) if getattr(sys, "frozen", False) else None

    if exe_path is None:
        raise RuntimeError(
            "Auto-update only works when running as a built EXE.\n"
            "Download the new version manually."
        )

    new_exe = exe_path.parent / "TAFOrderEntry_update.exe"
    old_exe = exe_path.parent / "TAFOrderEntry_old.exe"

    # ── Download ─────────────────────────────────────────────────────────────
    if progress_cb:
        progress_cb(0, "Connecting…")

    def _report(block_num, block_size, total_size):
        if total_size > 0 and progress_cb:
            pct = min(95, int(block_num * block_size / total_size * 100))
            mb  = total_size / 1_048_576
            progress_cb(pct, f"Downloading… ({pct}% of {mb:.1f} MB)")

    urllib.request.urlretrieve(url, str(new_exe), reporthook=_report)

    if progress_cb:
        progress_cb(97, "Swapping files…")

    # ── Atomic file swap ─────────────────────────────────────────────────────
    # Remove leftover _old exe from any previous update
    try:
        if old_exe.exists():
            old_exe.unlink()
    except Exception:
        pass

    # Rename the running exe out of the way (Windows allows this for running exes).
    # Then move the downloaded update into the original location.
    try:
        exe_path.rename(old_exe)
        new_exe.rename(exe_path)
    except Exception as exc:
        # Clean up download on failure so it doesn't clutter the folder
        try:
            new_exe.unlink()
        except Exception:
            pass
        raise RuntimeError(f"Could not replace executable: {exc}") from exc

    if progress_cb:
        progress_cb(99, "Restarting…")

    # ── Relaunch via ShellExecuteW ────────────────────────────────────────────
    # ShellExecuteW is identical to Explorer / double-click.  It sets up the
    # correct DLL search path and process environment — the batch/PowerShell
    # approach does not, which caused the python3xx.dll LoadLibrary failure.
    try:
        ctypes.windll.shell32.ShellExecuteW(
            None,                    # hwnd
            "open",                  # verb
            str(exe_path),           # file
            None,                    # parameters
            str(exe_path.parent),    # working directory
            1,                       # SW_SHOWNORMAL
        )
    except Exception:
        # Fallback: plain subprocess if ShellExecuteW somehow fails
        subprocess.Popen(
            [str(exe_path)],
            cwd=str(exe_path.parent),
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )

    if progress_cb:
        progress_cb(100, "Restarting…")
    # Main thread detects pct==100 and calls os._exit(0) after a short delay.


def push_version(version: str, download_url: str, release_notes: str = "") -> None:
    """Developer tool: update the version row in the DB."""
    from taf_order_app import db
    import datetime
    db.get_client().table("app_versions").upsert({
        "id":           1,
        "version":      version,
        "download_url": download_url,
        "release_notes": release_notes,
        "updated_at":   datetime.datetime.utcnow().isoformat(),
    }).execute()


def upload_and_push(exe_path: str, version: str, release_notes: str,
                    anon_key: str) -> str:
    """
    Upload the EXE to Supabase Storage and update the version table.
    Returns the public download URL.
    """
    from supabase import create_client
    from taf_order_app.db import SUPABASE_URL

    client = create_client(SUPABASE_URL, anon_key)

    # Sign in first so we have the Director/Admin session
    # (called from push_update.py which handles sign-in)

    file_name = "TAFOrderEntry.exe"
    with open(exe_path, "rb") as f:
        data = f.read()

    try:
        client.storage.from_("releases").remove([file_name])
    except Exception:
        pass

    client.storage.from_("releases").upload(
        file_name, data,
        file_options={"content-type": "application/octet-stream", "upsert": "true"},
    )

    url = f"{SUPABASE_URL}/storage/v1/object/public/releases/{file_name}"

    # Update version row
    import datetime
    client.table("app_versions").upsert({
        "id":            1,
        "version":       version,
        "download_url":  url,
        "release_notes": release_notes,
        "updated_at":    datetime.datetime.utcnow().isoformat(),
    }).execute()

    return url
