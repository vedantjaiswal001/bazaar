"""Merchant of record - the authoritative source of price and category.

Trust boundary: the SELLER AGENT gets a read-only view (`seller_view`) with no
write path at all. Prices are seeded/updated only through the admin path
(`seed` / `update_price`), which the seller agent never holds a reference to.

Negotiation asks the merchant of record to `make_offer`. The seller may *propose*
a price, but `make_offer` clamps it into the merchant's own [floor, list] band and
returns an authoritative, snapshotted price. The seller can never move money
outside that band - that is the price-integrity defense.
"""
from __future__ import annotations

import dataclasses
import sqlite3

from bazaar.db import repository as repo
from bazaar.models import MerchantRecord


class SellerCatalogView:
    """Read-only projection handed to the seller agent. Deliberately has no
    write methods, so the seller literally cannot mutate an authoritative price."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, sku: str) -> MerchantRecord | None:
        return repo.get_catalog_item(self._conn, sku)

    def list_active(self) -> list[MerchantRecord]:
        return repo.list_catalog_items(self._conn)


class CatalogStore:
    """Full merchant-of-record store. Only trusted code holds this."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ---- admin / merchant write path (NOT exposed to the seller agent) ----
    def seed(self, items: list[MerchantRecord]) -> None:
        for item in items:
            repo.upsert_catalog_item(self._conn, item)

    def update_price(self, sku: str, new_price: int) -> None:
        item = repo.get_catalog_item(self._conn, sku)
        if item is None:
            raise KeyError(sku)
        repo.upsert_catalog_item(self._conn, dataclasses.replace(item, price=new_price))

    # ---- read path (safe to share) ----
    def get(self, sku: str) -> MerchantRecord | None:
        return repo.get_catalog_item(self._conn, sku)

    def list_active(self) -> list[MerchantRecord]:
        return repo.list_catalog_items(self._conn)

    def seller_view(self) -> SellerCatalogView:
        return SellerCatalogView(self._conn)

    # ---- authoritative pricing (the merchant of record decides the price) ----
    def make_offer(self, sku: str, requested_price: int | None = None) -> MerchantRecord | None:
        """Return an authoritative, snapshotted offer for a sku.

        `requested_price` is what negotiation asked for; the merchant of record
        clamps it into [floor_price, list_price]. With no request, the list price
        is returned. The returned record's `price` is the ONLY price that may
        settle for this transaction.
        """
        item = repo.get_catalog_item(self._conn, sku)
        if item is None or not item.active:
            return None
        if requested_price is None:
            price = item.price
        else:
            lo, hi = item.floor_price, item.price
            price = max(lo, min(requested_price, hi))
        return dataclasses.replace(item, price=price)
