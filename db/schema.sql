-- HDFC RM Assist schema. Applied by `python -m db.seed` against a freshly created
-- `hdfc_rm` database, so no IF NOT EXISTS guards are needed here.

-- ---------------------------------------------------------------------------
-- Bank product catalogue. Read by product_info_agent on the Type 1 path.
-- ---------------------------------------------------------------------------
CREATE TABLE products (
    product_id     SERIAL PRIMARY KEY,
    name           TEXT           NOT NULL,
    category       TEXT           NOT NULL,
    description    TEXT           NOT NULL,
    key_features   TEXT[]         NOT NULL DEFAULT '{}',
    eligibility    TEXT           NOT NULL,
    interest_rate  NUMERIC(5, 2),          -- NULL for products with no headline rate
    fees           TEXT           NOT NULL
);

-- ---------------------------------------------------------------------------
-- Customers. `email` is the join key from an inbound email to a known customer.
-- ---------------------------------------------------------------------------
CREATE TABLE customers (
    customer_id     SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    email           TEXT NOT NULL UNIQUE,
    account_number  TEXT NOT NULL UNIQUE,
    phone           TEXT NOT NULL,
    kyc_status      TEXT NOT NULL CHECK (kyc_status IN ('verified', 'pending', 'expired'))
);

-- ---------------------------------------------------------------------------
-- Inbound RM mailbox.
--   status      - new -> processing (set by intent_classifier) -> answered (set by an RM action)
--   intent_type - NULL until the classifier runs
-- ---------------------------------------------------------------------------
CREATE TABLE emails (
    email_id        SERIAL PRIMARY KEY,
    customer_email  TEXT        NOT NULL,
    subject         TEXT        NOT NULL,
    body            TEXT        NOT NULL,
    received_at     TIMESTAMPTZ NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'new'
                                CHECK (status IN ('new', 'processing', 'answered')),
    intent_type     TEXT        CHECK (intent_type IN ('type_1', 'type_2'))
);

CREATE INDEX emails_status_idx ON emails (status);
CREATE INDEX emails_customer_email_idx ON emails (customer_email);

-- ---------------------------------------------------------------------------
-- Stand-in for core banking / SWIFT. Read by data_retrieval_agent on the Type 2 path.
-- `swift_ref` is only populated for type = 'swift'.
-- ---------------------------------------------------------------------------
CREATE TABLE transactions (
    txn_id        SERIAL PRIMARY KEY,
    customer_id   INTEGER       NOT NULL REFERENCES customers (customer_id),
    type          TEXT          NOT NULL CHECK (type IN ('transfer', 'swift', 'neft', 'rtgs')),
    amount        NUMERIC(14, 2) NOT NULL,
    currency      TEXT          NOT NULL DEFAULT 'INR',
    status        TEXT          NOT NULL
                                CHECK (status IN ('pending', 'completed', 'failed', 'in_transit')),
    reference_no  TEXT          NOT NULL UNIQUE,
    swift_ref     TEXT,
    initiated_at  TIMESTAMPTZ   NOT NULL,
    updated_at    TIMESTAMPTZ   NOT NULL
);

CREATE INDEX transactions_customer_idx ON transactions (customer_id);
CREATE INDEX transactions_swift_ref_idx ON transactions (swift_ref);

-- ---------------------------------------------------------------------------
-- The RM's decision on a drafted reply. One row per email (upserted), holding the
-- CURRENT decision. The full history lives in rm_audit_log.
-- ---------------------------------------------------------------------------
CREATE TABLE rm_responses (
    response_id  SERIAL PRIMARY KEY,
    email_id     INTEGER     NOT NULL UNIQUE REFERENCES emails (email_id),
    draft_text   TEXT        NOT NULL,
    final_text   TEXT,                    -- NULL when rm_action = 'rejected'
    rm_action    TEXT        NOT NULL CHECK (rm_action IN ('accepted', 'rejected', 'edited')),
    edited_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Append-only audit trail of every RM action. Separate from rm_responses because
-- that table is upserted and therefore only ever shows the latest decision, while an
-- audit log must retain supersede-d ones (e.g. reject, then regenerate, then accept).
-- ---------------------------------------------------------------------------
CREATE TABLE rm_audit_log (
    audit_id     SERIAL PRIMARY KEY,
    email_id     INTEGER     NOT NULL REFERENCES emails (email_id),
    action       TEXT        NOT NULL,   -- accepted | rejected | edited | processed | regenerated
    detail       TEXT,
    actor        TEXT        NOT NULL DEFAULT 'RM',
    occurred_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX rm_audit_log_email_idx ON rm_audit_log (email_id);
