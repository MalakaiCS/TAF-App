-- ============================================================================
-- Step 35: switching delivery labels off
--
--   * customers.delivery_labels - false for a customer whose orders never
--     need delivery labels (they collect, say). Generate Output then skips
--     them. Everyone else stays as they are: the default is on.
--   * a 'delivery_labels' section in calc_settings - the switch for
--     everyone, kept and versioned with the other label settings.
--
-- Labels asked for by hand (View Order > Actions > Delivery labels, pallet
-- labels) still print either way.
--
-- Needs step 33 (migrate_packing_and_merge.sql). Safe to run more than once.
-- ============================================================================

DO $$
BEGIN
  IF to_regclass('public.calc_settings') IS NULL THEN
    RAISE EXCEPTION 'Run migrate_packing_and_merge.sql (step 33) first.';
  END IF;
END $$;

ALTER TABLE public.customers
    ADD COLUMN IF NOT EXISTS delivery_labels boolean NOT NULL DEFAULT true;

ALTER TABLE public.calc_settings
    DROP CONSTRAINT IF EXISTS calc_settings_key_check;
ALTER TABLE public.calc_settings
    ADD CONSTRAINT calc_settings_key_check CHECK (key IN (
        'materials', 'steel', 'cut_profiles', 'component_profiles',
        'brace_profiles', 'mounting_frame_profiles', 'wire_rules',
        'required_components', 'packaging', 'handling_profiles',
        'max_bundle_kg', 'shipping_rounding', 'company', 'c_channel',
        'delivery_labels'));
