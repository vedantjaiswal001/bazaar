"""Webhook verification + reconciliation, tested without any live Razorpay keys.

Covers: signature verify pass/fail, the ambiguous-window default (not paid),
doubled webhook (no double-settle), late webhook (reconcile, never re-charge),
amount-mismatch rejection, and idempotent order creation.
"""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from bazaar.agents.buyer import BuyerAgent
from bazaar.agents.issuer import Issuer
from bazaar.agents.negotiation import negotiate
from bazaar.agents.seller import SellerAgent
from bazaar.catalog.seed import seed_default_catalog
from bazaar.catalog.store import CatalogStore
from bazaar.crypto.signing import generate_keypair
from bazaar.db import repository as repo
from bazaar.razorpay.client import OrderResult
from bazaar.razorpay.settlement import reconcile, settle
from bazaar.razorpay.webhooks import handle_event, verify_webhook_signature
from bazaar.verifier.service import AuthorizationService

WEBHOOK_SECRET = "whsec_test_bazaar"


class FakeRazorpay:
    """Stands in for RazorpayClient in tests. Deterministic, no network."""

    def __init__(self):
        self.n = 0
        self.captured: dict[str, list] = {}

    def create_order(self, *, amount, receipt, currency="INR", notes=None):
        self.n += 1
        return OrderResult(order_id=f"order_FAKE{self.n}", amount=amount, currency=currency,
                           status="created", receipt=receipt, raw={})

    def order_payments(self, order_id):
        return {"items": self.captured.get(order_id, [])}


def _authorized_txn(db):
    seed_default_catalog(db)
    store = CatalogStore(db)
    seller = SellerAgent("merch-athleto", store.seller_view())
    issuer = Issuer()
    buyer = BuyerAgent("buyer-1")
    repo.register_agent(db, "buyer-1", "Buyer One", "buyer")
    svc = AuthorizationService(db, authority_keys=generate_keypair(),
                               trusted_issuer_keys={issuer.public_key})
    _, unsigned, _ = buyer.draft_mandate("shoes under ₹5,000, 30-day returns, auto")
    mandate = issuer.confirm_and_sign(unsigned)
    repo.save_mandate(db, mandate)
    offer, _ = negotiate(store=store, seller=seller, buyer_cap=mandate.max_amount,
                         base_sku="SKU-SHOE-01")
    txn = buyer.build_transaction(mandate, offer)
    out = svc.authorize(txn, offer)
    assert out.result.decision == "ALLOW"
    return txn, offer


def _signed_event(body: dict) -> tuple[bytes, str]:
    raw = json.dumps(body).encode("utf-8")
    sig = hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return raw, sig


def _captured_event(order_id: str, payment_id: str, amount: int) -> dict:
    return {"event": "payment.captured",
            "payload": {"payment": {"entity": {"id": payment_id, "order_id": order_id,
                                               "amount": amount, "status": "captured"}}}}


def test_signature_verification():
    raw, sig = _signed_event({"event": "payment.captured"})
    assert verify_webhook_signature(raw, sig, WEBHOOK_SECRET)
    assert not verify_webhook_signature(raw, "deadbeef", WEBHOOK_SECRET)
    assert not verify_webhook_signature(raw, sig, "wrong_secret")


def test_settle_is_idempotent(db):
    txn, _ = _authorized_txn(db)
    fake = FakeRazorpay()
    r1 = settle(db, txn.txn_id, fake)
    r2 = settle(db, txn.txn_id, fake)
    assert r1.status == "order_created"
    assert r2.status == "order_exists"
    assert r1.order_id == r2.order_id           # same order - no second charge
    assert fake.n == 1                            # create_order called exactly once


def test_ambiguous_window_defaults_to_not_paid(db):
    txn, _ = _authorized_txn(db)
    settle(db, txn.txn_id, FakeRazorpay())
    row = db.execute("SELECT status FROM transactions WHERE txn_id=?", (txn.txn_id,)).fetchone()
    assert row["status"] == "pending_settlement"   # NOT 'settled' until confirmed


def test_captured_webhook_settles_once_and_doubled_webhook_is_ignored(db):
    txn, _ = _authorized_txn(db)
    res = settle(db, txn.txn_id, FakeRazorpay())
    event = _captured_event(res.order_id, "pay_ABC", res.amount)

    first = handle_event(db, event)
    second = handle_event(db, event)             # exact duplicate delivery
    assert first.action == "settled"
    assert second.action == "duplicate_ignored"
    row = db.execute("SELECT status, razorpay_payment_id FROM transactions WHERE txn_id=?",
                     (txn.txn_id,)).fetchone()
    assert row["status"] == "settled"
    assert row["razorpay_payment_id"] == "pay_ABC"  # one payment, never doubled


def test_amount_mismatch_is_rejected(db):
    txn, _ = _authorized_txn(db)
    res = settle(db, txn.txn_id, FakeRazorpay())
    bad = _captured_event(res.order_id, "pay_BAD", res.amount + 100_000)  # wrong amount
    out = handle_event(db, bad)
    assert out.action == "amount_mismatch"
    row = db.execute("SELECT status FROM transactions WHERE txn_id=?", (txn.txn_id,)).fetchone()
    assert row["status"] == "pending_settlement"    # unchanged; never settled a wrong amount


def test_late_webhook_reconciles_not_recharge(db):
    txn, _ = _authorized_txn(db)
    fake = FakeRazorpay()
    res = settle(db, txn.txn_id, fake)
    # Webhook was "missed"; reconcile finds no capture yet -> stays not paid.
    r = reconcile(db, txn.txn_id, fake)
    assert r.status == "order_exists"
    # Now Razorpay shows the capture; a late reconcile settles exactly once.
    fake.captured[res.order_id] = [{"id": "pay_LATE", "status": "captured", "amount": res.amount}]
    r2 = reconcile(db, txn.txn_id, fake)
    assert r2.status == "already_settled"
    assert fake.n == 1                                # never created a second order (no re-charge)


@pytest.mark.parametrize("etype", ["payment.captured", "order.paid"])
def test_capture_events_settle(db, etype):
    txn, _ = _authorized_txn(db)
    res = settle(db, txn.txn_id, FakeRazorpay())
    event = _captured_event(res.order_id, "pay_X", res.amount)
    event["event"] = etype
    assert handle_event(db, event).action == "settled"
