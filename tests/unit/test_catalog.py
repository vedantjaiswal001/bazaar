"""The seller has no write path; the merchant of record clamps prices to its band."""
from __future__ import annotations

from bazaar.catalog.seed import seed_default_catalog
from bazaar.catalog.store import CatalogStore, SellerCatalogView


def test_seller_view_has_no_write_methods(db):
    view = CatalogStore(db).seller_view()
    assert isinstance(view, SellerCatalogView)
    for forbidden in ("seed", "update_price", "make_offer", "upsert"):
        assert not hasattr(view, forbidden), f"seller view must not expose {forbidden}"


def test_seller_view_can_only_read(db):
    seed_default_catalog(db)
    view = CatalogStore(db).seller_view()
    rec = view.get("SKU-SHOE-01")
    assert rec is not None and rec.price == 449_900
    assert {r.sku for r in view.list_active()} >= {"SKU-SHOE-01", "SKU-SHOE-PRO"}


def test_make_offer_clamps_below_floor(db):
    seed_default_catalog(db)
    store = CatalogStore(db)
    # Ask for a price below the floor -> clamped up to floor.
    offer = store.make_offer("SKU-SHOE-01", requested_price=100)
    assert offer is not None and offer.price == 400_000  # floor


def test_make_offer_clamps_above_list(db):
    seed_default_catalog(db)
    store = CatalogStore(db)
    offer = store.make_offer("SKU-SHOE-01", requested_price=10_000_000)
    assert offer is not None and offer.price == 449_900  # list price ceiling


def test_make_offer_respects_negotiated_price_in_band(db):
    seed_default_catalog(db)
    store = CatalogStore(db)
    offer = store.make_offer("SKU-SHOE-01", requested_price=425_000)
    assert offer is not None and offer.price == 425_000  # inside [400000, 449900]
