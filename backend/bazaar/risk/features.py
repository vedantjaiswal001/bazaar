"""Feature extraction for the advisory risk brain.

PURE and dependency-light: this module imports only the shared domain types
(bazaar.models) and the standard library + numpy. It must NOT import the
verifier - the risk layer informs, it never authorizes (enforced by
tests/security/test_module_boundary.py).

A transaction is turned into a fixed-length numeric feature vector. The features
mix HARD signals (over-cap, price mismatch, expired, replay/duplicate/frozen
flags) with SOFT / behavioural ones (cap utilisation, price-delta ratio,
near-cap pressure, velocity, agent reputation). The soft signals are what let a
LEARNED model generalise to fuzzy or previously unseen attacks - something a
fixed checklist, by construction, cannot do.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from bazaar.models import (
    MerchantRecord,
    PriceSource,
    TransactionRequest,
    now_utc,
    parse_rfc3339,
)

# --- prompt-injection markers in untrusted catalog text -----------------------
# (Kept here, re-exported by risk.model, so tests/security/test_prompt_injection.py
#  can still `from bazaar.risk.model import scan_injection`.)
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


@dataclass(frozen=True)
class RiskContext:
    """Live context the (txn, record) pair alone does not carry.

    Every field defaults to the benign value, so `assess(txn, record)` with no
    context is well-defined (it simply cannot see replay / duplicate / frozen /
    forged-issuer signals - which is exactly why the old model was blind to them).
    The DB-backed service and the benchmark harness fill these in for real.
    """

    nonce_seen: bool = False
    idem_seen: bool = False
    agent_frozen: bool = False
    issuer_trusted: bool = True
    velocity_1m: int = 0        # recent transactions from this agent in a short window
    agent_prior_blocks: int = 0  # how many of this agent's past attempts were blocked


#: Stable feature order. The trained artifact stores this too and asserts a match.
FEATURE_NAMES: tuple[str, ...] = (
    "cap_utilization",
    "over_cap",
    "price_mismatch",
    "price_delta_ratio",
    "record_missing",
    "provenance_untrusted",
    "category_out",
    "injection_markers",
    "expired",
    "ttl_remaining_norm",
    "nonce_seen",
    "idem_seen",
    "agent_frozen",
    "issuer_untrusted",
    "sig_invalid",
    "near_cap",
    "num_allowed_categories",
    "amount_log",
    "velocity_1m",
    "agent_prior_blocks",
)


def _clip(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def extract(
    txn: TransactionRequest,
    record: MerchantRecord | None,
    context: RiskContext | None = None,
) -> list[float]:
    """Turn one transaction into the fixed-length feature vector (FEATURE_NAMES order)."""
    ctx = context or RiskContext()
    cap = txn.mandate.max_amount
    amount = txn.amount
    price = record.price if record is not None else 0

    cap_utilization = amount / cap if cap > 0 else 2.0
    over_cap = 1.0 if amount > cap else 0.0
    price_mismatch = 1.0 if (record is not None and amount != record.price) else 0.0
    price_delta_ratio = (abs(amount - price) / price) if (record is not None and price > 0) else (
        0.0 if record is not None else 1.0
    )
    record_missing = 1.0 if (
        record is None or not record.active or record.sku != txn.sku
    ) else 0.0
    provenance_untrusted = 1.0 if txn.price_source != PriceSource.MERCHANT_RECORD else 0.0
    category_out = 1.0 if (
        record is not None and record.category not in txn.mandate.allowed_categories
    ) else 0.0
    injection_markers = float(len(scan_injection(record.description))) if record is not None else 0.0

    expired = 1.0 if txn.mandate.is_expired() else 0.0
    try:
        ttl = (parse_rfc3339(txn.mandate.expires_at) - now_utc()).total_seconds()
    except Exception:
        ttl = 0.0
    ttl_remaining_norm = _clip(ttl / 900.0, 0.0, 1.0)

    issuer_untrusted = 0.0 if ctx.issuer_trusted else 1.0
    sig_invalid = 0.0 if txn.mandate.verify_signature() else 1.0
    near_cap = 1.0 if (cap > 0 and amount >= 0.98 * cap) else 0.0
    num_allowed = float(len(txn.mandate.allowed_categories))
    amount_log = math.log1p(max(amount, 0)) / 20.0

    return [
        _clip(cap_utilization, 0.0, 4.0),
        over_cap,
        price_mismatch,
        _clip(price_delta_ratio, 0.0, 5.0),
        record_missing,
        provenance_untrusted,
        category_out,
        _clip(injection_markers, 0.0, 10.0),
        expired,
        ttl_remaining_norm,
        1.0 if ctx.nonce_seen else 0.0,
        1.0 if ctx.idem_seen else 0.0,
        1.0 if ctx.agent_frozen else 0.0,
        issuer_untrusted,
        sig_invalid,
        near_cap,
        num_allowed,
        amount_log,
        float(ctx.velocity_1m),
        float(ctx.agent_prior_blocks),
    ]


def top_reasons(txn: TransactionRequest, record: MerchantRecord | None,
                context: RiskContext | None = None, k: int = 3) -> list[str]:
    """Human-readable explanation of why a transaction looks risky.

    Advisory only - a plain-English gloss of the strongest signals, so a REVIEW
    hold is never rendered as "the model said no".
    """
    ctx = context or RiskContext()
    cap = txn.mandate.max_amount
    reasons: list[tuple[float, str]] = []
    if cap > 0 and txn.amount > cap:
        reasons.append((3.0, f"amount {txn.amount} exceeds signed cap {cap}"))
    if record is not None and txn.amount != record.price:
        reasons.append((2.5, "amount disagrees with the merchant-of-record price"))
    if txn.price_source != PriceSource.MERCHANT_RECORD:
        reasons.append((2.4, f"money-field provenance is '{txn.price_source.value}' (untrusted)"))
    if not ctx.issuer_trusted:
        reasons.append((2.6, "mandate not signed by a trusted issuer key"))
    if record is not None and record.category not in txn.mandate.allowed_categories:
        reasons.append((2.2, f"category '{record.category}' is outside the mandate allowlist"))
    if txn.mandate.is_expired():
        reasons.append((2.1, "mandate is past its time-to-live"))
    if ctx.nonce_seen:
        reasons.append((2.0, "nonce has already been used (replay)"))
    if ctx.idem_seen:
        reasons.append((2.0, "idempotency key already used (duplicate)"))
    if ctx.agent_frozen:
        reasons.append((1.9, "agent is currently frozen"))
    if record is not None and scan_injection(record.description):
        reasons.append((1.6, "prompt-injection markers in catalog text"))
    if cap > 0 and txn.amount >= 0.98 * cap and txn.amount <= cap:
        reasons.append((0.8, "amount is within 2% of the mandate cap"))
    if ctx.velocity_1m >= 5:
        reasons.append((0.7, f"high recent velocity ({ctx.velocity_1m} txns/min)"))
    reasons.sort(reverse=True)
    return [r for _, r in reasons[:k]]
