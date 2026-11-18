-- ============================================================================
-- Step 55: plain delivery labels, customer by customer
--
--   * customers.plain_labels - true for a customer whose delivery labels must
--     not show who made the filters: no TAF logo, no From address, no phone
--     number or ABN. A customer who resells under their own name, say, or
--     whose own customer must not see us. Their labels still carry the
--     delivery address, the order and job numbers, the sizes, quantities,
--     weights and the barcode.
--
-- Everyone else stays as they are: the default is off.
--
-- Needs migrate_label_switches.sql (step 35). Safe to run more than once.
-- ============================================================================

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE table_schema = 'public' AND table_name = 'customers'
                    AND column_name = 'delivery_labels') THEN
    RAISE EXCEPTION 'Run migrate_label_switches.sql (step 35) first.';
  END IF;
END $$;

ALTER TABLE public.customers
    ADD COLUMN IF NOT EXISTS plain_labels boolean NOT NULL DEFAULT false;
