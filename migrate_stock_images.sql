-- ============================================================
-- TAF Order App - Pictures of stock items
-- Run this in Supabase Dashboard -> SQL Editor. Safe to re-run.
--
-- stock_schema.sql only said to make the bucket by hand, so on a project
-- where nobody did, attaching a picture to a stock item failed with
-- "Bucket not found". This makes it.
--
-- Public-read, like the profile pictures: the picture is shown in the stock
-- list, and a signed link that expires would mean it quietly vanishing. The
-- file is named after the stock item's id and says nothing else.
-- ============================================================

INSERT INTO storage.buckets (id, name, public)
VALUES ('stock-images', 'stock-images', true)
ON CONFLICT (id) DO UPDATE SET public = true;


-- ── Who may change a picture ────────────────────────────────────────────────
-- Anyone can see them. Adding, replacing and removing one is for staff.

DROP POLICY IF EXISTS "Stock images are readable" ON storage.objects;
CREATE POLICY "Stock images are readable"
    ON storage.objects FOR SELECT
    USING (bucket_id = 'stock-images');

DROP POLICY IF EXISTS "Staff can upload a stock image" ON storage.objects;
CREATE POLICY "Staff can upload a stock image"
    ON storage.objects FOR INSERT TO authenticated
    WITH CHECK (bucket_id = 'stock-images' AND public.is_staff());

DROP POLICY IF EXISTS "Staff can replace a stock image" ON storage.objects;
CREATE POLICY "Staff can replace a stock image"
    ON storage.objects FOR UPDATE TO authenticated
    USING (bucket_id = 'stock-images' AND public.is_staff());

DROP POLICY IF EXISTS "Staff can remove a stock image" ON storage.objects;
CREATE POLICY "Staff can remove a stock image"
    ON storage.objects FOR DELETE TO authenticated
    USING (bucket_id = 'stock-images' AND public.is_staff());
