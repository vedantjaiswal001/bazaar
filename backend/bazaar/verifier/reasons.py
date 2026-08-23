"""Machine-readable reason codes.

Every authorization decision is either ALLOW or a BLOCK carrying exactly one of
these codes. The demo, the benchmark, and the frontend all speak this vocabulary
so that a decision is never rendered as "the AI decided no" -- it is always a
specific, testable rule with a specific failure.

Each attack class in the threat model maps to exactly one BLOCK code here.
"""
from __future__ import annotations

from enum import Enum


class Decision(str, Enum):
    """The three verdicts the gate can return.

    A probabilistic signal may move a decision from ALLOW to REVIEW to BLOCK
    (tighten), but can never move it the other way (widen). See risk/model.py.
    """

    ALLOW = "ALLOW"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


class Reason(str, Enum):
    """Machine-readable reason codes returned by the deterministic gate."""

    # ALLOW carries this so every decision has a non-null reason.
    OK = "OK"

    # --- Attack-class BLOCK codes (one per class in the threat model) ---
    MANDATE_LIMIT_EXCEEDED = "MANDATE_LIMIT_EXCEEDED"          # Budget:   spend > signed cap
    MANDATE_IMMUTABLE = "MANDATE_IMMUTABLE"                    # Policy:   agent rewrote a signed field
    PRICE_MISMATCH_MERCHANT_RECORD = "PRICE_MISMATCH_MERCHANT_RECORD"  # Price: price != merchant of record
    NONCE_REPLAY = "NONCE_REPLAY"                              # Replay:   nonce reused
    DUPLICATE_TRANSACTION = "DUPLICATE_TRANSACTION"            # Double-charge: idempotency key reused
    CATEGORY_OUTSIDE_MANDATE = "CATEGORY_OUTSIDE_MANDATE"      # Category: item not in allowlist
    UNTRUSTED_INSTRUCTION = "UNTRUSTED_INSTRUCTION"            # Injection: money-field sourced from untrusted text
    AGENT_FROZEN = "AGENT_FROZEN"                              # State:    agent frozen
    MANDATE_EXPIRED = "MANDATE_EXPIRED"                        # Expiry:   mandate past TTL


# A REVIEW hold raised by the advisory risk signal (never an approval).
RISK_REVIEW = "RISK_REVIEW_HOLD"


#: Canonical mapping attack class -> reason code, asserted by the benchmark.
ATTACK_CLASS_TO_REASON: dict[str, Reason] = {
    "budget": Reason.MANDATE_LIMIT_EXCEEDED,
    "policy": Reason.MANDATE_IMMUTABLE,
    "price": Reason.PRICE_MISMATCH_MERCHANT_RECORD,
    "replay": Reason.NONCE_REPLAY,
    "double_charge": Reason.DUPLICATE_TRANSACTION,
    "category": Reason.CATEGORY_OUTSIDE_MANDATE,
    "injection": Reason.UNTRUSTED_INSTRUCTION,
    "state": Reason.AGENT_FROZEN,
    "expiry": Reason.MANDATE_EXPIRED,
}
