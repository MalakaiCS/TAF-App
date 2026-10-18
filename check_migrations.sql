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
               WHERE n.nspname='public' AND p.proname='adjust_stock_atomic')),

  (22, 'migrate_avatars.sql', 'Profile pictures on accounts', 'optional',
      EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name='profiles'
                 AND column_name='avatar_url')),

  (23, 'migrate_bulk_status.sql', 'Marking a batch of orders complete without losing notes', 'recommended',
      EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
               WHERE n.nspname='public' AND p.proname='merge_order_header')),

  (24, 'migrate_line_progress.sql', 'Ticking an order off one line at a time', 'recommended',
      EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
               WHERE n.nspname='public' AND p.proname='set_order_line_made')),

  (25, 'migrate_recurring_jobs.sql', 'Jobs that come round every 3 or 6 months', 'optional',
      to_regclass('public.recurring_jobs') IS NOT NULL),

  (26, 'migrate_margin.sql', 'What a job costs, next to what it sells for', 'optional',
      EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name='price_list'
                 AND column_name='unit_cost')),

  (27, 'migrate_order_files.sql', 'Photos and a signature kept with an order', 'optional',
      to_regclass('public.order_files') IS NOT NULL),

  (28, 'migrate_notifications.sql', 'A morning summary of what needs doing', 'optional',
      to_regclass('public.notify_settings') IS NOT NULL),

  (29, 'migrate_features.sql', 'Switching new features on, and how the workshop cuts', 'recommended',
      to_regclass('public.feature_switches') IS NOT NULL),

  (30, 'migrate_more_features.sql', 'Kits, sites, returns, stocktakes, buying, agreed prices, shutdowns', 'optional',
      to_regclass('public.kits') IS NOT NULL),

  (31, 'migrate_quote_shipping.sql', 'Delivery charged on a quote, so the counter and the invoice agree', 'recommended',
      EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name='quotes'
                 AND column_name='shipping')),

  (32, 'migrate_supply_requests.sql', 'Asking for supplies, and the bell that tells managers', 'recommended',
      to_regclass('public.supply_requests') IS NOT NULL
      AND to_regclass('public.notifications') IS NOT NULL),

  (33, 'migrate_packing_and_merge.sql', 'Weights, packing, delivery labels and merging customers', 'recommended',
      to_regclass('public.calc_settings') IS NOT NULL
      AND to_regclass('public.customer_merges') IS NOT NULL
      AND to_regprocedure('public.merge_customers(text,uuid,uuid[],jsonb,jsonb)') IS NOT NULL),

  (34, 'migrate_c_channel.sql', 'C-channel weights: material, centre widths and measured weights', 'recommended',
      EXISTS (SELECT 1 FROM pg_constraint
               WHERE conname = 'calc_settings_key_check'
                 AND pg_get_constraintdef(oid) LIKE '%c_channel%')),

  (35, 'migrate_label_switches.sql', 'Switching delivery labels off, for a customer or for everyone', 'recommended',
      EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name='customers'
                 AND column_name='delivery_labels')),

  (36, 'migrate_merge_names.sql', 'An account''s name follows onto its orders after a merge or rename', 'recommended',
      to_regprocedure('public.sync_customer_order_names(uuid)') IS NOT NULL),

  (37, 'migrate_xero_link.sql', 'Xero linked: orders become draft invoices, approved and emailed when complete', 'recommended',
      to_regclass('public.xero_invoices') IS NOT NULL
      AND to_regprocedure('public.xero_orders_to_draft(integer)') IS NOT NULL
      AND EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='xero_connection'
                     AND column_name='mode')),

  (38, 'migrate_price_tiers.sql', 'Three price tiers: each customer on Tier 1, 2 or 3', 'recommended',
      EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name='customers'
                 AND column_name='price_tier')
      AND EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name='price_list'
                 AND column_name='unit_price_3')),

  (39, 'migrate_customer_xero_delivery.sql', 'A customer''s Xero contact and delivery fee', 'recommended',
      EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name='customers'
                 AND column_name='delivery_fee')),

  (40, 'migrate_purchasing.sql', 'Buying through Xero: suppliers, items, multi-item requests, receiving into stock', 'recommended',
      to_regclass('public.suppliers') IS NOT NULL
      AND to_regprocedure('public.receive_purchase(uuid,jsonb)') IS NOT NULL),

  (41, 'migrate_stock_images.sql', 'The storage bucket for pictures of stock items', 'recommended',
      EXISTS (SELECT 1 FROM storage.buckets WHERE id = 'stock-images')),

  (42, 'migrate_stock_suppliers.sql', 'Where each stock item comes from: suppliers, their codes and prices', 'recommended',
      to_regclass('public.stock_item_suppliers') IS NOT NULL),

  (43, 'migrate_supply_bell.sql', 'The bell only shows supply requests still waiting', 'recommended',
      COALESCE(pg_get_functiondef(to_regprocedure('public.settle_supply_notifications()'))
               LIKE '%DELETE FROM public.notifications%', false)),

  (44, 'migrate_floor.sql', 'The factory floor: TV board, job timer, QC checks, faults, finished-job photos', 'recommended',
      to_regclass('public.job_times') IS NOT NULL
      AND to_regclass('public.qc_checklists') IS NOT NULL),

  (45, 'migrate_planning.sql', 'Staff roster and leave, and warning when a due date is already full', 'recommended',
      to_regclass('public.staff_roster') IS NOT NULL
      AND to_regclass('public.staff_leave') IS NOT NULL),

  (46, 'migrate_sales.sql', 'Chasing quotes, why they are lost, service reminders, price changes', 'recommended',
      to_regclass('public.price_changes') IS NOT NULL
      AND EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='quotes'
                     AND column_name='lost_reason')),

  (47, 'migrate_stock_insight.sql', 'Stocktakes on the phone, stock spoken for, supplier prices and lead times', 'recommended',
      to_regclass('public.stock_reserved') IS NOT NULL
      AND to_regclass('public.supplier_lead_times') IS NOT NULL),

  (48, 'migrate_delivery_money.sql', 'Route order, proof of delivery, order values, sales targets, owner''s report', 'recommended',
      to_regclass('public.delivery_runs') IS NOT NULL
      AND to_regclass('public.order_values') IS NOT NULL
      AND to_regclass('public.owner_reports') IS NOT NULL),

  (49, 'migrate_staff_board.sql', 'How-to library, noticeboard and group chats with who-may-do-what', 'recommended',
      to_regclass('public.sops') IS NOT NULL
      AND to_regclass('public.chat_messages') IS NOT NULL
      AND to_regclass('public.chat_rules') IS NOT NULL),

  (50, 'migrate_direct_messages.sql', 'Private messages between two people', 'recommended',
      to_regprocedure('public.open_direct(uuid)') IS NOT NULL),

  (51, 'migrate_cash_sales.sql', 'The cash sale account: an email asked for each time it is invoiced', 'recommended',
      EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name='customers'
                 AND column_name='cash_sale'))
)
SELECT step,
       CASE WHEN present THEN 'already done' ELSE 'RUN THIS' END AS status,
       needed,
       file,
       purpose
  FROM checks
 ORDER BY present, step;
