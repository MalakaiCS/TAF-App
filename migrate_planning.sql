-- ============================================================================
-- Step 45: who is in, and whether a day is already full
--
--   staff_roster   each person on the floor: the days they work, their hours
--   staff_leave    who is away, from when to when
--   workshop_settings  two more numbers: the minutes a filter takes when the
--                  job timer has not timed that type yet, and the share of a
--                  rostered day spent making (the rest is cleaning up,
--                  loading the ute, the phone)
--
-- With these, a new order due on a day that is already full says so before
-- it is saved, and names the next day with room - worked out from what is
-- booked that day (the job timer's minutes a filter, step 44), who is
-- rostered, who is on leave and the shutdown calendar.
--
-- Managers write the roster and leave; everybody can see them. Needs
-- migrate_staff_access.sql (16) and migrate_features.sql. Safe to run more
-- than once.
-- ============================================================================

DO $$
BEGIN
  IF to_regclass('public.workshop_settings') IS NULL THEN
    RAISE EXCEPTION 'Run migrate_features.sql first.';
  END IF;
END $$;


CREATE TABLE IF NOT EXISTS public.staff_roster (
    person     text PRIMARY KEY,
    -- The days they work, Monday 1 to Sunday 7.
    days       int[]       NOT NULL DEFAULT '{1,2,3,4,5}',
    hours      numeric     NOT NULL DEFAULT 7.6
                           CHECK (hours >= 0 AND hours <= 24),
    -- On the floor making filters. The office is rostered too, but does not
    -- add to what the factory can make in a day.
    makes      boolean     NOT NULL DEFAULT true,
    active     boolean     NOT NULL DEFAULT true,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text        NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS public.staff_leave (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    person     text        NOT NULL,
    first_day  date        NOT NULL,
    last_day   date        NOT NULL,
    kind       text        NOT NULL DEFAULT 'annual',
    note       text        NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by text        NOT NULL DEFAULT '',
    CHECK (last_day >= first_day)
);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conname = 'staff_leave_kind_check') THEN
    ALTER TABLE public.staff_leave ADD CONSTRAINT staff_leave_kind_check
        CHECK (kind IN ('annual', 'sick', 'training', 'other'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conname = 'staff_roster_days_check') THEN
    ALTER TABLE public.staff_roster ADD CONSTRAINT staff_roster_days_check
        CHECK (days <@ ARRAY[1, 2, 3, 4, 5, 6, 7]);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS staff_leave_days
    ON public.staff_leave (first_day, last_day);

ALTER TABLE public.staff_roster ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.staff_leave  ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Staff read the roster"     ON public.staff_roster;
DROP POLICY IF EXISTS "Managers write the roster" ON public.staff_roster;
DROP POLICY IF EXISTS "Staff read leave"          ON public.staff_leave;
DROP POLICY IF EXISTS "Managers write leave"      ON public.staff_leave;

CREATE POLICY "Staff read the roster" ON public.staff_roster FOR SELECT
    TO authenticated USING (public.is_staff());
CREATE POLICY "Managers write the roster" ON public.staff_roster FOR ALL
    TO authenticated USING (public.is_manager()) WITH CHECK (public.is_manager());
CREATE POLICY "Staff read leave" ON public.staff_leave FOR SELECT
    TO authenticated USING (public.is_staff());
CREATE POLICY "Managers write leave" ON public.staff_leave FOR ALL
    TO authenticated USING (public.is_manager()) WITH CHECK (public.is_manager());


INSERT INTO public.workshop_settings (key, value) VALUES
    ('minutes_per_filter', 15),   -- until the job timer has timed that type
    ('making_share',     0.8)     -- of a rostered day, spent making
ON CONFLICT (key) DO NOTHING;     -- never overwrite what the workshop has set
