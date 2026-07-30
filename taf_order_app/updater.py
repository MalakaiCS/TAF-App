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

APP_VERSION = "2.3.4"

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
    app_dir  = exe_path.parent
    app_pid  = os.getpid()

    # Logs so a failed update can actually be diagnosed instead of guessed at.
    data_dir = Path(os.environ.get("APPDATA", tempfile.gettempdir())) / "TAF Order Entry"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        data_dir = Path(tempfile.gettempdir())
    diag    = data_dir / "update.log"
    innolog = data_dir / "update_install_inno.log"

    # ── Helper script (PowerShell): wait for the app to exit, install to the
    #    same folder (silent if writable, elevated if not), relaunch, and log
    #    every step so failures are diagnosable. ────────────────────────────
    def _q(p) -> str:
        return "'" + str(p).replace("'", "''") + "'"

    inno_args = f"/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOCANCEL /LOG=\"{innolog}\""
    ps_script = f"""
$ErrorActionPreference = 'Continue'
$log = {_q(diag)}
Add-Content -Path $log -Value '[helper] started - waiting for app PID {app_pid} to exit'
try {{ Wait-Process -Id {app_pid} -Timeout 60 -ErrorAction SilentlyContinue }} catch {{ }}
Start-Sleep -Seconds 2
$appDir = {_q(app_dir)}
$test   = Join-Path $appDir '__wtest.tmp'
$canWrite = $true
try {{ Set-Content -Path $test -Value 'x' -ErrorAction Stop
      Remove-Item $test -ErrorAction SilentlyContinue }} catch {{ $canWrite = $false }}
if ($canWrite) {{
  Add-Content -Path $log -Value '[helper] app folder writable - running silent install'
  $p = Start-Process -FilePath {_q(setup)} -ArgumentList {_q(inno_args)} -Wait -PassThru
  Add-Content -Path $log -Value ('[helper] installer exit code: ' + $p.ExitCode)
}} else {{
  Add-Content -Path $log -Value '[helper] app folder needs admin - elevated install (UAC prompt)'
  try {{ Start-Process -FilePath {_q(setup)} -ArgumentList {_q(inno_args)} -Verb RunAs -Wait }} catch {{ }}
  Add-Content -Path $log -Value '[helper] elevated install returned'
}}
Add-Content -Path $log -Value '[helper] relaunching app'
Start-Process -FilePath {_q(exe_path)} -WorkingDirectory {_q(app_dir)}
try {{ schtasks /Delete /TN 'TAFOrderEntryUpdate' /F 2>$null | Out-Null }} catch {{ }}
Add-Content -Path $log -Value '[helper] done'
"""
    ps_path = Path(tempfile.gettempdir()) / "TAFOrderEntry_update.ps1"
    ps_path.write_text(ps_script, encoding="utf-8-sig")

    def _diag_write(line: str, reset: bool = False) -> None:
        try:
            with open(diag, "w" if reset else "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    _diag_write(f"[update] v{APP_VERSION} -> v{info.get('version','?')} - launching helper", reset=True)

    # ── Launch the helper OUTSIDE the app's process tree. ─────────────────
    # Update logs kept stopping at the first line: the helper (a child of the
    # app) was killed the moment the app exited, because the app runs inside a
    # Windows job object with kill-on-close that also DENIES breakaway (so the
    # CREATE_BREAKAWAY_FROM_JOB attempt silently fell back into the job).
    # Fix: ask a system service to start the helper instead — processes
    # created via WMI (or Task Scheduler) are parented to the service, not the
    # app, so they are untouched by the app's job. Every attempt is logged.
    CREATE_NO_WINDOW = 0x08000000
    helper_cmd = (f'powershell.exe -NoProfile -ExecutionPolicy Bypass '
                  f'-WindowStyle Hidden -File "{ps_path}"')

    launched = False

    # 1) WMI (Win32_Process.Create) — helper is parented to the WMI service.
    try:
        cim = ("$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
               "-Arguments @{ CommandLine = " + _q(helper_cmd) + " }; "
               "exit [int]$r.ReturnValue")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cim],
                           creationflags=CREATE_NO_WINDOW, timeout=40)
        launched = (r.returncode == 0)
    except Exception:
        launched = False
    _diag_write(f"[update] launch via WMI: {'ok' if launched else 'FAILED'}")

    # 2) Task Scheduler — task processes run under the scheduler service.
    if not launched:
        try:
            subprocess.run(["schtasks", "/Create", "/TN", "TAFOrderEntryUpdate",
                            "/TR", helper_cmd, "/SC", "ONCE", "/ST", "23:59", "/F"],
                           creationflags=CREATE_NO_WINDOW, timeout=40)
            r = subprocess.run(["schtasks", "/Run", "/TN", "TAFOrderEntryUpdate"],
                               creationflags=CREATE_NO_WINDOW, timeout=40)
            launched = (r.returncode == 0)
        except Exception:
            launched = False
        _diag_write(f"[update] launch via Task Scheduler: {'ok' if launched else 'FAILED'}")

    # 3) Last resort: direct child with breakaway (works when no job denies it).
    if not launched:
        DETACHED_PROCESS          = 0x00000008
        CREATE_BREAKAWAY_FROM_JOB = 0x01000000
        base = DETACHED_PROCESS | CREATE_NO_WINDOW
        try:
            subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                              "-WindowStyle", "Hidden", "-File", str(ps_path)],
                             creationflags=base | CREATE_BREAKAWAY_FROM_JOB,
                             close_fds=True)
        except Exception:
            subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                              "-WindowStyle", "Hidden", "-File", str(ps_path)],
                             creationflags=base, close_fds=True)
        _diag_write("[update] launch via direct child (breakaway attempt)")

    if progress_cb:
        progress_cb(100, "Installing update… the app will reopen shortly.")
    # Main thread detects pct==100 and calls os._exit(0) after a short delay so
    # the app's files unlock; the helper's Wait-Process then proceeds.
