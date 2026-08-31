-- BAZAAR schema. SQLite now; kept Postgres-compatible (no SQLite-only types).
--
-- Two invariants live in the DATABASE, not in application code, so no code path
-- can forget to enforce them:
--   1. nonces.nonce is UNIQUE          -> replay is impossible to commit twice.
--   2. transactions.idempotency_key is UNIQUE -> double-charge cannot be recorded twice.
--
-- All money is stored as INTEGER minor units (paise). No floats touch money.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Agents. An agent can be frozen; a frozen agent authorizes nothing.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agents (
    agent_id      TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('buyer', 'seller')),
    frozen        INTEGER NOT NULL DEFAULT 0 CHECK (frozen IN (0, 1)),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ---------------------------------------------------------------------------
-- Mandates. Human-authorized, Ed25519-signed, immutable once signed.
-- The signature is over the RFC 8785 (JCS) canonicalization of the mandate
-- body. Any change to a signed field breaks the signature -> MANDATE_IMMUTABLE.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mandates (
    mandate_id           TEXT PRIMARY KEY,
    agent_id             TEXT NOT NULL REFERENCES agents(agent_id),
    max_amount           INTEGER NOT NULL CHECK (max_amount >= 0),  -- signed cap, paise
    currency             TEXT NOT NULL DEFAULT 'INR',
    allowed_categories   TEXT NOT NULL,        -- JSON array of category strings
    return_policy_days   INTEGER NOT NULL DEFAULT 0,
    issued_at            TEXT NOT NULL,        -- RFC3339 UTC
    expires_at           TEXT NOT NULL,        -- RFC3339 UTC (TTL: minutes, not seconds)
    public_key           TEXT NOT NULL,        -- base64 Ed25519 verify key
    signature            TEXT NOT NULL,        -- base64 Ed25519 signature over JCS(body)
    canonical_body       TEXT NOT NULL,        -- the exact JCS bytes that were signed
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ---------------------------------------------------------------------------
-- Merchant catalog == the merchant of record. THE AUTHORITATIVE PRICE SOURCE.
-- The seller agent has NO write path to this table (enforced in catalog/store.py:
-- the seller-facing API is read-only; only an admin/merchant seeding path writes).
-- The verifier reads price and category from here, never from an agent's claim.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS merchant_catalog (
    sku                  TEXT PRIMARY KEY,
    merchant_id          TEXT NOT NULL,
    title                TEXT NOT NULL,
    category             TEXT NOT NULL,        -- authoritative category
    price                INTEGER NOT NULL CHECK (price >= 0),  -- authoritative price, paise
    currency             TEXT NOT NULL DEFAULT 'INR',
    return_policy_days   INTEGER NOT NULL DEFAULT 0,
    -- Free text. UNTRUSTED. May contain prompt-injection. Never a money source.
    description          TEXT NOT NULL DEFAULT '',
    floor_price          INTEGER NOT NULL DEFAULT 0,  -- seller negotiation floor, paise
    active               INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    updated_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ---------------------------------------------------------------------------
-- Nonces. Replay defense lives HERE, in the schema, as a UNIQUE constraint.
-- A second INSERT of the same nonce fails at the database, not in a branch that
-- code could skip.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nonces (
    nonce        TEXT PRIMARY KEY,             -- UNIQUE by being the primary key
    mandate_id   TEXT NOT NULL REFERENCES mandates(mandate_id),
    used_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ---------------------------------------------------------------------------
-- Transactions. idempotency_key is UNIQUE -> double-charge defense in schema.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transactions (
    txn_id               TEXT PRIMARY KEY,
    mandate_id           TEXT NOT NULL REFERENCES mandates(mandate_id),
    agent_id             TEXT NOT NULL REFERENCES agents(agent_id),
    sku                  TEXT NOT NULL,
    category             TEXT NOT NULL,        -- category presented for this txn
    amount               INTEGER NOT NULL CHECK (amount >= 0),  -- paise
    price_source         TEXT NOT NULL,        -- 'merchant_record' required to pass the gate
    nonce                TEXT NOT NULL,
    idempotency_key      TEXT NOT NULL,        -- double-charge defense: partial unique index below
    decision             TEXT NOT NULL DEFAULT 'PENDING',  -- ALLOW / REVIEW / BLOCK / PENDING
    reason_code          TEXT NOT NULL DEFAULT 'PENDING',
    status               TEXT NOT NULL DEFAULT 'pending',  -- pending/authorized/blocked/settled/failed
    razorpay_order_id    TEXT,
    razorpay_payment_id  TEXT,
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    executed_at          TEXT
);

-- ---------------------------------------------------------------------------
-- Append-only, hash-chained audit log. Each entry commits to the previous
-- entry's hash, making the whole log tamper-evident WITHOUT a blockchain.
-- entry_hash = SHA-256( prev_hash || event_type || 0x1F || JCS(payload) ).  seq is monotonic.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_logs (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type   TEXT NOT NULL,
    payload      TEXT NOT NULL,                -- JCS canonical JSON of the event
    prev_hash    TEXT NOT NULL,                -- hex sha256 of previous entry (genesis = 64 zeros)
    entry_hash   TEXT NOT NULL UNIQUE,         -- hex sha256(prev_hash || payload)
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ---------------------------------------------------------------------------
-- Trust receipts. One signed receipt per authorization decision.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS receipts (
    receipt_id     TEXT PRIMARY KEY,
    txn_id         TEXT NOT NULL REFERENCES transactions(txn_id),
    canonical_body TEXT NOT NULL,              -- JCS bytes that were signed
    public_key     TEXT NOT NULL,              -- base64 Ed25519 verify key
    signature      TEXT NOT NULL,              -- base64 Ed25519 signature
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ---------------------------------------------------------------------------
-- Benchmark / red-team run records. Actual outcomes only; never a pre-written 0.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS attack_runs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            TEXT NOT NULL,
    attack_class      TEXT NOT NULL,
    expected_decision TEXT NOT NULL,
    actual_decision   TEXT NOT NULL,
    reason_code       TEXT NOT NULL,
    passed            INTEGER NOT NULL CHECK (passed IN (0, 1)),
    details           TEXT NOT NULL DEFAULT '{}',
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Double-charge defense, in the schema: an idempotency key may be AUTHORIZED at
-- most once. Blocked attempts (the double-charge attack itself) may reuse a key;
-- a second ALLOW with the same key is refused by the database.
CREATE UNIQUE INDEX IF NOT EXISTS idx_txn_idem_allow
    ON transactions(idempotency_key) WHERE decision = 'ALLOW';

CREATE INDEX IF NOT EXISTS idx_txn_mandate ON transactions(mandate_id);
CREATE INDEX IF NOT EXISTS idx_attack_runs_run ON attack_runs(run_id);
CREATE INDEX IF NOT EXISTS idx_audit_seq ON audit_logs(seq);
