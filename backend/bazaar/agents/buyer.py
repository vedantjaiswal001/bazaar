"""Buyer agent. Parses intent, drafts a mandate for HUMAN confirmation, signs it,
and builds transactions that source money-fields from the merchant of record only.

The buyer never invents a price or a category for authorization: `build_transaction`
takes an authoritative offer (from the merchant of record) and marks the money-field
provenance as MERCHANT_RECORD. Anything an adversary injects into catalog text is
never used as a money-field - that is enforced at the gate, but the honest agent
does not even try.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from bazaar.config import settings
from bazaar.intent.compiler import IntentDraft, IntentParser, compile_intent
from bazaar.models import (
    Mandate,
    MerchantRecord,
    PriceSource,
    TransactionRequest,
    now_utc,
    to_rfc3339,
)


@dataclass(frozen=True)
class ConfirmationView:
    """What the human sees and confirms before anything is signed."""

    intent_text: str
    max_amount: int
    allowed_categories: tuple[str, ...]
    return_policy_days: int
    autonomous: bool
    expires_at: str
    warnings: tuple[str, ...]

    def is_confirmable(self) -> bool:
        return self.max_amount > 0 and len(self.allowed_categories) > 0


class BuyerAgent:
    """Proposes. Never signs. The buyer agent holds NO mandate-signing key - only
    the Issuer does - so a compromised buyer cannot self-issue a mandate."""

    def __init__(
        self,
        agent_id: str,
        parser: IntentParser | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        self.agent_id = agent_id
        self._parser = parser
        self._ttl = ttl_seconds or settings.mandate_ttl_seconds

    def draft_mandate(self, intent_text: str) -> tuple[IntentDraft, Mandate, ConfirmationView]:
        """Parse intent into an UNSIGNED mandate draft plus the human-facing view."""
        draft = compile_intent(intent_text, self._parser)
        issued = now_utc()
        expires = issued + timedelta(seconds=self._ttl)
        unsigned = Mandate(
            mandate_id=f"m-{uuid.uuid4().hex[:8]}",
            agent_id=self.agent_id,
            max_amount=draft.max_amount,
            allowed_categories=draft.allowed_categories,
            return_policy_days=draft.return_policy_days,
            issued_at=to_rfc3339(issued),
            expires_at=to_rfc3339(expires),
        )
        view = ConfirmationView(
            intent_text=intent_text,
            max_amount=draft.max_amount,
            allowed_categories=draft.allowed_categories,
            return_policy_days=draft.return_policy_days,
            autonomous=draft.autonomous,
            expires_at=unsigned.expires_at,
            warnings=draft.notes,
        )
        return draft, unsigned, view

    def build_transaction(
        self,
        mandate: Mandate,
        offer: MerchantRecord,
        *,
        nonce: str | None = None,
        idempotency_key: str | None = None,
    ) -> TransactionRequest:
        """Build a transaction whose money-fields come from the authoritative offer."""
        return TransactionRequest(
            txn_id=f"t-{uuid.uuid4().hex[:10]}",
            mandate=mandate,
            agent_id=self.agent_id,
            sku=offer.sku,
            category=offer.category,              # authoritative category from the record
            amount=offer.price,                   # authoritative price from the merchant of record
            price_source=PriceSource.MERCHANT_RECORD,
            nonce=nonce or uuid.uuid4().hex,
            idempotency_key=idempotency_key or uuid.uuid4().hex,
        )
