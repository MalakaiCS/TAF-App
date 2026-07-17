-- Migration: Audit log for order actions
-- Run in: supabase.com → your project → SQL Editor

create table if not exists audit_log (
  id          bigserial primary key,
  user_id     uuid        references auth.users(id) on delete set null,
  username    text        not null default '',
  action      text        not null,
  details     text        not null default '',
  created_at  timestamptz not null default now()
);

alter table audit_log enable row level security;

create policy "Users can insert audit log"
  on audit_log for insert to authenticated
  with check (user_id = auth.uid());

create policy "Managers can read audit log"
  on audit_log for select to authenticated
  using (
    exists (
      select 1 from profiles
      where id = auth.uid()
      and role in ('Manager', 'Director', 'Admin')
    )
  );
