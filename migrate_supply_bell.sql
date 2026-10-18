-- ============================================================================
-- Step 43: the bell only shows what still needs doing
--
-- A supply request's notification used to be marked read once the request
-- was dealt with, and stayed in everybody's list. Now it is taken off the
-- bell altogether once nothing on the request is waiting any more - ordered,
-- received, declined or cancelled, by anybody.
--
-- Several things asked for together (one New order) are one notification:
-- it goes when the last of them is dealt with, not the first.
--
-- Also clears the notifications already there for requests that have been
-- dealt with.
--
-- Needs migrate_supply_requests.sql (step 32) and migrate_purchasing.sql
-- (step 40). Safe to run more than once.
-- ============================================================================

DO $$
BEGIN
  IF to_regclass('public.notifications') IS NULL THEN
    RAISE EXCEPTION 'Run migrate_supply_requests.sql (step 32) first.';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE table_schema = 'public'
                    AND table_name = 'supply_requests'
                    AND column_name = 'batch_id') THEN
    RAISE EXCEPTION 'Run migrate_purchasing.sql (step 40) first.';
  END IF;
END $$;


-- A batch's notification points at its first request; a single request's
-- at itself. Either way: gone once no request it covers is still open.
CREATE OR REPLACE FUNCTION public.settle_supply_notifications()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF OLD.status = 'open' AND NEW.status <> 'open' THEN
        IF NEW.batch_id IS NULL THEN
            DELETE FROM public.notifications
             WHERE kind = 'supply_request' AND ref_id = NEW.id;
        ELSIF NOT EXISTS (SELECT 1 FROM public.supply_requests
                           WHERE batch_id = NEW.batch_id
                             AND status = 'open') THEN
            DELETE FROM public.notifications
             WHERE kind = 'supply_request'
               AND ref_id IN (SELECT id FROM public.supply_requests
                               WHERE batch_id = NEW.batch_id);
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS supply_requests_settle ON public.supply_requests;
CREATE TRIGGER supply_requests_settle
    AFTER UPDATE OF status ON public.supply_requests
    FOR EACH ROW EXECUTE FUNCTION public.settle_supply_notifications();

REVOKE ALL ON FUNCTION public.settle_supply_notifications()
    FROM public, anon, authenticated;


-- What is on the bell now for things already dealt with.
DELETE FROM public.notifications n
 WHERE n.kind = 'supply_request'
   AND NOT EXISTS (
       SELECT 1
         FROM public.supply_requests r
         JOIN public.supply_requests mine ON mine.id = n.ref_id
        WHERE r.status = 'open'
          AND (r.id = mine.id
               OR (mine.batch_id IS NOT NULL AND r.batch_id = mine.batch_id)));
