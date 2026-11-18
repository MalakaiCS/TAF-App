-- ============================================================
-- TAF Order App - Seven more of the thirty
-- Run this in Supabase Dashboard -> SQL Editor. Safe to re-run.
-- Needs migrate_features.sql first (is_admin, and the feature switches).
--
-- Every one of these arrives behind a switch that is off, so running this
-- file changes nothing anybody sees until a Director or an Admin turns the
-- feature on. It only makes the room.
--
--   kits                a set of filters entered as one line
--   sites               what is actually installed at each plant room
--   returns             a filter that came back
--   stocktakes          counting a rack without losing your place
--   purchase_orders     buying, rather than only knowing
--   customer_prices     an agreed rate that applies without being remembered
--   shutdown_days       Christmas, and the Mondays that do not exist
--
-- Lines are kept as jsonb, the same way an order keeps its items. It is not
-- tidier than a child table, but it is the shape the rest of this system
-- already reads and writes, and one shape everybody knows beats two shapes
-- where one of them is correct.
-- ============================================================


-- ── Kits ────────────────────────────────────────────────────────────────────
-- An AHU that takes four panels and two bags is six lines typed every time,
-- and six chances to leave one out.

CREATE TABLE IF NOT EXISTS public.kits (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name       text        NOT NULL,
    note       text        NOT NULL DEFAULT '',
    lines      jsonb       NOT NULL DEFAULT '[]'::jsonb,
    active     boolean     NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by text        NOT NULL DEFAULT ''
);

CREATE UNIQUE INDEX IF NOT EXISTS kits_one_name
    ON public.kits (lower(btrim(name)));

ALTER TABLE public.kits ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Staff read kits"     ON public.kits;
DROP POLICY IF EXISTS "Staff add kits"      ON public.kits;
DROP POLICY IF EXISTS "Staff change kits"   ON public.kits;
DROP POLICY IF EXISTS "Managers bin kits"   ON public.kits;

CREATE POLICY "Staff read kits"   ON public.kits FOR SELECT TO authenticated
    USING (public.is_staff());
CREATE POLICY "Staff add kits"    ON public.kits FOR INSERT TO authenticated
    WITH CHECK (public.is_staff());
CREATE POLICY "Staff change kits" ON public.kits FOR UPDATE TO authenticated
    USING (public.is_staff()) WITH CHECK (public.is_staff());
-- Deleting one takes it off every screen at once, including from under
-- somebody halfway through using it.
CREATE POLICY "Managers bin kits" ON public.kits FOR DELETE TO authenticated
    USING (public.is_manager());


-- ── What is installed where ─────────────────────────────────────────────────
-- Most of the work is replacing the same units on a cycle, and what is in
-- each plant room currently lives in old orders and in people's heads. With
-- it, a service visit writes its own order.

CREATE TABLE IF NOT EXISTS public.sites (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_name text        NOT NULL DEFAULT '',
    name          text        NOT NULL,
    location      text        NOT NULL DEFAULT '',
    note          text        NOT NULL DEFAULT '',
    filters       jsonb       NOT NULL DEFAULT '[]'::jsonb,
    every_months  integer     NOT NULL DEFAULT 0,   -- 0 = no set cycle
    last_done     date,
    active        boolean     NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now(),
    created_by    text        NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS sites_by_customer
    ON public.sites (lower(btrim(customer_name)), name);

ALTER TABLE public.sites ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Staff read sites"   ON public.sites;
DROP POLICY IF EXISTS "Staff add sites"    ON public.sites;
DROP POLICY IF EXISTS "Staff change sites" ON public.sites;
DROP POLICY IF EXISTS "Managers bin sites" ON public.sites;

CREATE POLICY "Staff read sites"   ON public.sites FOR SELECT TO authenticated
    USING (public.is_staff());
CREATE POLICY "Staff add sites"    ON public.sites FOR INSERT TO authenticated
    WITH CHECK (public.is_staff());
CREATE POLICY "Staff change sites" ON public.sites FOR UPDATE TO authenticated
    USING (public.is_staff()) WITH CHECK (public.is_staff());
CREATE POLICY "Managers bin sites" ON public.sites FOR DELETE TO authenticated
    USING (public.is_manager());


-- ── A filter that came back ─────────────────────────────────────────────────
-- Recorded against the order it came from, so "is it one product, one media
-- or one customer's site" is a question with an answer.

CREATE TABLE IF NOT EXISTS public.returns (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id      uuid REFERENCES public.orders(id) ON DELETE SET NULL,
    order_number  text        NOT NULL DEFAULT '',
    customer_name text        NOT NULL DEFAULT '',
    quantity      numeric     NOT NULL DEFAULT 1 CHECK (quantity > 0),
    reason        text        NOT NULL DEFAULT '',
    detail        text        NOT NULL DEFAULT '',
    outcome       text        NOT NULL DEFAULT 'open',
    created_at    timestamptz NOT NULL DEFAULT now(),
    created_by    text        NOT NULL DEFAULT '',
    closed_at     timestamptz,
    closed_by     text        NOT NULL DEFAULT ''
);

-- ON DELETE SET NULL, not CASCADE: deleting an old order must not delete the
-- record that something came back off it. The return survives with the order
-- number still written on it, which is what somebody reading it needs.

CREATE INDEX IF NOT EXISTS returns_recent
    ON public.returns (created_at DESC);

ALTER TABLE public.returns ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Staff read returns"     ON public.returns;
DROP POLICY IF EXISTS "Staff add returns"      ON public.returns;
DROP POLICY IF EXISTS "Staff change returns"   ON public.returns;
DROP POLICY IF EXISTS "Managers bin returns"   ON public.returns;

CREATE POLICY "Staff read returns"   ON public.returns FOR SELECT TO authenticated
    USING (public.is_staff());
-- Anyone, because the person a return is handed to is whoever is at the
-- counter, and a form only a manager can fill in is a form nobody fills in.
CREATE POLICY "Staff add returns"    ON public.returns FOR INSERT TO authenticated
    WITH CHECK (public.is_staff());
CREATE POLICY "Staff change returns" ON public.returns FOR UPDATE TO authenticated
    USING (public.is_staff()) WITH CHECK (public.is_staff());
-- A record of something going wrong that the person it reflects on can
-- quietly remove is not a record.
CREATE POLICY "Managers bin returns" ON public.returns FOR DELETE TO authenticated
    USING (public.is_manager());


-- ── Counting a rack ─────────────────────────────────────────────────────────
-- Counting a whole shed one item at a time is why stocktakes do not happen.
-- A session remembers what has been counted and what has not, so it can be
-- put down at lunchtime and picked up after.

CREATE TABLE IF NOT EXISTS public.stocktakes (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text        NOT NULL DEFAULT '',
    note        text        NOT NULL DEFAULT '',
    started_at  timestamptz NOT NULL DEFAULT now(),
    started_by  text        NOT NULL DEFAULT '',
    finished_at timestamptz,
    finished_by text        NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS public.stocktake_counts (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    stocktake_id uuid NOT NULL REFERENCES public.stocktakes(id) ON DELETE CASCADE,
    item_id      uuid NOT NULL REFERENCES public.stock_items(id) ON DELETE CASCADE,
    counted      numeric     NOT NULL,
    was          numeric     NOT NULL DEFAULT 0,
    counted_at   timestamptz NOT NULL DEFAULT now(),
    counted_by   text        NOT NULL DEFAULT ''
);

-- One count per item per session. Counting the same rack twice is a thing
-- that happens; the second count is the one that stands, and this makes that
-- an update rather than two rows disagreeing.
CREATE UNIQUE INDEX IF NOT EXISTS stocktake_one_per_item
    ON public.stocktake_counts (stocktake_id, item_id);

ALTER TABLE public.stocktakes       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stocktake_counts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Staff read stocktakes"    ON public.stocktakes;
DROP POLICY IF EXISTS "Staff run stocktakes"     ON public.stocktakes;
DROP POLICY IF EXISTS "Staff finish stocktakes"  ON public.stocktakes;
DROP POLICY IF EXISTS "Managers bin stocktakes"  ON public.stocktakes;
DROP POLICY IF EXISTS "Staff read counts"        ON public.stocktake_counts;
DROP POLICY IF EXISTS "Staff add counts"         ON public.stocktake_counts;
DROP POLICY IF EXISTS "Staff fix counts"         ON public.stocktake_counts;
DROP POLICY IF EXISTS "Managers bin counts"      ON public.stocktake_counts;

CREATE POLICY "Staff read stocktakes"   ON public.stocktakes FOR SELECT TO authenticated
    USING (public.is_staff());
CREATE POLICY "Staff run stocktakes"    ON public.stocktakes FOR INSERT TO authenticated
    WITH CHECK (public.is_staff());
CREATE POLICY "Staff finish stocktakes" ON public.stocktakes FOR UPDATE TO authenticated
    USING (public.is_staff()) WITH CHECK (public.is_staff());
CREATE POLICY "Managers bin stocktakes" ON public.stocktakes FOR DELETE TO authenticated
    USING (public.is_manager());

CREATE POLICY "Staff read counts" ON public.stocktake_counts FOR SELECT TO authenticated
    USING (public.is_staff());
CREATE POLICY "Staff add counts"  ON public.stocktake_counts FOR INSERT TO authenticated
    WITH CHECK (public.is_staff());
CREATE POLICY "Staff fix counts"  ON public.stocktake_counts FOR UPDATE TO authenticated
    USING (public.is_staff()) WITH CHECK (public.is_staff());
CREATE POLICY "Managers bin counts" ON public.stocktake_counts FOR DELETE TO authenticated
    USING (public.is_manager());


-- ── Applying what was counted ───────────────────────────────────────────────
-- A stocktake that ends in a list nobody acts on is a day spent counting.
-- This turns every variance into a real stock movement, through the same
-- locked-row, client-reference path a scanning gun uses - so a session
-- applied twice by two people is applied once.

CREATE OR REPLACE FUNCTION public.apply_stocktake(p_stocktake uuid)
RETURNS TABLE (item_id uuid, moved numeric, applied boolean)
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    r RECORD;
    v_after numeric;
    v_change numeric;
    v_applied boolean;
BEGIN
    FOR r IN
        SELECT c.item_id, c.counted
          FROM public.stocktake_counts c
         WHERE c.stocktake_id = p_stocktake
         ORDER BY c.counted_at
    LOOP
        SELECT a.quantity_after, a.quantity_change, a.applied
          INTO v_after, v_change, v_applied
          FROM public.adjust_stock_atomic(
                   r.item_id, 'count', r.counted,
                   'Stocktake ' || p_stocktake::text,
                   'stocktake-' || p_stocktake::text || '-' || r.item_id::text,
                   '', 'stocktake') AS a;
        item_id := r.item_id;
        moved   := v_change;
        applied := v_applied;
        RETURN NEXT;
    END LOOP;
END;
$$;

REVOKE ALL ON FUNCTION public.apply_stocktake(uuid) FROM public;
GRANT EXECUTE ON FUNCTION public.apply_stocktake(uuid) TO authenticated;


-- ── Buying ──────────────────────────────────────────────────────────────────
-- Low stock is currently a red row and a phone call. A quantity marked as on
-- order is the other half: without it the on-hand figure keeps looking like a
-- crisis while the roll is on a truck.

CREATE TABLE IF NOT EXISTS public.purchase_orders (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    supplier       text        NOT NULL DEFAULT '',
    supplier_email text        NOT NULL DEFAULT '',
    reference      text        NOT NULL DEFAULT '',
    status         text        NOT NULL DEFAULT 'draft',
    lines          jsonb       NOT NULL DEFAULT '[]'::jsonb,
    note           text        NOT NULL DEFAULT '',
    expected       date,
    created_at     timestamptz NOT NULL DEFAULT now(),
    created_by     text        NOT NULL DEFAULT '',
    sent_at        timestamptz,
    received_at    timestamptz
);

CREATE INDEX IF NOT EXISTS purchase_orders_open
    ON public.purchase_orders (status, created_at DESC);

ALTER TABLE public.purchase_orders ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Staff read purchases"      ON public.purchase_orders;
DROP POLICY IF EXISTS "Managers raise purchases"  ON public.purchase_orders;
DROP POLICY IF EXISTS "Managers change purchases" ON public.purchase_orders;
DROP POLICY IF EXISTS "Managers bin purchases"    ON public.purchase_orders;

CREATE POLICY "Staff read purchases" ON public.purchase_orders
    FOR SELECT TO authenticated USING (public.is_staff());
-- Committing the company to spending money is a manager's decision, unlike
-- writing down an offcut.
CREATE POLICY "Managers raise purchases" ON public.purchase_orders
    FOR INSERT TO authenticated WITH CHECK (public.is_manager());
CREATE POLICY "Managers change purchases" ON public.purchase_orders
    FOR UPDATE TO authenticated
    USING (public.is_manager()) WITH CHECK (public.is_manager());
CREATE POLICY "Managers bin purchases" ON public.purchase_orders
    FOR DELETE TO authenticated USING (public.is_manager());


-- ── What a particular customer pays ─────────────────────────────────────────
-- One price per part number is not how anybody sells. An agreed rate that has
-- to be remembered is an agreed rate that gets forgotten on a Friday.

CREATE TABLE IF NOT EXISTS public.customer_prices (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id uuid REFERENCES public.customers(id) ON DELETE CASCADE,
    part_number text        NOT NULL DEFAULT '',
    unit_price  numeric,
    discount    numeric,                     -- per cent off the list price
    note        text        NOT NULL DEFAULT '',
    created_at  timestamptz NOT NULL DEFAULT now(),
    created_by  text        NOT NULL DEFAULT '',
    CHECK (unit_price IS NOT NULL OR discount IS NOT NULL),
    CHECK (discount IS NULL OR (discount >= 0 AND discount < 100))
);

-- A blank part number is the customer's across-the-board discount. One row
-- per customer per part number, so there is never a pair of rows disagreeing
-- about what somebody pays.
CREATE UNIQUE INDEX IF NOT EXISTS customer_prices_one_each
    ON public.customer_prices (customer_id, upper(btrim(part_number)));

ALTER TABLE public.customer_prices ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Staff read customer prices"    ON public.customer_prices;
DROP POLICY IF EXISTS "Managers set customer prices"  ON public.customer_prices;
DROP POLICY IF EXISTS "Managers fix customer prices"  ON public.customer_prices;
DROP POLICY IF EXISTS "Managers bin customer prices"  ON public.customer_prices;

CREATE POLICY "Staff read customer prices" ON public.customer_prices
    FOR SELECT TO authenticated USING (public.is_staff());
CREATE POLICY "Managers set customer prices" ON public.customer_prices
    FOR INSERT TO authenticated WITH CHECK (public.is_manager());
CREATE POLICY "Managers fix customer prices" ON public.customer_prices
    FOR UPDATE TO authenticated
    USING (public.is_manager()) WITH CHECK (public.is_manager());
CREATE POLICY "Managers bin customer prices" ON public.customer_prices
    FOR DELETE TO authenticated USING (public.is_manager());


-- ── Days that do not exist ──────────────────────────────────────────────────
-- Christmas, the public holidays, and the fortnight the place is shut. A due
-- date that lands on one of them was never going to be met.

CREATE TABLE IF NOT EXISTS public.shutdown_days (
    day        date PRIMARY KEY,
    name       text        NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by text        NOT NULL DEFAULT ''
);

ALTER TABLE public.shutdown_days ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Staff read shutdown days"    ON public.shutdown_days;
DROP POLICY IF EXISTS "Managers set shutdown days"  ON public.shutdown_days;
DROP POLICY IF EXISTS "Managers fix shutdown days"  ON public.shutdown_days;
DROP POLICY IF EXISTS "Managers bin shutdown days"  ON public.shutdown_days;

CREATE POLICY "Staff read shutdown days" ON public.shutdown_days
    FOR SELECT TO authenticated USING (public.is_staff());
CREATE POLICY "Managers set shutdown days" ON public.shutdown_days
    FOR INSERT TO authenticated WITH CHECK (public.is_manager());
CREATE POLICY "Managers fix shutdown days" ON public.shutdown_days
    FOR UPDATE TO authenticated
    USING (public.is_manager()) WITH CHECK (public.is_manager());
CREATE POLICY "Managers bin shutdown days" ON public.shutdown_days
    FOR DELETE TO authenticated USING (public.is_manager());
