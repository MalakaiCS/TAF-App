"""The filter-calculator Edge Function, run for real and called over HTTP.

Starts a stand-in for the two parts of Supabase the function talks to - the
auth server that says who a token belongs to, and the REST API it reads
is_staff() and calc_settings through - then serves the actual function with
Deno and calls it the way another program would.

Run:  python tests/api_function.py
Needs Deno. Skips without it, unless REQUIRE_DENO is set (CI).
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FUNCTION = ROOT / "supabase" / "functions" / "filter-calculator" / "index.ts"

STAFF = "Bearer staff-token"
STRANGER = "Bearer stranger-token"
SETTINGS = [
    {"key": "company", "value": {"base_address": "9 New Road, Logan QLD 4114"},
     "version": 4},
    {"key": "packaging", "value": {"confirmed": True, "base_kg": 0.2},
     "version": 2},
]

FAILURES: list = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}"
          + ("" if ok or not detail else f"\n        {detail}"))
    if not ok:
        FAILURES.append(label)


class Supabase(BaseHTTPRequestHandler):
    def log_message(self, *_a):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _who(self):
        return self.headers.get("Authorization", "")

    def do_GET(self):
        if self.path.startswith("/auth/v1/user"):
            if self._who() in (STAFF, STRANGER):
                return self._send(200, {"id": "u1", "aud": "authenticated",
                                        "role": "authenticated"})
            return self._send(401, {"message": "invalid token"})
        if self.path.startswith("/rest/v1/calc_settings"):
            return self._send(200, SETTINGS if self._who() == STAFF else [])
        self._send(404, {})

    def do_POST(self):
        if self.path.startswith("/rest/v1/rpc/is_staff"):
            return self._send(200, self._who() == STAFF)
        self._send(404, {})


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def call(port: int, body, auth: str = STAFF):
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/", data=data,
                                 method="POST",
                                 headers={"Authorization": auth,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def run_checks(port: int) -> None:
    print("\n── who may call it ──")
    code, _ = call(port, {"action": "settings"}, auth="")
    check("no token is refused", code == 401, str(code))
    code, _ = call(port, {"action": "settings"}, auth=STRANGER)
    check("a signed-in account that is not approved staff is refused",
          code == 403, str(code))
    code, _ = call(port, b"not json")
    check("a body that is not JSON is refused", code == 400, str(code))
    code, out = call(port, {"action": "nope"})
    check("an unknown action says which ones exist",
          code == 400 and "calculate" in out.get("error", ""), str(out))

    print("\n── the calculator, over HTTP ──")
    code, out = call(port, {"action": "calculate", "request": {
        "wire": {"pieces": [{"cut_width_mm": 600, "cut_length_mm": 1000,
                             "pieces_per_filter": 2}]},
        "wire_material_override": "LARGE_WIRE", "order_quantity": 10,
        "parts": ["wire"]}})
    r = out.get("result", {})
    check("measured wire comes back weighed",
          code == 200 and abs(r.get("wire_blank_weight_kg_order", 0) - 8.29)
          < 1e-9, json.dumps(r)[:200])
    check("with the versions it was worked out from",
          out.get("calc_version", "").startswith("TAF-FILTER-CALC") and
          out.get("settings_versions", {}).get("company") == 4,
          json.dumps(out.get("settings_versions")))
    code, out = call(port, {"action": "calculate", "item": {
        "Filter Type": "V-form", "Short": 595, "Long": 595, "Channel": 90,
        "Quantity": 4, "Media Type": "G4"}})
    piece = (out.get("result", {}).get("wire") or {}).get("pieces", [{}])[0]
    check("a saved order line is calculated with the worksheet's rules",
          code == 200 and piece.get("cut_width_mm") == 585 and
          piece.get("cut_length_mm") == 1062, json.dumps(piece))
    res = out["result"]
    check("and weighed from the supplied rates with nothing entered",
          res["weight_complete"] and abs(
              res["complete_filter_weight_kg_per_filter"]
              - res["installed_wire_weight_kg_per_filter"]
              - res["installed_media_weight_kg_per_filter"]) < 1e-9,
          json.dumps(res.get("missing")))
    code, out = call(port, {"action": "calculate", "item": {
        "Filter Type": "V-form", "Short": 595, "Long": 595, "Channel": 90,
        "Quantity": 4}})
    check("and an incomplete weight is null, never zero",
          out["result"]["complete_filter_weight_kg_per_filter"] is None and
          "which media this filter is made of" in out["result"]["missing"],
          json.dumps(out["result"].get("missing")))
    code, out = call(port, {"action": "calculate", "request": {
        "filter_type": "V-form", "width_mm": -1, "height_mm": 500}})
    check("bad input is answered 422 with the reason",
          code == 422 and out["result"]["errors"], str(code))

    print("\n── bracing, frames, packing, labels ──")
    code, out = call(port, {"action": "bracing", "construction": "flat panel",
                            "width_mm": 1301, "height_mm": 700})
    check("bracing by the API", code == 200 and out["result"]["message"] ==
          "Brace Required - 2 braces, Cross Format", json.dumps(out)[:200])
    code, out = call(port, {"action": "mounting_frame", "width_mm": 610,
                            "height_mm": 610, "quantity": 2})
    check("a mounting frame with no profile is unknown, not zero",
          code == 200 and out["result"]["status"] ==
          "needs_mounting_frame_profile" and
          out["result"]["mounting_frame_weight_kg_order"] is None)
    code, out = call(port, {"action": "pack", "quantity": 60, "width_mm": 412,
                            "height_mm": 412, "depth_mm": 90, "unit_kg": 1.9})
    wraps = [w["quantity"] for w in out.get("result", {}).get("wraps", [])]
    check("60 x 412x412x90 at 1.9 kg packs in twelve lots of five",
          code == 200 and wraps == [5] * 12 and out["result"]["compliant"],
          str(wraps))
    code, out = call(port, {"action": "pack", "quantity": 10, "unit_kg": 2.0,
                            "wraps": [{"quantity": 6}, {"quantity": 4}]})
    check("a hand-set plan over 10 kg is reported with a proposal",
          code == 200 and not out["result"]["ok"] and
          out["result"]["proposal"]["wraps"], json.dumps(out)[:200])
    order = {"customer_name": "Complete Air Supply - Tweed Heads",
             "address_line_1": "3A/38 Enterprise Avenue", "suburb":
             "Tweed Heads", "state": "NSW", "postcode": "2486",
             "order_number": "57920", "job_number": None,
             "items": [{"quantity": 10, "width_mm": 500, "height_mm": 600,
                        "depth_mm": 50, "wrap_quantities": [5, 5]},
                       {"quantity": 2, "width_mm": 500, "height_mm": 600,
                        "depth_mm": 90, "wrap_quantities": [2],
                        "complete_filter_weight_kg_per_filter": 1.5}]}
    code, out = call(port, {"action": "labels", "order": order})
    labels = out.get("labels", [])
    check("labels are numbered across the order",
          [l["wrap_page"] for l in labels] == ["1A/2", "1B/2", "2/2"],
          json.dumps(out)[:300])
    check("from the company's base address, read once",
          {l["from_address"] for l in labels} == {"9 New Road, Logan QLD 4114"})
    check("with N/A for no job and the weight worked out",
          labels and labels[0]["job_number"] == "N/A" and
          labels[2]["weight_kg"] == "3.200", json.dumps(labels[2:])[:200])
    bad = dict(order, fax="07 0000 0000")
    code, out = call(port, {"action": "labels", "order": bad})
    check("a field that is not on labels is refused, by name",
          code == 422 and any("fax" in p for p in out.get("problems", [])),
          json.dumps(out)[:200])


def _skip(why: str) -> int:
    if os.environ.get("REQUIRE_DENO"):
        print(f"FAIL: {why} - and this run requires it")
        return 1
    print(f"SKIP: {why}")
    return 0


def main() -> int:
    deno = shutil.which("deno")
    if not deno:
        return _skip("deno is not installed")
    sb_port, fn_port = _free_port(), _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", sb_port), Supabase)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = dict(os.environ, SUPABASE_URL=f"http://127.0.0.1:{sb_port}",
               SUPABASE_ANON_KEY="anon-key", DENO_NO_UPDATE_CHECK="1")
    # The function calls Deno.serve() the way the Edge runtime expects. A
    # two-line wrapper hands it a free port, so the test never fights
    # something else for 8000.
    import tempfile
    wrapper = Path(tempfile.mkdtemp(prefix="taf-fn-")) / "serve.ts"
    wrapper.write_text(
        "const serve = Deno.serve;\n"
        "// deno-lint-ignore no-explicit-any\n"
        "(Deno as any).serve = (h: any) => serve({ port: "
        f"{fn_port}, onListen() {{}} }}, h);\n"
        f"await import({json.dumps(FUNCTION.as_uri())});\n",
        encoding="utf-8")
    proc = subprocess.Popen(
        [deno, "run", "--allow-net", "--allow-env", "--allow-read",
         "--no-lock", str(wrapper)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace")
    try:
        for _ in range(240):
            try:
                socket.create_connection(("127.0.0.1", fn_port), 0.5).close()
                break
            except OSError:
                if proc.poll() is not None:
                    print(proc.stdout.read())
                    return _skip("the function would not start")
                time.sleep(0.5)
        else:
            return _skip("the function did not start in time")
        run_checks(fn_port)
    finally:
        proc.terminate()
        server.shutdown()
    print(f"\n{len(FAILURES)} FAILED" if FAILURES
          else "\nThe API answers as the apps do.")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
