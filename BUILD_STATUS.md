# BUILD STATUS

Honest build log. A checkpoint is marked complete only when the command actually
ran successfully. Anything not yet run says so.

## Current phase: Phase 1 done → Phase 3 next (Phase 2 waits on Razorpay keys)

## Phases

### ✅ Phase 0 — Scaffolding
- Repo structure, Makefile, module seams, SQLite schema, docs.
- `docs/THREAT_MODEL.md` states the trusted-price-source rule and the Razorpay
  webhook / ambiguous-window rule explicitly.
- **Checkpoint command:** `make setup`
- **Status:** see the checkpoint output recorded below once run.

### ✅ Phase 1 — Deterministic verifier + property tests (THE CORE)
- Mandate model, Ed25519 signing over JCS, the fixed-checklist verifier,
  property-based tests for the spend-cap invariant and nonce uniqueness.
- **Checkpoint result (actual, from a run on this machine):**
  - `make test` → 20 passed (unit gate truth-table for all 9 attack classes +
    crypto tamper tests + module-boundary test + property tests).
  - `make fuzz` (50,000 iterations, seed 205585394):
    - ALLOW / REVIEW / BLOCK = 13,244 / 0 / 36,756
    - **spend-cap violations = 0** (actual count, not pre-written)
    - price-mismatch escapes = 0
    - all 8 block reason codes + OK exercised.
  - The gate is a PURE FUNCTION (no I/O), so it is exhaustively fuzzable; DB
    state is passed in. The deterministic core imports nothing from the LLM
    layer (enforced by tests/security/test_module_boundary.py).

### ⬜ Phase 2 — Razorpay Test Mode settlement
- Needs Vedant's Razorpay **test-mode** API keys. Deferred until then.

### ✅ Phase 3 — Trust Receipt + hash-chained audit log
- receipt/trust_receipt.py: canonical-JSON, Ed25519-signed receipt per decision.
- ledger/audit_log.py: append-only chain, entry_hash = SHA-256(prev_hash || JCS(payload)).
- **Checkpoint (`make verify`, actual run):** receipt verify=True, then tamper→False;
  audit chain verify ok=True over 6 entries, then edit seq=4 → ok=False, broken_at_seq=4.
- `make test` → 28 passed.
### ✅ Phase 4 — Agents + merchant catalog + bounded negotiation
- catalog/store.py: merchant of record. Seller gets a read-only SellerCatalogView
  (no write methods); make_offer() clamps any requested price into [floor, list].
- intent/compiler.py: deterministic, reproducible NL→mandate-draft parser; the
  LLM parser is pluggable and falls back to rules (no API key needed).
- agents/buyer.py, seller.py, negotiation.py: human-confirmation-then-sign; one
  bounded negotiation round clamped to buyer cap AND seller floor (both visible).
- verifier/service.py: DB-backed adapter — gate + risk + receipt + audit + the
  DB UNIQUE backstops for replay/double-charge.
- **Checkpoint (`make demo`, actual run):** full happy path intent→confirm→
  negotiate(inside two walls: cap ₹5,000 / floor ₹4,500, upsold to PRO)→verifier
  ALLOW (11/11 checks) → receipt verifies → audit chain intact. Live attacks
  returned MANDATE_LIMIT_EXCEEDED, CATEGORY_OUTSIDE_MANDATE, UNTRUSTED_INSTRUCTION,
  NONCE_REPLAY. `make test` → 44 passed.
### ⬜ Phase 5 — Red-team harness + benchmark + revenue axis
### ⬜ Phase 6 — Frontend + demo polish

## Known constraints
- Razorpay network settlement can only be validated once test keys are provided
  and the Razorpay API is reachable from the run environment.

## Log
- Phase 0 files created; `make setup` checkpoint output recorded in the commit
  that closes Phase 0.
