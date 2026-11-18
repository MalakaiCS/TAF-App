-- ============================================================================
-- Step 51: cash sales
--
--   customers.cash_sale   the account walk-in and one-off buyers are put
--                         under. Each of its orders goes to somebody
--                         different, so its invoice is never emailed to the
--                         account's address on file: the app asks for the
--                         buyer's email every time it is invoiced, keeps it
--                         on the order ("Invoice Email"), and the xero
--                         function emails the invoice there - the same Xero
--                         invoice and email as every other customer's.
--
-- Which account that is, is a manager's decision. Needs
-- migrate_customer_xero_delivery.sql (step 39). Safe to run more than once.
-- ============================================================================

ALTER TABLE public.customers
  ADD COLUMN IF NOT EXISTS cash_sale boolean NOT NULL DEFAULT false;

CREATE OR REPLACE FUNCTION public._cash_sale_guard()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF auth.uid() IS NULL THEN
    RETURN NEW;            -- the SQL Editor, or the service role
  END IF;
  IF (TG_OP = 'INSERT' AND NEW.cash_sale)
     OR (TG_OP = 'UPDATE' AND NEW.cash_sale IS DISTINCT FROM OLD.cash_sale) THEN
    IF NOT EXISTS (
         SELECT 1 FROM public.profiles p
          WHERE p.id = auth.uid()
            AND p.role IN ('Director', 'Admin', 'Manager')
            AND COALESCE((to_jsonb(p) ->> 'approved')::boolean, true)) THEN
      RAISE EXCEPTION 'Only a manager can make an account the cash sale account.';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public._cash_sale_guard() FROM PUBLIC;

DROP TRIGGER IF EXISTS customers_cash_sale_guard ON public.customers;
CREATE TRIGGER customers_cash_sale_guard
  BEFORE INSERT OR UPDATE OF cash_sale ON public.customers
  FOR EACH ROW EXECUTE FUNCTION public._cash_sale_guard();
