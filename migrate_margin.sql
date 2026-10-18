-- ============================================================
-- TAF Order App - What a job actually makes
-- Run this in Supabase Dashboard -> SQL Editor. Safe to re-run.
--
-- The app has always known what a filter sells for and never what it costs
-- to make, so a quote could be written, sent and accepted without anyone
-- being able to say whether it was worth doing. Media price is the input
-- that actually moves, and it moves without asking.
--
-- Two columns, mirroring the two ways a line is priced:
--
--   price_list.unit_cost     what we pay for a listed part number
--   price_rates.cost_per_sqm what the media costs per square metre
--
-- Same shape as the sell side on purpose. Anything that can be priced can
-- now be costed the same way, and a line that cannot be costed says so
-- rather than being counted as pure profit - which is the failure that
-- makes a margin figure worse than no margin figure at all.
-- ============================================================

ALTER TABLE public.price_list
    ADD COLUMN IF NOT EXISTS unit_cost numeric(12, 4) NOT NULL DEFAULT 0;

ALTER TABLE public.price_rates
    ADD COLUMN IF NOT EXISTS cost_per_sqm numeric(12, 4) NOT NULL DEFAULT 0;

-- Zero means "nobody has said", not "free". The app treats it as unknown and
-- shows the line as uncosted; it never reports a 100% margin because a cost
-- was never entered.

COMMENT ON COLUMN public.price_list.unit_cost IS
    'What we pay for this part. 0 = not known, not free.';
COMMENT ON COLUMN public.price_rates.cost_per_sqm IS
    'Media cost per square metre. 0 = not known, not free.';
