-- ============================================================
-- TAF Order App - Saved quotes
-- Run this in Supabase Dashboard -> SQL Editor
--
-- A quote is a business record, not a PDF someone printed once: what was
-- quoted, to whom, at what price, and whether it was won. Keeping them is
-- what lets an accepted quote become an order without being re-keyed.
-- ============================================================

CREATE TABLE IF NOT EXISTS quotes (
    id              uuid        DEFAULT gen_random_uuid() PRIMARY KEY,
    quote_number    text        NOT NULL DEFAULT '',
    customer_id     uuid        REFERENCES customers(id) ON DELETE SET NULL,
    customer_name   text        NOT NULL DEFAULT '',
    reference       text        DEFAULT '',      -- the customer's own reference
    location        text        DEFAULT '',      -- delivery region
    -- draft | sent | accepted | declined | expired
    status          text        NOT NULL DEFAULT 'draft',
    -- The lines exactly as quoted, so a later price change never rewrites
    -- what a customer was told.
    items           jsonb       NOT NULL DEFAULT '[]'::jsonb,
    subtotal        numeric(12, 2) NOT NULL DEFAULT 0,
    gst             numeric(12, 2) NOT NULL DEFAULT 0,
    total           numeric(12, 2) NOT NULL DEFAULT 0,
    unpriced_count  integer     NOT NULL DEFAULT 0,
    valid_until     date,
    notes           text        DEFAULT '',
    -- Set when the quote becomes an order, so it can't be converted twice.
    converted_order_id uuid,
    converted_at    timestamptz,
    created_by_name text        DEFAULT '',
    created_at      timestamptz DEFAULT now(),
    updated_at      timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS quotes_status_idx   ON quotes (status);
CREATE INDEX IF NOT EXISTS quotes_created_idx  ON quotes (created_at DESC);
CREATE INDEX IF NOT EXISTS quotes_customer_idx ON quotes (customer_name);

ALTER TABLE quotes ENABLE ROW LEVEL SECURITY;

-- Everyone signed in can read and write quotes: quoting is ordinary work.
-- Deleting one is not, so it is kept to Managers and above.
DROP POLICY IF EXISTS "quotes read"   ON quotes;
DROP POLICY IF EXISTS "quotes insert" ON quotes;
DROP POLICY IF EXISTS "quotes update" ON quotes;
DROP POLICY IF EXISTS "quotes delete" ON quotes;

CREATE POLICY "quotes read"   ON quotes FOR SELECT TO authenticated USING (true);
CREATE POLICY "quotes insert" ON quotes FOR INSERT TO authenticated WITH CHECK (true);
CREATE POLICY "quotes update" ON quotes FOR UPDATE TO authenticated USING (true);
CREATE POLICY "quotes delete" ON quotes FOR DELETE TO authenticated
  USING (EXISTS (SELECT 1 FROM profiles
                 WHERE id = auth.uid()
                   AND role IN ('Director', 'Admin', 'Manager')));
