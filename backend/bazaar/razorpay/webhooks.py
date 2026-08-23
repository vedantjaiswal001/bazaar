"""Razorpay webhook verification + idempotent reconciliation.

Two rules from the threat model, enforced here:

  * Signature first. An unsigned or wrongly-signed webhook is rejected before any
    state change (HMAC-SHA256 over the raw body with the webhook secret).
  * The ambiguous window defaults to NOT PAID. A transaction only becomes
    'settled' when a verified webhook (or a reconcile against Razorpay, the source
    of truth) confirms a captured payment for the right order and the right amount.
    A duplicate or late webhook never double-settles and never re-charges.
"""
from __future__ import annotations

import hashlib
import hmac
import sqlite3
from dataclasses import dataclass
from typing import Any

from bazaar.db import repository as repo
from bazaar.ledger.audit_log import append_event


def verify_webhook_signature(body: bytes, signature: str, secret: str) -> bool:
    """Constant-time HMAC-SHA256 check, matching Razorpay's webhook scheme."""
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@dataclass
class WebhookResult:
    action: str          # 'settled' | 'duplicate_ignored' | 'failed' | 'unknown_order' | 'amount_mismatch'
    txn_id: str | None
    detail: str


def _payment_entity(event: dict[str, Any]) -> dict[str, Any]:
    try:
        return event["payload"]["payment"]["entity"]
    except (KeyError, TypeError):
        return {}


def handle_event(conn: sqlite3.Connection, event: dict[str, Any]) -> WebhookResult:
    """Apply a *verified* webhook event to our state, idempotently.

    Call verify_webhook_signature() on the raw body BEFORE this. Never creates an
    order and never re-charges — reconciliation only moves state forward once.
    """
    etype = event.get("event", "")
    entity = _payment_entity(event)
    order_id = entity.get("order_id")
    payment_id = entity.get("id")
    amount = entity.get("amount")

    if not order_id:
        return WebhookResult("unknown_order", None, "event has no order_id")

    row = conn.execute(
        "SELECT txn_id, amount, status, razorpay_payment_id FROM transactions "
        "WHERE razorpay_order_id = ?", (order_id,),
    ).fetchone()
    if row is None:
        return WebhookResult("unknown_order", None, f"no transaction for order {order_id}")

    txn_id = row["txn_id"]

    # Amount guard: never settle a different amount than we authorized.
    if amount is not None and int(amount) != int(row["amount"]):
        return WebhookResult("amount_mismatch", txn_id,
                             f"webhook amount {amount} != authorized {row['amount']}")

    # Idempotency: already settled with this payment -> no-op (duplicate/late webhook).
    if row["status"] == "settled" and row["razorpay_payment_id"] == payment_id:
        return WebhookResult("duplicate_ignored", txn_id, "already settled with this payment")

    if etype in ("payment.captured", "order.paid"):
        if row["status"] == "settled":
            # Already settled (possibly by a prior different event) — do not re-charge.
            return WebhookResult("duplicate_ignored", txn_id, "already settled")
        repo.set_transaction_settlement(conn, txn_id, status="settled",
                                        razorpay_payment_id=payment_id)
        append_event(conn, "settlement", {
            "txn_id": txn_id, "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id, "status": "settled",
        })
        return WebhookResult("settled", txn_id, "payment captured and reconciled")

    if etype == "payment.failed":
        if row["status"] != "settled":
            repo.set_transaction_settlement(conn, txn_id, status="failed",
                                            razorpay_payment_id=payment_id)
            append_event(conn, "settlement", {
                "txn_id": txn_id, "razorpay_order_id": order_id, "status": "failed",
            })
        return WebhookResult("failed", txn_id, "payment failed")

    return WebhookResult("unknown_order", txn_id, f"unhandled event type {etype}")
