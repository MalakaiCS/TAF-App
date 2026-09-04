-- ============================================================
-- TAF Order App - Our own order numbers
-- Run this in Supabase Dashboard -> SQL Editor. Safe to re-run.
--
-- Some customers ring up without a purchase order number. Those orders get
-- one of ours instead: TAF-ON-0001, TAF-ON-0002, and so on.
--
-- Deliberately its own counter, with nothing to do with invoice numbers. An
-- order number identifies a job in the shop; an invoice number is an
-- accounting record with its own rules. Tying the two together means neither
-- can be changed without disturbing the other.
--
-- A SEQUENCE rather than "find the highest and add one", because two people
-- on two PCs press the button at the same moment often enough to matter, and
-- reading-then-writing hands them both the same number. A sequence cannot do
-- that, even under load, even in a transaction that later rolls back.
--
-- The cost of that guarantee is gaps: a number handed out and then abandoned
-- is not reissued. That is the right trade for an order number - the number
-- has to be unique far more than it has to be consecutive. (An invoice
-- number, where a missing number is a question from an auditor, is exactly
-- why these are kept apart.)
-- ============================================================

CREATE SEQUENCE IF NOT EXISTS taf_order_number_seq AS bigint START WITH 1;

CREATE OR REPLACE FUNCTION public.next_taf_order_number()
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  n bigint;
BEGIN
  -- Definer rights bypass row-level security, so the staff check that every
  -- other table gets from its policies has to be made here instead.
  IF to_regprocedure('public.is_staff()') IS NOT NULL THEN
    IF NOT public.is_staff() THEN
      RAISE EXCEPTION 'not permitted';
    END IF;
  ELSIF auth.uid() IS NULL THEN
    -- Before migrate_staff_access.sql there is no staff notion; at least
    -- insist on being signed in.
    RAISE EXCEPTION 'not permitted';
  END IF;

  n := nextval('public.taf_order_number_seq');
  RETURN 'TAF-ON-' || lpad(n::text, 4, '0');
END;
$$;

REVOKE ALL ON FUNCTION public.next_taf_order_number() FROM public;
GRANT EXECUTE ON FUNCTION public.next_taf_order_number() TO authenticated;
GRANT USAGE ON SEQUENCE taf_order_number_seq TO authenticated;

-- ── Catching up an existing database ────────────────────────────────────────
-- If TAF-ON numbers have already been written by hand, start the counter
-- above the highest one rather than handing out a number that is in use.

DO $$
DECLARE
  highest bigint;
  current_value bigint;
BEGIN
  SELECT max((regexp_replace(order_number, '^TAF-ON-', ''))::bigint)
    INTO highest
    FROM public.orders
   WHERE order_number ~ '^TAF-ON-[0-9]+$';

  SELECT last_value INTO current_value FROM public.taf_order_number_seq;

  IF highest IS NOT NULL AND highest >= current_value THEN
    PERFORM setval('public.taf_order_number_seq', highest);
    RAISE NOTICE 'TAF-ON counter moved up to %', highest;
  END IF;
EXCEPTION WHEN OTHERS THEN
  RAISE NOTICE 'could not read existing TAF-ON numbers: %', SQLERRM;
END $$;
