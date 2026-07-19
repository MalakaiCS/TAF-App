"""
Auto-update support for TAF Order App — GitHub Releases edition.

Update source: the latest published GitHub Release of GITHUB_REPO. Each
release attaches the Inno Setup installer (TAFOrderEntry_Setup.exe); updating
downloads it and runs it silently, then relaunches the app.

Public API (unchanged for the GUI):
    check_for_update()            -> dict | None
    get_current_remote_version()  -> str
    download_and_install(info, progress_cb)
    cleanup_old_exe()
"""
from __future__ import annotations
import os, sys, json, subprocess, tempfile
from pathlib import Path
import urllib.request

APP_VERSION = "2.1.0"

# Public repo whose GitHub Releases drive updates.
GITHUB_REPO = "MalakaiCS/TAF-App"
_API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def _parse_version(v: str) -> tuple:
    try:
        return tuple(int(x) for x in str(v).strip().lstrip("vV").split("."))
    except Exception:
        return (0,)


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    return _parse_version(remote) > _parse_version(local)


def _fetch_latest() -> dict | None:
    """Return the latest-release JSON from the GitHub API, or None on any error."""
    try:
        req = urllib.request.Request(_API_LATEST, headers={
            "Accept":     "application/vnd.github+json",
            "User-Agent": f"TAFOrderEntry/{APP_VERSION}",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp)
    except Exception:
        return None


def check_for_update() -> dict | None:
    """
    Returns {"version", "download_url", "release_notes"} if the latest GitHub
    release is newer than APP_VERSION, else None. download_url points at the
    release's installer (.exe) asset.
    """
    data = _fetch_latest()
    if not data:
        return None
    tag = (data.get("tag_name") or "").strip()
    version = tag.lstrip("vV")
    if not version or not is_newer(version):
        return None

    download_url = ""
    for asset in data.get("assets", []):
        name = (asset.get("name") or "").lower()
        if name.endswith(".exe"):
            download_url = asset.get("browser_download_url", "")
            break

    return {
        "version":       version,
        "download_url":  download_url,
        "release_notes": data.get("body", "") or "",
    }


def get_current_remote_version() -> str:
    """Return the latest release version from GitHub, or APP_VERSION on error."""
    data = _fetch_latest()
    if not data:
        return APP_VERSION
    return (data.get("tag_name") or APP_VERSION).strip().lstrip("vV") or APP_VERSION


def cleanup_old_exe() -> None:
    """Kept for GUI compatibility. The installer-based update leaves nothing to clean."""
    return


def download_and_install(info: dict, progress_cb=None) -> None:
    """
    Download the release installer and run it silently, then relaunch the app.

    Because this is a PyInstaller *onedir* build (exe + locked _internal DLLs),
    we can't hot-swap files in place. Instead we hand off to the Inno Setup
    installer via a detached helper that:
        1) waits a moment for this app to close,
        2) runs the installer silently (replacing all files),
        3) relaunches the app.
    The GUI exits (os._exit) once progress reaches 100 so the files unlock.
    """
    url = info.get("download_url", "")
    if not url:
        raise RuntimeError(
            "This release has no installer attached yet.\n"
            "Download the latest version manually from the GitHub Releases page."
        )
    if not getattr(sys, "frozen", False):
        raise RuntimeError(
            "Auto-update only works in the installed app.\n"
            "When running from source, just git pull / rebuild."
        )

    if progress_cb:
        progress_cb(0, "Connecting…")

    setup = Path(tempfile.gettempdir()) / "TAFOrderEntry_Setup.exe"

    def _report(block_num, block_size, total_size):
        if total_size > 0 and progress_cb:
            pct = min(95, int(block_num * block_size / total_size * 100))
            mb  = total_size / 1_048_576
            progress_cb(pct, f"Downloading… ({pct}% of {mb:.1f} MB)")

    urllib.request.urlretrieve(url, str(setup), reporthook=_report)

    if progress_cb:
        progress_cb(97, "Starting installer…")

    exe_path = Path(sys.executable)
    app_pid  = os.getpid()

    # ── Hand off to a detached helper that (1) waits for THIS app to fully
    #    exit so its exe/DLLs unlock, (2) runs the installer to completion,
    #    (3) relaunches the updated app. ────────────────────────────────────
    #
    # The previous helper used cmd's `timeout`, which fails instantly under a
    # detached / no-console process ("input redirection is not supported").
    # Chained with `&`, that made the installer run *before* the app had
    # closed, so it couldn't overwrite the locked files and the silent install
    # aborted — the app shut down but nothing updated. The installer has no
    # AppMutex, so it can't close the app itself; we must wait it out here.
    # PowerShell's Wait-Process / Start-Sleep need no console, so they work
    # correctly when launched detached.
    def _ps_quote(p) -> str:
        return "'" + str(p).replace("'", "''") + "'"

    ps_script = "\n".join([
        "$ErrorActionPreference = 'SilentlyContinue'",
        # 1) Wait for the running app to close (up to 30s) so its files unlock.
        f"try {{ Wait-Process -Id {app_pid} -Timeout 30 }} catch {{ }}",
        "Start-Sleep -Seconds 1",
        # 2) Install the update silently and WAIT for it to finish.
        f"Start-Process -FilePath {_ps_quote(setup)} "
        f"-ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOCANCEL' -Wait",
        # 3) Relaunch the updated app.
        f"Start-Process -FilePath {_ps_quote(exe_path)}",
        "",
    ])
    ps_path = Path(tempfile.gettempdir()) / "TAFOrderEntry_update.ps1"
    ps_path.write_text(ps_script, encoding="utf-8")

    DETACHED_PROCESS = 0x00000008
    CREATE_NO_WINDOW = 0x08000000
    flags = DETACHED_PROCESS | CREATE_NO_WINDOW

    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-WindowStyle", "Hidden", "-File", str(ps_path)],
            creationflags=flags, close_fds=True)
    except Exception:
        # Fallback if PowerShell can't be launched: a cmd helper that uses
        # `ping` for the delay (works with no console, unlike `timeout`) and
        # relies on `&` running sequentially so the install finishes before
        # the relaunch.
        helper = (
            f'ping 127.0.0.1 -n 5 >nul & '
            f'"{setup}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOCANCEL & '
            f'start "" "{exe_path}"'
        )
        subprocess.Popen(["cmd", "/c", helper],
                         creationflags=flags, close_fds=True)

    if progress_cb:
        progress_cb(100, "Installing update… the app will reopen shortly.")
    # Main thread detects pct==100 and calls os._exit(0) after a short delay,
    # which lets the helper's Wait-Process return and the install proceed.
