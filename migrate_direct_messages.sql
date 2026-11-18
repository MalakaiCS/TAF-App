-- ============================================================================
-- Step 50: private messages
--
-- A conversation between two people, beside the noticeboard and the groups
-- (step 49). Anybody on staff can message anybody else on staff; only the
-- two of them can see it. Starting one with somebody you already have one
-- with opens that one, so there is only ever one conversation between two
-- people.
--
-- Needs migrate_staff_board.sql (step 49). Safe to run more than once.
-- ============================================================================

DO $$
BEGIN
  IF to_regclass('public.chat_channels') IS NULL THEN
    RAISE EXCEPTION 'Run migrate_staff_board.sql (step 49) first.';
  END IF;
END $$;

ALTER TABLE public.chat_channels DROP CONSTRAINT IF EXISTS chat_channels_kind_check;
ALTER TABLE public.chat_channels ADD CONSTRAINT chat_channels_kind_check
    CHECK (kind IN ('board', 'group', 'direct'));

-- The two people, smaller id first: what makes "one conversation between
-- two people" something the database holds, not something the apps hope.
ALTER TABLE public.chat_channels ADD COLUMN IF NOT EXISTS direct_key text;
CREATE UNIQUE INDEX IF NOT EXISTS chat_one_direct
    ON public.chat_channels (direct_key) WHERE direct_key IS NOT NULL;

CREATE OR REPLACE FUNCTION public.open_direct(p_user uuid)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    me  uuid := auth.uid();
    k   text;
    cid uuid;
BEGIN
    IF NOT public.is_staff() THEN
        RAISE EXCEPTION 'Only staff can send messages.';
    END IF;
    IF p_user IS NULL OR p_user = me THEN
        RAISE EXCEPTION 'Pick somebody else to message.';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.profiles WHERE id = p_user AND approved) THEN
        RAISE EXCEPTION 'That person is not on staff.';
    END IF;
    k := least(me::text, p_user::text) || ':' || greatest(me::text, p_user::text);
    SELECT id INTO cid FROM public.chat_channels WHERE direct_key = k;
    IF cid IS NULL THEN
        INSERT INTO public.chat_channels (name, kind, created_by, direct_key)
        VALUES ('Direct', 'direct', me, k)
        ON CONFLICT (direct_key) WHERE direct_key IS NOT NULL DO NOTHING
        RETURNING id INTO cid;
        IF cid IS NULL THEN               -- the other one started it just now
            SELECT id INTO cid FROM public.chat_channels WHERE direct_key = k;
        END IF;
    END IF;
    INSERT INTO public.chat_members (channel_id, user_id)
    VALUES (cid, me), (cid, p_user)
    ON CONFLICT DO NOTHING;
    UPDATE public.chat_channels SET archived = false WHERE id = cid;
    RETURN cid;
END;
$$;

REVOKE ALL ON FUNCTION public.open_direct(uuid) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.open_direct(uuid) TO authenticated;

-- my_chats, the same columns: a private conversation is named after the
-- other person, and the noticeboard comes first, then whatever was last
-- talked in.
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
    SELECT c.id,
           CASE WHEN c.kind = 'direct' THEN COALESCE((
               SELECT COALESCE(NULLIF(p.full_name, ''), p.username)
                 FROM public.chat_members m
                 JOIN public.profiles p ON p.id = m.user_id
                WHERE m.channel_id = c.id AND m.user_id <> auth.uid()
                LIMIT 1), 'Direct')
                ELSE c.name END,
           c.kind, c.post_min_role, c.created_by,
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
     ORDER BY (c.kind = 'board') DESC, COALESCE(l.created_at, c.created_at) DESC;
$$;
