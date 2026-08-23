#!/usr/bin/env python3
"""BAZAAR - the showcase run (built for the demo video, drives the real backend).

One command tells the whole story, paced for a single-take screen recording:

  1. A legitimate purchase clears the gate  -> ALLOW + a signed Trust Receipt.
  2. Tamper one field of the receipt          -> signature INVALID (crypto is real).
  3. All nine attack classes                   -> nine BLOCKs, nine reason codes.
  4. The hash-chained audit log                -> intact, then tampered -> detected.
  5. The honest scoreboard, computed live      -> block rate, false-block rate,
                                                  fuzzer-style invariant, AOV uplift.

Every number below is produced by code in this run. Nothing is pre-written.

    python scripts/showcase.py            # plain
    python scripts/showcase.py --pace 0.8 # add pauses for recording
    python scripts/showcase.py --no-color # disable ANSI colors
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import random
import sys
import tempfile
import time
from pathlib import Path

from bazaar.agents.buyer import BuyerAgent
from bazaar.agents.issuer import Issuer
from bazaar.agents.negotiation import negotiate
from bazaar.agents.seller import SellerAgent
from bazaar.catalog.seed import seed_default_catalog
from bazaar.catalog.store import CatalogStore
from bazaar.crypto.signing import generate_keypair
from bazaar.db import repository as repo
from bazaar.db.database import connect, init_db
from bazaar.ledger.audit_log import verify_chain
from bazaar.redteam.attacks import (
    ATTACK_CLASSES,
    _make_attack,
    generate_adversarial,
    generate_legitimate,
)
from bazaar.redteam.harness import evaluate_cases, revenue_axis, security_metrics
from bazaar.verifier.gate import authorize
from bazaar.verifier.service import AuthorizationService

_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
_PACE = 0.0


def _c(text: str, code: str) -> str:
    if not _COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def green(t): return _c(t, "1;32")
def red(t): return _c(t, "1;31")
def cyan(t): return _c(t, "1;36")
def dim(t): return _c(t, "2")
def bold(t): return _c(t, "1")
def yellow(t): return _c(t, "1;33")


def rupees(paise: int) -> str:
    return f"₹{paise / 100:,.2f}"


def beat(title: str) -> None:
    time.sleep(_PACE)
    print()
    print(cyan("=" * 72))
    print(cyan(bold(title)))
    print(cyan("=" * 72))


def line(text: str = "") -> None:
    print(text)
    if _PACE:
        time.sleep(_PACE * 0.35)


def main() -> int:
    global _COLOR, _PACE
    ap = argparse.ArgumentParser(description="BAZAAR showcase run")
    ap.add_argument("--pace", type=float, default=0.0,
                    help="seconds to pause between beats (for recording)")
    ap.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    args = ap.parse_args()
    if args.no_color:
        _COLOR = False
    _PACE = max(0.0, args.pace)

    print()
    print(bold("  BAZAAR  ") + dim("- a deterministic authorization gate for AI-to-AI commerce"))
    print(dim("  LLMs propose. Policies constrain. A deterministic verifier authorizes."))
    print(dim("  Nothing probabilistic can widen authority. The agent cannot overspend."))

    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "showcase.db")
        init_db(path, drop=True)
        conn = connect(path)

        seed_default_catalog(conn)
        store = CatalogStore(conn)
        seller = SellerAgent("merch-athleto", store.seller_view())
        issuer = Issuer()
        buyer = BuyerAgent("buyer-1")
        repo.register_agent(conn, "buyer-1", "Buyer One", "buyer")
        svc = AuthorizationService(conn, trusted_issuer_keys={issuer.public_key})

        # ----------------------------------------------------------------- #
        beat("1  A legitimate purchase clears the gate")
        intent = "Buy running shoes under ₹5,000 with 30-day returns, automatically"
        _, unsigned, view = buyer.draft_mandate(intent)
        line(f"  intent   {dim(intent)}")
        line(f"  mandate  cap {bold(rupees(view.max_amount))}  "
             f"categories {list(view.allowed_categories)}  "
             f"returns {view.return_policy_days}d  autonomous {view.autonomous}")
        mandate = issuer.confirm_and_sign(unsigned)     # the human authority signs
        repo.save_mandate(conn, mandate)
        line(f"  signed   Ed25519 - signature verifies: {green(str(mandate.verify_signature()))}"
             f"  {dim('(signed by the issuer, not the agent)')}")

        offer, outcome = negotiate(store=store, seller=seller, buyer_cap=mandate.max_amount,
                                   base_sku="SKU-SHOE-01")
        line()
        line(f"  bounded negotiation, one round, two hard walls "
             f"{dim('(buyer cap and seller floor)')}:")
        for step in outcome.transcript:
            price = "" if step.price == 0 else f"  {rupees(step.price)}"
            line(f"     {dim('[' + step.actor + ']'):>28}{price}   {dim(step.note)}")
        line(f"  agreed   {bold(rupees(outcome.agreed_price))}  within walls: "
             f"{green(str(outcome.within_walls()))}")

        txn = buyer.build_transaction(mandate, offer)
        out = svc.authorize(txn, offer)
        line()
        line("  deterministic verifier:")
        for chk in out.result.checks:
            mark = green("PASS") if chk.passed else red("FAIL")
            line(f"     {mark}  {chk.name}")
        decision = out.result.decision
        d_str = green(decision) if decision == "ALLOW" else red(decision)
        line(f"  decision {bold(d_str)} ({out.result.reason})   "
             f"risk={out.risk.score} -> effective {out.effective_decision}")
        line(f"  receipt  {out.receipt.receipt_id}  "
             f"signature valid: {green(str(out.receipt.verify()))}")

        # A few more real authorizations so the audit chain has visible depth.
        for _ in range(3):
            o2, _ = negotiate(store=store, seller=seller, buyer_cap=mandate.max_amount,
                              base_sku="SKU-SHOE-01")
            svc.authorize(buyer.build_transaction(mandate, o2), o2)

        # ----------------------------------------------------------------- #
        beat("2  Tamper one field of the receipt - the signature breaks")
        receipt = out.receipt
        line(f"  original amount {bold(rupees(receipt.body['amount']))}  "
             f"verifies: {green(str(receipt.verify()))}")
        tampered = dataclasses.replace(
            receipt, body={**receipt.body, "amount": 9_999_900})   # ₹99,999
        line(f"  tamper -> amount {bold(rupees(9_999_900))}  "
             f"verifies: {red(str(tampered.verify()))}   "
             f"{dim('the cryptography is real, not decorative')}")

        # ----------------------------------------------------------------- #
        beat("3  Nine attack classes, nine machine-readable reason codes")
        rng = random.Random(20260823)
        sk, pk = generate_keypair()                     # a trusted issuer keypair
        trusted = frozenset({pk})
        allblock = True
        for cls in ATTACK_CLASSES:
            case = _make_attack(cls, rng, sk, pk)
            gr = authorize(case.txn, case.offer, nonce_seen=case.nonce_seen,
                           idempotency_seen=case.idem_seen, agent_frozen=case.agent_frozen,
                           trusted_issuer_keys=trusted)
            ok = gr.decision == "BLOCK" and gr.reason == case.expected_reason
            allblock = allblock and ok
            tag = red("BLOCK") if gr.decision == "BLOCK" else green(gr.decision)
            line(f"     {dim(cls):>26}   {tag}  {yellow(gr.reason)}")
        line()
        line(f"  all nine blocked with the correct reason code: "
             f"{green(str(allblock)) if allblock else red(str(allblock))}")

        # ----------------------------------------------------------------- #
        beat("4  The audit log is hash-chained - tampering is detectable")
        chain = verify_chain(conn)
        entry_word = "entry" if chain.length == 1 else "entries"
        line(f"  {chain.length} {entry_word}, chain intact: {green(str(chain.ok))}")
        # Tamper a past payload directly in the DB, then re-verify.
        conn.execute("UPDATE audit_logs SET payload = ? WHERE seq = "
                     "(SELECT MIN(seq) FROM audit_logs)",
                     ('{"tampered":true}',))
        conn.commit()
        broken = verify_chain(conn)
        line(f"  after editing one past entry: intact {red(str(broken.ok))}  "
             f"-> first break at seq {broken.broken_at_seq}  {dim('(' + broken.detail + ')')}")

        conn.close()

    # --------------------------------------------------------------------- #
    beat("5  The honest scoreboard - computed live, nothing pre-written")
    line(dim("  (generating fresh adversarial + legitimate sets and running the gate...)"))
    rng = random.Random(7)
    sk, pk = generate_keypair()
    adversarial = generate_adversarial(rng, sk, pk, per_class=16)
    legit = generate_legitimate(rng, sk, pk, n=400)
    results = evaluate_cases(adversarial + legit)
    m = security_metrics(results)
    rev = revenue_axis(n_buyers=200, seed=7)

    def pct(x: float) -> str:
        return f"{x * 100:.1f}%"

    line(f"  adversarial blocked      {green(pct(m.overall_block_rate))}   "
         f"{dim(f'({m.attack_total} attacks, correct reason code {pct(m.overall_correct_code_rate)})')}")
    line(f"  false-block on legit     {green(pct(m.false_block_rate))}   "
         f"{dim(f'({m.legit_total} legitimate orders, incl. boundary cases)')}")
    escapes = red(str(len(m.escapes))) if m.escapes else green("0")
    line(f"  escapes (honestly counted) {escapes}")
    line(f"  AOV uplift from bounded upsell  {green('+' + str(rev.aov_uplift_pct) + '%')}   "
         f"{dim(f'share still cleared by the gate {pct(rev.share_of_uplift_cleared)}')}")
    line(dim("  (the risk classifier's precision/recall is reported separately by "
             "`make benchmark` -"))
    line(dim("   a probabilistic model never shares a scoreboard with gate correctness.)"))

    print()
    print(cyan("=" * 72))
    print("  " + bold("Autonomous commerce is not trustworthy because we say it is safe."))
    print("  " + bold("It is trustworthy because we can measure where it fails.  That is BAZAAR."))
    print(cyan("=" * 72))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
