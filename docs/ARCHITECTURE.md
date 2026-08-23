# BAZAAR - Architecture

## One principle

Separate what is *smart* from what is *trusted*. Probabilistic components inform;
deterministic rules decide.

```
Human intent
   │  (probabilistic, advisory only)
   ▼
LLM / rule parser  ──proposes──►  structured mandate DRAFT
   │
   ▼
Human confirmation ──►  SIGN (Ed25519 over JCS)   ← the only thing that authorizes
   │
   ▼
Policy engine + Deterministic verifier  ──►  ALLOW  /  BLOCK(reason_code)
   │                                              │
   │  (risk signal may only TIGHTEN)              │
   ▼                                              ▼
Razorpay Test Mode  ──►  webhook  ──►  Trust Receipt (signed) ──► hash-chained log
```

## Modules (hard seams)

| Module            | Responsibility                                                        | Trusted? |
|-------------------|-----------------------------------------------------------------------|----------|
| `intent/`         | Parse natural language → mandate draft (deterministic, LLM-pluggable) | No       |
| `policy/`         | Constraints: category allowlist, caps, risk escalation                | Yes      |
| `verifier/`       | **The gate.** Fixed checklist → ALLOW or one reason code              | **Yes**  |
| `risk/`           | Advisory risk signal; may only tighten the gate                       | No       |
| `catalog/`        | Merchant of record - authoritative price/category, seller read-only   | Yes      |
| `agents/`         | Buyer + seller agents; bounded negotiation                            | No       |
| `crypto/`         | Ed25519 signing + RFC 8785 canonical JSON (vetted libs only)          | Yes      |
| `ledger/`         | Append-only, hash-chained audit log                                   | Yes      |
| `receipt/`        | Signed Trust Receipt + live verify                                    | Yes      |
| `razorpay/`       | Test-mode Orders + Payments + verified webhooks                       | Yes      |
| `redteam/`        | Adversarial agent + property fuzzer                                   | -        |
| `db/`             | SQLite schema + access; UNIQUE constraints enforce two defenses       | Yes      |

## The boundary that must not blur

`verifier/` imports **nothing** from `intent/`, `agents/`, or any LLM code. This
is enforced by `tests/security/test_module_boundary.py`, which fails the build
if the deterministic core ever imports the probabilistic layer.

## Stack

- **Backend:** Python 3.10+, FastAPI. Money is always integer paise.
- **Crypto:** PyNaCl (Ed25519 / libsodium) + `rfc8785` (JCS). Never hand-rolled.
- **Data:** SQLite (Postgres-compatible schema). Replay + double-charge defenses
  live in UNIQUE constraints, not application code.
- **Frontend:** React + TypeScript + Vite. Six screens, functional not flashy.
- **Testing:** pytest + Hypothesis (property-based fuzzing of the core invariant).
