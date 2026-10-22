-- ============================================================
-- TAF Order App - Speed
-- Run this in Supabase Dashboard -> SQL Editor. Safe to re-run.
--
-- THE ORDER LIST WAS PULLING EVERY ORDER IN FULL
--
-- Previous Orders, the Dashboard, Delivery and Load-from-an-Order all call
-- one query that did `select *` on orders. That includes the `items` JSON -
-- every line of every order ever placed - and it was being downloaded and
-- parsed in Python every time one of those screens was opened.
--
-- The list shows a row count, not the lines. So this view gives it the count
-- and leaves the lines in the database until something actually needs them.
--
-- It also fixes a bug: that query had no paging, and PostgREST stops at 1000
-- rows. Past a thousand orders, the oldest simply stopped appearing.
--
-- security_invoker means the view is read as whoever is querying it, so the
-- row-level security on `orders` still applies. Without it a view owned by
-- postgres would hand out every order regardless of policy.
-- ============================================================

CREATE OR REPLACE VIEW public.orders_list
WITH (security_invoker = true) AS
SELECT
    o.id,
    o.order_type,
    o.customer_name,
    o.order_number,
    o.date_ordered,
    o.date_due,
    o.created_at,
    o.user_id,
    o.user_email,
    o.username,
    o.full_name,
    o.created_by_role,
    o.archived,
    o.header,
    jsonb_array_length(COALESCE(o.items, '[]'::jsonb)) AS n_items
FROM public.orders o;

GRANT SELECT ON public.orders_list TO authenticated;

-- ── Indexes for the lookups that got slower as things were added ────────────

-- The order list is always newest-first.
CREATE INDEX IF NOT EXISTS orders_created_idx
    ON public.orders (created_at DESC);

-- The duplicate-order guard looks orders up by number, and the customer
-- portal matches them by name. Both compare case- and space-insensitively,
-- so the index has to be on the same expression or it will not be used.
CREATE INDEX IF NOT EXISTS orders_order_number_idx
    ON public.orders (lower(btrim(COALESCE(order_number, ''))));
CREATE INDEX IF NOT EXISTS orders_customer_name_idx
    ON public.orders (lower(btrim(COALESCE(customer_name, ''))));

-- The portal signs a customer in by matching their email.
CREATE INDEX IF NOT EXISTS customers_email_idx
    ON public.customers (lower(btrim(COALESCE(email, ''))));

-- Quotes are listed newest-first and filtered by status.
CREATE INDEX IF NOT EXISTS quotes_created_status_idx
    ON public.quotes (status, created_at DESC);

-- Stock movements are read per item, newest first.
CREATE INDEX IF NOT EXISTS stock_tx_item_idx
    ON public.stock_transactions (stock_item_id, created_at DESC);

-- ── What the Dashboard's stock alerts need ──────────────────────────────────
-- The alerts panel counted media use by walking every order's lines in
-- Python. It only ever wanted this month, so it asks for this month.

CREATE OR REPLACE FUNCTION public.media_usage_since(p_since date)
RETURNS TABLE (media_type text, used bigint)
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
  SELECT COALESCE(NULLIF(it->>'Media Type', ''),
                  NULLIF(it->>'media_type', ''),
                  NULLIF(it->>'media', ''))       AS media_type,
         count(*)                                  AS used
    FROM public.orders o
    CROSS JOIN LATERAL jsonb_array_elements(COALESCE(o.items, '[]'::jsonb)) AS it
   WHERE o.created_at >= p_since
     AND COALESCE(NULLIF(it->>'Media Type', ''),
                  NULLIF(it->>'media_type', ''),
                  NULLIF(it->>'media', '')) IS NOT NULL
   GROUP BY 1;
$$;

REVOKE ALL ON FUNCTION public.media_usage_since(date) FROM public;
GRANT EXECUTE ON FUNCTION public.media_usage_since(date) TO authenticated;
