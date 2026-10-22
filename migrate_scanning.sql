-- ============================================================
-- TAF Order App - Scanning groundwork (barcode guns)
-- Run this in Supabase Dashboard -> SQL Editor. Safe to re-run.
--
-- WHAT THIS FIXES, AND WHY IT MATTERS BEFORE ANY GUN EXISTS
--
-- 1. TWO PEOPLE COUNTING AT ONCE LOSES A COUNT.
--    adjust_stock() read stock_on_hand, worked out the new figure in Python,
--    and wrote it back. One person on one PC is fine. Two guns counting the
--    same rack at the same moment both read 40, both write their own answer,
--    and one count vanishes with nothing in the log to say so. The arithmetic
--    has to happen inside the database, on a locked row.
--
-- 2. A GUN THAT LOSES SIGNAL WILL DOUBLE-COUNT.
--    Any handheld worth using queues scans when the wifi drops and sends them
--    when it comes back. If the network dies AFTER the write lands but BEFORE
--    the reply arrives, the gun cannot tell "it failed" from "it worked and I
--    didn't hear" - so it retries, and the stock moves twice. The cure is for
--    the gun to stamp each scan with its own reference and for the database to
--    apply a given reference once and only once. Every retry after that is
--    answered with what happened the first time.
--
-- 3. A SCANNED CODE HAS TO MEAN EXACTLY ONE THING.
--    sku had no index and no uniqueness, so two items could carry the same
--    code and a scan would be a coin toss. And nothing told an app what it had
--    just scanned - a stock code, an order number, or a part number.
-- ============================================================

-- ── 1. A SKU identifies one item ────────────────────────────────────────────

-- Lookups come in as whatever the label prints, so match the way the app asks.
CREATE INDEX IF NOT EXISTS stock_items_sku_idx
    ON public.stock_items (upper(btrim(COALESCE(sku, ''))));

-- Uniqueness is what makes a scan unambiguous, but an existing list may
-- already have duplicates - and failing the whole migration over that would
-- leave everything else in this file unapplied. So try, and if it can't be
-- done, say exactly which codes are in the way.
DO $$
DECLARE
    dupes text;
BEGIN
    BEGIN
        CREATE UNIQUE INDEX IF NOT EXISTS stock_items_sku_unique
            ON public.stock_items (upper(btrim(sku)))
            WHERE btrim(COALESCE(sku, '')) <> '';
        RAISE NOTICE 'SKUs are unique - a scan will find exactly one item.';
    EXCEPTION WHEN unique_violation THEN
        SELECT string_agg(DISTINCT upper(btrim(sku)), ', ')
          INTO dupes
          FROM public.stock_items
         WHERE btrim(COALESCE(sku, '')) <> ''
         GROUP BY upper(btrim(sku))
        HAVING count(*) > 1;
        RAISE WARNING 'Duplicate SKUs, so scanning them is a coin toss: %', dupes;
        RAISE WARNING 'Fix those in Stock, then run this file again.';
    END;
END $$;


-- ── 2. Applying a scan once, even when it is sent twice ─────────────────────

-- The gun's own reference for one scan. Unique, so the second copy of a
-- retried scan cannot become a second movement.
ALTER TABLE public.stock_transactions
    ADD COLUMN IF NOT EXISTS client_ref text;

CREATE UNIQUE INDEX IF NOT EXISTS stock_tx_client_ref_unique
    ON public.stock_transactions (client_ref)
    WHERE client_ref IS NOT NULL;

-- Who scanned it, on which handheld - worth having when a count looks wrong.
ALTER TABLE public.stock_transactions
    ADD COLUMN IF NOT EXISTS device text DEFAULT '';


-- ── 3. The adjustment itself, done in the database ──────────────────────────
--
-- SECURITY INVOKER: the caller's own row-level security still decides whether
-- they may touch stock. A SECURITY DEFINER function here would quietly hand
-- every signed-in account write access to the whole stock table.

CREATE OR REPLACE FUNCTION public.adjust_stock_atomic(
    p_item_id    uuid,
    p_type       text,
    p_quantity   numeric,
    p_notes      text DEFAULT '',
    p_client_ref text DEFAULT NULL,
    p_username   text DEFAULT '',
    p_device     text DEFAULT ''
)
RETURNS TABLE (quantity_after numeric, quantity_change numeric, applied boolean)
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_old   numeric;
    v_new   numeric;
    v_delta numeric;
    v_prior public.stock_transactions%ROWTYPE;
BEGIN
    IF p_type NOT IN ('receive', 'use', 'count', 'writeoff') THEN
        RAISE EXCEPTION 'unknown movement %', p_type;
    END IF;

    -- The lock is the whole point: anyone else adjusting this item waits here
    -- instead of reading the figure this call is about to change.
    SELECT stock_on_hand INTO v_old
      FROM public.stock_items
     WHERE id = p_item_id
       FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'no stock item %', p_item_id;
    END IF;

    -- Checked while holding the lock, not before it. Two copies of one scan
    -- queue up here, so by the time the second gets in, the first has
    -- committed and is visible - which is the whole trick. Already done means
    -- this is a retry of a scan that did land, and the honest answer is what
    -- happened the first time, not a second movement.
    IF btrim(COALESCE(p_client_ref, '')) <> '' THEN
        SELECT * INTO v_prior FROM public.stock_transactions
         WHERE client_ref = p_client_ref LIMIT 1;
        IF FOUND THEN
            RETURN QUERY SELECT v_prior.quantity_after,
                                v_prior.quantity_change,
                                false;
            RETURN;
        END IF;
    END IF;

    IF p_type = 'count' THEN
        v_new   := GREATEST(0, p_quantity);      -- a count is the new truth
        v_delta := v_new - v_old;
    ELSIF p_type IN ('use', 'writeoff') THEN
        v_delta := -abs(p_quantity);
        v_new   := GREATEST(0, v_old + v_delta);
        v_delta := v_new - v_old;                -- never claim to have used
                                                 -- more than was there
    ELSE
        v_delta := abs(p_quantity);
        v_new   := v_old + v_delta;
    END IF;

    UPDATE public.stock_items
       SET stock_on_hand = v_new, updated_at = now()
     WHERE id = p_item_id;

    BEGIN
        INSERT INTO public.stock_transactions (
            stock_item_id, transaction_type, quantity_change, quantity_after,
            notes, username, client_ref, device)
        VALUES (p_item_id, p_type, round(v_delta, 3), round(v_new, 3),
                COALESCE(p_notes, ''), COALESCE(p_username, ''),
                NULLIF(btrim(COALESCE(p_client_ref, '')), ''),
                COALESCE(p_device, ''));
    EXCEPTION WHEN unique_violation THEN
        -- Belt and braces: the row lock above should already have serialised
        -- two copies of one scan. If one still gets here, undo this call's
        -- arithmetic (the failed INSERT rolls back on its own, the UPDATE
        -- before this block does not) and answer with what actually stuck.
        IF btrim(COALESCE(p_client_ref, '')) = '' THEN
            RAISE;                      -- nothing to do with idempotency
        END IF;
        UPDATE public.stock_items
           SET stock_on_hand = v_old, updated_at = now()
         WHERE id = p_item_id;
        SELECT * INTO v_prior FROM public.stock_transactions
         WHERE client_ref = p_client_ref LIMIT 1;
        IF NOT FOUND THEN
            RAISE;
        END IF;
        RETURN QUERY SELECT v_prior.quantity_after, v_prior.quantity_change, false;
        RETURN;
    END;

    RETURN QUERY SELECT round(v_new, 3), round(v_delta, 3), true;
END $$;

REVOKE ALL ON FUNCTION public.adjust_stock_atomic(uuid, text, numeric, text,
                                                  text, text, text) FROM public;
GRANT EXECUTE ON FUNCTION public.adjust_stock_atomic(uuid, text, numeric, text,
                                                     text, text, text) TO authenticated;


-- ── 4. What did I just scan? ────────────────────────────────────────────────
--
-- One place that answers it, so the handheld, the phone page and the desktop
-- never drift apart on what a code means. Ordered most specific first: a stock
-- code is a thing you can count, and that is what a gun is usually for.

CREATE OR REPLACE FUNCTION public.resolve_scan(p_code text)
RETURNS TABLE (kind text, ref text, label text, detail text, extra jsonb)
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
WITH code AS (SELECT upper(btrim(COALESCE(p_code, ''))) AS c)
SELECT 'stock'::text,
       s.id::text,
       s.name,
       COALESCE(NULLIF(s.location, ''), 'No location'),
       jsonb_build_object('sku', s.sku, 'unit', s.unit,
                          'stock_on_hand', s.stock_on_hand,
                          'minimum_on_hand', s.minimum_on_hand,
                          'product_type', s.product_type,
                          'location', s.location)
  FROM public.stock_items s, code
 WHERE code.c <> '' AND upper(btrim(COALESCE(s.sku, ''))) = code.c

UNION ALL
SELECT 'order'::text,
       o.id::text,
       o.customer_name,
       COALESCE(o.header ->> 'status', 'Pending'),
       jsonb_build_object('order_number', o.order_number,
                          'date_due', o.date_due,
                          'location', o.header ->> 'Location',
                          'job', o.header ->> 'Job')
  FROM public.orders o, code
 WHERE code.c <> '' AND upper(btrim(COALESCE(o.order_number, ''))) = code.c
   AND COALESCE(o.archived, false) = false

UNION ALL
SELECT 'product'::text,
       p.part_number,
       COALESCE(NULLIF(p.name, ''), p.part_number),
       COALESCE(p.description, ''),
       jsonb_build_object('unit_price', p.unit_price)
  FROM public.price_list p, code
 WHERE code.c <> '' AND upper(btrim(COALESCE(p.part_number, ''))) = code.c
$$;

REVOKE ALL ON FUNCTION public.resolve_scan(text) FROM public;
GRANT EXECUTE ON FUNCTION public.resolve_scan(text) TO authenticated;
