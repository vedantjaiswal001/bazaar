"""Evaluation harness. Runs cases through the PURE gate and computes honest metrics.

Two vocabularies, kept strictly separate (see docs/EVAL.md):
  * the deterministic gate is CORRECT/INCORRECT vs the spec — we report block
    rates and reason-code correctness, never "accuracy";
  * the risk model is a probabilistic CLASSIFIER — it alone gets precision /
    recall / F1, reported separately and never merged with gate correctness.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from bazaar.agents.negotiation import negotiate
from bazaar.agents.seller import SellerAgent
from bazaar.catalog.seed import seed_default_catalog
from bazaar.catalog.store import CatalogStore
from bazaar.crypto.signing import generate_keypair
from bazaar.db.database import connect, init_db
from bazaar.models import RiskAction
from bazaar.redteam.attacks import ATTACK_CLASSES, Case
from bazaar.risk.model import assess
from bazaar.verifier.gate import authorize
from bazaar.verifier.reasons import Decision


@dataclass
class CaseResult:
    id: str
    kind: str
    attack_class: str | None
    expected_decision: str
    expected_reason: str
    actual_decision: str
    actual_reason: str
    passed: bool
    risk_flagged: bool


def evaluate_cases(cases: list[Case]) -> list[CaseResult]:
    results: list[CaseResult] = []
    for c in cases:
        gr = authorize(c.txn, c.offer, nonce_seen=c.nonce_seen,
                       idempotency_seen=c.idem_seen, agent_frozen=c.agent_frozen)
        if c.kind == "attack":
            passed = gr.decision == Decision.BLOCK.value and gr.reason == c.expected_reason
        else:
            passed = gr.decision == Decision.ALLOW.value
        risk = assess(c.txn, c.offer)
        results.append(CaseResult(
            id=c.id, kind=c.kind, attack_class=c.attack_class,
            expected_decision=c.expected_decision, expected_reason=c.expected_reason,
            actual_decision=gr.decision, actual_reason=gr.reason, passed=passed,
            risk_flagged=risk.action != RiskAction.NORMAL,
        ))
    return results


@dataclass
class SecurityMetrics:
    per_class_blocked: dict[str, float]
    per_class_correct_code: dict[str, float]
    overall_block_rate: float
    overall_correct_code_rate: float
    escapes: list[dict]
    false_block_rate: float
    legit_total: int
    attack_total: int


def security_metrics(results: list[CaseResult]) -> SecurityMetrics:
    attacks = [r for r in results if r.kind == "attack"]
    legit = [r for r in results if r.kind == "legit"]

    per_blocked: dict[str, float] = {}
    per_correct: dict[str, float] = {}
    for cls in ATTACK_CLASSES:
        rows = [r for r in attacks if r.attack_class == cls]
        if not rows:
            continue
        per_blocked[cls] = sum(r.actual_decision == Decision.BLOCK.value for r in rows) / len(rows)
        per_correct[cls] = sum(r.passed for r in rows) / len(rows)

    escapes = [
        {"id": r.id, "class": r.attack_class, "got": f"{r.actual_decision}/{r.actual_reason}",
         "expected": f"BLOCK/{r.expected_reason}"}
        for r in attacks if r.actual_decision != Decision.BLOCK.value
    ]
    overall_block = (sum(r.actual_decision == Decision.BLOCK.value for r in attacks) / len(attacks)
                     if attacks else 0.0)
    overall_correct = sum(r.passed for r in attacks) / len(attacks) if attacks else 0.0
    false_blocks = sum(r.actual_decision != Decision.ALLOW.value for r in legit)
    false_block_rate = false_blocks / len(legit) if legit else 0.0

    return SecurityMetrics(
        per_class_blocked=per_blocked, per_class_correct_code=per_correct,
        overall_block_rate=overall_block, overall_correct_code_rate=overall_correct,
        escapes=escapes, false_block_rate=false_block_rate,
        legit_total=len(legit), attack_total=len(attacks),
    )


@dataclass
class ClassifierMetrics:
    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int
    tn: int


def risk_classifier_metrics(results: list[CaseResult]) -> ClassifierMetrics:
    """Precision/recall/F1 for the ADVISORY risk model. Kept separate from gate correctness."""
    tp = sum(r.kind == "attack" and r.risk_flagged for r in results)
    fp = sum(r.kind == "legit" and r.risk_flagged for r in results)
    fn = sum(r.kind == "attack" and not r.risk_flagged for r in results)
    tn = sum(r.kind == "legit" and not r.risk_flagged for r in results)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return ClassifierMetrics(precision, recall, f1, tp, fp, fn, tn)


@dataclass
class RevenueAxis:
    buyers: int
    mean_aov_baseline: int
    mean_aov_upsell: int
    aov_uplift_pct: float
    share_of_uplift_cleared: float   # fraction of upsold orders that still cleared the gate


def revenue_axis(n_buyers: int = 200, seed: int = 7) -> RevenueAxis:
    """Same harness, no new engine: run legitimate buyers with upsell OFF then ON."""
    import random

    rng = random.Random(seed)
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "rev.db")
        init_db(path, drop=True)
        conn = connect(path)
        seed_default_catalog(conn)
        store = CatalogStore(conn)
        seller = SellerAgent("merch-athleto", store.seller_view())

        base_total = 0
        up_total = 0
        up_cleared = 0
        for _ in range(n_buyers):
            cap = rng.choice([480_000, 500_000, 520_000])   # caps around the pro price
            sk, pk = generate_keypair()
            from bazaar.redteam.attacks import _mandate, _txn  # reuse builders
            mandate = _mandate(sk, pk, cap=cap)

            base_offer, _ = negotiate(store=store, seller=seller, buyer_cap=cap,
                                      base_sku="SKU-SHOE-01", upsell=False)
            up_offer, up_out = negotiate(store=store, seller=seller, buyer_cap=cap,
                                         base_sku="SKU-SHOE-01", upsell=True)
            base_total += base_offer.price
            up_total += up_offer.price

            # Does the upsold order still clear the deterministic gate?
            up_txn = _txn(mandate, up_offer)
            gr = authorize(up_txn, up_offer, nonce_seen=False, idempotency_seen=False,
                           agent_frozen=False)
            if gr.decision == Decision.ALLOW.value:
                up_cleared += 1
        conn.close()

    mean_base = base_total // n_buyers
    mean_up = up_total // n_buyers
    uplift = (mean_up / mean_base - 1.0) * 100 if mean_base else 0.0
    share = up_cleared / n_buyers if n_buyers else 0.0
    return RevenueAxis(n_buyers, mean_base, mean_up, round(uplift, 2), round(share, 4))
