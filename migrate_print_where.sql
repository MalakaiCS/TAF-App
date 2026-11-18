-- ============================================================================
-- Step 54: is this PC at work? (printing goes to the work printers when not)
--
-- A PC away from work should send its printing to the printers at work by
-- itself, and print on its own printer when it is at work. What tells them
-- apart is the internet connection: everything on the workshop's network
-- reaches the database from the same address. The print station (step 53)
-- notes the address it comes from each time it checks in; print_where()
-- tells any PC or phone whether it is coming from one of those.
--
-- The address is read from the request by the database itself - never
-- taken from the app - so it is what the internet saw, not what a PC says.
-- An IPv6 address is compared by its network (the first half), which is
-- the same for every device on one connection.
--
-- Needs migrate_print_queue.sql (step 53). Safe to run more than once.
-- ============================================================================

DO $$
BEGIN
  IF to_regclass('public.print_stations') IS NULL THEN
    RAISE EXCEPTION 'Run migrate_print_queue.sql (step 53) first.';
  END IF;
END $$;

-- The networks the station has checked in from, most recent first.
ALTER TABLE public.print_stations
  ADD COLUMN IF NOT EXISTS networks text[] NOT NULL DEFAULT '{}';


-- Where this request came from, as a network: an IPv4 address as it is,
-- an IPv6 one cut to its /64. NULL when it cannot be told.
CREATE OR REPLACE FUNCTION public._request_network()
RETURNS text
LANGUAGE plpgsql
STABLE
SET search_path = public, pg_temp
AS $$
DECLARE
    h  json;
    ip text;
    a  inet;
BEGIN
    BEGIN
        h := nullif(current_setting('request.headers', true), '')::json;
    EXCEPTION WHEN others THEN
        RETURN NULL;
    END;
    IF h IS NULL THEN
        RETURN NULL;
    END IF;
    ip := COALESCE(nullif(btrim(h ->> 'cf-connecting-ip'), ''),
                   nullif(btrim(split_part(h ->> 'x-forwarded-for', ',', 1)), ''),
                   nullif(btrim(h ->> 'x-real-ip'), ''));
    IF ip IS NULL THEN
        RETURN NULL;
    END IF;
    BEGIN
        a := ip::inet;
    EXCEPTION WHEN others THEN
        RETURN NULL;
    END;
    IF family(a) = 6 THEN
        RETURN network(set_masklen(a, 64))::text;
    END IF;
    RETURN host(a);
END;
$$;

REVOKE ALL ON FUNCTION public._request_network() FROM PUBLIC, anon;


-- print_station_checkin as in step 53, noting the network it came from.
CREATE OR REPLACE FUNCTION public.print_station_checkin(
    p_name text, p_printers text[], p_default text)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    sid uuid;
    on_ boolean;
    net text := public._request_network();
BEGIN
    IF NOT public.is_staff() THEN
        RAISE EXCEPTION 'Only staff can run a print station.';
    END IF;
    IF p_name IS NULL OR length(btrim(p_name)) = 0 THEN
        RAISE EXCEPTION 'A print station needs a name.';
    END IF;
    SELECT id, enabled INTO sid, on_ FROM public.print_stations
     WHERE name = btrim(p_name);
    IF sid IS NULL THEN
        IF NOT public.is_manager() THEN
            RAISE EXCEPTION 'Only a manager can make a PC a print station.';
        END IF;
        INSERT INTO public.print_stations (name, printers, default_printer)
        VALUES (btrim(p_name), COALESCE(p_printers, '{}'), COALESCE(p_default, ''))
        RETURNING id INTO sid;
    ELSIF NOT on_ THEN
        RAISE EXCEPTION 'This print station has been turned off by a manager.';
    END IF;
    UPDATE public.print_stations
       SET printers = COALESCE(p_printers, '{}'),
           default_printer = COALESCE(p_default, ''),
           last_seen = now(),
           -- This network first, then the others it has used, five at most:
           -- a connection with both IPv4 and IPv6 shows up as two.
           networks = CASE WHEN net IS NULL THEN networks ELSE
               (ARRAY[net] || array_remove(networks, net))[1:5] END
     WHERE id = sid;
    RETURN sid;
END;
$$;


-- Is whoever is asking at work? true: on the same connection as a print
-- station. false: somewhere else. null: it cannot be told (no station has
-- checked in yet, or the request carries no address).
CREATE OR REPLACE FUNCTION public.print_where()
RETURNS json
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    net  text := public._request_network();
    nets text[];
BEGIN
    IF NOT public.is_staff() THEN
        RAISE EXCEPTION 'Only staff can print at work.';
    END IF;
    SELECT COALESCE(array_agg(DISTINCT n), '{}') INTO nets
      FROM public.print_stations s, unnest(s.networks) AS n
     WHERE s.enabled AND s.last_seen > now() - interval '30 days';
    RETURN json_build_object(
        'at_work', CASE WHEN net IS NULL OR cardinality(nets) = 0 THEN NULL
                        ELSE net = ANY (nets) END,
        'stations', (SELECT count(*) FROM public.print_stations WHERE enabled));
END;
$$;

REVOKE ALL ON FUNCTION public.print_where() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.print_where() TO authenticated;
