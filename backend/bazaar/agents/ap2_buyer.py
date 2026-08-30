"""An AP2 buyer - the credential provider / shopping agent side.

Owns an ES256 (P-256) key and signs **Cart Mandates** the way a real AI buyer's
credential provider would. Includes deliberate tamper helpers so the red-team
and the demo can prove the merchant side (adapters/ap2.py) catches each one.

This is agent-layer code (untrusted, probabilistic world). The deterministic
verifier never imports it - it only ever sees the translated, gate-checked
transaction.
"""
from __future__ import annotations

import time
import uuid

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from bazaar.adapters.ap2 import CART_VCT


class AP2ShoppingAgent:
    """A registered credential provider that signs Cart Mandates with ES256."""

    def __init__(self, cp_id: str = "cp-athleto-1", *, subject: str = "user-42") -> None:
        self.kid = cp_id
        self.subject = subject
        self._key = ec.generate_private_key(ec.SECP256R1())
        self._priv_pem = self._key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()

    @property
    def public_pem(self) -> str:
        """The PEM the merchant registers (kid -> this key) to trust this provider."""
        return self._key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

    def sign_cart(
        self,
        *,
        sku: str,
        title: str,
        unit_amount: int,
        merchant_id: str,
        budget: int,
        quantity: int = 1,
        ttl: int = 900,
        total_override: int | None = None,
        exp_override: int | None = None,
        allowed_payees: list[str] | None = None,
    ) -> str:
        """Sign a Cart Mandate JWS. Overrides let the demo craft tamper cases."""
        now = int(time.time())
        total = total_override if total_override is not None else unit_amount * quantity
        claims = {
            "vct": CART_VCT,
            "iss": self.kid,
            "sub": self.subject,
            "iat": now,
            "exp": exp_override if exp_override is not None else now + ttl,
            "transaction_id": uuid.uuid4().hex,
            "cart": {
                "payee": {"merchant_id": merchant_id},
                "currency": "INR",
                "items": [{
                    "sku": sku, "title": title,
                    "unit_amount": unit_amount, "quantity": quantity,
                }],
                "total_amount": total,
            },
            "constraints": {
                "max_amount": budget,
                "allowed_payees": allowed_payees if allowed_payees is not None else [merchant_id],
            },
        }
        return jwt.encode(claims, self._priv_pem, algorithm="ES256", headers={"kid": self.kid})


def tamper_signature(token: str) -> str:
    """Flip the last few signature chars so ES256 verification must fail."""
    tail = "AAAA" if token[-4:] != "AAAA" else "BBBB"
    return token[:-4] + tail
