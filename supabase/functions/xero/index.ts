// Supabase Edge Function: xero
//
// Xero, connected properly - push the invoice and get back whether it has
// been paid, instead of exporting a CSV and importing it by hand.
//
// Everything about Xero that is a secret lives here and only here. The
// client secret and the refresh token never go near the Windows installer,
// which anyone can download and unzip, and never near a browser. The app
// asks this function to do things; it does not hold the keys to do them
// itself. That is the same reason the Anthropic key and the mail key are
// function secrets, and it matters more here: these keys move money.
//
// Four things it does.
//
//   start    hand back the URL a person signs in to Xero at
//   finish   swap the code that comes back for tokens, and remember them
//   push     write one order to Xero as a sales invoice
//   owing    what is outstanding, so you know who is behind before you
//            make them more filters
//
// Deploy:
//   supabase secrets set XERO_CLIENT_ID=...
//   supabase secrets set XERO_CLIENT_SECRET=...
//   supabase secrets set XERO_REDIRECT_URI=https://<project>.supabase.co/functions/v1/xero?do=finish
//   supabase functions deploy xero
//
// The tokens are kept in catalog_lists under "xero_tokens", read and written
// with the service role, so no signed-in account can read them out through
// PostgREST even though every account can use this function.

import { createClient } from "npm:@supabase/supabase-js@2";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
};

const TOKEN_KEY = "xero_tokens";
const SCOPES = "offline_access accounting.transactions accounting.contacts";

function json(payload: unknown, status: number): Response {
  return new Response(JSON.stringify(payload), {
    status, headers: { ...CORS, "Content-Type": "application/json" },
  });
}

function admin() {
  return createClient(Deno.env.get("SUPABASE_URL")!,
                      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
}

async function stored(): Promise<Record<string, unknown>> {
  const { data } = await admin().from("catalog_lists")
    .select("value").eq("key", TOKEN_KEY).maybeSingle();
  return (data?.value ?? {}) as Record<string, unknown>;
}

async function remember(value: Record<string, unknown>) {
  await admin().from("catalog_lists").upsert(
    { key: TOKEN_KEY, value, updated_at: new Date().toISOString() },
    { onConflict: "key" });
}

function basic(): string {
  return btoa(`${Deno.env.get("XERO_CLIENT_ID")}:` +
              `${Deno.env.get("XERO_CLIENT_SECRET")}`);
}

/** A live access token, refreshed if the one on file has expired.
 *
 *  Xero's refresh tokens are single use: every refresh hands back a new one
 *  and invalidates the old. Writing the new one down before doing anything
 *  else with it is the difference between a connection that lasts and one
 *  that silently dies the first time two requests overlap. */
async function token(): Promise<string> {
  const have = await stored();
  const expires = Number(have.expires_at ?? 0);
  if (have.access_token && expires > Date.now() + 60_000) {
    return String(have.access_token);
  }
  if (!have.refresh_token) {
    throw new Error("Xero is not connected yet. Connect it under Settings.");
  }
  const res = await fetch("https://identity.xero.com/connect/token", {
    method: "POST",
    headers: { "Authorization": `Basic ${basic()}`,
               "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: String(have.refresh_token),
    }),
  });
  if (!res.ok) {
    await remember({ ...have, refresh_token: null });
    throw new Error("Xero would not renew the connection. Connect it again.");
  }
  const got = await res.json();
  await remember({
    ...have,
    access_token: got.access_token,
    refresh_token: got.refresh_token,
    expires_at: Date.now() + (Number(got.expires_in ?? 1800) * 1000),
  });
  return String(got.access_token);
}

async function tenant(access: string): Promise<string> {
  const have = await stored();
  if (have.tenant_id) return String(have.tenant_id);
  const res = await fetch("https://api.xero.com/connections", {
    headers: { "Authorization": `Bearer ${access}` },
  });
  const rows = await res.json();
  const first = Array.isArray(rows) ? rows[0] : null;
  if (!first?.tenantId) throw new Error("No Xero organisation is connected.");
  await remember({ ...have, tenant_id: first.tenantId,
                   tenant_name: first.tenantName ?? "" });
  return String(first.tenantId);
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });

  const url = new URL(req.url);
  const action = url.searchParams.get("do")
    ?? (req.method === "POST" ? "" : "status");

  // `finish` is the one Xero itself calls, in a browser, carrying a code
  // rather than a signed-in account. Everything else is a person at a PC.
  if (action !== "finish") {
    const auth = req.headers.get("Authorization") ?? "";
    if (!auth.startsWith("Bearer ")) return json({ error: "Not signed in." }, 401);
    const asCaller = createClient(Deno.env.get("SUPABASE_URL")!,
                                  Deno.env.get("SUPABASE_ANON_KEY")!,
                                  { global: { headers: { Authorization: auth } } });
    const { data: who } = await asCaller.auth.getUser();
    if (!who?.user) return json({ error: "Not signed in." }, 401);
  }

  const id = Deno.env.get("XERO_CLIENT_ID");
  const secret = Deno.env.get("XERO_CLIENT_SECRET");
  const redirect = Deno.env.get("XERO_REDIRECT_URI");
  if (!id || !secret || !redirect) {
    return json({ error: "This Supabase project has no Xero app set up. " +
                         "Set XERO_CLIENT_ID, XERO_CLIENT_SECRET and " +
                         "XERO_REDIRECT_URI as function secrets." }, 503);
  }

  try {
    if (action === "status") {
      const have = await stored();
      return json({
        connected: !!have.refresh_token,
        organisation: have.tenant_name ?? "",
      }, 200);
    }

    if (action === "start") {
      // The state is checked when Xero sends the person back, so a link
      // somebody was emailed cannot connect a different Xero to us.
      const state = crypto.randomUUID();
      const have = await stored();
      await remember({ ...have, state });
      const go = new URL("https://login.xero.com/identity/connect/authorize");
      go.searchParams.set("response_type", "code");
      go.searchParams.set("client_id", id);
      go.searchParams.set("redirect_uri", redirect);
      go.searchParams.set("scope", SCOPES);
      go.searchParams.set("state", state);
      return json({ url: go.toString() }, 200);
    }

    if (action === "finish") {
      const code = url.searchParams.get("code") ?? "";
      const state = url.searchParams.get("state") ?? "";
      const have = await stored();
      if (!code || !state || state !== have.state) {
        return new Response("That link is not one we started. Try connecting "
                            + "again from the app.", { status: 400 });
      }
      const res = await fetch("https://identity.xero.com/connect/token", {
        method: "POST",
        headers: { "Authorization": `Basic ${basic()}`,
                   "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          grant_type: "authorization_code", code, redirect_uri: redirect,
        }),
      });
      if (!res.ok) {
        return new Response("Xero refused that. Try connecting again.",
                            { status: 400 });
      }
      const got = await res.json();
      await remember({
        access_token: got.access_token,
        refresh_token: got.refresh_token,
        expires_at: Date.now() + (Number(got.expires_in ?? 1800) * 1000),
        state: null,
      });
      const access = await token();
      await tenant(access);
      return new Response(
        "Xero is connected. You can close this window and go back to the app.",
        { status: 200, headers: { "Content-Type": "text/plain" } });
    }

    const body = req.method === "POST" ? await req.json().catch(() => ({})) : {};

    if (action === "push") {
      const invoice = body.invoice;
      if (!invoice) return json({ error: "No invoice was given." }, 400);
      const access = await token();
      const org = await tenant(access);
      const res = await fetch("https://api.xero.com/api.xro/2.0/Invoices", {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${access}`,
          "Xero-tenant-id": org,
          "Content-Type": "application/json",
          "Accept": "application/json",
        },
        body: JSON.stringify({ Invoices: [invoice] }),
      });
      const out = await res.json().catch(() => ({}));
      if (!res.ok) {
        const why = out?.Elements?.[0]?.ValidationErrors?.[0]?.Message
          ?? out?.Message ?? `Xero said ${res.status}`;
        return json({ error: why }, 400);
      }
      const made = out?.Invoices?.[0] ?? {};
      return json({ sent: true, number: made.InvoiceNumber ?? "",
                    id: made.InvoiceID ?? "" }, 200);
    }

    if (action === "owing") {
      const access = await token();
      const org = await tenant(access);
      const res = await fetch(
        "https://api.xero.com/api.xro/2.0/Invoices"
        + "?where=Type==\"ACCREC\"%20AND%20Status==\"AUTHORISED\""
        + "&order=DueDate", {
          headers: { "Authorization": `Bearer ${access}`,
                     "Xero-tenant-id": org, "Accept": "application/json" },
        });
      const out = await res.json().catch(() => ({}));
      if (!res.ok) return json({ error: `Xero said ${res.status}` }, 400);
      const today = new Date();
      const rows = (out?.Invoices ?? []).map((inv: Record<string, unknown>) => {
        const due = String(inv.DueDateString ?? inv.DueDate ?? "");
        const when = due ? new Date(due) : null;
        const days = when
          ? Math.floor((today.getTime() - when.getTime()) / 86400000) : 0;
        return {
          number: inv.InvoiceNumber ?? "",
          customer: (inv.Contact as Record<string, unknown>)?.Name ?? "",
          due: due.slice(0, 10),
          total: Number(inv.Total ?? 0),
          owing: Number(inv.AmountDue ?? 0),
          days_late: days > 0 ? days : 0,
        };
      }).filter((r: Record<string, number>) => r.owing > 0);
      return json({ rows, owed: rows.reduce(
        (n: number, r: Record<string, number>) => n + r.owing, 0) }, 200);
    }

    return json({ error: `There is nothing called ${action}.` }, 400);
  } catch (err) {
    return json({ error: String((err as Error)?.message ?? err) }, 400);
  }
});
