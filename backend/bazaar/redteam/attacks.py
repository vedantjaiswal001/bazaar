"""Red-team attack generators - labeled cases for every class in the threat model.

Each case is fully self-describing: a transaction (plus the DB-state flags the
gate needs) and the verdict + reason code we expect. The benchmark runs these
through the PURE gate, so the whole thing is reproducible from a seed with no I/O.

Attack classes and the reason each must produce:
  budget->MANDATE_LIMIT_EXCEEDED  policy->MANDATE_IMMUTABLE
  price->PRICE_MISMATCH_MERCHANT_RECORD  replay->NONCE_REPLAY
  double_charge->DUPLICATE_TRANSACTION  category->CATEGORY_OUTSIDE_MANDATE
  injection->UNTRUSTED_INSTRUCTION  state->AGENT_FROZEN  expiry->MANDATE_EXPIRED
"""
from __future__ import annotations

import dataclasses
import random
import uuid
from dataclasses import dataclass
from datetime import timedelta

from bazaar.crypto.signing import generate_keypair
from bazaar.models import (
    Mandate,
    MerchantRecord,
    PriceSource,
    TransactionRequest,
    now_utc,
    sign_mandate,
    to_rfc3339,
)
from bazaar.verifier.reasons import ATTACK_CLASS_TO_REASON, Decision, Reason

ATTACK_CLASSES = list(ATTACK_CLASS_TO_REASON.keys())
_ALLOW_CATS = ("footwear",)
_CATEGORIES = ["footwear", "apparel", "wearables", "electronics", "grocery"]
_CAP = 500_000  # ₹5,000


@dataclass(frozen=True)
class Case:
    id: str
    kind: str                    # 'attack' | 'legit'
    attack_class: str | None
    txn: TransactionRequest
    offer: MerchantRecord | None
    expected_decision: str
    expected_reason: str
    nonce_seen: bool = False
    idem_seen: bool = False
    agent_frozen: bool = False
    trusted_issuer_keys: frozenset[str] | None = None


def _mandate(sk: str, pk: str, *, cap: int = _CAP, cats=_ALLOW_CATS,
             ttl: int = 900, issued_offset: int = 0) -> Mandate:
    issued = now_utc() + timedelta(seconds=issued_offset)
    expires = issued + timedelta(seconds=ttl)
    draft = Mandate(
        mandate_id=f"m-{uuid.uuid4().hex[:8]}", agent_id="buyer-1", max_amount=cap,
        allowed_categories=cats, return_policy_days=30,
        issued_at=to_rfc3339(issued), expires_at=to_rfc3339(expires),
    )
    return sign_mandate(sk, pk, draft)


def _record(*, sku="SKU-X", category="footwear", price=449_900) -> MerchantRecord:
    return MerchantRecord(sku=sku, merchant_id="m", title="x", category=category,
                          price=price, floor_price=max(0, price - 50_000))


def _txn(mandate: Mandate, offer: MerchantRecord, *, amount=None,
         price_source=PriceSource.MERCHANT_RECORD) -> TransactionRequest:
    return TransactionRequest(
        txn_id=f"t-{uuid.uuid4().hex[:10]}", mandate=mandate, agent_id="buyer-1",
        sku=offer.sku, category=offer.category,
        amount=offer.price if amount is None else amount,
        price_source=price_source, nonce=uuid.uuid4().hex, idempotency_key=uuid.uuid4().hex,
    )


def _make_attack(cls: str, rng: random.Random, sk: str, pk: str) -> Case:
    """Build one attack of the given class, engineered to trigger its reason code."""
    reason = ATTACK_CLASS_TO_REASON[cls].value
    m = _mandate(sk, pk)

    if cls == "budget":
        price = rng.randint(_CAP + 1, _CAP * 2)                # genuinely over cap
        offer = _record(price=price)
        txn = _txn(m, offer)                                   # amount == price > cap
    elif cls == "policy":
        offer = _record(price=rng.randint(100_000, _CAP))
        # Forged mandate: the agent mints a mandate with a doubled cap and signs it
        # with its OWN key. Internally valid, but the key is not the trusted issuer.
        atk_sk, atk_pk = generate_keypair()
        forged = _mandate(atk_sk, atk_pk, cap=_CAP * 2)
        txn = _txn(forged, offer)
    elif cls == "price":
        p = rng.randint(100_000, _CAP)
        offer = _record(price=p)
        txn = _txn(m, offer, amount=rng.choice([p - 10_000, p + 10_000]))  # != record
    elif cls == "replay":
        offer = _record(price=rng.randint(100_000, _CAP))
        txn = _txn(m, offer)
        return Case(f"atk-{cls}-{uuid.uuid4().hex[:6]}", "attack", cls, txn, offer,
                    Decision.BLOCK.value, reason, nonce_seen=True)
    elif cls == "double_charge":
        offer = _record(price=rng.randint(100_000, _CAP))
        txn = _txn(m, offer)
        return Case(f"atk-{cls}-{uuid.uuid4().hex[:6]}", "attack", cls, txn, offer,
                    Decision.BLOCK.value, reason, idem_seen=True)
    elif cls == "category":
        offer = _record(sku="SKU-WATCH", category="wearables",
                        price=rng.randint(100_000, _CAP))       # off-mandate category
        txn = _txn(m, offer)
    elif cls == "injection":
        offer = _record(price=rng.randint(100_000, _CAP))
        txn = _txn(m, offer, price_source=rng.choice(
            [PriceSource.DESCRIPTION, PriceSource.SELLER_CLAIM, PriceSource.AGENT_INVENTED]))
    elif cls == "state":
        offer = _record(price=rng.randint(100_000, _CAP))
        txn = _txn(m, offer)
        return Case(f"atk-{cls}-{uuid.uuid4().hex[:6]}", "attack", cls, txn, offer,
                    Decision.BLOCK.value, reason, agent_frozen=True)
    elif cls == "expiry":
        m_exp = _mandate(sk, pk, ttl=10, issued_offset=-1000)   # long expired
        offer = _record(price=rng.randint(100_000, _CAP))
        txn = _txn(m_exp, offer)
    else:  # pragma: no cover
        raise ValueError(cls)

    return Case(f"atk-{cls}-{uuid.uuid4().hex[:6]}", "attack", cls, txn, offer,
                Decision.BLOCK.value, reason)


def _make_legit(rng: random.Random, sk: str, pk: str) -> Case:
    """A within-policy transaction that SHOULD be allowed.

    Deliberately realistic and varied so a 0% false-block rate is a real signal,
    not an artifact: caps vary, mandates carry multiple allowed categories, the
    purchased category is any allowed one (not always footwear), and amounts span
    the whole in-cap range INCLUDING the boundary edges (cap, cap-100, cap-5000).
    """
    cap = rng.choice([300_000, 500_000, 700_000, 1_000_000])
    cats = tuple(sorted(set(
        rng.sample(list(_CATEGORIES), rng.randint(1, 3)))))
    category = rng.choice(cats)
    m = _mandate(sk, pk, cap=cap, cats=cats)
    amount = rng.choice([
        rng.randint(1_000, cap),                     # anywhere in range
        cap - 5_000, cap - 100, cap,                 # boundary edges (must still pass)
        rng.randint(max(1, cap - 20_000), cap),      # near-cap band
    ])
    amount = min(amount, cap)
    offer = _record(sku=f"SKU-{category[:4].upper()}", category=category, price=amount)
    txn = _txn(m, offer)
    return Case(f"leg-{uuid.uuid4().hex[:6]}", "legit", None, txn, offer,
                Decision.ALLOW.value, Reason.OK.value)


def generate_adversarial(rng: random.Random, sk: str, pk: str, per_class: int = 16) -> list[Case]:
    """`pk` is the trusted issuer key; every case is pinned to it (a forged mandate
    signed by any other key is rejected)."""
    trusted = frozenset({pk})
    cases: list[Case] = []
    for cls in ATTACK_CLASSES:
        for _ in range(per_class):
            c = _make_attack(cls, rng, sk, pk)
            cases.append(dataclasses.replace(c, trusted_issuer_keys=trusted))
    return cases


def generate_legitimate(rng: random.Random, sk: str, pk: str, n: int = 400) -> list[Case]:
    trusted = frozenset({pk})
    return [dataclasses.replace(_make_legit(rng, sk, pk), trusted_issuer_keys=trusted)
            for _ in range(n)]
