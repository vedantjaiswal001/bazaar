#!/usr/bin/env python3
"""BAZAAR end-to-end demo (no network needed).

Runs the full happy path:
    intent -> human confirmation -> sign -> bounded negotiation (inside two walls)
    -> deterministic verifier -> Trust Receipt -> hash-chained audit log

Then fires a few live attacks so you can see the machine-readable reason codes.
Razorpay test-mode settlement is Phase 2 and is clearly marked as pending here.
"""
from __future__ import annotations

import dataclasses
import tempfile
from pathlib import Path

from bazaar.agents.buyer import BuyerAgent
from bazaar.agents.issuer import Issuer
from bazaar.agents.negotiation import negotiate
from bazaar.agents.seller import SellerAgent
from bazaar.catalog.seed import seed_default_catalog
from bazaar.catalog.store import CatalogStore
from bazaar.db import repository as repo
from bazaar.db.database import connect, init_db
from bazaar.ledger.audit_log import verify_chain
from bazaar.models import PriceSource
from bazaar.verifier.service import AuthorizationService


def rupees(paise: int) -> str:
    return f"₹{paise / 100:,.2f}"


def hr(c: str = "-") -> None:
    print(c * 68)


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "demo.db")
        init_db(path, drop=True)
        conn = connect(path)

        # ---- setup ----
        seed_default_catalog(conn)
        store = CatalogStore(conn)
        seller = SellerAgent("merch-athleto", store.seller_view())
        issuer = Issuer()                            # trusted human authority (signs mandates)
        buyer = BuyerAgent("buyer-1")                # proposes only; holds no signing key
        repo.register_agent(conn, "buyer-1", "Buyer One", "buyer")
        svc = AuthorizationService(conn, trusted_issuer_keys={issuer.public_key})

        print("BAZAAR - end-to-end demo")
        hr("=")

        # ---- 1. intent -> confirmation -> sign ----
        intent = "Buy running shoes under ₹5,000 with 30-day returns, automatically"
        _, unsigned, view = buyer.draft_mandate(intent)
        print(f"1. INTENT: {intent!r}")
        print("   Compiled mandate (human confirms this BEFORE signing):")
        print(f"     cap={rupees(view.max_amount)}  categories={list(view.allowed_categories)}"
              f"  returns={view.return_policy_days}d  autonomous={view.autonomous}")
        print(f"     confirmable={view.is_confirmable()}  expires_at={view.expires_at}")
        mandate = issuer.confirm_and_sign(unsigned)
        repo.save_mandate(conn, mandate)
        print(f"   ✓ signed (Ed25519). signature verifies: {mandate.verify_signature()}")
        hr()

        # ---- 2. bounded negotiation inside two visible walls ----
        offer, outcome = negotiate(store=store, seller=seller, buyer_cap=mandate.max_amount,
                                   base_sku="SKU-SHOE-01", upsell=True)
        print("2. BOUNDED NEGOTIATION (one round, two hard walls):")
        for step in outcome.transcript:
            label = step.actor.upper()
            price = "" if step.price == 0 else f"  {rupees(step.price)}"
            print(f"     [{label:>16}]{price}   {step.note}")
        print(f"   ✓ agreed {rupees(outcome.agreed_price)} - within walls: {outcome.within_walls()}"
              f"  (upsold: {outcome.upsold})")
        hr()

        # ---- 3. verifier -> receipt ----
        txn = buyer.build_transaction(mandate, offer)
        out = svc.authorize(txn, offer)
        print("3. DETERMINISTIC VERIFIER:")
        for chk in out.result.checks:
            mark = "✓" if chk.passed else "✗"
            print(f"     {mark} {chk.name}")
        print(f"   DECISION: {out.result.decision} ({out.result.reason})   "
              f"risk_score={out.risk.score} -> effective {out.effective_decision}")
        print(f"   Trust Receipt {out.receipt.receipt_id} verifies: {out.receipt.verify()}")
        print("   [Razorpay test-mode settlement: PENDING - wired in Phase 2 with test keys]")
        hr()

        # ---- 4. a few live attacks -> reason codes ----
        print("4. LIVE ATTACKS (same gate, machine-readable reason codes):")
        # over-cap luxury boots
        lux = store.make_offer("SKU-SHOE-LUX")
        t = buyer.build_transaction(mandate, lux)
        r = svc.authorize(t, lux).result
        print(f"     budget    (₹7,000 vs ₹5,000 cap)  -> {r.decision} {r.reason}")
        # off-mandate smartwatch
        watch = store.make_offer("SKU-WATCH-9")
        t = buyer.build_transaction(mandate, watch)
        r = svc.authorize(t, watch).result
        print(f"     category  (smartwatch off-mandate) -> {r.decision} {r.reason}")
        # injection: money-field sourced from untrusted description
        inj = store.make_offer("SKU-SHOE-INJ")
        t = buyer.build_transaction(mandate, inj)
        # Simulate a FOOLED agent: it took the money-field from the untrusted text.
        t = dataclasses.replace(t, price_source=PriceSource.DESCRIPTION)
        r = svc.authorize(t, inj).result
        print(f"     injection (price from catalog text) -> {r.decision} {r.reason}")
        # replay: reuse the happy-path nonce
        t = buyer.build_transaction(mandate, offer, nonce=txn.nonce)
        r = svc.authorize(t, offer).result
        print(f"     replay    (reused nonce)            -> {r.decision} {r.reason}")
        hr()

        # ---- 5. audit chain ----
        chain = verify_chain(conn)
        print(f"5. AUDIT CHAIN: {chain.length} entries, intact={chain.ok}")
        hr("=")
        print("✓ demo complete - every decision above was produced by code, live.")
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
