"""Seller agent. Proposes and upsells — but is NEVER the source of truth for price.

It holds only a read-only catalog view. It can suggest a pricier item (bounded
upsell) and counter a buyer's opening price, but the authoritative price always
comes back from the merchant of record via CatalogStore.make_offer().
"""
from __future__ import annotations

from bazaar.catalog.store import SellerCatalogView
from bazaar.models import MerchantRecord


class SellerAgent:
    def __init__(self, merchant_id: str, view: SellerCatalogView) -> None:
        self.merchant_id = merchant_id
        self._view = view

    def list_offers(self, category: str | None = None) -> list[MerchantRecord]:
        items = self._view.list_active()
        return [i for i in items if category is None or i.category == category]

    def propose_upsell(self, base_sku: str, buyer_cap: int) -> str:
        """Suggest the highest-value in-category item whose LIST price still fits
        the buyer's cap. Returns the base sku if nothing better fits."""
        base = self._view.get(base_sku)
        if base is None:
            return base_sku
        candidates = [
            i for i in self._view.list_active()
            if i.category == base.category and i.price <= buyer_cap and i.price >= base.price
        ]
        if not candidates:
            return base_sku
        best = max(candidates, key=lambda i: i.price)
        return best.sku

    def counter(self, record: MerchantRecord, buyer_open_price: int) -> int:
        """One counter-offer, held within the merchant's [floor, list] band."""
        # The seller wants list; it will not go below its floor.
        proposed = max(record.floor_price, min(record.price, buyer_open_price))
        # Nudge back toward list to model a single concession.
        return (proposed + record.price) // 2
