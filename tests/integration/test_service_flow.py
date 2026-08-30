"""End-to-end: intent -> confirm -> sign -> negotiate -> authorize -> receipt + audit.

Also proves the DB-level defenses fire on replay and double-charge, and that the
service pins mandates to the trusted issuer key (a forged mandate is rejected).
"""
from __future__ import annotations

import dataclasses
import uuid

import pytest

from bazaar.agents.buyer import BuyerAgent
from bazaar.agents.issuer import Issuer
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
    issuer = Issuer()                                 # trusted human authority
    buyer = BuyerAgent("buyer-1")                      # proposes only; no signing key
    repo.register_agent(db, "buyer-1", "Buyer One", "buyer")
    svc = AuthorizationService(db, authority_keys=generate_keypair(),
                               trusted_issuer_keys={issuer.public_key})
    return db, store, seller, buyer, issuer, svc


def _happy_mandate(buyer, issuer, db):
    _, unsigned, view = buyer.draft_mandate(
        "running shoes under ₹5,000 with 30-day returns, buy automatically")
    assert view.is_confirmable()
    mandate = issuer.confirm_and_sign(unsigned)        # only the issuer signs
    repo.save_mandate(db, mandate)
    return mandate


def test_full_happy_path_authorizes_and_proves(world):
    db, store, seller, buyer, issuer, svc = world
    mandate = _happy_mandate(buyer, issuer, db)
    offer, outcome = negotiate(store=store, seller=seller, buyer_cap=mandate.max_amount,
                               base_sku="SKU-SHOE-01", upsell=False)
    txn = buyer.build_transaction(mandate, offer)

    out = svc.authorize(txn, offer)
    assert out.result.decision == "ALLOW"
    assert out.persisted
    assert out.receipt.verify()                       # cryptographic proof
    assert verify_chain(db).ok                         # audit chain intact
    assert outcome.within_walls()


def test_forged_mandate_signed_by_agent_key_is_blocked(world):
    """A mandate the agent minted and signed with its OWN key is rejected: the
    signature is valid but the key is not the trusted issuer's."""
    db, store, seller, buyer, issuer, svc = world
    _, unsigned, _ = buyer.draft_mandate("shoes under ₹5,000, 30-day returns, auto")
    attacker = Issuer()                                # a key that is NOT the trusted issuer
    forged = attacker.confirm_and_sign(
        dataclasses.replace(unsigned, mandate_id=f"m-{uuid.uuid4().hex[:8]}",
                            max_amount=unsigned.max_amount * 100))
    repo.save_mandate(db, forged)
    offer = store.make_offer("SKU-SHOE-01")
    txn = buyer.build_transaction(forged, offer)
    out = svc.authorize(txn, offer)
    assert out.result.decision == "BLOCK"
    assert out.result.reason == "MANDATE_IMMUTABLE"


def test_replay_same_nonce_is_blocked_by_db(world):
    db, store, seller, buyer, issuer, svc = world
    mandate = _happy_mandate(buyer, issuer, db)
    offer, _ = negotiate(store=store, seller=seller, buyer_cap=mandate.max_amount,
                         base_sku="SKU-SHOE-01")
    txn1 = buyer.build_transaction(mandate, offer)
    assert svc.authorize(txn1, offer).result.decision == "ALLOW"

    txn2 = buyer.build_transaction(mandate, offer, nonce=txn1.nonce)
    out2 = svc.authorize(txn2, offer)
    assert out2.result.decision == "BLOCK"
    assert out2.result.reason == "NONCE_REPLAY"


def test_double_charge_same_idempotency_key_is_blocked(world):
    db, store, seller, buyer, issuer, svc = world
    mandate = _happy_mandate(buyer, issuer, db)
    offer, _ = negotiate(store=store, seller=seller, buyer_cap=mandate.max_amount,
                         base_sku="SKU-SHOE-01")
    txn1 = buyer.build_transaction(mandate, offer)
    assert svc.authorize(txn1, offer).result.decision == "ALLOW"

    txn2 = buyer.build_transaction(mandate, offer, idempotency_key=txn1.idempotency_key)
    out2 = svc.authorize(txn2, offer)
    assert out2.result.decision == "BLOCK"
    assert out2.result.reason == "DUPLICATE_TRANSACTION"


def test_frozen_agent_cannot_transact(world):
    db, store, seller, buyer, issuer, svc = world
    mandate = _happy_mandate(buyer, issuer, db)
    offer, _ = negotiate(store=store, seller=seller, buyer_cap=mandate.max_amount,
                         base_sku="SKU-SHOE-01")
    repo.set_agent_frozen(db, "buyer-1", True)
    txn = buyer.build_transaction(mandate, offer)
    out = svc.authorize(txn, offer)
    assert out.result.decision == "BLOCK"
    assert out.result.reason == "AGENT_FROZEN"
