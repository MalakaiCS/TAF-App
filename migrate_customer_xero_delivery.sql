-- ============================================================================
-- Step 39: a customer's Xero contact, and their delivery fee
--
--   customers.xero_contact_id   the contact this customer is in Xero. Set
--                               from Customers > Customer > Link to a Xero
--                               contact (or found by name the first time),
--                               and used for their invoices from then on -
--                               so a customer called something different in
--                               Xero still invoices to the right contact.
--   customers.delivery_fee      a delivery charge every order of theirs
--                               carries (ex GST), or empty for none. Like
--                               their price tier, only a manager can set it.
--
-- Safe to run more than once.
-- ============================================================================

ALTER TABLE public.customers
  ADD COLUMN IF NOT EXISTS xero_contact_id text,
  ADD COLUMN IF NOT EXISTS delivery_fee numeric(12, 2);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conname = 'customers_delivery_fee_check') THEN
    ALTER TABLE public.customers
      ADD CONSTRAINT customers_delivery_fee_check
      CHECK (delivery_fee IS NULL OR delivery_fee >= 0);
  END IF;
END $$;

-- What a customer is charged is a manager's decision.
CREATE OR REPLACE FUNCTION public._delivery_fee_guard()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF auth.uid() IS NULL THEN
    RETURN NEW;            -- the SQL Editor, or the service role
  END IF;
  IF (TG_OP = 'INSERT' AND NEW.delivery_fee IS NOT NULL)
     OR (TG_OP = 'UPDATE' AND NEW.delivery_fee IS DISTINCT FROM OLD.delivery_fee) THEN
    IF NOT EXISTS (
         SELECT 1 FROM public.profiles p
          WHERE p.id = auth.uid()
            AND p.role IN ('Director', 'Admin', 'Manager')
            AND COALESCE((to_jsonb(p) ->> 'approved')::boolean, true)) THEN
      RAISE EXCEPTION 'Only a manager can change a customer''s delivery fee.';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public._delivery_fee_guard() FROM PUBLIC;

DROP TRIGGER IF EXISTS customers_delivery_fee_guard ON public.customers;
CREATE TRIGGER customers_delivery_fee_guard
  BEFORE INSERT OR UPDATE OF delivery_fee ON public.customers
  FOR EACH ROW EXECUTE FUNCTION public._delivery_fee_guard();
