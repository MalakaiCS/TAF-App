-- ============================================================================
-- Step 48: out the door, and what it made
--
--   delivery_runs     the order the van goes round in, for each day - set on
--                     the PC or the phone, and the same on both
--   delivery_proofs   which signature was emailed to which customer, and when
--                     (written only by the proof-of-delivery function)
--   order_values      what each order is worth: its priced lines and its
--                     delivery fee, worked out once, here, so the PC, the
--                     phone and the owner's report never disagree
--   sales_targets     what a month should sell
--   owner_reports     which month's report went to whom - so the schedule
--                     never sends one twice
--
-- Behind switches that start off (Settings -> Features). Needs
-- migrate_staff_access.sql and the orders table. Safe to run more than once.
-- ============================================================================

DO $$
BEGIN
  IF to_regprocedure('public.is_staff()') IS NULL THEN
    RAISE EXCEPTION 'Run migrate_staff_access.sql first.';
  END IF;
END $$;


-- ── The run, in the order the van goes ──────────────────────────────────────
-- A day's stops as order ids, first stop first. Anybody on staff sets it: the
-- driver knows the roads better than the office does.

CREATE TABLE IF NOT EXISTS public.delivery_runs (
    run_date   date PRIMARY KEY,
    stops      uuid[]      NOT NULL DEFAULT '{}',
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text        NOT NULL DEFAULT ''
);

ALTER TABLE public.delivery_runs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Staff read runs"   ON public.delivery_runs;
DROP POLICY IF EXISTS "Staff write runs"  ON public.delivery_runs;
DROP POLICY IF EXISTS "Staff change runs" ON public.delivery_runs;
CREATE POLICY "Staff read runs" ON public.delivery_runs FOR SELECT
    TO authenticated USING (public.is_staff());
CREATE POLICY "Staff write runs" ON public.delivery_runs FOR INSERT
    TO authenticated WITH CHECK (public.is_staff());
CREATE POLICY "Staff change runs" ON public.delivery_runs FOR UPDATE
    TO authenticated USING (public.is_staff()) WITH CHECK (public.is_staff());


-- ── Proof of delivery, sent ─────────────────────────────────────────────────
-- Read by staff, so an order can say "emailed to them at 10:42". Nobody
-- writes it but the function, with the service key: a row here says an email
-- went, and only the thing that sent it can say that.

CREATE TABLE IF NOT EXISTS public.delivery_proofs (
    order_id       uuid PRIMARY KEY REFERENCES public.orders(id) ON DELETE CASCADE,
    signature_path text        NOT NULL DEFAULT '',
    signed_by      text        NOT NULL DEFAULT '',
    emailed_to     text        NOT NULL DEFAULT '',
    emailed_at     timestamptz,
    photos         integer     NOT NULL DEFAULT 0
);

ALTER TABLE public.delivery_proofs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Staff read proofs" ON public.delivery_proofs;
CREATE POLICY "Staff read proofs" ON public.delivery_proofs FOR SELECT
    TO authenticated USING (public.is_staff());


-- ── What an order is worth ──────────────────────────────────────────────────
-- Each line's "Unit Price" times its quantity ("Quantity" on a filter,
-- "quantity" on a bag or roll), plus the order's delivery fee - the same sum
-- the desktop shows under an order. A line with no price adds nothing and is
-- counted, so a figure can say how much of it is missing. The day is the day
-- it was entered, in Brisbane.

CREATE OR REPLACE VIEW public.order_values
WITH (security_invoker = true) AS
SELECT o.id,
       o.customer_name,
       o.order_number,
       o.created_at,
       (o.created_at AT TIME ZONE 'Australia/Brisbane')::date      AS ordered_on,
       COALESCE(NULLIF(o.header ->> 'status', ''), 'Pending')     AS status,
       COALESCE(o.archived, false)                                 AS archived,
       COALESCE(v.lines, 0)                                        AS lines_value,
       COALESCE(v.unpriced, 0)::integer                            AS unpriced,
       f.fee                                                       AS delivery_fee,
       round(COALESCE(v.lines, 0) + f.fee, 2)                      AS value
  FROM public.orders o
  LEFT JOIN LATERAL (
      SELECT sum(CASE WHEN p.price > 0 THEN p.price * p.qty ELSE 0 END) AS lines,
             count(*) FILTER (WHERE p.price <= 0)                       AS unpriced
        FROM jsonb_array_elements(
               CASE WHEN jsonb_typeof(o.items) = 'array' THEN o.items
                    ELSE '[]'::jsonb END) AS l(line)
        CROSS JOIN LATERAL (
            SELECT CASE WHEN COALESCE(l.line ->> 'Unit Price', '') ~ '^[0-9]+(\.[0-9]+)?$'
                        THEN (l.line ->> 'Unit Price')::numeric ELSE 0 END AS price,
                   CASE WHEN COALESCE(NULLIF(l.line ->> 'Quantity', ''),
                                      l.line ->> 'quantity', '') ~ '^[0-9]+(\.[0-9]+)?$'
                        THEN floor(COALESCE(NULLIF(l.line ->> 'Quantity', ''),
                                            l.line ->> 'quantity')::numeric)
                        ELSE 0 END AS qty
        ) AS p
       WHERE jsonb_typeof(l.line) = 'object'
  ) AS v ON true
 CROSS JOIN LATERAL (
      SELECT CASE WHEN ltrim(COALESCE(o.header ->> 'Delivery Fee', ''), '$')
                       ~ '^[0-9]+(\.[0-9]+)?$'
                  THEN round(ltrim(o.header ->> 'Delivery Fee', '$')::numeric, 2)
                  ELSE 0 END AS fee
 ) AS f;

GRANT SELECT ON public.order_values TO authenticated;


-- ── Targets ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.sales_targets (
    month      date PRIMARY KEY,
    target     numeric     NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text        NOT NULL DEFAULT '',
    CHECK (extract(day FROM month) = 1),
    CHECK (target >= 0)
);

ALTER TABLE public.sales_targets ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Staff read targets"     ON public.sales_targets;
DROP POLICY IF EXISTS "Managers write targets" ON public.sales_targets;
CREATE POLICY "Staff read targets" ON public.sales_targets FOR SELECT
    TO authenticated USING (public.is_staff());
CREATE POLICY "Managers write targets" ON public.sales_targets FOR ALL
    TO authenticated USING (public.is_manager()) WITH CHECK (public.is_manager());


-- ── The owner's report, sent ────────────────────────────────────────────────
-- Written by the function with the service key; managers can see what went.

CREATE TABLE IF NOT EXISTS public.owner_reports (
    month   date PRIMARY KEY,
    sent_at timestamptz NOT NULL DEFAULT now(),
    sent_to text[]      NOT NULL DEFAULT '{}',
    figures jsonb       NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE public.owner_reports ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Managers read reports" ON public.owner_reports;
CREATE POLICY "Managers read reports" ON public.owner_reports FOR SELECT
    TO authenticated USING (public.is_manager());


-- ── Sending the owner's report on the 1st ───────────────────────────────────
-- "Preview" and "Email it to me" on the PC work as soon as the owner-report
-- function is deployed. To send last month's to every director and admin on
-- the 1st, at 7am Brisbane (21:00 UTC the day before - the last day of the
-- month, which cron cannot say, so it runs each night from the 28th and the
-- function only sends on the night before the 1st):
--
--   SELECT cron.schedule('taf-owner-report', '0 21 28-31 * *', $job$
--     SELECT net.http_post(
--       url     := 'https://<your-project>.supabase.co/functions/v1/owner-report',
--       headers := jsonb_build_object(
--                    'Content-Type',  'application/json',
--                    'Authorization', 'Bearer ' || (SELECT decrypted_secret
--                                                     FROM vault.decrypted_secrets
--                                                    WHERE name = 'service_role_key')),
--       body    := '{"scheduled": true}'::jsonb);
--   $job$);
--
-- The service-role key lives in Vault (see migrate_notifications.sql), never
-- in this file.
