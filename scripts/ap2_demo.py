#!/usr/bin/env python3
"""AP2 rail conformance demo - a real AI buyer, verified end to end.

Signs genuine ES256 Cart Mandates (a legit one + five tamper variants) and runs
each through the SAME deterministic gate. Prints an honest conformance summary:
legit carts clear, every tamper is caught at the right layer (AP2 authenticity
vs the money gate).

    python scripts/ap2_demo.py            # or: make ap2
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from bazaar.api.app import _mint_demo_cart, _run_ap2, state

VARIANTS = [
    ("legit", "a real signed cart at the merchant's price"),
    ("price_tamper", "validly signed, but price disagrees with the merchant of record"),
    ("over_budget", "amount == real price, but above the signed cap"),
    ("expired", "cart mandate past its exp"),
    ("signature_tamper", "one byte of the ES256 signature flipped"),
    ("untrusted_issuer", "signed by a credential provider we never registered"),
]


def main() -> int:
    s = state()
    W = 74
    print("=" * W)
    print("  AP2 RAIL CONFORMANCE  -  sellable to a real AI buyer, safely")
    print("=" * W)
    print(f"  merchant trusts credential providers: {list(s.ap2_trusted_keys)}")
    print("-" * W)

    legit_cleared = tampers_caught = tampers_total = 0
    for variant, note in VARIANTS:
        token = _mint_demo_cart(s, variant)
        out = _run_ap2(s, token)
        decision, reason, stage = out["decision"], out["reason"], out.get("stage", "-")
        layer = "AP2 authenticity" if not out.get("verified") else "money gate"
        if variant == "legit":
            legit_cleared += int(decision == "ALLOW")
            mark = "✓ ALLOW" if decision == "ALLOW" else f"✗ {decision}"
        else:
            tampers_total += 1
            tampers_caught += int(decision == "BLOCK")
            mark = f"✓ BLOCK {reason}" if decision == "BLOCK" else f"✗ {decision}"
        print(f"  {variant:17s} [{layer:16s}] {mark}")
        print(f"      {note}")
    print("-" * W)
    print(f"  legit cleared: {legit_cleared}/1     tampers caught: "
          f"{tampers_caught}/{tampers_total}")
    ok = legit_cleared == 1 and tampers_caught == tampers_total
    print("  RESULT:", "✓ conformant - real carts settle, every tamper is caught"
          if ok else "✗ see above")
    print("=" * W)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
