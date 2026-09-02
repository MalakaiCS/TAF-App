-- Migration: shared catalogue lists (dedicated filter presets, custom filter types)
-- Run in: supabase.com → your project → SQL Editor
--
-- One row per list; the value is the whole list as JSON. Used for:
--   key = 'gd_packs'            → Comp Air / Gardner Denver housing models
--   key = 'sigrist_pack'        → Sigrist preset spec
--   key = 'stepped_packs'       → Stepped Filter size presets
--   key = 'custom_filter_types' → extra Filter Type names beyond the built-ins
--   key = 'po_corrections'      → what purchase-order wordings turned out to
--                                 mean, learned from corrections made in the
--                                 import review screen
--   key = 'stock_settings'      → whether orders deduct stock automatically

create table if not exists catalog_lists (
  key        text primary key,
  value      jsonb not null,
  updated_at timestamptz default now()
);

alter table catalog_lists enable row level security;

-- All authenticated users can read
create policy "Authenticated users can view catalog lists"
  on catalog_lists for select to authenticated using (true);

-- Managers and above can insert/update/delete
create policy "Managers can insert catalog lists"
  on catalog_lists for insert to authenticated
  with check (
    exists (
      select 1 from profiles
      where id = auth.uid()
      and role in ('Director', 'Admin', 'Manager')
    )
  );

create policy "Managers can update catalog lists"
  on catalog_lists for update to authenticated
  using (
    exists (
      select 1 from profiles
      where id = auth.uid()
      and role in ('Director', 'Admin', 'Manager')
    )
  );

create policy "Managers can delete catalog lists"
  on catalog_lists for delete to authenticated
  using (
    exists (
      select 1 from profiles
      where id = auth.uid()
      and role in ('Director', 'Admin', 'Manager')
    )
  );
