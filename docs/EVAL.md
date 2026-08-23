# BAZAAR — Evaluation

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

- **Adversarial set (100–200):** scripted attacks, labeled by class, each with an
  expected verdict and expected reason code.
- **Legitimate set (300–500):** generated from a distribution over amounts,
  categories, return policies, and velocities — **sampled independently of the
  policy thresholds**, and deliberately including **boundary cases** (₹4,950
  against a ₹5,000 cap; a return of exactly 30 days). This measures the
  false-block rate where it actually matters: at the edges.

## Disciplines that make the numbers credible

- **Held-out:** tune against development attacks; evaluate on fresh, unseen
  instances the code has never seen — no overfitting to our own test.
- **Fuzzer:** a property-based (Hypothesis) fuzzer throws thousands of random
  states at the spend-cap invariant. We report the **actual** violation count,
  never a pre-written zero.
- **Revenue axis (same harness, no new engine):** run the legitimate set twice —
  seller upsell OFF (baseline) then ON — same buyers, same catalog, same gate.
  Report average-order-value uplift and the share of uplift that still cleared
  the gate (target: all of it).

## The scoreboard (`make benchmark`)

| Category            | Metric                                                                 |
|---------------------|------------------------------------------------------------------------|
| Security correctness| per-class block rate; overall block rate; escapes (honestly reported)   |
| Usability           | false-block rate on legitimate traffic (the false-positive cost)        |
| Behavioral classifier| precision / recall / F1 for the risk model — reported separately       |
| Economic value      | AOV uplift from bounded upsell; share of uplift that still cleared the gate |
| Integrity           | fuzzer: actual violation count against the spend-cap invariant          |
| System              | authorization latency; Razorpay test transaction success rate           |

**One command** regenerates the datasets, reruns the gate and the fuzzer, and
prints the scoreboard — including any real escape. Reproducibility is the
strongest possible signal that the numbers are honest.
