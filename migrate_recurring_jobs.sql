-- ============================================================
-- TAF Order App - Jobs that come round again
-- Run this in Supabase Dashboard -> SQL Editor. Safe to re-run.
--
-- A handful of jobs are done on a cycle - the same site, the same filters,
-- every three or six months. The app has recorded every one of them for
-- years and never once used that to say "this one is due again". Somebody
-- has to remember, and when they don't, the customer rings up instead.
--
-- One row per standing job, pointing at the order it is copied from. Not a
-- rule per filter type: TAF does three or four of these, and a rule that
-- fires on every G4 panel ever sold would be noise.
-- ============================================================

CREATE TABLE IF NOT EXISTS public.recurring_jobs (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_name     text        NOT NULL DEFAULT '',
    job               text        NOT NULL DEFAULT '',
    location          text        NOT NULL DEFAULT '',
    every_months      integer     NOT NULL DEFAULT 3,
    next_due          date        NOT NULL,
    last_raised       date,
    template_order_id uuid        REFERENCES public.orders(id) ON DELETE SET NULL,
    active            boolean     NOT NULL DEFAULT true,
    note              text        NOT NULL DEFAULT '',
    created_at        timestamptz NOT NULL DEFAULT now(),
    created_by        text        NOT NULL DEFAULT ''
);

-- ON DELETE SET NULL, not CASCADE: deleting an old order must not silently
-- delete the standing job that was copied from it. The job survives with no
-- template and says so, which is a thing someone can fix.

CREATE INDEX IF NOT EXISTS recurring_jobs_due_idx
    ON public.recurring_jobs (next_due) WHERE active;

ALTER TABLE public.recurring_jobs ENABLE ROW LEVEL SECURITY;

-- Same rule as everything else: approved staff only. is_staff() comes from
-- migrate_staff_access.sql - run that one first.
DROP POLICY IF EXISTS "Staff read recurring jobs"   ON public.recurring_jobs;
DROP POLICY IF EXISTS "Staff add recurring jobs"    ON public.recurring_jobs;
DROP POLICY IF EXISTS "Staff change recurring jobs" ON public.recurring_jobs;
DROP POLICY IF EXISTS "Staff remove recurring jobs" ON public.recurring_jobs;

CREATE POLICY "Staff read recurring jobs"
    ON public.recurring_jobs FOR SELECT TO authenticated
    USING (public.is_staff());

CREATE POLICY "Staff add recurring jobs"
    ON public.recurring_jobs FOR INSERT TO authenticated
    WITH CHECK (public.is_staff());

CREATE POLICY "Staff change recurring jobs"
    ON public.recurring_jobs FOR UPDATE TO authenticated
    USING (public.is_staff());

CREATE POLICY "Staff remove recurring jobs"
    ON public.recurring_jobs FOR DELETE TO authenticated
    USING (public.is_staff());
