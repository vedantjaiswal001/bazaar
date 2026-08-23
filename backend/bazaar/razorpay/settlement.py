"""Settlement flow for an AUTHORIZED transaction.

The gate authorizes; settlement is a separate step that creates a real Razorpay
Test Mode order. Two safety properties:

  * Idempotent: if a transaction already has an order, we return it instead of
    creating a second one - a retry can never produce a double charge.
  * Ambiguous = not paid: creating the order sets status 'pending_settlement'.
    The transaction becomes 'settled' only via a verified webhook (webhooks.py)
    or a reconcile against Razorpay, which is the source of truth.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from bazaar.db import repository as repo
from bazaar.ledger.audit_log import append_event
from bazaar.razorpay.client import RazorpayClient


@dataclass
class SettlementResult:
    status: str            # 'order_created' | 'already_settled' | 'order_exists' | 'not_authorized'
    txn_id: str
    order_id: str | None
    amount: int | None
    detail: str


def _txn_row(conn: sqlite3.Connection, txn_id: str):
    return conn.execute(
        "SELECT txn_id, amount, decision, status, razorpay_order_id "
        "FROM transactions WHERE txn_id = ?", (txn_id,),
    ).fetchone()


def settle(conn: sqlite3.Connection, txn_id: str, client: RazorpayClient) -> SettlementResult:
    """Create (or return the existing) Razorpay order for an authorized transaction."""
    row = _txn_row(conn, txn_id)
    if row is None:
        return SettlementResult("not_authorized", txn_id, None, None, "no such transaction")
    if row["decision"] != "ALLOW":
        return SettlementResult("not_authorized", txn_id, None, None,
                                f"transaction decision is {row['decision']}, not ALLOW")
    if row["status"] == "review_hold":
        return SettlementResult("not_authorized", txn_id, None, row["amount"],
                                "transaction is on human-review hold; approve before settling")
    if row["status"] == "settled":
        return SettlementResult("already_settled", txn_id, row["razorpay_order_id"],
                                row["amount"], "already settled")
    if row["razorpay_order_id"]:
        # Idempotent: reuse the existing order, never create a second one.
        return SettlementResult("order_exists", txn_id, row["razorpay_order_id"],
                                row["amount"], "order already created for this transaction")

    order = client.create_order(amount=int(row["amount"]), receipt=txn_id,
                                notes={"txn_id": txn_id})
    repo.set_transaction_settlement(conn, txn_id, status="pending_settlement",
                                    razorpay_order_id=order.order_id)
    append_event(conn, "settlement", {
        "txn_id": txn_id, "razorpay_order_id": order.order_id,
        "amount": int(row["amount"]), "status": "pending_settlement",
    })
    return SettlementResult("order_created", txn_id, order.order_id, int(row["amount"]),
                            "order created; awaiting captured-payment webhook (default: NOT PAID)")


def reconcile(conn: sqlite3.Connection, txn_id: str, client: RazorpayClient) -> SettlementResult:
    """Fallback for the ambiguous window: ask Razorpay (source of truth) directly."""
    row = _txn_row(conn, txn_id)
    if row is None or not row["razorpay_order_id"]:
        return SettlementResult("not_authorized", txn_id, None, None, "no order to reconcile")
    if row["status"] == "settled":
        return SettlementResult("already_settled", txn_id, row["razorpay_order_id"],
                                row["amount"], "already settled")

    payments = client.order_payments(row["razorpay_order_id"])
    for p in payments.get("items", []):
        if p.get("status") == "captured" and int(p.get("amount", -1)) == int(row["amount"]):
            repo.set_transaction_settlement(conn, txn_id, status="settled",
                                            razorpay_payment_id=p.get("id"))
            append_event(conn, "settlement", {
                "txn_id": txn_id, "razorpay_order_id": row["razorpay_order_id"],
                "razorpay_payment_id": p.get("id"), "status": "settled",
                "via": "reconcile",
            })
            return SettlementResult("already_settled", txn_id, row["razorpay_order_id"],
                                    row["amount"], "reconciled from Razorpay as captured")
    # Still not captured -> remain NOT PAID. Never re-charge.
    return SettlementResult("order_exists", txn_id, row["razorpay_order_id"], row["amount"],
                            "no captured payment yet - remains not paid")
