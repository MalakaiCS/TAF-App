-- ============================================================
-- TAF Order App - Photos and signatures kept with an order
-- Run this in Supabase Dashboard -> SQL Editor. Safe to re-run.
--
-- Two things people currently keep somewhere other than in the system:
--
-- The old filter, the plant room, the damage. Photographed on a phone at
-- the site and then left on that phone, so somebody ringing about a job
-- three months later has nothing to look at.
--
-- And the signature on the run sheet, written on with a pen and then living
-- in a ute. "We never got them" is currently settled by memory.
--
-- Both are the same thing: a file, against an order, with who and when.
--
-- Files live in Storage, one folder per order. The row here is what the app
-- lists - Storage has no place to record who took a photo or what it is of.
-- ============================================================

INSERT INTO storage.buckets (id, name, public)
VALUES ('order-files', 'order-files', false)
ON CONFLICT (id) DO NOTHING;

-- Not public. A site photo can show a customer's plant room, and a
-- signature is somebody's name in their own hand. Both are read through a
-- signed URL by an account that is allowed to see the order.

DROP POLICY IF EXISTS "Staff add order files"    ON storage.objects;
DROP POLICY IF EXISTS "Staff read order files"   ON storage.objects;
DROP POLICY IF EXISTS "Staff remove order files" ON storage.objects;

CREATE POLICY "Staff add order files"
    ON storage.objects FOR INSERT TO authenticated
    WITH CHECK (bucket_id = 'order-files' AND public.is_staff());

CREATE POLICY "Staff read order files"
    ON storage.objects FOR SELECT TO authenticated
    USING (bucket_id = 'order-files' AND public.is_staff());

CREATE POLICY "Staff remove order files"
    ON storage.objects FOR DELETE TO authenticated
    USING (bucket_id = 'order-files' AND public.is_staff());


-- ── What each file is ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.order_files (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id    uuid NOT NULL REFERENCES public.orders(id) ON DELETE CASCADE,
    -- photo | signature | document
    kind        text NOT NULL DEFAULT 'photo',
    path        text NOT NULL,            -- where it sits in the bucket
    caption     text NOT NULL DEFAULT '',
    -- Only set on a signature: who signed for the delivery, in their words.
    signed_by   text NOT NULL DEFAULT '',
    taken_by    text NOT NULL DEFAULT '',
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- ON DELETE CASCADE here, unlike the recurring jobs: a photo of an order
-- that no longer exists is of no use to anybody, and leaving orphans behind
-- would mean a bucket that only ever grows.

CREATE INDEX IF NOT EXISTS order_files_order_idx
    ON public.order_files (order_id, created_at DESC);

ALTER TABLE public.order_files ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Staff read order file rows"   ON public.order_files;
DROP POLICY IF EXISTS "Staff add order file rows"    ON public.order_files;
DROP POLICY IF EXISTS "Staff change order file rows" ON public.order_files;
DROP POLICY IF EXISTS "Staff remove order file rows" ON public.order_files;

CREATE POLICY "Staff read order file rows"
    ON public.order_files FOR SELECT TO authenticated
    USING (public.is_staff());

CREATE POLICY "Staff add order file rows"
    ON public.order_files FOR INSERT TO authenticated
    WITH CHECK (public.is_staff());

CREATE POLICY "Staff change order file rows"
    ON public.order_files FOR UPDATE TO authenticated
    USING (public.is_staff());

-- Deliberately narrower than the rest: a proof of delivery is evidence, and
-- evidence that the person being asked about it can quietly remove is not
-- evidence. is_manager() is Director, Admin or Manager.
CREATE POLICY "Staff remove order file rows"
    ON public.order_files FOR DELETE TO authenticated
    USING (public.is_manager());
