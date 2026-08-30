# The AP2 rail - sellable to a real AI buyer

*Author: Vedant Jaiswal. Reproduce with `python scripts/ap2_demo.py` and
`pytest tests/integration/test_ap2.py`.*

BAZAAR now accepts a real, agent-standard payment authorization - Google's
**Agent Payments Protocol (AP2)** - and settles it through the *same* deterministic
gate that guards every other transaction. This is the leap from "a safe
AI-to-AI sandbox" to "**a merchant that a real ChatGPT/Gemini-class agent can buy
from, safely.**"

## The flow

```
AI buyer's credential provider          BAZAAR merchant
  signs a Cart Mandate (ES256 JWS)  ─▶   verify_cart_mandate()   ── AP2 authenticity
   { cart, payee, amount,                    │  ES256 sig, kid registered,
     constraints, exp }                      │  not expired, self-consistent
                                             ▼
                                        to_bazaar()              ── translate
                                             │  mint a trusted-issuer-signed
                                             │  BAZAAR Mandate + TransactionRequest
                                             ▼
                                        the untouched 11-check gate  ── money
                                             │  amount == merchant-of-record price?
                                             │  within cap? category? nonce? ...
                                             ▼
                                        ALLOW → settle (Razorpay test mode)
                                        BLOCK → machine-readable reason code
```

## Division of trust (why this is safe)

- **AP2 layer proves _authenticity_.** A Cart Mandate must be an `ES256` JWS
  signed by a **registered credential provider** (`kid` on an allow-list),
  unexpired, and internally consistent (the signed total equals the signed line
  maths; the payee is permitted). A cart signed by an unknown key is rejected
  before anything else - a rogue agent cannot mint its own authorization.
- **The gate enforces _money_.** The bridge only mints a BAZAAR mandate (signed
  by a **pinned** trusted issuer) *after* AP2 verification passes. The authorized
  amount then faces the same rule as every rail: it must equal the merchant of
  record's price and sit within the signed cap. A validly-signed cart whose price
  disagrees with the merchant of record is a **price tamper**, and the gate
  blocks it with `PRICE_MISMATCH_MERCHANT_RECORD`.

The gate itself is **unchanged** - the new rail feeds it, it does not bypass it.

## Conformance (reproducible)

`python scripts/ap2_demo.py`:

| Cart | Caught at | Result |
|---|---|---|
| legit (real price) | - | ✓ ALLOW |
| price_tamper (price ≠ record) | money gate | ✓ BLOCK `PRICE_MISMATCH_MERCHANT_RECORD` |
| over_budget (> signed cap) | money gate | ✓ BLOCK `MANDATE_LIMIT_EXCEEDED` |
| expired | AP2 authenticity | ✓ BLOCK `AP2_EXPIRED` |
| signature_tamper | AP2 authenticity | ✓ BLOCK `AP2_INVALID_SIGNATURE` |
| untrusted_issuer | AP2 authenticity | ✓ BLOCK `AP2_UNTRUSTED_ISSUER` |

**legit cleared 1/1 · tampers caught 5/5.** 12 tests in
`tests/integration/test_ap2.py`.

## Endpoints

- `GET  /api/ap2/info` - which credential providers this merchant trusts.
- `POST /api/ap2/checkout` - an AI buyer presents an ES256 Cart Mandate JWS.
- `POST /api/ap2/demo` - mint a demo cart (legit or a tamper variant) and run it
  end to end, for the UI and the pitch.

## Honest scope

This bridge verifies the **ES256-signed Cart Mandate** (a JWS with the AP2 field
structure) and settles **single-line carts**. Full SD-JWT *selective disclosure*
and multi-item carts are documented extensions, not claimed as done - the
authenticity + money-integrity guarantees above are what run today.
