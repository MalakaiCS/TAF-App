-- ============================================================
-- TAF Order App - Customer portal (orders, quotes, account)
-- Run AFTER migrate_quotes.sql, migrate_quote_portal.sql and
-- migrate_staff_access.sql. Safe to re-run.
--
-- A customer follows a link with a random 64-character token and sees THEIR
-- orders, THEIR quotes and THEIR account details. Nothing else.
--
-- They are never signed in. The anonymous role has no access to any table -
-- migrate_staff_access.sql saw to that - and everything here goes through
-- SECURITY DEFINER functions that take the token and hand back one customer's
-- data. There is no query a visitor can shape, and nothing to enumerate.
--
-- The token belongs to the customer, not to a person, so it is revocable:
-- rotating it in the app invalidates every link that was ever sent.
-- ============================================================

ALTER TABLE customers ADD COLUMN IF NOT EXISTS portal_token   text;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS portal_enabled boolean NOT NULL DEFAULT false;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS portal_viewed_at timestamptz;

CREATE UNIQUE INDEX IF NOT EXISTS customers_portal_token_idx
    ON customers (portal_token) WHERE portal_token IS NOT NULL;

-- ── Which customer a token belongs to ───────────────────────────────────────

CREATE OR REPLACE FUNCTION public.portal_customer(p_token text)
RETURNS public.customers
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT * FROM public.customers
   WHERE portal_token = p_token
     AND portal_enabled = true
     AND p_token IS NOT NULL
     AND length(p_token) >= 32
   LIMIT 1;
$$;

REVOKE ALL ON FUNCTION public.portal_customer(text) FROM public;
-- Not granted to anon: it returns the whole customer row and exists only for
-- the three functions below to build on.

-- ── The account ─────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.portal_account(p_token text)
RETURNS json
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  c public.customers%ROWTYPE;
BEGIN
  c := public.portal_customer(p_token);
  IF c.id IS NULL THEN
    RETURN NULL;
  END IF;

  UPDATE public.customers SET portal_viewed_at = now() WHERE id = c.id;

  RETURN json_build_object(
    'name',    COALESCE(NULLIF(c.short_name, ''), c.name, c.legal_name),
    'legal_name',   c.legal_name,
    'contact_person', c.contact_person,
    'email',          c.email,
    'phone',          c.phone,
    'region',         c.region,
    'delivery', json_build_object(
        'address1',  c.delivery_address1,
        'address2',  c.delivery_address2,
        'city',      c.delivery_city,
        'state',     c.delivery_state,
        'postcode',  c.delivery_postcode)
  );
  -- Deliberately absent: internal notes, aliases, the job-number template,
  -- pricing, and every other customer.
END;
$$;

-- ── Their orders, and what stage each is at ─────────────────────────────────

CREATE OR REPLACE FUNCTION public.portal_orders(p_token text)
RETURNS json
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  c public.customers%ROWTYPE;
  result json;
BEGIN
  c := public.portal_customer(p_token);
  IF c.id IS NULL THEN
    RETURN NULL;
  END IF;

  -- Orders are matched on the customer name written on them, which is the
  -- branch short name the app puts there. Matching on that rather than on an
  -- id keeps orders keyed the same way the worksheets are.
  SELECT COALESCE(json_agg(row_to_json(o) ORDER BY o.sort_key DESC), '[]'::json)
    INTO result
  FROM (
    SELECT
      o.order_number,
      o.customer_name,
      o.date_ordered,
      o.date_due,
      o.created_at                                   AS sort_key,
      COALESCE(o.header->>'status', 'Pending')       AS status,
      COALESCE(o.header->>'Location', '')            AS region,
      jsonb_array_length(COALESCE(o.items, '[]'::jsonb)) AS item_count,
      -- What the customer actually wants to know. "Complete" in the shop
      -- means different things depending on how it leaves the building.
      CASE
        WHEN COALESCE(o.header->>'status', 'Pending') = 'Dispatched'
          THEN CASE WHEN COALESCE(o.header->>'Location','') = 'Pick Up'
                    THEN 'Collected' ELSE 'Delivered' END
        WHEN COALESCE(o.header->>'status', 'Pending') = 'Complete'
          THEN CASE WHEN COALESCE(o.header->>'Location','') = 'Pick Up'
                    THEN 'Ready for pick up' ELSE 'Ready for delivery' END
        WHEN COALESCE(o.header->>'status', 'Pending') = 'In Production'
          THEN 'Being made'
        ELSE 'Received'
      END AS stage
    FROM public.orders o
    WHERE lower(trim(o.customer_name)) IN (
            lower(trim(COALESCE(c.short_name, ''))),
            lower(trim(COALESCE(c.name, ''))))
      AND COALESCE(o.customer_name, '') <> ''
    ORDER BY o.created_at DESC
    LIMIT 200
  ) o;

  RETURN result;
END;
$$;

-- ── Their quotes ────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.portal_quotes(p_token text)
RETURNS json
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  c public.customers%ROWTYPE;
  result json;
BEGIN
  c := public.portal_customer(p_token);
  IF c.id IS NULL THEN
    RETURN NULL;
  END IF;

  SELECT COALESCE(json_agg(row_to_json(q) ORDER BY q.created_at DESC), '[]'::json)
    INTO result
  FROM (
    SELECT quote_number, reference, status, total, valid_until, created_at,
           responded_at, response_name,
           -- The link a customer can open to read the quote and answer it.
           public_token AS token
      FROM public.quotes
     WHERE (customer_id = c.id
            OR lower(trim(customer_name)) IN (
                 lower(trim(COALESCE(c.short_name, ''))),
                 lower(trim(COALESCE(c.name, '')))))
       AND status <> 'draft'          -- a draft is not theirs to see yet
     ORDER BY created_at DESC
     LIMIT 100
  ) q;

  RETURN result;
END;
$$;

REVOKE ALL ON FUNCTION public.portal_account(text) FROM public;
REVOKE ALL ON FUNCTION public.portal_orders(text)  FROM public;
REVOKE ALL ON FUNCTION public.portal_quotes(text)  FROM public;

GRANT EXECUTE ON FUNCTION public.portal_account(text) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.portal_orders(text)  TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.portal_quotes(text)  TO anon, authenticated;
