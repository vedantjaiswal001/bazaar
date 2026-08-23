# BAZAAR - submission one-pager

**Razorpay AI Buildathon 2026 · Track 01 - AI Growth & Agentic Commerce**

One sentence: **BAZAAR is a deterministic authorization gate that lets an AI agent
transact on Razorpay Test Mode while making it impossible for the agent to
overspend, replay a payment, pay a tampered price, leave its category, or be
steered by injected text - and it proves each block with a machine-readable
reason code, a signed receipt, and a tamper-evident audit log.**

## Track 01's bar, met line by line

The track asks: *"Every money action explainable, bounded and gated. Show the
audit trail and one failure handled gracefully."*

| The bar          | How BAZAAR meets it                                                                 | See it |
|------------------|-------------------------------------------------------------------------------------|--------|
| **Explainable**  | Every decision is a fixed checklist; every block returns one of nine reason codes, not "the AI decided." | `make showcase` beat 3 |
| **Bounded**      | Spend is capped by a human-signed mandate; negotiation is clamped between the buyer cap and the seller floor; nothing probabilistic can raise a limit. | `make showcase` beat 1 |
| **Gated**        | One deterministic verifier authorizes money. The LLM and the risk model may only *tighten* (NORMAL → REVIEW → BLOCK), never widen authority. | `backend/bazaar/verifier/gate.py` |
| **Audit trail**  | Every authorization emits an Ed25519-signed Trust Receipt; each audit entry hash-chains the previous one, so editing any past entry is detected. | `make showcase` beat 4, `make verify` |
| **One failure, gracefully** | The Razorpay ambiguous window (order created, capture not yet confirmed) defaults to **NOT PAID**, reconciles from Razorpay as the source of truth, and **never re-charges**. | `make live`, webhook tests |

## Prove every claim - the commands

```bash
make setup        # venv + install + init db
make test         # 76 tests: unit + property + security + integration
make fuzz         # property-based fuzzer vs the spend-cap invariant -> real count
make benchmark    # regenerate datasets, run gate + fuzzer -> the scoreboard
make showcase     # the whole story in one paced, recordable run
make verify       # receipt verify/tamper + audit-chain verify/tamper
make live         # ONE real Razorpay Test Mode payment, end to end
```

## The numbers (reproduce with `make benchmark`)

| Number                                                     | Value        |
|------------------------------------------------------------|--------------|
| Adversarial block rate (144 attacks, 9 classes)            | **100%**, correct reason code every time |
| False-block rate on legitimate traffic (400, incl. edges)  | **0%**       |
| Held-out (72 fresh, unseen attacks)                        | **100%** block, 0% false-block |
| Fuzzer spend-cap violations (20,000 random states)         | **0**        |
| Escapes                                                    | **0** (honestly counted; a real one would be printed) |
| AOV uplift from bounded upsell / share still gated         | **+7.72% / 100%** (a controlled A/B on simulated buyers - see `docs/EVAL.md`) |
| Advisory risk classifier (reported *separately*)           | precision **1.00** |

## Nine attacks → nine reason codes

| Attack | Reason code |
|--------|-------------|
| Spend above the signed cap        | `MANDATE_LIMIT_EXCEEDED` |
| Rewrite the mandate / self-issue one | `MANDATE_IMMUTABLE` |
| False or post-auth price change    | `PRICE_MISMATCH_MERCHANT_RECORD` |
| Replay a nonce                     | `NONCE_REPLAY` |
| Resubmit a paid transaction        | `DUPLICATE_TRANSACTION` |
| Buy off-mandate category           | `CATEGORY_OUTSIDE_MANDATE` |
| Prompt injection in catalog text   | `UNTRUSTED_INSTRUCTION` |
| Transact while frozen              | `AGENT_FROZEN` |
| Use an expired mandate             | `MANDATE_EXPIRED` |

## What makes it credible under questioning

- **Issuer-key pinning.** The buyer agent holds **no** mandate-signing key. The
  verifier pins the mandate to a trusted human/issuer key, so a compromised agent
  cannot mint its own mandate with a bigger cap - the signature must be the
  issuer's, not the agent's. This is what makes "the agent cannot escalate its own
  authority" literally true, not merely asserted.
- **Schema-level defenses.** Nonce uniqueness (replay) and idempotency (double
  charge) live in the database schema, so a code path cannot forget them.
- **No hand-rolled crypto.** Ed25519 via libsodium (PyNaCl); RFC 8785 canonical
  JSON via `rfc8785`.
- **No fabricated numbers, ever.** Anything not produced by a real run reads
  `UNVERIFIED`. Every figure above regenerates from a command.

## Deliberately out of scope (named, not half-built)

No full marketplace, reputation graph, blockchain, custom agent protocol,
multi-round negotiation, or real money. Settlement is Razorpay **Test Mode** only.
These are stated as future work so the built parts can be finished to a high bar
rather than many parts left partial.
