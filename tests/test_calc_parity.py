"""The desktop's Python and the web app's JavaScript give the same answers.

docs/app/calc.js is the calculator the web app and the filter-calculator
API use; taf_order_app is the one the desktop uses. Two copies of a rule are
two chances to change one and not the other, so this runs the same requests
through both and compares the WHOLE result - every field, status, message
and number - not a sample of it.

Needs Node. CI has it; a machine without it skips, unless REQUIRE_NODE is
set, where a skip would let a broken twin through.
"""
from __future__ import annotations

import copy
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taf_order_app import bracing as br                    # noqa: E402
from taf_order_app import calc_settings as cs              # noqa: E402
from taf_order_app import delivery_labels as dl            # noqa: E402
from taf_order_app import filter_calc as fc                # noqa: E402
from taf_order_app import materials as m                   # noqa: E402
from taf_order_app import mounting_frames as mf            # noqa: E402
from taf_order_app import order_packing as op              # noqa: E402
from taf_order_app import packing as pk                    # noqa: E402
from taf_order_app import part_numbers as pn               # noqa: E402

JS = ROOT / "docs" / "app" / "calc.js"
SHARED = ROOT / "supabase" / "functions" / "_shared" / "calc.js"


def _settings(**changes):
    s = cs.defaults()
    for k, v in changes.items():
        s[k] = v
    return s


COMPLETE = _settings(
    cut_profiles=[
        {"id": "W", "version": 1, "kind": "wire", "verified": True,
         "constructions": ["Flat Panel"], "method": "linear",
         "width": {"from": "short", "add": -10},
         "length": {"from": "long", "add": -10},
         "pieces_per_filter": 2, "installed": "full_blank"},
        {"id": "M", "version": 1, "kind": "media", "verified": True,
         "constructions": ["Flat Panel"], "method": "flat",
         "usable_width_mm": {"from": "short"},
         "usable_length_mm": {"from": "long"},
         "pieces_per_filter": 1, "installed": "full_blank"},
        {"id": "TRI", "version": 3, "kind": "wire", "verified": True,
         "constructions": ["V-form"], "method": "triangular_v", "v_count": 4,
         "usable_span_mm": 400, "peak_to_trough_mm": 80,
         "straight_dimension_mm": {"from": "short", "add": -10},
         "length_allowances_mm": [10, 10], "width_allowances_mm": 5,
         "cut_increment_mm": {"length": 12}, "pieces_per_filter": 2},
        {"id": "SEG", "version": 1, "kind": "media", "verified": True,
         "constructions": ["V-form"], "method": "segments",
         "segments": [[30, 40], [30, 40], [0, 50]],
         "straight_dimension_mm": 500, "cut_increment_mm": 50,
         "pieces_per_filter": 1, "depth_min_mm": 200, "depth_max_mm": 300}],
    wire_rules={"Flat Panel": "SMALL_WIRE"},
    component_profiles=[{"name": "filter_frame", "id": "FR", "version": 1,
                         "verified": True, "method": "per_perimeter_m",
                         "kg_per_m": 0.5}],
    brace_profiles={"Flat Panel": {"kg_each_including_fixings": 0.35,
                                   "version": 1},
                    "V-form": {"count": 2}},
    mounting_frame_profiles=[{"id": "T", "version": 1, "verified": True,
                              "sizes": [[610, 610]],
                              "pieces": [{"name": "side", "qty": 4,
                                          "developed_flat_width_mm": 100,
                                          "retained_length_mm": 500}],
                              "hardware": [{"name": "rivet", "qty": 8,
                                            "kg_each": 0.002}]}],
    steel={"density_kg_m3": 8000, "basis": "test", "version": 1},
    packaging={"confirmed": True, "base_kg": 0.2, "per_filter_kg": 0.01},
    shipping_rounding="up_0.1")

P = lambda w=600, l=1000, n=1, **k: dict(  # noqa: E731
    {"cut_width_mm": w, "cut_length_mm": l, "pieces_per_filter": n}, **k)

CALCULATE = (
    [({"wire": {"pieces": [P()]}, "wire_material_override": "LARGE_WIRE",
       "parts": ["wire"]}, None),
     ({"wire": {"pieces": [P(n=2)], "installed": "full_blank"},
       "wire_material_override": "small", "order_quantity": 10,
       "media_components": [{"media_code": "F5", "pieces": [P()],
                             "installed": "full_blank"}]}, None)]
    + [({"media_components": [{"media_code": c, "pieces": [P()]}],
         "parts": ["media"]}, None)
       for c in ("WASH", "180", 180, "black", "gray")]
    + [({"filter_type": "V-form", "width_mm": 595, "height_mm": 595,
         "nominal_depth_mm": d, "media_code": "G4", "order_quantity": 4},
        None)
       for d in (30, 45, 50, 60, 62, 65, 75, 90, 100, 105, 150, 25)]
    + [({"filter_type": "pleated panel", "width_mm": 412, "height_mm": 412,
         "nominal_depth_mm": 90, "media_code": "G4", "parts": ["media"]},
        None)]
    + [({"filter_type": "Flat Panel", "width_mm": w, "height_mm": h,
         "nominal_depth_mm": 25, "media_code": "G4", "order_quantity": 3},
        COMPLETE)
       for w, h in ((500, 600), (701, 701), (1301, 700), (333, 444))]
    + [({"filter_type": "V-form", "width_mm": 1301, "height_mm": 701,
         "nominal_depth_mm": 90, "wire": {"profile_id": "TRI",
                                          "profile_version": 3},
         "media_code": "G4"}, COMPLETE),
       ({"filter_type": "V-form", "width_mm": 500, "height_mm": 600,
         "nominal_depth_mm": 250, "media_code": "GREY"}, COMPLETE),
       ({"filter_type": "Flyscreen", "width_mm": 800, "height_mm": 150,
         "nominal_depth_mm": 9, "media_code": "GREY"}, None),
       ({"filter_type": "Flat Panel", "width_mm": 610, "height_mm": 610,
         "nominal_depth_mm": 25, "media_code": "G4",
         "includes_mounting_frame": True,
         "components": [{"name": "clips", "kg_per_filter": 0.05},
                        {"name": "label", "not_applicable": True},
                        {"name": "glue"}]}, COMPLETE),
       ({"wire": {"pieces": [P(1300, 1300)]},
         "wire_material_override": "LARGE_WIRE", "parts": ["wire"]}, None),
       ({"wire": {"pieces": [P(1300, 900, rotation_allowed=False)]},
         "wire_material_override": "LARGE_WIRE", "parts": ["wire"]}, None),
       ({"wire": {"pieces": [P()], "installed": {
           "rule": "retained_area",
           "retained_area_mm2_per_filter": 500000}},
         "wire_material_override": "LARGE_WIRE", "parts": ["wire"]}, None),
       ({"media_components": [{"media_code": "CARBON", "pieces": [P()]}],
         "parts": ["media"]}, None),
       ({"filter_type": "Bag"}, None),
       ({"filter_type": "V-form", "width_mm": 0, "height_mm": 500}, None),
       ({"filter_type": "V-form", "width_mm": 500, "height_mm": 500,
         "order_quantity": 2.5}, None),
       ({"wire": {"pieces": [P(n=0)]}, "wire_material_override":
         "LARGE_WIRE", "parts": ["wire"]}, None),
       ({"filter_type": "V-form", "width_mm": 500, "height_mm": 500,
         "nominal_depth_mm": 90, "wire": {"profile_id": "NOPE"},
         "parts": ["wire"]}, None),
       ({"filter_type": "Header", "width_mm": 610, "height_mm": 610,
         "nominal_depth_mm": 25, "header_only": True}, None),
       ({"filter_type": "V-form", "width_mm": 595, "height_mm": 595,
         "nominal_depth_mm": 50, "pleat_insert": True, "media_code": "G4"},
        COMPLETE)]
)


def _python_cases():
    calc = [{"req": r, "settings": s} for r, s in CALCULATE]
    braces = [(k, w, h, p) for k in ("Flat Panel", "V-form", "Flyscreen",
                                     "Header", "Stepped Filter", "")
              for w, h in ((700, 700), (701, 701), (1300, 701), (1301, 700),
                           (1301, 701), (800, 150), (800, 151), (1301, 650),
                           (1301, 651), (0, 5), ("x", 5))
              for p in (None, {"count": 2})]
    frames = [(610, 610, 3, 0), (510, 455, 5, 0), (610, 610, 1, None),
              (0, 610, 1, 0), (610, 610, 2.5, 0)]
    proposals = [(12, 2.0, {"confirmed": True, "base_kg": 0}, None, None,
                  None),
                 (60, None, None, 5, None, None),
                 (60, 2.4, {"confirmed": True, "base_kg": 0.2}, 5, None,
                  None),
                 (9, 0.5, {"confirmed": True, "base_kg": 0}, 4, 3, None),
                 (20, None, None, None, None, None),
                 (1, None, None, None, None, None),
                 (3, 10.5, {"confirmed": True, "base_kg": 0.1}, None, None,
                  None),
                 (20, 1.0, {"confirmed": True, "base_kg": 0.1,
                            "per_filter_kg": 0.1}, None, 4,
                  [{"name": "Area A", "quantity": 10},
                   {"name": "Area B", "quantity": 10}]),
                 (3, 3.0, {"confirmed": True, "by_quantity":
                           {"1": 0.5, "2": 0.5, "3": 1.5}}, None, None,
                  None)]
    plans = [([{"quantity": 6}, {"quantity": 4}], 10, 2.0,
              {"confirmed": True, "base_kg": 0}, None, None, None),
             ([{"quantity": 5, "measured_weight_kg": 10.2},
               {"quantity": 5}], 10, None, None, 4, None, None),
             ([{"quantity": 10, "group": "Area A"},
               {"quantity": 10, "group": "Area B"}], 20, None, None, None,
              None, [{"name": "Area A", "quantity": 10},
                     {"name": "Area B", "quantity": 10}])]
    weights = [({"quantity": 5, "measured_weight_kg": 3.2,
                 "measured_weight_text": "3.20"}, 1.0, None, "none"),
               ({"quantity": 5}, 1.0, {"confirmed": True, "base_kg": 0.25},
                "none"),
               ({"quantity": 3}, 1.01, {"confirmed": True, "base_kg": 0.04},
                "up_0.1"),
               ({"quantity": 3}, None, {"confirmed": True}, "none"),
               ({"quantity": 3}, 1.0, None, "none"),
               ({"quantity": 2, "packaging_weight_kg": 0,
                 "packaging_confirmed": True}, 1.5, None, "none")]
    base_order = {
        "customer_name": "Complete Air Supply - Tweed Heads",
        "address_line_1": "3A/38 Enterprise Avenue", "address_line_2": "",
        "suburb": "Tweed Heads", "state": "Queensland", "postcode": "2486",
        "contact_name": "Michael", "contact_phone": "07 5513 1044",
        "order_number": "57920", "job_number": "  ",
        "items": [{"quantity": 10, "width_mm": 500, "height_mm": 600,
                   "depth_mm": 50, "wrap_quantities": [5, 5],
                   "wrap_weights_kg": [3.2, None],
                   "complete_filter_weight_kg_per_filter": 1.01},
                  {"quantity": 2, "width_mm": 500, "height_mm": 600,
                   "depth_mm": 90, "max_per_wrap": 1}]}
    bad = copy.deepcopy(base_order)
    bad.update(fax="x", postcode=2486)
    bad["items"][0]["wrap_quantities"] = [5, 4]
    single = copy.deepcopy(base_order)
    single["items"] = [{"quantity": 60, "width_mm": 412, "height_mm": 412,
                        "depth_mm": 90}]
    labels = [(base_order, "Base", None), (base_order, "Base", COMPLETE),
              (bad, "Base", None), (single, "Base", None)]
    return {"calculate": calc, "bracing": braces, "frames": frames,
            "propose": proposals, "check_plan": plans, "weights": weights,
            "labels": labels,
            "codes": [[1], [2], [5, 5, 1], [30, 1], [1, 1, 1]],
            "letters": [1, 26, 27, 52, 53, 702, 703],
            "instruction": [[3, 3, 3], [10, 10], [5] * 12, [5, 5, 2],
                            [1, 1], [5, 2, 5]],
            "media_codes": ["WASH", "180", 180, "g4", "Black", "E-MESH",
                            180.5, True, None],
            "constructions": ["pleated panel", "V Filter", "FPF", "flat",
                              "Flyscreen", "stepped", "header", "bag", ""]}


def _err(fn, *a, **k):
    try:
        return {"ok": fn(*a, **k)}
    except (pk.PackingError, dl.LabelError, m.MaterialError,
            ValueError) as exc:
        problems = getattr(exc, "problems", None)
        return {"error": problems if problems is not None else str(exc)}


def _python(cases):
    out = {"calculate": [fc.calculate(c["req"], c["settings"])
                         for c in cases["calculate"]],
           "bracing": [br.evaluate(*c) for c in cases["bracing"]],
           "frames": [mf.calculate(w, h, q, None if p is None else
                                   COMPLETE["mounting_frame_profiles"][0],
                                   COMPLETE["steel"])
                      for w, h, q, p in cases["frames"]],
           "propose": [_err(pk.propose, *c) for c in cases["propose"]],
           "check_plan": [_err(pk.check_plan, *c)
                          for c in cases["check_plan"]],
           "weights": [op.resolve_wrap_weight(*c) for c in cases["weights"]],
           "labels": [_err(dl.build, o, b, s) for o, b, s in cases["labels"]],
           "codes": [pk.wrap_codes(c) for c in cases["codes"]],
           "letters": [pk.letters(n) for n in cases["letters"]],
           "instruction": [pk.instruction(q) for q in cases["instruction"]],
           "media_codes": [_err(m.normalise_media_code, c)
                           for c in cases["media_codes"]],
           "constructions": [fc.construction_of(c)
                             for c in cases["constructions"]]}
    return out


NODE_RUNNER = r"""
const C = require(process.argv[1]);
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const P = cases._complete;
function err(fn) {
  try { return {ok: fn()}; }
  catch (e) { return {error: e.problems !== undefined ? e.problems : e.message}; }
}
const out = {
  calculate: cases.calculate.map(c => C.calculate(c.req, c.settings || undefined)),
  bracing: cases.bracing.map(c => C.bracing(c[0], c[1], c[2], c[3])),
  frames: cases.frames.map(c => C.mountingFrame(c[0], c[1], c[2],
      c[3] === null ? null : P.mounting_frame_profiles[0], P.steel)),
  propose: cases.propose.map(c => err(() => C.propose(c[0], c[1], c[2], c[3], c[4], c[5]))),
  check_plan: cases.check_plan.map(c => err(() => C.checkPlan(c[0], c[1], c[2], c[3], c[4], c[5], c[6]))),
  weights: cases.weights.map(c => C.resolveWrapWeight(c[0], c[1], c[2], c[3])),
  labels: cases.labels.map(c => err(() => C.buildLabels(c[0], c[1], c[2] || undefined))),
  codes: cases.codes.map(c => C.wrapCodes(c)),
  letters: cases.letters.map(n => C.letters(n)),
  instruction: cases.instruction.map(q => C.instruction(q)),
  media_codes: cases.media_codes.map(c => err(() => C.normaliseMediaCode(c))),
  constructions: cases.constructions.map(c => C.constructionOf(c)),
};
process.stdout.write(JSON.stringify(out));
"""


def _node() -> str:
    return shutil.which("node") or ""


def _norm(x):
    """Numbers compared as numbers (585 == 585.0), quotes compared as quotes
    (Python's repr says 'x' where JSON says "x")."""
    if isinstance(x, bool) or x is None:
        return x
    if isinstance(x, (int, float)):
        if isinstance(x, float) and math.isinf(x):
            return "inf"
        return round(float(x), 9)
    if isinstance(x, str):
        return x.replace('"', "'")
    if isinstance(x, (list, tuple)):
        return [_norm(v) for v in x]
    if isinstance(x, dict):
        return {k: _norm(v) for k, v in x.items()}
    return x


def _first_difference(a, b, path="$"):
    if type(a) is not type(b):
        return f"{path}: python {a!r} / js {b!r}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}.{k}: only in {'python' if k in a else 'js'}"
            d = _first_difference(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return ""
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: {len(a)} items in python, {len(b)} in js"
        for i, (x, y) in enumerate(zip(a, b)):
            d = _first_difference(x, y, f"{path}[{i}]")
            if d:
                return d
        return ""
    return "" if a == b else f"{path}: python {a!r} / js {b!r}"


def _run_js(cases):
    node = _node()
    payload = json.loads(json.dumps(cases, default=lambda o: None))
    payload["_complete"] = COMPLETE
    r = subprocess.run([node, "-e", NODE_RUNNER, str(JS)],
                       input=json.dumps(payload), capture_output=True,
                       text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _skip_without_node():
    if _node():
        return False
    if os.environ.get("REQUIRE_NODE"):
        raise AssertionError("node is required for the parity test here")
    print("  (node not installed - parity not checked)")
    return True


def test_python_and_javascript_give_the_same_answers():
    if _skip_without_node():
        return
    cases = _python_cases()
    py = _norm(json.loads(json.dumps(_python(cases), default=lambda o: None)))
    js = _norm(_run_js(cases))
    for section in py:
        for i, (a, b) in enumerate(zip(py[section], js[section])):
            diff = _first_difference(a, b)
            assert not diff, f"{section}[{i}] differs: {diff}"
        assert len(py[section]) == len(js[section]), section


def test_the_javascript_knows_the_same_filter_type_wordings():
    if _skip_without_node():
        return
    r = subprocess.run([_node(), "-e", "process.stdout.write(JSON.stringify("
                        "require(process.argv[1]).FILTER_TYPE_WORDINGS))",
                        str(JS)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert json.loads(r.stdout) == pn.FILTER_TYPE_WORDINGS


def test_the_api_copy_is_the_web_apps_copy():
    """An Edge Function can only bundle what is under supabase/functions,
    so it carries a copy. A copy that drifts is a second calculator."""
    assert SHARED.exists(), "supabase/functions/_shared/calc.js is missing"
    assert SHARED.read_bytes() == JS.read_bytes(), \
        "supabase/functions/_shared/calc.js differs from docs/app/calc.js"


def test_the_worksheet_profiles_are_the_same_in_both():
    if _skip_without_node():
        return
    r = subprocess.run([_node(), "-e", "process.stdout.write(JSON.stringify("
                        "require(process.argv[1]).BUILTIN_PROFILES))",
                        str(JS)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert _norm(json.loads(r.stdout)) == _norm(fc.BUILTIN_PROFILES)
