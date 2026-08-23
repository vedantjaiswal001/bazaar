"""Bounded negotiation - exactly one round, inside two hard walls.

The two walls are the buyer's signed mandate cap and the seller's policy floor,
both visible in the transcript (and on screen in the UI). The negotiated price is
never taken from the seller's word: it is finalized by the merchant of record via
CatalogStore.make_offer(), which clamps it into [floor, list]. The returned offer
snapshot's price is the only price that can settle.
"""
from __future__ import annotations

from dataclasses import dataclass

from bazaar.agents.seller import SellerAgent
from bazaar.catalog.store import CatalogStore
from bazaar.models import MerchantRecord


@dataclass(frozen=True)
class NegotiationStep:
    actor: str
    price: int
    note: str


@dataclass(frozen=True)
class NegotiationOutcome:
    sku: str
    list_price: int
    floor_price: int
    buyer_cap: int
    agreed_price: int
    upsold: bool
    transcript: list[NegotiationStep]

    def within_walls(self) -> bool:
        return self.floor_price <= self.agreed_price <= min(self.list_price, self.buyer_cap)


def negotiate(
    *,
    store: CatalogStore,
    seller: SellerAgent,
    buyer_cap: int,
    base_sku: str,
    upsell: bool = False,
) -> tuple[MerchantRecord | None, NegotiationOutcome | None]:
    """Run one bounded negotiation round and return (authoritative_offer, outcome)."""
    sku = seller.propose_upsell(base_sku, buyer_cap) if upsell else base_sku
    record = store.get(sku)
    if record is None:
        return None, None

    upper = min(record.price, buyer_cap)              # can't agree above list or above cap
    lower = record.floor_price                        # can't agree below the seller's floor
    if upper < lower:
        return None, None                             # no viable price: cap below the seller floor
    transcript: list[NegotiationStep] = [
        NegotiationStep("walls", 0, f"buyer cap {buyer_cap} · seller floor {lower} · list {record.price}"),
    ]

    if upsell and sku != base_sku:
        transcript.append(NegotiationStep("seller", record.price,
                                          f"upsell to {sku} (in-category, within cap)"))

    buyer_open = lower                                # buyer opens at the floor
    transcript.append(NegotiationStep("buyer", buyer_open, "opens at the seller's floor"))
    seller_counter = seller.counter(record, buyer_open)
    transcript.append(NegotiationStep("seller", seller_counter, "one concession toward list"))

    midpoint = (buyer_open + seller_counter) // 2
    agreed = max(lower, min(midpoint, upper))         # clamp inside the walls

    # Authoritative finalization: the merchant of record clamps to its band.
    offer = store.make_offer(sku, requested_price=agreed)
    if offer is None:
        return None, None
    transcript.append(NegotiationStep("merchant_of_record", offer.price,
                                      "authoritative price (clamped to [floor, list])"))

    outcome = NegotiationOutcome(
        sku=sku, list_price=record.price, floor_price=lower, buyer_cap=buyer_cap,
        agreed_price=offer.price, upsold=(sku != base_sku), transcript=transcript,
    )
    return offer, outcome
