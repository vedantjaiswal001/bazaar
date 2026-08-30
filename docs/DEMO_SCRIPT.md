# The five-minute demo - a three-act story

> **Don't trust the agent. Test the authorization boundary.**

Don't demo features in a list. Tell a story in three acts: show the *future*
(agentic commerce), show the *boundary* (a real payment, authorized and settled),
then *try to break it* (the adversarial climax). Every screen drives the real
backend; nothing is mocked.

## Before you record

```bash
make setup                 # once: venv + install + init db
make train                 # writes the calibrated risk-model artifact + eval plots
make benchmark             # generates the scoreboard the Results tab reads
```

For the live payment, put your Razorpay **Test Mode** keys in `.env`. Two ways to
record: **the console** (`make run` + `make web`, open `localhost:5173`) or **one
terminal take** (`make showcase`). The console is more visual; the terminal is the
safest single take. Pick one - both hit the same three acts.

---

## Act 1 - The future (agentic commerce)  ·  0:00-1:15

Open the console (or run `make showcase`). Show an **AI buyer** transacting:

- A natural-language intent compiles into a **human-signed** mandate (the agent
  holds no signing key), and a bounded negotiation settles the price *between* the
  seller's floor and the buyer's cap.
- Then the AP2 rail: click **Legit cart** - a **real ES256-signed Cart Mandate**
  from an AI buyer's credential provider.

> *"This is agentic commerce. An AI agent finds a merchant, receives a signed
> offer, and tries to pay - over a real agent-payments protocol."*

**Judge thinks:** *okay, this is agentic commerce, and it actually runs.*

---

## Act 2 - The boundary (authorized, then settled)  ·  1:15-2:45

Now show the authorization itself - the heart of the project:

```
Buyer authority (signed cap): ₹5,000
Merchant-signed offer:        ₹4,499
Category:                     footwear   ✓
Expiry:                       valid      ✓
Amount ≤ cap · price = record · nonce fresh · not replayed ...
→ 11/11 checks pass → ALLOW  ·  dual-signed
```

- The **Trust Receipt** verifies (`VALID`); tamper one field → `INVALID`. *"The
  cryptography is real, not decorative."*
- Then run **`make live`** - one **real Razorpay Test Mode** order, pay with the
  test card, reconcile settles exactly once, a retry refuses to double-charge.

> *"It doesn't just decide - it settles, on real Razorpay Test Mode, and it can
> never charge twice."*

**Judge thinks:** *okay, this genuinely works, end to end.*

---

## Act 3 - Try to break it (the climax)  ·  2:45-4:30

The turn. *"Now let's attack it."* Fire the adversarial suite: in the console
click each attack, or run `make benchmark` and let the red-team suite run:

| Attempt | Result |
|---|---|
| Spend ₹7,000 against a ₹5,000 cap | ✕ BLOCK `MANDATE_LIMIT_EXCEEDED` |
| Self-issue a mandate with a doubled cap | ✕ BLOCK `MANDATE_IMMUTABLE` |
| Tamper the price after signing | ✕ BLOCK `PRICE_MISMATCH_MERCHANT_RECORD` |
| Replay a used nonce / resubmit a paid txn | ✕ BLOCK `NONCE_REPLAY` / `DUPLICATE_TRANSACTION` |
| Buy off-mandate · inject via catalog text · transact while frozen · expired mandate | ✕ BLOCK - each with its own code |
| AP2: expired / signature-flipped / unregistered-signer cart | ✕ BLOCK at AP2 verification, before the gate |

Then the scoreboard, computed live:

```
Adversarial attempts blocked : 100%   (correct reason code every time)
False-blocks on legit        : 0%
Fuzzer spend-cap violations  : 0   over 20,000 random states
Escapes                      : 0
```

> *"Every attack is refused, and told exactly which rule fired. The agent cannot
> escalate its own authority - that's a property of the verifier, not a promise
> of the AI."*

**This is the climax.** Nine attack classes, an AP2 tamper set, and a
property-fuzzer - all blocked, zero escapes.

---

## Close  ·  4:30-5:00

Be brutally honest about the ML - it makes you *more* credible:

> *"On our synthetic held-out set - 360 attacks, 900 legit - the classes are
> separable by construction, so a clean 1.00 is expected; I don't claim it as
> real-world fraud accuracy. So we report calibration, a noise-robustness curve,
> and a leave-one-class-out limit instead. The model is advisory and can only
> tighten a decision - the deterministic verifier, not the model, is the
> guarantee."*

End on the thesis:

> *"Don't trust the agent. Test the authorization boundary. That's BAZAAR."*

---

**Fallback:** everything except the live Razorpay payment runs offline
(`make showcase`, `make ap2`, `make benchmark`). Record one successful `make live`
clip in advance so the settlement moment is safe even if the network wobbles.
