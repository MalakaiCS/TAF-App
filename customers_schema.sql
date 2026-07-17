-- ============================================================
-- TAF Order App – Customer Database Schema
-- Run this in Supabase Dashboard → SQL Editor
-- ============================================================

CREATE TABLE IF NOT EXISTS customers (
    id                  uuid        DEFAULT gen_random_uuid() PRIMARY KEY,

    -- Business identity
    name                text        NOT NULL,           -- Trading / display name used on orders
    legal_name          text        DEFAULT '',         -- Full legal entity name
    abn                 text        DEFAULT '',         -- Australian Business Number
    website             text        DEFAULT '',

    -- Primary contact
    contact_person      text        DEFAULT '',
    contact_role        text        DEFAULT '',         -- e.g. "Purchasing Manager"
    phone               text        DEFAULT '',
    email               text        DEFAULT '',

    -- Delivery address
    delivery_address1   text        DEFAULT '',
    delivery_address2   text        DEFAULT '',
    delivery_city       text        DEFAULT '',
    delivery_state      text        DEFAULT '',
    delivery_postcode   text        DEFAULT '',
    delivery_country    text        DEFAULT 'Australia',

    -- Billing address (may differ)
    billing_same        boolean     DEFAULT true,
    billing_address1    text        DEFAULT '',
    billing_address2    text        DEFAULT '',
    billing_city        text        DEFAULT '',
    billing_state       text        DEFAULT '',
    billing_postcode    text        DEFAULT '',
    billing_country     text        DEFAULT 'Australia',

    -- Financial
    payment_terms       text        DEFAULT 'Net 30',   -- Net 7 | Net 14 | Net 30 | COD | EOM
    currency            text        DEFAULT 'AUD',

    -- Internal
    notes               text        DEFAULT '',
    is_active           boolean     DEFAULT true,
    created_by_name     text        DEFAULT '',
    created_at          timestamptz DEFAULT now(),
    updated_at          timestamptz DEFAULT now()
);

-- Indexes for fast search
CREATE INDEX IF NOT EXISTS customers_name_idx    ON customers (name);
CREATE INDEX IF NOT EXISTS customers_abn_idx     ON customers (abn);
CREATE INDEX IF NOT EXISTS customers_active_idx  ON customers (is_active);

-- Row-level security
ALTER TABLE customers ENABLE ROW LEVEL SECURITY;

CREATE POLICY "customers_select" ON customers FOR SELECT TO authenticated USING (true);
CREATE POLICY "customers_insert" ON customers FOR INSERT TO authenticated WITH CHECK (true);
CREATE POLICY "customers_update" ON customers FOR UPDATE TO authenticated USING (true);
CREATE POLICY "customers_delete" ON customers FOR DELETE TO authenticated USING (true);
