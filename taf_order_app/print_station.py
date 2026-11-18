"""Printing on the work printers from anywhere.

The printers stay on the workshop's network and nothing outside can reach
them. One PC at work, with the app open and "This PC prints for everybody"
ticked, is the print station: every few seconds it asks the database for the
next job anybody has sent (migrate_print_queue.sql, step 53), prints it on
the printer they picked and says how it went. Whoever sent it sees "Printed"
- or why not - on their PC or phone.

Nothing here touches the screen. The window hands in how to list printers,
how to print a file and how to build an order's worksheets, and is told
what happened through on_event, from the station's own thread.
"""
from __future__ import annotations

import datetime as _dt
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

# A station that has not checked in for this long is shown as off.
ONLINE_SECONDS = 120
POLL_SECONDS = 5
CHECKIN_SECONDS = 60

STATUS_WORDS = {"queued": "Waiting", "printing": "Printing",
                "printed": "Printed", "failed": "Did not print",
                "cancelled": "Cancelled"}


def _when(text) -> Optional[_dt.datetime]:
    try:
        t = _dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=_dt.timezone.utc)


def is_online(station: dict, now: Optional[_dt.datetime] = None) -> bool:
    """On, and heard from in the last two minutes."""
    if not station.get("enabled", True):
        return False
    seen = _when(station.get("last_seen"))
    if seen is None:
        return False
    now = now or _dt.datetime.now(_dt.timezone.utc)
    return (now - seen).total_seconds() <= ONLINE_SECONDS


def printer_choices(stations: list, now=None) -> List[Tuple[str, str, str]]:
    """[(label, station id, printer)] for a "which printer" list: each
    station's own default first, then each of its printers. A station that
    is off is still listed - a job sent to it waits until it is back."""
    out = []
    for st in stations or []:
        if not st.get("enabled", True):
            continue
        name = str(st.get("name") or "")
        tag = "" if is_online(st, now) else "  (off right now)"
        default = str(st.get("default_printer") or "")
        out.append((f"{name}: its usual printer"
                    + (f" ({default})" if default else "") + tag,
                    str(st.get("id") or ""), ""))
        for p in st.get("printers") or []:
            out.append((f"{name}: {p}{tag}", str(st.get("id") or ""), str(p)))
    return out


def status_text(job: dict) -> str:
    word = STATUS_WORDS.get(str(job.get("status") or ""), str(job.get("status")))
    if job.get("status") == "failed" and job.get("error"):
        return f"{word}: {job['error']}"
    return word


def photo_as_pdf(path: Path) -> str:
    """A photo as a one-page PDF beside it, so it prints the way a PDF does
    (on Windows, straight to the printer rather than through a photo app
    asking questions nobody at the station is there to answer). A PDF, or a
    photo that will not open, is returned as it is."""
    path = Path(path)
    if path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        return str(path)
    try:
        from PIL import Image, ImageOps
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            out = path.with_suffix(".pdf")
            img.save(out, "PDF", resolution=150)
        return str(out)
    except Exception:
        return str(path)


def wait_for(job_id: str, fetch: Callable[[str], Optional[dict]],
             timeout: float = 180.0, interval: float = 4.0,
             sleep: Callable[[float], None] = time.sleep) -> Optional[dict]:
    """The job once it has printed, failed or been cancelled - or as it
    stands when the time is up. For whoever sent it, on their own thread."""
    deadline = time.monotonic() + timeout
    job = None
    while True:
        job = fetch(job_id) or job
        if job and job.get("status") in ("printed", "failed", "cancelled"):
            return job
        if time.monotonic() >= deadline:
            return job
        sleep(interval)


class PrintStation:
    """The loop that prints what is sent. start() and stop(); run_once()
    is one turn of it, for the tests."""

    def __init__(self, name: str, db,
                 list_printers: Callable[[], List[str]],
                 default_printer: Callable[[], str],
                 print_file: Callable[[str, str], str],
                 build_order: Callable[[str], Tuple[List[str], str]],
                 on_event: Optional[Callable[[str, dict, str], None]] = None):
        self.name = name
        self.db = db
        self.list_printers = list_printers
        self.default_printer = default_printer
        self.print_file = print_file
        self.build_order = build_order
        self.on_event = on_event or (lambda *_a: None)
        self.station_id = ""
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_checkin = 0.0

    # ── Being there ─────────────────────────────────────────────────────

    def checkin(self) -> str:
        try:
            printers = list(self.list_printers() or [])
        except Exception:
            printers = []
        self.station_id = self.db.print_station_checkin(
            self.name, printers, self.default_printer() or "")
        self._last_checkin = time.monotonic()
        return self.station_id

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="print-station")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive()
                    and not self._stop.is_set())

    def _loop(self) -> None:
        try:
            self.checkin()
        except Exception as exc:
            self.on_event("stopped", {}, str(exc))
            return
        self.on_event("started", {}, "")
        quiet = 0
        while not self._stop.is_set():
            try:
                if time.monotonic() - self._last_checkin >= CHECKIN_SECONDS:
                    self.checkin()
                busy = self.run_once()
                quiet = 0
            except Exception as exc:
                busy = False
                quiet += 1
                if "turned off" in str(exc):
                    self.on_event("stopped", {}, str(exc))
                    return
                if quiet == 3:          # said once, not every five seconds
                    self.on_event("trouble", {}, str(exc))
            if not busy:
                self._stop.wait(POLL_SECONDS * (1 if quiet < 3 else 6))

    # ── One job ─────────────────────────────────────────────────────────

    def run_once(self) -> bool:
        """Take and print the next job. True when there was one."""
        job = self.db.claim_print_job(self.station_id)
        if not job:
            return False
        self.on_event("printing", job, "")
        error = self._print_job(job)
        try:
            self.db.finish_print_job(job["id"], self.station_id, not error,
                                     error)
        finally:
            if job.get("kind") == "file" and job.get("file_path"):
                self.db.remove_print_file(job["file_path"])
        self.on_event("failed" if error else "printed", job, error)
        return True

    def _print_job(self, job: dict) -> str:
        """"" when it printed, otherwise why not, in words for the sender."""
        tmp = Path(tempfile.mkdtemp(prefix="taf-print-"))
        try:
            if job.get("kind") == "order":
                paths, error = self.build_order(str(job.get("order_id") or ""))
                if error:
                    return error
                if not paths:
                    return "The order's worksheets could not be made."
            else:
                name = str(job.get("file_path") or "")
                ext = os.path.splitext(name)[1].lower() or ".pdf"
                path = tmp / f"print{ext}"
                try:
                    path.write_bytes(self.db.download_print_file(name))
                except Exception as exc:
                    return f"The file could not be fetched ({exc})."
                paths = [photo_as_pdf(path)]
            printer = str(job.get("printer") or "")
            for _copy in range(max(1, int(job.get("copies") or 1))):
                for p in paths:
                    error = self.print_file(p, printer)
                    if error:
                        return error
            return ""
        except Exception as exc:
            return str(exc) or "Something went wrong printing it."
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
