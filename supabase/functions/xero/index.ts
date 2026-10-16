// Supabase Edge Function: xero
//
// Xero, linked for good. One connection for the whole company, made once by
// a manager; every staff account works through it from then on. It runs one
// of two ways (xero_connection.mode):
//
//   TRIAL ('manual', where it starts): nothing goes by itself. The button on
//   an order sends it - as a draft, or invoiced there and then (approved and
//   emailed by Xero to the contact on file), after which the app marks the
//   order Complete.
//
//   AUTOMATIC ('automatic', published by a manager after the trial):
//   * Each order goes to Xero as a DRAFT sales invoice, dated the day on the
//     work order, and is kept up to date while it is still a draft.
//   * When the job is marked Complete (or Dispatched) - from any PC, phone or
//     screen - the invoice is dated that day, approved, and emailed by Xero to
//     the contact on file there.
//
// A part number Xero has no item for is made an item in Xero (code, name and
// sales description), so every line carries an item code.
//
// Everything about Xero that is a secret lives here and only here. The client
// secret is a function secret; the sign-in (access and refresh tokens) is in
// the xero_connection table, which no app account can read or write - only
// this function, with the service role. Neither goes near the installer or a
// browser. These are the keys that move money.
//
// Pricing an order needs the price list and the part-number rules, which live
// in the desktop app, so the app prices each order and hands the lines here
// (do=draft). Completion is noted by a trigger on orders (migrate_xero_link.sql,
// step 37), so it does not matter which screen marked the job; do=sweep then
// approves and emails whatever is waiting.
//
// Actions (?do=...):
//
//   status      connected or not, to which organisation, mode  staff
//   mode        trial ('manual') or 'automatic'                 manager
//   start       the URL a manager signs in to Xero at           manager
//   finish      where Xero sends them back                      (Xero)
//   disconnect  end the link                                    manager
//   draft       make or update one order's draft invoice; with
//               invoice_now, approve and email it there and then staff
//   sweep       approve and email completed jobs; take deleted
//               orders' drafts back out                         staff, or the
//                                                               service role
//   retry       try one order again now                         staff
//   list        where each order's invoice is up to             staff
//   pdf         an order's invoice as Xero prints it            staff
//   contacts    Xero contacts matching a search, to link a
//               customer to theirs                              staff
//   owing       what is outstanding in Xero                     staff
//
// Deploy:
//   supabase secrets set XERO_CLIENT_ID=...
//   supabase secrets set XERO_CLIENT_SECRET=...
//   supabase secrets set XERO_REDIRECT_URI=https://<project>.supabase.co/functions/v1/xero
//   supabase functions deploy xero --no-verify-jwt
//
// --no-verify-jwt because Xero sends the person back to `finish` in a
// browser, with no app sign-in. Every other action checks the caller here.
//
// Optional secrets: XERO_ACCOUNT_CODE (default 200, Sales), XERO_TAX_TYPE
// (default OUTPUT, GST on Income), XERO_CREATE_ITEMS=false to stop part
// numbers being made items in Xero, and XERO_SCOPES.

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
};

// What the app may do in Xero, asked for once when a manager connects.
// Xero's granular scopes - an app made since 2 March 2026 is refused the old
// broad accounting.transactions ("invalid_scope"), and older apps must move
// by September 2027:
//   accounting.invoices  sales invoices (make, approve, email) and, later,
//                        purchase orders
//   accounting.contacts  find customers now; create them later
//   accounting.settings  items (made for new part numbers) and the
//                        organisation's payment terms
// Asking for all of it now means adding those later needs no reconnecting.
// XERO_SCOPES overrides it.
const SCOPES = () => env("XERO_SCOPES",
  "offline_access accounting.invoices accounting.contacts " +
  "accounting.settings");
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const MINUTE = 60_000;

const env = (k: string, d = "") => Deno.env.get(k) ?? d;
const SB = () => env("SUPABASE_URL").replace(/\/+$/, "");
const SERVICE = () => env("SUPABASE_SERVICE_ROLE_KEY");
const API = () => env("XERO_API_BASE", "https://api.xero.com").replace(/\/+$/, "");
const IDENTITY = () =>
  env("XERO_IDENTITY_BASE", "https://identity.xero.com").replace(/\/+$/, "");
const LOGIN = () =>
  env("XERO_LOGIN_URL", "https://login.xero.com/identity/connect/authorize");
const ACCOUNT = () => env("XERO_ACCOUNT_CODE", "200");
const TAX = () => env("XERO_TAX_TYPE", "OUTPUT");

// deno-lint-ignore no-explicit-any
type Any = any;
type Row = Record<string, Any>;

function json(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status, headers: { ...CORS, "Content-Type": "application/json" },
  });
}

function text(body: string, status = 200): Response {
  return new Response(body, {
    status, headers: { ...CORS, "Content-Type": "text/plain; charset=utf-8" },
  });
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const nowIso = () => new Date().toISOString();
const later = (ms: number) => new Date(Date.now() + ms).toISOString();

/** Today in Brisbane (no daylight saving, so always UTC+10). */
function today(): string {
  return new Date(Date.now() + 10 * 3600_000).toISOString().slice(0, 10);
}

/** A problem that is not a fault - not connected, no contact, and so on. */
class Problem extends Error {
  status: number;
  constructor(message: string, status = 0) {
    super(message);
    this.status = status;
  }
}


// ── The database, as the service role ───────────────────────────────────────

async function rpc<T = Any>(name: string, args: Row = {}): Promise<T> {
  const res = await fetch(`${SB()}/rest/v1/rpc/${name}`, {
    method: "POST",
    headers: {
      apikey: SERVICE(), Authorization: `Bearer ${SERVICE()}`,
      "Content-Type": "application/json", Accept: "application/json",
    },
    body: JSON.stringify(args),
  });
  const body = await res.text();
  if (!res.ok) {
    throw new Error(`The database said ${res.status}: ${body.slice(0, 200)}` +
      (body.includes("xero_") ? " - has migrate_xero_link.sql (step 37) been run?" : ""));
  }
  return (body ? JSON.parse(body) : null) as T;
}

const conn = async (): Promise<Row> => (await rpc<Row>("xero_conn_get")) ?? {};
const connPut = (patch: Row) => rpc("xero_conn_put", { p_patch: patch });

async function put(order: string, patch: Row): Promise<Row> {
  const rows = await rpc<Row[]>("xero_invoice_put", { p_order: order, p_patch: patch });
  return rows?.[0] ?? {};
}

async function claim(order: string, seconds = 120): Promise<Row | null> {
  const rows = await rpc<Row[]>("xero_claim", { p_order: order, p_seconds: seconds });
  return rows?.[0] ?? null;
}


// ── Who is asking ───────────────────────────────────────────────────────────

type Who = { id: string; staff: boolean; manager: boolean; system: boolean };

async function caller(req: Request): Promise<Who | null> {
  const auth = req.headers.get("Authorization") ?? "";
  if (!auth.startsWith("Bearer ")) return null;
  if (SERVICE() && auth === `Bearer ${SERVICE()}`) {
    return { id: "", staff: false, manager: false, system: true };
  }
  const res = await fetch(`${SB()}/auth/v1/user`, {
    headers: { apikey: env("SUPABASE_ANON_KEY"), Authorization: auth },
  });
  if (!res.ok) return null;
  const user = await res.json().catch(() => ({}));
  if (!user?.id) return null;
  const who = await rpc<Row>("xero_who", { p_uid: user.id });
  return { id: user.id, staff: !!who?.staff, manager: !!who?.manager, system: false };
}


// ── The sign-in to Xero ─────────────────────────────────────────────────────

function basic(): string {
  return btoa(`${env("XERO_CLIENT_ID")}:${env("XERO_CLIENT_SECRET")}`);
}

const NOT_CONNECTED =
  "Xero is not connected yet. A manager connects it from the Xero screen.";
const ENDED =
  "Xero ended the connection - it was disconnected in Xero, or not used for " +
  "60 days. A manager needs to press Connect again. Orders keep queuing and " +
  "go through once it is back.";

/** A live access token. `stale` is one Xero has just refused.
 *
 *  Xero's refresh tokens work once: every renewal hands back a new one and
 *  ends the old. Two requests renewing at the same moment would have the
 *  second end the connection - the old version of this did exactly that, and
 *  then wiped the token. So one renewal at a time (xero_conn_begin_refresh),
 *  the others wait for its result, and a refusal only ends the connection
 *  when nobody has renewed in the meantime. */
async function token(stale = ""): Promise<string> {
  for (let i = 0; i < 40; i++) {
    const c = await conn();
    if (!c.refresh_token) throw new Problem(c.problem || NOT_CONNECTED);
    const expires = c.expires_at ? Date.parse(c.expires_at) : 0;
    if (c.access_token && c.access_token !== stale && expires > Date.now() + MINUTE) {
      return c.access_token;
    }
    const old = await rpc<string | null>("xero_conn_begin_refresh", { p_seconds: 30 });
    if (!old) {
      await sleep(500);
      continue;
    }
    let res: Response;
    try {
      res = await fetch(`${IDENTITY()}/connect/token`, {
        method: "POST",
        headers: { Authorization: `Basic ${basic()}`,
                   "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ grant_type: "refresh_token", refresh_token: old }),
      });
    } catch {
      await rpc("xero_conn_end_refresh", { p_old: old, p_patch: {} });
      throw new Problem("Could not reach Xero to renew the connection. It will try again.");
    }
    const got = await res.json().catch(() => ({}));
    if (res.ok && got.access_token && got.refresh_token) {
      await rpc("xero_conn_end_refresh", { p_old: old, p_patch: {
        access_token: got.access_token,
        refresh_token: got.refresh_token,
        expires_at: later(Number(got.expires_in ?? 1800) * 1000),
        refreshed_at: nowIso(),
        problem: null,
      } });
      return String(got.access_token);
    }
    if (got?.error === "invalid_grant") {
      const now = await conn();
      if (now.refresh_token && now.refresh_token !== old) continue;
      await rpc("xero_conn_end_refresh", { p_old: old, p_patch: {
        access_token: null, refresh_token: null, expires_at: null, problem: ENDED,
      } });
      throw new Problem(ENDED);
    }
    await rpc("xero_conn_end_refresh", { p_old: old, p_patch: {} });
    throw new Problem(`Xero would not renew the connection just now (${res.status}). ` +
                      "It will try again.");
  }
  throw new Problem("Another request is renewing the Xero connection. It will try again.");
}

async function tenant(access: string): Promise<string> {
  const c = await conn();
  if (c.tenant_id) return String(c.tenant_id);
  const res = await fetch(`${API()}/connections`, {
    headers: { Authorization: `Bearer ${access}`, Accept: "application/json" },
  });
  const rows = await res.json().catch(() => []);
  const first = Array.isArray(rows) ? rows[0] : null;
  if (!first?.tenantId) throw new Problem("No Xero organisation is connected.");
  await connPut({ tenant_id: first.tenantId, tenant_name: first.tenantName ?? "" });
  return String(first.tenantId);
}

function why(out: Any, status: number): string {
  const v = (out?.Elements ?? []).flatMap((e: Any) =>
    (e?.ValidationErrors ?? []).map((x: Any) => x?.Message)).filter(Boolean);
  if (v.length) return [...new Set(v)].join("; ");
  if (status === 429) return "Xero is busy (too many requests). It will try again shortly.";
  return out?.Message || out?.Detail || out?.Title || `Xero said ${status}`;
}

/** One call to Xero's accounting API, as the connected organisation. */
async function xero(method: string, path: string, body?: unknown,
                    extra: Record<string, string> = {}): Promise<Any> {
  let access = await token();
  for (let attempt = 0; attempt < 2; attempt++) {
    const org = await tenant(access);
    const res = await fetch(`${API()}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${access}`, "Xero-tenant-id": org,
        Accept: "application/json",
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...extra,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (res.status === 401 && attempt === 0) {
      access = await token(access);
      continue;
    }
    const raw = await res.text();
    let out: Any = {};
    try {
      out = raw ? JSON.parse(raw) : {};
    } catch {
      out = { Message: raw.slice(0, 200) };
    }
    if (!res.ok) throw new Problem(why(out, res.status), res.status);
    return out;
  }
  throw new Problem("Xero would not accept the connection's sign-in.", 401);
}


// ── Xero's records ──────────────────────────────────────────────────────────

/** The invoice as Xero prints it - the PDF the customer gets. */
async function invoicePdf(id: string): Promise<ArrayBuffer> {
  let access = await token();
  for (let attempt = 0; attempt < 2; attempt++) {
    const org = await tenant(access);
    const res = await fetch(`${API()}/api.xro/2.0/Invoices/${encodeURIComponent(id)}`, {
      headers: { Authorization: `Bearer ${access}`, "Xero-tenant-id": org,
                 Accept: "application/pdf" },
    });
    if (res.status === 401 && attempt === 0) {
      access = await token(access);
      continue;
    }
    if (!res.ok) {
      const raw = await res.text();
      let out: Any = {};
      try { out = JSON.parse(raw); } catch { out = { Message: raw.slice(0, 200) }; }
      throw new Problem(why(out, res.status), res.status);
    }
    return await res.arrayBuffer();
  }
  throw new Problem("Xero would not accept the connection's sign-in.", 401);
}

async function getInvoice(id: string): Promise<Row | null> {
  try {
    const out = await xero("GET", `/api.xro/2.0/Invoices/${encodeURIComponent(id)}`);
    return out?.Invoices?.[0] ?? null;
  } catch (e) {
    if ((e as Problem).status === 404) return null;
    throw e;
  }
}

async function getContact(id: string | undefined): Promise<Row | null> {
  if (!id) return null;
  try {
    const out = await xero("GET", `/api.xro/2.0/Contacts/${encodeURIComponent(id)}`);
    return out?.Contacts?.[0] ?? null;
  } catch (e) {
    if ((e as Problem).status === 404) return null;
    throw e;
  }
}

/** The contact an order's customer is in Xero: by name, ignoring case,
 *  trying the legal name, the name and the short name in turn. A contact is
 *  never made up here - one with no email address would only fail later,
 *  when the invoice is to be sent. */
async function findContact(names: string[]): Promise<Row | null> {
  const seen = new Set<string>();
  for (const raw of names) {
    const name = String(raw ?? "").trim().toLowerCase();
    if (!name || seen.has(name)) continue;
    seen.add(name);
    const out = await xero("GET", "/api.xro/2.0/Contacts?searchTerm=" +
      encodeURIComponent(name));
    const found = (out?.Contacts ?? []).filter((c: Row) =>
      c?.ContactStatus !== "ARCHIVED" &&
      String(c?.Name ?? "").trim().toLowerCase() === name);
    if (found.length) return found[0];
  }
  return null;
}

let itemCache: { at: number; codes: Map<string, string> } | null = null;

/** Xero's item codes, upper-cased to the code as Xero has it. A code Xero
 *  does not know would fail the whole invoice, so only known ones are sent;
 *  the description says what the line is either way. */
async function itemCodes(): Promise<Map<string, string>> {
  if (itemCache && Date.now() - itemCache.at < 10 * MINUTE) return itemCache.codes;
  const codes = new Map<string, string>();
  try {
    const out = await xero("GET", "/api.xro/2.0/Items");
    for (const it of out?.Items ?? []) {
      if (it?.Code) codes.set(String(it.Code).toUpperCase(), String(it.Code));
    }
  } catch {
    return codes;           // none sent rather than none invoiced
  }
  itemCache = { at: Date.now(), codes };
  return codes;
}

let orgTermsCache: { at: number; terms: Row | null } | null = null;

async function orgTerms(): Promise<Row | null> {
  if (orgTermsCache && Date.now() - orgTermsCache.at < 30 * MINUTE) {
    return orgTermsCache.terms;
  }
  let terms: Row | null = null;
  try {
    const out = await xero("GET", "/api.xro/2.0/Organisation");
    terms = out?.Organisations?.[0]?.PaymentTerms?.Sales ?? null;
  } catch {
    terms = null;
  }
  orgTermsCache = { at: Date.now(), terms };
  return terms;
}


// ── Due dates ───────────────────────────────────────────────────────────────

/** The app's own wording of a customer's terms, for when Xero has none for
 *  the contact or the organisation: "Net 30", "COD", "EOM", "Prepaid". */
function appTerms(words: unknown): Row | null {
  const t = String(words ?? "").trim().toUpperCase();
  const net = t.match(/(\d+)/);
  if (t.startsWith("NET") && net) return { Type: "DAYSAFTERBILLDATE", Day: Number(net[1]) };
  if (t === "COD" || t === "PREPAID") return { Type: "DAYSAFTERBILLDATE", Day: 0 };
  if (t === "EOM") return { Type: "OFFOLLOWINGMONTH", Day: 31 };
  return null;
}

/** When an invoice dated `date` is due, by Xero's kinds of terms. */
function dueDate(date: string, terms: Row | null): string {
  const [y, m, d] = date.split("-").map(Number);
  const day = Math.max(0, Number(terms?.Day ?? 30));
  const last = (yy: number, mm: number) => new Date(Date.UTC(yy, mm + 1, 0)).getUTCDate();
  let out: Date;
  switch (terms ? String(terms.Type ?? "") : "") {
    case "DAYSAFTERBILLMONTH":
      out = new Date(Date.UTC(y, m - 1, last(y, m - 1) + day));
      break;
    case "OFCURRENTMONTH":
      out = new Date(Date.UTC(y, m - 1, Math.max(d, Math.min(day || 1, last(y, m - 1)))));
      break;
    case "OFFOLLOWINGMONTH":
      out = new Date(Date.UTC(y, m, Math.min(day || 1, last(y, m))));
      break;
    case "DAYSAFTERBILLDATE":
      out = new Date(Date.UTC(y, m - 1, d + day));
      break;
    default:
      out = new Date(Date.UTC(y, m - 1, d + 30));
  }
  return out.toISOString().slice(0, 10);
}

async function dueFor(date: string, contact: Row | null, words: unknown) {
  return dueDate(date, contact?.PaymentTerms?.Sales ?? await orgTerms() ?? appTerms(words));
}


// ── One order ───────────────────────────────────────────────────────────────

const FINISHED = ["approved", "sent", "deleted", "gone"];

type Line = { description: string; quantity: number; unit_amount: number;
              item_code?: string };

function readInvoice(raw: Any): { ok: true; inv: Row } | { ok: false; error: string } {
  if (!raw || typeof raw !== "object") return { ok: false, error: "No invoice was given." };
  const clean = (list: Any, priced: boolean): Line[] | null => {
    if (!Array.isArray(list) || list.length > 500) return null;
    const out: Line[] = [];
    for (const l of list) {
      const q = Number(l?.quantity), u = Number(priced ? l?.unit_amount : 0);
      if (!Number.isFinite(q) || q <= 0 || !Number.isFinite(u) || u < 0) return null;
      out.push({ description: String(l?.description ?? "").slice(0, 3900) || "Filter",
                 quantity: q, unit_amount: Math.round(u * 10000) / 10000,
                 // Never shortened: a cut-down code is a different item.
                 // One too long for Xero (30) just goes without.
                 item_code: String(l?.item_code ?? "").trim().slice(0, 64) });
    }
    return out;
  };
  const lines = clean(raw.lines ?? [], true);
  const unpriced = clean(raw.unpriced ?? [], false);
  if (!lines || !unpriced) return { ok: false, error: "The invoice lines are not right." };
  if (!lines.length && !unpriced.length) return { ok: false, error: "The order has no lines." };
  return { ok: true, inv: {
    // The customer's own link to their Xero contact, when they have one.
    contact_id: /^[0-9a-f-]{36}$/i.test(String(raw.contact_id ?? ""))
      ? String(raw.contact_id) : "",
    contact_names: (Array.isArray(raw.contact_names) ? raw.contact_names : [])
      .slice(0, 6).map((n: unknown) => String(n ?? "").slice(0, 200)),
    date: DAY.test(String(raw.date ?? "")) ? String(raw.date) : today(),
    number: String(raw.number ?? "").trim().slice(0, 255),
    reference: String(raw.reference ?? "").trim().slice(0, 255),
    terms: String(raw.terms ?? "").slice(0, 40),
    lines, unpriced,
  } };
}

/** Make the part numbers Xero has no item for into items, so the line can
 *  carry its code. Never a reason for the invoice to fail: an item Xero will
 *  not take is simply left off the line, as before. */
async function makeItems(lines: Line[], codes: Map<string, string>) {
  if (env("XERO_CREATE_ITEMS", "true").toLowerCase() === "false") return;
  const wanted = new Map<string, Line>();
  for (const l of lines) {
    const code = (l.item_code ?? "").trim();
    if (!code || code.length > 30 || codes.has(code.toUpperCase())) continue;
    wanted.set(code.toUpperCase(), { ...l, item_code: code });
  }
  if (!wanted.size) return;
  const items = [...wanted.values()].map((l) => ({
    Code: l.item_code,
    Name: (l.description.split("\n")[0] || l.item_code!).slice(0, 50),
    Description: l.description.slice(0, 4000),
    IsSold: true,
    IsPurchased: false,
    SalesDetails: { AccountCode: ACCOUNT(), TaxType: TAX() },
  }));
  try {
    const out = await xero("POST", "/api.xro/2.0/Items?summarizeErrors=false",
                           { Items: items });
    for (const it of out?.Items ?? []) {
      const failed = (it?.ValidationErrors ?? []).length > 0;
      if (it?.Code && !failed) codes.set(String(it.Code).toUpperCase(), String(it.Code));
    }
  } catch {
    // No permission to make items (an older connection), or Xero refused:
    // the lines go without codes.
  }
}

async function lineItems(inv: Row) {
  const codes = await itemCodes();
  await makeItems(inv.lines, codes);
  const one = (l: Line, desc: string) => {
    const item: Row = { Description: desc, Quantity: l.quantity,
                        UnitAmount: l.unit_amount, AccountCode: ACCOUNT(),
                        TaxType: TAX() };
    const code = codes.get((l.item_code ?? "").toUpperCase());
    if (code) item.ItemCode = code;
    return item;
  };
  return [
    ...inv.lines.map((l: Line) => one(l, l.description)),
    ...inv.unpriced.map((l: Line) => one(l, `NO PRICE - ${l.description}`)),
  ];
}

/** Hand an invoice somebody has taken over in Xero back to them. */
async function handOver(row: Row, cur: Row | null) {
  const status = String(cur?.Status ?? "deleted").toLowerCase();
  const error = cur
    ? `It was ${status} by hand in Xero, so the app has left it alone.`
    : "The invoice is no longer in Xero, so the app has left it alone.";
  await put(row.order_id, { state: "gone", error, claimed_until: null });
  return { state: "gone", error };
}

async function draftOne(row: Row, inv: Row, hash: string, md5: string | null,
                        now = false) {
  if (FINISHED.includes(row.state) || row.delete_wanted) {
    await put(row.order_id, { claimed_until: null });
    if (now && row.state === "gone") {
      throw new Problem(row.error || "Its invoice was changed by hand in Xero.");
    }
    return { state: row.state, unchanged: true, already: true,
             number: row.invoice_number ?? "", emailed_to: row.emailed_to ?? "" };
  }
  const unpriced = inv.unpriced.length;
  if (now && unpriced) {
    throw new Problem(`${unpriced} line${unpriced === 1 ? " has" : "s have"} no ` +
      "price. Put the price on the work order, then send it again.");
  }
  if (now) {
    // Invoiced from its button: the job is done today.
    row = await put(row.order_id, { complete_wanted: true,
                                    completed_on: row.completed_on ?? today() });
  }
  if (row.invoice_id && row.lines_hash === hash) {
    row = await put(row.order_id, { source_md5: md5 });
    if (row.complete_wanted && row.state === "draft" && !row.unpriced) {
      return await approveOne(row);
    }
    await put(row.order_id, { claimed_until: null });
    return { state: row.state, unchanged: true, number: row.invoice_number };
  }

  // The contact the customer is linked to wins; then the one this order's
  // invoice already has; then a search by name.
  let contact = inv.contact_id ? await getContact(inv.contact_id) : null;
  if (!contact && row.contact_id) contact = await getContact(row.contact_id);
  if (!contact) contact = await findContact(inv.contact_names);
  if (!contact) {
    const name = inv.contact_names.find((n: string) => n.trim()) ?? "this customer";
    throw new Problem(`Xero has no contact called "${name}". Add them in Xero, with ` +
      "the email address their invoices go to (or give them the same name in " +
      "both) - it goes through on its own after that.");
  }
  const items = await lineItems(inv);
  const due = await dueFor(inv.date, contact, inv.terms);
  const fields = { Contact: { ContactID: contact.ContactID }, Date: inv.date,
                   DueDate: due, Reference: inv.reference,
                   LineAmountTypes: "Exclusive", LineItems: items };
  let made: Row | undefined;
  if (row.invoice_id) {
    const cur = await getInvoice(row.invoice_id);
    if (!cur || !["DRAFT", "SUBMITTED"].includes(cur.Status)) return await handOver(row, cur);
    const out = await xero("POST", `/api.xro/2.0/Invoices/${row.invoice_id}`,
                           { Invoices: [{ InvoiceID: row.invoice_id, ...fields }] });
    made = out?.Invoices?.[0];
  } else {
    const base = { Type: "ACCREC", Status: "DRAFT", ...fields };
    const key = `taf-${row.order_id}-${hash}`.slice(0, 120);
    try {
      const out = await xero("POST", "/api.xro/2.0/Invoices",
        { Invoices: [{ ...base, InvoiceNumber: inv.number || undefined }] },
        { "Idempotency-Key": key });
      made = out?.Invoices?.[0];
    } catch (e) {
      // Our order number is already an invoice number in Xero (another
      // customer's purchase order, say): let Xero number it, and keep ours
      // in the reference.
      if (!inv.number || !/unique/i.test(String((e as Error).message))) throw e;
      const out = await xero("POST", "/api.xro/2.0/Invoices",
        { Invoices: [{ ...base,
          Reference: [inv.number, inv.reference].filter(Boolean).join(" - ").slice(0, 255) }] },
        { "Idempotency-Key": `${key}-n` });
      made = out?.Invoices?.[0];
    }
  }
  if (!made?.InvoiceID) throw new Problem("Xero did not say which invoice it made.");

  row = await put(row.order_id, {
    state: "draft", invoice_id: made.InvoiceID,
    invoice_number: made.InvoiceNumber ?? "", contact_id: contact.ContactID,
    contact_name: contact.Name ?? "", lines_hash: hash, source_md5: md5,
    unpriced, total: Number(made.Total ?? 0), invoice_date: inv.date,
    terms: inv.terms || null, next_try_at: null,
    error: unpriced
      ? `${unpriced} line${unpriced === 1 ? " has" : "s have"} no price - on the ` +
        "draft at $0, marked NO PRICE. It is not approved or emailed until the " +
        "price is on the order (or finish it in Xero by hand)."
      : null,
  });
  if (row.complete_wanted && !unpriced) return await approveOne(row);
  await put(row.order_id, { claimed_until: null });
  return { state: "draft", number: row.invoice_number, unpriced };
}

/** The job is finished: date the invoice that day, approve it, email it. */
async function approveOne(row: Row) {
  const cur = await getInvoice(row.invoice_id);
  if (!cur) return await handOver(row, null);
  let inv = cur;
  let contact: Row | null = null;
  if (["DRAFT", "SUBMITTED"].includes(cur.Status)) {
    const date = row.completed_on ?? today();
    contact = await getContact(cur.Contact?.ContactID);
    const due = await dueFor(date, contact, row.terms);
    const out = await xero("POST", `/api.xro/2.0/Invoices/${row.invoice_id}`, {
      Invoices: [{ InvoiceID: row.invoice_id, Status: "AUTHORISED",
                   Date: date, DueDate: due }],
    });
    inv = out?.Invoices?.[0] ?? cur;
    row = await put(row.order_id, {
      state: "approved", approved_at: nowIso(), invoice_date: date,
      invoice_number: inv.InvoiceNumber ?? row.invoice_number,
      total: Number(inv.Total ?? row.total ?? 0), error: null,
    });
  } else if (cur.Status === "AUTHORISED") {
    row = await put(row.order_id, { state: "approved",
                                    approved_at: row.approved_at ?? nowIso() });
  } else {
    return await handOver(row, cur);
  }
  return await emailOne(row, inv, contact);
}

async function emailOne(row: Row, inv: Row | null, contact: Row | null = null) {
  if (inv?.SentToContact) {
    await put(row.order_id, { state: "sent", emailed_at: nowIso(),
                              emailed_to: "sent from Xero", error: null,
                              claimed_until: null });
    return { state: "sent", number: row.invoice_number };
  }
  // Xero's email sending fails now and then on its side ("An error occurred
  // in Xero", a 5xx) straight after approving; another go a moment later
  // usually sends it. A refusal about the invoice or contact (4xx) is said
  // as Xero says it.
  let failure: Problem | null = null;
  for (const wait of [0, 2000, 5000]) {
    if (wait) await sleep(wait);
    try {
      await xero("POST", `/api.xro/2.0/Invoices/${row.invoice_id}/Email`, {});
      failure = null;
      break;
    } catch (e) {
      failure = e as Problem;
      if (failure.status && failure.status < 500 && failure.status !== 429) break;
    }
  }
  if (failure) {
    const theirs = !failure.status || failure.status >= 500 || failure.status === 429;
    const error = theirs
      ? "Approved in Xero, but Xero could not send the email just now (a " +
        "problem on Xero's side, not the invoice). Press Retry on the Xero " +
        "screen in a few minutes, or send it from Xero."
      : `Approved in Xero, but Xero would not email it: ${failure.message}. ` +
        "Check the contact's email address in Xero and press Retry, or send it " +
        "from Xero.";
    await put(row.order_id, { error, claimed_until: null });
    return { state: "approved", error };
  }
  contact = contact ?? await getContact(inv?.Contact?.ContactID).catch(() => null);
  await put(row.order_id, { state: "sent", emailed_at: nowIso(),
                            emailed_to: contact?.EmailAddress ?? "", error: null,
                            claimed_until: null });
  return { state: "sent", number: row.invoice_number,
           emailed_to: contact?.EmailAddress ?? "" };
}

/** The order was deleted: take its draft back out of Xero. */
async function deleteOne(row: Row) {
  if (!row.invoice_id) {
    await put(row.order_id, { state: "deleted", error: null, claimed_until: null });
    return { state: "deleted" };
  }
  const cur = await getInvoice(row.invoice_id);
  if (cur && ["DRAFT", "SUBMITTED"].includes(cur.Status)) {
    await xero("POST", `/api.xro/2.0/Invoices/${row.invoice_id}`,
               { Invoices: [{ InvoiceID: row.invoice_id, Status: "DELETED" }] });
  } else if (cur && !["DELETED", "VOIDED"].includes(cur.Status)) {
    const error = "The order was deleted, but its invoice had already been " +
      "approved in Xero. Void it there if it should not stand.";
    await put(row.order_id, { state: "gone", error, claimed_until: null });
    return { state: "gone", error };
  }
  await put(row.order_id, { state: "deleted", error: null, claimed_until: null });
  return { state: "deleted" };
}

/** Something stopped it: say why on the row, and wait before trying again
 *  (Xero allows 60 calls a minute; an order that cannot go should not use
 *  them all up every few minutes). */
async function failed(row: Row, err: unknown, md5?: string | null) {
  const e = err as Problem;
  const wait = e?.status === 429 ? 2 * MINUTE : 30 * MINUTE;
  const patch: Row = { error: String(e?.message ?? err).slice(0, 1000),
                       next_try_at: later(wait), claimed_until: null };
  if (md5 !== undefined) patch.source_md5 = md5;
  await put(row.order_id, patch).catch(() => {});
  return { state: row.state, error: patch.error };
}

async function sweep() {
  const c = await conn();
  if (!c.refresh_token) return { done: 0, problems: [], connected: false };
  const work = await rpc<Row[]>("xero_due_work", { p_limit: 8 });
  const problems: string[] = [];
  let done = 0;
  for (const w of work ?? []) {
    const row = await claim(w.order_id);
    if (!row) continue;
    try {
      const out: Row = row.delete_wanted ? await deleteOne(row) : await approveOne(row);
      if (out.error) problems.push(out.error);
      else done++;
    } catch (e) {
      const out = await failed(row, e);
      problems.push(out.error);
      if ((e as Problem).status === 429) break;
    }
  }
  return { done, problems, connected: true };
}


// ── Requests ────────────────────────────────────────────────────────────────

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  const url = new URL(req.url);
  // Xero sends the manager back with ?code=...&state=... (or ?error=... if
  // they cancelled), so the redirect URI can be the function's plain address.
  const back = url.searchParams.has("state") &&
    (url.searchParams.has("code") || url.searchParams.has("error"));
  const action = url.searchParams.get("do") ?? (back ? "finish" : "status");

  if (!env("XERO_CLIENT_ID") || !env("XERO_CLIENT_SECRET") || !env("XERO_REDIRECT_URI")) {
    return json({ error: "This Supabase project has no Xero app set up. Set " +
      "XERO_CLIENT_ID, XERO_CLIENT_SECRET and XERO_REDIRECT_URI as function " +
      "secrets." }, 503);
  }

  try {
    // Xero itself sends the person here, in a browser, with a code.
    if (action === "finish") {
      if (url.searchParams.has("error")) {
        return text("Xero was not connected (" + (url.searchParams.get("error") ?? "") +
                    "). Press Connect in the app to try again.", 400);
      }
      const code = url.searchParams.get("code") ?? "";
      const state = url.searchParams.get("state") ?? "";
      const c = await conn();
      const fresh = c.state_at && Date.now() - Date.parse(c.state_at) < 30 * MINUTE;
      if (!code || !state || state !== c.state || !fresh) {
        return text("That link is not one the app started, or it is too old. " +
                    "Press Connect in the app again.", 400);
      }
      const res = await fetch(`${IDENTITY()}/connect/token`, {
        method: "POST",
        headers: { Authorization: `Basic ${basic()}`,
                   "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ grant_type: "authorization_code", code,
                                    redirect_uri: env("XERO_REDIRECT_URI") }),
      });
      const got = await res.json().catch(() => ({}));
      if (!res.ok || !got.refresh_token) {
        return text("Xero refused that. Press Connect in the app again.", 400);
      }
      const orgs = await fetch(`${API()}/connections`, {
        headers: { Authorization: `Bearer ${got.access_token}`, Accept: "application/json" },
      }).then((r) => r.json()).catch(() => []);
      const org = Array.isArray(orgs) ? orgs[0] : null;
      await connPut({
        access_token: got.access_token, refresh_token: got.refresh_token,
        expires_at: later(Number(got.expires_in ?? 1800) * 1000),
        refreshed_at: nowIso(), refreshing_until: null,
        tenant_id: org?.tenantId ?? null, tenant_name: org?.tenantName ?? "",
        state: null, state_by: null, state_at: null,
        connected_by: c.state_by ?? null, connected_at: nowIso(),
        problem: null,
      });
      return text(`Xero is connected${org?.tenantName ? ` to ${org.tenantName}` : ""}. ` +
                  "You can close this window and go back to the app.");
    }

    const who = await caller(req);
    if (!who) return json({ error: "Not signed in." }, 401);
    if (!who.staff && !(who.system && ["sweep", "status"].includes(action))) {
      return json({ error: "Only staff can use Xero from the app." }, 403);
    }
    const body: Row = req.method === "POST"
      ? await req.json().catch(() => ({})) : {};

    if (action === "status") {
      let c = await conn();
      // Keep the link alive: Xero ends a sign-in not renewed for 60 days.
      const renewed = c.refreshed_at ? Date.parse(c.refreshed_at) : 0;
      if (c.refresh_token && Date.now() - renewed > 7 * 24 * 60 * MINUTE) {
        await token(c.access_token ?? "").catch(() => {});
        c = await conn();
      }
      return json({ connected: !!c.refresh_token, organisation: c.tenant_name ?? "",
                    connected_at: c.connected_at ?? null,
                    mode: c.mode ?? "manual",
                    drafts_from: c.drafts_from ?? null, problem: c.problem ?? "" });
    }

    if (action === "mode") {
      if (!who.manager) return json({ error: "Only a manager can change how Xero is used." }, 403);
      const mode = String(body.mode ?? "");
      if (mode !== "manual" && mode !== "automatic") {
        return json({ error: "The mode is 'manual' (trial) or 'automatic'." }, 400);
      }
      const c = await conn();
      // Going automatic: orders from now on go by themselves. Not the orders
      // of the trial, which were sent by hand or not at all.
      const patch: Row = { mode };
      if (mode === "automatic" && c.mode !== "automatic") patch.drafts_from = nowIso();
      const after = await connPut(patch);
      return json({ mode: after?.mode ?? mode, drafts_from: after?.drafts_from ?? null });
    }

    if (action === "start" || action === "disconnect") {
      if (!who.manager) return json({ error: "Only a manager can connect or disconnect Xero." }, 403);
    }

    if (action === "start") {
      // Checked when Xero sends the person back, so a link somebody was sent
      // cannot connect a different Xero to the app.
      const state = crypto.randomUUID();
      await connPut({ state, state_by: who.id, state_at: nowIso() });
      const go = new URL(LOGIN());
      go.searchParams.set("response_type", "code");
      go.searchParams.set("client_id", env("XERO_CLIENT_ID"));
      go.searchParams.set("redirect_uri", env("XERO_REDIRECT_URI"));
      go.searchParams.set("scope", SCOPES());
      go.searchParams.set("state", state);
      return json({ url: go.toString() });
    }

    if (action === "disconnect") {
      const c = await conn();
      if (c.refresh_token) {
        await fetch(`${IDENTITY()}/connect/revocation`, {
          method: "POST",
          headers: { Authorization: `Basic ${basic()}`,
                     "Content-Type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({ token: c.refresh_token }),
        }).catch(() => {});
      }
      await connPut({ access_token: null, refresh_token: null, expires_at: null,
                      tenant_id: null, tenant_name: null, drafts_from: null,
                      refreshing_until: null, problem: null });
      return json({ connected: false });
    }

    if (action === "draft") {
      const order = String(body.order_id ?? "");
      if (!UUID.test(order)) return json({ error: "Which order?" }, 400);
      const read = readInvoice(body.invoice);
      if (!read.ok) return json({ error: read.error }, 400);
      const hash = String(body.hash ?? "").replace(/[^0-9a-zA-Z]/g, "").slice(0, 64);
      if (!hash) return json({ error: "No hash was given." }, 400);
      const md5 = body.source_md5 ? String(body.source_md5).slice(0, 64) : null;
      const now = body.invoice_now === true;
      const row = await claim(order);
      if (!row) return json({ busy: true });
      try {
        return json(await draftOne(row, read.inv, hash, md5, now));
      } catch (e) {
        return json(await failed(row, e, md5), 422);
      }
    }

    if (action === "sweep") return json(await sweep());

    if (action === "retry") {
      const order = String(body.order_id ?? "");
      if (!UUID.test(order)) return json({ error: "Which order?" }, 400);
      const row = await claim(order);
      if (!row) return json({ busy: true });
      try {
        if (row.state === "approved") {
          return json(await emailOne(row, await getInvoice(row.invoice_id)));
        }
        if (row.delete_wanted && ["waiting", "draft"].includes(row.state)) {
          return json(await deleteOne(row));
        }
        if (row.state === "draft" && row.complete_wanted && !row.unpriced) {
          return json(await approveOne(row));
        }
        // Anything else is made by a PC from the order: let the next one at it.
        await put(order, { next_try_at: null, source_md5: null, claimed_until: null });
        return json({ state: row.state, queued: true });
      } catch (e) {
        return json(await failed(row, e), 422);
      }
    }

    if (action === "pdf") {
      // An order's invoice as a PDF, to print or keep. Only invoices this
      // app made, found through the order they belong to.
      const order = String(body.order_id ?? "");
      if (!UUID.test(order)) return json({ error: "Which order?" }, 400);
      const res = await fetch(`${SB()}/rest/v1/xero_invoices?order_id=eq.${order}` +
                              "&select=invoice_id,invoice_number,state", {
        headers: { apikey: SERVICE(), Authorization: `Bearer ${SERVICE()}`,
                   Accept: "application/json" },
      });
      const rows = res.ok ? await res.json().catch(() => []) : [];
      const row = Array.isArray(rows) ? rows[0] : null;
      if (!row?.invoice_id) return json({ error: "This order has no invoice in Xero." }, 404);
      const pdf = await invoicePdf(String(row.invoice_id));
      return new Response(pdf, { status: 200, headers: {
        ...CORS, "Content-Type": "application/pdf",
        "X-Invoice-Number": String(row.invoice_number ?? ""),
      } });
    }

    if (action === "contacts") {
      // Finding a customer's contact in Xero, to link them.
      const term = String(body.term ?? "").trim().slice(0, 100);
      if (!term) return json({ contacts: [] });
      const out = await xero("GET", "/api.xro/2.0/Contacts?searchTerm=" +
        encodeURIComponent(term));
      const contacts = (out?.Contacts ?? [])
        .filter((c: Row) => c?.ContactStatus !== "ARCHIVED")
        .slice(0, 25)
        .map((c: Row) => ({ id: c.ContactID, name: c.Name ?? "",
                            email: c.EmailAddress ?? "" }));
      return json({ contacts });
    }

    if (action === "list") {
      return json({ rows: await rpc<Row[]>("xero_list", { p_limit: 300 }) });
    }

    if (action === "owing") {
      const rows: Row[] = [];
      const now = Date.now();
      for (let page = 1; page <= 10; page++) {
        const out = await xero("GET", "/api.xro/2.0/Invoices?where=" +
          encodeURIComponent('Type=="ACCREC" AND Status=="AUTHORISED"') +
          `&order=DueDate&page=${page}`);
        const list = out?.Invoices ?? [];
        for (const inv of list) {
          const due = String(inv.DueDateString ?? "").slice(0, 10);
          const days = due ? Math.floor((now - Date.parse(due)) / 86400000) : 0;
          const owing = Number(inv.AmountDue ?? 0);
          if (owing > 0) {
            rows.push({ number: inv.InvoiceNumber ?? "", customer: inv.Contact?.Name ?? "",
                        due, total: Number(inv.Total ?? 0), owing,
                        days_late: days > 0 ? days : 0 });
          }
        }
        if (list.length < 100) break;
      }
      return json({ rows, owed: rows.reduce((n, r) => n + r.owing, 0) });
    }

    return json({ error: `There is nothing called ${action}.` }, 400);
  } catch (err) {
    const e = err as Problem;
    return json({ error: String(e?.message ?? err) }, e instanceof Problem ? 409 : 500);
  }
});
