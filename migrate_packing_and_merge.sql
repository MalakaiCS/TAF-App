-- ============================================================
-- TAF Order App - Weights, packing, delivery labels and merging customers
-- Run this in Supabase Dashboard -> SQL Editor. Safe to re-run.
-- Needs migrate_staff_access.sql first (is_staff / is_manager).
--
-- Three things live here:
--
--  1. calc_settings: the numbers the weight calculator, the packing planner
--     and the delivery labels share - material rates, cut profiles, the
--     company's base address. One row per section, a version that goes up
--     on every change, and the old value kept in calc_settings_history, so
--     a weight worked out last month can be worked out again exactly.
--
--  2. Packing plans are NOT here. They are saved on each order line inside
--     orders.items, through the same save as the rest of the order, so they
--     are covered by the order's own permissions and arrive wherever the
--     order does - including the phone, offline.
--
--  3. merge_customers(): two or more accounts for the same company folded
--     into one, in a single transaction. Orders, quotes, sites, returns,
--     recurring jobs and agreed prices move to the account that stays; the
--     others are archived, never deleted; every moved row's old value is
--     written down so undo_customer_merge() can put it back.
-- ============================================================

DO $$
BEGIN
  IF to_regprocedure('public.is_staff()') IS NULL
     OR to_regprocedure('public.is_manager()') IS NULL THEN
    RAISE EXCEPTION 'Run migrate_staff_access.sql first - this needs '
                    'is_staff() and is_manager().';
  END IF;
END $$;


-- ── 1. Calculator settings ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.calc_settings (
    key        text PRIMARY KEY CHECK (key IN (
                   'materials', 'steel', 'cut_profiles', 'component_profiles',
                   'brace_profiles', 'mounting_frame_profiles', 'wire_rules',
                   'required_components', 'packaging', 'handling_profiles',
                   'max_bundle_kg', 'shipping_rounding', 'company',
                   'c_channel', 'delivery_labels')),
    value      jsonb       NOT NULL,
    version    integer     NOT NULL DEFAULT 1,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text        NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS public.calc_settings_history (
    id         bigserial PRIMARY KEY,
    key        text        NOT NULL,
    version    integer     NOT NULL,
    value      jsonb       NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT now(),
    changed_by text        NOT NULL DEFAULT '',
    UNIQUE (key, version)
);

ALTER TABLE public.calc_settings         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.calc_settings_history ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Staff read calc settings"     ON public.calc_settings;
DROP POLICY IF EXISTS "Managers add calc settings"   ON public.calc_settings;
DROP POLICY IF EXISTS "Managers change calc settings" ON public.calc_settings;
DROP POLICY IF EXISTS "Staff read calc history"      ON public.calc_settings_history;

CREATE POLICY "Staff read calc settings" ON public.calc_settings
    FOR SELECT TO authenticated USING (public.is_staff());
CREATE POLICY "Managers add calc settings" ON public.calc_settings
    FOR INSERT TO authenticated WITH CHECK (public.is_manager());
CREATE POLICY "Managers change calc settings" ON public.calc_settings
    FOR UPDATE TO authenticated
    USING (public.is_manager()) WITH CHECK (public.is_manager());
CREATE POLICY "Staff read calc history" ON public.calc_settings_history
    FOR SELECT TO authenticated USING (public.is_staff());
-- Nobody writes history directly and nobody deletes either table's rows:
-- the trigger below is the only way in.
REVOKE INSERT, UPDATE, DELETE ON public.calc_settings_history
    FROM anon, authenticated;
REVOKE DELETE ON public.calc_settings FROM anon, authenticated;

-- Every version is kept, stamped with who made it. SECURITY DEFINER so the
-- history can be written while the app cannot write it itself.
CREATE OR REPLACE FUNCTION public.keep_calc_setting_history()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  who text := COALESCE((SELECT COALESCE(NULLIF(full_name, ''), username)
                          FROM public.profiles WHERE id = auth.uid()), '');
BEGIN
  IF TG_OP = 'UPDATE' THEN
    -- The version always moves on, whatever the app sent.
    NEW.version    := OLD.version + 1;
  END IF;
  NEW.updated_at := now();
  NEW.updated_by := who;
  INSERT INTO public.calc_settings_history (key, version, value, changed_by)
  VALUES (NEW.key, NEW.version, NEW.value, who)
  ON CONFLICT (key, version) DO NOTHING;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS calc_settings_history ON public.calc_settings;
CREATE TRIGGER calc_settings_history
    BEFORE INSERT OR UPDATE ON public.calc_settings
    FOR EACH ROW EXECUTE FUNCTION public.keep_calc_setting_history();

REVOKE ALL ON FUNCTION public.keep_calc_setting_history() FROM public;

-- Save a section. SECURITY INVOKER: the policies above decide who may.
CREATE OR REPLACE FUNCTION public.set_calc_setting(p_key text, p_value jsonb)
RETURNS integer
LANGUAGE sql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
  INSERT INTO public.calc_settings (key, value)
  VALUES (btrim(p_key), p_value)
  ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
  RETURNING version;
$$;

REVOKE ALL ON FUNCTION public.set_calc_setting(text, jsonb) FROM public;
GRANT EXECUTE ON FUNCTION public.set_calc_setting(text, jsonb) TO authenticated;

-- What has been supplied, and nothing more. Everything not seeded here is
-- unknown until somebody enters it, and the calculator says so. Never
-- overwrites what has already been changed.
INSERT INTO public.calc_settings (key, value) VALUES
('company', '{"base_address": "Unit 1/19 Tradelink Road, Hillcrest Queensland 4118 Australia"}'),
('materials', '{
  "version": "TAF-MATERIALS-2026-10",
  "wire": {
    "LARGE_WIRE": {"mesh_opening_mm": [25, 25], "wire_diameter_mm": 1.24,
                   "roll_width_mm": 1200, "roll_length_mm": 30000,
                   "roll_weight_kg": 24.87, "basis": "supplied_roll_mass"},
    "SMALL_WIRE": {"mesh_opening_mm": [12, 12], "wire_diameter_mm": 0.80,
                   "roll_width_mm": 1200, "roll_length_mm": 30000,
                   "roll_weight_kg": 19.30, "basis": "supplied_roll_mass"}
  },
  "media": {
    "WASHABLE": {"stock_weight_kg": 10.08, "stock_area_m2": 42, "basis": "supplied_stock_mass"},
    "F5":       {"stock_weight_kg": 14.70, "stock_area_m2": 42, "basis": "supplied_stock_mass"},
    "G4":       {"stock_weight_kg": 12.60, "stock_area_m2": 42, "basis": "supplied_stock_mass"},
    "180":      {"stock_weight_kg": 15.12, "stock_area_m2": 84, "basis": "supplied_stock_mass"},
    "GREY":     {"stock_weight_kg": 12.60, "stock_area_m2": 84, "basis": "supplied_stock_mass"},
    "BLACK":    {"stock_weight_kg": null, "stock_area_m2": 63,
                 "basis": "derived_from_GREY", "derived_from": "GREY"}
  }
}'),
('handling_profiles', '[{"id": "HANDLING-412x412x90", "version": 1, "verified": true,
   "match": {"width_mm": 412, "height_mm": 412, "depth_mm": 90},
   "max_per_wrap": 5,
   "source": "supplied: 412 x 412 x 90 filters are wrapped five at most"}]'),
('max_bundle_kg', '10.0')
ON CONFLICT (key) DO NOTHING;


-- ── 2. Customers: links, archive, aliases ───────────────────────────────────

ALTER TABLE public.customers
    ADD COLUMN IF NOT EXISTS merged_into uuid REFERENCES public.customers(id),
    ADD COLUMN IF NOT EXISTS merged_at   timestamptz;

-- An order has always been linked to its customer by name. The id is added
-- alongside, so a merge can say exactly which account an order belongs to
-- without rewriting what was printed on it (orders.header is never touched).
ALTER TABLE public.orders
    ADD COLUMN IF NOT EXISTS customer_id uuid
        REFERENCES public.customers(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS orders_customer_id ON public.orders (customer_id);

CREATE TABLE IF NOT EXISTS public.customer_merges (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id     text        NOT NULL UNIQUE,
    survivor_id    uuid        NOT NULL REFERENCES public.customers(id),
    merged_ids     uuid[]      NOT NULL,
    decisions      jsonb       NOT NULL DEFAULT '{}'::jsonb,
    before         jsonb       NOT NULL DEFAULT '[]'::jsonb,
    moved          jsonb       NOT NULL DEFAULT '[]'::jsonb,
    unresolved     jsonb       NOT NULL DEFAULT '[]'::jsonb,
    merged_by      uuid,
    merged_by_name text        NOT NULL DEFAULT '',
    merged_at      timestamptz NOT NULL DEFAULT now(),
    undone_at      timestamptz,
    undone_by_name text        NOT NULL DEFAULT ''
);

-- A former account, pointing at the one it became. Searches and old links
-- find the survivor through these.
CREATE TABLE IF NOT EXISTS public.customer_aliases (
    former_id         uuid PRIMARY KEY,
    survivor_id       uuid NOT NULL REFERENCES public.customers(id),
    former_name       text NOT NULL DEFAULT '',
    former_short_name text NOT NULL DEFAULT '',
    former_legal_name text NOT NULL DEFAULT '',
    merge_id          uuid REFERENCES public.customer_merges(id) ON DELETE CASCADE,
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS customer_aliases_names
    ON public.customer_aliases (lower(btrim(former_name)));

ALTER TABLE public.customer_merges  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.customer_aliases ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Staff read merges"  ON public.customer_merges;
DROP POLICY IF EXISTS "Staff read aliases" ON public.customer_aliases;
CREATE POLICY "Staff read merges"  ON public.customer_merges
    FOR SELECT TO authenticated USING (public.is_staff());
CREATE POLICY "Staff read aliases" ON public.customer_aliases
    FOR SELECT TO authenticated USING (public.is_staff());
-- Only the functions below write these.
REVOKE INSERT, UPDATE, DELETE ON public.customer_merges  FROM anon, authenticated;
REVOKE INSERT, UPDATE, DELETE ON public.customer_aliases FROM anon, authenticated;


-- The account an id now means: itself, or wherever it was merged into.
CREATE OR REPLACE FUNCTION public.resolve_customer(p_id uuid)
RETURNS uuid
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
  cur  uuid := p_id;
  nxt  uuid;
  hops int := 0;
BEGIN
  LOOP
    SELECT merged_into INTO nxt FROM public.customers WHERE id = cur;
    EXIT WHEN nxt IS NULL OR hops > 20;
    cur := nxt;
    hops := hops + 1;
  END LOOP;
  RETURN cur;
END;
$$;

REVOKE ALL ON FUNCTION public.resolve_customer(uuid) FROM public;
GRANT EXECUTE ON FUNCTION public.resolve_customer(uuid) TO authenticated;


-- The names an account's records can safely be matched on: its trading
-- name and its short name - never its legal name, which every branch of a
-- company shares - and only names no account outside `p_set` also uses,
-- because a name two live accounts share does not say whose a record is.
CREATE OR REPLACE FUNCTION public.customer_link_names(p_id uuid, p_set uuid[])
RETURNS text[]
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT COALESCE(array_agg(DISTINCT n), '{}')
    FROM (
      SELECT lower(btrim(x)) AS n
        FROM public.customers c,
             LATERAL unnest(ARRAY[c.name, c.short_name]) AS x
       WHERE c.id = p_id AND btrim(COALESCE(x, '')) <> ''
    ) names
   WHERE NOT EXISTS (
     SELECT 1 FROM public.customers o
      WHERE o.id <> ALL (p_set)
        AND o.merged_into IS NULL
        AND (lower(btrim(o.name)) = names.n
             OR lower(btrim(COALESCE(o.short_name, ''))) = names.n));
$$;

REVOKE ALL ON FUNCTION public.customer_link_names(uuid, uuid[]) FROM public;
GRANT EXECUTE ON FUNCTION public.customer_link_names(uuid, uuid[]) TO authenticated;


-- What a merge would move, per account, without moving anything.
CREATE OR REPLACE FUNCTION public.customer_merge_preview(p_ids uuid[])
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  out   jsonb := '[]'::jsonb;
  cid   uuid;
  names text[];
  row_  jsonb;
  n     bigint;
  t     text;
BEGIN
  IF NOT public.is_staff() THEN
    RAISE EXCEPTION 'Sign in as staff to look at customer accounts.';
  END IF;
  FOREACH cid IN ARRAY p_ids LOOP
    names := public.customer_link_names(cid, p_ids);
    row_ := jsonb_build_object(
      'id', cid,
      'link_names', to_jsonb(names),
      'orders', (SELECT count(*) FROM public.orders o
                  WHERE o.customer_id = cid
                     OR (o.customer_id IS NULL
                         AND lower(btrim(o.customer_name)) = ANY (names))),
      'quotes', (SELECT count(*) FROM public.quotes q
                  WHERE q.customer_id = cid
                     OR (q.customer_id IS NULL
                         AND lower(btrim(q.customer_name)) = ANY (names))),
      'quote_total', (SELECT COALESCE(sum(q.total), 0) FROM public.quotes q
                  WHERE q.customer_id = cid
                     OR (q.customer_id IS NULL
                         AND lower(btrim(q.customer_name)) = ANY (names))),
      'customer_prices', (SELECT count(*) FROM public.customer_prices p
                           WHERE p.customer_id = cid));
    FOR t IN SELECT unnest(ARRAY['sites', 'returns', 'recurring_jobs']) LOOP
      IF to_regclass('public.' || t) IS NOT NULL THEN
        EXECUTE format('SELECT count(*) FROM public.%I '
                       'WHERE lower(btrim(customer_name)) = ANY ($1)', t)
          INTO n USING names;
        row_ := row_ || jsonb_build_object(t, n);
      END IF;
    END LOOP;
    out := out || jsonb_build_array(row_);
  END LOOP;
  RETURN out;
END;
$$;

REVOKE ALL ON FUNCTION public.customer_merge_preview(uuid[]) FROM public;
GRANT EXECUTE ON FUNCTION public.customer_merge_preview(uuid[]) TO authenticated;


-- ── 3. The merge ────────────────────────────────────────────────────────────
-- p_decisions:
--   {"set": {"name": "...", "payment_terms": "...", ...}   fields for the
--                                                          account that stays
--    "prices": {"<PART>": "survivor" | "<duplicate id>"},  which agreed price
--                                                          wins when both have
--                                                          one ("" = discount)
--    "confirm_different_abn": true}                        only when the ABNs
--                                                          differ and that is
--                                                          known and accepted
-- p_expected: {"<id>": "<updated_at as previewed>"} - the merge is refused
--   if any account changed after the preview it was decided on.
--
-- SECURITY DEFINER because one merge touches several people's orders and
-- tables with different policies; the manager check below is the gate, and
-- search_path is pinned so nothing can be shadowed.

CREATE OR REPLACE FUNCTION public.merge_customers(
    p_request_id text, p_survivor uuid, p_merged uuid[],
    p_decisions jsonb DEFAULT '{}'::jsonb, p_expected jsonb DEFAULT NULL)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  existing  public.customer_merges%ROWTYPE;
  all_ids   uuid[];
  n_found   int;
  v_before  jsonb;
  v_moved   jsonb := '[]'::jsonb;
  v_set     jsonb := COALESCE(p_decisions -> 'set', '{}'::jsonb);
  v_prices  jsonb := COALESCE(p_decisions -> 'prices', '{}'::jsonb);
  v_cols    text;
  v_link    text;
  v_names   text[] := '{}';
  v_surv_names text[];
  v_merge   uuid := gen_random_uuid();
  v_who     text;
  r         record;
  allowed   text[] := ARRAY[
    'name', 'legal_name', 'short_name', 'abn', 'website', 'contact_person',
    'contact_role', 'phone', 'email', 'delivery_address1',
    'delivery_address2', 'delivery_city', 'delivery_state',
    'delivery_postcode', 'delivery_country', 'billing_same',
    'billing_address1', 'billing_address2', 'billing_city', 'billing_state',
    'billing_postcode', 'billing_country', 'payment_terms', 'currency',
    'notes', 'region', 'job_number_label', 'frame_preference'];
  v_conflicts text[];
  v_unresolved jsonb := '[]'::jsonb;
BEGIN
  IF NOT public.is_manager() THEN
    RAISE EXCEPTION 'Only a manager can merge customer accounts.';
  END IF;
  IF btrim(COALESCE(p_request_id, '')) = '' THEN
    RAISE EXCEPTION 'A merge needs a request id, so a retry is not a second merge.';
  END IF;

  -- A retry of a merge that already happened is answered with that merge.
  SELECT * INTO existing FROM public.customer_merges
   WHERE request_id = p_request_id;
  IF FOUND THEN
    IF existing.survivor_id = p_survivor
       AND (SELECT array_agg(x ORDER BY x) FROM unnest(existing.merged_ids) x)
         = (SELECT array_agg(DISTINCT x ORDER BY x) FROM unnest(p_merged) x) THEN
      RETURN existing.id;
    END IF;
    RAISE EXCEPTION 'That request id was already used for a different merge.';
  END IF;

  IF p_survivor IS NULL OR p_merged IS NULL OR cardinality(p_merged) = 0 THEN
    RAISE EXCEPTION 'Choose the account that stays and at least one to merge into it.';
  END IF;
  IF p_survivor = ANY (p_merged) THEN
    RAISE EXCEPTION 'An account cannot be merged into itself.';
  END IF;
  IF (SELECT count(DISTINCT x) FROM unnest(p_merged) x) <> cardinality(p_merged) THEN
    RAISE EXCEPTION 'The same account is listed twice.';
  END IF;
  all_ids := p_merged || p_survivor;

  -- Lock every account involved, in a fixed order so two merges at once
  -- cannot deadlock, and check they are all still live.
  PERFORM 1 FROM public.customers WHERE id = ANY (all_ids)
    ORDER BY id FOR UPDATE;
  SELECT count(*) INTO n_found FROM public.customers WHERE id = ANY (all_ids);
  IF n_found <> cardinality(all_ids) THEN
    RAISE EXCEPTION 'One of those accounts no longer exists.';
  END IF;
  IF EXISTS (SELECT 1 FROM public.customers
              WHERE id = ANY (all_ids) AND merged_into IS NOT NULL) THEN
    RAISE EXCEPTION 'One of those accounts has already been merged into another.';
  END IF;
  IF p_expected IS NOT NULL AND EXISTS (
       SELECT 1 FROM public.customers c
        WHERE c.id = ANY (all_ids)
          AND p_expected ? c.id::text
          AND (p_expected ->> c.id::text)::timestamptz
              IS DISTINCT FROM c.updated_at) THEN
    RAISE EXCEPTION 'One of those accounts was changed after the preview. '
                    'Look at it again before merging.';
  END IF;

  -- Conflicts that must be decided, not defaulted.
  IF btrim(COALESCE(v_set ->> 'name', '')) = '' THEN
    RAISE EXCEPTION 'Choose the company name the merged account keeps.';
  END IF;
  IF (SELECT count(DISTINCT upper(regexp_replace(abn, '\s', '', 'g')))
        FROM public.customers
       WHERE id = ANY (all_ids) AND btrim(COALESCE(abn, '')) <> '') > 1
     AND NOT (COALESCE((p_decisions ->> 'confirm_different_abn')::boolean, false)
              AND v_set ? 'abn') THEN
    RAISE EXCEPTION 'These accounts have different ABNs - they may be '
                    'different companies. Confirm it and choose the ABN to keep.';
  END IF;
  IF (SELECT count(DISTINCT btrim(payment_terms)) FROM public.customers
       WHERE id = ANY (all_ids) AND btrim(COALESCE(payment_terms, '')) <> '') > 1
     AND NOT v_set ? 'payment_terms' THEN
    RAISE EXCEPTION 'The accounts have different payment terms. Choose the one to keep.';
  END IF;
  SELECT array_agg(DISTINCT upper(btrim(d.part_number)))
    INTO v_conflicts
    FROM public.customer_prices d
    JOIN public.customer_prices s
      ON s.customer_id = p_survivor
     AND upper(btrim(s.part_number)) = upper(btrim(d.part_number))
   WHERE d.customer_id = ANY (p_merged)
     AND NOT v_prices ? upper(btrim(d.part_number));
  IF v_conflicts IS NOT NULL THEN
    RAISE EXCEPTION 'Both accounts have an agreed price for: %. Choose which one stays.',
      array_to_string(v_conflicts, ', ');
  END IF;
  -- Two duplicates with a price for the same part, and the survivor without
  -- one, is a conflict too.
  SELECT array_agg(part) INTO v_conflicts FROM (
    SELECT upper(btrim(part_number)) AS part FROM public.customer_prices
     WHERE customer_id = ANY (p_merged)
     GROUP BY 1 HAVING count(*) > 1) t
   WHERE NOT v_prices ? part;
  IF v_conflicts IS NOT NULL THEN
    RAISE EXCEPTION 'More than one merged account has an agreed price for: %. Choose which one stays.',
      array_to_string(v_conflicts, ', ');
  END IF;

  v_who := COALESCE((SELECT COALESCE(NULLIF(full_name, ''), username)
                       FROM public.profiles WHERE id = auth.uid()), '');

  -- Everything as it was, for undo.
  SELECT jsonb_agg(to_jsonb(c) ORDER BY c.id) INTO v_before
    FROM public.customers c WHERE c.id = ANY (all_ids);

  -- The names records can be matched on, worked out before anything moves.
  SELECT COALESCE(array_agg(DISTINCT n), '{}') INTO v_names
    FROM unnest(p_merged) AS m(id),
         LATERAL unnest(public.customer_link_names(m.id, all_ids)) AS n;
  v_surv_names := public.customer_link_names(p_survivor, all_ids);

  -- The account that stays takes the chosen details.
  SELECT string_agg(format('%I = r.%I', k, k), ', ')
    INTO v_cols
    FROM jsonb_object_keys(v_set) AS k
   WHERE k = ANY (allowed)
     AND EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE table_schema = 'public' AND table_name = 'customers'
                    AND column_name = k);
  IF v_cols IS NOT NULL THEN
    EXECUTE format('UPDATE public.customers c SET %s, updated_at = now() '
                   'FROM jsonb_populate_record(NULL::public.customers, $1) r '
                   'WHERE c.id = $2', v_cols)
      USING v_set, p_survivor;
  END IF;
  -- Purchase-order wording learned on any of them keeps matching, and so
  -- do the old names.
  UPDATE public.customers c
     SET po_aliases = (
       SELECT COALESCE(jsonb_agg(DISTINCT a), '[]'::jsonb) FROM (
         SELECT jsonb_array_elements_text(COALESCE(x.po_aliases, '[]'::jsonb)) AS a
           FROM public.customers x WHERE x.id = ANY (all_ids)
         UNION
         SELECT btrim(x.name) FROM public.customers x
          WHERE x.id = ANY (p_merged) AND btrim(COALESCE(x.name, '')) <> ''
         UNION
         SELECT btrim(x.short_name) FROM public.customers x
          WHERE x.id = ANY (p_merged) AND btrim(COALESCE(x.short_name, '')) <> ''
       ) t WHERE a IS NOT NULL AND btrim(a) <> '')
   WHERE c.id = p_survivor;

  SELECT COALESCE(NULLIF(btrim(short_name), ''), name) INTO v_link
    FROM public.customers WHERE id = p_survivor;

  -- Orders: the id and the live name move; the header - what was printed -
  -- does not.
  WITH moved AS (
    UPDATE public.orders o
       SET customer_id = p_survivor, customer_name = v_link
      FROM (SELECT id, customer_id, customer_name FROM public.orders
             WHERE customer_id = ANY (p_merged)
                OR (customer_id IS NULL
                    AND lower(btrim(customer_name)) = ANY (v_names))
             FOR UPDATE) old
     WHERE o.id = old.id
    RETURNING o.id, old.customer_id AS old_id, old.customer_name AS old_name)
  SELECT v_moved || COALESCE(jsonb_agg(jsonb_build_object(
           't', 'orders', 'id', id,
           'old', jsonb_build_object('customer_id', old_id, 'customer_name', old_name),
           'new', jsonb_build_object('customer_id', p_survivor, 'customer_name', v_link))),
           '[]'::jsonb)
    INTO v_moved FROM moved;

  -- The survivor's own orders, linked by id too while we are here.
  WITH linked AS (
    UPDATE public.orders o SET customer_id = p_survivor
     WHERE o.customer_id IS NULL
       AND lower(btrim(o.customer_name)) = ANY (v_surv_names)
    RETURNING o.id, o.customer_name)
  SELECT v_moved || COALESCE(jsonb_agg(jsonb_build_object(
           't', 'orders', 'id', id,
           'old', jsonb_build_object('customer_id', NULL, 'customer_name', customer_name),
           'new', jsonb_build_object('customer_id', p_survivor, 'customer_name', customer_name))),
           '[]'::jsonb)
    INTO v_moved FROM linked;

  -- Quotes: the account and name move; numbers, totals and status do not.
  WITH moved AS (
    UPDATE public.quotes q
       SET customer_id = p_survivor, customer_name = v_link
      FROM (SELECT id, customer_id, customer_name FROM public.quotes
             WHERE customer_id = ANY (p_merged)
                OR (customer_id IS NULL
                    AND lower(btrim(customer_name)) = ANY (v_names))
             FOR UPDATE) old
     WHERE q.id = old.id
    RETURNING q.id, old.customer_id AS old_id, old.customer_name AS old_name)
  SELECT v_moved || COALESCE(jsonb_agg(jsonb_build_object(
           't', 'quotes', 'id', id,
           'old', jsonb_build_object('customer_id', old_id, 'customer_name', old_name),
           'new', jsonb_build_object('customer_id', p_survivor, 'customer_name', v_link))),
           '[]'::jsonb)
    INTO v_moved FROM moved;

  WITH linked AS (
    UPDATE public.quotes q SET customer_id = p_survivor
     WHERE q.customer_id IS NULL
       AND lower(btrim(q.customer_name)) = ANY (v_surv_names)
    RETURNING q.id, q.customer_name)
  SELECT v_moved || COALESCE(jsonb_agg(jsonb_build_object(
           't', 'quotes', 'id', id,
           'old', jsonb_build_object('customer_id', NULL, 'customer_name', customer_name),
           'new', jsonb_build_object('customer_id', p_survivor, 'customer_name', customer_name))),
           '[]'::jsonb)
    INTO v_moved FROM linked;

  -- Tables that only know the customer by name, where they exist.
  FOR r IN SELECT unnest(ARRAY['sites', 'returns', 'recurring_jobs']) AS t LOOP
    IF to_regclass('public.' || r.t) IS NULL THEN CONTINUE; END IF;
    EXECUTE format(
      'WITH moved AS (UPDATE public.%1$I x SET customer_name = $1 '
      '  FROM (SELECT id, customer_name FROM public.%1$I '
      '         WHERE lower(btrim(customer_name)) = ANY ($2) FOR UPDATE) old '
      ' WHERE x.id = old.id RETURNING x.id, old.customer_name AS old_name) '
      'SELECT $3 || COALESCE(jsonb_agg(jsonb_build_object(''t'', %1$L, '
      '  ''id'', id, ''old'', jsonb_build_object(''customer_name'', old_name), '
      '  ''new'', jsonb_build_object(''customer_name'', $1))), ''[]''::jsonb) '
      'FROM moved', r.t)
      INTO v_moved USING v_link, v_names, v_moved;
  END LOOP;

  -- A merged account's delivery address that differs from the one kept is
  -- a real place: it is kept as a site of the survivor, not dropped.
  IF to_regclass('public.sites') IS NOT NULL THEN
    WITH addr AS (
      SELECT c.id, c.name,
             concat_ws(', ', NULLIF(btrim(c.delivery_address1), ''),
                       NULLIF(btrim(c.delivery_address2), ''),
                       NULLIF(btrim(concat_ws(' ', NULLIF(btrim(c.delivery_city), ''),
                                                    NULLIF(btrim(c.delivery_state), ''),
                                                    NULLIF(btrim(c.delivery_postcode), ''))), ''))
               AS line
        FROM public.customers c WHERE c.id = ANY (p_merged)),
    kept AS (
      SELECT lower(concat_ws(', ', NULLIF(btrim(c.delivery_address1), ''),
                       NULLIF(btrim(c.delivery_address2), ''),
                       NULLIF(btrim(concat_ws(' ', NULLIF(btrim(c.delivery_city), ''),
                                                    NULLIF(btrim(c.delivery_state), ''),
                                                    NULLIF(btrim(c.delivery_postcode), ''))), '')))
               AS line
        FROM public.customers c WHERE c.id = p_survivor),
    made AS (
      INSERT INTO public.sites (customer_name, name, location, note, created_by)
      SELECT v_link, 'Delivery address from ' || a.name, a.line,
             'Kept when ' || a.name || ' was merged into this account.', v_who
        FROM addr a, kept k
       WHERE a.line <> '' AND lower(a.line) <> k.line
      RETURNING id)
    SELECT v_moved || COALESCE(jsonb_agg(jsonb_build_object(
             't', 'sites', 'id', id, 'created', true)), '[]'::jsonb)
      INTO v_moved FROM made;
  END IF;

  -- Agreed prices: the chosen one of each conflicting pair stays; the
  -- other is removed and kept in full in the merge record.
  FOR r IN
    SELECT p.*, upper(btrim(p.part_number)) AS part
      FROM public.customer_prices p
     WHERE p.customer_id = ANY (all_ids)
       AND v_prices ? upper(btrim(p.part_number))
  LOOP
    IF ((v_prices ->> r.part) = 'survivor' AND r.customer_id <> p_survivor)
       OR ((v_prices ->> r.part) <> 'survivor'
           AND r.customer_id::text <> (v_prices ->> r.part)) THEN
      DELETE FROM public.customer_prices WHERE id = r.id;
      v_moved := v_moved || jsonb_build_array(jsonb_build_object(
        't', 'customer_prices', 'id', r.id, 'deleted',
        to_jsonb(r) - 'part'));
    END IF;
  END LOOP;
  WITH moved AS (
    UPDATE public.customer_prices p SET customer_id = p_survivor
      FROM (SELECT id, customer_id FROM public.customer_prices
             WHERE customer_id = ANY (p_merged) FOR UPDATE) old
     WHERE p.id = old.id
    RETURNING p.id, old.customer_id AS old_id)
  SELECT v_moved || COALESCE(jsonb_agg(jsonb_build_object(
           't', 'customer_prices', 'id', id,
           'old', jsonb_build_object('customer_id', old_id),
           'new', jsonb_build_object('customer_id', p_survivor))), '[]'::jsonb)
    INTO v_moved FROM moved;

  -- The others are archived, pointing at the survivor. Never deleted: old
  -- links and searches still find their way through them.
  UPDATE public.customers
     SET is_active = false, merged_into = p_survivor, merged_at = now(),
         portal_enabled = false, updated_at = now()
   WHERE id = ANY (p_merged);

  INSERT INTO public.customer_merges
         (id, request_id, survivor_id, merged_ids, decisions, before, moved,
          unresolved, merged_by, merged_by_name)
  VALUES (v_merge, p_request_id, p_survivor, p_merged, p_decisions, v_before,
          v_moved, v_unresolved, auth.uid(), v_who);

  INSERT INTO public.customer_aliases
         (former_id, survivor_id, former_name, former_short_name,
          former_legal_name, merge_id)
  SELECT c.id, p_survivor, COALESCE(c.name, ''), COALESCE(c.short_name, ''),
         COALESCE(c.legal_name, ''), v_merge
    FROM jsonb_populate_recordset(NULL::public.customers, v_before) c
   WHERE c.id = ANY (p_merged);
  -- An earlier merge whose survivor has now been merged follows along.
  UPDATE public.customer_aliases SET survivor_id = p_survivor
   WHERE survivor_id = ANY (p_merged);

  RETURN v_merge;
END;
$$;

REVOKE ALL ON FUNCTION public.merge_customers(text, uuid, uuid[], jsonb, jsonb) FROM public;
GRANT EXECUTE ON FUNCTION public.merge_customers(text, uuid, uuid[], jsonb, jsonb) TO authenticated;


-- Put a merge back. Records changed since the merge are left as they are
-- now and listed, rather than overwritten.
CREATE OR REPLACE FUNCTION public.undo_customer_merge(p_merge_id uuid)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  m        public.customer_merges%ROWTYPE;
  v_cols   text;
  e        jsonb;
  skipped  jsonb := '[]'::jsonb;
  n        int;
BEGIN
  IF NOT public.is_manager() THEN
    RAISE EXCEPTION 'Only a manager can undo a customer merge.';
  END IF;
  SELECT * INTO m FROM public.customer_merges WHERE id = p_merge_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'There is no such merge.';
  END IF;
  IF m.undone_at IS NOT NULL THEN
    RETURN jsonb_build_object('already_undone', true, 'skipped', '[]'::jsonb);
  END IF;
  IF EXISTS (SELECT 1 FROM public.customers
              WHERE merged_into = m.survivor_id
                AND id <> ALL (m.merged_ids)) THEN
    RAISE EXCEPTION 'Another account has since been merged into this one. '
                    'Undo that merge first.';
  END IF;
  IF EXISTS (SELECT 1 FROM public.customers
              WHERE id = m.survivor_id AND merged_into IS NOT NULL) THEN
    RAISE EXCEPTION 'This account has since been merged into another. '
                    'Undo that merge first.';
  END IF;

  -- Records back where they were, if nobody has changed them since. In
  -- reverse: a price moved onto the survivor has to move off again before
  -- the survivor's own price can go back in its place.
  FOR e IN SELECT x.value FROM jsonb_array_elements(m.moved)
                               WITH ORDINALITY AS x(value, n)
            ORDER BY x.n DESC LOOP
    IF e ->> 't' IN ('orders', 'quotes') THEN
      EXECUTE format(
        'UPDATE public.%I SET customer_id = ($1 ->> ''customer_id'')::uuid, '
        '       customer_name = $1 ->> ''customer_name'' '
        ' WHERE id = ($2)::uuid '
        '   AND customer_id IS NOT DISTINCT FROM ($3 ->> ''customer_id'')::uuid '
        '   AND customer_name IS NOT DISTINCT FROM $3 ->> ''customer_name''',
        e ->> 't')
        USING e -> 'old', e ->> 'id', e -> 'new';
      GET DIAGNOSTICS n = ROW_COUNT;
    ELSIF e ->> 't' IN ('sites', 'returns', 'recurring_jobs')
          AND NOT COALESCE((e ->> 'created')::boolean, false) THEN
      EXECUTE format(
        'UPDATE public.%I SET customer_name = $1 ->> ''customer_name'' '
        ' WHERE id = ($2)::uuid AND customer_name = $3 ->> ''customer_name''',
        e ->> 't')
        USING e -> 'old', e ->> 'id', e -> 'new';
      GET DIAGNOSTICS n = ROW_COUNT;
    ELSIF e ->> 't' = 'sites' THEN
      DELETE FROM public.sites WHERE id = (e ->> 'id')::uuid;
      n := 1;
    ELSIF e ->> 't' = 'customer_prices' AND e ? 'old' THEN
      UPDATE public.customer_prices
         SET customer_id = (e -> 'old' ->> 'customer_id')::uuid
       WHERE id = (e ->> 'id')::uuid
         AND customer_id = (e -> 'new' ->> 'customer_id')::uuid;
      GET DIAGNOSTICS n = ROW_COUNT;
    ELSIF e ->> 't' = 'customer_prices' AND e ? 'deleted' THEN
      INSERT INTO public.customer_prices
      SELECT * FROM jsonb_populate_record(NULL::public.customer_prices,
                                          e -> 'deleted')
      ON CONFLICT DO NOTHING;
      GET DIAGNOSTICS n = ROW_COUNT;
    ELSE
      n := 1;
    END IF;
    IF n = 0 THEN
      skipped := skipped || jsonb_build_array(e);
    END IF;
  END LOOP;

  -- Every account back as it was before the merge.
  SELECT string_agg(format('%I = r.%I', column_name, column_name), ', ')
    INTO v_cols
    FROM information_schema.columns
   WHERE table_schema = 'public' AND table_name = 'customers'
     AND column_name <> 'id';
  EXECUTE format('UPDATE public.customers c SET %s '
                 'FROM jsonb_populate_recordset(NULL::public.customers, $1) r '
                 'WHERE c.id = r.id', v_cols)
    USING m.before;

  DELETE FROM public.customer_aliases WHERE merge_id = m.id;
  UPDATE public.customer_merges
     SET undone_at = now(),
         undone_by_name = COALESCE((SELECT COALESCE(NULLIF(full_name, ''), username)
                                      FROM public.profiles WHERE id = auth.uid()), '')
   WHERE id = m.id;
  RETURN jsonb_build_object('already_undone', false, 'skipped', skipped);
END;
$$;

REVOKE ALL ON FUNCTION public.undo_customer_merge(uuid) FROM public;
GRANT EXECUTE ON FUNCTION public.undo_customer_merge(uuid) TO authenticated;
