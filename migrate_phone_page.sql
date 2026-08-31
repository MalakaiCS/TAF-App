-- Migration: public bucket that hosts the phone upload page
-- Run in: supabase.com → your project → SQL Editor
--
-- The page staff open on their phone is published here by the desktop app
-- (Import Purchase Order → Photograph it on a phone) rather than served by an
-- Edge Function. Storage returns exactly the content type set at upload, so
-- the page always arrives as HTML; the function's response was reaching
-- phones labelled text/plain, which browsers never sniff into HTML, and it
-- showed up as unstyled source.
--
-- Public read is required: the page has to load on a phone that has not
-- signed in yet. It contains only markup and the anon (publishable) key that
-- already ships inside the desktop app — signing in happens inside the page,
-- and row-level security still governs what anyone may actually do.

insert into storage.buckets (id, name, public)
values ('phone-page', 'phone-page', true)
on conflict (id) do update set public = true;

-- Anyone can load the page…
create policy "Anyone can load the phone page"
  on storage.objects for select
  using (bucket_id = 'phone-page');

-- …and signed-in staff can publish or refresh it from the app.
create policy "Staff can publish the phone page"
  on storage.objects for insert to authenticated
  with check (bucket_id = 'phone-page');

create policy "Staff can update the phone page"
  on storage.objects for update to authenticated
  using (bucket_id = 'phone-page');

create policy "Staff can replace the phone page"
  on storage.objects for delete to authenticated
  using (bucket_id = 'phone-page');
