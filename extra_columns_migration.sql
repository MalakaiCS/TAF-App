-- ============================================================
-- TAF Order App – Extra Columns Migration
-- Run this in Supabase Dashboard → SQL Editor
-- ============================================================

-- Short name for customers (used as a display alias in dropdowns)
ALTER TABLE customers ADD COLUMN IF NOT EXISTS short_name text DEFAULT '';

-- Supplier email on stock items (supplier contact detail)
ALTER TABLE stock_items ADD COLUMN IF NOT EXISTS supplier_email text DEFAULT '';
