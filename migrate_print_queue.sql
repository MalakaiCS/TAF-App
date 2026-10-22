-- ============================================================================
-- Step 53: printing on the work printers from anywhere
--
-- The printers stay where they are, on the workshop's network, and nothing
-- on the internet can reach them. Instead one PC at work - left on, with the
-- app open and "This PC prints for everybody" ticked in Settings - is the
-- print station. Somebody at home, on the road or on their phone sends a
-- job; it waits here; the station picks it up within a few seconds, prints
-- it on the printer they picked and says so.
--
--   print_stations   the PCs at work that print, and the printers each has
--   print_jobs       what is waiting, printing, printed or failed
--   print-jobs       (Storage, private) the files sent to print
--
-- Only somebody on staff, signed in to the app, can send anything. Making a
-- PC a print station is a manager's decision; once it is one, whoever is
-- signed in on it keeps it going. A job is only ever touched by the RPCs
-- below, so two stations can never print the same job.
--
-- Needs migrate_staff_access.sql. Safe to run more than once.
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.print_stations (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name            text        NOT NULL UNIQUE CHECK (length(btrim(name)) > 0),
    printers        text[]      NOT NULL DEFAULT '{}',
    default_printer text        NOT NULL DEFAULT '',
    enabled         boolean     NOT NULL DEFAULT true,
    last_seen       timestamptz NOT NULL DEFAULT now(),
    created_by      uuid        DEFAULT auth.uid(),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.print_jobs (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at  timestamptz NOT NULL DEFAULT now(),
    created_by  uuid        NOT NULL DEFAULT auth.uid(),
    sent_by     text        NOT NULL DEFAULT '',
    title       text        NOT NULL DEFAULT '',
    -- file: a PDF or photo in the print-jobs bucket.
    -- order: an order's worksheets, built by the station itself - what the
    --        phone sends, since a phone cannot make a worksheet.
    kind        text        NOT NULL DEFAULT 'file'
                CHECK (kind IN ('file', 'order')),
    file_path   text,
    order_id    uuid,
    -- Which station and printer; empty means whichever station is on, and
    -- that station's own default printer.
    station_id  uuid REFERENCES public.print_stations(id) ON DELETE SET NULL,
    printer     text        NOT NULL DEFAULT '',
    copies      integer     NOT NULL DEFAULT 1 CHECK (copies BETWEEN 1 AND 20),
    status      text        NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'printing', 'printed', 'failed',
                                  'cancelled')),
    claimed_by  uuid REFERENCES public.print_stations(id) ON DELETE SET NULL,
    claimed_at  timestamptz,
    finished_at timestamptz,
    error       text        NOT NULL DEFAULT '',
    CHECK ((kind = 'file' AND file_path IS NOT NULL AND length(file_path) > 0)
        OR (kind = 'order' AND order_id IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS print_jobs_waiting
    ON public.print_jobs (created_at) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS print_jobs_mine
    ON public.print_jobs (created_by, created_at DESC);

ALTER TABLE public.print_stations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.print_jobs     ENABLE ROW LEVEL SECURITY;

-- Everybody on staff sees the stations (to pick a printer); only a manager
-- turns one off or removes it. They are made and kept up by print_station_checkin.
DROP POLICY IF EXISTS "Staff see print stations"      ON public.print_stations;
DROP POLICY IF EXISTS "Managers change print stations" ON public.print_stations;
DROP POLICY IF EXISTS "Managers remove print stations" ON public.print_stations;
CREATE POLICY "Staff see print stations" ON public.print_stations FOR SELECT
    TO authenticated USING (public.is_staff());
CREATE POLICY "Managers change print stations" ON public.print_stations FOR UPDATE
    TO authenticated USING (public.is_manager()) WITH CHECK (public.is_manager());
CREATE POLICY "Managers remove print stations" ON public.print_stations FOR DELETE
    TO authenticated USING (public.is_manager());

-- Your own jobs; a manager sees everybody's. Sending one is an insert of a
-- job that is yours and waiting - nothing else. Everything after that is the
-- RPCs below.
DROP POLICY IF EXISTS "Staff see their print jobs" ON public.print_jobs;
DROP POLICY IF EXISTS "Staff send print jobs"      ON public.print_jobs;
CREATE POLICY "Staff see their print jobs" ON public.print_jobs FOR SELECT
    TO authenticated
    USING (public.is_staff() AND (created_by = auth.uid() OR public.is_manager()));
CREATE POLICY "Staff send print jobs" ON public.print_jobs FOR INSERT
    TO authenticated
    WITH CHECK (public.is_staff() AND created_by = auth.uid()
                AND status = 'queued' AND claimed_by IS NULL
                AND claimed_at IS NULL AND finished_at IS NULL);


-- ── A station says it is here, and what it can print on ────────────────────
-- Called when "This PC prints for everybody" is ticked and every minute
-- after. A new station needs a manager; an existing one keeps going under
-- whoever is signed in on that PC. A station a manager has turned off stays
-- off. Returns the station's id.

CREATE OR REPLACE FUNCTION public.print_station_checkin(
    p_name text, p_printers text[], p_default text)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    sid uuid;
    on_ boolean;
BEGIN
    IF NOT public.is_staff() THEN
        RAISE EXCEPTION 'Only staff can run a print station.';
    END IF;
    IF p_name IS NULL OR length(btrim(p_name)) = 0 THEN
        RAISE EXCEPTION 'A print station needs a name.';
    END IF;
    SELECT id, enabled INTO sid, on_ FROM public.print_stations
     WHERE name = btrim(p_name);
    IF sid IS NULL THEN
        IF NOT public.is_manager() THEN
            RAISE EXCEPTION 'Only a manager can make a PC a print station.';
        END IF;
        INSERT INTO public.print_stations (name, printers, default_printer)
        VALUES (btrim(p_name), COALESCE(p_printers, '{}'), COALESCE(p_default, ''))
        RETURNING id INTO sid;
        RETURN sid;
    END IF;
    IF NOT on_ THEN
        RAISE EXCEPTION 'This print station has been turned off by a manager.';
    END IF;
    UPDATE public.print_stations
       SET printers = COALESCE(p_printers, '{}'),
           default_printer = COALESCE(p_default, ''),
           last_seen = now()
     WHERE id = sid;
    RETURN sid;
END;
$$;


-- ── The station takes the next job ─────────────────────────────────────────
-- The oldest job waiting for this station or for any station, marked as
-- printing in the same statement, so a second station asking at the same
-- moment gets the next one. Also tidies up on the way: a job left printing
-- for 15 minutes (the station was switched off mid-job) is failed rather
-- than printed twice, and one nobody has printed in 7 days is let go.

CREATE OR REPLACE FUNCTION public.claim_print_job(p_station uuid)
RETURNS SETOF public.print_jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    jid uuid;
BEGIN
    IF NOT public.is_staff() THEN
        RAISE EXCEPTION 'Only staff can run a print station.';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.print_stations
                    WHERE id = p_station AND enabled) THEN
        RAISE EXCEPTION 'This print station has been turned off by a manager.';
    END IF;
    UPDATE public.print_stations SET last_seen = now() WHERE id = p_station;

    UPDATE public.print_jobs
       SET status = 'failed', finished_at = now(),
           error = 'The print station stopped while printing this. Send it again.'
     WHERE status = 'printing' AND claimed_at < now() - interval '15 minutes';
    UPDATE public.print_jobs
       SET status = 'failed', finished_at = now(),
           error = 'No print station was on to print this within 7 days.'
     WHERE status = 'queued' AND created_at < now() - interval '7 days';

    SELECT id INTO jid FROM public.print_jobs
     WHERE status = 'queued'
       AND (station_id IS NULL OR station_id = p_station)
     ORDER BY created_at
     LIMIT 1
     FOR UPDATE SKIP LOCKED;
    IF jid IS NULL THEN
        RETURN;
    END IF;
    RETURN QUERY
    UPDATE public.print_jobs
       SET status = 'printing', claimed_by = p_station, claimed_at = now()
     WHERE id = jid
    RETURNING *;
END;
$$;


-- ── The station says how it went ───────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.finish_print_job(
    p_id uuid, p_station uuid, p_ok boolean, p_error text DEFAULT '')
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF NOT public.is_staff() THEN
        RAISE EXCEPTION 'Only staff can run a print station.';
    END IF;
    UPDATE public.print_jobs
       SET status = CASE WHEN p_ok THEN 'printed' ELSE 'failed' END,
           finished_at = now(),
           error = CASE WHEN p_ok THEN '' ELSE left(COALESCE(p_error, ''), 500) END
     WHERE id = p_id AND claimed_by = p_station AND status = 'printing';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'That job is not this station''s to finish.';
    END IF;
END;
$$;


-- ── Changing your mind ─────────────────────────────────────────────────────
-- Your own job, or anybody's for a manager, while it is still waiting.

CREATE OR REPLACE FUNCTION public.cancel_print_job(p_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF NOT public.is_staff() THEN
        RAISE EXCEPTION 'Only staff can cancel a print job.';
    END IF;
    UPDATE public.print_jobs
       SET status = 'cancelled', finished_at = now()
     WHERE id = p_id AND status = 'queued'
       AND (created_by = auth.uid() OR public.is_manager());
    IF NOT FOUND THEN
        RAISE EXCEPTION 'That job has already started printing, or is not yours.';
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION public.print_station_checkin(text, text[], text) FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION public.claim_print_job(uuid) FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION public.finish_print_job(uuid, uuid, boolean, text) FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION public.cancel_print_job(uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.print_station_checkin(text, text[], text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.claim_print_job(uuid) TO authenticated;
GRANT EXECUTE ON FUNCTION public.finish_print_job(uuid, uuid, boolean, text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.cancel_print_job(uuid) TO authenticated;


-- ── The files ──────────────────────────────────────────────────────────────
-- Private: an invoice or a worksheet is nobody else's business. PDFs,
-- photos, and Word, Excel and text files, 25 MB at most. Each sender puts theirs in a folder named
-- after themselves; the station, signed in as anybody on staff, reads and
-- removes them once printed.

DO $$
BEGIN
  -- A database without Supabase Storage (a test one) has no buckets.
  IF to_regclass('storage.buckets') IS NULL THEN
    RETURN;
  END IF;
  INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
  VALUES ('print-jobs', 'print-jobs', false, 26214400,
          ARRAY['application/pdf', 'image/jpeg', 'image/png', 'text/plain',
                'application/msword',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'application/vnd.ms-excel',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'])
  ON CONFLICT (id) DO UPDATE
     SET public = false, file_size_limit = 26214400,
         allowed_mime_types = ARRAY['application/pdf', 'image/jpeg', 'image/png', 'text/plain',
                'application/msword',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'application/vnd.ms-excel',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'];

  EXECUTE 'DROP POLICY IF EXISTS "Staff send files to print" ON storage.objects';
  EXECUTE 'DROP POLICY IF EXISTS "Staff read files to print" ON storage.objects';
  EXECUTE 'DROP POLICY IF EXISTS "Staff remove printed files" ON storage.objects';
  EXECUTE 'CREATE POLICY "Staff send files to print" ON storage.objects
             FOR INSERT TO authenticated
             WITH CHECK (bucket_id = ''print-jobs'' AND public.is_staff()
                         AND (storage.foldername(name))[1] = auth.uid()::text)';
  EXECUTE 'CREATE POLICY "Staff read files to print" ON storage.objects
             FOR SELECT TO authenticated
             USING (bucket_id = ''print-jobs'' AND public.is_staff())';
  EXECUTE 'CREATE POLICY "Staff remove printed files" ON storage.objects
             FOR DELETE TO authenticated
             USING (bucket_id = ''print-jobs'' AND public.is_staff())';
END $$;
