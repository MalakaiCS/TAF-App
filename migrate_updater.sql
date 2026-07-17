-- Migration: app version tracking
-- Run in: supabase.com → your project → SQL Editor

create table if not exists app_versions (
  id            int  primary key default 1,   -- always one row
  version       text not null default '1.0.0',
  download_url  text not null default '',
  release_notes text          default '',
  updated_at    timestamptz   default now()
);

alter table app_versions enable row level security;

-- All authenticated users can read the current version
create policy "Authenticated users can read version"
  on app_versions for select to authenticated using (true);

-- Only Directors / Admins can push updates
create policy "Directors can update version"
  on app_versions for update to authenticated
  using (
    exists (
      select 1 from profiles
      where id = auth.uid()
      and role in ('Director', 'Admin')
    )
  );

create policy "Directors can insert version"
  on app_versions for insert to authenticated
  with check (
    exists (
      select 1 from profiles
      where id = auth.uid()
      and role in ('Director', 'Admin')
    )
  );

-- Insert initial row (version 1.0.0, no download yet)
insert into app_versions (id, version, download_url, release_notes)
values (1, '1.0.0', '', 'Initial release.')
on conflict (id) do nothing;

-- Storage bucket for releases (run separately if needed):
-- Go to Storage in your Supabase dashboard and create a PUBLIC bucket named "releases"
