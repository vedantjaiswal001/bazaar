"""Property fuzzer for the spend-cap invariant, as a runnable command.

    python -m bazaar.redteam.fuzz_cli [iterations] [seed]

Throws N randomized states at the pure gate and reports the ACTUAL number of
states where the gate authorized an amount greater than the signed cap. That
number is produced by running - never written before the run. Zero is the
expected result; a non-zero result is a real finding and is printed as one.
"""
from __future__ import annotations

import random
import sys
import uuid
from dataclasses import dataclass, field
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
from bazaar.verifier.gate import authorize
from bazaar.verifier.reasons import Decision

_CATEGORIES = ["footwear", "apparel", "wearables", "electronics", "grocery"]


@dataclass
class FuzzReport:
    iterations: int
    seed: int
    allows: int = 0
    blocks: int = 0
    reviews: int = 0
    cap_violations: int = 0                       # ALLOW with amount > signed cap
    price_violations: int = 0                     # ALLOW with amount != record price
    violation_examples: list[dict] = field(default_factory=list)
    reason_counts: dict[str, int] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return self.cap_violations == 0 and self.price_violations == 0


def run_fuzz(iterations: int = 20_000, seed: int | None = None) -> FuzzReport:
    seed = random.randrange(2**31) if seed is None else seed
    rng = random.Random(seed)
    sk, vk = generate_keypair()
    report = FuzzReport(iterations=iterations, seed=seed)

    for _ in range(iterations):
        cap = rng.randint(1, 10_000_000)
        # Half the states are "coherent" - engineered so the ALLOW path is
        # actually reachable and the CAP BOUNDARY is exercised (price straddles
        # the cap, amount tracks price). The other half is adversarial noise.
        # Without this, independent amount/price would block on price every time
        # and the invariant would be tested with zero ALLOWs - vacuously true.
        coherent = rng.random() < 0.5
        if coherent:
            price = rng.randint(0, int(cap * 1.3) + 1)   # straddles the cap
            amount = price                                # agent quotes the record price
            category = rng.choice(_CATEGORIES)
            allowed = tuple(set(rng.sample(_CATEGORIES, rng.randint(1, len(_CATEGORIES))) + [category]))
            price_source = PriceSource.MERCHANT_RECORD
            ttl = rng.randint(60, 900)
        else:
            price = rng.randint(0, 10_000_000)
            amount = rng.randint(0, 10_000_000)
            category = rng.choice(_CATEGORIES)
            allowed = tuple(rng.sample(_CATEGORIES, rng.randint(1, len(_CATEGORIES))))
            price_source = rng.choice(list(PriceSource))
            ttl = rng.randint(-500, 900)
        issued = now_utc() + timedelta(seconds=(0 if ttl > 0 else -1000))
        expires = issued + timedelta(seconds=max(ttl, 1))

        draft = Mandate(
            mandate_id=f"m-{uuid.uuid4().hex[:8]}",
            agent_id="buyer-1",
            max_amount=cap,
            allowed_categories=allowed,
            return_policy_days=30,
            issued_at=to_rfc3339(issued),
            expires_at=to_rfc3339(expires),
        )
        mandate = sign_mandate(sk, vk, draft)
        record = MerchantRecord(
            sku="SKU-X", merchant_id="m", title="x", category=category,
            price=price, active=rng.random() > 0.05,
        )
        txn = TransactionRequest(
            txn_id="t", mandate=mandate, agent_id="buyer-1", sku="SKU-X",
            category=category, amount=amount, price_source=price_source,
            nonce=uuid.uuid4().hex, idempotency_key=uuid.uuid4().hex,
        )
        result = authorize(
            txn, record,
            nonce_seen=rng.random() < 0.1,
            idempotency_seen=rng.random() < 0.1,
            agent_frozen=rng.random() < 0.1,
        )
        report.reason_counts[result.reason] = report.reason_counts.get(result.reason, 0) + 1

        if result.decision == Decision.ALLOW.value:
            report.allows += 1
            if amount > cap:
                report.cap_violations += 1
                if len(report.violation_examples) < 5:
                    report.violation_examples.append(
                        {"type": "cap", "amount": amount, "cap": cap})
            if amount != price:
                report.price_violations += 1
        elif result.decision == Decision.REVIEW.value:
            report.reviews += 1
        else:
            report.blocks += 1

    return report


def main(argv: list[str]) -> int:
    iterations = int(argv[1]) if len(argv) > 1 else 20_000
    seed = int(argv[2]) if len(argv) > 2 else None
    r = run_fuzz(iterations, seed)
    print("=" * 60)
    print("  SPEND-CAP FUZZER  (invariant #3: ALLOW => amount <= signed cap)")
    print("=" * 60)
    print(f"  iterations              : {r.iterations:,}")
    print(f"  seed (reproducible)     : {r.seed}")
    print(f"  ALLOW / REVIEW / BLOCK  : {r.allows:,} / {r.reviews:,} / {r.blocks:,}")
    print(f"  spend-cap violations    : {r.cap_violations}   <-- actual count, not pre-written")
    print(f"  price-mismatch escapes  : {r.price_violations}")
    if r.clean:
        print("  RESULT                  : ✓ no invariant violation found")
    else:
        print("  RESULT                  : ✗ VIOLATIONS FOUND (kept and reported honestly):")
        for ex in r.violation_examples:
            print(f"      {ex}")
    print("-" * 60)
    print("  reason-code distribution:")
    for reason, count in sorted(r.reason_counts.items(), key=lambda kv: -kv[1]):
        print(f"      {reason:34s} {count:,}")
    print("=" * 60)
    return 0 if r.clean else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
