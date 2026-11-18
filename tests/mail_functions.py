"""The proof-of-delivery and owner's report functions, run for real.

Both serve with Deno behind a small stand-in for Supabase (sign-in, the
tables they read, storage, and the mail provider), the way xero_function.py
does for the xero function. What they write to the database is checked on a
real Postgres by db_rules.py (step 48).

Run:  python tests/mail_functions.py
Needs Deno. Skips without it, unless REQUIRE_DENO is set (CI).
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FUNCTIONS = {"pod": ROOT / "supabase" / "functions" / "proof-of-delivery" / "index.ts",
             "report": ROOT / "supabase" / "functions" / "owner-report" / "index.ts"}
SERVICE = "service-key"
# token: (user id, email, staff, manager)
USERS = {"floor": ("u-floor", "dave@taf.example", True, False),
         "boss": ("u-boss", "sarah@taf.example", True, True),
         "stranger": ("u-who", "who@example.com", False, False)}
LOCK = threading.RLock()
FAILURES: list = []
MAIL: list = []

NOW = dt.datetime.now(dt.timezone.utc)


def iso(d: dt.datetime) -> str:
    return d.astimezone(dt.timezone.utc).isoformat()


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}"
          + ("" if ok or not detail else f"\n        {detail}"))
    if not ok:
        FAILURES.append(label)


# ── The stand-in's data ──────────────────────────────────────────────────────

SIGNED = NOW - dt.timedelta(minutes=5)
TABLES: dict = {
    "feature_switches": [],
    "orders": [
        {"id": "o1", "customer_id": "c1", "customer_name": "BCC",
         "order_number": "PO-1", "date_due": "",
         "header": {"Job": "Level 3 AHU"},
         "items": [{"Filter Type": "V-Form", "Quantity": 4, "Short": 595, "Long": 595}]},
        {"id": "o2", "customer_name": "Nobody Pty", "order_number": "PO-2",
         "header": {}, "items": []},
    ],
    "order_files": [
        {"order_id": "o1", "kind": "signature", "path": "o1/sig.png",
         "signed_by": "Jo Smith", "created_at": iso(SIGNED)},
        {"order_id": "o1", "kind": "photo", "path": "o1/drop.jpg",
         "created_at": iso(SIGNED - dt.timedelta(minutes=2))},
        {"order_id": "o1", "kind": "photo", "path": "o1/plant-room.jpg",
         "created_at": iso(SIGNED - dt.timedelta(days=3))},
        {"order_id": "o2", "kind": "signature", "path": "o2/sig.png",
         "signed_by": "Al", "created_at": iso(SIGNED)},
    ],
    "customers": [
        {"id": "c1", "name": "Bells Creek Constructions", "short_name": "BCC",
         "email": "accounts@bells.example"},
        {"id": "c2", "name": "Nobody Pty", "short_name": "", "email": ""},
    ],
    "delivery_proofs": [],
    "profiles": [
        {"id": "u-boss", "email": "sarah@taf.example", "role": "Manager", "approved": True},
        {"id": "u-kai", "email": "kai@taf.example", "role": "Director", "approved": True},
        {"id": "u-amy", "email": "amy@taf.example", "role": "Admin", "approved": True},
        {"id": "u-new", "email": "new@taf.example", "role": "Director", "approved": False},
    ],
    # September 2026 in Brisbane is 31 Aug 14:00 UTC to 30 Sep 14:00 UTC.
    "order_values": [
        {"id": "v1", "customer_name": "BCC", "created_at": "2026-08-31T15:00:00+00:00",
         "value": 1000, "unpriced": 0},
        {"id": "v2", "customer_name": "Tweed", "created_at": "2026-09-15T01:00:00+00:00",
         "value": 2500, "unpriced": 1},
        {"id": "v3", "customer_name": "BCC", "created_at": "2026-09-20T01:00:00+00:00",
         "value": 500, "unpriced": 0},
        {"id": "v4", "customer_name": "BCC", "created_at": "2026-09-30T15:00:00+00:00",
         "value": 9999, "unpriced": 0},     # 1 October in Brisbane
        {"id": "v5", "customer_name": "Tweed", "created_at": "2026-08-10T01:00:00+00:00",
         "value": 2000, "unpriced": 0},     # August
    ],
    "sales_targets": [{"month": "2026-09-01", "target": 5000}],
    "quotes": [
        {"status": "accepted", "total": 800, "lost_reason": "", "created_at": "2026-09-02T01:00:00+00:00"},
        {"status": "declined", "total": 300, "lost_reason": "Price", "created_at": "2026-09-03T01:00:00+00:00"},
        {"status": "declined", "total": 300, "lost_reason": "Price", "created_at": "2026-09-04T01:00:00+00:00"},
        {"status": "sent", "total": 100, "lost_reason": "", "created_at": "2026-09-05T01:00:00+00:00"},
    ],
    "returns": [{"id": "r1", "reason": "Wrong size", "created_at": "2026-09-09T01:00:00+00:00"}],
    "job_times": [{"minutes": 90, "stopped_at": "2026-09-09T01:00:00+00:00"},
                  {"minutes": 30, "stopped_at": "2026-09-10T01:00:00+00:00"}],
    "stock_items": [{"name": "G4 roll", "stock_on_hand": 2, "minimum_on_hand": 5},
                    {"name": "Rivets", "stock_on_hand": 50, "minimum_on_hand": 5}],
    "owner_reports": [],
}
TABLES["orders"] += [
    {"id": "f1", "date_due": "10/09/2026",
     "header": {"status": "Complete", "status_at": "2026-09-09T02:00:00+00:00"}},
    {"id": "f2", "date_due": "05/09/2026",
     "header": {"status": "Dispatched", "status_at": "2026-09-09T02:00:00+00:00"}},
    {"id": "f3", "date_due": "ASAP",
     "header": {"status": "Delivered", "status_at": "2026-09-12T02:00:00+00:00"}},
    {"id": "f4", "date_due": "01/09/2026",
     "header": {"status": "In Production", "status_at": "2026-09-12T02:00:00+00:00"}},
]
FILES = {"o1/sig.png": b"\x89PNG signature", "o1/drop.jpg": b"\xff\xd8 drop",
         "o1/plant-room.jpg": b"\xff\xd8 old", "o2/sig.png": b"\x89PNG al"}


def field(row: dict, key: str):
    if "->>" in key:
        col, sub = key.split("->>", 1)
        return (row.get(col) or {}).get(sub)
    return row.get(key)


def matches(row: dict, query: dict) -> bool:
    for k, vals in query.items():
        if k in ("select", "order", "offset", "limit", "on_conflict", "columns"):
            continue
        for v in vals:
            got = field(row, k)
            op, _, want = v.partition(".")
            if op == "eq" and str(got) != want:
                return False
            if op == "in":
                if str(got) not in [w.strip('"') for w in want.strip("()").split(",")]:
                    return False
            if op == "gte" and (got is None or str(got) < want):
                return False
            if op == "lt" and (got is None or str(got) >= want):
                return False
    return True


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *_a):
        pass

    def _send(self, code, body, raw: bytes = b"", kind="application/json"):
        data = raw or (b"" if body is None else json.dumps(body).encode())
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _user(self):
        token = self.headers.get("Authorization", "")[7:]
        return USERS.get(token)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PATCH(self):
        self._handle("PATCH")

    def _handle(self, method):
        url = urllib.parse.urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"null") if n else None
        token = self.headers.get("Authorization", "")[7:]
        if url.path == "/auth/v1/user":
            u = self._user()
            return self._send(200, {"id": u[0], "email": u[1]} if u else {},
                              ) if u else self._send(401, {"message": "bad jwt"})
        if url.path == "/resend":
            with LOCK:
                MAIL.append(body)
            return self._send(200, {"id": "m" + str(len(MAIL))})
        if url.path.startswith("/storage/v1/object/"):
            path = url.path.split("/", 5)[5]
            if path not in FILES or token != SERVICE:
                return self._send(404, {"message": "not found"})
            return self._send(200, None, FILES[path], "application/octet-stream")
        if url.path.startswith("/rest/v1/rpc/"):
            name = url.path.rsplit("/", 1)[1]
            u = self._user()
            if name == "is_staff":
                return self._send(200, bool(u and u[2]))
            if name == "is_manager":
                return self._send(200, bool(u and u[3]))
            return self._send(404, {})
        if url.path.startswith("/rest/v1/"):
            table = url.path.rsplit("/", 1)[1]
            query = urllib.parse.parse_qs(url.query)
            with LOCK:
                store = TABLES.setdefault(table, [])
                if method == "GET":
                    rows = [dict(r) for r in store if matches(r, query)]
                    if "created_at.desc" in query.get("order", [""])[0]:
                        rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
                    if "vnd.pgrst.object" in (self.headers.get("Accept") or ""):
                        if len(rows) != 1:
                            return self._send(406, {
                                "code": "PGRST116", "details": f"The result contains {len(rows)} rows",
                                "message": "JSON object requested, multiple (or no) rows returned"})
                        return self._send(200, rows[0])
                    return self._send(200, rows)
                if method == "POST":
                    if token != SERVICE:
                        return self._send(403, {"message": "row-level security"})
                    key = "order_id" if table == "delivery_proofs" else "month"
                    for row in body if isinstance(body, list) else [body]:
                        hit = next((r for r in store if r.get(key) == row.get(key)), None)
                        if hit:
                            hit.update(row)
                        else:
                            store.append(dict(row))
                    return self._send(201, None)
        return self._send(404, {})


def call(name: str, token: str, payload: dict):
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORTS[name]}/", data=json.dumps(payload).encode(),
        method="POST", headers={"Authorization": f"Bearer {token}",
                                "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def switch(key: str, on: bool) -> None:
    with LOCK:
        TABLES["feature_switches"] = [r for r in TABLES["feature_switches"] if r["key"] != key]
        TABLES["feature_switches"].append({"key": key, "enabled": on})


def run_pod_checks() -> None:
    print("\n── proof of delivery ──")
    code, out = call("pod", "stranger", {"order_id": "o1"})
    check("an account that is not staff cannot send one", code == 403, str(out))
    code, out = call("pod", "floor", {"order_id": "o1"})
    check("switched off, nothing is sent and it says why",
          code == 200 and out.get("sent") is False and "switched off" in out.get("reason", "")
          and not MAIL, str(out))
    switch("pod_email", True)
    code, out = call("pod", "floor", {})
    check("an order has to be named", code == 400, str(out))
    code, out = call("pod", "floor", {"order_id": "o1"})
    mail = MAIL[-1] if MAIL else {}
    check("signed for: the customer is emailed", code == 200 and out.get("sent") is True
          and mail.get("to") == ["accounts@bells.example"]
          and mail.get("subject") == "Delivered — PO-1", f"{out} {mail.get('to')}")
    names = [a["filename"] for a in mail.get("attachments", [])]
    check("with the signature and the photo from the drop, not the old one",
          names == ["signature.png", "photo-1.jpg"]
          and base64.b64decode(mail["attachments"][0]["content"]) == FILES["o1/sig.png"],
          str(names))
    html = mail.get("html", "")
    check("saying who signed, the job and what was delivered",
          "Jo Smith" in html and "Level 3 AHU" in html and "V-Form" in html
          and "595 × 595" in html)
    proof = next((p for p in TABLES["delivery_proofs"] if p["order_id"] == "o1"), {})
    check("and it is written down as sent", proof.get("emailed_to") == "accounts@bells.example"
          and proof.get("signature_path") == "o1/sig.png" and proof.get("photos") == 1, str(proof))
    sent = len(MAIL)
    code, out = call("pod", "floor", {"order_id": "o1"})
    check("asked again for the same signature, it does not go twice",
          code == 200 and out.get("already") is True and len(MAIL) == sent, str(out))
    code, out = call("pod", "floor", {"order_id": "o2"})
    check("a customer with no email address is not an error",
          code == 200 and out.get("sent") is False and "No email" in out.get("reason", ""), str(out))


def run_report_checks() -> None:
    print("\n── the owner's report ──")
    code, out = call("report", "floor", {"month": "2026-09"})
    check("somebody on the floor cannot see it", code == 403, str(out))
    before = len(MAIL)
    code, out = call("report", "boss", {"month": "2026-09"})
    f = out.get("figures", {})
    s = f.get("sales") or {}
    check("a manager sees the month without anything being sent",
          code == 200 and "September 2026" in out.get("html", "") and len(MAIL) == before,
          str(out)[:300])
    check("orders and their value, by the Brisbane day they came in",
          s.get("orders") == 3 and s.get("value") == 4000 and s.get("unpriced") == 1
          and s.get("prev_orders") == 1 and s.get("prev_value") == 2000, str(s))
    check("against the target", f.get("target") == 5000 and "80%" in out.get("html", ""))
    check("biggest customers first", [t["name"] for t in s.get("top", [])] == ["Tweed", "BCC"])
    q = f.get("quotes") or {}
    check("quotes sent, won and lost, and why",
          (q.get("sent"), q.get("won"), q.get("lost")) == (4, 1, 2)
          and q.get("reasons") == [{"reason": "Price", "count": 2}], str(q))
    j = f.get("jobs") or {}
    check("jobs finished and how many on time",
          (j.get("finished"), j.get("with_due"), j.get("on_time")) == (3, 2, 1), str(j))
    check("faults, hours at the bench and stock under its minimum",
          f.get("faults") == 1 and f.get("hours") == 2 and f.get("low") == ["G4 roll"], str(f))
    code, out = call("report", "boss", {"month": "2026-09", "send": True})
    check("'Email it to me' sends it to that manager only",
          code == 200 and out.get("to") == "sarah@taf.example"
          and MAIL[-1]["to"] == ["sarah@taf.example"] and len(MAIL) == before + 1, str(out))

    code, out = call("report", "boss", {"scheduled": True})
    check("a signed-in account cannot send it to every director", code == 403, str(out))
    code, out = call("report", SERVICE, {"scheduled": True, "force": True})
    check("the schedule sends nothing while it is switched off",
          code == 200 and out.get("sent") == 0 and "switched off" in out.get("reason", ""), str(out))
    switch("owner_report", True)
    brisbane = NOW + dt.timedelta(hours=10)
    if brisbane.day != 1:
        code, out = call("report", SERVICE, {"scheduled": True})
        check("it goes on the 1st, not before",
              code == 200 and out.get("sent") == 0 and "1st" in out.get("reason", ""), str(out))
    before = len(MAIL)
    code, out = call("report", SERVICE, {"scheduled": True, "force": True})
    to = sorted(m["to"][0] for m in MAIL[before:])
    check("on the day, every approved director and admin gets their own copy",
          code == 200 and out.get("sent") == 2 and to == ["amy@taf.example", "kai@taf.example"],
          f"{out} {to}")
    check("and it is written down", len(TABLES["owner_reports"]) == 1
          and TABLES["owner_reports"][0]["sent_to"] == ["kai@taf.example", "amy@taf.example"])
    code, out = call("report", SERVICE, {"scheduled": True, "force": True})
    check("so the next night's run does not send it again",
          out.get("sent") == 0 and "Already" in out.get("reason", ""), str(out))


def _skip(why: str) -> int:
    if os.environ.get("REQUIRE_DENO"):
        print(f"FAIL: {why} - and this run requires it")
        return 1
    print(f"SKIP: {why}")
    return 0


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


PORTS: dict = {}


def main() -> int:
    deno = shutil.which("deno")
    if not deno:
        return _skip("deno is not installed")
    fake_port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", fake_port), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{fake_port}"
    env = dict(os.environ, SUPABASE_URL=base, SUPABASE_ANON_KEY="anon-key",
               SUPABASE_SERVICE_ROLE_KEY=SERVICE, RESEND_API_KEY="mail-key",
               MAIL_FROM="TAF <office@taf.example>", RESEND_API_URL=f"{base}/resend",
               DENO_NO_UPDATE_CHECK="1")
    procs = []
    try:
        for name, fn in FUNCTIONS.items():
            PORTS[name] = _free_port()
            wrapper = Path(tempfile.mkdtemp(prefix=f"taf-{name}-")) / "serve.ts"
            wrapper.write_text(
                "const serve = Deno.serve;\n"
                "// deno-lint-ignore no-explicit-any\n"
                f"(Deno as any).serve = (h: any) => serve({{ port: {PORTS[name]}, "
                "onListen() {} }, h);\n"
                f"await import({json.dumps(fn.as_uri())});\n", encoding="utf-8")
            procs.append(subprocess.Popen(
                [deno, "run", "--allow-net", "--allow-env", "--allow-read",
                 "--no-lock", str(wrapper)],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace"))
        for name, proc in zip(FUNCTIONS, procs):
            for _ in range(240):
                try:
                    socket.create_connection(("127.0.0.1", PORTS[name]), 0.5).close()
                    break
                except OSError:
                    if proc.poll() is not None:
                        print(proc.stdout.read())
                        return _skip(f"the {name} function would not start")
                    time.sleep(0.5)
            else:
                return _skip(f"the {name} function did not start in time")
        run_pod_checks()
        run_report_checks()
    finally:
        for p in procs:
            p.terminate()
        server.shutdown()
    print(f"\n{len(FAILURES)} FAILED" if FAILURES
          else "\nThe customer hears it arrived; the directors hear how the month went.")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
