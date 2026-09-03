-- ============================================================
-- TAF Order App - WHICH MIGRATIONS DO I STILL NEED?
--
-- Paste this whole file into Supabase -> SQL Editor -> New query and run it.
-- It changes nothing. It reads what your project already has and tells you,
-- in order, which files are still to run.
--
-- Read the "status" column: RUN THIS means that file has not been applied.
-- Work down the list from the top - some of them build on the ones above.
-- ============================================================

WITH checks(step, file, purpose, needed, present) AS (VALUES

  ( 1, 'setup_database.sql', 'Accounts and orders - the base tables', 'essential',
      to_regclass('public.profiles') IS NOT NULL
      AND to_regclass('public.orders') IS NOT NULL),

  ( 2, 'customers_schema.sql', 'The customer list', 'essential',
      to_regclass('public.customers') IS NOT NULL),

  ( 3, 'stock_schema.sql', 'Stock items and their movements', 'essential',
      to_regclass('public.stock_items') IS NOT NULL),

  ( 4, 'extra_columns_migration.sql', 'Supplier email and short name on stock', 'optional',
      EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND column_name='supplier_email')),

  ( 5, 'migrate_orders.sql', 'Archiving an order, and delete by role', 'essential',
      EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name='orders'
                 AND column_name='archived')),

  ( 6, 'migrate_audit_log.sql', 'Who did what, and when', 'recommended',
      to_regclass('public.audit_log') IS NOT NULL),

  ( 7, 'migrate_media_types.sql', 'Media types shared between PCs', 'recommended',
      to_regclass('public.media_types') IS NOT NULL),

  ( 8, 'migrate_stock_alerts.sql', 'Low-stock thresholds on the Dashboard', 'optional',
      to_regclass('public.stock_alerts') IS NOT NULL),

  ( 9, 'migrate_user_management.sql', 'Directors and Admins managing accounts', 'recommended',
      EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
               WHERE n.nspname='public' AND p.proname='update_user_profile')),

  (10, 'migrate_catalog.sql', 'Filter presets shared between PCs', 'recommended',
      to_regclass('public.catalog_lists') IS NOT NULL),

  (11, 'migrate_customer_profiles.sql', 'Short names, regions, job-number rules', 'recommended',
      EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name='customers'
                 AND column_name='short_name')),

  (12, 'migrate_po_inbox.sql', 'Photos sent from a phone', 'optional',
      EXISTS (SELECT 1 FROM storage.buckets WHERE id = 'po-inbox')),

  (13, 'migrate_pricing.sql', 'The price list and rates per square metre', 'recommended',
      to_regclass('public.price_list') IS NOT NULL),

  (14, 'migrate_quotes.sql', 'Saved quotes', 'recommended',
      to_regclass('public.quotes') IS NOT NULL),

  (15, 'migrate_quote_portal.sql', 'Customers accepting a quote online', 'optional',
      EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name='quotes'
                 AND column_name='public_token')),

  (16, 'migrate_staff_access.sql', 'SECURITY - only approved staff can read anything', 'ESSENTIAL',
      EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
               WHERE n.nspname='public' AND p.proname='is_staff')),

  (17, 'migrate_customer_portal.sql', 'Customers seeing their own orders online', 'optional',
      EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
               WHERE n.nspname='public' AND p.proname='portal_orders')),

  (18, 'migrate_portal_signin.sql', 'Signing in by email or purchase order number', 'optional',
      EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
               WHERE n.nspname='public' AND p.proname='portal_sign_in')),

  (19, 'migrate_supplied_order_numbers.sql', 'Our own TAF-ON- order numbers', 'recommended',
      to_regclass('public.taf_order_number_seq') IS NOT NULL),

  (20, 'migrate_performance.sql', 'Speed, and orders past the thousandth appearing', 'recommended',
      to_regclass('public.orders_list') IS NOT NULL),

  (21, 'migrate_scanning.sql', 'Stock counts that cannot be lost or double-counted', 'recommended',
      EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
               WHERE n.nspname='public' AND p.proname='adjust_stock_atomic'))
)
SELECT step,
       CASE WHEN present THEN 'already done' ELSE 'RUN THIS' END AS status,
       needed,
       file,
       purpose
  FROM checks
 ORDER BY present, step;
