"""Builders for tests, the fuzzer, and the benchmark.

One place that knows how to mint a signed mandate, a merchant record, and a
transaction request, so every test speaks the same language.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from bazaar.crypto.signing import generate_keypair
from bazaar.models import (
    Mandate,
    MerchantRecord,
    PriceSource,
    TransactionRequest,
    now_utc,
    sign_mandate,
    to_rfc3339,
)


def make_keypair() -> tuple[str, str]:
    return generate_keypair()


def make_signed_mandate(
    *,
    signing_key: str,
    public_key: str,
    agent_id: str = "buyer-1",
    max_amount: int = 500_000,          # ₹5,000 in paise
    allowed_categories: tuple[str, ...] = ("footwear",),
    return_policy_days: int = 30,
    ttl_seconds: int = 900,
    issued_offset_seconds: int = 0,
    mandate_id: str | None = None,
) -> Mandate:
    issued = now_utc() + timedelta(seconds=issued_offset_seconds)
    expires = issued + timedelta(seconds=ttl_seconds)
    draft = Mandate(
        mandate_id=mandate_id or f"m-{uuid.uuid4().hex[:8]}",
        agent_id=agent_id,
        max_amount=max_amount,
        allowed_categories=allowed_categories,
        return_policy_days=return_policy_days,
        issued_at=to_rfc3339(issued),
        expires_at=to_rfc3339(expires),
        currency="INR",
    )
    return sign_mandate(signing_key, public_key, draft)


def make_record(
    *,
    sku: str = "SKU-SHOE-01",
    merchant_id: str = "merch-1",
    title: str = "Trail Running Shoes",
    category: str = "footwear",
    price: int = 449_900,               # ₹4,499
    return_policy_days: int = 30,
    description: str = "Lightweight trail shoes.",
    floor_price: int = 400_000,
    active: bool = True,
) -> MerchantRecord:
    return MerchantRecord(
        sku=sku,
        merchant_id=merchant_id,
        title=title,
        category=category,
        price=price,
        return_policy_days=return_policy_days,
        description=description,
        floor_price=floor_price,
        active=active,
    )


def make_txn(
    *,
    mandate: Mandate,
    sku: str = "SKU-SHOE-01",
    category: str = "footwear",
    amount: int = 449_900,
    price_source: PriceSource = PriceSource.MERCHANT_RECORD,
    nonce: str | None = None,
    idempotency_key: str | None = None,
    agent_id: str | None = None,
    txn_id: str | None = None,
) -> TransactionRequest:
    return TransactionRequest(
        txn_id=txn_id or f"t-{uuid.uuid4().hex[:8]}",
        mandate=mandate,
        agent_id=agent_id or mandate.agent_id,
        sku=sku,
        category=category,
        amount=amount,
        price_source=price_source,
        nonce=nonce or f"n-{uuid.uuid4().hex}",
        idempotency_key=idempotency_key or f"idem-{uuid.uuid4().hex}",
    )
