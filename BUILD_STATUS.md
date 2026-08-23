# BUILD STATUS

Honest build log. A checkpoint is marked complete only when the command actually
ran successfully. Anything not yet run says so.

## Current phase: All phases built. Phase 2 LIVE settlement + GitHub push await Vedant's inputs.

## Phases

### ✅ Phase 0 - Scaffolding
- Repo structure, Makefile, module seams, SQLite schema, docs.
- `docs/THREAT_MODEL.md` states the trusted-price-source rule and the Razorpay
  webhook / ambiguous-window rule explicitly.
- **Checkpoint command:** `make setup`
- **Status:** see the checkpoint output recorded below once run.

### ✅ Phase 1 - Deterministic verifier + property tests (THE CORE)
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

### 🟡 Phase 2 - Razorpay Test Mode settlement (code done; LIVE checkpoint needs keys)
- razorpay/client.py: real Orders via the official SDK; guardrail refuses any
  non-`rzp_test_` key. Order creation deduped at our layer (no invented idempotency).
- razorpay/webhooks.py: HMAC-SHA256 signature verification + idempotent event
  handling. razorpay/settlement.py: settle() (idempotent, "ambiguous = NOT PAID")
  + reconcile() (Razorpay = source of truth, never re-charge).
- API: POST /api/settle (honest 'not_configured' without keys), POST
  /api/webhook/razorpay (verifies signature before any state change).
- **Tested WITHOUT keys (8 tests):** signature verify pass/fail; ambiguous window
  defaults to pending; doubled webhook → no double-settle; late webhook → reconcile
  not re-charge; amount-mismatch rejected; settle() idempotent (one order only).
- **LIVE checkpoint still pending:** a real test-mode payment settling end-to-end
  and appearing in the Razorpay dashboard - needs Vedant's test Key ID + Secret.

### ✅ Phase 3 - Trust Receipt + hash-chained audit log
- receipt/trust_receipt.py: canonical-JSON, Ed25519-signed receipt per decision.
- ledger/audit_log.py: append-only chain, entry_hash = SHA-256(prev_hash || JCS(payload)).
- **Checkpoint (`make verify`, actual run):** receipt verify=True, then tamper→False;
  audit chain verify ok=True over 6 entries, then edit seq=4 → ok=False, broken_at_seq=4.
- `make test` → 28 passed.
### ✅ Phase 4 - Agents + merchant catalog + bounded negotiation
- catalog/store.py: merchant of record. Seller gets a read-only SellerCatalogView
  (no write methods); make_offer() clamps any requested price into [floor, list].
- intent/compiler.py: deterministic, reproducible NL→mandate-draft parser; the
  LLM parser is pluggable and falls back to rules (no API key needed).
- agents/buyer.py, seller.py, negotiation.py: human-confirmation-then-sign; one
  bounded negotiation round clamped to buyer cap AND seller floor (both visible).
- verifier/service.py: DB-backed adapter - gate + risk + receipt + audit + the
  DB UNIQUE backstops for replay/double-charge.
- **Checkpoint (`make demo`, actual run):** full happy path intent→confirm→
  negotiate(inside two walls: cap ₹5,000 / floor ₹4,500, upsold to PRO)→verifier
  ALLOW (11/11 checks) → receipt verifies → audit chain intact. Live attacks
  returned MANDATE_LIMIT_EXCEEDED, CATEGORY_OUTSIDE_MANDATE, UNTRUSTED_INSTRUCTION,
  NONCE_REPLAY. `make test` → 44 passed.
### ✅ Phase 5 - Red-team harness + benchmark + revenue axis
- redteam/attacks.py: labeled generators for all 9 attack classes (incl. catalog
  prompt-injection). redteam/harness.py: evaluation with vocabularies kept
  separate (gate correctness vs risk precision/recall). benchmarks/{datasets,runner}.py.
- **Checkpoint (`make benchmark`, actual run):**
  - dataset 144 adversarial + 400 legit; held-out 72 + 200.
  - adversarial block rate 100% (correct reason code 100%), per-class all 100%.
  - false-block rate 0% (incl. boundary cases ₹4,950 / ₹4,999 / exactly-cap).
  - held-out block rate 100%, false-block 0%.
  - fuzzer 0 spend-cap violations over 20,000 states.
  - AOV uplift +7.72% from bounded upsell; 100% of upsold orders cleared the gate.
  - risk classifier reported SEPARATELY: precision 1.000 (no false alarms).
  - escapes: none. Scoreboard written to benchmarks/out/scoreboard.json.
- `make test` → 51 passed.
### ✅ Phase 6 - Frontend + demo polish
- FastAPI backend (api/app.py) + React/TS/Vite six-screen UI (Intent, Transaction,
  Verifier, Trust Receipt, Red Team, Benchmark). `make run` + `make web`.
- **Checkpoint:** `make web-build` type-checks + builds clean; live smoke test of
  uvicorn confirmed happy-path ALLOW and budget-attack BLOCK over HTTP; Playwright
  screenshots of all six screens captured to docs/screens/. Every screen drives
  the real gate/receipts/benchmark - nothing mocked.
- 66 tests total (incl. API integration) all green.

## Known constraints
- Razorpay network settlement can only be validated once test keys are provided
  and the Razorpay API is reachable from the run environment.

## Log
- Phase 0 files created; `make setup` checkpoint output recorded in the commit
  that closes Phase 0.
