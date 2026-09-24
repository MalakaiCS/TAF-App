-- Migration: phone photo inbox for purchase-order import
-- Run in: supabase.com → your project → SQL Editor
--
-- Staff photograph a purchase order on their phone (see the `po-upload` Edge
-- Function), the photos land in this private bucket, and the desktop app
-- picks them up, reads them and clears them.
--
-- Files are laid out one folder per submission:
--     po-inbox/<batch-id>/01.jpg
--     po-inbox/<batch-id>/02.jpg
--     po-inbox/<batch-id>/_complete.json   ← written last, marks it finished
-- The app only touches a batch once _complete.json exists, so it can never
-- read a half-uploaded set of photos.

insert into storage.buckets (id, name, public)
values ('po-inbox', 'po-inbox', false)
on conflict (id) do nothing;

-- Any signed-in staff member may send photos in…
drop policy if exists "Staff can upload PO photos" on storage.objects;
create policy "Staff can upload PO photos"
  on storage.objects for insert to authenticated
  with check (bucket_id = 'po-inbox');

-- …and the office PC (also signed in) reads and clears them once processed.
drop policy if exists "Staff can read PO photos" on storage.objects;
create policy "Staff can read PO photos"
  on storage.objects for select to authenticated
  using (bucket_id = 'po-inbox');

drop policy if exists "Staff can delete processed PO photos" on storage.objects;
create policy "Staff can delete processed PO photos"
  on storage.objects for delete to authenticated
  using (bucket_id = 'po-inbox');
