-- ============================================================================
-- Step 38: three price tiers
--
-- Each customer is on Tier 1, 2 or 3, and every product and every price per
-- square metre can have a price for each tier. The customer's tier decides
-- which one fills in the price on the work order (and so on the invoice).
--
--   customers.price_tier            1, 2 or 3 (everyone starts on Tier 1)
--   price_list.unit_price           the Tier 1 price, as it always was
--   price_list.unit_price_2 / _3    Tier 2 and Tier 3; blank = the Tier 1 price
--   price_rates.rate_per_sqm        the Tier 1 rate, as it always was
--   price_rates.rate_per_sqm_2 / _3 Tier 2 and Tier 3; blank = the Tier 1 rate
--
-- A customer's own agreed price (Per-customer pricing) still wins over any
-- tier, and a price typed on the work order wins over both.
--
-- Safe to run more than once.
-- ============================================================================

ALTER TABLE public.customers
  ADD COLUMN IF NOT EXISTS price_tier smallint NOT NULL DEFAULT 1;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conname = 'customers_price_tier_check') THEN
    ALTER TABLE public.customers
      ADD CONSTRAINT customers_price_tier_check CHECK (price_tier IN (1, 2, 3));
  END IF;
END $$;

ALTER TABLE public.price_list
  ADD COLUMN IF NOT EXISTS unit_price_2 numeric(12, 4),
  ADD COLUMN IF NOT EXISTS unit_price_3 numeric(12, 4);

ALTER TABLE public.price_rates
  ADD COLUMN IF NOT EXISTS rate_per_sqm_2 numeric(12, 4),
  ADD COLUMN IF NOT EXISTS rate_per_sqm_3 numeric(12, 4);

-- What a customer pays is a manager's decision, as prices are. Staff can
-- still edit everything else about a customer.
CREATE OR REPLACE FUNCTION public._price_tier_guard()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF auth.uid() IS NULL THEN
    RETURN NEW;            -- the SQL Editor, or the service role
  END IF;
  IF (TG_OP = 'INSERT' AND NEW.price_tier <> 1)
     OR (TG_OP = 'UPDATE' AND NEW.price_tier IS DISTINCT FROM OLD.price_tier) THEN
    IF NOT EXISTS (
         SELECT 1 FROM public.profiles p
          WHERE p.id = auth.uid()
            AND p.role IN ('Director', 'Admin', 'Manager')
            AND COALESCE((to_jsonb(p) ->> 'approved')::boolean, true)) THEN
      RAISE EXCEPTION 'Only a manager can change a customer''s price tier.';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public._price_tier_guard() FROM PUBLIC;

DROP TRIGGER IF EXISTS customers_price_tier_guard ON public.customers;
CREATE TRIGGER customers_price_tier_guard
  BEFORE INSERT OR UPDATE OF price_tier ON public.customers
  FOR EACH ROW EXECUTE FUNCTION public._price_tier_guard();
