"""Advisory risk model.

This is the probabilistic layer. It emits a *signal*, nothing more. By
construction it can only push a decision toward MORE scrutiny
(NORMAL -> REVIEW -> BLOCK). It has no path to approve a payment or raise a
limit - that is the verifier's job alone.

Its accuracy is measured separately (precision / recall / F1) and is never
merged with the deterministic gate's correctness. See docs/EVAL.md.
"""
from __future__ import annotations

import re

from bazaar.models import MerchantRecord, PriceSource, RiskAction, RiskSignal, TransactionRequest

# Heuristic markers of prompt-injection in untrusted catalog text.
_INJECTION_PATTERNS = [
    r"ignore (all |the |previous |above )*instructions",
    r"disregard",
    r"system\s*:",
    r"you are now",
    r"authorize",
    r"send (money|payment|funds)",
    r"transfer",
    r"admin",
    r"override",
    r"</?\s*system\s*>",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


def scan_injection(text: str) -> list[str]:
    """Return the injection markers found in untrusted text (may be empty)."""
    return [m.group(0) for m in _INJECTION_RE.finditer(text or "")]


def assess(txn: TransactionRequest, record: MerchantRecord | None) -> RiskSignal:
    """Produce an advisory risk signal for a transaction.

    Deterministic given its inputs (so it is reproducible in tests), but framed
    as a probabilistic score: it informs, it does not decide.
    """
    score = 0.0
    reasons: list[str] = []

    # Money-field provenance from untrusted text is the single strongest signal.
    if txn.price_source != PriceSource.MERCHANT_RECORD:
        score += 0.6
        reasons.append(f"price_source={txn.price_source.value} (not merchant of record)")

    # Injection markers in the catalog description the agent read.
    if record is not None:
        markers = scan_injection(record.description)
        if markers:
            score += 0.4
            reasons.append(f"injection markers in catalog text: {markers[:3]}")

    # Spending right at the ceiling is worth a human glance (advisory only).
    cap = txn.mandate.max_amount
    if cap > 0 and txn.amount >= int(cap * 0.98):
        score += 0.2
        reasons.append("amount within 2% of the mandate cap")

    # Price disagreement with the merchant of record always warrants human review.
    # (Legitimate traffic quotes the record price exactly, so this never false-alarms.)
    if record is not None and txn.amount != record.price:
        score += 0.4
        reasons.append("amount disagrees with merchant-of-record price")

    score = min(score, 1.0)
    if score >= 0.8:
        action = RiskAction.BLOCK
    elif score >= 0.4:
        action = RiskAction.REVIEW
    else:
        action = RiskAction.NORMAL
    return RiskSignal(score=round(score, 3), action=action, reasons=tuple(reasons))
