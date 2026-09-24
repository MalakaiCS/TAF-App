// Supabase Edge Function: inbound-order
//
// An address purchase orders can be emailed to, so nobody has to photograph
// a PDF that arrived as a PDF.
//
// It does not read the order. Everything for that already exists: the
// attachments go into the same po-inbox bucket the phone uploads to, and the
// office app's existing sweep picks them up, reads them and puts them in the
// review screen exactly as it does a photo. One reader, one review screen,
// one set of corrections it learns from.
//
// Provider-agnostic on purpose. Inbound email is the one thing every
// provider shapes differently, and hard-coding one of them is a rewrite the
// day that contract ends. It accepts the two shapes they all reduce to:
//
//   { "from": "...", "subject": "...", "attachments":
//       [{ "filename": "po.pdf", "content": "<base64>", "type": "..." }] }
//
//   multipart/form-data with file parts, which is what a "post the raw
//   message to this URL" setting sends.
//
// Authentication is a shared secret in the URL, not a signed-in account:
// there is no person at the other end of an email. Set INBOUND_TOKEN and
// give the provider .../inbound-order?token=...
//
// Deploy:
//   supabase secrets set INBOUND_TOKEN=<a long random string>
//   supabase functions deploy inbound-order --no-verify-jwt

import { createClient } from "npm:@supabase/supabase-js@2";

const BUCKET = "po-inbox";

// Anything else is not a purchase order, and a function that will write any
// file anyone emails it into storage is a place to host anything.
const ALLOWED = ["application/pdf", "image/jpeg", "image/png", "image/heic",
                 "image/webp", "image/tiff"];
const MAX_BYTES = 25 * 1024 * 1024;

function json(payload: unknown, status: number): Response {
  return new Response(JSON.stringify(payload), {
    status, headers: { "Content-Type": "application/json" },
  });
}

function safeName(raw: string): string {
  // The filename comes from whoever sent the email. Anything but the last
  // component of a plain name is thrown away: a name with a slash in it
  // writes outside the folder it was meant for.
  const base = String(raw || "order").split(/[\\/]/).pop() || "order";
  return base.replace(/[^A-Za-z0-9._-]/g, "_").slice(-80) || "order";
}

function decode(b64: string): Uint8Array {
  const clean = String(b64 || "").replace(/\s+/g, "");
  const bin = atob(clean);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") return json({ error: "POST only" }, 405);

  const want = Deno.env.get("INBOUND_TOKEN") ?? "";
  if (!want) {
    return json({ error: "This project has no INBOUND_TOKEN set, so the " +
                         "address is not switched on." }, 503);
  }
  const url = new URL(req.url);
  const given = url.searchParams.get("token")
    ?? (req.headers.get("Authorization") ?? "").replace(/^Bearer /, "");
  // Compared character by character over the whole secret rather than with a
  // plain !==, which stops as soon as two characters differ.
  if (given.length !== want.length ||
      !given.split("").every((c, i) => c === want[i])) {
    return json({ error: "Not for you." }, 401);
  }

  const admin = createClient(Deno.env.get("SUPABASE_URL")!,
                             Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);

  type Incoming = { name: string; type: string; body: Uint8Array };
  const files: Incoming[] = [];
  let from = "", subject = "";

  const kind = (req.headers.get("Content-Type") ?? "").toLowerCase();
  try {
    if (kind.includes("multipart/form-data")) {
      const form = await req.formData();
      from = String(form.get("from") ?? "");
      subject = String(form.get("subject") ?? "");
      for (const [, value] of form.entries()) {
        if (value instanceof File) {
          files.push({
            name: value.name, type: value.type,
            body: new Uint8Array(await value.arrayBuffer()),
          });
        }
      }
    } else {
      const body = await req.json();
      from = String(body.from ?? body.sender ?? "");
      subject = String(body.subject ?? "");
      for (const att of (body.attachments ?? [])) {
        if (!att?.content) continue;
        files.push({
          name: String(att.filename ?? att.name ?? "order"),
          type: String(att.type ?? att.content_type ?? ""),
          body: decode(String(att.content)),
        });
      }
    }
  } catch (err) {
    return json({ error: `Could not read that message: ${err}` }, 400);
  }

  if (!files.length) {
    // Not an error. Plenty of email has nothing attached, and answering 400
    // to those makes a provider start retrying them forever.
    return json({ taken: 0, reason: "Nothing attached." }, 200);
  }

  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const taken: string[] = [];
  const refused: string[] = [];

  for (const file of files) {
    const type = (file.type || "").toLowerCase().split(";")[0];
    if (!ALLOWED.includes(type)) {
      refused.push(`${file.name}: ${type || "no type"}`);
      continue;
    }
    if (file.body.byteLength > MAX_BYTES) {
      refused.push(`${file.name}: too big`);
      continue;
    }
    const path = `email/${stamp}-${safeName(file.name)}`;
    const { error } = await admin.storage.from(BUCKET)
      .upload(path, file.body, { contentType: type, upsert: false });
    if (error) {
      refused.push(`${file.name}: ${error.message}`);
      continue;
    }
    taken.push(path);
  }

  // Always 200 once the token checked out. A provider that gets a 500
  // retries, and a retry means the same purchase order arrives in the review
  // screen twice.
  return json({ taken: taken.length, paths: taken, refused, from, subject },
              200);
});
