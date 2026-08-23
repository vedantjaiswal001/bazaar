#!/usr/bin/env python3
"""BAZAAR benchmark — one command regenerates the sets, runs the gate + fuzzer,
and prints the scoreboard. Every number is produced by this run. Escapes, if any,
are printed honestly and cause a non-zero exit.

    python benchmarks/runner.py            # or: make benchmark
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow "python benchmarks/runner.py" without installing benchmarks as a package.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bazaar.redteam.fuzz_cli import run_fuzz
from bazaar.redteam.harness import (
    evaluate_cases,
    revenue_axis,
    risk_classifier_metrics,
    security_metrics,
)
from datasets import build

OUT_DIR = Path(__file__).resolve().parent / "out"


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def rupees(paise: int) -> str:
    return f"₹{paise / 100:,.2f}"


def main() -> int:
    fuzz_iters = int(sys.argv[1]) if len(sys.argv) > 1 else 20_000

    data = build()
    dev = evaluate_cases(data.dev)
    held = evaluate_cases(data.held_out)

    sec = security_metrics(dev)
    sec_ho = security_metrics(held)
    risk = risk_classifier_metrics(dev)
    rev = revenue_axis()
    fuzz = run_fuzz(fuzz_iters)

    W = 66
    print("=" * W)
    print("  BAZAAR BENCHMARK SCOREBOARD  (every number produced by this run)")
    print("=" * W)
    print(f"  dataset: {sec.attack_total} adversarial + {sec.legit_total} legitimate"
          f"  |  held-out: {sec_ho.attack_total} + {sec_ho.legit_total}")
    print("-" * W)
    print("  THE FOUR NUMBERS THAT MATTER")
    print(f"    1. adversarial block rate (overall) : {pct(sec.overall_block_rate)}"
          f"   correct-code: {pct(sec.overall_correct_code_rate)}")
    print(f"    2. false-block rate on legit traffic : {pct(sec.false_block_rate)}")
    print(f"    3. held-out block rate (fresh/unseen): {pct(sec_ho.overall_block_rate)}"
          f"   false-block: {pct(sec_ho.false_block_rate)}")
    print(f"    4. fuzzer spend-cap violations       : {fuzz.cap_violations}"
          f"   (over {fuzz.iterations:,} states, seed {fuzz.seed})")
    print("-" * W)
    print("  SECURITY CORRECTNESS — per attack class (blocked / correct reason code)")
    for cls in sorted(sec.per_class_blocked):
        b = sec.per_class_blocked[cls]
        c = sec.per_class_correct_code[cls]
        print(f"    {cls:14s} blocked {pct(b):>6}   correct-code {pct(c):>6}"
              f"   -> {'OK' if c == 1.0 else 'CHECK'}")
    if sec.escapes:
        print("    ESCAPES (kept and reported honestly):")
        for e in sec.escapes[:10]:
            print(f"      {e}")
    else:
        print("    escapes: none")
    print("-" * W)
    print("  USABILITY / ECONOMIC VALUE")
    print(f"    false-block rate at the edges        : {pct(sec.false_block_rate)}")
    print(f"    AOV baseline (upsell OFF)            : {rupees(rev.mean_aov_baseline)}")
    print(f"    AOV with bounded upsell (ON)         : {rupees(rev.mean_aov_upsell)}")
    print(f"    AOV uplift                           : {rev.aov_uplift_pct:.2f}%")
    print(f"    share of upsold orders clearing gate : {pct(rev.share_of_uplift_cleared)}")
    print("-" * W)
    print("  BEHAVIORAL CLASSIFIER — advisory risk model ONLY (kept separate)")
    print(f"    precision {risk.precision:.3f}  recall {risk.recall:.3f}  F1 {risk.f1:.3f}"
          f"   (tp={risk.tp} fp={risk.fp} fn={risk.fn} tn={risk.tn})")
    print("    (the deterministic gate has no 'accuracy'; only this classifier does)")
    print("=" * W)

    clean = (not sec.escapes) and fuzz.clean and sec.false_block_rate == 0.0
    print("  RESULT:", "✓ all attacks blocked, zero false blocks, zero fuzzer violations"
          if clean else "✗ see escapes / violations above (reported honestly)")
    print("=" * W)

    OUT_DIR.mkdir(exist_ok=True)
    scoreboard = {
        "dataset": {"adversarial": sec.attack_total, "legit": sec.legit_total,
                    "held_out_adversarial": sec_ho.attack_total,
                    "held_out_legit": sec_ho.legit_total},
        "four_numbers": {
            "adversarial_block_rate": sec.overall_block_rate,
            "adversarial_correct_code_rate": sec.overall_correct_code_rate,
            "false_block_rate": sec.false_block_rate,
            "held_out_block_rate": sec_ho.overall_block_rate,
            "held_out_false_block_rate": sec_ho.false_block_rate,
            "fuzzer_cap_violations": fuzz.cap_violations,
            "fuzzer_iterations": fuzz.iterations,
            "fuzzer_seed": fuzz.seed,
        },
        "per_class_blocked": sec.per_class_blocked,
        "per_class_correct_code": sec.per_class_correct_code,
        "escapes": sec.escapes,
        "revenue_axis": {
            "aov_baseline_paise": rev.mean_aov_baseline,
            "aov_upsell_paise": rev.mean_aov_upsell,
            "aov_uplift_pct": rev.aov_uplift_pct,
            "share_of_uplift_cleared": rev.share_of_uplift_cleared,
        },
        "risk_classifier": {"precision": risk.precision, "recall": risk.recall, "f1": risk.f1},
    }
    (OUT_DIR / "scoreboard.json").write_text(json.dumps(scoreboard, indent=2), encoding="utf-8")
    print(f"  wrote {OUT_DIR / 'scoreboard.json'}")
    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
