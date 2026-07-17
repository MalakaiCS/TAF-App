-- TAF Order App – Supabase database setup (full)
-- Run this in: supabase.com → your project → SQL Editor → New query

-- ── Profiles ──────────────────────────────────────────────────────────────────
create table if not exists profiles (
  id        uuid references auth.users primary key,
  email     text not null,
  full_name text default '',
  username  text unique not null,
  role      text default 'Employee'
              check (role in ('Director', 'Admin', 'Manager', 'Employee')),
  created_at timestamptz default now()
);

alter table profiles enable row level security;

create policy "Authenticated users can view all profiles"
  on profiles for select to authenticated using (true);

create policy "Users can insert own profile"
  on profiles for insert to authenticated with check (auth.uid() = id);

create policy "Users can update own profile"
  on profiles for update to authenticated using (auth.uid() = id);

-- Allow privileged users to update any profile's role via a helper function:
create or replace function update_profile_role(
  target_id uuid,
  new_role   text
) returns void language plpgsql security definer as $$
declare
  caller_role text;
  role_level  int;
begin
  select role into caller_role from profiles where id = auth.uid();

  -- Map roles to numeric levels
  caller_role := coalesce(caller_role, 'Employee');
  case caller_role
    when 'Director' then role_level := 4;
    when 'Admin'    then role_level := 4;
    when 'Manager'  then role_level := 3;
    else role_level := 1;
  end case;

  if role_level < 3 then
    raise exception 'Insufficient permissions to change roles.';
  end if;

  -- Managers can only assign Employee; Directors/Admins can assign anything
  if role_level = 3 and new_role not in ('Employee') then
    raise exception 'Managers can only assign the Employee role.';
  end if;

  update profiles set role = new_role where id = target_id;
end;
$$;

-- ── Orders ────────────────────────────────────────────────────────────────────
create table if not exists orders (
  id            uuid        default gen_random_uuid() primary key,
  user_id       uuid        references auth.users not null,
  user_email    text        default '',
  username      text        default '',
  full_name     text        default '',
  customer_name text        default '',
  order_number  text        default '',
  date_ordered  text        default '',
  date_due      text        default '',
  attention     text        default '',
  job           text        default '',
  location      text        default '',
  notes         text        default '',
  order_type    text        default 'filter',
  header        jsonb       default '{}'::jsonb,
  items         jsonb       default '[]'::jsonb,
  created_at    timestamptz default now()
);

alter table orders enable row level security;

create policy "Authenticated users can view all orders"
  on orders for select to authenticated using (true);

create policy "Users can insert their own orders"
  on orders for insert to authenticated with check (auth.uid() = user_id);

create policy "Users can update their own orders"
  on orders for update to authenticated using (auth.uid() = user_id);

create policy "Users can delete their own orders"
  on orders for delete to authenticated using (auth.uid() = user_id);
