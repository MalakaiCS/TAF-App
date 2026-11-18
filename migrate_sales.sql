-- ============================================================================
-- Step 46: winning the work, and keeping it
--
--   quotes.chased_at, chase_count   when a quote that has had no answer was
--                                   last chased, and how many times
--   quotes.lost_reason, lost_note   why a quote was lost (price, lead time,
--                                   went elsewhere...) - the pattern is the
--                                   point
--   customers.service_weeks         how often a customer's filters are
--                                   changed, so they can be reminded before
--                                   they ring - and snoozed for a while
--   price_changes                   a rise (or cut) of so many percent, to
--                                   a tier or a filter type, from a date -
--                                   previewed, then applied once
--
-- Behind switches that start off (Settings -> Features). Needs
-- migrate_quotes.sql, migrate_quote_portal.sql, migrate_pricing.sql and
-- migrate_price_tiers.sql. Safe to run more than once.
-- ============================================================================

DO $$
BEGIN
  IF to_regclass('public.quotes') IS NULL THEN
    RAISE EXCEPTION 'Run migrate_quotes.sql first.';
  END IF;
  IF to_regclass('public.price_rates') IS NULL THEN
    RAISE EXCEPTION 'Run migrate_pricing.sql first.';
  END IF;
END $$;


-- ── Chasing, and why a quote was lost ───────────────────────────────────────

ALTER TABLE public.quotes ADD COLUMN IF NOT EXISTS chased_at   timestamptz;
ALTER TABLE public.quotes ADD COLUMN IF NOT EXISTS chase_count integer NOT NULL DEFAULT 0;
ALTER TABLE public.quotes ADD COLUMN IF NOT EXISTS lost_reason text    NOT NULL DEFAULT '';
ALTER TABLE public.quotes ADD COLUMN IF NOT EXISTS lost_note   text    NOT NULL DEFAULT '';

-- Chased: one more, now. A function so two people chasing at once count
-- twice rather than one overwriting the other.
CREATE OR REPLACE FUNCTION public.quote_chased(p_id uuid)
RETURNS integer
LANGUAGE sql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
    UPDATE public.quotes
       SET chased_at = now(), chase_count = chase_count + 1, updated_at = now()
     WHERE id = p_id
    RETURNING chase_count;
$$;

REVOKE ALL ON FUNCTION public.quote_chased(uuid) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.quote_chased(uuid) TO authenticated;


-- ── When a customer's filters are due for a change ──────────────────────────

ALTER TABLE public.customers ADD COLUMN IF NOT EXISTS service_weeks integer;
ALTER TABLE public.customers ADD COLUMN IF NOT EXISTS service_snoozed_until date;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conname = 'customers_service_weeks_check') THEN
    ALTER TABLE public.customers ADD CONSTRAINT customers_service_weeks_check
        CHECK (service_weeks IS NULL OR (service_weeks BETWEEN 1 AND 104));
  END IF;
END $$;


-- ── Changing prices ─────────────────────────────────────────────────────────
-- A change is written down first and applied once: on the day it is from,
-- by a manager's PC (apply_due_price_changes), or straight away. Applying
-- it twice is impossible - the row says when it was.

CREATE TABLE IF NOT EXISTS public.price_changes (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- 'all', 'list' (part numbers) or 'rates' (per square metre)
    scope       text        NOT NULL DEFAULT 'all',
    -- Only part numbers or filter types containing this, when given.
    match_text  text        NOT NULL DEFAULT '',
    tiers       int[]       NOT NULL DEFAULT '{1,2,3}',
    percent     numeric     NOT NULL,
    starts_on   date        NOT NULL DEFAULT current_date,
    note        text        NOT NULL DEFAULT '',
    applied_at  timestamptz,
    applied_by  text        NOT NULL DEFAULT '',
    changed     integer     NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now(),
    created_by  text        NOT NULL DEFAULT '',
    CHECK (scope IN ('all', 'list', 'rates')),
    CHECK (percent > -90 AND percent < 500),
    CHECK (tiers <@ ARRAY[1, 2, 3] AND cardinality(tiers) > 0)
);

ALTER TABLE public.price_changes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Staff read price changes"     ON public.price_changes;
DROP POLICY IF EXISTS "Managers write price changes" ON public.price_changes;
CREATE POLICY "Staff read price changes" ON public.price_changes FOR SELECT
    TO authenticated USING (public.is_staff());
CREATE POLICY "Managers write price changes" ON public.price_changes FOR ALL
    TO authenticated USING (public.is_manager()) WITH CHECK (public.is_manager());

-- One change, applied. INVOKER, so the price tables' own rules decide - a
-- manager's prices change, nobody else's call changes anything.
CREATE OR REPLACE FUNCTION public.apply_price_change(p_id uuid)
RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    c       public.price_changes%ROWTYPE;
    f       numeric;
    n       integer := 0;
    k       integer;
    v_who   text;
BEGIN
    IF NOT public.is_manager() THEN
        RAISE EXCEPTION 'Only a manager can change prices.';
    END IF;
    SELECT * INTO c FROM public.price_changes WHERE id = p_id FOR UPDATE;
    IF c.id IS NULL THEN
        RAISE EXCEPTION 'That price change is not there any more.';
    END IF;
    IF c.applied_at IS NOT NULL THEN
        RETURN 0;                       -- once only
    END IF;
    f := 1 + c.percent / 100.0;
    SELECT COALESCE(NULLIF(full_name, ''), username) INTO v_who
      FROM public.profiles WHERE id = auth.uid();

    IF c.scope IN ('all', 'list') THEN
        UPDATE public.price_list SET
            unit_price   = CASE WHEN 1 = ANY(c.tiers) THEN round(unit_price * f, 2)
                                ELSE unit_price END,
            unit_price_2 = CASE WHEN 2 = ANY(c.tiers) AND unit_price_2 IS NOT NULL
                                THEN round(unit_price_2 * f, 2) ELSE unit_price_2 END,
            unit_price_3 = CASE WHEN 3 = ANY(c.tiers) AND unit_price_3 IS NOT NULL
                                THEN round(unit_price_3 * f, 2) ELSE unit_price_3 END,
            updated_by_name = COALESCE(v_who, ''),
            updated_at = now()
         WHERE c.match_text = ''
            OR part_number ILIKE '%' || c.match_text || '%'
            OR COALESCE(name, '') ILIKE '%' || c.match_text || '%';
        GET DIAGNOSTICS k = ROW_COUNT;
        n := n + k;
    END IF;
    IF c.scope IN ('all', 'rates') THEN
        UPDATE public.price_rates SET
            rate_per_sqm   = CASE WHEN 1 = ANY(c.tiers) THEN round(rate_per_sqm * f, 2)
                                  ELSE rate_per_sqm END,
            rate_per_sqm_2 = CASE WHEN 2 = ANY(c.tiers) AND rate_per_sqm_2 IS NOT NULL
                                  THEN round(rate_per_sqm_2 * f, 2) ELSE rate_per_sqm_2 END,
            rate_per_sqm_3 = CASE WHEN 3 = ANY(c.tiers) AND rate_per_sqm_3 IS NOT NULL
                                  THEN round(rate_per_sqm_3 * f, 2) ELSE rate_per_sqm_3 END,
            updated_by_name = COALESCE(v_who, ''),
            updated_at = now()
         WHERE c.match_text = ''
            OR filter_type ILIKE '%' || c.match_text || '%'
            OR COALESCE(media_type, '') ILIKE '%' || c.match_text || '%';
        GET DIAGNOSTICS k = ROW_COUNT;
        n := n + k;
    END IF;

    UPDATE public.price_changes
       SET applied_at = now(), applied_by = COALESCE(v_who, ''), changed = n
     WHERE id = c.id;
    RETURN n;
END;
$$;

-- Everything due by today and not yet applied. Called by a manager's PC
-- when it starts; anybody else's call changes nothing.
CREATE OR REPLACE FUNCTION public.apply_due_price_changes()
RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    r record;
    n integer := 0;
BEGIN
    IF NOT public.is_manager() THEN
        RETURN 0;
    END IF;
    FOR r IN SELECT id FROM public.price_changes
              WHERE applied_at IS NULL AND starts_on <= current_date
              ORDER BY starts_on, created_at LOOP
        n := n + public.apply_price_change(r.id);
    END LOOP;
    RETURN n;
END;
$$;

REVOKE ALL ON FUNCTION public.apply_price_change(uuid)    FROM public, anon;
REVOKE ALL ON FUNCTION public.apply_due_price_changes()   FROM public, anon;
GRANT EXECUTE ON FUNCTION public.apply_price_change(uuid)  TO authenticated;
GRANT EXECUTE ON FUNCTION public.apply_due_price_changes() TO authenticated;
