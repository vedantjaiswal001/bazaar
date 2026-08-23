"""Razorpay Test Mode client — real Orders + Payments.

Keys come from the environment only (RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET);
never hardcoded. This wraps the official `razorpay` SDK. Order creation is a
payment-mutating operation, so we do NOT assume Razorpay dedupes it for us: we
pass our own idempotency key as the order `receipt` and dedupe at our own layer
(see settlement.py) — an honest choice that does not invent an API guarantee.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bazaar.config import settings


class RazorpayNotConfigured(RuntimeError):
    """Raised when a live Razorpay operation is attempted without test keys."""


@dataclass
class OrderResult:
    order_id: str
    amount: int
    currency: str
    status: str
    receipt: str
    raw: dict[str, Any]


class RazorpayClient:
    """Thin wrapper over the official SDK. Test mode only in this project."""

    def __init__(self, key_id: str | None = None, key_secret: str | None = None) -> None:
        self.key_id = key_id or settings.razorpay_key_id
        self.key_secret = key_secret or settings.razorpay_key_secret
        self._client = None

    def _sdk(self):
        if not self.key_id or not self.key_secret:
            raise RazorpayNotConfigured(
                "RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not set. Copy .env.example "
                "to .env and add your Razorpay TEST-mode keys."
            )
        if not self.key_id.startswith("rzp_test_"):
            # Guardrail: this project must never touch live keys.
            raise RazorpayNotConfigured("refusing to run: key is not a rzp_test_ (Test Mode) key")
        if self._client is None:
            import razorpay  # imported lazily so the rest of the system needs no keys

            self._client = razorpay.Client(auth=(self.key_id, self.key_secret))
        return self._client

    def create_order(self, *, amount: int, receipt: str, currency: str = "INR",
                     notes: dict[str, str] | None = None) -> OrderResult:
        """Create a Test Mode order for an authorized transaction. `amount` is paise."""
        data = {
            "amount": amount,
            "currency": currency,
            "receipt": receipt,          # our idempotency key -> our own dedupe reference
            "notes": notes or {},
            "payment_capture": 1,
        }
        order = self._sdk().order.create(data=data)
        return OrderResult(
            order_id=order["id"], amount=order["amount"], currency=order["currency"],
            status=order["status"], receipt=order.get("receipt", receipt), raw=order,
        )

    def fetch_order(self, order_id: str) -> dict[str, Any]:
        return self._sdk().order.fetch(order_id)

    def fetch_payment(self, payment_id: str) -> dict[str, Any]:
        return self._sdk().payment.fetch(payment_id)

    def order_payments(self, order_id: str) -> dict[str, Any]:
        """All payments against an order — the reconciliation source of truth."""
        return self._sdk().order.payments(order_id)
