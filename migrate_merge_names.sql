-- ============================================================================
-- Step 36: an account's name follows onto its orders
--
-- Merging customers moved each order's account and the name in the order
-- list, but:
--   * the account that stayed kept its old name on its own orders, even when
--     the merge chose the other account's name for it;
--   * the name inside the order itself (orders.header, "Customer Name") was
--     never changed - and View Order, reprints and regenerated worksheets
--     read it from there;
--   * an order only moved if its name matched the account's exactly.
--
-- sync_customer_order_names(account) puts the account's name - its short
-- name, else its name, the same as a merge uses - on every order of that
-- account and of every account merged into it: those linked to them, and
-- unlinked ones under any of their names or the purchase-order wording they
-- are known by (never a name another live account also uses, which would
-- not say whose the order is). Quotes follow as well.
--
-- The app runs it after every merge and every undo, and from Customers >
-- Customer > "Put this name on their orders" after renaming one. This file
-- also runs it once over every merge already made.
--
-- Needs step 33 (migrate_packing_and_merge.sql). Safe to run more than once.
-- ============================================================================

DO $$
BEGIN
  IF to_regprocedure('public.merge_customers(text,uuid,uuid[],jsonb,jsonb)') IS NULL THEN
    RAISE EXCEPTION 'Run migrate_packing_and_merge.sql (step 33) first.';
  END IF;
END $$;


-- The work, with no permission check: for this file's one-off run, and for
-- the checked function below. Nobody can call it directly.
CREATE OR REPLACE FUNCTION public._sync_customer_order_names(p_id uuid)
RETURNS int
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_target uuid := public.resolve_customer(p_id);
  v_link   text;
  v_ids    uuid[];
  v_names  text[];
  n_orders int := 0;
BEGIN
  SELECT COALESCE(NULLIF(btrim(short_name), ''), btrim(name)) INTO v_link
    FROM public.customers WHERE id = v_target;
  IF COALESCE(v_link, '') = '' THEN
    RETURN 0;
  END IF;

  -- The account and everything merged into it, however many times over.
  SELECT array_agg(id) INTO v_ids
    FROM public.customers WHERE public.resolve_customer(id) = v_target;

  -- The names an unlinked order of theirs can be known by.
  SELECT COALESCE(array_agg(DISTINCT nm), '{}') INTO v_names FROM (
    SELECT unnest(public.customer_link_names(x, v_ids)) AS nm
      FROM unnest(v_ids) AS x
    UNION
    SELECT lower(btrim(a))
      FROM public.customers c,
           LATERAL jsonb_array_elements_text(
             COALESCE(c.po_aliases, '[]'::jsonb)) AS a
     WHERE c.id = ANY (v_ids) AND btrim(a) <> ''
       AND NOT EXISTS (
         SELECT 1 FROM public.customers o
          WHERE o.id <> ALL (v_ids) AND o.merged_into IS NULL
            AND (lower(btrim(o.name)) = lower(btrim(a))
                 OR lower(btrim(COALESCE(o.short_name, ''))) = lower(btrim(a))))
  ) t;

  UPDATE public.orders o
     SET customer_id   = v_target,
         customer_name = v_link,
         header        = jsonb_set(COALESCE(o.header, '{}'::jsonb),
                                   '{Customer Name}', to_jsonb(v_link))
   WHERE (o.customer_id = ANY (v_ids)
          OR (o.customer_id IS NULL
              AND lower(btrim(COALESCE(o.customer_name, ''))) = ANY (v_names)))
     AND (o.customer_id IS DISTINCT FROM v_target
          OR o.customer_name IS DISTINCT FROM v_link
          OR o.header ->> 'Customer Name' IS DISTINCT FROM v_link);
  GET DIAGNOSTICS n_orders = ROW_COUNT;

  IF to_regclass('public.quotes') IS NOT NULL THEN
    UPDATE public.quotes q
       SET customer_id = v_target, customer_name = v_link
     WHERE (q.customer_id = ANY (v_ids)
            OR (q.customer_id IS NULL
                AND lower(btrim(COALESCE(q.customer_name, ''))) = ANY (v_names)))
       AND (q.customer_id IS DISTINCT FROM v_target
            OR q.customer_name IS DISTINCT FROM v_link);
  END IF;

  RETURN n_orders;
END;
$$;

REVOKE ALL ON FUNCTION public._sync_customer_order_names(uuid)
  FROM public, anon, authenticated;


-- What the app calls. A manager's job, like merging.
CREATE OR REPLACE FUNCTION public.sync_customer_order_names(p_id uuid)
RETURNS int
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF NOT public.is_manager() THEN
    RAISE EXCEPTION 'Only a manager can change the name on past orders.';
  END IF;
  RETURN public._sync_customer_order_names(p_id);
END;
$$;

REVOKE ALL ON FUNCTION public.sync_customer_order_names(uuid) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.sync_customer_order_names(uuid) TO authenticated;


-- Every merge already made, once.
DO $$
DECLARE
  r record;
BEGIN
  FOR r IN SELECT DISTINCT public.resolve_customer(id) AS target
             FROM public.customers WHERE merged_into IS NOT NULL
  LOOP
    PERFORM public._sync_customer_order_names(r.target);
  END LOOP;
END $$;
