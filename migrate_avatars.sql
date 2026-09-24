-- ============================================================
-- TAF Order App - Profile pictures
-- Run this in Supabase Dashboard -> SQL Editor. Safe to re-run.
--
-- A photo against each account, so the name in the corner and the initials
-- on an order belong to a face rather than two letters.
--
-- The picture lives in Storage and the profile keeps the link to it. The
-- bucket is public-read on purpose: these are staff head-shots shown in the
-- app's own header, and a signed URL that expires would mean the header
-- quietly losing its picture an hour into the day. Nothing else about the
-- account is exposed by it - the file name is the account's id and reveals
-- no name, email or role.
-- ============================================================

ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS avatar_url text DEFAULT '';


-- ── The bucket ──────────────────────────────────────────────────────────────

INSERT INTO storage.buckets (id, name, public)
VALUES ('avatars', 'avatars', true)
ON CONFLICT (id) DO UPDATE SET public = true;


-- ── Who may change a picture ────────────────────────────────────────────────
-- Anyone signed in can see them - they are shown all over the app. Writing is
-- limited to staff, and a picture is named after the account it belongs to.

DROP POLICY IF EXISTS "Avatars are readable" ON storage.objects;
CREATE POLICY "Avatars are readable"
    ON storage.objects FOR SELECT
    USING (bucket_id = 'avatars');

DROP POLICY IF EXISTS "Staff can upload an avatar" ON storage.objects;
CREATE POLICY "Staff can upload an avatar"
    ON storage.objects FOR INSERT TO authenticated
    WITH CHECK (bucket_id = 'avatars' AND public.is_staff());

DROP POLICY IF EXISTS "Staff can replace an avatar" ON storage.objects;
CREATE POLICY "Staff can replace an avatar"
    ON storage.objects FOR UPDATE TO authenticated
    USING (bucket_id = 'avatars' AND public.is_staff());

DROP POLICY IF EXISTS "Staff can remove an avatar" ON storage.objects;
CREATE POLICY "Staff can remove an avatar"
    ON storage.objects FOR DELETE TO authenticated
    USING (bucket_id = 'avatars' AND public.is_staff());


-- ── Setting your own picture ────────────────────────────────────────────────
-- The profiles policies let someone update their own row, so this needs no
-- special power. It exists so an Admin can also set someone else's, and so
-- the check for that lives in the database rather than only in the app.

CREATE OR REPLACE FUNCTION public.set_avatar(p_user_id uuid, p_url text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF NOT public.is_staff() THEN
        RAISE EXCEPTION 'not permitted';
    END IF;
    -- Your own picture, or anyone's if you manage accounts.
    IF auth.uid() <> p_user_id AND NOT public.is_manager() THEN
        RAISE EXCEPTION 'not permitted';
    END IF;
    UPDATE public.profiles SET avatar_url = COALESCE(p_url, '')
     WHERE id = p_user_id;
END $$;

REVOKE ALL ON FUNCTION public.set_avatar(uuid, text) FROM public;
GRANT EXECUTE ON FUNCTION public.set_avatar(uuid, text) TO authenticated;
