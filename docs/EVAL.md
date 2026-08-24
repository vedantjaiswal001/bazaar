# BAZAAR - Evaluation

A security claim is worthless without a false-positive number. "We block 100% of
attacks" can just mean "we block everything." BAZAAR is evaluated like a real
system, and every number in the scoreboard is produced by a command you can run.

## Two vocabularies, kept separate

- **The deterministic gate is *correct* or *incorrect* against a specification.**
  It has no "accuracy." We report block rates and the exact reason code per case.
- **A probabilistic classifier** (the risk model) is the only thing that earns
  the words *precision*, *recall*, *F1*. Its numbers are reported separately and
  never merged with gate correctness.

## Datasets

- **Adversarial set (100-200):** scripted attacks, labeled by class, each with an
  expected verdict and expected reason code.
- **Legitimate set (300-500):** generated from a distribution over amounts and
  categories - **sampled independently of the policy thresholds** - with varied
  caps and multi-category allowlists, and deliberately including **amount boundary
  cases** that must still pass: exactly at the cap, one rupee under it
  (cap - 100 paise = ₹4,999 against a ₹5,000 cap), and ₹50 under it
  (cap - 5,000 paise = ₹4,950). This measures the false-block rate where it
  actually matters: at the edges of the spend cap.

## Disciplines that make the numbers credible

- **Held-out:** tune against development attacks; evaluate on fresh, unseen
  instances the code has never seen - no overfitting to our own test.
- **Fuzzer:** a property-based (Hypothesis) fuzzer throws thousands of random
  states at the spend-cap invariant. We report the **actual** violation count,
  never a pre-written zero.
- **Revenue axis (same harness, no new engine):** run the legitimate set twice -
  seller upsell OFF (baseline) then ON - same buyers, same catalog, same gate.
  Report average-order-value uplift and the share of uplift that still cleared
  the gate (target: all of it).

### What the AOV number is, precisely (and what it is not)

The honest reading matters more than the digit, so it is spelled out here.

- **What it measures:** a controlled A/B on one fixed set of 200 simulated
  legitimate buyers (seed 7). Each buyer is run through the *same* bounded
  negotiation twice - once with the seller's in-category upsell **off**, once
  **on** - and we report `mean(order_value_on) / mean(order_value_off) - 1`. The
  seller may only ever propose a higher item **in the buyer's allowed category and
  under the signed cap**; the upsold order is then re-run through the deterministic
  gate, and we report the share that still cleared it (target and result: 100%).
- **Why it belongs in a *security* project:** it is the counter-argument to "a
  safe gate just blocks everything and kills revenue." The point is not the size
  of the lift; it is that the lift and the safety are not in tension - every extra
  rupee still passed the same gate that blocks the nine attacks.
- **What it does NOT claim:** it is not real-world revenue, conversion, or a
  live-shopper result. There are no real buyers and no real money. It is a
  reproducible statement about a simulated buyer distribution, nothing more, and
  the number regenerates from the seed on every `make benchmark`.

## The scoreboard (`make benchmark`)

| Category            | Metric                                                                 |
|---------------------|------------------------------------------------------------------------|
| Security correctness| per-class block rate; overall block rate; escapes (honestly reported)   |
| Usability           | false-block rate on legitimate traffic (the false-positive cost)        |
| Behavioral classifier| precision / recall / F1 for the risk model - reported separately       |
| Economic value      | AOV uplift from bounded upsell; share of uplift that still cleared the gate |
| Integrity           | fuzzer: actual violation count against the spend-cap invariant          |

Every row above is printed by `make benchmark`. Razorpay Test Mode settlement is
proven separately and live by `make live` (it needs real `rzp_test_` keys, so it
is not part of the keyless benchmark).

**One command** regenerates the datasets, reruns the gate and the fuzzer, and
prints the scoreboard - including any real escape. Reproducibility is the
strongest possible signal that the numbers are honest.
