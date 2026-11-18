// Supabase Edge Function: proof-of-delivery
//
// The moment a customer signs for a delivery on the driver's phone, they get
// an email saying so: what was delivered, who signed, when, with the
// signature and the photos taken at the drop attached. No more "we never got
// it" a fortnight later, and nobody in the office posting dockets.
//
// The phone calls this straight after the signature is saved. It does
// nothing unless "Proof of delivery emails" is switched on (Settings ->
// Features), read fresh here on every call, and it sends one signature once:
// calling it again for the same signature says it already went.
//
// The mail provider's key is a function secret, as for every other email.
//
// Deploy:
//   supabase secrets set RESEND_API_KEY=re_...      (already set for the others)
//   supabase secrets set MAIL_FROM="Total Air Filtration <orders@yourdomain>"
//   supabase functions deploy proof-of-delivery

import { createClient } from "npm:@supabase/supabase-js@2";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const FILE_BUCKET = "order-files";
const MAX_PHOTOS = 4;
// Photos taken this long before the signature count as taken at the drop.
const DROP_WINDOW_MS = 12 * 60 * 60 * 1000;

function json(payload: unknown, status: number): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { ...CORS, "Content-Type": "application/json" },
  });
}

function esc(s: unknown): string {
  return String(s ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function base64(bytes: Uint8Array): string {
  let text = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(text);
}

function brisbane(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleString("en-AU", {
    timeZone: "Australia/Brisbane", day: "numeric", month: "long",
    year: "numeric", hour: "numeric", minute: "2-digit",
  });
}

type Row = Record<string, unknown>;

function describeLine(it: Row): [string, string, string] {
  const kind = String(it.item_kind ?? "filter");
  let name = String(it["Filter Type"] ?? "Filter");
  let size = [it["Short"], it["Long"], it["Channel"]].filter(Boolean).join(" × ");
  if (kind === "bag") {
    name = String(it.product_type ?? "Bag / Roll");
    size = [it.width, it.height, it.depth].filter(Boolean).join(" × ");
  } else if (kind === "catalogue") {
    name = String(it["Description"] ?? it["Part Number"] ?? "Item");
    size = "";
  }
  return [String(it["Quantity"] ?? it.quantity ?? ""), name, size];
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return json({ error: "POST only" }, 405);

  const auth = req.headers.get("Authorization") ?? "";
  if (!auth.startsWith("Bearer ")) return json({ error: "Not signed in." }, 401);

  const url = Deno.env.get("SUPABASE_URL")!;
  const admin = createClient(url, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
  const asCaller = createClient(url, Deno.env.get("SUPABASE_ANON_KEY")!, {
    global: { headers: { Authorization: auth } },
  });
  const { data: who } = await asCaller.auth.getUser();
  if (!who?.user) return json({ error: "Not signed in." }, 401);
  const { data: staff } = await asCaller.rpc("is_staff");
  if (staff !== true) return json({ error: "Only staff can send this." }, 403);

  let body: Row = {};
  try { body = await req.json(); } catch { /* checked below */ }
  const orderId = String(body.order_id ?? "").trim();
  if (!orderId) return json({ error: "No order given." }, 400);

  // ── Switched on? ──────────────────────────────────────────────────────────
  const { data: sw } = await admin.from("feature_switches")
    .select("enabled").eq("key", "pod_email").maybeSingle();
  if (sw?.enabled !== true) {
    return json({ sent: false, reason: "Proof of delivery emails are switched off." }, 200);
  }

  // ── The order, read as the caller ─────────────────────────────────────────
  const { data: order } = await asCaller.from("orders").select("*")
    .eq("id", orderId).maybeSingle();
  if (!order) return json({ error: "That order could not be read." }, 404);
  const header = (order.header ?? {}) as Row;

  // ── What was signed, and photographed at the drop ─────────────────────────
  const { data: fileRows } = await admin.from("order_files").select("*")
    .eq("order_id", orderId).order("created_at", { ascending: false });
  const files = (fileRows ?? []) as Row[];
  const sig = files.find((f) => f.kind === "signature");
  if (!sig) {
    return json({ error: "Nothing has been signed for on this order yet." }, 400);
  }
  const { data: before } = await admin.from("delivery_proofs").select("*")
    .eq("order_id", orderId).maybeSingle();
  if (before && before.signature_path === sig.path && before.emailed_at &&
      body.resend !== true) {
    return json({ sent: false, already: true,
                  reason: `Already emailed to ${before.emailed_to}.` }, 200);
  }
  const signedAt = new Date(String(sig.created_at ?? "")).getTime() || Date.now();
  const photos = files.filter((f) =>
    (f.kind === "photo" || f.kind === "finished") &&
    Math.abs(signedAt - (new Date(String(f.created_at ?? "")).getTime() || 0))
      <= DROP_WINDOW_MS).slice(0, MAX_PHOTOS);

  // ── Who to tell ───────────────────────────────────────────────────────────
  let customer: Row | null = null;
  if (order.customer_id) {
    const { data } = await admin.from("customers").select("*")
      .eq("id", order.customer_id).maybeSingle();
    customer = data;
  }
  if (!customer) {
    const wanted = String(order.customer_name ?? "").trim().toLowerCase();
    const { data } = await admin.from("customers")
      .select("id, name, short_name, email");
    customer = ((data ?? []) as Row[]).find((c) =>
      String(c.name ?? "").trim().toLowerCase() === wanted ||
      String(c.short_name ?? "").trim().toLowerCase() === wanted) ?? null;
  }
  const to = String(customer?.email ?? "").trim();
  if (!to) {
    return json({ sent: false, reason: "No email address on file for this customer." }, 200);
  }

  const apiKey = Deno.env.get("RESEND_API_KEY");
  const from = Deno.env.get("MAIL_FROM");
  if (!apiKey || !from) {
    return json({ error: "Proof of delivery emails are switched on but this " +
                  "Supabase project has no mail provider set up. Set " +
                  "RESEND_API_KEY and MAIL_FROM as function secrets." }, 500);
  }

  // ── The attachments ───────────────────────────────────────────────────────
  const attachments: { filename: string; content: string }[] = [];
  for (const [i, f] of [sig, ...photos].entries()) {
    const bucket = String(f.bucket ?? "") || FILE_BUCKET;
    const { data: blob } = await admin.storage.from(bucket).download(String(f.path));
    if (!blob) continue;
    const ext = String(f.path).split(".").pop() || "jpg";
    attachments.push({
      filename: f === sig ? `signature.${ext}` : `photo-${i}.${ext}`,
      content: base64(new Uint8Array(await blob.arrayBuffer())),
    });
  }

  const ref = String(order.order_number ?? header["Order Number"] ?? "").trim();
  const items = (Array.isArray(order.items) ? order.items : []) as Row[];
  const rows = items.map((it) => {
    const [qty, name, size] = describeLine(it ?? {});
    return `<tr><td style="padding:6px 12px;border-bottom:1px solid #E3EAEF;">${esc(qty)}</td>
      <td style="padding:6px 12px;border-bottom:1px solid #E3EAEF;">${esc(name)}</td>
      <td style="padding:6px 12px;border-bottom:1px solid #E3EAEF;color:#5C6B78;">${esc(size)}</td></tr>`;
  }).join("");
  const when = brisbane(String(sig.created_at ?? new Date().toISOString()));
  const signer = String(sig.signed_by ?? "").trim();
  const subject = ref ? `Delivered — ${ref}` : "Your filters have been delivered";
  const html = `<div style="font-family:'Segoe UI',Arial,sans-serif;color:#0F1A24;
       max-width:640px;margin:0 auto;padding:28px 24px;">
    <h1 style="font-size:20px;margin:0 0 4px;">Delivered</h1>
    <p style="margin:0 0 18px;color:#5C6B78;">
      ${esc(customer?.short_name || customer?.name || order.customer_name)}</p>
    <table style="border-collapse:collapse;font-size:14px;margin-bottom:18px;">
      ${ref ? `<tr><td style="padding:2px 16px 2px 0;color:#5C6B78;">Your order number</td>
               <td style="font-weight:600;">${esc(ref)}</td></tr>` : ""}
      ${header["Job"] ? `<tr><td style="padding:2px 16px 2px 0;color:#5C6B78;">Job</td>
               <td>${esc(header["Job"])}</td></tr>` : ""}
      <tr><td style="padding:2px 16px 2px 0;color:#5C6B78;">Signed for by</td>
          <td style="font-weight:600;">${esc(signer || "—")}</td></tr>
      <tr><td style="padding:2px 16px 2px 0;color:#5C6B78;">When</td>
          <td>${esc(when)}</td></tr>
    </table>
    ${rows ? `<table style="border-collapse:collapse;width:100%;font-size:14px;">
      <thead><tr style="background:#F7FAFC;color:#40525F;text-align:left;">
        <th style="padding:6px 12px;">Qty</th><th style="padding:6px 12px;">Item</th>
        <th style="padding:6px 12px;">Size (mm)</th></tr></thead>
      <tbody>${rows}</tbody></table>` : ""}
    <p style="margin:18px 0 0;color:#5C6B78;font-size:13px;">
      The signature${photos.length ? " and photos from the delivery are" : " is"} attached.</p>
    <p style="margin:28px 0 0;color:#5C6B78;font-size:13px;line-height:1.5;">
      Total Air Filtration · Unit 1/19 Tradelink Road, Hillcrest QLD 4118<br>
      If anything is not right with this delivery, reply to this email.</p>
  </div>`;

  const res = await fetch(Deno.env.get("RESEND_API_URL") ?? "https://api.resend.com/emails", {
    method: "POST",
    headers: { "Authorization": `Bearer ${apiKey}`, "Content-Type": "application/json" },
    body: JSON.stringify({ from, to: [to], subject, html, attachments }),
  });
  if (!res.ok) {
    return json({ error: `The mail provider refused it: ${await res.text()}` }, 502);
  }

  await admin.from("delivery_proofs").upsert({
    order_id: orderId, signature_path: String(sig.path), signed_by: signer,
    emailed_to: to, emailed_at: new Date().toISOString(), photos: photos.length,
  });
  return json({ sent: true, to, photos: photos.length }, 200);
});
