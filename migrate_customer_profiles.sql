-- Migration: customer short names, delivery regions, job-number rules,
--            and part-number codes for media types
-- Run in: supabase.com → your project → SQL Editor
--
-- A purchase order says "Complete Air Supply Pty Ltd" at "19-27 Fred Chaplin
-- Circuit, Bells Creek QLD 4551". The order should say "CAS - Bells Creek" in
-- "Sunshine Coast". Each branch is its own customer profile, holding the short
-- name that goes on orders, the region it delivers to, and where that
-- company's purchase orders put their job number.

alter table customers add column if not exists short_name       text default '';
alter table customers add column if not exists region           text default '';
alter table customers add column if not exists job_number_label text default '';
-- Names and addresses seen on their purchase orders that identify this branch,
-- so the same wording is recognised next time without asking again.
alter table customers add column if not exists po_aliases       jsonb default '[]'::jsonb;

-- Orders are written under the short name, so it needs to be quick to look up.
create index if not exists customers_short_name_idx on customers (lower(short_name));

-- Part-number code for each media type: Carbon -> CARB, so a flat panel comes
-- out as FPFCARB25-020. Seeded from the name; correct any that look wrong in
-- Settings → Media Types.
alter table media_types add column if not exists code text default '';
