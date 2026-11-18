-- ============================================================
-- TAF Order App - Asking for supplies, and the bell that says so
-- Run this in Supabase Dashboard -> SQL Editor. Safe to re-run.
--
-- Needs migrate_staff_access.sql first: it uses is_staff() and is_manager()
-- from there, and stops with a plain message if they are missing.
--
-- Somebody on the floor runs out of rivets. Until now that was a shout
-- across the factory, a note on the whiteboard, or nothing until the job
-- stopped. This is where they ask, from the desktop or from a phone, and
-- every manager is told.
--
-- Two tables, and the line between them is the point of the design.
--
-- supply_requests is what somebody asked for. Anyone on staff can ask, and
-- anyone on staff can see what has been asked - so the second person out of
-- tape sees it is already on its way instead of asking again.
--
-- notifications is who is told. Nobody writes to it from an app. A trigger
-- fans each request out to every manager, inside the database, as a
-- consequence of the request existing. If the apps could insert
-- notifications, anyone with a login could put a message in a Director's
-- bell saying anything they liked under anybody's name.
-- ============================================================

DO $$
BEGIN
    IF to_regprocedure('public.is_staff()') IS NULL
       OR to_regprocedure('public.is_manager()') IS NULL THEN
        RAISE EXCEPTION
            'Run migrate_staff_access.sql first - this uses is_staff() and '
            'is_manager() from it.';
    END IF;
END $$;


-- ── What was asked for ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.supply_requests (
    id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Rivets, Tape, Media, Mesh Wire, Channel or Other. The list lives in the
    -- apps rather than a CHECK here, so adding "Glue" next month is an app
    -- update and not a migration somebody has to remember to run.
    item              text        NOT NULL CHECK (length(trim(item)) > 0),
    -- Which tape, which grade, which depth. For "Other" it is the whole
    -- request, so it cannot be empty there.
    detail            text        NOT NULL DEFAULT '',
    -- Free text on purpose: "2 rolls", "a box", "10 lengths". Every item is
    -- counted in its own unit and a number column would get "2" and nobody
    -- would know two of what.
    quantity          text        NOT NULL DEFAULT '',
    urgent            boolean     NOT NULL DEFAULT false,
    note              text        NOT NULL DEFAULT '',
    status            text        NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open', 'ordered', 'received',
                                        'declined', 'cancelled')),
    -- Stamped by the trigger below, never taken from the app.
    requested_by      uuid        REFERENCES public.profiles(id) ON DELETE SET NULL,
    requested_by_name text        NOT NULL DEFAULT '',
    handled_by_name   text        NOT NULL DEFAULT '',
    handled_at        timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT other_says_what_it_is
        CHECK (item <> 'Other' OR length(trim(detail)) > 0)
);

CREATE INDEX IF NOT EXISTS supply_requests_open_idx
    ON public.supply_requests (created_at DESC) WHERE status = 'open';

-- Made up by the app that sent it, so sending the same request twice files
-- it once. A phone at the back of the factory sends, loses the signal before
-- the answer arrives, and sends again when it comes back. Without this that
-- is two requests for the same tape and every manager told twice.
ALTER TABLE public.supply_requests ADD COLUMN IF NOT EXISTS client_ref text;
CREATE UNIQUE INDEX IF NOT EXISTS supply_requests_client_ref_key
    ON public.supply_requests (client_ref);

ALTER TABLE public.supply_requests ENABLE ROW LEVEL SECURITY;


-- ── Who asked, written down by the database ─────────────────────────────────
-- The name on a request is the name on every manager's notification. Taking
-- it from the app would let anybody ask for things as anybody else, so the
-- app's version is thrown away and the signed-in account is written instead.

CREATE OR REPLACE FUNCTION public.stamp_supply_request()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    who text;
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT coalesce(nullif(trim(full_name), ''), nullif(trim(username), ''),
                        'Somebody')
          INTO who
          FROM public.profiles WHERE id = auth.uid();
        NEW.requested_by      := auth.uid();
        NEW.requested_by_name := coalesce(who, 'Somebody');
        NEW.status            := 'open';
        NEW.handled_by_name   := '';
        NEW.handled_at        := NULL;
        NEW.created_at        := now();
        RETURN NEW;
    END IF;

    -- An update can move a request along. It cannot rewrite who asked or
    -- when - that is the part somebody will want to check later.
    NEW.requested_by      := OLD.requested_by;
    NEW.requested_by_name := OLD.requested_by_name;
    NEW.created_at        := OLD.created_at;
    IF NEW.status IS DISTINCT FROM OLD.status THEN
        SELECT coalesce(nullif(trim(full_name), ''), nullif(trim(username), ''),
                        'Somebody')
          INTO who
          FROM public.profiles WHERE id = auth.uid();
        NEW.handled_by_name := coalesce(who, 'Somebody');
        NEW.handled_at      := now();
    ELSE
        NEW.handled_by_name := OLD.handled_by_name;
        NEW.handled_at      := OLD.handled_at;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS supply_requests_stamp ON public.supply_requests;
CREATE TRIGGER supply_requests_stamp
    BEFORE INSERT OR UPDATE ON public.supply_requests
    FOR EACH ROW EXECUTE FUNCTION public.stamp_supply_request();


-- ── Who may do what with a request ──────────────────────────────────────────

DROP POLICY IF EXISTS "Staff read supply requests"      ON public.supply_requests;
DROP POLICY IF EXISTS "Staff ask for supplies"          ON public.supply_requests;
DROP POLICY IF EXISTS "Managers handle supply requests" ON public.supply_requests;
DROP POLICY IF EXISTS "Askers change their own open request" ON public.supply_requests;

-- Everybody sees everything that has been asked for. The second person out
-- of tape should find it already on its way, not ask a second time and have
-- a manager order it twice.
CREATE POLICY "Staff read supply requests" ON public.supply_requests
    FOR SELECT TO authenticated
    USING (public.is_staff());

CREATE POLICY "Staff ask for supplies" ON public.supply_requests
    FOR INSERT TO authenticated
    WITH CHECK (public.is_staff());

-- Ordered, received, declined: a manager's call.
CREATE POLICY "Managers handle supply requests" ON public.supply_requests
    FOR UPDATE TO authenticated
    USING (public.is_manager())
    WITH CHECK (public.is_manager());

-- Whoever asked can change their mind while nothing has happened yet -
-- make it three rolls, or cancel it because the rivets turned up in the
-- other bay. Once it has been ordered it is not theirs to change.
CREATE POLICY "Askers change their own open request" ON public.supply_requests
    FOR UPDATE TO authenticated
    USING (requested_by = auth.uid() AND status = 'open')
    WITH CHECK (requested_by = auth.uid() AND status IN ('open', 'cancelled'));

-- No delete policy. A request is marked, never removed: "did anybody ask for
-- mesh wire last week" is a question somebody asks, and a row that vanished
-- cannot answer it.


-- ── Who is told ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.notifications (
    id         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    recipient  uuid        NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    -- What it is about, so an app can open the right screen when it is
    -- tapped. Only 'supply_request' today; the bell is not tied to it.
    kind       text        NOT NULL,
    ref_id     uuid,
    title      text        NOT NULL,
    body       text        NOT NULL DEFAULT '',
    read_at    timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- The bell asks one question every thirty seconds on every PC and phone:
-- how many unread are mine. This is the index that answers it.
CREATE INDEX IF NOT EXISTS notifications_unread_idx
    ON public.notifications (recipient) WHERE read_at IS NULL;
CREATE INDEX IF NOT EXISTS notifications_recent_idx
    ON public.notifications (recipient, created_at DESC);

ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "People read their own notifications"  ON public.notifications;
DROP POLICY IF EXISTS "People mark their own notifications"  ON public.notifications;

CREATE POLICY "People read their own notifications" ON public.notifications
    FOR SELECT TO authenticated
    USING (recipient = auth.uid());

CREATE POLICY "People mark their own notifications" ON public.notifications
    FOR UPDATE TO authenticated
    USING (recipient = auth.uid())
    WITH CHECK (recipient = auth.uid());

-- No insert policy, and the privilege taken away as well, so there are two
-- things in the way rather than one. The only way a row gets in is the
-- trigger below. And marking one read may change read_at and nothing else:
-- a notification that could be edited could be made to say something its
-- sender never sent.
REVOKE INSERT, DELETE ON public.notifications FROM authenticated, anon;
REVOKE UPDATE ON public.notifications FROM authenticated, anon;
GRANT  UPDATE (read_at) ON public.notifications TO authenticated;


-- ── Telling every manager ───────────────────────────────────────────────────
-- SECURITY DEFINER because it writes rows addressed to other people, which
-- nobody may do from an app. Pinned search_path so nothing in another
-- schema can stand in for the tables it writes to.

CREATE OR REPLACE FUNCTION public.notify_managers_of_supply_request()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    INSERT INTO public.notifications (recipient, kind, ref_id, title, body)
    SELECT p.id,
           'supply_request',
           NEW.id,
           CASE WHEN NEW.urgent THEN 'URGENT: ' ELSE '' END
               || NEW.item
               || CASE WHEN length(trim(NEW.detail)) > 0
                       THEN ' - ' || trim(NEW.detail) ELSE '' END,
           NEW.requested_by_name || ' asked for '
               || coalesce(nullif(trim(NEW.quantity), ''), 'some')
               || CASE WHEN length(trim(NEW.note)) > 0
                       THEN '. ' || trim(NEW.note) ELSE '' END
      FROM public.profiles p
     WHERE p.approved = true
       AND p.role IN ('Director', 'Admin', 'Manager')
       -- A manager asking for something does not need telling they asked.
       AND p.id IS DISTINCT FROM NEW.requested_by;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS supply_requests_notify ON public.supply_requests;
CREATE TRIGGER supply_requests_notify
    AFTER INSERT ON public.supply_requests
    FOR EACH ROW EXECUTE FUNCTION public.notify_managers_of_supply_request();


-- ── Settled by one manager means settled for all of them ────────────────────
-- Four managers are told about the same roll of tape. One orders it. Left
-- alone, the other three still have a red 1 on their bell for a job that is
-- done - and the likeliest thing any of them does next is order it again.
-- So once a request stops being open, everyone's notification for it is
-- marked read.

CREATE OR REPLACE FUNCTION public.settle_supply_notifications()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF OLD.status = 'open' AND NEW.status <> 'open' THEN
        UPDATE public.notifications
           SET read_at = now()
         WHERE kind = 'supply_request'
           AND ref_id = NEW.id
           AND read_at IS NULL;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS supply_requests_settle ON public.supply_requests;
CREATE TRIGGER supply_requests_settle
    AFTER UPDATE OF status ON public.supply_requests
    FOR EACH ROW EXECUTE FUNCTION public.settle_supply_notifications();


-- ── The one way in ──────────────────────────────────────────────────────────
-- Both apps ask through this rather than inserting, so there is a single
-- place where "sent twice" becomes "filed once". Invoker, not definer: it
-- runs as whoever is asking, so the insert policy above still decides
-- whether they may, and the trigger still writes who they are.

CREATE OR REPLACE FUNCTION public.request_supply(
    p_item       text,
    p_detail     text    DEFAULT '',
    p_quantity   text    DEFAULT '',
    p_urgent     boolean DEFAULT false,
    p_note       text    DEFAULT '',
    p_client_ref text    DEFAULT NULL)
RETURNS public.supply_requests
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    r public.supply_requests;
BEGIN
    IF p_client_ref IS NOT NULL THEN
        SELECT * INTO r FROM public.supply_requests
         WHERE client_ref = p_client_ref;
        IF FOUND THEN
            RETURN r;            -- already filed; this is the retry
        END IF;
    END IF;

    INSERT INTO public.supply_requests
           (item, detail, quantity, urgent, note, client_ref)
    VALUES (coalesce(p_item, ''), coalesce(p_detail, ''),
            coalesce(p_quantity, ''), coalesce(p_urgent, false),
            coalesce(p_note, ''), p_client_ref)
    ON CONFLICT (client_ref) DO NOTHING
    RETURNING * INTO r;

    -- Two copies arriving at the same instant: the other one won the race,
    -- and this one hands back what it filed.
    IF r.id IS NULL THEN
        SELECT * INTO r FROM public.supply_requests
         WHERE client_ref = p_client_ref;
    END IF;
    RETURN r;
END;
$$;

REVOKE ALL ON FUNCTION public.request_supply(text, text, text, boolean, text, text)
    FROM public, anon;
GRANT EXECUTE ON FUNCTION public.request_supply(text, text, text, boolean, text, text)
    TO authenticated;


-- ── What the bell asks ──────────────────────────────────────────────────────
-- Invoker, not definer: they run as the person asking, so row-level security
-- confines both to that person's own notifications without either function
-- having to be trusted to check.

CREATE OR REPLACE FUNCTION public.my_unread_count()
RETURNS integer
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
    SELECT count(*)::integer
      FROM public.notifications
     WHERE recipient = auth.uid()
       AND read_at IS NULL;
$$;

-- Null ids means all of them.
CREATE OR REPLACE FUNCTION public.mark_notifications_read(p_ids uuid[] DEFAULT NULL)
RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    n integer;
BEGIN
    UPDATE public.notifications
       SET read_at = now()
     WHERE recipient = auth.uid()
       AND read_at IS NULL
       AND (p_ids IS NULL OR id = ANY (p_ids));
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END;
$$;

REVOKE ALL ON FUNCTION public.my_unread_count()                FROM public, anon;
REVOKE ALL ON FUNCTION public.mark_notifications_read(uuid[])  FROM public, anon;
GRANT EXECUTE ON FUNCTION public.my_unread_count()               TO authenticated;
GRANT EXECUTE ON FUNCTION public.mark_notifications_read(uuid[]) TO authenticated;

-- The trigger functions are called by the table, never by a person.
REVOKE ALL ON FUNCTION public.stamp_supply_request()               FROM public, anon, authenticated;
REVOKE ALL ON FUNCTION public.notify_managers_of_supply_request()  FROM public, anon, authenticated;
REVOKE ALL ON FUNCTION public.settle_supply_notifications()        FROM public, anon, authenticated;
