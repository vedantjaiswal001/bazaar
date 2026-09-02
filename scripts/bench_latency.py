#!/usr/bin/env python3
"""Measure the REAL latency of one authorization decision through the frozen gate.

The gate is a pure function. Authorizing a payment is a fixed 11-check list plus
one Ed25519 signature verification, with zero network calls and zero model
inference. This script times the full `authorize(...)` call on the ALLOW path
(every check runs, including the signature verify and the issuer-key pin) and
reports real percentiles. It writes the result to docs/evidence/gate_latency.json.

    make latency            # 50,000 timed calls (after a warmup)
    python scripts/bench_latency.py 200000

Nothing here touches verifier/gate.py. It only calls it and times it. The point
this proves is one of orders of magnitude, not of a specific machine: a
deterministic gate authorizes in microseconds, where an LLM-as-judge would spend
hundreds of milliseconds to seconds on a network round-trip per decision.
"""
from __future__ import annotations

import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Make "bazaar" and "tests" importable when run as "python scripts/bench_latency.py".
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from bazaar.verifier.gate import authorize
from bazaar.verifier.reasons import Decision

from tests.factory import (
    make_keypair,
    make_record,
    make_signed_mandate,
    make_txn,
)

EVIDENCE = ROOT / "docs" / "evidence" / "gate_latency.json"


def _pctl(sorted_us: list[float], q: float) -> float:
    """Percentile from an ascending list, nearest-rank, clamped to valid indices."""
    if not sorted_us:
        return 0.0
    idx = round(q * (len(sorted_us) - 1))
    idx = max(0, min(idx, len(sorted_us) - 1))
    return sorted_us[idx]


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 50_000
    warmup = min(5_000, max(1_000, n // 10))

    # Build one valid ALLOW scenario. Issuer pinning is ON (production path):
    # the mandate's key must be a trusted issuer key, not the agent's own.
    sk, vk = make_keypair()
    mandate = make_signed_mandate(signing_key=sk, public_key=vk)
    record = make_record()
    issuer_keys = {vk}

    def one_call() -> str:
        # A fresh txn per call: unique nonce + idempotency key, exactly as a real
        # authorization would arrive. amount == record.price so the path is ALLOW.
        txn = make_txn(mandate=mandate, amount=record.price)
        res = authorize(
            txn,
            record,
            nonce_seen=False,
            idempotency_seen=False,
            agent_frozen=False,
            trusted_issuer_keys=issuer_keys,
        )
        return res.decision

    # Sanity: the path we are timing must actually be ALLOW, or the number is a lie.
    if one_call() != Decision.ALLOW.value:
        print("ABORT: the benchmark scenario did not ALLOW; refusing to report a "
              "latency for the wrong path.", file=sys.stderr)
        return 2

    # Warmup (fills caches, lets the allocator settle). Not measured.
    for _ in range(warmup):
        one_call()

    # Measured run. Time each call individually so we get a real distribution,
    # not just a mean.
    samples_us: list[float] = []
    samples_us_append = samples_us.append
    perf = time.perf_counter_ns
    t_wall0 = perf()
    for _ in range(n):
        t0 = perf()
        one_call()
        samples_us_append((perf() - t0) / 1_000.0)
    wall_s = (perf() - t_wall0) / 1_000_000_000.0

    samples_us.sort()
    mean_us = sum(samples_us) / len(samples_us)
    result = {
        "measured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "path": "ALLOW (all 11 checks + Ed25519 verify + issuer-key pin)",
        "iterations": n,
        "warmup_iterations": warmup,
        "mean_us": round(mean_us, 3),
        "p50_us": round(_pctl(samples_us, 0.50), 3),
        "p95_us": round(_pctl(samples_us, 0.95), 3),
        "p99_us": round(_pctl(samples_us, 0.99), 3),
        "p999_us": round(_pctl(samples_us, 0.999), 3),
        "min_us": round(samples_us[0], 3),
        "max_us": round(samples_us[-1], 3),
        "throughput_calls_per_sec": round(n / wall_s, 0) if wall_s > 0 else 0,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor() or "unknown",
            "note": "measured in the project sandbox/CI, not on Razorpay hardware; "
                    "the claim is one of orders of magnitude, reproduce with `make latency`",
        },
    }

    W = 66
    print("=" * W)
    print("  BAZAAR GATE LATENCY  (every number produced by this run)")
    print("=" * W)
    print(f"  path        : {result['path']}")
    print(f"  iterations  : {n:,} timed  (+{warmup:,} warmup, not counted)")
    print("-" * W)
    print(f"    mean   : {result['mean_us']:>9.3f} us")
    print(f"    p50    : {result['p50_us']:>9.3f} us")
    print(f"    p95    : {result['p95_us']:>9.3f} us")
    print(f"    p99    : {result['p99_us']:>9.3f} us")
    print(f"    p99.9  : {result['p999_us']:>9.3f} us")
    print(f"    min    : {result['min_us']:>9.3f} us")
    print(f"    max    : {result['max_us']:>9.3f} us")
    print("-" * W)
    print(f"  throughput  : {result['throughput_calls_per_sec']:>,.0f} authorizations / sec (single core)")
    print(f"  environment : Python {result['environment']['python']} | "
          f"{result['environment']['platform']}")
    print("=" * W)
    print("  For contrast, an LLM-as-judge decision is a network round-trip:")
    print("  hundreds of milliseconds to seconds each. This gate is 3 to 4 orders")
    print("  of magnitude faster AND returns the same reason code every time.")
    print("=" * W)

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"  wrote {EVIDENCE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
