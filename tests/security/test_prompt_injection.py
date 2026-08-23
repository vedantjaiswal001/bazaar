"""Prompt injection in catalog text can move words, never money.

Two facts, both asserted:
  1. The HONEST agent sources money-fields from the merchant of record, so an
     injected instruction in the description has ZERO effect - the purchase
     settles at the true price and is ALLOWed.
  2. A FOOLED agent that took a money-field from the untrusted description is
     blocked outright with UNTRUSTED_INSTRUCTION, whatever the value happens to be.
"""
from __future__ import annotations

import dataclasses

from bazaar.agents.buyer import BuyerAgent
from bazaar.agents.issuer import Issuer
from bazaar.catalog.seed import seed_default_catalog
from bazaar.catalog.store import CatalogStore
from bazaar.crypto.signing import generate_keypair
from bazaar.db import repository as repo
from bazaar.models import PriceSource
from bazaar.risk.model import scan_injection
from bazaar.verifier.service import AuthorizationService


def _world(db):
    seed_default_catalog(db)
    store = CatalogStore(db)
    issuer = Issuer()
    buyer = BuyerAgent("buyer-1")
    repo.register_agent(db, "buyer-1", "Buyer One", "buyer")
    svc = AuthorizationService(db, authority_keys=generate_keypair(),
                               trusted_issuer_keys={issuer.public_key})
    _, unsigned, _ = buyer.draft_mandate("shoes under ₹5,000, 30-day returns, auto")
    mandate = issuer.confirm_and_sign(unsigned)
    repo.save_mandate(db, mandate)
    return store, buyer, svc, mandate


def test_injected_description_is_detectable(db):
    store, _, _, _ = _world(db)
    rec = store.get("SKU-SHOE-INJ")
    assert rec is not None
    assert scan_injection(rec.description)          # the payload is really there


def test_honest_agent_ignores_injection_and_settles_true_price(db):
    store, buyer, svc, mandate = _world(db)
    offer = store.make_offer("SKU-SHOE-INJ")         # authoritative record, ignores text
    txn = buyer.build_transaction(mandate, offer)
    out = svc.authorize(txn, offer)
    assert out.result.decision == "ALLOW"
    assert txn.amount == offer.price                 # settled at the TRUE price, not ₹99,999
    assert txn.price_source == PriceSource.MERCHANT_RECORD


def test_fooled_agent_taking_text_as_money_is_blocked(db):
    store, buyer, svc, mandate = _world(db)
    offer = store.make_offer("SKU-SHOE-INJ")
    txn = buyer.build_transaction(mandate, offer)
    fooled = dataclasses.replace(txn, price_source=PriceSource.DESCRIPTION)
    out = svc.authorize(fooled, offer)
    assert out.result.decision == "BLOCK"
    assert out.result.reason == "UNTRUSTED_INSTRUCTION"
