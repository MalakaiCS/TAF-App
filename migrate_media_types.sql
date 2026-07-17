-- Migration: shared media types table
-- Run in: supabase.com → your project → SQL Editor

create table if not exists media_types (
  id         uuid    default gen_random_uuid() primary key,
  name       text    unique not null,
  sort_order int     default 0,
  created_at timestamptz default now()
);

alter table media_types enable row level security;

-- All authenticated users can read
create policy "Authenticated users can view media types"
  on media_types for select to authenticated using (true);

-- Managers and above can insert/update/delete
create policy "Managers can manage media types"
  on media_types for insert to authenticated
  with check (
    exists (
      select 1 from profiles
      where id = auth.uid()
      and role in ('Director', 'Admin', 'Manager')
    )
  );

create policy "Managers can update media types"
  on media_types for update to authenticated
  using (
    exists (
      select 1 from profiles
      where id = auth.uid()
      and role in ('Director', 'Admin', 'Manager')
    )
  );

create policy "Managers can delete media types"
  on media_types for delete to authenticated
  using (
    exists (
      select 1 from profiles
      where id = auth.uid()
      and role in ('Director', 'Admin', 'Manager')
    )
  );
