// Supabase Edge Function: filter-calculator
//
// The weight calculator, bracing rules, packing planner and delivery-label
// numbering, for other programs. The same rules the desktop app and the web
// app use: the calculation is ../_shared/calc.js, which is a byte-for-byte
// copy of docs/app/calc.js, and tests/test_calc_parity.py holds that file to
// the desktop's Python answer for answer.
//
// Who may call it: approved staff, signed in. The caller's own token is used
// to read the shared settings (calc_settings), so row-level security decides
// what they can see and nothing here uses the service role.
//
// POST /functions/v1/filter-calculator  with a JSON body:
//
//   {"action": "calculate", "request": {...}}      one order line, as fields
//   {"action": "calculate", "item": {...}}         one saved order line
//   {"action": "bracing", "construction": "Flat Panel",
//                         "width_mm": 1301, "height_mm": 700}
//   {"action": "mounting_frame", "width_mm": 610, "height_mm": 610,
//                                "quantity": 2}
//   {"action": "pack", "quantity": 60, "width_mm": 412, "height_mm": 412,
//                      "depth_mm": 90, "unit_kg": 1.9,
//                      "max_per_wrap": null, "groups": null,
//                      "wraps": null}      wraps given = check that plan
//   {"action": "labels", "order": {...}}           the label data contract
//   {"action": "settings"}                         what is in force, with
//                                                  versions
//
// C-channel (the same calculator the frames, stock and labels use):
//   {"action": "c_channel_weight", "nominal_depth_mm": 45,
//                                  "centre_width_mm": null, "length_mm": 2440,
//                                  "stacks": [1, 2, 5, 10, 20]}
//   {"action": "c_channel_table", "stacks": [1, 2, 5, 10]}   every depth
//   {"action": "c_channel_frame", "short_mm": 595, "long_mm": 595,
//                                 "nominal_depth_mm": 25, "method": "g",
//                                 "order_quantity": 10}
//                     or "cut_list": [{"nominal_depth_mm": 25,
//                                      "cut_length_mm": 1819,
//                                      "section_quantity": 1}, ...]
//   {"action": "c_channel_stock", "nominal_depth_mm": 45, "lengths": 10}
//
// Answers are JSON. Weights are plain kg numbers at full precision; nothing
// is rounded for display except the label weight text, which follows the
// company's shipping-rounding setting exactly as the printed label does.
// Bad input answers 422 with every problem listed.
//
// Deploy:  supabase functions deploy filter-calculator

import { createClient } from "npm:@supabase/supabase-js@2";
import "../_shared/calc.js";

// deno-lint-ignore no-explicit-any
const C: any = (globalThis as any).TAFCALC;

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function json(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status, headers: { ...CORS, "Content-Type": "application/json" },
  });
}

// deno-lint-ignore no-explicit-any
function problems(err: any): string[] {
  if (err && Array.isArray(err.problems)) return err.problems;
  return [String(err?.message ?? err)];
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return json({ error: "POST a JSON body." }, 405);

  const auth = req.headers.get("Authorization") ?? "";
  if (!auth.startsWith("Bearer ")) return json({ error: "Not signed in." }, 401);
  const asCaller = createClient(Deno.env.get("SUPABASE_URL")!,
                                Deno.env.get("SUPABASE_ANON_KEY")!,
                                { global: { headers: { Authorization: auth } } });
  const { data: who } = await asCaller.auth.getUser();
  if (!who?.user) return json({ error: "Not signed in." }, 401);
  const { data: staff } = await asCaller.rpc("is_staff");
  if (staff !== true) {
    return json({ error: "This account has not been approved yet." }, 403);
  }

  // deno-lint-ignore no-explicit-any
  let body: any;
  try {
    body = await req.json();
  } catch {
    return json({ error: "The body has to be JSON." }, 400);
  }

  // The shared numbers, read once for this request, as this caller.
  const { data: rows, error: readErr } = await asCaller
    .from("calc_settings").select("key,value,version");
  if (readErr && !/calc_settings/.test(readErr.message)) {
    return json({ error: readErr.message }, 502);
  }
  const settings = C.mergeSettings(rows ?? []);
  const meta = {
    calc_version: C.CALC_VERSION,
    settings_versions: settings.versions,
  };

  try {
    switch (body?.action) {
      case "calculate": {
        const result = body.item
          ? C.calculateItem(body.item, settings)
          : C.calculate(body.request ?? {}, settings);
        const status = result.status === "invalid_input" ? 422 : 200;
        return json({ ...meta, result }, status);
      }
      case "bracing": {
        const construction = C.constructionOf(body.construction);
        const result = C.bracing(construction, body.width_mm, body.height_mm,
                                 (settings.brace_profiles ?? {})[construction]);
        return json({ ...meta, result },
                    result.status === "invalid_input" ? 422 : 200);
      }
      case "mounting_frame": {
        const w = C.positive(body.width_mm) ?? 0;
        const h = C.positive(body.height_mm) ?? 0;
        const profile = C.mountingFrameProfile(w, h,
                                               settings.mounting_frame_profiles);
        const result = C.mountingFrame(body.width_mm, body.height_mm,
                                       body.quantity ?? 1, profile,
                                       settings.steel);
        return json({ ...meta, result },
                    result.status === "invalid_input" ? 422 : 200);
      }
      case "pack": {
        const handling = C.handlingLimit(body.width_mm, body.height_mm,
                                         body.depth_mm,
                                         C.constructionOf(body.construction),
                                         settings.handling_profiles);
        const max = settings.max_bundle_kg;
        const result = Array.isArray(body.wraps)
          ? C.checkPlan(body.wraps, body.quantity, body.unit_kg ?? null,
                        settings.packaging,
                        handling ? handling.max_per_wrap : null,
                        body.max_per_wrap ?? null, body.groups ?? null, max)
          : C.propose(body.quantity, body.unit_kg ?? null, settings.packaging,
                      handling ? handling.max_per_wrap : null,
                      body.max_per_wrap ?? null, body.groups ?? null, max,
                      settings.default_max_per_wrap);
        return json({ ...meta, handling_profile: handling, result });
      }
      case "labels": {
        const base = C.baseAddress(settings);
        const labels = C.buildLabels(body.order ?? {}, base, settings);
        return json({ ...meta, base_address: base, labels });
      }
      case "settings":
        return json({ ...meta, settings });
      case "c_channel_weight": {
        const result = C.calculateCChannelWeight(
          body.nominal_depth_mm ?? null, body.centre_width_mm ?? null,
          body.length_mm ?? null, settings, body.material_code ?? null,
          body.left_flange_mm ?? null, body.right_flange_mm ?? null);
        result.stacks = C.calculateCChannelStackWeights(result,
                                                        body.stacks ?? null);
        return json({ ...meta, result },
                    result.calculation_status === "ok" ? 200 : 422);
      }
      case "c_channel_table":
        return json({ ...meta,
                      result: C.cChannelTable(settings, body.stacks ?? null) });
      case "c_channel_frame": {
        const cut = Array.isArray(body.cut_list) ? body.cut_list
          : C.frameCutList(body.short_mm, body.long_mm, body.method ?? "u",
                           body.nominal_depth_mm ?? null);
        const result = C.calculateCChannelFrameWeight(
          cut, body.order_quantity ?? 1, settings);
        return json({ ...meta, result },
                    result.calculation_status === "invalid_input" ? 422 : 200);
      }
      case "c_channel_stock": {
        const result = C.calculateCChannelStockWeight(
          body.nominal_depth_mm ?? null, body.lengths ?? 1,
          body.length_mm ?? null, body.centre_width_mm ?? null, settings,
          body.material_code ?? null);
        return json({ ...meta, result },
                    result.calculation_status === "ok" ? 200 : 422);
      }
      default:
        return json({ error: "Unknown action. Use calculate, bracing, " +
                             "mounting_frame, pack, labels, settings, " +
                             "c_channel_weight, c_channel_table, " +
                             "c_channel_frame or c_channel_stock." }, 400);
    }
  } catch (err) {
    return json({ ...meta, error: "The request could not be worked out.",
                  problems: problems(err) }, 422);
  }
});
