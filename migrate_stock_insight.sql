-- ============================================================================
-- Step 47: stock you can trust
--
--   count_stock()        a count from the phone during a stocktake, safe to
--                        send twice (the same count stands either way), so a
--                        phone out of signal at the back rack can keep it
--   stock_reserved       what the open orders will take of each stock item,
--                        worked out by the desktop app from the same rules it
--                        deducts by - so "free" is on hand less what is spoken
--                        for, on the PC and the phone
--   supplier_prices      what has been paid for each item, from every
--                        purchase order sent, by supplier and date
--   supplier_lead_times  how long each supplier takes, sent to received
--
-- Behind switches that start off (Settings -> Features). Needs stock_schema
-- (3), migrate_more_features.sql (stocktakes, purchase_orders) and
-- migrate_purchasing.sql (40). Safe to run more than once.
-- ============================================================================

DO $$
BEGIN
  IF to_regclass('public.stocktake_counts') IS NULL THEN
    RAISE EXCEPTION 'Run migrate_more_features.sql first.';
  END IF;
  IF to_regclass('public.suppliers') IS NULL THEN
    RAISE EXCEPTION 'Run migrate_purchasing.sql (step 40) first.';
  END IF;
END $$;


-- ── A count from the phone ──────────────────────────────────────────────────
-- What the shelf holds, written against the open stocktake, with what the
-- system said at the time. Counting the same item again replaces the first
-- count - which is also what makes a retry after a dropped signal harmless.
-- Nothing is written to a stocktake that has been finished.

CREATE OR REPLACE FUNCTION public.count_stock(
    p_stocktake uuid,
    p_item      uuid,
    p_counted   numeric,
    p_by        text DEFAULT '')
RETURNS uuid
LANGUAGE sql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
    INSERT INTO public.stocktake_counts
           (stocktake_id, item_id, counted, was, counted_at, counted_by)
    SELECT p_stocktake, s.id, p_counted, COALESCE(s.stock_on_hand, 0), now(),
           left(COALESCE(p_by, ''), 120)
      FROM public.stock_items s
     WHERE s.id = p_item
       AND p_counted >= 0
       AND EXISTS (SELECT 1 FROM public.stocktakes t
                    WHERE t.id = p_stocktake AND t.finished_at IS NULL)
    ON CONFLICT (stocktake_id, item_id) DO UPDATE
       SET counted = EXCLUDED.counted, was = EXCLUDED.was,
           counted_at = now(), counted_by = EXCLUDED.counted_by
    RETURNING id;
$$;

REVOKE ALL ON FUNCTION public.count_stock(uuid, uuid, numeric, text) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.count_stock(uuid, uuid, numeric, text) TO authenticated;


-- ── Spoken for ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.stock_reserved (
    item_id    uuid PRIMARY KEY REFERENCES public.stock_items(id) ON DELETE CASCADE,
    reserved   numeric     NOT NULL DEFAULT 0,
    orders     integer     NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.stock_reserved ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Staff read reserved"  ON public.stock_reserved;
DROP POLICY IF EXISTS "Staff write reserved" ON public.stock_reserved;
CREATE POLICY "Staff read reserved" ON public.stock_reserved FOR SELECT
    TO authenticated USING (public.is_staff());
-- Any PC on staff works it out; it is a figure worked out from the orders,
-- not a decision, and every PC works it out the same way.
CREATE POLICY "Staff write reserved" ON public.stock_reserved FOR ALL
    TO authenticated USING (public.is_staff()) WITH CHECK (public.is_staff());

-- All of it at once, so nobody reads it half written.
CREATE OR REPLACE FUNCTION public.set_stock_reserved(p_rows jsonb)
RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    n integer;
BEGIN
    DELETE FROM public.stock_reserved WHERE true;
    INSERT INTO public.stock_reserved (item_id, reserved, orders)
    SELECT (r ->> 'item_id')::uuid,
           GREATEST(0, COALESCE((r ->> 'reserved')::numeric, 0)),
           GREATEST(0, COALESCE((r ->> 'orders')::integer, 0))
      FROM jsonb_array_elements(COALESCE(p_rows, '[]'::jsonb)) AS r
     WHERE EXISTS (SELECT 1 FROM public.stock_items s
                    WHERE s.id = (r ->> 'item_id')::uuid);
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END;
$$;

REVOKE ALL ON FUNCTION public.set_stock_reserved(jsonb) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.set_stock_reserved(jsonb) TO authenticated;


-- ── What has been paid, and how long it took ────────────────────────────────

CREATE OR REPLACE VIEW public.supplier_prices
WITH (security_invoker = true) AS
SELECT po.id                                          AS po_id,
       COALESCE(po.po_number, '')                     AS po_number,
       COALESCE(po.emailed_at, po.sent_at, po.created_at) AS bought_at,
       po.supplier_id,
       COALESCE(s.name, po.supplier, '')              AS supplier,
       COALESCE(l ->> 'item_code', '')                AS item_code,
       NULLIF(l ->> 'stock_item_id', '')              AS stock_item_id,
       COALESCE(l ->> 'description', '')              AS description,
       (l ->> 'unit_price')::numeric                  AS unit_price,
       CASE WHEN COALESCE(l ->> 'quantity', '') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (l ->> 'quantity')::numeric ELSE 0 END AS quantity
  FROM public.purchase_orders po
  LEFT JOIN public.suppliers s ON s.id = po.supplier_id
 CROSS JOIN LATERAL jsonb_array_elements(COALESCE(po.lines, '[]'::jsonb)) AS l
 WHERE po.status IN ('sent', 'part_received', 'received')
   AND COALESCE(l ->> 'unit_price', '') ~ '^[0-9]+(\.[0-9]+)?$';

GRANT SELECT ON public.supplier_prices TO authenticated;

CREATE OR REPLACE VIEW public.supplier_lead_times
WITH (security_invoker = true) AS
SELECT po.supplier_id,
       COALESCE(s.name, po.supplier, '')                         AS supplier,
       count(*)                                                  AS orders,
       round(avg(extract(epoch FROM po.received_at
                 - COALESCE(po.emailed_at, po.sent_at, po.created_at)) / 86400)::numeric, 1)
                                                                 AS avg_days,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY
                 extract(epoch FROM po.received_at
                 - COALESCE(po.emailed_at, po.sent_at, po.created_at)) / 86400))::numeric, 1)
                                                                 AS median_days,
       round(max(extract(epoch FROM po.received_at
                 - COALESCE(po.emailed_at, po.sent_at, po.created_at)) / 86400)::numeric, 1)
                                                                 AS longest_days,
       max(po.received_at)                                       AS last_received
  FROM public.purchase_orders po
  LEFT JOIN public.suppliers s ON s.id = po.supplier_id
 WHERE po.received_at IS NOT NULL
   AND po.status = 'received'
   AND po.received_at > now() - interval '18 months'
 GROUP BY po.supplier_id, COALESCE(s.name, po.supplier, '');

GRANT SELECT ON public.supplier_lead_times TO authenticated;
