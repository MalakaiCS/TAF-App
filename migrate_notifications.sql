-- ============================================================
-- TAF Order App - Being told, rather than going to look
-- Run this in Supabase Dashboard -> SQL Editor. Safe to re-run.
--
-- Everything the app knows about what is late, what is due today and what is
-- nearly out of stock is already on the Dashboard. The trouble with a
-- Dashboard is that it only says anything to somebody who opens it, and the
-- morning it matters most is the morning nobody did.
--
-- So: a short summary, once a day, by email. Per person and off by default -
-- nobody wants a system that starts mailing the whole company the day it is
-- installed - with the same company-wide master switch the customer emails
-- have, so one person cannot turn the whole thing on for everybody.
--
-- The sending is done by the `daily-summary` Edge Function, which holds the
-- mail provider's key as a function secret. This file is only the record of
-- who wants one.
-- ============================================================

CREATE TABLE IF NOT EXISTS public.notify_settings (
    user_id       uuid PRIMARY KEY
                       REFERENCES auth.users(id) ON DELETE CASCADE,
    daily_summary boolean     NOT NULL DEFAULT false,
    updated_at    timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.notify_settings ENABLE ROW LEVEL SECURITY;

-- Yours to set, and nobody else's. A row here decides where mail is sent, so
-- being able to write somebody else's would be being able to sign them up.

DROP POLICY IF EXISTS "Read my notify settings"    ON public.notify_settings;
DROP POLICY IF EXISTS "Write my notify settings"   ON public.notify_settings;
DROP POLICY IF EXISTS "Change my notify settings"  ON public.notify_settings;
DROP POLICY IF EXISTS "Managers see who is on"     ON public.notify_settings;

CREATE POLICY "Read my notify settings"
    ON public.notify_settings FOR SELECT TO authenticated
    USING (user_id = auth.uid());

CREATE POLICY "Write my notify settings"
    ON public.notify_settings FOR INSERT TO authenticated
    WITH CHECK (user_id = auth.uid());

CREATE POLICY "Change my notify settings"
    ON public.notify_settings FOR UPDATE TO authenticated
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- Read-only, and only so somebody can answer "who is getting these?" without
-- guessing. Deliberately not an UPDATE policy: a manager who thinks you
-- should be getting the summary can ask you.
CREATE POLICY "Managers see who is on"
    ON public.notify_settings FOR SELECT TO authenticated
    USING (public.is_manager());


-- ── One person's own switch ─────────────────────────────────────────────────
-- Upsert by hand is three round trips and a race between two devices. This
-- is one statement, and it can only ever write the caller's own row - the
-- user id is taken from the session, not from an argument, so there is
-- nothing to pass in wrongly or on purpose.

CREATE OR REPLACE FUNCTION public.set_my_daily_summary(p_on boolean)
RETURNS boolean
LANGUAGE sql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
    INSERT INTO public.notify_settings (user_id, daily_summary, updated_at)
    VALUES (auth.uid(), COALESCE(p_on, false), now())
    ON CONFLICT (user_id) DO UPDATE
        SET daily_summary = COALESCE(p_on, false),
            updated_at    = now()
    RETURNING daily_summary;
$$;

REVOKE ALL ON FUNCTION public.set_my_daily_summary(boolean) FROM public;
GRANT EXECUTE ON FUNCTION public.set_my_daily_summary(boolean) TO authenticated;


-- ── Sending it every morning ────────────────────────────────────────────────
--
-- Optional, and left to be done by hand on purpose. The summary can be sent
-- from the app at any time - "Send mine now" under Settings - so the feature
-- works the moment the function is deployed. What follows only automates it.
--
-- It needs the pg_cron and pg_net extensions, both a switch in
-- Database -> Extensions, and the service-role key, which must be put in
-- Vault rather than typed into a SQL file that lives in a public repository.
--
--   1. Database -> Extensions: enable pg_cron and pg_net.
--   2. Add the key to Vault, once:
--        SELECT vault.create_secret('<service-role key>', 'service_role_key');
--   3. Then schedule it - 7am Brisbane is 21:00 UTC the day before, and
--      Queensland has no daylight saving, so this one line stays right all
--      year:
--
--   SELECT cron.schedule('taf-daily-summary', '0 21 * * 0-4', $job$
--     SELECT net.http_post(
--       url     := 'https://<your-project>.supabase.co/functions/v1/daily-summary',
--       headers := jsonb_build_object(
--                    'Content-Type',  'application/json',
--                    'Authorization', 'Bearer ' || (SELECT decrypted_secret
--                                                     FROM vault.decrypted_secrets
--                                                    WHERE name = 'service_role_key')),
--       body    := '{"everyone": true}'::jsonb);
--   $job$);
--
-- Sunday to Thursday UTC is Monday to Friday here. To stop it again:
--   SELECT cron.unschedule('taf-daily-summary');
