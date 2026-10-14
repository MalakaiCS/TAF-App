-- ============================================================================
-- Step 34: C-channel settings
--
-- Lets the C-channel material, centre widths, measured weights and the
-- estimate rule be saved with the other weight settings (calc_settings), so a
-- change is versioned in calc_settings_history like every other one. The
-- defaults live in the app (taf_order_app/cchannel.py) until a manager saves
-- a change: G2 Z275 galvanised steel, 0.55 mm, 7850 kg/m3, 2440 mm lengths,
-- 23 mm flanges, TAF's measured centre widths for 15-100 mm.
--
-- Needs step 33 (migrate_packing_and_merge.sql). Safe to run more than once.
-- ============================================================================

DO $$
BEGIN
  IF to_regclass('public.calc_settings') IS NULL THEN
    RAISE EXCEPTION 'Run migrate_packing_and_merge.sql (step 33) first.';
  END IF;
END $$;

ALTER TABLE public.calc_settings
    DROP CONSTRAINT IF EXISTS calc_settings_key_check;
ALTER TABLE public.calc_settings
    ADD CONSTRAINT calc_settings_key_check CHECK (key IN (
        'materials', 'steel', 'cut_profiles', 'component_profiles',
        'brace_profiles', 'mounting_frame_profiles', 'wire_rules',
        'required_components', 'packaging', 'handling_profiles',
        'max_bundle_kg', 'shipping_rounding', 'company', 'c_channel'));
