-- ============================================================
-- TAF Order App - Changing one field of an order without losing the rest
-- Run this in Supabase Dashboard -> SQL Editor. Safe to re-run.
--
-- Everything about an order that isn't a line item lives in one JSON column:
-- status, priority, printed, freight, notes. The app used to change one key
-- of it by reading the whole header, editing it in Python, and writing the
-- whole thing back.
--
-- That is two round trips per order, which is slow when you tick twenty of
-- them and mark the lot complete. Worse, it is a read-modify-write with no
-- lock: if someone adds a note to one of those orders in the moment between
-- the read and the write, the write puts back a header that never had the
-- note in it and the note is gone.
--
-- This does the merge in the database, in one statement. `header || patch`
-- replaces the keys given and leaves every other key exactly as it was, so
-- two people changing two different fields of the same order no longer
-- overwrite each other.
--
-- SECURITY INVOKER on purpose: the function runs as whoever called it, so
-- the row-level security policies on orders still decide who may change
-- what. It is a faster, safer way to do the same write - not a way around
-- the rules about who can do it.
-- ============================================================

DROP FUNCTION IF EXISTS public.merge_order_header(uuid, jsonb);

CREATE FUNCTION public.merge_order_header(p_order_id uuid, p_patch jsonb)
RETURNS uuid
LANGUAGE sql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
    UPDATE public.orders
       SET header = COALESCE(header, '{}'::jsonb) || COALESCE(p_patch, '{}'::jsonb)
     WHERE id = p_order_id
    RETURNING id;
$$;

-- Returning the id is what lets the app tell "changed it" from "that row is
-- not there, or you are not allowed to touch it". An UPDATE that matches no
-- row is not an error in Postgres, and it was being read as success.

REVOKE ALL ON FUNCTION public.merge_order_header(uuid, jsonb) FROM public;
GRANT EXECUTE ON FUNCTION public.merge_order_header(uuid, jsonb) TO authenticated;


-- ── Finding the orders that are due ─────────────────────────────────────────
-- Ticking a box on twenty rows means listing them first. The status lives
-- inside the JSON, so filtering by it reads every row without this.

CREATE INDEX IF NOT EXISTS orders_header_status_idx
    ON public.orders ((header ->> 'status'));
