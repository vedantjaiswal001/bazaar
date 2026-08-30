"""Advisory risk model - now a trained, calibrated behavioural classifier.

This is the probabilistic layer. It emits a *signal*, nothing more. By
construction it can only push a decision toward MORE scrutiny
(NORMAL -> REVIEW -> BLOCK); it has no path to approve a payment or raise a
limit - that is the deterministic verifier's job alone.

Two implementations live here behind one `assess()` API:

  * a LEARNED model (gradient-boosted + isotonic-calibrated) loaded from a small
    artifact, whose probability is thresholded by an FP-COST-optimal cutoff. This
    is what raises recall from the old heuristic's 0.22 to ~1.0 while holding
    zero false positives, and it generalises to unseen attack shapes.
  * a transparent HEURISTIC fallback (the original rules) used whenever the
    artifact is absent - so a fresh clone still runs and every test still passes.

Its accuracy is measured SEPARATELY (precision / recall / F1 / calibration) and
is never merged with the deterministic gate's correctness. See docs/EVAL.md.

This module imports only bazaar.models + the pure feature layer - never the
verifier (enforced by tests/security/test_module_boundary.py).
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from bazaar.models import (
    MerchantRecord,
    PriceSource,
    RiskAction,
    RiskSignal,
    TransactionRequest,
)
from bazaar.risk.features import (  # noqa: F401  (scan_injection re-exported on purpose)
    FEATURE_NAMES,
    RiskContext,
    extract,
    scan_injection,
    top_reasons,
)

ARTIFACT_PATH = Path(__file__).resolve().parent / "artifacts" / "risk_model.joblib"

_LOCK = threading.Lock()
_LOADED = False
_MODEL: Any | None = None
_THRESHOLDS: dict[str, float] = {"review": 0.5, "block": 0.8}


def _load_model() -> Any | None:
    """Load the trained artifact once. Returns None if unavailable (-> heuristic)."""
    global _LOADED, _MODEL, _THRESHOLDS
    if _LOADED:
        return _MODEL
    with _LOCK:
        if _LOADED:
            return _MODEL
        _LOADED = True
        try:
            import joblib  # local import: only needed when an artifact exists
            if not ARTIFACT_PATH.exists():
                _MODEL = None
                return None
            bundle = joblib.load(ARTIFACT_PATH)
            if list(bundle.get("feature_names", ())) != list(FEATURE_NAMES):
                # Feature layout drifted from the trained artifact: fail safe to
                # the heuristic rather than scoring on mismatched inputs.
                _MODEL = None
                return None
            _MODEL = bundle["model"]
            _THRESHOLDS = dict(bundle.get("thresholds", _THRESHOLDS))
        except Exception:
            _MODEL = None
    return _MODEL


def model_available() -> bool:
    return _load_model() is not None


def _action_for(prob: float) -> RiskAction:
    if prob >= _THRESHOLDS["block"]:
        return RiskAction.BLOCK
    if prob >= _THRESHOLDS["review"]:
        return RiskAction.REVIEW
    return RiskAction.NORMAL


def _heuristic_assess(
    txn: TransactionRequest, record: MerchantRecord | None, context: RiskContext | None
) -> RiskSignal:
    """The original transparent rules - fallback when no trained artifact is present."""
    ctx = context or RiskContext()
    score = 0.0
    reasons: list[str] = []

    if txn.price_source != PriceSource.MERCHANT_RECORD:
        score += 0.6
        reasons.append(f"price_source={txn.price_source.value} (not merchant of record)")
    if record is not None:
        markers = scan_injection(record.description)
        if markers:
            score += 0.4
            reasons.append(f"injection markers in catalog text: {markers[:3]}")
    cap = txn.mandate.max_amount
    if cap > 0 and txn.amount >= int(cap * 0.98):
        score += 0.2
        reasons.append("amount within 2% of the mandate cap")
    if record is not None and txn.amount != record.price:
        score += 0.4
        reasons.append("amount disagrees with merchant-of-record price")
    if not ctx.issuer_trusted:
        score += 0.6
        reasons.append("mandate not signed by a trusted issuer key")
    if ctx.nonce_seen or ctx.idem_seen:
        score += 0.5
        reasons.append("replay / duplicate signal from live state")
    if ctx.agent_frozen:
        score += 0.5
        reasons.append("agent is frozen")

    score = min(score, 1.0)
    action = RiskAction.BLOCK if score >= 0.8 else RiskAction.REVIEW if score >= 0.4 else RiskAction.NORMAL
    return RiskSignal(score=round(score, 3), action=action, reasons=tuple(reasons))


def assess(
    txn: TransactionRequest,
    record: MerchantRecord | None,
    context: RiskContext | None = None,
) -> RiskSignal:
    """Produce an advisory risk signal for a transaction.

    Uses the trained model when its artifact is present; otherwise the transparent
    heuristic. Either way the result is advisory: it can tighten a decision to a
    human-review hold, never approve money or raise a limit.
    """
    model = _load_model()
    if model is None:
        return _heuristic_assess(txn, record, context)

    feats = [extract(txn, record, context)]
    try:
        prob = float(model.predict_proba(feats)[0][1])
    except Exception:
        return _heuristic_assess(txn, record, context)

    action = _action_for(prob)
    reasons = tuple(top_reasons(txn, record, context)) if action != RiskAction.NORMAL else ()
    return RiskSignal(score=round(prob, 3), action=action, reasons=reasons)
