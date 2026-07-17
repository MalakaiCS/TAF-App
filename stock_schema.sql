-- ============================================================
-- TAF Order App – Stock Management Schema
-- Run this in Supabase Dashboard → SQL Editor
-- ============================================================

-- Stock items (master catalogue)
CREATE TABLE IF NOT EXISTS stock_items (
    id                  uuid        DEFAULT gen_random_uuid() PRIMARY KEY,
    name                text        NOT NULL,
    sku                 text        DEFAULT '',
    product_type        text        NOT NULL DEFAULT 'Other',
    description         text        DEFAULT '',
    unit                text        DEFAULT 'each',
    stock_on_hand       numeric(12, 3) DEFAULT 0,
    minimum_on_hand     numeric(12, 3) DEFAULT 0,
    image_url           text        DEFAULT '',
    location            text        DEFAULT '',
    supplier            text        DEFAULT '',
    notes               text        DEFAULT '',
    created_by_name     text        DEFAULT '',
    created_at          timestamptz DEFAULT now(),
    updated_at          timestamptz DEFAULT now()
);

-- Stock movement history
CREATE TABLE IF NOT EXISTS stock_transactions (
    id                  uuid        DEFAULT gen_random_uuid() PRIMARY KEY,
    stock_item_id       uuid        REFERENCES stock_items(id) ON DELETE CASCADE,
    transaction_type    text        NOT NULL,   -- receive | use | count | writeoff
    quantity_change     numeric(12, 3) NOT NULL,
    quantity_after      numeric(12, 3) NOT NULL,
    notes               text        DEFAULT '',
    username            text        DEFAULT '',
    created_at          timestamptz DEFAULT now()
);

-- Row-level security
ALTER TABLE stock_items       ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_transactions ENABLE ROW LEVEL SECURITY;

-- All authenticated users can read
CREATE POLICY "stock_items_select"
    ON stock_items FOR SELECT TO authenticated USING (true);

CREATE POLICY "stock_items_insert"
    ON stock_items FOR INSERT TO authenticated WITH CHECK (true);

CREATE POLICY "stock_items_update"
    ON stock_items FOR UPDATE TO authenticated USING (true);

CREATE POLICY "stock_items_delete"
    ON stock_items FOR DELETE TO authenticated USING (true);

CREATE POLICY "stock_tx_select"
    ON stock_transactions FOR SELECT TO authenticated USING (true);

CREATE POLICY "stock_tx_insert"
    ON stock_transactions FOR INSERT TO authenticated WITH CHECK (true);

-- Storage bucket for product images
-- Go to Supabase → Storage → New Bucket
-- Name: stock-images
-- Public: YES  (so image URLs work without auth tokens)
-- Then add this policy to the bucket:
--   Authenticated users can upload/update/delete
