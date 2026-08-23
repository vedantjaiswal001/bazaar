"""End-to-end: intent -> confirm -> sign -> negotiate -> authorize -> receipt + audit.

Also proves the DB-level defenses fire on replay and double-charge, not just the
in-memory checks.
"""
from __future__ import annotations

import pytest

from bazaar.agents.buyer import BuyerAgent
from bazaar.agents.negotiation import negotiate
from bazaar.agents.seller import SellerAgent
from bazaar.catalog.seed import seed_default_catalog
from bazaar.catalog.store import CatalogStore
from bazaar.crypto.signing import generate_keypair
from bazaar.db import repository as repo
from bazaar.ledger.audit_log import verify_chain
from bazaar.verifier.service import AuthorizationService


@pytest.fixture()
def world(db):
    seed_default_catalog(db)
    store = CatalogStore(db)
    seller = SellerAgent("merch-athleto", store.seller_view())
    sk, pk = generate_keypair()
    buyer = BuyerAgent("buyer-1", sk, pk)
    repo.register_agent(db, "buyer-1", "Buyer One", "buyer")
    svc = AuthorizationService(db, authority_keys=generate_keypair())
    return db, store, seller, buyer, svc


def _happy_mandate(buyer, db):
    _, unsigned, view = buyer.draft_mandate(
        "running shoes under ₹5,000 with 30-day returns, buy automatically")
    assert view.is_confirmable()
    mandate = buyer.confirm_and_sign(unsigned)
    repo.save_mandate(db, mandate)
    return mandate


def test_full_happy_path_authorizes_and_proves(world):
    db, store, seller, buyer, svc = world
    mandate = _happy_mandate(buyer, db)
    offer, outcome = negotiate(store=store, seller=seller, buyer_cap=mandate.max_amount,
                               base_sku="SKU-SHOE-01", upsell=False)
    txn = buyer.build_transaction(mandate, offer)

    out = svc.authorize(txn, offer)
    assert out.result.decision == "ALLOW"
    assert out.persisted
    assert out.receipt.verify()                       # cryptographic proof
    assert verify_chain(db).ok                         # audit chain intact
    assert outcome.within_walls()


def test_replay_same_nonce_is_blocked_by_db(world):
    db, store, seller, buyer, svc = world
    mandate = _happy_mandate(buyer, db)
    offer, _ = negotiate(store=store, seller=seller, buyer_cap=mandate.max_amount,
                         base_sku="SKU-SHOE-01")
    txn1 = buyer.build_transaction(mandate, offer)
    assert svc.authorize(txn1, offer).result.decision == "ALLOW"

    # Same nonce, fresh idempotency key -> replay.
    txn2 = buyer.build_transaction(mandate, offer, nonce=txn1.nonce)
    out2 = svc.authorize(txn2, offer)
    assert out2.result.decision == "BLOCK"
    assert out2.result.reason == "NONCE_REPLAY"


def test_double_charge_same_idempotency_key_is_blocked(world):
    db, store, seller, buyer, svc = world
    mandate = _happy_mandate(buyer, db)
    offer, _ = negotiate(store=store, seller=seller, buyer_cap=mandate.max_amount,
                         base_sku="SKU-SHOE-01")
    txn1 = buyer.build_transaction(mandate, offer)
    assert svc.authorize(txn1, offer).result.decision == "ALLOW"

    # Same idempotency key, fresh nonce -> duplicate transaction.
    txn2 = buyer.build_transaction(mandate, offer, idempotency_key=txn1.idempotency_key)
    out2 = svc.authorize(txn2, offer)
    assert out2.result.decision == "BLOCK"
    assert out2.result.reason == "DUPLICATE_TRANSACTION"


def test_frozen_agent_cannot_transact(world):
    db, store, seller, buyer, svc = world
    mandate = _happy_mandate(buyer, db)
    offer, _ = negotiate(store=store, seller=seller, buyer_cap=mandate.max_amount,
                         base_sku="SKU-SHOE-01")
    repo.set_agent_frozen(db, "buyer-1", True)
    txn = buyer.build_transaction(mandate, offer)
    out = svc.authorize(txn, offer)
    assert out.result.decision == "BLOCK"
    assert out.result.reason == "AGENT_FROZEN"
