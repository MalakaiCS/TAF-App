-- ============================================================================
-- Step 44: the factory floor
--
--   orders.header.status_at  when an order last changed status, stamped by
--                            the database - so the TV board knows what went
--                            out the door today
--   job_times                a start/stop timer on an order line, from the
--                            phone, and job_rates: how long each filter type
--                            really takes
--   qc_checklists            the few checks for each filter type, ticked
--                            before a line is marked made (kept on the line)
--   returns                  now also faults found in QC: which line, which
--                            filter type, who made it, and a photo
--   order_files / job-photos a photo of the finished job, which the customer
--                            sees on their portal - and, with the "finished
--                            photo" switch on, needed before an order is
--                            marked Complete
--
-- Every one of these is behind a feature switch that starts off (Settings ->
-- Features on the desktop), so running this changes nothing anybody sees.
--
-- Needs migrate_staff_access.sql (16), migrate_line_progress.sql,
-- migrate_order_files.sql, migrate_more_features.sql, migrate_features.sql
-- and migrate_portal_signin.sql. Safe to run more than once.
-- ============================================================================

DO $$
BEGIN
  IF to_regclass('public.feature_switches') IS NULL THEN
    RAISE EXCEPTION 'Run migrate_features.sql first.';
  END IF;
  IF to_regclass('public.returns') IS NULL THEN
    RAISE EXCEPTION 'Run migrate_more_features.sql first.';
  END IF;
  IF to_regclass('public.order_files') IS NULL THEN
    RAISE NOTICE 'migrate_order_files.sql has not been run: finished-job '
                 'photos wait until it is, then run this again.';
  END IF;
END $$;


-- ── When an order changed status ────────────────────────────────────────────
-- Stamped here rather than by each app, so a status set from the phone, the
-- desktop, a bulk change or the Xero sweep is stamped the same way.
--
-- And, with the "finished photo" switch on, an order cannot become Complete
-- (or go straight out the door) until somebody has taken a photo of the
-- finished job. Checked here so no screen can forget to.

CREATE OR REPLACE FUNCTION public.order_status_changed()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_old text := COALESCE(OLD.header ->> 'status', 'Pending');
    v_new text := COALESCE(NEW.header ->> 'status', 'Pending');
    v_has boolean := false;
BEGIN
    IF v_new IS DISTINCT FROM v_old THEN
        NEW.header := COALESCE(NEW.header, '{}'::jsonb)
            || jsonb_build_object('status_at',
                   to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'));
        IF v_new IN ('Complete', 'Dispatched', 'Delivered', 'Collected')
           AND v_old NOT IN ('Complete', 'Dispatched', 'Delivered', 'Collected')
           AND EXISTS (SELECT 1 FROM public.feature_switches
                        WHERE key = 'finished_photo' AND enabled) THEN
            -- Looked up by name, so this still works where photos have not
            -- been set up (it then has nothing to require).
            IF to_regclass('public.order_files') IS NOT NULL THEN
                EXECUTE 'SELECT EXISTS (SELECT 1 FROM public.order_files '
                        'WHERE order_id = $1 AND kind = ''finished'')'
                   INTO v_has USING NEW.id;
                IF NOT v_has THEN
                    RAISE EXCEPTION 'Take a photo of the finished job first: '
                        'open order % on the phone and press Finished job '
                        'photo.', COALESCE(NULLIF(NEW.order_number, ''), 'the')
                        USING ERRCODE = 'check_violation';
                END IF;
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS orders_status_changed ON public.orders;
CREATE TRIGGER orders_status_changed
    BEFORE UPDATE OF header ON public.orders
    FOR EACH ROW EXECUTE FUNCTION public.order_status_changed();

REVOKE ALL ON FUNCTION public.order_status_changed() FROM public, anon, authenticated;


-- ── How long things take ────────────────────────────────────────────────────
-- Start on a line, stop when it is done. One timer running per person:
-- starting another stops the first, the way a person can only be at one
-- bench. Written only through the two functions below, so a time cannot be
-- typed in after the fact.

CREATE TABLE IF NOT EXISTS public.job_times (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id     uuid REFERENCES public.orders(id) ON DELETE CASCADE,
    order_number text        NOT NULL DEFAULT '',
    line_id      text        NOT NULL DEFAULT '',
    filter_type  text        NOT NULL DEFAULT '',
    quantity     numeric     NOT NULL DEFAULT 0,
    user_id      uuid        DEFAULT auth.uid(),
    user_name    text        NOT NULL DEFAULT '',
    started_at   timestamptz NOT NULL DEFAULT now(),
    stopped_at   timestamptz,
    minutes      numeric
);

CREATE INDEX IF NOT EXISTS job_times_running
    ON public.job_times (user_id) WHERE stopped_at IS NULL;
CREATE INDEX IF NOT EXISTS job_times_by_type
    ON public.job_times (filter_type, started_at DESC);
CREATE INDEX IF NOT EXISTS job_times_by_order
    ON public.job_times (order_id);

ALTER TABLE public.job_times ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Staff read job times"     ON public.job_times;
DROP POLICY IF EXISTS "Managers bin job times"   ON public.job_times;
CREATE POLICY "Staff read job times" ON public.job_times FOR SELECT
    TO authenticated USING (public.is_staff());
-- A timer left running over the weekend is a manager's to throw away.
CREATE POLICY "Managers bin job times" ON public.job_times FOR DELETE
    TO authenticated USING (public.is_manager());

CREATE OR REPLACE FUNCTION public.stop_job_timer(p_id uuid DEFAULT NULL)
RETURNS SETOF public.job_times
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF NOT public.is_staff() THEN
        RAISE EXCEPTION 'Only staff can time a job.';
    END IF;
    RETURN QUERY
    UPDATE public.job_times
       SET stopped_at = now(),
           minutes = round((extract(epoch FROM now() - started_at) / 60.0)::numeric, 1)
     WHERE stopped_at IS NULL
       AND ((p_id IS NULL AND user_id = auth.uid())
            OR (p_id IS NOT NULL AND id = p_id
                AND (user_id = auth.uid() OR public.is_manager())))
    RETURNING *;
END;
$$;

CREATE OR REPLACE FUNCTION public.start_job_timer(p_order_id uuid, p_line_id text)
RETURNS public.job_times
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_order public.orders%ROWTYPE;
    v_line  jsonb;
    v_row   public.job_times%ROWTYPE;
BEGIN
    IF NOT public.is_staff() THEN
        RAISE EXCEPTION 'Only staff can time a job.';
    END IF;
    SELECT * INTO v_order FROM public.orders WHERE id = p_order_id;
    SELECT l INTO v_line
      FROM jsonb_array_elements(COALESCE(v_order.items, '[]'::jsonb)) AS l
     WHERE l ->> 'line_id' = p_line_id
     LIMIT 1;
    IF v_order.id IS NULL OR v_line IS NULL THEN
        RAISE EXCEPTION 'That line is not on the order any more.';
    END IF;

    PERFORM public.stop_job_timer(NULL);      -- one bench at a time

    INSERT INTO public.job_times
           (order_id, order_number, line_id, filter_type, quantity,
            user_id, user_name)
    VALUES (v_order.id, COALESCE(v_order.order_number, ''), p_line_id,
            COALESCE(NULLIF(v_line ->> 'Filter Type', ''),
                     NULLIF(v_line ->> 'product_type', ''),
                     NULLIF(v_line ->> 'Description', ''), 'Other'),
            COALESCE(NULLIF(regexp_replace(COALESCE(v_line ->> 'Quantity',
                                v_line ->> 'quantity', ''), '[^0-9.]', '', 'g'),
                            '')::numeric, 0),
            auth.uid(),
            COALESCE((SELECT COALESCE(NULLIF(full_name, ''), username)
                        FROM public.profiles WHERE id = auth.uid()), ''))
    RETURNING * INTO v_row;
    RETURN v_row;
END;
$$;

REVOKE ALL ON FUNCTION public.start_job_timer(uuid, text) FROM public, anon;
REVOKE ALL ON FUNCTION public.stop_job_timer(uuid)       FROM public, anon;
GRANT EXECUTE ON FUNCTION public.start_job_timer(uuid, text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.stop_job_timer(uuid)       TO authenticated;

-- Minutes a filter, by type, over the last six months. A timer left running
-- for more than ten hours was somebody going home, not a filter.
CREATE OR REPLACE VIEW public.job_rates
WITH (security_invoker = true) AS
SELECT filter_type,
       count(*)                                         AS timings,
       sum(quantity)                                    AS filters,
       round(sum(minutes) / NULLIF(sum(quantity), 0), 1) AS minutes_each
  FROM public.job_times
 WHERE stopped_at IS NOT NULL
   AND minutes > 0 AND minutes < 600
   AND quantity > 0
   AND started_at > now() - interval '180 days'
 GROUP BY filter_type;

GRANT SELECT ON public.job_rates TO authenticated;


-- ── Quality checks ──────────────────────────────────────────────────────────
-- A short list per filter type ('*' for any type without its own), ticked
-- before a line is marked made. What was ticked, by whom and when is kept on
-- the line itself, next to who made it.

CREATE TABLE IF NOT EXISTS public.qc_checklists (
    filter_type text PRIMARY KEY,
    checks      jsonb       NOT NULL DEFAULT '[]'::jsonb,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    updated_by  text        NOT NULL DEFAULT ''
);

ALTER TABLE public.qc_checklists ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Staff read QC checklists"      ON public.qc_checklists;
DROP POLICY IF EXISTS "Managers write QC checklists"  ON public.qc_checklists;
CREATE POLICY "Staff read QC checklists" ON public.qc_checklists FOR SELECT
    TO authenticated USING (public.is_staff());
CREATE POLICY "Managers write QC checklists" ON public.qc_checklists FOR ALL
    TO authenticated USING (public.is_manager()) WITH CHECK (public.is_manager());

-- The same shape as set_order_line_made: one line, by its id, in place.
DROP FUNCTION IF EXISTS public.set_order_line_qc(uuid, text, jsonb);
CREATE FUNCTION public.set_order_line_qc(
    p_order_id uuid,
    p_line_id  text,
    p_qc       jsonb)
RETURNS uuid
LANGUAGE sql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
    UPDATE public.orders
       SET items = (
           SELECT jsonb_agg(
                      CASE WHEN line ->> 'line_id' = p_line_id
                           THEN line || jsonb_build_object('qc', p_qc)
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

REVOKE ALL ON FUNCTION public.set_order_line_qc(uuid, text, jsonb) FROM public;
GRANT EXECUTE ON FUNCTION public.set_order_line_qc(uuid, text, jsonb) TO authenticated;


-- ── Faults: found in QC, or come back ───────────────────────────────────────
-- The returns already kept say what came back and why. A fault found before
-- it left is the same record, earlier: which line, what type, who made it,
-- and a photo - so patterns by type and by person can be seen.

ALTER TABLE public.returns ADD COLUMN IF NOT EXISTS line_id     text NOT NULL DEFAULT '';
ALTER TABLE public.returns ADD COLUMN IF NOT EXISTS filter_type text NOT NULL DEFAULT '';
ALTER TABLE public.returns ADD COLUMN IF NOT EXISTS found       text NOT NULL DEFAULT 'returned';
ALTER TABLE public.returns ADD COLUMN IF NOT EXISTS made_by     text NOT NULL DEFAULT '';
ALTER TABLE public.returns ADD COLUMN IF NOT EXISTS photo_path  text NOT NULL DEFAULT '';

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conname = 'returns_found_check') THEN
    ALTER TABLE public.returns ADD CONSTRAINT returns_found_check
        CHECK (found IN ('returned', 'qc', 'site'));
  END IF;
END $$;


-- ── A photo of the finished job ─────────────────────────────────────────────
-- Kept in its own bucket, which is public: the customer sees it on their
-- portal, where there is no sign-in to read a private file with. Each file's
-- name is random, so it cannot be guessed; it shows filters, never a
-- signature or anybody's plant room (those stay in order-files).

DO $$
BEGIN
  IF to_regclass('public.order_files') IS NOT NULL THEN
    ALTER TABLE public.order_files
        ADD COLUMN IF NOT EXISTS bucket text NOT NULL DEFAULT 'order-files';
  END IF;
END $$;

DO $$
BEGIN
  -- A database without Supabase Storage (a test one) has no buckets.
  IF to_regclass('storage.buckets') IS NULL THEN
    RETURN;
  END IF;
  INSERT INTO storage.buckets (id, name, public)
  VALUES ('job-photos', 'job-photos', true)
  ON CONFLICT (id) DO UPDATE SET public = true;

  EXECUTE 'DROP POLICY IF EXISTS "Staff add job photos" ON storage.objects';
  EXECUTE 'DROP POLICY IF EXISTS "Staff remove job photos" ON storage.objects';
  EXECUTE 'CREATE POLICY "Staff add job photos" ON storage.objects
             FOR INSERT TO authenticated
             WITH CHECK (bucket_id = ''job-photos'' AND public.is_staff())';
  EXECUTE 'CREATE POLICY "Staff remove job photos" ON storage.objects
             FOR DELETE TO authenticated
             USING (bucket_id = ''job-photos'' AND public.is_staff())';
END $$;


-- ── The customer's portal shows them ────────────────────────────────────────
-- portal_order as in migrate_portal_signin.sql, with the finished-job photos
-- added at the end.

CREATE OR REPLACE FUNCTION public.portal_order(p_token text, p_order_number text)
RETURNS json
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  c public.customers%ROWTYPE;
  o public.orders%ROWTYPE;
BEGIN
  c := public.portal_customer(p_token);
  IF c.id IS NULL THEN
    RETURN NULL;
  END IF;

  SELECT * INTO o
    FROM public.orders
   WHERE lower(trim(COALESCE(order_number, ''))) =
         lower(trim(COALESCE(p_order_number, '')))
     AND lower(trim(COALESCE(customer_name, ''))) IN (
           lower(trim(COALESCE(c.short_name, ''))),
           lower(trim(COALESCE(c.name, ''))))
   ORDER BY created_at DESC
   LIMIT 1;

  IF o.id IS NULL THEN
    RETURN NULL;
  END IF;

  RETURN json_build_object(
    'order_number', o.order_number,
    'date_ordered', o.date_ordered,
    'date_due',     o.date_due,
    'status',       COALESCE(o.header->>'status', 'Pending'),
    'region',       COALESCE(o.header->>'Location', ''),
    'job',          COALESCE(o.header->>'Job', ''),
    'stage', CASE
        WHEN COALESCE(o.header->>'status', 'Pending') = 'Dispatched'
          THEN CASE WHEN COALESCE(o.header->>'Location','') = 'Pick Up'
                    THEN 'Collected' ELSE 'Delivered' END
        WHEN COALESCE(o.header->>'status', 'Pending') = 'Complete'
          THEN CASE WHEN COALESCE(o.header->>'Location','') = 'Pick Up'
                    THEN 'Ready for pick up' ELSE 'Ready for delivery' END
        WHEN COALESCE(o.header->>'status', 'Pending') = 'In Production'
          THEN 'Being made'
        ELSE 'Received' END,
    'freight', COALESCE(o.header->'freight', '{}'::jsonb),
    'items', COALESCE((
        SELECT json_agg(json_build_object(
                 'quantity',    it->>'Quantity',
                 'description', trim(concat_ws(' ',
                     NULLIF(it->>'Filter Type', ''),
                     NULLIF(it->>'Media Type', ''),
                     CASE WHEN COALESCE(it->>'Short','') <> ''
                          THEN concat(it->>'Short', ' x ', it->>'Long',
                                      ' x ', it->>'Channel', 'mm') END)),
                 'part_number', it->>'Part Number'))
          FROM jsonb_array_elements(COALESCE(o.items, '[]'::jsonb)) AS it
      ), '[]'::json),
    -- Their finished filters, in the public job-photos bucket.
    'photos', COALESCE((
        SELECT json_agg(f.path ORDER BY f.created_at)
          FROM public.order_files f
         WHERE f.order_id = o.id AND f.kind = 'finished'
           AND f.bucket = 'job-photos'
      ), '[]'::json)
  );
END;
$$;

REVOKE ALL ON FUNCTION public.portal_order(text, text) FROM public;
GRANT EXECUTE ON FUNCTION public.portal_order(text, text) TO anon, authenticated;
