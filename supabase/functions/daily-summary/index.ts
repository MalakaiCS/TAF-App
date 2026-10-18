// Supabase Edge Function: daily-summary
//
// A short email each morning: what is overdue, what is due today, what is
// nearly out of stock, and which repeat jobs have come round.
//
// Everything in it is already on the Dashboard. The trouble with a Dashboard
// is that it only says anything to somebody who opens it, and the morning it
// mattered most is the morning nobody did.
//
// Two ways it gets called.
//
//   By a person, from the app: "Send mine now", under Settings. Sends that
//   one person their own copy, whatever the time of day. This is also what
//   makes the whole thing useful before anybody sets up a schedule.
//
//   By the schedule, with the service-role key: sends to everybody who has
//   switched it on. See migrate_notifications.sql for the pg_cron line.
//
// A signed-in person cannot ask for the second one. Being able to mail the
// whole company is not something an ordinary account should have.
//
// Deploy:
//   supabase secrets set RESEND_API_KEY=re_...
//   supabase secrets set MAIL_FROM="Total Air Filtration <orders@yourdomain>"
//   supabase functions deploy daily-summary
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

// ── When an order is due ────────────────────────────────────────────────────
// Word for word the same as docs/app/ui.js, and a test holds them to that. A
// due date on an order is text somebody typed - dd/mm/yyyy, dd/mm/yy, or
// "ASAP" - and an email that calls an order late when the app does not is
// worse than no email.

function parseDate(text) {
  var s = String(text || "").trim();
  if (!s || /^asap$/i.test(s)) { return null; }
  var m = s.match(/^(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{2,4})$/);
  if (m) {
    var year = parseInt(m[3], 10);
    if (year < 100) { year += 2000; }
    var d = new Date(year, parseInt(m[2], 10) - 1, parseInt(m[1], 10));
    return isNaN(d.getTime()) ? null : d;
  }
  m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) {
    return new Date(parseInt(m[1], 10), parseInt(m[2], 10) - 1,
                    parseInt(m[3], 10));
  }
  return null;
}

function today() {
  var d = new Date(); d.setHours(0, 0, 0, 0); return d;
}

var DONE = ["Complete", "Dispatched", "Delivered", "Collected"];

function dueBucket(row) {
  var status = String((row && row.status) || "");
  if (DONE.indexOf(status) !== -1) { return "done"; }
  var due = parseDate(row && row.date_due);
  if (!due) { return "none"; }
  var now = today();
  var days = Math.round((due - now) / 86400000);
  if (days < 0) { return "overdue"; }
  if (days === 0) { return "today"; }
  if (days <= 7) { return "week"; }
  return "later";
}

// ── The numbers ─────────────────────────────────────────────────────────────

type Line = { customer: string; ref: string; due: string; status: string };

async function gather(admin: ReturnType<typeof createClient>) {
  const { data: rows } = await admin
    .from("orders")
    .select("customer_name, order_number, date_due, header, archived")
    .eq("archived", false)
    .order("created_at", { ascending: false })
    .limit(1000);

  const buckets: Record<string, Line[]> = { overdue: [], today: [], week: [] };
  for (const r of rows ?? []) {
    const header = (r.header ?? {}) as Record<string, unknown>;
    const line = {
      customer: String(r.customer_name ?? ""),
      ref: String(r.order_number ?? ""),
      due: String(r.date_due ?? ""),
      status: String(header.status ?? "Pending"),
    };
    const b = dueBucket(line);
    if (buckets[b]) buckets[b].push(line);
  }
  // Oldest promise first, which is the order they should be worked in.
  const age = (l: Line) => (parseDate(l.due)?.getTime() ?? 8.64e15);
  for (const key of Object.keys(buckets)) buckets[key].sort((a, b) => age(a) - age(b));

  const { data: stock } = await admin
    .from("stock_items")
    .select("name, sku, stock_on_hand, minimum_on_hand")
    .limit(2000);
  const low = (stock ?? []).filter((s: Record<string, unknown>) => {
    const min = Number(s.minimum_on_hand ?? 0);
    return min > 0 && Number(s.stock_on_hand ?? 0) <= min;
  });

  // Repeat jobs that have come round. The table is optional, so a project
  // without migrate_recurring_jobs.sql gets a summary with one section less
  // rather than an error.
  let due: Record<string, unknown>[] = [];
  try {
    const stamp = new Date().toISOString().slice(0, 10);
    const { data } = await admin
      .from("recurring_jobs")
      .select("customer_name, job, next_due")
      .eq("active", true)
      .lte("next_due", stamp)
      .limit(100);
    due = data ?? [];
  } catch { /* not set up */ }

  return { buckets, low, due };
}

function build(name: string, out: Awaited<ReturnType<typeof gather>>): string {
  const { buckets, low, due } = out;

  const list = (rows: Line[], limit: number) => rows.slice(0, limit).map((l) =>
    `<tr>
       <td style="padding:6px 12px 6px 0;">${esc(l.customer)}</td>
       <td style="padding:6px 12px 6px 0;color:#5C6B78;">${esc(l.ref)}</td>
       <td style="padding:6px 0;color:#5C6B78;">${esc(l.due)}</td>
     </tr>`).join("");

  const section = (title: string, rows: Line[], colour: string) => {
    if (!rows.length) return "";
    const more = rows.length > 10
      ? `<p style="margin:6px 0 0;color:#5C6B78;font-size:13px;">
           and ${rows.length - 10} more</p>` : "";
    return `<h2 style="font-size:15px;margin:22px 0 6px;color:${colour};">
        ${esc(title)} (${rows.length})</h2>
      <table style="border-collapse:collapse;font-size:14px;width:100%;">
        ${list(rows, 10)}</table>${more}`;
  };

  const nothing = !buckets.overdue.length && !buckets.today.length
    && !buckets.week.length && !low.length && !due.length;

  const stockRows = low.slice(0, 10).map((s: Record<string, unknown>) =>
    `<tr><td style="padding:6px 12px 6px 0;">${esc(s.name)}</td>
         <td style="padding:6px 0;color:#5C6B78;">${esc(s.stock_on_hand)} left,
           minimum ${esc(s.minimum_on_hand)}</td></tr>`).join("");

  const jobRows = due.map((j: Record<string, unknown>) =>
    `<tr><td style="padding:6px 12px 6px 0;">${esc(j.customer_name)}</td>
         <td style="padding:6px 0;color:#5C6B78;">${esc(j.job)}</td>
     </tr>`).join("");

  return `<div style="font-family:'Segoe UI',Arial,sans-serif;color:#0F1A24;
       max-width:640px;margin:0 auto;padding:28px 24px;">
    <h1 style="font-size:20px;margin:0 0 4px;">Good morning${name ? ", " + esc(name) : ""}</h1>
    <p style="margin:0 0 8px;color:#5C6B78;">Where things stand this morning.</p>
    ${nothing ? `<p style="margin:22px 0;">Nothing is overdue, nothing is due
        today, and nothing is below its minimum. A good morning.</p>` : ""}
    ${section("Overdue", buckets.overdue, "#C0392B")}
    ${section("Due today", buckets.today, "#8A6D00")}
    ${section("Due this week", buckets.week, "#1B3A5C")}
    ${low.length ? `<h2 style="font-size:15px;margin:22px 0 6px;color:#8A6D00;">
        Low on stock (${low.length})</h2>
      <table style="border-collapse:collapse;font-size:14px;width:100%;">
        ${stockRows}</table>` : ""}
    ${due.length ? `<h2 style="font-size:15px;margin:22px 0 6px;color:#1B3A5C;">
        Repeat jobs due to be raised (${due.length})</h2>
      <table style="border-collapse:collapse;font-size:14px;width:100%;">
        ${jobRows}</table>` : ""}
    <p style="margin:28px 0 0;color:#5C6B78;font-size:13px;line-height:1.5;">
      Total Air Filtration · Unit 1/19 Tradelink Road, Hillcrest QLD 4118<br>
      You are getting this because you switched it on. Turn it off under
      Settings in the app, or on your phone under your name.</p>
  </div>`;
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return json({ error: "POST only" }, 405);

  const auth = req.headers.get("Authorization") ?? "";
  if (!auth.startsWith("Bearer ")) return json({ error: "Not signed in." }, 401);
  const token = auth.slice(7).trim();

  const url = Deno.env.get("SUPABASE_URL")!;
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
  const admin = createClient(url, serviceKey);

  let body: Record<string, unknown> = {};
  try { body = await req.json(); } catch { /* an empty body is fine */ }

  // Only the schedule holds the service-role key, and only the schedule may
  // send to everybody. A signed-in account asking for that is refused rather
  // than quietly given its own copy: it asked for something it may not have,
  // and saying so is how somebody finds out why nothing arrived.
  const scheduled = !!serviceKey && token === serviceKey;
  const everyone = body.everyone === true;
  if (everyone && !scheduled) {
    return json({ error: "Only the morning schedule can send to everybody." },
                403);
  }

  // ── Is this turned on at all? ─────────────────────────────────────────────
  const { data: settingRow } = await admin
    .from("catalog_lists").select("value").eq("key", SETTINGS_KEY).maybeSingle();
  const settings = (settingRow?.value ?? {}) as Record<string, unknown>;
  if (settings.daily_summary !== true) {
    // Not an error. Nothing is wrong; nobody has switched it on.
    return json({ sent: 0, reason: "The morning summary is switched off." }, 200);
  }

  // ── Who is getting one ────────────────────────────────────────────────────
  let people: { id: string; email: string; name: string }[] = [];

  if (scheduled) {
    const { data: on } = await admin
      .from("notify_settings").select("user_id").eq("daily_summary", true);
    const ids = (on ?? []).map((r: Record<string, unknown>) => String(r.user_id));
    if (!ids.length) return json({ sent: 0, reason: "Nobody has it on." }, 200);
    const { data: rows } = await admin
      .from("profiles").select("id, email, full_name, username").in("id", ids);
    people = (rows ?? []).map((p: Record<string, unknown>) => ({
      id: String(p.id),
      email: String(p.email ?? "").trim(),
      name: String(p.full_name ?? p.username ?? "").trim(),
    })).filter((p) => p.email);
  } else {
    const asCaller = createClient(url, Deno.env.get("SUPABASE_ANON_KEY")!, {
      global: { headers: { Authorization: auth } },
    });
    const { data: who } = await asCaller.auth.getUser();
    if (!who?.user) return json({ error: "Not signed in." }, 401);
    const { data: me } = await admin
      .from("profiles").select("id, email, full_name, username")
      .eq("id", who.user.id).maybeSingle();
    const email = String(me?.email ?? who.user.email ?? "").trim();
    if (!email) return json({ error: "There is no address on your account." }, 400);
    people = [{
      id: who.user.id,
      email,
      name: String(me?.full_name ?? me?.username ?? "").trim(),
    }];
  }

  // ── Send it ───────────────────────────────────────────────────────────────
  const apiKey = Deno.env.get("RESEND_API_KEY");
  const from = Deno.env.get("MAIL_FROM");
  if (!apiKey || !from) {
    return json({
      error: "The summary is switched on but this Supabase project has no " +
             "mail provider set up. Set RESEND_API_KEY and MAIL_FROM as " +
             "function secrets.",
    }, 500);
  }

  const numbers = await gather(admin);
  const subject = numbers.buckets.overdue.length
    ? `This morning — ${numbers.buckets.overdue.length} overdue`
    : "This morning at Total Air Filtration";

  let sent = 0;
  const refused: string[] = [];
  for (const person of people) {
    // One at a time, and one address per message. A summary of the whole
    // factory bcc'd to everybody is one wrong address away from being a
    // list of every customer's late job sitting in a stranger's inbox.
    const res = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from,
        to: [person.email],
        subject,
        html: build(person.name, numbers),
        reply_to: String(settings.reply_to ?? "") || undefined,
      }),
    });
    if (res.ok) sent += 1;
    else refused.push(person.email);
  }

  // One address the provider would not take must not lose everybody else's.
  return json({ sent, refused }, 200);
});
