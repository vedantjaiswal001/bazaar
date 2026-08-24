# BAZAAR - the five-minute demo (run-of-show)

Open on honesty, not on a shopping cart. The sequence is engineered so the
senior-engineer moments - the live tamper-fail, the fuzzer, the honest escape
number, one real Razorpay payment - land hardest. Every screen drives the real
backend.

There are two ways to record. **Option A** is the safest single take and needs no
UI. **Option B** is more visual. Pick one; both hit the same beats.

---

## Before you record

```bash
make setup                 # once: venv + install + init db
make benchmark             # generates the scoreboard the UI reads
```

For the live payment moment, have `.env` filled with your Razorpay **Test Mode**
keys and `pip install razorpay python-dotenv` done inside the venv.

Screen-recording tip: a dark terminal, ~16pt font, and `make showcase` (it has
built-in pauses via `--pace 0.6`) make a clean one-take recording.

---

## Option A - one-command terminal demo (recommended, ~4 min)

This is the whole story in two commands. It is the most reliable take because
nothing depends on a browser or a dev server.

### 0:00-0:20 · The thesis
Run:
```bash
make showcase           # (uses --pace 0.6 for on-screen pauses)
```
Read the three header lines aloud: *"LLMs propose, policies constrain, a
deterministic verifier authorizes - nothing probabilistic can widen authority.
The agent cannot overspend."*

| On screen | Say |
|-----------|-----|
| **Beat 1** - mandate compiled, Ed25519 signed, negotiation clamped between two walls, verifier ticks all green to `ALLOW`, receipt `valid: True` | "A human signs a spending mandate. The agent negotiates only *between* the cap and the seller's floor. The gate checks every rule and allows it - and signs a receipt." |
| **Beat 2** - tamper the receipt amount to ₹99,999 → `verifies: False` | "Change one field of that receipt and the signature breaks. The cryptography is real, not decorative." |
| **Beat 3** - nine attack classes, nine `BLOCK` lines, nine reason codes | "Nine different agents trying to cheat. Each is blocked - and told exactly which rule fired, not 'the AI decided no.'" |
| **Beat 4** - audit chain intact, then one past entry edited → `first break at seq N` | "The audit log is hash-chained. Edit any past entry and verification points at the exact break." |
| **Beat 5** - live scoreboard: 100% blocked, 0% false-block, 0 escapes, +7.72% AOV | "And the honest scoreboard, computed in this run: 100% of attacks blocked, zero false blocks on legitimate traffic, zero escapes - and the bounded upsell still lifted order value, every rupee through the same gate." |

### 4:00-5:00 · One real Razorpay payment
Run:
```bash
make live
```

| On screen | Say |
|-----------|-----|
| Gate ALLOWs, then a **real** `order_...` id prints, status `pending_settlement` | "Now the real thing. The gate authorizes, we create a genuine Test Mode order on Razorpay - and until a payment is confirmed, we default to NOT PAID." |
| Browser opens the checkout; pay with test card `4111 1111 1111 1111` | "I pay with Razorpay's test card. No real money." |
| Press Enter → reconcile settles once; `settle again` / `reconcile again` → already settled | "We reconcile against Razorpay itself and settle exactly once. Retry it - it never charges twice." |
| Close: | "Explainable, bounded, gated, audited - and it really touches Razorpay. That's BAZAAR." |

---

## Option B - UI walkthrough (~5 min, more visual)

```bash
make run                   # backend on :8000  (terminal 1)
make web                   # frontend on :5173 (terminal 2)
```

### 0:00-0:30 · Hook - open mid-attack
Open on the **Red Team** screen. Click **Fire all 9**. Nine cards light `BLOCK`
with nine reason codes. *"These are AI agents trying to spend money they weren't
authorized to. This is the gate stopping each one, and naming the rule."*

### 0:30-1:30 · Happy path, fast
**Intent** → type *"running shoes under ₹5,000, 30-day returns, buy
automatically."* Compile → the human-readable mandate appears. **Confirm & sign.**
On **Transaction**, the bounded negotiation plays between the two walls and the
verifier ticks green to `ALLOW`.

### 1:30-2:00 · Trust Receipt + live verification
**Trust Receipt → Verify signature**: `VALID`. **Tamper amount → ₹99,999**:
`INVALID`. *"The cryptography is real."* One line: *"across the benchmark, the
bounded upsell lifted average order value ~7.7% - every rupee through this gate."*

### 2:00-3:30 · Red team, by class
Walk 3-4 cards individually: over-cap → `MANDATE_LIMIT_EXCEEDED`; price changed →
`PRICE_MISMATCH_MERCHANT_RECORD`; catalog injection → `UNTRUSTED_INSTRUCTION`;
frozen agent → `AGENT_FROZEN`. *"Machine-readable reason codes - measurable, not
vibes."*

### 3:30-4:15 · The fuzzer
Drop to a terminal: `make fuzz`. *"I didn't only try attacks I designed - a
property-based fuzzer threw tens of thousands of random states at the spend-cap
invariant."* Read the real number: **0 violations**. *"Zero is great; if it found
one, I'd keep it and explain it. The number is never written before the run."*

### 4:15-5:00 · Honest metrics + one real payment
**Benchmark** screen: 100% block, 0% false-block, 100% held-out, 0 fuzzer
violations, risk classifier reported **separately**. If time allows, run
`make live` for one real Test Mode payment. Close: *"Autonomous commerce becomes
trustworthy when we can measure where it fails. That's BAZAAR."*

---

**Fallback:** everything except the live Razorpay payment runs offline
(`make showcase`). Record one successful `make live` payment as a short backup
clip so the settlement moment is safe even if the network wobbles live.
