# BAZAAR

**Adversarial infrastructure for autonomous commerce.**
AI agents can transact. BAZAAR measures whether they *should be allowed to*.

> Razorpay AI Buildathon 2026 · Track 01 — AI Growth & Agentic Commerce
> Settlement on Razorpay **Test Mode** only. No live money.

---

## The invariant

> **No execution path may settle an amount greater than the signed mandate cap,
> and nothing probabilistic may widen authority.**

LLMs **propose**. Policies **constrain**. A deterministic verifier **authorizes**.
Razorpay **executes**. Receipts **prove**. The red team **challenges**.

## The threat model in one line

A compromised buyer or seller agent tries to overspend, replay a payment, change
a price after authorization, escape its category, or smuggle instructions through
untrusted catalog text — and BAZAAR blocks each with a specific, machine-readable
reason code, not "the AI decided no." See [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md).

## The four numbers that matter

Printed by `make benchmark` — reproduce them yourself. The block rates are
deterministic (the gate is a fixed checklist); the fuzzer seed varies per run but
the violation count is always 0. This project never ships a fabricated number: a
value not yet produced by a real run reads `UNVERIFIED`.

| Number                                       | Value (reproduce with `make benchmark`)        |
|----------------------------------------------|------------------------------------------------|
| Adversarial block rate (144 attacks, 9 classes) | **100%** — every class, correct reason code |
| False-block rate on legitimate traffic (400, incl. boundaries) | **0%**                        |
| Held-out result (72 fresh, unseen attacks)   | **100%** block, 0% false-block                 |
| Fuzzer: actual spend-cap violations          | **0** over 20,000 random states                |

Economic axis (same harness): bounded upsell lifted average order value by
**~7.7%**, with **100%** of upsold orders still clearing the same gate. The
advisory risk model is reported separately (precision 1.00) and never merged with
gate correctness.

## Demo screens

Six screens (React + TypeScript + Vite), each driving the real backend — nothing mocked.

**Bounded negotiation → deterministic settlement** (the agreed price sits between the
seller's floor and the buyer's cap):

![Transaction screen](docs/screens/03_transaction.png)

**Red-team harness** — fire all nine attack classes live; each returns its specific reason code:

![Red team screen](docs/screens/07_redteam.png)

**Benchmark scoreboard** — the four numbers, produced by `make benchmark`, with the advisory
risk model reported separately:

![Benchmark screen](docs/screens/08_benchmark.png)

## Quickstart

```bash
make setup       # venv + install + initialize the database
make test        # unit + property + security tests
make fuzz        # property-based fuzzer against the spend-cap invariant
make benchmark   # regenerate datasets, run gate + fuzzer, print the scoreboard
make demo        # scripted end-to-end run (no network needed)
make run         # start the FastAPI backend on :8000
```

Razorpay Test Mode settlement (Phase 2) needs test keys — copy `.env.example`
to `.env` and fill them in. The rest of the system runs with no keys at all.

## What BAZAAR builds — six components

1. **Intent Compiler & Signed Mandate** — natural-language request → structured
   mandate; the human confirms the rendered mandate, then it is Ed25519-signed
   and locked with a generous but bounded TTL.
2. **Deterministic Authorization Gate** — the heart: a fixed checklist (cap,
   category, price == merchant of record, signature valid + unexpired, nonce
   unused, not frozen, not already executed) → ALLOW or a reason code.
3. **Buyer & Seller Agents + Bounded Negotiation** — one negotiation round
   clamped between the buyer's cap and the seller's floor, both visible on screen.
4. **Razorpay Test-Mode Settlement** — real Orders + Payments with idempotency
   and verified webhooks; the ambiguous window defaults to "not paid," reconciles
   from Razorpay, never re-charges.
5. **Trust Receipt + Hash-Chained Audit Log** — every authorization emits a
   signed receipt; each log entry chains the previous entry's hash, making the
   whole log tamper-evident without a blockchain.
6. **Red-Team Harness + Benchmark** — an adversarial agent attacks the live gate
   across nine attack classes; a property-based fuzzer attacks the core invariant;
   the benchmark measures block rates, false-block rate, and honest escapes.

## Repository shape

```
bazaar/
├── backend/     intent/ policy/ verifier/ risk/ razorpay/ receipt/ ledger/ redteam/ agents/ catalog/
├── frontend/    six demo screens (React + TS + Vite)
├── tests/       unit/ integration/ property/ security/
├── benchmarks/  one-command runner → scoreboard
├── docs/        THREAT_MODEL.md  ARCHITECTURE.md  EVAL.md
├── README.md
└── Makefile     setup · test · fuzz · benchmark · run · demo
```

## Honesty rules this repo holds itself to

- **No fabricated results — ever.** Numbers come from commands that actually ran.
  Anything not yet run is labeled `UNVERIFIED`.
- **Reason codes, not vibes.** Every block returns a machine-readable code.
- **Secrets never in git.** `.env` is git-ignored; `.env.example` shows the shape.
- **Never hand-rolled crypto.** Ed25519 via libsodium (PyNaCl); JCS via `rfc8785`.

## License

MIT — see [`LICENSE`](LICENSE).
