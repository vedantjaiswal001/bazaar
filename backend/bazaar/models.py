"""Shared, trusted domain types.

These live at the package root (not under intent/ or agents/) so the
deterministic verifier can import them without importing any probabilistic /
LLM code. The module-boundary test enforces that separation.

Money is always an integer number of paise. There are no floats here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from bazaar.crypto.signing import sign_object, verify_object


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_rfc3339(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_rfc3339(text: str) -> datetime:
    # Accept both with and without fractional seconds.
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    # Last resort: ISO parse.
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


class PriceSource(str, Enum):
    """Where a transaction's money-fields (price, category) came from.

    Only MERCHANT_RECORD is trusted. Anything else means the value was derived
    from something an adversary (or injected text) could influence, and the gate
    rejects it outright — this is the prompt-injection defense.
    """

    MERCHANT_RECORD = "merchant_record"  # read from the merchant of record (trusted)
    SELLER_CLAIM = "seller_claim"        # a value the seller agent asserted (untrusted)
    DESCRIPTION = "description"           # extracted from catalog free text (untrusted)
    AGENT_INVENTED = "agent_invented"     # the agent made it up (untrusted)


class RiskAction(str, Enum):
    NORMAL = "NORMAL"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class MerchantRecord:
    """A row of the merchant of record. Authoritative price + category."""

    sku: str
    merchant_id: str
    title: str
    category: str
    price: int              # authoritative price, paise
    currency: str = "INR"
    return_policy_days: int = 0
    description: str = ""    # UNTRUSTED free text; may contain injection
    floor_price: int = 0     # seller negotiation floor, paise
    active: bool = True


@dataclass(frozen=True)
class Mandate:
    """A human-authorized, Ed25519-signed spending mandate.

    The signature is over the JCS canonicalization of `signed_body()`. Any change
    to a signed field breaks verification (the Policy / MANDATE_IMMUTABLE attack).
    """

    mandate_id: str
    agent_id: str
    max_amount: int                       # signed cap, paise
    allowed_categories: tuple[str, ...]
    return_policy_days: int
    issued_at: str                        # RFC3339 UTC
    expires_at: str                       # RFC3339 UTC
    currency: str = "INR"
    public_key: str = ""                  # base64 Ed25519 verify key
    signature: str = ""                   # base64 signature over JCS(signed_body)
    canonical_body: str = ""              # exact JCS bytes that were signed (audit)

    def signed_body(self) -> dict[str, Any]:
        """The immutable subset that is signed. Categories are sorted for stability."""
        return {
            "mandate_id": self.mandate_id,
            "agent_id": self.agent_id,
            "max_amount": self.max_amount,
            "currency": self.currency,
            "allowed_categories": sorted(self.allowed_categories),
            "return_policy_days": self.return_policy_days,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    def verify_signature(self) -> bool:
        """Recompute the signed body from live fields and verify the signature.

        Because the body is recomputed from the current field values, tampering
        with any signed field (e.g. raising max_amount) makes this return False.
        """
        if not self.public_key or not self.signature:
            return False
        return verify_object(self.public_key, self.signed_body(), self.signature)

    def is_expired(self, at: datetime | None = None) -> bool:
        at = at or now_utc()
        return at > parse_rfc3339(self.expires_at)


def sign_mandate(signing_key_b64: str, public_key_b64: str, draft: Mandate) -> Mandate:
    """Sign a mandate draft and return a new, locked Mandate carrying the signature."""
    body, signature = sign_object(signing_key_b64, draft.signed_body())
    return Mandate(
        mandate_id=draft.mandate_id,
        agent_id=draft.agent_id,
        max_amount=draft.max_amount,
        allowed_categories=draft.allowed_categories,
        return_policy_days=draft.return_policy_days,
        issued_at=draft.issued_at,
        expires_at=draft.expires_at,
        currency=draft.currency,
        public_key=public_key_b64,
        signature=signature,
        canonical_body=body,
    )


@dataclass(frozen=True)
class TransactionRequest:
    """What an agent submits to the gate for authorization."""

    txn_id: str
    mandate: Mandate
    agent_id: str
    sku: str
    category: str
    amount: int                 # paise the agent wants to settle
    price_source: PriceSource   # provenance of the money-fields
    nonce: str
    idempotency_key: str


@dataclass(frozen=True)
class RiskSignal:
    """Advisory only. May tighten the gate (NORMAL->REVIEW->BLOCK), never widen it."""

    score: float                 # 0.0 (benign) .. 1.0 (hostile)
    action: RiskAction
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class GateResult:
    """The verifier's verdict: a decision, one reason code, and the full checklist."""

    decision: str                # Decision value: ALLOW / REVIEW / BLOCK
    reason: str                  # Reason value
    detail: str
    checks: list[Check] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.decision == "ALLOW"
