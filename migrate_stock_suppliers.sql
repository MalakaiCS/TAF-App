-- ============================================================================
-- Step 42: where each stock item comes from
--
--   stock_item_suppliers  every supplier a stock item is bought from, with
--                         their code for it (an item code in Xero) and,
--                         optionally, a price that beats Xero's. Channel from
--                         FD Greenwood and from Air Diffusion is two rows;
--                         one of them can be preferred.
--   supply_requests       can name the stock item asked for, so the
--                         purchase order knows its code, price and where it
--                         goes into stock.
--
-- With this, Order Supplies offers the stock items themselves, and low stock
-- becomes a purchase order to the right supplier with codes and prices in.
--
-- Needs migrate_purchasing.sql (step 40) and stock_schema.sql (step 3).
-- Safe to run more than once.
-- ============================================================================

DO $$
BEGIN
  IF to_regclass('public.suppliers') IS NULL THEN
    RAISE EXCEPTION 'Run migrate_purchasing.sql (step 40) first.';
  END IF;
  IF to_regclass('public.stock_items') IS NULL THEN
    RAISE EXCEPTION 'Run stock_schema.sql (step 3) first.';
  END IF;
END $$;


-- ── Who each stock item comes from ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.stock_item_suppliers (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  stock_item_id  uuid NOT NULL REFERENCES public.stock_items(id) ON DELETE CASCADE,
  supplier_id    uuid NOT NULL REFERENCES public.suppliers(id) ON DELETE CASCADE,
  supplier_code  text NOT NULL DEFAULT '',
  unit_price     numeric(12, 4) CHECK (unit_price IS NULL OR unit_price >= 0),
  preferred      boolean NOT NULL DEFAULT false,
  note           text NOT NULL DEFAULT '',
  updated_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (stock_item_id, supplier_id)
);

CREATE INDEX IF NOT EXISTS stock_item_suppliers_supplier
  ON public.stock_item_suppliers (supplier_id);

-- One preferred supplier per stock item at most.
CREATE UNIQUE INDEX IF NOT EXISTS stock_item_suppliers_one_preferred
  ON public.stock_item_suppliers (stock_item_id) WHERE preferred;

ALTER TABLE public.stock_item_suppliers ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS stock_item_suppliers_staff_read ON public.stock_item_suppliers;
DROP POLICY IF EXISTS stock_item_suppliers_managers_add ON public.stock_item_suppliers;
DROP POLICY IF EXISTS stock_item_suppliers_managers_change ON public.stock_item_suppliers;
DROP POLICY IF EXISTS stock_item_suppliers_managers_remove ON public.stock_item_suppliers;
CREATE POLICY stock_item_suppliers_staff_read ON public.stock_item_suppliers
  FOR SELECT TO authenticated USING (public.is_staff());
CREATE POLICY stock_item_suppliers_managers_add ON public.stock_item_suppliers
  FOR INSERT TO authenticated WITH CHECK (public.is_manager());
CREATE POLICY stock_item_suppliers_managers_change ON public.stock_item_suppliers
  FOR UPDATE TO authenticated
  USING (public.is_manager()) WITH CHECK (public.is_manager());
CREATE POLICY stock_item_suppliers_managers_remove ON public.stock_item_suppliers
  FOR DELETE TO authenticated USING (public.is_manager());


-- ── A request can name the stock item ───────────────────────────────────────

ALTER TABLE public.supply_requests ADD COLUMN IF NOT EXISTS stock_item_id uuid;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conname = 'supply_requests_stock_item_fk') THEN
    ALTER TABLE public.supply_requests ADD CONSTRAINT supply_requests_stock_item_fk
      FOREIGN KEY (stock_item_id) REFERENCES public.stock_items(id) ON DELETE SET NULL;
  END IF;
END $$;

-- The same as step 40's, which now also files the stock item - kept here so
-- a database that ran step 40 before it did gets it too.
DROP FUNCTION IF EXISTS public.request_supplies(jsonb, boolean, text, text);
CREATE FUNCTION public.request_supplies(
    p_lines      jsonb,
    p_urgent     boolean DEFAULT false,
    p_note       text    DEFAULT '',
    p_client_ref text    DEFAULT NULL)
RETURNS SETOF public.supply_requests
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_batch uuid := gen_random_uuid();
    v_line  jsonb;
    v_i     int := 0;
    v_first uuid;
    v_who   text;
    v_items text := '';
BEGIN
    IF NOT public.is_staff() THEN
        RAISE EXCEPTION 'Only staff can ask for supplies.';
    END IF;
    IF jsonb_typeof(p_lines) <> 'array' OR jsonb_array_length(p_lines) = 0 THEN
        RAISE EXCEPTION 'Nothing was asked for.';
    END IF;
    IF jsonb_array_length(p_lines) > 50 THEN
        RAISE EXCEPTION 'At most 50 things in one request.';
    END IF;
    -- Sent twice after a dropped connection: the first one stands.
    IF p_client_ref IS NOT NULL AND EXISTS (
         SELECT 1 FROM public.supply_requests
          WHERE client_ref = p_client_ref || '-1') THEN
        RETURN QUERY SELECT * FROM public.supply_requests
                      WHERE client_ref LIKE p_client_ref || '-%'
                      ORDER BY client_ref;
        RETURN;
    END IF;

    PERFORM set_config('taf.supply_batch', 'on', true);
    FOR v_line IN SELECT * FROM jsonb_array_elements(p_lines) LOOP
        v_i := v_i + 1;
        INSERT INTO public.supply_requests
               (item, detail, quantity, urgent, note, client_ref,
                supplier_id, item_code, stock_item_id, batch_id)
        VALUES (coalesce(v_line ->> 'item', ''),
                left(coalesce(v_line ->> 'detail', ''), 200),
                left(coalesce(v_line ->> 'quantity', ''), 60),
                coalesce(p_urgent, false),
                left(coalesce(p_note, ''), 500),
                CASE WHEN p_client_ref IS NULL THEN NULL
                     ELSE p_client_ref || '-' || v_i END,
                nullif(v_line ->> 'supplier_id', '')::uuid,
                nullif(trim(coalesce(v_line ->> 'item_code', '')), ''),
                nullif(v_line ->> 'stock_item_id', '')::uuid,
                v_batch)
        RETURNING id INTO v_first;
        v_items := v_items
            || CASE WHEN v_i > 1 THEN '; ' ELSE '' END
            || coalesce(nullif(trim(v_line ->> 'quantity'), ''), 'some') || ' x '
            || coalesce(v_line ->> 'item', '')
            || CASE WHEN length(trim(coalesce(v_line ->> 'detail', ''))) > 0
                    THEN ' ' || trim(v_line ->> 'detail') ELSE '' END;
    END LOOP;
    PERFORM set_config('taf.supply_batch', 'off', true);

    SELECT coalesce(nullif(trim(full_name), ''), nullif(trim(username), ''),
                    'Somebody') INTO v_who
      FROM public.profiles WHERE id = auth.uid();
    SELECT id INTO v_first FROM public.supply_requests
     WHERE batch_id = v_batch ORDER BY client_ref NULLS LAST, created_at LIMIT 1;

    INSERT INTO public.notifications (recipient, kind, ref_id, title, body)
    SELECT p.id, 'supply_request', v_first,
           CASE WHEN p_urgent THEN 'URGENT: ' ELSE '' END
             || CASE WHEN v_i = 1 THEN 'Supplies asked for'
                     ELSE v_i || ' supplies asked for' END,
           left(coalesce(v_who, 'Somebody') || ' asked for ' || v_items
                || CASE WHEN length(trim(coalesce(p_note, ''))) > 0
                        THEN '. ' || trim(p_note) ELSE '' END, 1000)
      FROM public.profiles p
     WHERE p.approved = true
       AND p.role IN ('Director', 'Admin', 'Manager')
       AND p.id IS DISTINCT FROM auth.uid();

    RETURN QUERY SELECT * FROM public.supply_requests
                  WHERE batch_id = v_batch ORDER BY client_ref, created_at;
END;
$$;

REVOKE ALL ON FUNCTION public.request_supplies(jsonb, boolean, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.request_supplies(jsonb, boolean, text, text) TO authenticated;
