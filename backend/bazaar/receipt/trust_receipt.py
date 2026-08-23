"""Trust Receipt — a signed, verifiable record of one authorization decision.

Every authorization (ALLOW or BLOCK) emits a receipt: canonical JSON, Ed25519
signed by the authority key. Anyone can re-verify it offline. Tampering with a
single field makes verification fail — the cryptography is real, not decorative.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from bazaar.crypto.signing import sign_object, verify_object
from bazaar.models import GateResult, MerchantRecord, TransactionRequest, now_utc, to_rfc3339

RECEIPT_VERSION = "bazaar.receipt.v1"


@dataclass(frozen=True)
class TrustReceipt:
    receipt_id: str
    body: dict[str, Any]      # the exact object that was signed
    public_key: str
    signature: str

    def verify(self) -> bool:
        return verify_object(self.public_key, self.body, self.signature)

    def to_json(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "body": self.body,
            "public_key": self.public_key,
            "signature": self.signature,
        }


def build_receipt(
    signing_key: str,
    public_key: str,
    *,
    txn: TransactionRequest,
    record: MerchantRecord | None,
    result: GateResult,
    razorpay_order_id: str | None = None,
    razorpay_payment_id: str | None = None,
) -> TrustReceipt:
    """Build and sign a Trust Receipt for a decision."""
    receipt_id = f"rcpt-{uuid.uuid4().hex[:12]}"
    body: dict[str, Any] = {
        "version": RECEIPT_VERSION,
        "receipt_id": receipt_id,
        "txn_id": txn.txn_id,
        "agent_id": txn.agent_id,
        "mandate_id": txn.mandate.mandate_id,
        "mandate_cap": txn.mandate.max_amount,
        "sku": txn.sku,
        "category": record.category if record else txn.category,
        "amount": txn.amount,
        "currency": txn.mandate.currency,
        "merchant_id": record.merchant_id if record else None,
        "price_source": txn.price_source.value,
        "decision": result.decision,
        "reason": result.reason,
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": razorpay_payment_id,
        "issued_at": to_rfc3339(now_utc()),
    }
    _, signature = sign_object(signing_key, body)
    return TrustReceipt(
        receipt_id=receipt_id, body=body, public_key=public_key, signature=signature
    )


def verify_receipt_json(receipt: dict[str, Any]) -> bool:
    """Verify a receipt given as the to_json() dict (as the frontend would send it)."""
    try:
        return verify_object(receipt["public_key"], receipt["body"], receipt["signature"])
    except (KeyError, TypeError):
        return False
