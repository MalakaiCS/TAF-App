// Supabase Edge Function: extract-orders
//
// Reads purchase orders out of uploaded documents (PDFs, photos, scans,
// pasted email text) and returns them as structured order data the desktop
// app can turn into worksheets.
//
// The Anthropic API key lives here as a function secret — it is never shipped
// inside the Windows installer, where anyone could pull it back out.
//
// Deploy:
//   supabase secrets set ANTHROPIC_API_KEY=sk-ant-...
//   supabase functions deploy extract-orders
// (or paste this file into Supabase → Edge Functions → Deploy a new function)

import Anthropic from "npm:@anthropic-ai/sdk@0.71.0";

const MODEL = Deno.env.get("EXTRACT_MODEL") ?? "claude-opus-5";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

// What the app's order model actually looks like. The schema is enforced by
// the API, so the app never has to defend against a malformed shape.
const ORDER_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["orders"],
  properties: {
    orders: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: [
          "customer_name", "order_number", "date_ordered", "date_due",
          "attention", "job", "location", "notes", "confidence",
          "warnings", "items",
        ],
        properties: {
          customer_name: { type: "string" },
          order_number: { type: "string" },
          // Dates as dd/mm/yyyy — the app parses day-first.
          date_ordered: { type: "string" },
          date_due: { type: "string" },
          attention: { type: "string" },
          job: { type: "string" },
          location: { type: "string" },
          notes: { type: "string" },
          confidence: { type: "string", enum: ["high", "medium", "low"] },
          warnings: {
            type: "array",
            items: { type: "string" },
            description: "Anything a human should check before manufacturing.",
          },
          items: {
            type: "array",
            items: {
              type: "object",
              additionalProperties: false,
              required: [
                "item_kind", "quantity", "short", "long", "channel",
                "filter_type", "media_type", "notes", "confidence",
                "source_text",
              ],
              properties: {
                item_kind: { type: "string", enum: ["filter", "bag"] },
                quantity: { type: "integer" },
                short: { type: "integer", description: "Smaller face dimension in mm; 0 if unknown." },
                long: { type: "integer", description: "Larger face dimension in mm; 0 if unknown." },
                channel: { type: "integer", description: "Depth / thickness in mm; 0 if unknown." },
                filter_type: { type: "string" },
                media_type: { type: "string" },
                notes: { type: "string" },
                confidence: { type: "string", enum: ["high", "medium", "low"] },
                source_text: {
                  type: "string",
                  description: "The line as it appears in the document, verbatim.",
                },
              },
            },
          },
        },
      },
    },
  },
} as const;

const SYSTEM = `You read purchase orders for Total Air Filtration, an air-filter manufacturer, and turn them into structured order data for their production system.

The documents are customer purchase orders. They arrive as typed PDFs, phone photos of paper forms (often angled, shadowed or handwritten), flatbed scans, and pasted email text. Read whatever is there.

ONE DOCUMENT MAY CONTAIN SEVERAL SEPARATE PURCHASE ORDERS. Return one entry in "orders" per distinct purchase order — a new order number, a new customer, or a clear page/section break usually marks a new one. Do not merge two orders, and do not split one order across entries.

FIELDS
- customer_name: the company ordering the filters (not Total Air Filtration itself — TAF is the supplier).
- order_number: their purchase order / PO / order number.
- date_ordered, date_due: dd/mm/yyyy. These documents are Australian: 03/04/2026 is 3 April. If a due date is written as "ASAP" or similar, put exactly "ASAP". Leave "" when absent — never invent one.
- attention: the contact person named on the order.
- job / location: job name or site/delivery location if stated.
- notes: order-level instructions (delivery, packing, urgency). Not line-item detail.

LINE ITEMS
- One entry per distinct filter line. If a line says "4 off" or "qty 4", quantity is 4 — do not expand it into four entries.
- Dimensions are millimetres. Filters are described as face size then depth, e.g. "595 x 595 x 48". Put the SMALLER face dimension in "short", the LARGER in "long", and the depth/thickness in "channel". A dimension given in inches or metres must be converted to mm, and you must say so in that item's notes.
- filter_type: what kind of filter — e.g. V-form, Flat Panel, Stepped Filter, Flyscreen, Header, Pleated Panel, Bag Filter. Use the customer's wording when it is clear; leave "" if you genuinely cannot tell.
- media_type: the filter media or grade — e.g. G4, F5, F7, 180, WASH, GREY, E-MESH. Leave "" if not stated.
- item_kind: "bag" for bag/pocket filters and media rolls, otherwise "filter".
- notes: anything specific to that line (on wire, gelled, special size, insert).
- source_text: copy the line verbatim from the document. This is what the operator checks your reading against, so it must be what is actually written, not a tidied version.

CONFIDENCE AND WARNINGS — this matters more than completeness
A wrong dimension means a filter is manufactured wrong and the material is scrapped, so flag rather than guess.
- Set an item's confidence to "low" whenever a digit is blurred, ambiguous, handwritten unclearly, or you inferred it from context rather than read it.
- Set it to "medium" when you read it but the layout made the mapping uncertain (e.g. which number is depth).
- Use "high" only for values you can read plainly.
- The order's confidence is the lowest of its items, or lower still if the header is unclear.
- Put anything a human must check into "warnings": unreadable fields, a missing order number, ambiguous units, quantities that look implausible, two orders that might actually be one.
- If a field is genuinely absent, return "" (or 0 for a number). Never fill a gap with a plausible-looking value.

If the document contains no purchase order at all, return an empty "orders" array.`;

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: CORS });
  }
  if (req.method !== "POST") {
    return json({ error: "POST only" }, 405);
  }

  // Supabase verifies the caller's JWT before this runs (verify_jwt is on by
  // default), so reaching this point means a signed-in staff member.
  const apiKey = Deno.env.get("ANTHROPIC_API_KEY");
  if (!apiKey) {
    return json({
      error:
        "ANTHROPIC_API_KEY is not set on this function. Run: " +
        "supabase secrets set ANTHROPIC_API_KEY=sk-ant-...",
    }, 500);
  }

  let body: { files?: Array<{ media_type?: string; data?: string; text?: string; name?: string }> };
  try {
    body = await req.json();
  } catch {
    return json({ error: "Body must be JSON." }, 400);
  }

  const files = body.files ?? [];
  if (!files.length) {
    return json({ error: "No files supplied." }, 400);
  }

  // Build one user turn holding every uploaded document.
  const content: unknown[] = [];
  for (const f of files) {
    const label = f.name ? `Document: ${f.name}` : "Document";
    if (f.text) {
      content.push({ type: "text", text: `${label} (pasted text):\n\n${f.text}` });
      continue;
    }
    if (!f.data || !f.media_type) continue;
    content.push({ type: "text", text: label });
    if (f.media_type === "application/pdf") {
      content.push({
        type: "document",
        source: { type: "base64", media_type: "application/pdf", data: f.data },
      });
    } else {
      content.push({
        type: "image",
        source: { type: "base64", media_type: f.media_type, data: f.data },
      });
    }
  }
  if (!content.length) {
    return json({ error: "Nothing readable in the supplied files." }, 400);
  }
  content.push({
    type: "text",
    text: "Extract every purchase order in the documents above.",
  });

  const client = new Anthropic({ apiKey });

  try {
    // Streamed: a multi-page scan at high effort can run past the plain
    // request timeout, and we want the whole response either way.
    const stream = client.messages.stream({
      model: MODEL,
      max_tokens: 32000,
      system: SYSTEM,
      thinking: { type: "adaptive" },
      output_config: {
        effort: "high",
        format: { type: "json_schema", schema: ORDER_SCHEMA },
      },
      messages: [{ role: "user", content: content as never }],
    });
    const response = await stream.finalMessage();

    if (response.stop_reason === "refusal") {
      return json({
        error: "The document could not be processed (content declined).",
      }, 422);
    }

    const text = response.content
      .filter((b) => b.type === "text")
      .map((b) => (b as { text: string }).text)
      .join("");

    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      return json({ error: "Model returned unparseable output." }, 502);
    }

    return json({
      ...(parsed as Record<string, unknown>),
      usage: {
        input_tokens: response.usage.input_tokens,
        output_tokens: response.usage.output_tokens,
      },
    }, 200);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    const status = (err as { status?: number })?.status ?? 500;
    return json({ error: `Extraction failed: ${msg}` }, status >= 400 && status < 600 ? status : 500);
  }
});

function json(payload: unknown, status: number): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { ...CORS, "Content-Type": "application/json" },
  });
}
