-- ============================================================================
-- Step 37: Xero, linked for good
--
-- One Xero connection for the whole company, made once by a manager and used
-- by every staff account from then on:
--
--   * every order becomes a DRAFT invoice in Xero, dated the day on the work
--     order, and is kept up to date while it is still a draft;
--   * when the job is marked Complete (or Dispatched) the invoice is dated
--     that day, approved, and emailed to the contact on file in Xero.
--
-- What this file adds:
--
--   xero_connection   the sign-in to Xero. Nobody signed in to the app can
--                     read or change it - only the xero Edge Function, with
--                     the service role. (It used to sit in catalog_lists,
--                     which every signed-in account can read; that row is
--                     deleted here and Xero has to be connected again.)
--   xero_invoices     one row per order: its invoice in Xero, where it is up
--                     to, and anything that stopped it. Staff can read it;
--                     only the function and the triggers below write it.
--   a trigger on orders that notes the day a job is completed - whichever
--     screen, phone or PC marked it - and that an order was deleted, so its
--     draft can be taken back out of Xero.
--
-- The xero function does the talking to Xero. Deploy it with
--   supabase functions deploy xero --no-verify-jwt
-- (Xero sends the person back to it in a browser, without an app sign-in;
-- every other request is checked by the function itself.)
--
-- Safe to run more than once.
-- ============================================================================


-- ── The connection ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.xero_connection (
  id               int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  access_token     text,
  refresh_token    text,
  expires_at       timestamptz,
  tenant_id        text,
  tenant_name      text,
  -- The sign-in in progress: checked when Xero sends the person back.
  state            text,
  state_by         uuid,
  state_at         timestamptz,
  connected_by     uuid,
  connected_at     timestamptz,
  -- Orders raised from this moment on go to Xero. Kept across a connection
  -- that drops, so the orders taken while it was down still go once it is
  -- back; cleared by a deliberate Disconnect.
  drafts_from      timestamptz,
  refreshed_at     timestamptz,
  -- Xero's refresh tokens work once. Two requests renewing at the same time
  -- would have the second one end the connection, so one at a time.
  refreshing_until timestamptz,
  problem          text,
  updated_at       timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.xero_connection ENABLE ROW LEVEL SECURITY;
-- No policies, and no grants: not readable or writable by any app sign-in.
REVOKE ALL ON public.xero_connection FROM PUBLIC;
REVOKE ALL ON public.xero_connection FROM anon, authenticated;

-- The old home of the Xero sign-in was readable by every signed-in account.
-- Anything stored there has to be treated as seen: it goes, and Xero is
-- connected again into xero_connection.
DO $$
BEGIN
  IF to_regclass('public.catalog_lists') IS NOT NULL THEN
    DELETE FROM public.catalog_lists WHERE key = 'xero_tokens';
  END IF;
END $$;


-- ── One row per order ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.xero_invoices (
  order_id        uuid PRIMARY KEY,
  -- waiting   no invoice in Xero yet
  -- draft     a draft in Xero, following the order
  -- approved  approved in Xero; the email did not go (see error)
  -- sent      approved and emailed
  -- deleted   the order was deleted and so was its draft
  -- gone      changed by hand in Xero (approved, voided, deleted, paid):
  --           the app leaves it alone from then on
  state           text NOT NULL DEFAULT 'waiting'
                  CHECK (state IN ('waiting', 'draft', 'approved', 'sent',
                                   'deleted', 'gone')),
  invoice_id      text,
  invoice_number  text,
  contact_id      text,
  contact_name    text,
  -- What the draft was made from, so an unchanged order is not sent again.
  lines_hash      text,
  source_md5      text,
  unpriced        int NOT NULL DEFAULT 0,
  total           numeric,
  invoice_date    date,
  terms           text,
  complete_wanted boolean NOT NULL DEFAULT false,
  completed_on    date,
  delete_wanted   boolean NOT NULL DEFAULT false,
  error           text,
  next_try_at     timestamptz,
  claimed_until   timestamptz,
  approved_at     timestamptz,
  emailed_at      timestamptz,
  emailed_to      text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS xero_invoices_due
  ON public.xero_invoices (state) WHERE complete_wanted OR delete_wanted;

ALTER TABLE public.xero_invoices ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.xero_invoices FROM PUBLIC;
REVOKE ALL ON public.xero_invoices FROM anon, authenticated;
GRANT SELECT ON public.xero_invoices TO authenticated;

DROP POLICY IF EXISTS xero_invoices_staff_read ON public.xero_invoices;
DO $$
BEGIN
  IF to_regprocedure('public.is_staff()') IS NOT NULL THEN
    EXECUTE 'CREATE POLICY xero_invoices_staff_read ON public.xero_invoices '
         || 'FOR SELECT TO authenticated USING (public.is_staff())';
  ELSE
    -- Before migrate_staff_access.sql (step 16): the same as every other
    -- table until then. Run step 16.
    EXECUTE 'CREATE POLICY xero_invoices_staff_read ON public.xero_invoices '
         || 'FOR SELECT TO authenticated USING (true)';
  END IF;
END $$;


-- ── Who is asking ───────────────────────────────────────────────────────────
-- Approved staff, and whether a manager. Works before step 16 too, when
-- nobody has an "approved" yet (everyone counts as approved then).

CREATE OR REPLACE FUNCTION public._xero_is_staff(p_uid uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.profiles p
     WHERE p.id = p_uid
       AND COALESCE((to_jsonb(p) ->> 'approved')::boolean, true));
$$;

CREATE OR REPLACE FUNCTION public.xero_who(p_uid uuid)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT jsonb_build_object(
    'staff',   public._xero_is_staff(p_uid),
    'manager', public._xero_is_staff(p_uid) AND EXISTS (
                 SELECT 1 FROM public.profiles
                  WHERE id = p_uid
                    AND role IN ('Director', 'Admin', 'Manager')));
$$;


-- ── What an order's draft is made from ──────────────────────────────────────
-- The parts of an order that change its invoice. Notes, ticks and status do
-- not, so they do not send the draft round again.

CREATE OR REPLACE FUNCTION public._xero_source_md5(o public.orders)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT md5(COALESCE(o.items::text, '') || '|' ||
             COALESCE(o.customer_name, '') || '|' ||
             COALESCE(o.header ->> 'Customer Name', '') || '|' ||
             COALESCE(o.header ->> 'Order Number', '') || '|' ||
             COALESCE(o.header ->> 'Date Ordered', '') || '|' ||
             COALESCE(o.header ->> 'Job', ''));
$$;


-- ── The trigger: completed, uncompleted, deleted ────────────────────────────

CREATE OR REPLACE FUNCTION public._xero_order_changed()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_from     timestamptz;
  v_done_new boolean;
  v_done_old boolean := false;
BEGIN
  -- An order must never fail to save because of Xero.
  BEGIN
    IF TG_OP = 'DELETE' THEN
      UPDATE public.xero_invoices
         SET delete_wanted = true, next_try_at = NULL, updated_at = now()
       WHERE order_id = OLD.id AND state IN ('waiting', 'draft');
      RETURN OLD;
    END IF;

    SELECT drafts_from INTO v_from
      FROM public.xero_connection WHERE id = 1;
    IF v_from IS NULL OR NEW.created_at < v_from THEN
      RETURN NEW;
    END IF;

    v_done_new := COALESCE(NEW.header ->> 'status', '')
                  IN ('Complete', 'Dispatched');
    IF TG_OP = 'UPDATE' THEN
      v_done_old := COALESCE(OLD.header ->> 'status', '')
                    IN ('Complete', 'Dispatched');
    END IF;

    IF v_done_new AND NOT v_done_old THEN
      -- The day it was finished, in Brisbane, whenever the invoice is
      -- actually approved.
      INSERT INTO public.xero_invoices (order_id, complete_wanted, completed_on)
      VALUES (NEW.id, true, (now() AT TIME ZONE 'Australia/Brisbane')::date)
      ON CONFLICT (order_id) DO UPDATE
         SET complete_wanted = true,
             completed_on    = EXCLUDED.completed_on,
             next_try_at     = NULL,
             updated_at      = now()
       WHERE public.xero_invoices.state IN ('waiting', 'draft');
    ELSIF v_done_old AND NOT v_done_new THEN
      -- Put back before the invoice went: it waits again.
      UPDATE public.xero_invoices
         SET complete_wanted = false, completed_on = NULL, updated_at = now()
       WHERE order_id = NEW.id AND state IN ('waiting', 'draft');
    END IF;
  EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'xero: % (order still saved)', SQLERRM;
  END;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public._xero_order_changed() FROM PUBLIC;

DROP TRIGGER IF EXISTS xero_order_changed ON public.orders;
CREATE TRIGGER xero_order_changed
  AFTER INSERT OR DELETE OR UPDATE OF header ON public.orders
  FOR EACH ROW EXECUTE FUNCTION public._xero_order_changed();


-- ── For the app: orders whose draft needs making or bringing up to date ─────
-- Pricing an order needs the price list and the part-number rules, which
-- live in the desktop app; so the app asks for these, prices them and hands
-- each to the function.

DROP FUNCTION IF EXISTS public.xero_orders_to_draft(int);
CREATE FUNCTION public.xero_orders_to_draft(p_limit int DEFAULT 10)
RETURNS TABLE (order_id uuid, created_at timestamptz, customer_name text,
               customer_id text, header jsonb, items jsonb,
               lines_hash text, source_md5 text, state text)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF NOT public._xero_is_staff(auth.uid()) THEN
    RAISE EXCEPTION 'Only staff can send orders to Xero.';
  END IF;
  RETURN QUERY
  SELECT o.id, o.created_at, o.customer_name,
         to_jsonb(o) ->> 'customer_id', o.header, o.items,
         x.lines_hash, public._xero_source_md5(o), x.state
    FROM public.orders o
    JOIN public.xero_connection c
      ON c.id = 1 AND c.refresh_token IS NOT NULL
     AND c.drafts_from IS NOT NULL AND o.created_at >= c.drafts_from
    LEFT JOIN public.xero_invoices x ON x.order_id = o.id
   WHERE (x.claimed_until IS NULL OR x.claimed_until < now())
     AND NOT COALESCE(x.delete_wanted, false)
     AND (
       x.order_id IS NULL
       -- Not made yet: when it is due another go, or the order changed.
       OR (x.state = 'waiting' AND x.invoice_id IS NULL
           AND (x.next_try_at IS NULL OR x.next_try_at < now()
                OR x.source_md5 IS DISTINCT FROM public._xero_source_md5(o)))
       -- A draft whose order has changed since. Once the job is complete it
       -- is only redone to put right a line that had no price.
       OR (x.state = 'draft'
           AND x.source_md5 IS DISTINCT FROM public._xero_source_md5(o)
           AND (NOT x.complete_wanted OR x.unpriced > 0))
     )
   ORDER BY o.created_at
   LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 10), 50));
END;
$$;

-- How many invoices are waiting on Xero (approve and email, or take back
-- out), so the app only calls the function when there is something to do.
CREATE OR REPLACE FUNCTION public.xero_due_count()
RETURNS int
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT CASE WHEN NOT public._xero_is_staff(auth.uid()) THEN 0 ELSE (
    SELECT count(*)::int FROM public.xero_invoices
     WHERE (claimed_until IS NULL OR claimed_until < now())
       AND (next_try_at IS NULL OR next_try_at < now())
       AND ((complete_wanted AND state = 'draft' AND unpriced = 0
             AND invoice_id IS NOT NULL)
            OR (delete_wanted AND state IN ('waiting', 'draft')))) END;
$$;

REVOKE ALL ON FUNCTION public.xero_orders_to_draft(int) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.xero_due_count() FROM PUBLIC;
REVOKE ALL ON FUNCTION public._xero_is_staff(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.xero_who(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public._xero_source_md5(public.orders) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.xero_orders_to_draft(int) TO authenticated;
GRANT EXECUTE ON FUNCTION public.xero_due_count() TO authenticated;


-- ── For the function only (service role) ────────────────────────────────────

CREATE OR REPLACE FUNCTION public.xero_conn_get()
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT COALESCE((SELECT to_jsonb(c) FROM public.xero_connection c
                    WHERE id = 1), '{}'::jsonb);
$$;

-- Change the given fields of the connection; the rest stay as they are.
CREATE OR REPLACE FUNCTION public.xero_conn_put(p_patch jsonb)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  INSERT INTO public.xero_connection (id) VALUES (1) ON CONFLICT DO NOTHING;
  UPDATE public.xero_connection c
     SET (access_token, refresh_token, expires_at, tenant_id, tenant_name,
          state, state_by, state_at, connected_by, connected_at, drafts_from,
          refreshed_at, refreshing_until, problem)
       = (SELECT r.access_token, r.refresh_token, r.expires_at, r.tenant_id,
                 r.tenant_name, r.state, r.state_by, r.state_at,
                 r.connected_by, r.connected_at, r.drafts_from,
                 r.refreshed_at, r.refreshing_until, r.problem
            FROM jsonb_populate_record(c, p_patch - 'id') r),
         updated_at = now()
   WHERE c.id = 1;
  RETURN public.xero_conn_get();
END;
$$;

-- Take the right to renew the sign-in for a few seconds. Returns the refresh
-- token to renew with, or NULL when another request is renewing it already.
CREATE OR REPLACE FUNCTION public.xero_conn_begin_refresh(p_seconds int DEFAULT 30)
RETURNS text
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  UPDATE public.xero_connection
     SET refreshing_until = now() + make_interval(secs => p_seconds)
   WHERE id = 1 AND refresh_token IS NOT NULL
     AND (refreshing_until IS NULL OR refreshing_until < now())
  RETURNING refresh_token;
$$;

-- Write what the renewal gave back - only if nobody has renewed in between.
CREATE OR REPLACE FUNCTION public.xero_conn_end_refresh(p_old text, p_patch jsonb)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.xero_connection
                  WHERE id = 1 AND refresh_token IS NOT DISTINCT FROM p_old) THEN
    RETURN false;
  END IF;
  PERFORM public.xero_conn_put(p_patch || '{"refreshing_until": null}'::jsonb);
  RETURN true;
END;
$$;

-- Hold one order's row while it is worked on, so two PCs never make two
-- invoices for it. Returns the row, or nothing if somebody else has it.
CREATE OR REPLACE FUNCTION public.xero_claim(p_order uuid, p_seconds int DEFAULT 90)
RETURNS SETOF public.xero_invoices
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  INSERT INTO public.xero_invoices AS x (order_id, claimed_until)
  VALUES (p_order, now() + make_interval(secs => p_seconds))
  ON CONFLICT (order_id) DO UPDATE
     SET claimed_until = EXCLUDED.claimed_until
   WHERE x.claimed_until IS NULL OR x.claimed_until < now()
  RETURNING *;
$$;

-- Change the given fields of an order's row.
CREATE OR REPLACE FUNCTION public.xero_invoice_put(p_order uuid, p_patch jsonb)
RETURNS SETOF public.xero_invoices
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  UPDATE public.xero_invoices x
     SET (state, invoice_id, invoice_number, contact_id, contact_name,
          lines_hash, source_md5, unpriced, total, invoice_date, terms,
          complete_wanted, completed_on, delete_wanted, error, next_try_at,
          claimed_until, approved_at, emailed_at, emailed_to)
       = (SELECT r.state, r.invoice_id, r.invoice_number, r.contact_id,
                 r.contact_name, r.lines_hash, r.source_md5, r.unpriced,
                 r.total, r.invoice_date, r.terms, r.complete_wanted,
                 r.completed_on, r.delete_wanted, r.error, r.next_try_at,
                 r.claimed_until, r.approved_at, r.emailed_at, r.emailed_to
            FROM jsonb_populate_record(x, p_patch - 'order_id') r),
         updated_at = now()
   WHERE x.order_id = p_order
  RETURNING *;
$$;

-- Invoices waiting on Xero: approve and email, or take a draft back out.
CREATE OR REPLACE FUNCTION public.xero_due_work(p_limit int DEFAULT 10)
RETURNS SETOF public.xero_invoices
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT * FROM public.xero_invoices
   WHERE (claimed_until IS NULL OR claimed_until < now())
     AND (next_try_at IS NULL OR next_try_at < now())
     AND ((complete_wanted AND state = 'draft' AND unpriced = 0
           AND invoice_id IS NOT NULL)
          OR (delete_wanted AND state IN ('waiting', 'draft')))
   ORDER BY updated_at
   LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 10), 50));
$$;

-- The recent rows, with the order each one is for, for the Xero screen.
CREATE OR REPLACE FUNCTION public.xero_list(p_limit int DEFAULT 200)
RETURNS TABLE (order_id uuid, order_number text, customer_name text,
               order_status text, state text, invoice_number text,
               contact_name text, total numeric, unpriced int,
               invoice_date date, completed_on date, error text,
               emailed_to text, updated_at timestamptz)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT x.order_id, o.order_number, o.customer_name,
         COALESCE(o.header ->> 'status', 'Pending'), x.state,
         x.invoice_number, x.contact_name, x.total, x.unpriced,
         x.invoice_date, x.completed_on, x.error, x.emailed_to, x.updated_at
    FROM public.xero_invoices x
    LEFT JOIN public.orders o ON o.id = x.order_id
   ORDER BY x.updated_at DESC
   LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 200), 1000));
$$;

DO $$
DECLARE
  f text;
BEGIN
  FOREACH f IN ARRAY ARRAY[
    'public.xero_conn_get()', 'public.xero_conn_put(jsonb)',
    'public.xero_conn_begin_refresh(int)',
    'public.xero_conn_end_refresh(text,jsonb)',
    'public.xero_claim(uuid,int)', 'public.xero_invoice_put(uuid,jsonb)',
    'public.xero_due_work(int)', 'public.xero_list(int)'] LOOP
    EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', f);
    EXECUTE format('REVOKE ALL ON FUNCTION %s FROM anon, authenticated', f);
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
      EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role', f);
    END IF;
  END LOOP;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    GRANT EXECUTE ON FUNCTION public.xero_who(uuid) TO service_role;
    GRANT ALL ON public.xero_connection TO service_role;
    GRANT ALL ON public.xero_invoices TO service_role;
  END IF;
END $$;


-- ── Optional: without any PC switched on ────────────────────────────────────
-- The app sends approvals the moment a job is completed, and every few
-- minutes after that from any PC that is open. To have completed jobs
-- invoiced even when no PC is on, have the database ask every 10 minutes
-- (pg_cron and pg_net under Database -> Extensions, and the service-role key
-- in Vault as for the daily summary - see migrate_notifications.sql):
--
--   SELECT cron.schedule('taf-xero', '*/10 * * * *', $job$
--     SELECT net.http_post(
--       url     := 'https://<your-project>.supabase.co/functions/v1/xero?do=sweep',
--       headers := jsonb_build_object(
--                    'Content-Type',  'application/json',
--                    'Authorization', 'Bearer ' || (SELECT decrypted_secret
--                                                     FROM vault.decrypted_secrets
--                                                    WHERE name = 'service_role_key')),
--       body    := '{}'::jsonb);
--   $job$);
--
-- Drafts still need a PC: pricing an order needs the price list and the
-- part-number rules, which live in the desktop app.
