# The Risk Brain - advisory behavioural classifier

*Author: Vedant Jaiswal. Every number below is produced by `make train` (or
`python scripts/train_risk.py`) and `make benchmark`; the plots are written to
`docs/eval/`.*

## What it is (and is not)

The **deterministic gate remains the sole authoriser** - its 100% block / 0%
false-block is a *proof* (a fixed checklist + a fuzzed invariant), not a learned
metric. The risk brain is an **advisory** layer: a calibrated classifier that can
only ever *tighten* a decision to a human-review hold (`NORMAL → REVIEW →
BLOCK`). It can never approve a payment or widen a limit - enforced by
`tests/property/test_spend_cap_invariant.py::test_risk_never_widens_authority`
and the module-boundary test (the risk layer imports nothing from the verifier).

## The number we fixed

The previous advisory model was a hand-written heuristic - it never false-alarmed
but was nearly blind:

| Advisory risk model | precision | recall | F1 |
|---|---|---|---|
| Heuristic (before) | 1.000 | **0.222** | 0.364 |
| Calibrated logistic (after) | 1.000 | **1.000** | 1.000 |

It missed 112 of 144 attacks because it only ever saw `(txn, record)` - it could
not see the live signals that define replay, duplicate, frozen-agent and
forged-issuer attacks. The upgrade gives the model that context (`RiskContext`)
and replaces the rules with a **calibrated logistic model** over a 20-feature
behavioural vector.

## Dataset & methodology (so the numbers are defensible, not theatre)

A perfect precision/recall should make you ask *"on how many samples, generated
how?"* - so here it is, in full:

| Split | Size | Composition |
|---|---|---|
| Train | 2,210 | 810 attacks (90 × 9 classes) + 1,400 legit |
| Validation | 1,260 | threshold tuning **only** - never used for reporting |
| **Held-out** | **1,260** | **360 attacks (40 × 9 classes) + 900 legit** |

- **Generation:** synthetic + adversarial. The 9 attack classes come from labelled
  red-team generators (`backend/bazaar/redteam/attacks.py`); the legit traffic is
  within-policy and spans the whole in-cap range **including boundary edges**
  (exactly at cap, cap-100, cap-5,000).
- **Independence:** each split uses its **own RNG seed and a fresh Ed25519 issuer
  keypair**, so held-out mandates are signed by keys the model never saw.
- **The honest caveat:** these classes are **separable by construction** - each is
  defined by an exact invariant (over-cap, replayed nonce, off-category, ...). So a
  near-perfect score on *clean* held-out data is **expected, not magic**, and it is
  **not** a claim of real-world fraud accuracy. The genuinely hard, honest signals
  are the three below.

## Held-out evaluation (fresh keys, unseen)

```
Attacks (risky):    360      Detected:            360
Legitimate:         900      False positives:       0
Precision: 1.000    Recall: 1.000    F1: 1.000
PR-AUC:    1.000    ROC-AUC: 1.000   Brier: 0.038  (calibrated - see calibration.png)
```

The threshold is chosen by an **expected-cost sweep** (not F1), holding zero false
positives (`cost_curve.png`). Calibration - the fact that the scores are usable
*probabilities*, not just rankings - is the first honest signal (`calibration.png`).

## Out-of-distribution held-out (Generator B) - the credibility test

Different random seeds prove robustness to unseen *instances*, not to a different
*distribution*. So a second generator (`generate_*_ood` in `redteam/attacks.py`)
produces the **same threat model with a different process**: near-boundary
over-cap, tiny post-authorization price deltas, off-mandate categories from a
different set under multi-category allowlists, and unusual-but-valid benign edge
cases. The trained model is never tuned on it.

```
                              IID (Generator A)   OOD (Generator B)
  Deterministic gate block         100%               100%    <- the guarantee holds
  Risk model recall                1.000              0.631   <- the advisory layer drops
  Risk model precision             1.000              1.000
```

The honest reading: **the advisory model does not magically transfer.** Under a
genuinely different distribution its recall falls to **0.63** - it misses subtle,
near-boundary attacks at its IID-tuned threshold. But the **deterministic gate
still blocks 100%** of those same OOD attacks, with zero escapes. That is the whole
thesis in one number: **the model is not the security boundary; the verifier is.**
(360 attacks + 900 legit; `make train`.)

## Noise robustness - the honest answer to "is 1.00 just theatre?"

Perturb the held-out features with Gaussian noise scaled per-feature. A brittle
exact-threshold would fall off a cliff; a real model degrades smoothly. It does
(`noise_robustness.png`):

| Noise σ (× per-feature std) | Recall | Precision | FP | FN |
|---|---|---|---|---|
| 0.00 | 1.000 | 1.000 | 0 | 0 |
| 0.10 | 0.978 | 0.962 | 14 | 8 |
| 0.25 | 0.919 | 0.883 | 44 | 29 |
| 0.50 | 0.853 | 0.714 | 123 | 53 |
| 1.00 | 0.819 | 0.574 | 219 | 65 |

The perfect number holds only on clean data and degrades predictably under
measurement noise - exactly what a real model does, and the deterministic gate
catches the misses regardless.

## Generalisation (leave-one-attack-class-out) - reported honestly

Hide a whole attack class in training, test recall on it unseen. A class defined
by a single hard invariant does **not** transfer (mean **11%**) - and it
shouldn't: those invariants are the gate's job. The model's value is calibrated
**corroboration**, not replacing the gate. Reporting this limitation is the point.

## Why logistic, not a boosted tree

The behavioural signals are, by design, well separated, so a linear model gives
perfect ranking **and an interpretable weight per feature** - far more defensible
for a money system than an opaque ensemble (a `HistGradientBoosting` baseline
actually *underperformed* on these sparse one-hot signals). Top standardised
weights: `over_cap +2.28`, `nonce_seen +1.99`, `agent_frozen +1.96`,
`category_out +1.96`, `provenance_untrusted +1.95` - every driver is a signal a
human reviewer would name.

## Reproduce

```
make train       # trains, evaluates, writes the artifact + all four plots + risk_eval.json
make benchmark   # shows the advisory classifier line: precision/recall/F1
make test        # 93 tests, incl. the tighten-only + module-boundary guarantees
```
