# BUILD STATUS

Honest build log. A checkpoint is marked complete only when the command actually
ran successfully. Anything not yet run says so.

## Current phase: Phase 0 → Phase 1

## Phases

### ✅ Phase 0 — Scaffolding
- Repo structure, Makefile, module seams, SQLite schema, docs.
- `docs/THREAT_MODEL.md` states the trusted-price-source rule and the Razorpay
  webhook / ambiguous-window rule explicitly.
- **Checkpoint command:** `make setup`
- **Status:** see the checkpoint output recorded below once run.

### ⬜ Phase 1 — Deterministic verifier + property tests (THE CORE)
- Mandate model, Ed25519 signing over JCS, the fixed-checklist verifier,
  property-based tests for the spend-cap invariant and nonce uniqueness.
- **Checkpoint:** property tests pass; fuzzer prints the real violation count.

### ⬜ Phase 2 — Razorpay Test Mode settlement
- Needs Vedant's Razorpay **test-mode** API keys. Deferred until then.

### ⬜ Phase 3 — Trust Receipt + hash-chained audit log
### ⬜ Phase 4 — Agents + merchant catalog + bounded negotiation
### ⬜ Phase 5 — Red-team harness + benchmark + revenue axis
### ⬜ Phase 6 — Frontend + demo polish

## Known constraints
- Razorpay network settlement can only be validated once test keys are provided
  and the Razorpay API is reachable from the run environment.

## Log
- Phase 0 files created; `make setup` checkpoint output recorded in the commit
  that closes Phase 0.
