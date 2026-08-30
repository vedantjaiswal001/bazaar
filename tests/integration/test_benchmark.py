"""The benchmark harness must report a perfect gate and an honest revenue axis."""
from __future__ import annotations

import random

from bazaar.crypto.signing import generate_keypair
from bazaar.redteam.attacks import generate_adversarial, generate_legitimate
from bazaar.redteam.harness import (
    evaluate_cases,
    revenue_axis,
    risk_classifier_metrics,
    security_metrics,
)


def _cases(seed=3):
    rng = random.Random(seed)
    sk, pk = generate_keypair()
    return generate_adversarial(rng, sk, pk, per_class=6) + generate_legitimate(rng, sk, pk, n=120)


def test_gate_blocks_every_attack_with_correct_code():
    results = evaluate_cases(_cases())
    sec = security_metrics(results)
    assert sec.overall_block_rate == 1.0
    assert sec.overall_correct_code_rate == 1.0
    assert sec.escapes == []
    for cls, rate in sec.per_class_correct_code.items():
        assert rate == 1.0, f"{cls} reason-code correctness {rate}"


def test_no_false_blocks_on_legit_including_boundaries():
    sec = security_metrics(evaluate_cases(_cases()))
    assert sec.false_block_rate == 0.0


def test_risk_classifier_has_no_false_positives():
    """The advisory model may miss attacks (low recall), but must not flag legit traffic."""
    m = risk_classifier_metrics(evaluate_cases(_cases()))
    assert m.fp == 0
    assert m.precision == 1.0


def test_revenue_axis_uplift_is_positive_and_all_clears_the_gate():
    rev = revenue_axis(n_buyers=50, seed=11)
    assert rev.mean_aov_upsell > rev.mean_aov_baseline
    assert rev.aov_uplift_pct > 0
    assert rev.share_of_uplift_cleared == 1.0   # every rupee of uplift still passed the gate
