-- ============================================================
-- TAF Order App - Delivery on a quote
-- Run this in Supabase Dashboard -> SQL Editor
--
-- Freight was worked out in somebody's head and added at invoicing, which is
-- how a customer gets told one number at the counter and billed another. It
-- is part of the quote now: shown on the screen facing them, on the PDF, and
-- saved with everything else so an accepted quote becomes an invoice for the
-- amount that was actually agreed.
--
-- It is its own column rather than an extra line in `items`, because it is
-- not a thing we make. A line in items would need a part number, would be
-- counted in the line count, and would turn up in stock deduction.
-- ============================================================

ALTER TABLE quotes
    ADD COLUMN IF NOT EXISTS shipping numeric(12, 2) NOT NULL DEFAULT 0;

-- Existing quotes carry 0, which is what they were: every quote written
-- before today was written with delivery quoted separately or not at all,
-- and inventing a figure for them now would be making one up.

COMMENT ON COLUMN quotes.shipping IS
    'Delivery charged on this quote, ex GST. Included in subtotal and taxed '
    'with the goods - freight on a taxable supply is itself taxable.';
