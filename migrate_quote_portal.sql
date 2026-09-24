-- ============================================================
-- TAF Order App - Quote portal (customer accept / decline)
-- Run this AFTER migrate_quotes.sql, in Supabase Dashboard -> SQL Editor.
--
-- SECURITY, because this is the one part of the system a stranger can reach.
--
-- The customer is not signed in. They follow a link containing a random
-- 64-character token. That link must let them see THEIR quote and respond to
-- it, and nothing else - not other quotes, not customers, not orders, not
-- prices in general.
--
-- So the anon role is given NO access to the quotes table at all. It can only
-- call two functions, each of which takes the token and hands back exactly
-- what a customer is allowed to see. There is no query a caller can shape
-- themselves, and no way to enumerate: without a token you get nothing, and
-- the token is 256 bits of randomness.
--
-- Both functions are SECURITY DEFINER with a pinned search_path, so they run
-- with the rights needed to read the row while being unable to be tricked
-- into resolving a name to something the caller planted.
-- ============================================================

-- ── Columns the portal needs ────────────────────────────────────────────────

ALTER TABLE quotes ADD COLUMN IF NOT EXISTS public_token       text;
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS sent_at            timestamptz;
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS viewed_at          timestamptz;
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS responded_at       timestamptz;
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS response_name      text DEFAULT '';
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS response_reference text DEFAULT '';
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS response_note      text DEFAULT '';

-- The priced lines exactly as quoted. Kept separately from `items` (which is
-- what an accepted quote is built into an order from) so that what the
-- customer was shown can never be re-rendered at today's prices.
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS lines jsonb DEFAULT '[]'::jsonb;

CREATE UNIQUE INDEX IF NOT EXISTS quotes_public_token_idx
    ON quotes (public_token) WHERE public_token IS NOT NULL;

-- ── What a customer may see ─────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.quote_public_view(p_token text)
RETURNS json
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  q public.quotes%ROWTYPE;
BEGIN
  -- A short token is not a real one; refuse before touching the table.
  IF p_token IS NULL OR length(p_token) < 32 THEN
    RETURN NULL;
  END IF;

  SELECT * INTO q FROM public.quotes WHERE public_token = p_token;
  IF NOT FOUND THEN
    RETURN NULL;                      -- says nothing about what does exist
  END IF;

  -- Opening the link is worth knowing: it is the difference between "they
  -- haven't looked" and "they looked and haven't answered".
  IF q.viewed_at IS NULL THEN
    UPDATE public.quotes
       SET viewed_at = now(),
           status = CASE WHEN status IN ('draft', 'sent') THEN 'viewed'
                         ELSE status END
     WHERE id = q.id;
    q.viewed_at := now();
  END IF;

  RETURN json_build_object(
    'quote_number',  q.quote_number,
    'customer_name', q.customer_name,
    'reference',     q.reference,
    'lines',         COALESCE(q.lines, '[]'::jsonb),
    'subtotal',      q.subtotal,
    'gst',           q.gst,
    'total',         q.total,
    'valid_until',   q.valid_until,
    'created_at',    q.created_at,
    'status',        q.status,
    'responded_at',  q.responded_at,
    'response_name', q.response_name,
    'expired',       (q.valid_until IS NOT NULL AND q.valid_until < current_date)
  );
  -- Deliberately absent: internal notes, the order lines, who wrote it,
  -- customer_id, and every other quote in the table.
END;
$$;

-- ── Accepting or declining ──────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.quote_public_respond(
    p_token     text,
    p_decision  text,
    p_name      text DEFAULT '',
    p_reference text DEFAULT '',
    p_note      text DEFAULT '')
RETURNS json
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  q public.quotes%ROWTYPE;
BEGIN
  IF p_decision NOT IN ('accepted', 'declined') THEN
    RETURN json_build_object('ok', false, 'error', 'bad_decision');
  END IF;
  IF p_token IS NULL OR length(p_token) < 32 THEN
    RETURN json_build_object('ok', false, 'error', 'not_found');
  END IF;

  SELECT * INTO q FROM public.quotes WHERE public_token = p_token;
  IF NOT FOUND THEN
    RETURN json_build_object('ok', false, 'error', 'not_found');
  END IF;

  -- An answer already given is not overwritten from a public page. Changing
  -- one is a conversation, not a click.
  IF q.status IN ('accepted', 'declined') THEN
    RETURN json_build_object('ok', false, 'error', 'already',
                             'status', q.status,
                             'responded_at', q.responded_at);
  END IF;

  IF q.valid_until IS NOT NULL AND q.valid_until < current_date THEN
    RETURN json_build_object('ok', false, 'error', 'expired',
                             'valid_until', q.valid_until);
  END IF;

  UPDATE public.quotes
     SET status             = p_decision,
         responded_at       = now(),
         response_name      = left(COALESCE(p_name, ''), 120),
         response_reference = left(COALESCE(p_reference, ''), 120),
         response_note      = left(COALESCE(p_note, ''), 1000),
         updated_at         = now()
   WHERE id = q.id;

  RETURN json_build_object('ok', true, 'status', p_decision);
END;
$$;

-- ── Who may call them ───────────────────────────────────────────────────────
-- EXECUTE is granted to everyone by default, so it is taken away first and
-- then given back deliberately.

REVOKE ALL ON FUNCTION public.quote_public_view(text) FROM public;
REVOKE ALL ON FUNCTION public.quote_public_respond(text, text, text, text, text)
    FROM public;

GRANT EXECUTE ON FUNCTION public.quote_public_view(text)
    TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.quote_public_respond(text, text, text, text, text)
    TO anon, authenticated;

-- The quotes table itself stays closed to anon: no policy grants it anything,
-- and RLS is already enabled by migrate_quotes.sql. The functions above are
-- the only way in.
