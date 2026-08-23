# BAZAAR — Threat Model

BAZAAR is a deterministic authorization gate for AI-to-AI commerce. The threat
model is the spec. Every attack below maps to one defense and one
machine-readable reason code, and each is exercised live by the red-team harness
and measured at volume by the benchmark.

## Adversary

An **autonomous buyer or seller agent that has been compromised or is acting in
bad faith**. It can:

- propose any amount, category, price, sku, nonce, or idempotency key;
- attempt to rewrite fields of a mandate it was issued;
- replay or resubmit previous transactions;
- embed instructions in catalog free text (prompt injection);
- keep acting after being frozen;
- submit against expired mandates.

The adversary **cannot**: forge an Ed25519 signature without the private key,
write to the merchant-of-record catalog, or bypass the database's UNIQUE
constraints.

## The core invariant (enforced in code, never asserted in prose)

> **No execution path may settle an amount greater than the signed mandate cap,
> and nothing probabilistic may widen authority.**

Probabilistic components (the intent parser, the risk model) may **propose** and
may **tighten** (NORMAL → REVIEW → BLOCK). They can never authorize money and
never raise a limit. Only the deterministic verifier authorizes a payment.

## Two load-bearing rules

### 1. Trusted price source (defends Price + Injection at once)

**The price the verifier trusts is never a value the seller agent supplies.** It
is read from the independent `merchant_catalog` table (the merchant of record),
**snapshotted at offer-time and frozen for the transaction's lifetime.** The
seller agent has **no write path** to that table.

- A seller that lies at offer-time (claims ₹4,499 while the merchant record says
  ₹6,499) is blocked: `PRICE_MISMATCH_MERCHANT_RECORD`.
- A price changed after authorization is blocked at settlement for the same
  reason — the frozen snapshot is the only price that can settle.
- **Prompt injection** in catalog `description` text can move the LLM's *words*
  but not the *money*: the verifier re-checks price and category against the
  signed mandate and the merchant record, neither of which injected text can
  touch. A money-field whose provenance is anything other than `merchant_record`
  is blocked outright: `UNTRUSTED_INSTRUCTION`.

### 2. Razorpay webhook / settlement rule (defends the ambiguous window)

Settlement uses Razorpay Test Mode Orders + Payments with Razorpay-supported
idempotency on payment-mutating operations and **verified webhook signatures**.

**Rule for the ambiguous window between `order.created` and a confirmed
`payment.captured` webhook: default to "NOT PAID."** Reconcile state from
Razorpay as the source of truth. **Never re-charge.**

- A **duplicate webhook** (same event delivered twice) must not double-count:
  idempotent handling keyed on the Razorpay payment id.
- A **late webhook** arriving after a timeout must reconcile, not re-charge.
- An unsigned or wrongly-signed webhook is rejected before any state change.

## Attack classes → defense → reason code

| Class         | Attack                                             | Defense                                             | Reason code                      |
|---------------|----------------------------------------------------|-----------------------------------------------------|----------------------------------|
| Budget        | Spend above the signed cap (₹5,000 → ₹7,000)       | Cap check: `amount ≤ signed cap`                    | `MANDATE_LIMIT_EXCEEDED`         |
| Policy        | Agent rewrites its own `max_amount`                | Ed25519 signature over the mandate is immutable     | `MANDATE_IMMUTABLE`              |
| Price         | False price at offer, or price changed after auth  | Merchant-of-record check (frozen snapshot)          | `PRICE_MISMATCH_MERCHANT_RECORD` |
| Replay        | Same nonce submitted twice                         | DB-unique nonce (constraint in the schema)          | `NONCE_REPLAY`                   |
| Double-charge | Same transaction resubmitted                       | DB-unique idempotency key + Razorpay idempotency    | `DUPLICATE_TRANSACTION`          |
| Category      | Buy an off-mandate item (smartwatch)               | Allowlist: `category ∈ mandate.allowed_categories`  | `CATEGORY_OUTSIDE_MANDATE`       |
| Injection     | Malicious instruction in catalog text              | LLM ≠ authority; money-field must be merchant_record | `UNTRUSTED_INSTRUCTION`          |
| State         | Transact after being frozen                        | Agent state check                                   | `AGENT_FROZEN`                   |
| Expiry        | Submit against an expired mandate                  | TTL check (mandates carry a generous but bounded TTL)| `MANDATE_EXPIRED`                |

## Where the defenses live

- **In the database schema** (not application code): nonce uniqueness (replay),
  idempotency-key uniqueness (double-charge). A code path cannot forget them.
- **In cryptography**: Ed25519 (libsodium via PyNaCl) over RFC 8785 canonical
  JSON. A tampered signed field fails verification. We never hand-roll crypto.
- **In the module boundary**: the deterministic verifier imports nothing from
  the LLM / agent layer. This is enforced by an architecture test.
- **In the merchant of record**: price and category are read from
  `merchant_catalog`, snapshotted at offer-time, never from an agent's claim.

## Explicitly out of scope

No full marketplace, reputation network, trust graph, blockchain, custom agent
protocol, multi-round negotiation, real-money transactions, or production payment
infrastructure. Those are named as future work, not attempted and left
half-done. Settlement is Razorpay **Test Mode** only.
