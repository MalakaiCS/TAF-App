-- ============================================================================
-- Step 52: the part number each product sells as
--
-- The app writes a code for every line it makes - "3PG4-610610570" for a
-- full long G4 3-Peak bag, "MPHE-F78P595595560" for an 8-pocket MPHE - from
-- its type, media and size. Where that is not the part number the product
-- is sold under (the one in the price list, and in Xero), it is linked to
-- it here, once, and every line with that code is priced, costed and
-- invoiced as that part from then on.
--
-- Managers set them; everybody on staff reads them. Safe to run more than
-- once. Needs migrate_staff_access.sql.
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.part_links (
    code        text PRIMARY KEY,
    part_number text        NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    updated_by  text        NOT NULL DEFAULT '',
    -- Kept as the app compares them: trimmed and in capitals.
    CHECK (code = upper(btrim(code)) AND length(code) > 0),
    CHECK (part_number = upper(btrim(part_number)) AND length(part_number) > 0),
    CHECK (code <> part_number)
);

ALTER TABLE public.part_links ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Staff read part links"     ON public.part_links;
DROP POLICY IF EXISTS "Managers write part links" ON public.part_links;
CREATE POLICY "Staff read part links" ON public.part_links FOR SELECT
    TO authenticated USING (public.is_staff());
CREATE POLICY "Managers write part links" ON public.part_links FOR ALL
    TO authenticated USING (public.is_manager()) WITH CHECK (public.is_manager());
