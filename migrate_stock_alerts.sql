-- Migration: Low stock / media usage alerts
-- Run in: supabase.com → your project → SQL Editor

create table if not exists stock_alerts (
  id          bigserial primary key,
  media_type  text    not null unique,
  threshold   integer not null default 10,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

alter table stock_alerts enable row level security;

create policy "Authenticated users can read stock alerts"
  on stock_alerts for select to authenticated using (true);

create policy "Managers can manage stock alerts"
  on stock_alerts for all to authenticated
  using (
    exists (
      select 1 from profiles
      where id = auth.uid()
      and role in ('Manager', 'Director', 'Admin')
    )
  )
  with check (
    exists (
      select 1 from profiles
      where id = auth.uid()
      and role in ('Manager', 'Director', 'Admin')
    )
  );
