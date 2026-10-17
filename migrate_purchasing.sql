-- ============================================================================
-- Step 40: buying through Xero
--
--   suppliers          who we buy from, pulled from Xero's supplier contacts
--                      (FD Greenwood, Vulcan, ...). code_prefix is the start
--                      of their item codes - FDG for FD Greenwood - so their
--                      items are found by code.
--   xero_items         every item in Xero (code, name, purchase price),
--                      pulled in when asked, each linked to the supplier it
--                      comes from and the stock item it is.
--   supply_requests    can now name a supplier and an item code, and come in
--                      as several items in one go (batch_id): one request for
--                      five things, and managers told once, not five times.
--                      purchase_order_id is the order it went on.
--   purchase_orders    carry the supplier, Xero's PO number, when and to whom
--                      it was emailed, and each line's quantity received.
--   receive_purchase   ticks off what arrived - part or all of each line -
--                      and books it into stock on hand.
--
-- Needs migrate_staff_access.sql (is_staff / is_manager),
-- migrate_supply_requests.sql and migrate_more_features.sql.
-- Safe to run more than once.
-- ============================================================================

DO $$
BEGIN
  IF to_regprocedure('public.is_manager()') IS NULL THEN
    RAISE EXCEPTION 'Run migrate_staff_access.sql first - this uses is_staff() and is_manager().';
  END IF;
  IF to_regclass('public.supply_requests') IS NULL THEN
    RAISE EXCEPTION 'Run migrate_supply_requests.sql first.';
  END IF;
  IF to_regclass('public.purchase_orders') IS NULL THEN
    RAISE EXCEPTION 'Run migrate_more_features.sql first.';
  END IF;
END $$;


-- ── Suppliers ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.suppliers (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name            text NOT NULL CHECK (length(trim(name)) > 0),
  email           text NOT NULL DEFAULT '',
  phone           text NOT NULL DEFAULT '',
  xero_contact_id text UNIQUE,
  code_prefix     text NOT NULL DEFAULT '',
  active          boolean NOT NULL DEFAULT true,
  updated_at      timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.suppliers ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS suppliers_staff_read ON public.suppliers;
DROP POLICY IF EXISTS suppliers_managers_add ON public.suppliers;
DROP POLICY IF EXISTS suppliers_managers_change ON public.suppliers;
DROP POLICY IF EXISTS suppliers_managers_remove ON public.suppliers;
CREATE POLICY suppliers_staff_read ON public.suppliers
  FOR SELECT TO authenticated USING (public.is_staff());
CREATE POLICY suppliers_managers_add ON public.suppliers
  FOR INSERT TO authenticated WITH CHECK (public.is_manager());
CREATE POLICY suppliers_managers_change ON public.suppliers
  FOR UPDATE TO authenticated
  USING (public.is_manager()) WITH CHECK (public.is_manager());
CREATE POLICY suppliers_managers_remove ON public.suppliers
  FOR DELETE TO authenticated USING (public.is_manager());


-- ── Xero's items ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.xero_items (
  code                 text PRIMARY KEY,
  xero_item_id         text,
  name                 text NOT NULL DEFAULT '',
  description          text NOT NULL DEFAULT '',
  purchase_description text NOT NULL DEFAULT '',
  purchase_price       numeric(12, 4),
  sales_price          numeric(12, 4),
  tracked              boolean NOT NULL DEFAULT false,
  supplier_id          uuid REFERENCES public.suppliers(id) ON DELETE SET NULL,
  stock_item_id        uuid,
  updated_at           timestamptz NOT NULL DEFAULT now()
);

DO $$
BEGIN
  IF to_regclass('public.stock_items') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_constraint WHERE conname = 'xero_items_stock_item_fk') THEN
    ALTER TABLE public.xero_items ADD CONSTRAINT xero_items_stock_item_fk
      FOREIGN KEY (stock_item_id) REFERENCES public.stock_items(id) ON DELETE SET NULL;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS xero_items_supplier ON public.xero_items (supplier_id);

ALTER TABLE public.xero_items ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS xero_items_staff_read ON public.xero_items;
DROP POLICY IF EXISTS xero_items_managers_link ON public.xero_items;
CREATE POLICY xero_items_staff_read ON public.xero_items
  FOR SELECT TO authenticated USING (public.is_staff());
-- Which supplier and which stock item an item is: a manager's say. Pulling
-- from Xero is the xero function's, as the service role.
CREATE POLICY xero_items_managers_link ON public.xero_items
  FOR UPDATE TO authenticated
  USING (public.is_manager()) WITH CHECK (public.is_manager());
REVOKE INSERT, DELETE ON public.xero_items FROM authenticated, anon;


-- ── Requests, several at once, with a supplier ──────────────────────────────

ALTER TABLE public.supply_requests
  ADD COLUMN IF NOT EXISTS supplier_id uuid REFERENCES public.suppliers(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS item_code text,
  ADD COLUMN IF NOT EXISTS stock_item_id uuid,
  ADD COLUMN IF NOT EXISTS batch_id uuid,
  ADD COLUMN IF NOT EXISTS purchase_order_id uuid
      REFERENCES public.purchase_orders(id) ON DELETE SET NULL;

-- Which stock item was asked for, when it was one (linked once stock_items
-- is there, as for xero_items above).
DO $$
BEGIN
  IF to_regclass('public.stock_items') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_constraint WHERE conname = 'supply_requests_stock_item_fk') THEN
    ALTER TABLE public.supply_requests ADD CONSTRAINT supply_requests_stock_item_fk
      FOREIGN KEY (stock_item_id) REFERENCES public.stock_items(id) ON DELETE SET NULL;
  END IF;
END $$;

-- One request for several things tells each manager once. The per-row
-- notification stands aside while request_supplies files a batch, and the
-- batch sends its own.
CREATE OR REPLACE FUNCTION public.notify_managers_of_supply_request()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF current_setting('taf.supply_batch', true) = 'on' THEN
        RETURN NEW;
    END IF;
    INSERT INTO public.notifications (recipient, kind, ref_id, title, body)
    SELECT p.id,
           'supply_request',
           NEW.id,
           CASE WHEN NEW.urgent THEN 'URGENT: ' ELSE '' END
               || NEW.item
               || CASE WHEN length(trim(NEW.detail)) > 0
                       THEN ' - ' || trim(NEW.detail) ELSE '' END,
           NEW.requested_by_name || ' asked for '
               || coalesce(nullif(trim(NEW.quantity), ''), 'some')
               || CASE WHEN length(trim(NEW.note)) > 0
                       THEN '. ' || trim(NEW.note) ELSE '' END
      FROM public.profiles p
     WHERE p.approved = true
       AND p.role IN ('Director', 'Admin', 'Manager')
       AND p.id IS DISTINCT FROM NEW.requested_by;
    RETURN NEW;
END;
$$;

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


-- ── Purchase orders, sent through Xero and received ─────────────────────────

ALTER TABLE public.purchase_orders
  ADD COLUMN IF NOT EXISTS supplier_id uuid REFERENCES public.suppliers(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS xero_po_id text,
  ADD COLUMN IF NOT EXISTS po_number text,
  ADD COLUMN IF NOT EXISTS emailed_at timestamptz,
  ADD COLUMN IF NOT EXISTS emailed_to text,
  ADD COLUMN IF NOT EXISTS error text;

-- What arrived: [{"line": 0, "qty": 6}, ...]. Each line keeps how many have
-- come ("received"); a line linked to a stock item puts them in stock with a
-- receive movement. All in: the order is received, and the requests on it
-- with it. Some in: part received.
CREATE OR REPLACE FUNCTION public.receive_purchase(p_po uuid, p_received jsonb)
RETURNS public.purchase_orders
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_po     public.purchase_orders;
    v_lines  jsonb;
    v_got    jsonb;
    v_idx    int;
    v_qty    numeric;
    v_line   jsonb;
    v_stock  uuid;
    v_after  numeric;
    v_who    text;
    v_all    boolean := true;
    v_any    boolean := false;
BEGIN
    IF NOT public.is_manager() THEN
        RAISE EXCEPTION 'Only a manager can receive a purchase order.';
    END IF;
    SELECT * INTO v_po FROM public.purchase_orders WHERE id = p_po FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'That purchase order is not there any more.';
    END IF;
    IF v_po.status IN ('received', 'cancelled') THEN
        RAISE EXCEPTION 'That purchase order is already %.', v_po.status;
    END IF;
    SELECT coalesce(nullif(trim(full_name), ''), nullif(trim(username), ''),
                    'Somebody') INTO v_who
      FROM public.profiles WHERE id = auth.uid();

    v_lines := coalesce(v_po.lines, '[]'::jsonb);
    FOR v_got IN SELECT * FROM jsonb_array_elements(coalesce(p_received, '[]'::jsonb)) LOOP
        v_idx := (v_got ->> 'line')::int;
        v_qty := (v_got ->> 'qty')::numeric;
        IF v_idx IS NULL OR v_idx < 0 OR v_idx >= jsonb_array_length(v_lines) THEN
            RAISE EXCEPTION 'There is no line % on that order.', coalesce(v_idx::text, '?');
        END IF;
        IF v_qty IS NULL OR v_qty <= 0 THEN
            CONTINUE;
        END IF;
        v_line := v_lines -> v_idx;
        v_lines := jsonb_set(v_lines, ARRAY[v_idx::text, 'received'],
                             to_jsonb(coalesce((v_line ->> 'received')::numeric, 0) + v_qty));
        v_any := true;
        v_stock := nullif(coalesce(v_line ->> 'stock_item_id', v_line ->> 'item_id', ''), '')::uuid;
        IF v_stock IS NOT NULL AND to_regclass('public.stock_items') IS NOT NULL THEN
            UPDATE public.stock_items
               SET stock_on_hand = coalesce(stock_on_hand, 0) + v_qty,
                   updated_at = now()
             WHERE id = v_stock
            RETURNING stock_on_hand INTO v_after;
            IF FOUND THEN
                INSERT INTO public.stock_transactions
                       (stock_item_id, transaction_type, quantity_change,
                        quantity_after, notes, username)
                VALUES (v_stock, 'receive', v_qty, v_after,
                        'PO ' || coalesce(nullif(v_po.po_number, ''), v_po.reference, '')
                          || ' from ' || v_po.supplier,
                        coalesce(v_who, ''));
            END IF;
        END IF;
    END LOOP;
    IF NOT v_any THEN
        RAISE EXCEPTION 'Nothing was entered as received.';
    END IF;

    SELECT bool_and(coalesce((l ->> 'received')::numeric, 0)
                    >= coalesce((l ->> 'quantity')::numeric, 0))
      INTO v_all FROM jsonb_array_elements(v_lines) l;

    UPDATE public.purchase_orders
       SET lines = v_lines,
           status = CASE WHEN v_all THEN 'received' ELSE 'part_received' END,
           received_at = CASE WHEN v_all THEN now() ELSE received_at END
     WHERE id = p_po
    RETURNING * INTO v_po;

    IF v_all THEN
        UPDATE public.supply_requests SET status = 'received'
         WHERE purchase_order_id = p_po AND status IN ('open', 'ordered');
    END IF;
    RETURN v_po;
END;
$$;

REVOKE ALL ON FUNCTION public.receive_purchase(uuid, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.receive_purchase(uuid, jsonb) TO authenticated;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    GRANT ALL ON public.suppliers, public.xero_items TO service_role;
  END IF;
END $$;
