-- ============================================================
-- TAF Order App - Switching features on and off
-- Run this in Supabase Dashboard -> SQL Editor. Safe to re-run.
--
-- Thirty things were asked for at once. Turning all of them on at once would
-- change every screen in the building on the same afternoon, and the first
-- one that got in somebody's way would be blamed on all of them.
--
-- So each arrives switched off, and a Director or an Admin turns it on when
-- the company is ready for it. Not a Manager: this decides how everybody
-- works, which is a different kind of decision from the ones a manager makes
-- day to day, and the switches that already exist (customer emails, stock
-- deduction) stay where they are at manager level.
--
-- One row per feature, shared by every PC and the web app, so a feature is
-- never half on - one machine showing a screen the others do not is how two
-- people end up doing the same job two different ways.
-- ============================================================

CREATE TABLE IF NOT EXISTS public.feature_switches (
    key        text PRIMARY KEY,
    enabled    boolean     NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text        NOT NULL DEFAULT ''
);

ALTER TABLE public.feature_switches ENABLE ROW LEVEL SECURITY;


-- ── Who decides ─────────────────────────────────────────────────────────────
-- is_manager() already exists and covers Manager as well. This is narrower on
-- purpose. SECURITY DEFINER so it can read profiles regardless of the policies
-- on profiles themselves, and search_path pinned so nothing can be shadowed.

CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.profiles
     WHERE id = auth.uid() AND approved = true
       AND role IN ('Director', 'Admin')
  );
$$;

REVOKE ALL ON FUNCTION public.is_admin() FROM public;
GRANT EXECUTE ON FUNCTION public.is_admin() TO authenticated;


-- Everyone reads: the app has to know which screens to draw, and hiding the
-- list of switches from the people the switches affect buys nothing.
DROP POLICY IF EXISTS "Staff read feature switches"   ON public.feature_switches;
DROP POLICY IF EXISTS "Admins add feature switches"   ON public.feature_switches;
DROP POLICY IF EXISTS "Admins change feature switches" ON public.feature_switches;
DROP POLICY IF EXISTS "Admins remove feature switches" ON public.feature_switches;

CREATE POLICY "Staff read feature switches"
    ON public.feature_switches FOR SELECT TO authenticated
    USING (public.is_staff());

CREATE POLICY "Admins add feature switches"
    ON public.feature_switches FOR INSERT TO authenticated
    WITH CHECK (public.is_admin());

CREATE POLICY "Admins change feature switches"
    ON public.feature_switches FOR UPDATE TO authenticated
    USING (public.is_admin())
    WITH CHECK (public.is_admin());

CREATE POLICY "Admins remove feature switches"
    ON public.feature_switches FOR DELETE TO authenticated
    USING (public.is_admin());


-- ── Flipping one ────────────────────────────────────────────────────────────
-- One statement rather than a read, a decision and a write from the app: two
-- directors on two PCs deciding at the same time would otherwise be a race,
-- and the loser's change would vanish with nothing said.
--
-- SECURITY INVOKER, so the policies above are what actually decide. The
-- function is a convenience, never the guard - a guard that lives in the
-- function can be walked around by writing to the table directly.

CREATE OR REPLACE FUNCTION public.set_feature(p_key text, p_on boolean)
RETURNS boolean
LANGUAGE sql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
    INSERT INTO public.feature_switches (key, enabled, updated_at, updated_by)
    VALUES (btrim(p_key), COALESCE(p_on, false), now(),
            COALESCE((SELECT COALESCE(NULLIF(full_name, ''), username)
                        FROM public.profiles WHERE id = auth.uid()), ''))
    ON CONFLICT (key) DO UPDATE
        SET enabled    = COALESCE(p_on, false),
            updated_at = now(),
            updated_by = EXCLUDED.updated_by
    RETURNING enabled;
$$;

REVOKE ALL ON FUNCTION public.set_feature(text, boolean) FROM public;
GRANT EXECUTE ON FUNCTION public.set_feature(text, boolean) TO authenticated;


-- ── How a filter is made ────────────────────────────────────────────────────
-- The channel calculator needs numbers that are the workshop's, not the
-- program's: the stick length it buys, the lip, and the shortest offcut
-- worth walking back to the rack with.
--
-- kerf_mm is nothing by default, and that is deliberate. A frame is not cut
-- into pieces at its marks - two 45 degree cuts take a triangle out of the
-- side so it folds there, and the lip has its sides cut away so it can fold
-- down and close. Both come off the flanges, not off the running length. The
-- only cut through the channel is the one separating one strip from the next
-- on the stick, and that is what this number is for. Set it only if your saw
-- really does eat into the next piece.
--
-- min_lip_mm is the other half of the same story. A lip is nominally 20mm
-- but anything down to 10mm still closes the filter, so a frame can be
-- shortened when that is what stands between one more filter and an offcut:
-- two G frames of a 295 x 310 come to 2444 against a 2440 stick, and two
-- millimetres off each lip makes them 2440 exactly.
--
-- Kept here rather than in each PC's settings file for the usual reason - a
-- cut list worked out on one machine has to match the one worked out on the
-- next, or the person at the saw stops believing either.

CREATE TABLE IF NOT EXISTS public.workshop_settings (
    key        text PRIMARY KEY,
    value      numeric     NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.workshop_settings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Staff read workshop settings"    ON public.workshop_settings;
DROP POLICY IF EXISTS "Managers set workshop settings"  ON public.workshop_settings;
DROP POLICY IF EXISTS "Managers add workshop settings"  ON public.workshop_settings;

CREATE POLICY "Staff read workshop settings"
    ON public.workshop_settings FOR SELECT TO authenticated
    USING (public.is_staff());

-- A manager, not only a director: the blade gets changed and the stick length
-- changes with the supplier, and neither should wait for a director to be in.
CREATE POLICY "Managers add workshop settings"
    ON public.workshop_settings FOR INSERT TO authenticated
    WITH CHECK (public.is_manager());

CREATE POLICY "Managers set workshop settings"
    ON public.workshop_settings FOR UPDATE TO authenticated
    USING (public.is_manager())
    WITH CHECK (public.is_manager());

-- ── What is on the offcut rack ──────────────────────────────────────────────
--
-- This is where the money actually goes. A bin of 300mm pieces nobody wrote
-- down is channel bought twice, and a 900mm piece nobody reaches for is a
-- 900mm piece that eventually gets thrown out.
--
-- A used offcut is marked, never deleted. "Where did that 1300 go" is a
-- question somebody asks, and a row that vanished cannot answer it.

CREATE TABLE IF NOT EXISTS public.channel_offcuts (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    length_mm  numeric     NOT NULL CHECK (length_mm > 0),
    profile    text        NOT NULL DEFAULT '',   -- which channel it is
    note       text        NOT NULL DEFAULT '',
    used       boolean     NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by text        NOT NULL DEFAULT '',
    used_at    timestamptz,
    used_by    text        NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS channel_offcuts_on_rack
    ON public.channel_offcuts (used, length_mm DESC);

ALTER TABLE public.channel_offcuts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Staff read offcuts"   ON public.channel_offcuts;
DROP POLICY IF EXISTS "Staff add offcuts"    ON public.channel_offcuts;
DROP POLICY IF EXISTS "Staff use offcuts"    ON public.channel_offcuts;
DROP POLICY IF EXISTS "Managers bin offcuts" ON public.channel_offcuts;

CREATE POLICY "Staff read offcuts"
    ON public.channel_offcuts FOR SELECT TO authenticated
    USING (public.is_staff());

-- Anyone at the saw, because the moment to write one down is the moment it
-- comes off the stick. Making that a manager's job is how it stops happening.
CREATE POLICY "Staff add offcuts"
    ON public.channel_offcuts FOR INSERT TO authenticated
    WITH CHECK (public.is_staff());

CREATE POLICY "Staff use offcuts"
    ON public.channel_offcuts FOR UPDATE TO authenticated
    USING (public.is_staff()) WITH CHECK (public.is_staff());

CREATE POLICY "Managers bin offcuts"
    ON public.channel_offcuts FOR DELETE TO authenticated
    USING (public.is_manager());


-- ── Which way a customer's filters get made ─────────────────────────────────
-- Some of them always want a G, or have a spec that says so. Storing it stops
-- it being a question every time, and stops the calculator cheerfully
-- recommending something that will be sent back.
--
-- Empty means no preference: make it whichever way is cheapest that day.

ALTER TABLE public.customers
    ADD COLUMN IF NOT EXISTS frame_preference text NOT NULL DEFAULT '';


INSERT INTO public.workshop_settings (key, value) VALUES
    ('stick_length_mm', 2440),   -- what a length of channel comes in at
    ('kerf_mm',            0),   -- see below
    ('keep_offcut_mm',   400),   -- shorter than this goes in the bin
    ('lip_mm',            20),   -- the fold that closes the filter
    ('min_lip_mm',        10),   -- the shortest lip that still closes it
    ('side_allowance_mm',  2)    -- every side is cut at the size less this
ON CONFLICT (key) DO NOTHING;    -- never overwrite what the workshop has set
