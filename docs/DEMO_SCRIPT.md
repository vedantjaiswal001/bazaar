# BAZAAR — the five-minute demo

Open on honesty, not on a shopping cart. The sequence is engineered so the most
senior-engineer moments — the live tamper-fail, the fuzzer, the honest escape
number — land hardest. Every screen below drives the real backend.

**Setup (before you present):**
```bash
make setup && make benchmark      # generates the scoreboard the UI reads
make run                          # backend on :8000  (terminal 1)
make web                          # frontend on :5173 (terminal 2)
```

---

### 0:00–0:30 · Hook — open mid-attack
Open on the **Red Team** screen. Click **Fire all 9**. Nine attack cards light up
`BLOCK` with nine different reason codes. Say: *"These are AI agents trying to spend
money they weren't authorized to. This is the gate stopping each one — and telling
you exactly which rule fired, not 'the AI decided no.'"*

### 0:30–1:30 · Happy path, fast
Go to **Intent**. Type *"running shoes under ₹5,000, 30-day returns, buy
automatically."* Compile → the human-readable mandate appears (cap ₹5,000,
footwear, 30-day). Click **Confirm & sign**. On **Transaction**, the bounded
negotiation plays out between the two walls — seller floor and buyer cap, both on
screen — and the verifier ticks green to `ALLOW`. *(With Razorpay test keys wired,
click Settle here for a real test-mode payment.)*

### 1:30–2:00 · Trust Receipt + live verification
**Trust Receipt** → **Verify signature**: `VALID`. Then **Tamper amount → ₹99,999**:
`INVALID`. *"The cryptography is real, not decorative."* One line: *"and across the
benchmark, the seller's bounded upsell lifted average order value by ~7.7% — every
rupee of it through this same gate."*

### 2:00–3:30 · Red team, by class
Back to **Red Team**. Walk 3–4 cards individually: over-cap →
`MANDATE_LIMIT_EXCEEDED`; price changed → `PRICE_MISMATCH_MERCHANT_RECORD`; catalog
injection → `UNTRUSTED_INSTRUCTION`; frozen agent → `AGENT_FROZEN`. *"Each returns a
machine-readable reason code — this is measurable, not vibes."*

### 3:30–4:15 · The fuzzer
Drop to a terminal: `make fuzz`. *"I didn't only try attacks I designed. A
property-based fuzzer threw tens of thousands of random states at the spend-cap
invariant."* Read the actual number off the screen — **0 violations** — and note the
seed makes it reproducible. *"Zero is great; if it had found one, I'd keep it and
explain it. The number is never written before the run."*

### 4:15–5:00 · Honest metrics + the thesis
**Benchmark** screen. The four numbers: 100% adversarial block, 0% false-block on
legitimate traffic (including boundary cases), 100% held-out on fresh attacks, 0
fuzzer violations. Point out the risk classifier is reported **separately**
(precision/recall) and never merged with gate correctness. Close:
*"Autonomous commerce doesn't become trustworthy when we say it's safe. It becomes
trustworthy when we can measure where it fails. That's BAZAAR."*

---

**Fallbacks if the network wobbles:** the whole demo except live Razorpay settlement
runs offline (`make demo` is a scripted end-to-end run). Once test keys are wired,
record a short clip of one successful real test-mode payment as a backup for the
settlement moment.
