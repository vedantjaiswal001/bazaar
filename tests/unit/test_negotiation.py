"""Bounded negotiation stays inside the two walls; upsell raises AOV within cap."""
from __future__ import annotations

from bazaar.agents.negotiation import negotiate
from bazaar.agents.seller import SellerAgent
from bazaar.catalog.seed import seed_default_catalog
from bazaar.catalog.store import CatalogStore


def _seller(db):
    store = CatalogStore(db)
    seed_default_catalog(db)
    return store, SellerAgent("merch-athleto", store.seller_view())


def test_agreed_price_within_walls(db):
    store, seller = _seller(db)
    offer, outcome = negotiate(store=store, seller=seller, buyer_cap=500_000,
                               base_sku="SKU-SHOE-01", upsell=False)
    assert offer is not None and outcome is not None
    assert outcome.within_walls()
    assert outcome.floor_price <= outcome.agreed_price <= min(outcome.list_price, outcome.buyer_cap)
    assert offer.price == outcome.agreed_price
    assert not outcome.upsold


def test_upsell_picks_pricier_in_cap_item(db):
    store, seller = _seller(db)
    base_offer, base = negotiate(store=store, seller=seller, buyer_cap=500_000,
                                 base_sku="SKU-SHOE-01", upsell=False)
    up_offer, up = negotiate(store=store, seller=seller, buyer_cap=500_000,
                             base_sku="SKU-SHOE-01", upsell=True)
    assert up.upsold and up.sku == "SKU-SHOE-PRO"
    assert up.list_price > base.list_price
    assert up_offer.price <= 500_000                 # still within the buyer cap
    assert up_offer.price > base_offer.price         # AOV uplift, within the walls
    assert up.within_walls()


def test_upsell_never_exceeds_cap(db):
    store, seller = _seller(db)
    # A tiny cap means the pro shoe does not fit -> no upsell, base stays.
    offer, outcome = negotiate(store=store, seller=seller, buyer_cap=460_000,
                               base_sku="SKU-SHOE-01", upsell=True)
    assert outcome.agreed_price <= 460_000
