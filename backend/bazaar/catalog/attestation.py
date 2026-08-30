"""Merchant-as-signer: cryptographically signed price attestations.

Price integrity, made two-sided. Today the gate trusts the price row in the
merchant-of-record table. A **price attestation** goes further: the merchant
signs `(sku, price, category, merchant)` with its own Ed25519 key, so the price
the gate authorises against is one the merchant *cryptographically certified* -
not just a value that happened to be in a row. Tamper the price after signing
and the signature breaks; present a stale or forged attestation and the
signer/expiry check rejects it.

Paired with the buyer's signed mandate (or an AP2 Cart Mandate), this makes a
purchase a two-sided handshake: the buyer signs what they authorise, the merchant
signs what it will honour, and both must agree on the exact price.

This module imports only bazaar.models + the audited signing wrapper. It never
imports the verifier.
"""
from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from bazaar.crypto.signing import generate_keypair, sign_object, verify_object
from bazaar.models import MerchantRecord, now_utc, parse_rfc3339, to_rfc3339


@dataclass(frozen=True)
class PriceAttestation:
    """A merchant-signed certificate that a sku's price/category is authoritative."""

    attestation_id: str
    sku: str
    merchant_id: str
    price: int              # authoritative price, paise
    category: str
    currency: str = "INR"
    issued_at: str = ""     # RFC3339 UTC
    expires_at: str = ""    # RFC3339 UTC
    public_key: str = ""    # base64 Ed25519 verify key
    signature: str = ""     # base64 signature over JCS(signed_body)

    def signed_body(self) -> dict[str, Any]:
        return {
            "attestation_id": self.attestation_id,
            "sku": self.sku,
            "merchant_id": self.merchant_id,
            "price": self.price,
            "category": self.category,
            "currency": self.currency,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    def verify_signature(self) -> bool:
        if not self.public_key or not self.signature:
            return False
        return verify_object(self.public_key, self.signed_body(), self.signature)

    def is_expired(self, at: datetime | None = None) -> bool:
        at = at or now_utc()
        return at > parse_rfc3339(self.expires_at)


class MerchantSigner:
    """The merchant of record, holding the key it signs price attestations with."""

    def __init__(self, merchant_id: str, keypair: tuple[str, str] | None = None) -> None:
        self.merchant_id = merchant_id
        self._sk, self.public_key = keypair or generate_keypair()

    def attest(self, record: MerchantRecord, *, ttl_seconds: int = 900) -> PriceAttestation:
        """Sign a price attestation for a merchant-of-record row."""
        issued = now_utc()
        expires = issued + timedelta(seconds=ttl_seconds)
        draft = PriceAttestation(
            attestation_id=f"att-{uuid.uuid4().hex[:10]}",
            sku=record.sku, merchant_id=self.merchant_id,
            price=record.price, category=record.category, currency=record.currency,
            issued_at=to_rfc3339(issued), expires_at=to_rfc3339(expires),
        )
        _, signature = sign_object(self._sk, draft.signed_body())
        return dataclasses.replace(draft, public_key=self.public_key, signature=signature)


def verify_price_attestation(
    att: PriceAttestation,
    trusted_merchant_keys: set[str] | frozenset[str],
    *,
    at: datetime | None = None,
) -> tuple[bool, str]:
    """Verify a price attestation. Returns (ok, reason_code).

    Checks, in order: it is signed, by a trusted merchant key, the signature
    verifies over the current fields (any tamper breaks it), and it is not expired.
    """
    if not att.signature or not att.public_key:
        return False, "ATTESTATION_UNSIGNED"
    if att.public_key not in trusted_merchant_keys:
        return False, "ATTESTATION_UNTRUSTED_MERCHANT"
    if not att.verify_signature():
        return False, "ATTESTATION_TAMPERED"
    if att.is_expired(at):
        return False, "ATTESTATION_EXPIRED"
    return True, "OK"


def signed_offer(record: MerchantRecord, att: PriceAttestation) -> MerchantRecord:
    """Build the offer the gate authorises against, using the MERCHANT-SIGNED price.

    The price and category come from the verified attestation, so the gate's
    `amount == price` check is against a cryptographically certified value rather
    than a raw row that could have drifted or been tampered.
    """
    return dataclasses.replace(record, price=att.price, category=att.category)
