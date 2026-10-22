-- ============================================================
-- TAF Order App - Portal sign-in, and order detail with tracking
-- Run AFTER migrate_customer_portal.sql. Safe to re-run.
--
-- HOW SOMEONE GETS IN
--
-- Two ways, and neither hands out an account on one guessable fact:
--
--   1. The link we email them, which carries their token.
--   2. Their company email PLUS a purchase order number from their own
--      account.
--
-- The second exists because customers lose links. It deliberately asks for
-- both: an email address on its own is public information - it is on their
-- letterhead - and a purchase order number on its own is a short string that
-- can be counted through. Either alone would hand a stranger somebody's whole
-- order history. Together they are something only a real customer of theirs
-- has.
--
-- Failures are deliberately identical whichever half was wrong, so the form
-- cannot be used to find out which emails or order numbers exist.
-- ============================================================

-- Attempts are recorded so the sign-in form can be slowed down. Guessing a
-- purchase order number should not be something you can do ten thousand times
-- an hour.
CREATE TABLE IF NOT EXISTS portal_signin_attempts (
    id          bigserial PRIMARY KEY,
    email       text NOT NULL DEFAULT '',
    ok          boolean NOT NULL DEFAULT false,
    attempted_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS portal_signin_recent_idx
    ON portal_signin_attempts (email, attempted_at DESC);

ALTER TABLE portal_signin_attempts ENABLE ROW LEVEL SECURITY;
-- No policy at all: only the SECURITY DEFINER function below touches it.

CREATE OR REPLACE FUNCTION public.portal_sign_in(p_email text, p_order_number text)
RETURNS json
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_email  text := lower(trim(COALESCE(p_email, '')));
  v_order  text := lower(trim(COALESCE(p_order_number, '')));
  c        public.customers%ROWTYPE;
  recent   integer;
BEGIN
  IF v_email = '' OR v_order = '' THEN
    RETURN json_build_object('ok', false, 'error', 'incomplete');
  END IF;

  -- Ten tries in fifteen minutes for one email address is plenty for someone
  -- who is typing their own details in, and far too few to search with.
  SELECT count(*) INTO recent
    FROM public.portal_signin_attempts
   WHERE email = v_email
     AND ok = false
     AND attempted_at > now() - interval '15 minutes';
  IF recent >= 10 THEN
    RETURN json_build_object('ok', false, 'error', 'too_many');
  END IF;

  SELECT cu.* INTO c
    FROM public.customers cu
   WHERE cu.portal_enabled = true
     AND cu.portal_token IS NOT NULL
     AND lower(trim(COALESCE(cu.email, ''))) = v_email
     AND EXISTS (
           SELECT 1 FROM public.orders o
            WHERE lower(trim(COALESCE(o.order_number, ''))) = v_order
              AND lower(trim(COALESCE(o.customer_name, ''))) IN (
                    lower(trim(COALESCE(cu.short_name, ''))),
                    lower(trim(COALESCE(cu.name, ''))))
         )
   LIMIT 1;

  INSERT INTO public.portal_signin_attempts (email, ok)
       VALUES (v_email, c.id IS NOT NULL);

  IF c.id IS NULL THEN
    -- The same answer whichever half was wrong, and whether or not the
    -- account exists at all.
    RETURN json_build_object('ok', false, 'error', 'no_match');
  END IF;

  RETURN json_build_object('ok', true, 'token', c.portal_token);
END;
$$;

-- ── One order, in full ──────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.portal_order(p_token text, p_order_number text)
RETURNS json
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  c public.customers%ROWTYPE;
  o public.orders%ROWTYPE;
BEGIN
  c := public.portal_customer(p_token);
  IF c.id IS NULL THEN
    RETURN NULL;
  END IF;

  SELECT * INTO o
    FROM public.orders
   WHERE lower(trim(COALESCE(order_number, ''))) =
         lower(trim(COALESCE(p_order_number, '')))
     AND lower(trim(COALESCE(customer_name, ''))) IN (
           lower(trim(COALESCE(c.short_name, ''))),
           lower(trim(COALESCE(c.name, ''))))
   ORDER BY created_at DESC
   LIMIT 1;

  IF o.id IS NULL THEN
    RETURN NULL;
  END IF;

  RETURN json_build_object(
    'order_number', o.order_number,
    'date_ordered', o.date_ordered,
    'date_due',     o.date_due,
    'status',       COALESCE(o.header->>'status', 'Pending'),
    'region',       COALESCE(o.header->>'Location', ''),
    'job',          COALESCE(o.header->>'Job', ''),
    'stage', CASE
        WHEN COALESCE(o.header->>'status', 'Pending') = 'Dispatched'
          THEN CASE WHEN COALESCE(o.header->>'Location','') = 'Pick Up'
                    THEN 'Collected' ELSE 'Delivered' END
        WHEN COALESCE(o.header->>'status', 'Pending') = 'Complete'
          THEN CASE WHEN COALESCE(o.header->>'Location','') = 'Pick Up'
                    THEN 'Ready for pick up' ELSE 'Ready for delivery' END
        WHEN COALESCE(o.header->>'status', 'Pending') = 'In Production'
          THEN 'Being made'
        ELSE 'Received' END,
    -- Where it is, and anything holding it up.
    'freight', COALESCE(o.header->'freight', '{}'::jsonb),
    -- What they ordered, described plainly. No prices: an order's pricing is
    -- an invoice matter, and their quote already carries what they agreed.
    'items', COALESCE((
        SELECT json_agg(json_build_object(
                 'quantity',    it->>'Quantity',
                 'description', trim(concat_ws(' ',
                     NULLIF(it->>'Filter Type', ''),
                     NULLIF(it->>'Media Type', ''),
                     CASE WHEN COALESCE(it->>'Short','') <> ''
                          THEN concat(it->>'Short', ' x ', it->>'Long',
                                      ' x ', it->>'Channel', 'mm') END)),
                 'part_number', it->>'Part Number'))
          FROM jsonb_array_elements(COALESCE(o.items, '[]'::jsonb)) AS it
      ), '[]'::json)
  );
  -- Deliberately absent: internal notes, who keyed it, costs, and every other
  -- customer's orders.
END;
$$;

REVOKE ALL ON FUNCTION public.portal_sign_in(text, text) FROM public;
REVOKE ALL ON FUNCTION public.portal_order(text, text)   FROM public;
GRANT EXECUTE ON FUNCTION public.portal_sign_in(text, text) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.portal_order(text, text)   TO anon, authenticated;
