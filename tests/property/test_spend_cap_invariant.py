"""Property: the gate never authorizes an amount above the signed mandate cap.

This is invariant #3 - the primary property the fuzzer targets. Hypothesis throws
thousands of randomized states (random caps, amounts, prices, categories,
provenance, clocks, and DB flags) at the pure gate and asserts:

    result.decision == ALLOW  =>  amount <= signed cap  (and amount == record price)

We generate valid signatures (one module keypair) so ALLOW is actually reachable;
the invariant must hold on every single example regardless.
"""
from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bazaar.crypto.signing import generate_keypair
from bazaar.models import PriceSource
from bazaar.verifier.gate import apply_risk, authorize
from bazaar.verifier.reasons import Decision
from bazaar.risk.model import assess
from tests.factory import make_record, make_signed_mandate, make_txn

# One keypair for the whole module: every generated mandate is validly signed.
_SK, _VK = generate_keypair()

_CATEGORIES = ["footwear", "apparel", "wearables", "electronics", "grocery"]
_amounts = st.integers(min_value=0, max_value=10_000_000)


@st.composite
def scenario(draw):
    cap = draw(st.integers(min_value=1, max_value=10_000_000))
    # "coherent" scenarios engineer the ALLOW path to be reachable and push the
    # amount right up against the cap boundary, so the invariant is tested where
    # it actually bites - not vacuously on states that block on price first.
    coherent = draw(st.booleans())
    if coherent:
        price = draw(st.integers(min_value=0, max_value=int(cap * 1.3) + 1))
        amount = price
        category = draw(st.sampled_from(_CATEGORIES))
        allowed = list({*draw(st.lists(st.sampled_from(_CATEGORIES), min_size=1, max_size=5)), category})
        price_source = PriceSource.MERCHANT_RECORD
        ttl = draw(st.integers(min_value=60, max_value=900))
        active = True
        nonce_seen = draw(st.booleans())
        idem_seen = draw(st.booleans())
        frozen = draw(st.booleans())
    else:
        amount = draw(_amounts)
        price = draw(_amounts)
        category = draw(st.sampled_from(_CATEGORIES))
        allowed = draw(st.lists(st.sampled_from(_CATEGORIES), min_size=1, max_size=5, unique=True))
        price_source = draw(st.sampled_from(list(PriceSource)))
        ttl = draw(st.integers(min_value=-500, max_value=900))
        nonce_seen = draw(st.booleans())
        idem_seen = draw(st.booleans())
        frozen = draw(st.booleans())
        active = draw(st.booleans())

    mandate = make_signed_mandate(
        signing_key=_SK, public_key=_VK,
        max_amount=cap, allowed_categories=tuple(allowed), ttl_seconds=max(ttl, 1),
        issued_offset_seconds=0 if ttl > 0 else -1000,
    )
    record = make_record(sku="SKU-X", category=category, price=price, active=active)
    txn = make_txn(mandate=mandate, sku="SKU-X", category=category, amount=amount,
                   price_source=price_source)
    return mandate, record, txn, nonce_seen, idem_seen, frozen


@settings(max_examples=2000, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(scenario())
def test_allow_implies_within_cap(s):
    mandate, record, txn, nonce_seen, idem_seen, frozen = s
    result = authorize(txn, record, nonce_seen=nonce_seen,
                       idempotency_seen=idem_seen, agent_frozen=frozen)
    if result.decision == Decision.ALLOW.value:
        # The core money invariant, plus the stronger facts ALLOW guarantees.
        assert txn.amount <= mandate.max_amount
        assert txn.amount == record.price
        assert record.active
        assert txn.price_source == PriceSource.MERCHANT_RECORD
        assert record.category in mandate.allowed_categories
        assert not nonce_seen and not idem_seen and not frozen
        assert not mandate.is_expired()


@settings(max_examples=1000, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(scenario())
def test_risk_never_widens_authority(s):
    """Applying the advisory risk signal can only tighten, never approve."""
    mandate, record, txn, nonce_seen, idem_seen, frozen = s
    base = authorize(txn, record, nonce_seen=nonce_seen,
                     idempotency_seen=idem_seen, agent_frozen=frozen)
    tightened = apply_risk(base, assess(txn, record))
    ordering = {Decision.ALLOW.value: 0, Decision.REVIEW.value: 1, Decision.BLOCK.value: 2}
    # The post-risk decision is at least as strict as the deterministic one.
    assert ordering[tightened.decision] >= ordering[base.decision]
    # And a block is never softened to an allow.
    if base.decision == Decision.BLOCK.value:
        assert tightened.decision == Decision.BLOCK.value
