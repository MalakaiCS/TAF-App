-- ============================================================
-- TAF Order App - Restrict every table to approved staff
-- Run this in Supabase Dashboard -> SQL Editor. SAFE TO RE-RUN.
--
-- WHY THIS EXISTS
--
-- Every policy in this project was written as
--     FOR SELECT TO authenticated USING (true)
-- which means "anyone Supabase considers signed in". The login window offers
-- Create Account, which calls auth.sign_up with the publishable key - and
-- that key is public by design: it ships inside the Windows installer and now
-- travels in customer quote links.
--
-- Put together, anyone who has that key could create an account and then read
-- every order, customer, quote, price and stock record - and, on several
-- tables, change or delete them.
--
-- Being signed in is not the same as being staff. From here, staff means
-- "has an APPROVED row in profiles", and that is what the policies check.
--
-- NOBODY WHO WORKS THERE NOW IS LOCKED OUT: every profile that already exists
-- is marked approved by this script. Only accounts created after it runs need
-- approving, which is what you want - a stranger signing up gets an account
-- that can see nothing at all.
-- ============================================================

-- ── Who counts as staff ─────────────────────────────────────────────────────

ALTER TABLE profiles ADD COLUMN IF NOT EXISTS approved boolean NOT NULL DEFAULT false;

-- Everyone already on the books keeps working. This is the line that makes
-- the migration safe to run in the middle of a working day.
UPDATE profiles SET approved = true WHERE approved IS DISTINCT FROM true;

-- New self-registrations are NOT approved. A Director or Admin approves them
-- in User Management.
ALTER TABLE profiles ALTER COLUMN approved SET DEFAULT false;

CREATE OR REPLACE FUNCTION public.is_staff()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.profiles
     WHERE id = auth.uid() AND approved = true
  );
$$;

CREATE OR REPLACE FUNCTION public.is_manager()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.profiles
     WHERE id = auth.uid() AND approved = true
       AND role IN ('Director', 'Admin', 'Manager')
  );
$$;

REVOKE ALL ON FUNCTION public.is_staff()   FROM public;
REVOKE ALL ON FUNCTION public.is_manager() FROM public;
GRANT EXECUTE ON FUNCTION public.is_staff()   TO authenticated;
GRANT EXECUTE ON FUNCTION public.is_manager() TO authenticated;

-- ── profiles ────────────────────────────────────────────────────────────────
-- Everyone signed in may read their OWN row (the app needs it to know who you
-- are and whether you are approved yet). Reading everyone else's is staff only.

DROP POLICY IF EXISTS "Authenticated users can view all profiles" ON profiles;
DROP POLICY IF EXISTS "profiles_select_self"  ON profiles;
DROP POLICY IF EXISTS "profiles_select_staff" ON profiles;

CREATE POLICY "profiles_select_self"  ON profiles FOR SELECT TO authenticated
  USING (id = auth.uid());
CREATE POLICY "profiles_select_staff" ON profiles FOR SELECT TO authenticated
  USING (public.is_staff());

-- Creating and editing your own row stays as it was: it is how an account is
-- set up, and `approved` is what actually grants anything.
-- (The existing "Users can insert own profile" / "update own profile"
--  policies are left in place.)

-- ── Everything else: approved staff only ────────────────────────────────────

DO $$
DECLARE
  t text;
  staff_tables text[] := ARRAY[
    'orders', 'customers', 'stock_items', 'stock_transactions',
    'stock_alerts', 'media_types', 'catalog_lists', 'audit_log',
    'price_list', 'price_rates', 'quotes'
  ];
BEGIN
  FOREACH t IN ARRAY staff_tables LOOP
    IF to_regclass('public.' || t) IS NULL THEN
      RAISE NOTICE 'skipping %, not present', t;
      CONTINUE;
    END IF;

    -- Drop every existing policy on the table, whatever it was called, so a
    -- forgotten "USING (true)" cannot survive this migration.
    EXECUTE (
      SELECT coalesce(string_agg(
        format('DROP POLICY IF EXISTS %I ON public.%I;', polname, t), ' '), '')
      FROM pg_policy p
      JOIN pg_class c ON c.oid = p.polrelid
      WHERE c.relname = t AND c.relnamespace = 'public'::regnamespace
    );

    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY;', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I FOR SELECT TO authenticated '
      'USING (public.is_staff());', t || '_staff_read', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I FOR INSERT TO authenticated '
      'WITH CHECK (public.is_staff());', t || '_staff_insert', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I FOR UPDATE TO authenticated '
      'USING (public.is_staff()) WITH CHECK (public.is_staff());',
      t || '_staff_update', t);
  END LOOP;
END $$;

-- Deleting is for Managers and above, on everything.
DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['orders', 'customers', 'stock_items',
                           'stock_transactions', 'stock_alerts', 'media_types',
                           'catalog_lists', 'price_list', 'price_rates',
                           'quotes'] LOOP
    IF to_regclass('public.' || t) IS NULL THEN CONTINUE; END IF;
    EXECUTE format(
      'CREATE POLICY %I ON public.%I FOR DELETE TO authenticated '
      'USING (public.is_manager());', t || '_manager_delete', t);
  END LOOP;
END $$;

-- The audit log is append-only for staff and readable by Managers: a record
-- of what happened is worth little if the person who did it can edit it.
DROP POLICY IF EXISTS audit_log_staff_update ON audit_log;
DROP POLICY IF EXISTS audit_log_staff_read   ON audit_log;
DO $$
BEGIN
  IF to_regclass('public.audit_log') IS NOT NULL THEN
    EXECUTE 'DROP POLICY IF EXISTS audit_log_staff_read ON public.audit_log';
    EXECUTE 'CREATE POLICY audit_log_manager_read ON public.audit_log '
            'FOR SELECT TO authenticated USING (public.is_manager())';
  END IF;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── Check it worked ─────────────────────────────────────────────────────────
-- Every row this returns is a policy that still lets any signed-in account in.
-- It should come back empty.

SELECT c.relname AS still_open, p.polname
  FROM pg_policy p
  JOIN pg_class c ON c.oid = p.polrelid
 WHERE c.relnamespace = 'public'::regnamespace
   AND pg_get_expr(p.polqual, p.polrelid) = 'true'
   AND c.relname <> 'profiles';
