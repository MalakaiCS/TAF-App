-- ============================================================================
-- Step 49: how we do things, and talking to each other
--
--   sops            the how-to library: a procedure per job (or filter type),
--                   with words, a video link and a file - and a new version
--                   every time it changes
--   sop_reads       who has read which version ("I've read this")
--   chat_rules      who may do what: post on the noticeboard, pin, start a
--                   group, take down anybody's message - each a minimum role,
--                   changed by a director or admin
--   chat_channels   the noticeboard (one, everybody sees it) and group chats
--                   (only their members see them)
--   chat_members    who is in each group
--   chat_messages   what was said; pinned and removed only through the
--                   functions below, which hold the rules
--   chat_reads      where each person is up to, for the unread counts
--
-- Behind switches that start off (Settings -> Features). Needs
-- migrate_staff_access.sql and migrate_features.sql (is_admin). Safe to run
-- more than once.
-- ============================================================================

DO $$
BEGIN
  IF to_regprocedure('public.is_staff()') IS NULL THEN
    RAISE EXCEPTION 'Run migrate_staff_access.sql first.';
  END IF;
  IF to_regprocedure('public.is_admin()') IS NULL THEN
    RAISE EXCEPTION 'Run migrate_features.sql first.';
  END IF;
END $$;


-- ── Ranks ───────────────────────────────────────────────────────────────────
-- The same ladder as the apps (db.ROLE_LEVEL): a Director and an Admin are
-- level with each other, above a Manager, above everybody else.

CREATE OR REPLACE FUNCTION public.role_rank(p_role text)
RETURNS integer
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE p_role WHEN 'Employee' THEN 1 WHEN 'Manager' THEN 3
                     WHEN 'Admin' THEN 4 WHEN 'Director' THEN 4 ELSE 0 END;
$$;

CREATE OR REPLACE FUNCTION public.my_rank()
RETURNS integer
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT COALESCE((SELECT public.role_rank(role) FROM public.profiles
                    WHERE id = auth.uid() AND approved = true), 0);
$$;

REVOKE ALL ON FUNCTION public.my_rank() FROM public;
GRANT EXECUTE ON FUNCTION public.my_rank() TO authenticated;


-- ── The how-to library ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.sops (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title       text        NOT NULL,
    category    text        NOT NULL DEFAULT '',
    -- When it is how to make one type of filter, the type, so the line on an
    -- order can offer it.
    filter_type text        NOT NULL DEFAULT '',
    body        text        NOT NULL DEFAULT '',
    video_url   text        NOT NULL DEFAULT '',
    file_path   text        NOT NULL DEFAULT '',
    version     integer     NOT NULL DEFAULT 1,
    archived    boolean     NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    updated_by  text        NOT NULL DEFAULT '',
    CHECK (length(btrim(title)) > 0),
    CHECK (video_url = '' OR video_url ~* '^https?://')
);

ALTER TABLE public.sops ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Staff read sops"     ON public.sops;
DROP POLICY IF EXISTS "Managers write sops" ON public.sops;
CREATE POLICY "Staff read sops" ON public.sops FOR SELECT
    TO authenticated USING (public.is_staff());
CREATE POLICY "Managers write sops" ON public.sops FOR ALL
    TO authenticated USING (public.is_manager()) WITH CHECK (public.is_manager());

-- A change to what it says is a new version, so "read" means read this one.
CREATE OR REPLACE FUNCTION public.sop_changed()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF (NEW.title, NEW.body, NEW.video_url, NEW.file_path)
       IS DISTINCT FROM (OLD.title, OLD.body, OLD.video_url, OLD.file_path) THEN
        NEW.version := OLD.version + 1;
    ELSE
        NEW.version := OLD.version;
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS sops_changed ON public.sops;
CREATE TRIGGER sops_changed BEFORE UPDATE ON public.sops
    FOR EACH ROW EXECUTE FUNCTION public.sop_changed();

CREATE TABLE IF NOT EXISTS public.sop_reads (
    sop_id  uuid        NOT NULL REFERENCES public.sops(id) ON DELETE CASCADE,
    user_id uuid        NOT NULL,
    person  text        NOT NULL DEFAULT '',
    version integer     NOT NULL,
    read_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (sop_id, user_id)
);

ALTER TABLE public.sop_reads ENABLE ROW LEVEL SECURITY;

-- Your own, or everybody's for a manager. Written only by read_sop(), which
-- puts the version that is there now - not one somebody says they read.
DROP POLICY IF EXISTS "Read own or managers read all" ON public.sop_reads;
CREATE POLICY "Read own or managers read all" ON public.sop_reads FOR SELECT
    TO authenticated USING (user_id = auth.uid() OR public.is_manager());

CREATE OR REPLACE FUNCTION public.read_sop(p_id uuid)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v integer;
    who text;
BEGIN
    IF NOT public.is_staff() THEN
        RAISE EXCEPTION 'Only staff can sign off a how-to.';
    END IF;
    SELECT version INTO v FROM public.sops WHERE id = p_id AND NOT archived;
    IF v IS NULL THEN
        RAISE EXCEPTION 'That how-to is not there any more.';
    END IF;
    SELECT COALESCE(NULLIF(full_name, ''), username, '') INTO who
      FROM public.profiles WHERE id = auth.uid();
    INSERT INTO public.sop_reads (sop_id, user_id, person, version, read_at)
    VALUES (p_id, auth.uid(), COALESCE(who, ''), v, now())
    ON CONFLICT (sop_id, user_id) DO UPDATE
       SET version = EXCLUDED.version, read_at = now(), person = EXCLUDED.person;
    RETURN v;
END;
$$;

REVOKE ALL ON FUNCTION public.read_sop(uuid) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.read_sop(uuid) TO authenticated;

-- A private bucket for the files: staff read them through a signed link,
-- managers put them there.
DO $$
BEGIN
  IF to_regclass('storage.buckets') IS NULL THEN
    RAISE NOTICE 'No Storage here - files on how-tos will not upload.';
    RETURN;
  END IF;
  INSERT INTO storage.buckets (id, name, public) VALUES ('sops', 'sops', false)
  ON CONFLICT (id) DO NOTHING;
  EXECUTE 'DROP POLICY IF EXISTS "Staff read sop files" ON storage.objects';
  EXECUTE 'DROP POLICY IF EXISTS "Managers add sop files" ON storage.objects';
  EXECUTE 'DROP POLICY IF EXISTS "Managers remove sop files" ON storage.objects';
  EXECUTE 'CREATE POLICY "Staff read sop files" ON storage.objects FOR SELECT '
       || 'TO authenticated USING (bucket_id = ''sops'' AND public.is_staff())';
  EXECUTE 'CREATE POLICY "Managers add sop files" ON storage.objects FOR INSERT '
       || 'TO authenticated WITH CHECK (bucket_id = ''sops'' AND public.is_manager())';
  EXECUTE 'CREATE POLICY "Managers remove sop files" ON storage.objects FOR DELETE '
       || 'TO authenticated USING (bucket_id = ''sops'' AND public.is_manager())';
END $$;


-- ── Who may do what ─────────────────────────────────────────────────────────
-- Each a minimum role. Out of the box: managers and above post on the
-- noticeboard and start groups; directors and admins pin and take down
-- anybody's message. A director or admin changes them.

CREATE TABLE IF NOT EXISTS public.chat_rules (
    action     text PRIMARY KEY,
    min_role   text        NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text        NOT NULL DEFAULT '',
    CHECK (action IN ('post_board', 'pin', 'make_group', 'remove_any')),
    CHECK (min_role IN ('Employee', 'Manager', 'Admin'))
);

INSERT INTO public.chat_rules (action, min_role) VALUES
    ('post_board', 'Manager'), ('pin', 'Admin'),
    ('make_group', 'Manager'), ('remove_any', 'Admin')
ON CONFLICT (action) DO NOTHING;

ALTER TABLE public.chat_rules ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Staff read chat rules"   ON public.chat_rules;
DROP POLICY IF EXISTS "Admins change chat rules" ON public.chat_rules;
CREATE POLICY "Staff read chat rules" ON public.chat_rules FOR SELECT
    TO authenticated USING (public.is_staff());
CREATE POLICY "Admins change chat rules" ON public.chat_rules FOR UPDATE
    TO authenticated USING (public.is_admin()) WITH CHECK (public.is_admin());

CREATE OR REPLACE FUNCTION public.chat_may(p_action text)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT public.my_rank() > 0
     AND public.my_rank() >= public.role_rank(
           COALESCE((SELECT min_role FROM public.chat_rules WHERE action = p_action),
                    'Admin'));
$$;

REVOKE ALL ON FUNCTION public.chat_may(text) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.chat_may(text) TO authenticated;


-- ── The noticeboard and the groups ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.chat_channels (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name          text        NOT NULL,
    kind          text        NOT NULL DEFAULT 'group',
    -- Within a group, the least role that may post (everyone, by default).
    post_min_role text        NOT NULL DEFAULT 'Employee',
    created_by    uuid,
    created_at    timestamptz NOT NULL DEFAULT now(),
    archived      boolean     NOT NULL DEFAULT false,
    CHECK (kind IN ('board', 'group')),
    CHECK (post_min_role IN ('Employee', 'Manager', 'Admin')),
    CHECK (length(btrim(name)) > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS chat_one_board
    ON public.chat_channels (kind) WHERE kind = 'board';

INSERT INTO public.chat_channels (name, kind)
SELECT 'Noticeboard', 'board'
 WHERE NOT EXISTS (SELECT 1 FROM public.chat_channels WHERE kind = 'board');

CREATE TABLE IF NOT EXISTS public.chat_members (
    channel_id uuid        NOT NULL REFERENCES public.chat_channels(id) ON DELETE CASCADE,
    user_id    uuid        NOT NULL,
    added_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (channel_id, user_id)
);

CREATE TABLE IF NOT EXISTS public.chat_messages (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_id uuid        NOT NULL REFERENCES public.chat_channels(id) ON DELETE CASCADE,
    user_id    uuid        NOT NULL DEFAULT auth.uid(),
    author     text        NOT NULL DEFAULT '',
    body       text        NOT NULL,
    pinned     boolean     NOT NULL DEFAULT false,
    pinned_by  text        NOT NULL DEFAULT '',
    pinned_at  timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    removed_at timestamptz,
    removed_by text        NOT NULL DEFAULT '',
    CHECK (length(body) <= 4000)
);

CREATE INDEX IF NOT EXISTS chat_messages_by_channel
    ON public.chat_messages (channel_id, created_at);

CREATE TABLE IF NOT EXISTS public.chat_reads (
    channel_id   uuid        NOT NULL REFERENCES public.chat_channels(id) ON DELETE CASCADE,
    user_id      uuid        NOT NULL DEFAULT auth.uid(),
    last_read_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (channel_id, user_id)
);

-- Who can see a channel: everybody on staff the noticeboard, a group's
-- members theirs. Who can post in it: the noticeboard by the rule, a group
-- by its own least role - members only, and nothing archived.
CREATE OR REPLACE FUNCTION public.chat_can_see(p_channel uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT public.is_staff() AND EXISTS (
    SELECT 1 FROM public.chat_channels c
     WHERE c.id = p_channel
       AND (c.kind = 'board' OR EXISTS (
             SELECT 1 FROM public.chat_members m
              WHERE m.channel_id = c.id AND m.user_id = auth.uid())));
$$;

CREATE OR REPLACE FUNCTION public.chat_can_post(p_channel uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT public.chat_can_see(p_channel) AND EXISTS (
    SELECT 1 FROM public.chat_channels c
     WHERE c.id = p_channel AND NOT c.archived
       AND CASE WHEN c.kind = 'board' THEN public.chat_may('post_board')
                ELSE public.my_rank() >= public.role_rank(c.post_min_role) END);
$$;

REVOKE ALL ON FUNCTION public.chat_can_see(uuid)  FROM public, anon;
REVOKE ALL ON FUNCTION public.chat_can_post(uuid) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.chat_can_see(uuid)  TO authenticated;
GRANT EXECUTE ON FUNCTION public.chat_can_post(uuid) TO authenticated;

ALTER TABLE public.chat_channels ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_members  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_reads    ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "See your channels"         ON public.chat_channels;
DROP POLICY IF EXISTS "See your groups' members"  ON public.chat_members;
DROP POLICY IF EXISTS "Read what you can see"     ON public.chat_messages;
DROP POLICY IF EXISTS "Post where you may"        ON public.chat_messages;
DROP POLICY IF EXISTS "Your own place"            ON public.chat_reads;
CREATE POLICY "See your channels" ON public.chat_channels FOR SELECT
    TO authenticated USING (public.chat_can_see(id));
CREATE POLICY "See your groups' members" ON public.chat_members FOR SELECT
    TO authenticated USING (public.chat_can_see(channel_id));
CREATE POLICY "Read what you can see" ON public.chat_messages FOR SELECT
    TO authenticated USING (public.chat_can_see(channel_id));
-- Posting is as yourself, unpinned, where you may. Nothing is changed or
-- deleted directly: pinning and taking down go through the functions.
CREATE POLICY "Post where you may" ON public.chat_messages FOR INSERT
    TO authenticated WITH CHECK (
        user_id = auth.uid() AND public.chat_can_post(channel_id)
        AND NOT pinned AND removed_at IS NULL AND length(btrim(body)) > 0);
CREATE POLICY "Your own place" ON public.chat_reads FOR ALL
    TO authenticated USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid() AND public.chat_can_see(channel_id));

-- The name on a message is the poster's, whatever the app sent.
CREATE OR REPLACE FUNCTION public.chat_message_author()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    SELECT COALESCE(NULLIF(full_name, ''), username, '') INTO NEW.author
      FROM public.profiles WHERE id = NEW.user_id;
    NEW.author := COALESCE(NEW.author, '');
    NEW.created_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS chat_messages_author ON public.chat_messages;
CREATE TRIGGER chat_messages_author BEFORE INSERT ON public.chat_messages
    FOR EACH ROW EXECUTE FUNCTION public.chat_message_author();


-- ── What can be done, by the rules ──────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.make_group(p_name text, p_members uuid[],
                                             p_post_min_role text DEFAULT 'Employee')
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    gid uuid;
BEGIN
    IF NOT public.chat_may('make_group') THEN
        RAISE EXCEPTION 'You cannot start a group.';
    END IF;
    INSERT INTO public.chat_channels (name, kind, post_min_role, created_by)
    VALUES (btrim(p_name), 'group', COALESCE(p_post_min_role, 'Employee'), auth.uid())
    RETURNING id INTO gid;
    -- The person starting it, and everybody named who is approved staff.
    INSERT INTO public.chat_members (channel_id, user_id)
    SELECT gid, p.id FROM public.profiles p
     WHERE p.approved AND (p.id = auth.uid() OR p.id = ANY (COALESCE(p_members, '{}')))
    ON CONFLICT DO NOTHING;
    RETURN gid;
END;
$$;

-- Who is in a group: changed by whoever started it, or a director or admin.
CREATE OR REPLACE FUNCTION public.set_group_members(p_channel uuid, p_members uuid[])
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    c public.chat_channels%ROWTYPE;
    n integer;
BEGIN
    SELECT * INTO c FROM public.chat_channels WHERE id = p_channel;
    IF c.id IS NULL OR c.kind <> 'group' THEN
        RAISE EXCEPTION 'That is not a group.';
    END IF;
    IF NOT (public.is_staff() AND (c.created_by = auth.uid() OR public.is_admin())) THEN
        RAISE EXCEPTION 'Only whoever started the group, or an admin, can change who is in it.';
    END IF;
    DELETE FROM public.chat_members
     WHERE channel_id = c.id AND user_id <> ALL (COALESCE(p_members, '{}'))
       AND user_id IS DISTINCT FROM c.created_by;
    INSERT INTO public.chat_members (channel_id, user_id)
    SELECT c.id, p.id FROM public.profiles p
     WHERE p.approved AND p.id = ANY (COALESCE(p_members, '{}'))
    ON CONFLICT DO NOTHING;
    SELECT count(*) INTO n FROM public.chat_members WHERE channel_id = c.id;
    RETURN n;
END;
$$;

CREATE OR REPLACE FUNCTION public.leave_group(p_channel uuid)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    DELETE FROM public.chat_members
     WHERE channel_id = p_channel AND user_id = auth.uid()
       AND EXISTS (SELECT 1 FROM public.chat_channels
                    WHERE id = p_channel AND kind = 'group');
$$;

CREATE OR REPLACE FUNCTION public.pin_message(p_id uuid, p_on boolean DEFAULT true)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    m public.chat_messages%ROWTYPE;
    who text;
BEGIN
    SELECT * INTO m FROM public.chat_messages WHERE id = p_id;
    IF m.id IS NULL OR NOT public.chat_can_see(m.channel_id) THEN
        RAISE EXCEPTION 'That message is not there.';
    END IF;
    IF NOT public.chat_may('pin') THEN
        RAISE EXCEPTION 'You cannot pin messages.';
    END IF;
    IF m.removed_at IS NOT NULL THEN
        RAISE EXCEPTION 'That message was taken down.';
    END IF;
    SELECT COALESCE(NULLIF(full_name, ''), username, '') INTO who
      FROM public.profiles WHERE id = auth.uid();
    UPDATE public.chat_messages
       SET pinned = p_on,
           pinned_by = CASE WHEN p_on THEN COALESCE(who, '') ELSE '' END,
           pinned_at = CASE WHEN p_on THEN now() END
     WHERE id = p_id;
    RETURN p_on;
END;
$$;

CREATE OR REPLACE FUNCTION public.remove_message(p_id uuid)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    m public.chat_messages%ROWTYPE;
    who text;
BEGIN
    SELECT * INTO m FROM public.chat_messages WHERE id = p_id;
    IF m.id IS NULL OR NOT public.chat_can_see(m.channel_id) THEN
        RAISE EXCEPTION 'That message is not there.';
    END IF;
    IF m.user_id IS DISTINCT FROM auth.uid() AND NOT public.chat_may('remove_any') THEN
        RAISE EXCEPTION 'You can only take down your own messages.';
    END IF;
    SELECT COALESCE(NULLIF(full_name, ''), username, '') INTO who
      FROM public.profiles WHERE id = auth.uid();
    -- Kept as a row, so the conversation still reads in order; what it said
    -- is gone.
    UPDATE public.chat_messages
       SET body = '', pinned = false, pinned_by = '', pinned_at = NULL,
           removed_at = now(), removed_by = COALESCE(who, '')
     WHERE id = p_id AND removed_at IS NULL;
    RETURN true;
END;
$$;

-- Every channel you can see, with what you have not read yet.
CREATE OR REPLACE FUNCTION public.my_chats()
RETURNS TABLE (id uuid, name text, kind text, post_min_role text,
               created_by uuid, members integer, unread integer,
               last_at timestamptz, last_body text, last_author text,
               can_post boolean)
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
    SELECT c.id, c.name, c.kind, c.post_min_role, c.created_by,
           (SELECT count(*)::integer FROM public.chat_members m WHERE m.channel_id = c.id),
           (SELECT count(*)::integer FROM public.chat_messages x
             WHERE x.channel_id = c.id AND x.removed_at IS NULL
               AND x.user_id IS DISTINCT FROM auth.uid()
               AND x.created_at > COALESCE((SELECT r.last_read_at FROM public.chat_reads r
                                             WHERE r.channel_id = c.id
                                               AND r.user_id = auth.uid()),
                                           '-infinity'::timestamptz)),
           l.created_at, l.body, l.author,
           public.chat_can_post(c.id)
      FROM public.chat_channels c
      LEFT JOIN LATERAL (
          SELECT x.created_at, x.body, x.author FROM public.chat_messages x
           WHERE x.channel_id = c.id AND x.removed_at IS NULL
           ORDER BY x.created_at DESC LIMIT 1) AS l ON true
     WHERE NOT c.archived
     ORDER BY c.kind, COALESCE(l.created_at, c.created_at) DESC;
$$;

CREATE OR REPLACE FUNCTION public.mark_chat_read(p_channel uuid)
RETURNS void
LANGUAGE sql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
    INSERT INTO public.chat_reads (channel_id, user_id, last_read_at)
    VALUES (p_channel, auth.uid(), now())
    ON CONFLICT (channel_id, user_id) DO UPDATE SET last_read_at = now();
$$;

DO $$
DECLARE f text;
BEGIN
  FOREACH f IN ARRAY ARRAY[
      'make_group(text, uuid[], text)', 'set_group_members(uuid, uuid[])',
      'leave_group(uuid)', 'pin_message(uuid, boolean)', 'remove_message(uuid)',
      'my_chats()', 'mark_chat_read(uuid)'] LOOP
    EXECUTE format('REVOKE ALL ON FUNCTION public.%s FROM public, anon', f);
    EXECUTE format('GRANT EXECUTE ON FUNCTION public.%s TO authenticated', f);
  END LOOP;
END $$;
