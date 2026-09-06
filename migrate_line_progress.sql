-- ============================================================
-- TAF Order App - Ticking off an order one line at a time
-- Run this in Supabase Dashboard -> SQL Editor. Safe to re-run.
--
-- An order is not one thing that is either made or not. It is eight filters,
-- and on a Tuesday afternoon three of them are done. Knowing which three is
-- what lets the Dashboard say what is really left, lets a customer follow
-- their order honestly, and gives a scanning gun something to scan at.
--
-- Lines live in the order's items JSON array, so marking one made means
-- changing one entry of an array. Doing that in the app means reading the
-- whole array, changing one entry and writing it all back - and two people
-- at two benches ticking two different lines of the same order is the
-- normal case here, not a rare one. Whoever saved second would erase the
-- other's tick, and nobody would ever know.
--
-- This finds the line by its own id and rewrites only that element.
--
-- SECURITY INVOKER on purpose: it runs as whoever called it, so the
-- row-level security policies on orders still decide who may change what.
-- ============================================================

DROP FUNCTION IF EXISTS public.set_order_line_made(uuid, text, boolean, text, text);

CREATE FUNCTION public.set_order_line_made(
    p_order_id uuid,
    p_line_id  text,
    p_made     boolean,
    p_by       text,
    p_at       text)
RETURNS uuid
LANGUAGE sql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
    UPDATE public.orders
       SET items = (
           SELECT jsonb_agg(
                      CASE WHEN line ->> 'line_id' = p_line_id
                           THEN line
                                || jsonb_build_object('made', p_made)
                                || jsonb_build_object('made_by',
                                       CASE WHEN p_made THEN p_by ELSE '' END)
                                || jsonb_build_object('made_at', p_at)
                           ELSE line
                      END
                      ORDER BY ord)
             FROM jsonb_array_elements(items) WITH ORDINALITY AS t(line, ord))
     WHERE id = p_order_id
       AND EXISTS (SELECT 1
                     FROM jsonb_array_elements(items) AS l(line)
                    WHERE l.line ->> 'line_id' = p_line_id)
    RETURNING id;
$$;

-- Two things worth spelling out.
--
-- WITH ORDINALITY and ORDER BY ord: jsonb_agg over a set has no order of its
-- own, and an order whose lines silently reshuffle every time somebody ticks
-- one is worse than no ticking at all. The line the worksheet says is line 3
-- has to stay line 3.
--
-- The EXISTS: an UPDATE that matches no row is not an error in Postgres. The
-- id comes back only when a line was actually found, so the app can tell
-- "marked it" from "that line is not there any more" instead of reporting
-- both as success.

REVOKE ALL ON FUNCTION public.set_order_line_made(uuid, text, boolean, text, text) FROM public;
GRANT EXECUTE ON FUNCTION public.set_order_line_made(uuid, text, boolean, text, text) TO authenticated;


-- ── How far along each order is, in the list ────────────────────────────────
-- The order list deliberately does not fetch line items - they are the bulk
-- of an order and no list shows them. So the count of what is made has to be
-- worked out here, next to n_items, or the list would have to pull every line
-- of every order to draw one column.
--
-- This replaces the view from migrate_performance.sql, adding one column. Run
-- that one first; running this one again afterwards is harmless.

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
    jsonb_array_length(COALESCE(o.items, '[]'::jsonb)) AS n_items,
    (SELECT count(*)
       FROM jsonb_array_elements(COALESCE(o.items, '[]'::jsonb)) AS l(line)
      WHERE l.line -> 'made' = 'true'::jsonb)               AS n_made
FROM public.orders o;

GRANT SELECT ON public.orders_list TO authenticated;
