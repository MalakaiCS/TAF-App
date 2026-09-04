-- ============================================================
-- TAF Order App - Pricing & quotes
-- Run this in Supabase Dashboard -> SQL Editor
--
-- Two tables:
--   price_list  one price per part number, imported from the price
--               spreadsheets. This is the authority.
--   price_rates a fallback rate per square metre for a filter type and
--               media, used only when the part number is not in the list.
-- ============================================================

CREATE TABLE IF NOT EXISTS price_list (
    part_number     text        PRIMARY KEY,
    -- name        what the product is, e.g. "Flat Panel Filter G4 25mm - 0.2m2"
    -- description what goes on an invoice line in Xero. In a Xero item export
    --             this is a template ("... Rating / Size:") that reads the same
    --             on every row, which is why the name is kept as well.
    name            text        DEFAULT '',
    description     text        DEFAULT '',
    unit_price      numeric(12, 4) NOT NULL DEFAULT 0,
    updated_by_name text        DEFAULT '',
    updated_at      timestamptz DEFAULT now()
);

-- Safe to re-run on a price_list created before the name column existed.
ALTER TABLE price_list ADD COLUMN IF NOT EXISTS name text DEFAULT '';

CREATE TABLE IF NOT EXISTS price_rates (
    id              uuid        DEFAULT gen_random_uuid() PRIMARY KEY,
    filter_type     text        NOT NULL DEFAULT '',
    media_type      text        DEFAULT '',
    rate_per_sqm    numeric(12, 4) NOT NULL DEFAULT 0,
    updated_by_name text        DEFAULT '',
    updated_at      timestamptz DEFAULT now(),
    UNIQUE (filter_type, media_type)
);

ALTER TABLE price_list  ENABLE ROW LEVEL SECURITY;
ALTER TABLE price_rates ENABLE ROW LEVEL SECURITY;

-- Everyone signed in can read prices (they are needed to quote an order).
DROP POLICY IF EXISTS "price_list read"  ON price_list;
DROP POLICY IF EXISTS "price_rates read" ON price_rates;
CREATE POLICY "price_list read"  ON price_list  FOR SELECT TO authenticated USING (true);
CREATE POLICY "price_rates read" ON price_rates FOR SELECT TO authenticated USING (true);

-- Only Managers and above may change them: a wrong price goes out to a
-- customer on TAF letterhead.
DROP POLICY IF EXISTS "price_list write"  ON price_list;
DROP POLICY IF EXISTS "price_rates write" ON price_rates;
CREATE POLICY "price_list write" ON price_list FOR ALL TO authenticated
  USING (EXISTS (SELECT 1 FROM profiles p
                 WHERE p.id = auth.uid()
                   AND p.role IN ('Director', 'Admin', 'Manager')))
  WITH CHECK (EXISTS (SELECT 1 FROM profiles p
                      WHERE p.id = auth.uid()
                        AND p.role IN ('Director', 'Admin', 'Manager')));
CREATE POLICY "price_rates write" ON price_rates FOR ALL TO authenticated
  USING (EXISTS (SELECT 1 FROM profiles p
                 WHERE p.id = auth.uid()
                   AND p.role IN ('Director', 'Admin', 'Manager')))
  WITH CHECK (EXISTS (SELECT 1 FROM profiles p
                      WHERE p.id = auth.uid()
                        AND p.role IN ('Director', 'Admin', 'Manager')));

CREATE INDEX IF NOT EXISTS price_list_updated_idx ON price_list (updated_at DESC);
