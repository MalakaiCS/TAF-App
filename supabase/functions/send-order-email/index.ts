// Supabase Edge Function: send-order-email
//
// Sends a customer their order received slip, with a link to follow the job.
//
// Two things live here rather than in the app, for the same reason the
// Anthropic key does: the mail provider's API key is a function secret and is
// never shipped inside the Windows installer, where anyone could pull it back
// out and send mail as Total Air Filtration.
//
// The other is the on/off switch. The app checks it too, so the button is
// greyed out, but a desktop that has been open since yesterday is working
// from yesterday's answer. The switch that decides whether mail actually
// leaves is this one, read fresh on every request.
//
// Deploy:
//   supabase secrets set RESEND_API_KEY=re_...
//   supabase secrets set MAIL_FROM="Total Air Filtration <orders@yourdomain>"
//   supabase secrets set PORTAL_URL="https://malakaics.github.io/TAF-App/portal/"
//   supabase functions deploy send-order-email
// (or paste this file into Supabase → Edge Functions → Deploy a new function)

import { createClient } from "npm:@supabase/supabase-js@2";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const SETTINGS_KEY = "email_settings";

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

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return json({ error: "POST only" }, 405);

  const auth = req.headers.get("Authorization") ?? "";
  if (!auth.startsWith("Bearer ")) {
    return json({ error: "Not signed in." }, 401);
  }

  const url = Deno.env.get("SUPABASE_URL")!;
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

  // Read as the caller, so the row-level security policies decide what they
  // are allowed to see. A signed-in account that cannot read an order cannot
  // use this to have its contents emailed somewhere.
  const asCaller = createClient(url, Deno.env.get("SUPABASE_ANON_KEY")!, {
    global: { headers: { Authorization: auth } },
  });
  const { data: who } = await asCaller.auth.getUser();
  if (!who?.user) return json({ error: "Not signed in." }, 401);

  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return json({ error: "Expected JSON." }, 400);
  }
  const orderId = String(body.order_id ?? "").trim();
  if (!orderId) return json({ error: "No order given." }, 400);

  // ── Is this turned on at all? ─────────────────────────────────────────────
  const admin = createClient(url, serviceKey);
  const { data: settingRow } = await admin
    .from("catalog_lists").select("value").eq("key", SETTINGS_KEY).maybeSingle();
  const settings = (settingRow?.value ?? {}) as Record<string, unknown>;
  if (settings.order_received !== true) {
    // Not an error. Nothing is wrong; nobody has switched it on.
    return json({ sent: false, reason: "Emails to customers are switched off." }, 200);
  }

  // ── The order, read as the caller ─────────────────────────────────────────
  const { data: order, error: orderErr } = await asCaller
    .from("orders")
    .select("id, customer_name, order_number, date_ordered, date_due, items, header")
    .eq("id", orderId).single();
  if (orderErr || !order) {
    return json({ error: "That order could not be read." }, 404);
  }

  // ── Where to send it ──────────────────────────────────────────────────────
  const wanted = String(order.customer_name ?? "").trim().toLowerCase();
  const { data: customers } = await asCaller
    .from("customers").select("id, name, short_name, email, portal_token");
  const customer = (customers ?? []).find((c: Record<string, unknown>) =>
    String(c.name ?? "").trim().toLowerCase() === wanted ||
    String(c.short_name ?? "").trim().toLowerCase() === wanted);

  const to = String(customer?.email ?? "").trim();
  if (!to) {
    // Also not an error: plenty of customers have no address on file, and an
    // order must never fail to be raised because of that.
    return json({ sent: false, reason: "No email address on file for this customer." }, 200);
  }

  // ── The slip ──────────────────────────────────────────────────────────────
  const items = Array.isArray(order.items) ? order.items : [];
  const rows = items.map((raw: Record<string, unknown>) => {
    const it = raw ?? {};
    const kind = String(it.item_kind ?? "filter");
    let name = String(it["Filter Type"] ?? "Filter");
    let size = [it["Short"], it["Long"], it["Channel"]].filter(Boolean).join(" × ");
    if (kind === "bag") {
      name = String(it.product_type ?? "Bag / Roll");
      size = [it.roll_width, it.roll_length].filter(Boolean).join(" × ") ||
             [it.width, it.height, it.depth].filter(Boolean).join(" × ");
    } else if (kind === "catalogue") {
      name = String(it["Description"] ?? it["Part Number"] ?? "Item");
      size = "";
    }
    const qty = it["Quantity"] ?? it.quantity ?? "";
    return `<tr>
      <td style="padding:8px 12px;border-bottom:1px solid #E3EAEF;">${esc(qty)}</td>
      <td style="padding:8px 12px;border-bottom:1px solid #E3EAEF;">${esc(name)}</td>
      <td style="padding:8px 12px;border-bottom:1px solid #E3EAEF;color:#5C6B78;">${esc(size)}</td>
    </tr>`;
  }).join("");

  const portalBase = (Deno.env.get("PORTAL_URL") ?? "").trim();
  let follow = "";
  if (portalBase && customer?.portal_token) {
    const link = `${portalBase.replace(/\/+$/, "")}/?t=${encodeURIComponent(
      String(customer.portal_token))}&k=${encodeURIComponent(
      Deno.env.get("SUPABASE_ANON_KEY")!)}`;
    follow = `<p style="margin:24px 0 0;">
      <a href="${esc(link)}" style="background:#1DA1E6;color:#fff;
         padding:11px 20px;border-radius:6px;text-decoration:none;
         display:inline-block;font-weight:600;">Follow this order</a></p>
      <p style="margin:10px 0 0;color:#5C6B78;font-size:13px;">
        The same link shows every order and quote of yours.</p>`;
  }

  const ref = String(order.order_number ?? "").trim();
  const subject = ref ? `Order received — ${ref}` : "We have your order";
  const html = `<div style="font-family:'Segoe UI',Arial,sans-serif;color:#0F1A24;
       max-width:640px;margin:0 auto;padding:28px 24px;">
    <h1 style="font-size:20px;margin:0 0 4px;">Thanks — we have your order</h1>
    <p style="margin:0 0 20px;color:#5C6B78;">
      ${esc(customer?.short_name ?? customer?.name ?? order.customer_name)}</p>
    <table style="border-collapse:collapse;font-size:14px;margin-bottom:18px;">
      ${ref ? `<tr><td style="padding:2px 16px 2px 0;color:#5C6B78;">Your order number</td>
               <td style="font-weight:600;">${esc(ref)}</td></tr>` : ""}
      ${order.date_ordered ? `<tr><td style="padding:2px 16px 2px 0;color:#5C6B78;">Received</td>
               <td>${esc(order.date_ordered)}</td></tr>` : ""}
      ${order.date_due ? `<tr><td style="padding:2px 16px 2px 0;color:#5C6B78;">Due</td>
               <td>${esc(order.date_due)}</td></tr>` : ""}
    </table>
    ${rows ? `<table style="border-collapse:collapse;width:100%;font-size:14px;">
      <thead><tr style="background:#F7FAFC;color:#40525F;text-align:left;">
        <th style="padding:8px 12px;">Qty</th><th style="padding:8px 12px;">Item</th>
        <th style="padding:8px 12px;">Size (mm)</th></tr></thead>
      <tbody>${rows}</tbody></table>` : ""}
    ${follow}
    <p style="margin:28px 0 0;color:#5C6B78;font-size:13px;line-height:1.5;">
      Total Air Filtration · Unit 1/19 Tradelink Road, Hillcrest QLD 4118<br>
      This is a confirmation that we have your order. It is not an invoice.</p>
  </div>`;

  // ── Send it ───────────────────────────────────────────────────────────────
  const apiKey = Deno.env.get("RESEND_API_KEY");
  const from = Deno.env.get("MAIL_FROM");
  if (!apiKey || !from) {
    return json({
      error: "Sending is switched on but this Supabase project has no mail " +
             "provider set up. Set RESEND_API_KEY and MAIL_FROM as function " +
             "secrets.",
    }, 500);
  }

  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from,
      to: [to],
      subject,
      html,
      reply_to: String(settings.reply_to ?? "") || undefined,
    }),
  });
  if (!res.ok) {
    const detail = await res.text();
    return json({ error: `The mail provider refused it: ${detail}` }, 502);
  }
  return json({ sent: true, to }, 200);
});
