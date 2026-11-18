// Supabase Edge Function: owner-report
//
// Last month on one page, emailed to the directors on the 1st: what came in
// and what it was worth against the target, quotes won and lost (and why),
// jobs finished and how many on time, faults, hours on the bench, who the
// biggest customers were, and stock under its minimum now.
//
// Three ways it is called:
//
//   By a manager on the PC, to look at it: {"month": "2026-09"} returns the
//   page and its figures and sends nothing.
//
//   By a manager on the PC, "Email it to me": {"month": ..., "send": true}
//   sends it to that manager only.
//
//   By the schedule, with the service-role key: {"scheduled": true}. Only on
//   the 1st in Brisbane, only with "Owner's report" switched on, only once a
//   month (owner_reports), to every approved Director and Admin. See
//   migrate_delivery_money.sql for the cron line.
//
// A signed-in account cannot ask for the scheduled send - mailing every
// director is not something an ordinary account should be able to do.
//
// Deploy:
//   supabase secrets set RESEND_API_KEY=re_...      (already set for the others)
//   supabase secrets set MAIL_FROM="Total Air Filtration <orders@yourdomain>"
//   supabase functions deploy owner-report

import { createClient, SupabaseClient } from "npm:@supabase/supabase-js@2";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const DONE = ["Complete", "Dispatched", "Delivered", "Collected"];
// Queensland has no daylight saving: Brisbane is always ten hours ahead.
const BRISBANE_MS = 10 * 60 * 60 * 1000;

type Row = Record<string, unknown>;

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

function num(v: unknown): number {
  const n = Number(v);
  return isFinite(n) ? n : 0;
}

function money(v: number): string {
  return "$" + Math.round(v).toLocaleString("en-AU");
}

// "2026-09-01" for a year and month (1-12), as text, and the month's last day.
function ymd(y: number, m: number, d: number): string {
  return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

export function monthBounds(month: string): { first: string; last: string; next: string;
                                             prev: [string, string]; name: string } {
  const [y, m] = month.split("-").map((x) => parseInt(x, 10));
  const days = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const py = m === 1 ? y - 1 : y, pm = m === 1 ? 12 : m - 1;
  const pdays = new Date(Date.UTC(py, pm, 0)).getUTCDate();
  const ny = m === 12 ? y + 1 : y, nm = m === 12 ? 1 : m + 1;
  const name = new Date(Date.UTC(y, m - 1, 1)).toLocaleString("en-AU",
    { month: "long", year: "numeric", timeZone: "UTC" });
  return { first: ymd(y, m, 1), last: ymd(y, m, days), next: ymd(ny, nm, 1),
           prev: [ymd(py, pm, 1), ymd(py, pm, pdays)], name };
}

function brisbaneToday(): Date {
  return new Date(Date.now() + BRISBANE_MS);
}

function lastMonth(): string {
  const t = brisbaneToday();
  const y = t.getUTCMonth() === 0 ? t.getUTCFullYear() - 1 : t.getUTCFullYear();
  const m = t.getUTCMonth() === 0 ? 12 : t.getUTCMonth();
  return `${y}-${String(m).padStart(2, "0")}`;
}

// A due date somebody typed: dd/mm/yyyy, dd/mm/yy, yyyy-mm-dd, or ASAP.
function dueDay(text: unknown): string | null {
  const s = String(text ?? "").trim();
  let m = s.match(/^(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{2,4})$/);
  if (m) {
    let y = parseInt(m[3], 10);
    if (y < 100) y += 2000;
    return ymd(y, parseInt(m[2], 10), parseInt(m[1], 10));
  }
  m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[1]}-${m[2]}-${m[3]}` : null;
}

// The Brisbane day of a UTC timestamp, as yyyy-mm-dd.
function localDay(iso: unknown): string {
  const t = new Date(String(iso ?? "")).getTime();
  if (!isFinite(t)) return "";
  return new Date(t + BRISBANE_MS).toISOString().slice(0, 10);
}

async function rows(q: PromiseLike<{ data: unknown; error: unknown }>): Promise<Row[] | null> {
  try {
    const { data, error } = await q;
    return error ? null : (data as Row[]) ?? [];
  } catch {
    return null;
  }
}

export async function gather(db: SupabaseClient, month: string) {
  const b = monthBounds(month);
  // A day either side in UTC, then each row is put on its Brisbane day.
  const fromUtc = new Date(Date.parse(b.prev[0]) - BRISBANE_MS).toISOString();
  const toUtc = new Date(Date.parse(b.next)).toISOString();
  const inMonth = (iso: unknown) => {
    const d = localDay(iso);
    return d >= b.first && d <= b.last;
  };
  const inPrev = (iso: unknown) => {
    const d = localDay(iso);
    return d >= b.prev[0] && d <= b.prev[1];
  };

  const values = await rows(db.from("order_values")
    .select("id, customer_name, created_at, value, unpriced")
    .gte("created_at", fromUtc).lt("created_at", toUtc).limit(10000));
  const sales = values === null ? null : (() => {
    const now = values.filter((r) => inMonth(r.created_at));
    const before = values.filter((r) => inPrev(r.created_at));
    const byCustomer: Record<string, number> = {};
    for (const r of now) {
      const who = String(r.customer_name ?? "") || "—";
      byCustomer[who] = (byCustomer[who] ?? 0) + num(r.value);
    }
    return {
      orders: now.length,
      value: now.reduce((t, r) => t + num(r.value), 0),
      unpriced: now.filter((r) => num(r.unpriced) > 0).length,
      prev_orders: before.length,
      prev_value: before.reduce((t, r) => t + num(r.value), 0),
      top: Object.entries(byCustomer).sort((x, y) => y[1] - x[1]).slice(0, 5)
        .map(([name, value]) => ({ name, value })),
    };
  })();

  const targets = await rows(db.from("sales_targets").select("target")
    .eq("month", b.first));
  const target = targets && targets.length ? num(targets[0].target) : 0;

  const quoteRows = await rows(db.from("quotes")
    .select("status, total, lost_reason, created_at")
    .gte("created_at", fromUtc).lt("created_at", toUtc).limit(5000));
  const quotes = quoteRows === null ? null : (() => {
    const now = quoteRows.filter((q) => inMonth(q.created_at));
    const reasons: Record<string, number> = {};
    for (const q of now.filter((q) => q.status === "declined")) {
      const r = String(q.lost_reason ?? "") || "No reason given";
      reasons[r] = (reasons[r] ?? 0) + 1;
    }
    const won = now.filter((q) => q.status === "accepted");
    const lost = now.filter((q) => q.status === "declined");
    return {
      sent: now.length, value: now.reduce((t, q) => t + num(q.total), 0),
      won: won.length, won_value: won.reduce((t, q) => t + num(q.total), 0),
      lost: lost.length,
      reasons: Object.entries(reasons).sort((x, y) => y[1] - x[1])
        .map(([reason, count]) => ({ reason, count })),
    };
  })();

  const finishedRows = await rows(db.from("orders")
    .select("id, date_due, header")
    .gte("header->>status_at", fromUtc).lt("header->>status_at", toUtc)
    .limit(5000));
  const jobs = finishedRows === null ? null : (() => {
    const done = finishedRows.filter((o) => {
      const h = (o.header ?? {}) as Row;
      return DONE.includes(String(h.status ?? "")) && inMonth(h.status_at);
    });
    let timed = 0, onTime = 0;
    for (const o of done) {
      const h = (o.header ?? {}) as Row;
      const due = dueDay(o.date_due ?? h["Date Due"]);
      if (!due) continue;
      timed += 1;
      if (localDay(h.status_at) <= due) onTime += 1;
    }
    return { finished: done.length, with_due: timed, on_time: onTime };
  })();

  const faultRows = await rows(db.from("returns").select("id, created_at, reason")
    .gte("created_at", fromUtc).lt("created_at", toUtc).limit(5000));
  const faults = faultRows === null ? null
    : faultRows.filter((r) => inMonth(r.created_at)).length;

  const timeRows = await rows(db.from("job_times").select("minutes, stopped_at")
    .gte("stopped_at", fromUtc).lt("stopped_at", toUtc).limit(20000));
  const hours = timeRows === null ? null
    : Math.round(timeRows.filter((t) => inMonth(t.stopped_at))
        .reduce((s, t) => s + num(t.minutes), 0) / 6) / 10;

  const stockRows = await rows(db.from("stock_items")
    .select("name, stock_on_hand, minimum_on_hand").limit(5000));
  const low = stockRows === null ? null
    : stockRows.filter((s) => num(s.minimum_on_hand) > 0 &&
                              num(s.stock_on_hand) < num(s.minimum_on_hand))
        .map((s) => String(s.name ?? ""));

  return { month, name: b.name, sales, target, quotes, jobs, faults, hours, low };
}

type Figures = Awaited<ReturnType<typeof gather>>;

function change(now: number, before: number): string {
  if (!before) return "";
  const pct = Math.round((now - before) / before * 100);
  return ` <span style="color:${pct >= 0 ? "#1E7E34" : "#B03A2E"};">
    (${pct >= 0 ? "+" : ""}${pct}% on the month before)</span>`;
}

export function build(f: Figures): string {
  const line = (label: string, value: string) =>
    `<tr><td style="padding:4px 18px 4px 0;color:#5C6B78;">${esc(label)}</td>
         <td style="padding:4px 0;">${value}</td></tr>`;
  const section = (title: string, body: string) =>
    `<h2 style="font-size:15px;margin:22px 0 6px;color:#1A4F8A;">${esc(title)}</h2>
     <table style="border-collapse:collapse;font-size:14px;">${body}</table>`;
  const parts: string[] = [];
  if (f.sales) {
    let body = line("Orders in", `${f.sales.orders}${change(f.sales.orders, f.sales.prev_orders)}`)
      + line("Worth (ex GST)", `<b>${money(f.sales.value)}</b>${change(f.sales.value, f.sales.prev_value)}`);
    if (f.target > 0) {
      const pct = Math.round(f.sales.value / f.target * 100);
      body += line("Target", `${money(f.target)} — <b>${pct}%</b>` +
                   (f.sales.value >= f.target ? " ✔ made" : ` (${money(f.target - f.sales.value)} short)`));
    }
    if (f.sales.unpriced) {
      body += line("Not fully priced", `${f.sales.unpriced} order${f.sales.unpriced === 1 ? "" : "s"} ` +
                   "had a line with no price, so are worth more than this says");
    }
    parts.push(section("Sales", body));
    if (f.sales.top.length) {
      parts.push(section("Biggest customers",
        f.sales.top.map((t) => line(t.name, money(t.value))).join("")));
    }
  }
  if (f.quotes) {
    let body = line("Quotes sent", `${f.quotes.sent} (${money(f.quotes.value)})`)
      + line("Won", `${f.quotes.won} (${money(f.quotes.won_value)})`)
      + line("Lost", String(f.quotes.lost));
    if (f.quotes.reasons.length) {
      body += line("Why lost", f.quotes.reasons.map((r) => `${esc(r.reason)} ${r.count}`).join(", "));
    }
    parts.push(section("Quotes", body));
  }
  const floor: string[] = [];
  if (f.jobs) {
    floor.push(line("Jobs finished", String(f.jobs.finished)));
    if (f.jobs.with_due) {
      floor.push(line("On time", `${Math.round(f.jobs.on_time / f.jobs.with_due * 100)}% ` +
                      `(${f.jobs.on_time} of ${f.jobs.with_due} with a due date)`));
    }
  }
  if (f.hours !== null) floor.push(line("Hours timed at the bench", String(f.hours)));
  if (f.faults !== null) floor.push(line("Faults and rework", String(f.faults)));
  if (floor.length) parts.push(section("The factory", floor.join("")));
  if (f.low !== null) {
    parts.push(section("Stock", line("Under its minimum now", f.low.length
      ? `${f.low.length}: ${esc(f.low.slice(0, 8).join(", "))}${f.low.length > 8 ? "…" : ""}`
      : "Nothing")));
  }
  return `<div style="font-family:'Segoe UI',Arial,sans-serif;color:#0F1A24;
       max-width:640px;margin:0 auto;padding:28px 24px;">
    <h1 style="font-size:20px;margin:0 0 4px;">${esc(f.name)}</h1>
    <p style="margin:0;color:#5C6B78;">The month at Total Air Filtration</p>
    ${parts.join("")}
    <p style="margin:28px 0 0;color:#5C6B78;font-size:13px;line-height:1.5;">
      Worked out from the order app. Order values are the priced lines and
      delivery fees ex GST, on the day each order was entered.</p>
  </div>`;
}

async function send(to: string[], subject: string, html: string): Promise<string[]> {
  const apiKey = Deno.env.get("RESEND_API_KEY");
  const from = Deno.env.get("MAIL_FROM");
  if (!apiKey || !from) throw new Error("This Supabase project has no mail " +
    "provider set up. Set RESEND_API_KEY and MAIL_FROM as function secrets.");
  const sent: string[] = [];
  for (const address of to) {
    // One address per message: a company's figures bcc'd to a list is one
    // wrong address away from being in a stranger's inbox.
    const res = await fetch(Deno.env.get("RESEND_API_URL") ?? "https://api.resend.com/emails", {
      method: "POST",
      headers: { "Authorization": `Bearer ${apiKey}`, "Content-Type": "application/json" },
      body: JSON.stringify({ from, to: [address], subject, html }),
    });
    if (res.ok) sent.push(address);
  }
  return sent;
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
  let body: Row = {};
  try { body = await req.json(); } catch { /* an empty body is fine */ }

  const scheduled = !!serviceKey && token === serviceKey;
  if (body.scheduled === true && !scheduled) {
    return json({ error: "Only the schedule can send to every director." }, 403);
  }

  if (scheduled) {
    const { data: sw } = await admin.from("feature_switches")
      .select("enabled").eq("key", "owner_report").maybeSingle();
    if (sw?.enabled !== true) {
      return json({ sent: 0, reason: "The owner's report is switched off." }, 200);
    }
    if (brisbaneToday().getUTCDate() !== 1 && body.force !== true) {
      return json({ sent: 0, reason: "It goes on the 1st." }, 200);
    }
    const month = lastMonth();
    const { first } = monthBounds(month);
    const { data: already } = await admin.from("owner_reports").select("month")
      .eq("month", first).maybeSingle();
    if (already) return json({ sent: 0, reason: "Already sent for that month." }, 200);
    const { data: people } = await admin.from("profiles")
      .select("email, role, approved").in("role", ["Director", "Admin"]);
    const to = ((people ?? []) as Row[])
      .filter((p) => p.approved !== false && String(p.email ?? "").trim())
      .map((p) => String(p.email).trim());
    if (!to.length) return json({ sent: 0, reason: "No director has an email address." }, 200);
    const figures = await gather(admin, month);
    let sent: string[];
    try { sent = await send(to, `${figures.name} at Total Air Filtration`, build(figures)); }
    catch (e) { return json({ error: String((e as Error).message) }, 500); }
    if (sent.length) {
      await admin.from("owner_reports").insert({ month: first, sent_to: sent, figures });
    }
    return json({ sent: sent.length, month }, 200);
  }

  // ── A manager, from the PC ────────────────────────────────────────────────
  const asCaller = createClient(url, Deno.env.get("SUPABASE_ANON_KEY")!, {
    global: { headers: { Authorization: auth } },
  });
  const { data: who } = await asCaller.auth.getUser();
  if (!who?.user) return json({ error: "Not signed in." }, 401);
  const { data: manager } = await asCaller.rpc("is_manager");
  if (manager !== true) return json({ error: "Only a manager can see the owner's report." }, 403);

  const month = /^\d{4}-\d{2}$/.test(String(body.month ?? "")) ? String(body.month) : lastMonth();
  // Read as the manager, so the database's own rules decide what is in it.
  const figures = await gather(asCaller, month);
  const html = build(figures);
  if (body.send !== true) return json({ html, figures }, 200);

  const { data: me } = await admin.from("profiles").select("email")
    .eq("id", who.user.id).maybeSingle();
  const email = String(me?.email ?? who.user.email ?? "").trim();
  if (!email) return json({ error: "There is no address on your account." }, 400);
  try {
    const sent = await send([email], `${figures.name} at Total Air Filtration`, html);
    return json({ sent: sent.length, to: email }, sent.length ? 200 : 502);
  } catch (e) {
    return json({ error: String((e as Error).message) }, 500);
  }
});
