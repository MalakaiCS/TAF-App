"""Printing on the work printers from anywhere: the print station's loop
(step 53), with the database and the printer stood in for."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from taf_order_app import print_station as ps

NOW = dt.datetime(2026, 10, 22, 9, 0, tzinfo=dt.timezone.utc)


class FakeDB:
    def __init__(self, jobs=None, files=None):
        self.jobs = list(jobs or [])
        self.files = dict(files or {})
        self.finished, self.removed, self.checkins = [], [], []

    def print_station_checkin(self, name, printers, default):
        self.checkins.append((name, printers, default))
        return "st-1"

    def claim_print_job(self, station_id):
        return self.jobs.pop(0) if self.jobs else None

    def finish_print_job(self, job_id, station_id, ok, error=""):
        self.finished.append((job_id, station_id, ok, error))

    def download_print_file(self, name):
        if name not in self.files:
            raise RuntimeError("Object not found")
        return self.files[name]

    def remove_print_file(self, name):
        self.removed.append(name)


def _station(db, printed, order=None, fail=""):
    def _print(path, printer):
        printed.append((Path(path).suffix, Path(path).read_bytes()[:4]
                        if Path(path).exists() else b"", printer))
        return fail
    return ps.PrintStation(
        "WORKSHOP-PC", db, lambda: ["Brother", "Label"], lambda: "Brother",
        _print, order or (lambda oid: ([], "no order")))


def test_a_file_sent_from_anywhere_prints_on_the_printer_picked():
    db = FakeDB([{"id": "j1", "kind": "file", "file_path": "u/a.pdf",
                  "printer": "Label", "copies": 2, "title": "Run sheet"}],
                {"u/a.pdf": b"%PDF-1.4 hello"})
    printed = []
    st = _station(db, printed)
    assert st.checkin() == "st-1"
    assert db.checkins == [("WORKSHOP-PC", ["Brother", "Label"], "Brother")]
    assert st.run_once() is True
    assert printed == [(".pdf", b"%PDF", "Label")] * 2     # two copies
    assert db.finished == [("j1", "st-1", True, "")]
    assert db.removed == ["u/a.pdf"]                      # not kept after
    assert st.run_once() is False                         # nothing waiting


def test_a_printer_that_fails_is_told_to_whoever_sent_it():
    db = FakeDB([{"id": "j2", "kind": "file", "file_path": "u/b.pdf",
                  "printer": "", "copies": 1}], {"u/b.pdf": b"%PDF"})
    printed = []
    st = _station(db, printed, fail="Printer is out of paper")
    st.station_id = "st-1"
    st.run_once()
    assert db.finished == [("j2", "st-1", False, "Printer is out of paper")]
    assert db.removed == ["u/b.pdf"]


def test_a_file_that_has_gone_fails_rather_than_printing_nothing():
    db = FakeDB([{"id": "j3", "kind": "file", "file_path": "u/gone.pdf"}])
    st = _station(db, [])
    st.station_id = "st-1"
    st.run_once()
    ok, why = db.finished[0][2], db.finished[0][3]
    assert not ok and "could not be fetched" in why


def test_an_order_sent_from_a_phone_is_built_at_the_station():
    import tempfile
    tmp_path = Path(tempfile.mkdtemp())
    pdf = tmp_path / "order.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    asked = []

    def _build(oid):
        asked.append(oid)
        return [str(pdf)], ""
    db = FakeDB([{"id": "j4", "kind": "order", "order_id": "o-9",
                  "printer": "", "copies": 1}])
    printed = []
    st = _station(db, printed, order=_build)
    st.station_id = "st-1"
    st.run_once()
    assert asked == ["o-9"] and printed == [(".pdf", b"%PDF", "")]
    assert db.finished == [("j4", "st-1", True, "")] and db.removed == []

    db.jobs = [{"id": "j5", "kind": "order", "order_id": "o-10"}]
    st.build_order = lambda oid: ([], "The order needs fixing before it prints: "
                                      "Location is empty.")
    st.run_once()
    assert db.finished[-1][2] is False and "Location" in db.finished[-1][3]


def test_a_photo_is_printed_as_a_pdf():
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buf, "JPEG")
    db = FakeDB([{"id": "j6", "kind": "file", "file_path": "u/p.jpg"}],
                {"u/p.jpg": buf.getvalue()})
    printed = []
    st = _station(db, printed)
    st.station_id = "st-1"
    st.run_once()
    assert printed == [(".pdf", b"%PDF", "")]


def test_which_stations_are_on():
    on = {"name": "A", "enabled": True,
          "last_seen": (NOW - dt.timedelta(seconds=30)).isoformat()}
    off = dict(on, last_seen=(NOW - dt.timedelta(minutes=10)).isoformat())
    disabled = dict(on, enabled=False)
    assert ps.is_online(on, NOW) and not ps.is_online(off, NOW)
    assert not ps.is_online(disabled, NOW)
    assert not ps.is_online({"last_seen": "nonsense"}, NOW)


def test_the_printer_list_offers_each_stations_printers():
    st = [{"id": "s1", "name": "WORKSHOP", "enabled": True,
           "printers": ["Brother", "Zebra"], "default_printer": "Brother",
           "last_seen": NOW.isoformat()},
          {"id": "s2", "name": "OFFICE", "enabled": True, "printers": ["HP"],
           "default_printer": "", "last_seen": "2020-01-01T00:00:00+00:00"},
          {"id": "s3", "name": "OLD", "enabled": False, "printers": ["X"]}]
    got = ps.printer_choices(st, NOW)
    assert [(c[1], c[2]) for c in got] == [("s1", ""), ("s1", "Brother"),
                                           ("s1", "Zebra"), ("s2", ""),
                                           ("s2", "HP")]
    assert got[0][0] == "WORKSHOP: its usual printer (Brother)"
    assert got[3][0].endswith("(off right now)")


def test_whoever_sent_it_hears_when_it_printed():
    states = iter([{"status": "queued"}, {"status": "printing"},
                   {"status": "printed"}])
    got = ps.wait_for("j", lambda _id: next(states), timeout=60,
                      interval=0, sleep=lambda _s: None)
    assert got["status"] == "printed"
    assert ps.status_text({"status": "failed", "error": "Jammed"}) == \
        "Did not print: Jammed"
    assert ps.status_text({"status": "queued"}) == "Waiting"
