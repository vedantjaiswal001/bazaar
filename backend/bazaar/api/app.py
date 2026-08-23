"""FastAPI backend for the six demo screens.

Every endpoint runs the REAL system — the same gate, receipts, audit log, and
benchmark used everywhere else. Nothing here is mocked. Razorpay settlement is
Phase 2 and is reported as pending until test keys are configured.

Screens -> endpoints:
  Intent        POST /api/intent            compile NL -> confirmable mandate draft
  Transaction   POST /api/purchase          sign + negotiate + authorize (happy path)
  Verifier      (checks returned in /purchase and /attack)
  Trust Receipt POST /api/receipt/verify    verify / tamper a receipt
  Red Team      POST /api/attack            fire one attack class live
  Benchmark     GET  /api/benchmark         the scoreboard (from the latest run)
"""
from __future__ import annotations

import dataclasses
import json
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from bazaar.agents.buyer import BuyerAgent
from bazaar.agents.negotiation import negotiate
from bazaar.agents.seller import SellerAgent
from bazaar.catalog.seed import seed_default_catalog
from bazaar.catalog.store import CatalogStore
from bazaar.config import REPO_ROOT
from bazaar.crypto.signing import generate_keypair
from bazaar.db import repository as repo
from bazaar.db.database import connect, init_db
from bazaar.ledger.audit_log import verify_chain
from bazaar.models import Mandate, PriceSource
from bazaar.receipt.trust_receipt import verify_receipt_json
from bazaar.verifier.service import AuthorizationService

app = FastAPI(title="BAZAAR API", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

_LOCK = threading.Lock()


class _State:
    def __init__(self) -> None:
        db_path = str(REPO_ROOT / "bazaar_api.db")
        init_db(db_path, drop=True)
        self.conn = connect(db_path, check_same_thread=False)
        seed_default_catalog(self.conn)
        self.store = CatalogStore(self.conn)
        self.seller = SellerAgent("merch-athleto", self.store.seller_view())
        sk, pk = generate_keypair()
        self.buyer = BuyerAgent("buyer-1", sk, pk)
        repo.register_agent(self.conn, "buyer-1", "Buyer One", "buyer")
        self.svc = AuthorizationService(self.conn)
        self.mandates: dict[str, Mandate] = {}
        self.last_nonce: str | None = None


_state: _State | None = None


def state() -> _State:
    global _state
    if _state is None:
        _state = _State()
    return _state


# ----------------------------- models -----------------------------
class IntentIn(BaseModel):
    text: str = "Buy running shoes under ₹5,000 with 30-day returns, automatically"


class PurchaseIn(BaseModel):
    intent_text: str = "Buy running shoes under ₹5,000 with 30-day returns, automatically"
    base_sku: str = "SKU-SHOE-01"
    upsell: bool = True


class AttackIn(BaseModel):
    attack_class: str
    mandate_id: str | None = None


class VerifyIn(BaseModel):
    receipt: dict[str, Any]


# ----------------------------- helpers -----------------------------
def _checks(result) -> list[dict]:
    return [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in result.checks]


def _rupees(paise: int) -> str:
    return f"₹{paise / 100:,.2f}"


# ----------------------------- endpoints -----------------------------
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "razorpay_settlement": "pending (Phase 2 — needs test keys)"}


@app.get("/api/catalog")
def catalog() -> dict:
    with _LOCK:
        items = state().store.list_active()
    return {"items": [dataclasses.asdict(i) for i in items]}


@app.post("/api/intent")
def intent(body: IntentIn) -> dict:
    with _LOCK:
        _, _, view = state().buyer.draft_mandate(body.text)
    return {
        "intent_text": view.intent_text,
        "max_amount": view.max_amount, "max_amount_display": _rupees(view.max_amount),
        "allowed_categories": list(view.allowed_categories),
        "return_policy_days": view.return_policy_days,
        "autonomous": view.autonomous, "expires_at": view.expires_at,
        "confirmable": view.is_confirmable(), "warnings": list(view.warnings),
    }


@app.post("/api/purchase")
def purchase(body: PurchaseIn) -> dict:
    with _LOCK:
        s = state()
        _, unsigned, view = s.buyer.draft_mandate(body.intent_text)
        if not view.is_confirmable():
            raise HTTPException(400, f"mandate not confirmable: {list(view.warnings)}")
        mandate = s.buyer.confirm_and_sign(unsigned)
        repo.save_mandate(s.conn, mandate)
        s.mandates[mandate.mandate_id] = mandate

        offer, outcome = negotiate(store=s.store, seller=s.seller,
                                   buyer_cap=mandate.max_amount, base_sku=body.base_sku,
                                   upsell=body.upsell)
        if offer is None:
            raise HTTPException(400, "no offer for that sku")
        txn = s.buyer.build_transaction(mandate, offer)
        s.last_nonce = txn.nonce
        out = s.svc.authorize(txn, offer)

    return {
        "mandate_id": mandate.mandate_id,
        "mandate": {"cap": mandate.max_amount, "cap_display": _rupees(mandate.max_amount),
                    "categories": list(mandate.allowed_categories),
                    "expires_at": mandate.expires_at,
                    "signature_valid": mandate.verify_signature()},
        "negotiation": {
            "sku": outcome.sku, "list_price": outcome.list_price,
            "floor_price": outcome.floor_price, "buyer_cap": outcome.buyer_cap,
            "agreed_price": outcome.agreed_price, "upsold": outcome.upsold,
            "within_walls": outcome.within_walls(),
            "transcript": [{"actor": s.actor, "price": s.price, "note": s.note}
                           for s in outcome.transcript],
        },
        "decision": out.result.decision, "reason": out.result.reason,
        "risk_score": out.risk.score, "effective_decision": out.effective_decision,
        "checks": _checks(out.result),
        "receipt": out.receipt.to_json(),
        "razorpay": {"status": "pending", "note": "Phase 2 — real test-mode settlement"},
    }


@app.post("/api/attack")
def attack(body: AttackIn) -> dict:
    with _LOCK:
        s = state()
        mandate = (s.mandates.get(body.mandate_id) if body.mandate_id
                   else next(iter(s.mandates.values()), None))
        if mandate is None:
            # Ensure a mandate exists (run a purchase first, or create one now).
            _, unsigned, view = s.buyer.draft_mandate(
                "shoes under ₹5,000, 30-day returns, auto")
            mandate = s.buyer.confirm_and_sign(unsigned)
            repo.save_mandate(s.conn, mandate)
            s.mandates[mandate.mandate_id] = mandate

        cls = body.attack_class
        offer = None
        txn = None
        if cls == "budget":
            offer = s.store.make_offer("SKU-SHOE-LUX")             # ₹7,000 > cap
            txn = s.buyer.build_transaction(mandate, offer)
        elif cls == "category":
            offer = s.store.make_offer("SKU-WATCH-9")              # off-mandate
            txn = s.buyer.build_transaction(mandate, offer)
        elif cls == "injection":
            offer = s.store.make_offer("SKU-SHOE-INJ")
            txn = s.buyer.build_transaction(mandate, offer)
            txn = dataclasses.replace(txn, price_source=PriceSource.DESCRIPTION)
        elif cls == "price":
            offer = s.store.make_offer("SKU-SHOE-01")
            txn = s.buyer.build_transaction(mandate, offer)
            txn = dataclasses.replace(txn, amount=offer.price - 50_000)  # false price
        elif cls == "policy":
            offer = s.store.make_offer("SKU-SHOE-01")
            tampered = dataclasses.replace(mandate, max_amount=mandate.max_amount * 2)
            txn = s.buyer.build_transaction(tampered, offer)
        elif cls == "expiry":
            # A VALIDLY SIGNED but expired mandate (so the signature passes and the
            # TTL check is what blocks it — otherwise we'd trip MANDATE_IMMUTABLE).
            import datetime as _dt

            from bazaar.models import to_rfc3339
            now = _dt.datetime.now(_dt.timezone.utc)
            unsigned_exp = dataclasses.replace(
                mandate, mandate_id=f"m-{uuid.uuid4().hex[:8]}", signature="",
                public_key="", canonical_body="",
                issued_at=to_rfc3339(now - _dt.timedelta(hours=1)),
                expires_at=to_rfc3339(now - _dt.timedelta(minutes=30)),
            )
            expired = s.buyer.confirm_and_sign(unsigned_exp)
            repo.save_mandate(s.conn, expired)                     # satisfy the txn FK
            offer = s.store.make_offer("SKU-SHOE-01")
            txn = s.buyer.build_transaction(expired, offer)
        elif cls == "state":
            offer = s.store.make_offer("SKU-SHOE-01")
            repo.set_agent_frozen(s.conn, "buyer-1", True)
            txn = s.buyer.build_transaction(mandate, offer)
        elif cls == "replay":
            offer = s.store.make_offer("SKU-SHOE-01")
            nonce = uuid.uuid4().hex                               # fresh, then reused
            first = s.buyer.build_transaction(mandate, offer, nonce=nonce)
            s.svc.authorize(first, offer)                          # ensure the nonce is used
            txn = s.buyer.build_transaction(mandate, offer, nonce=nonce)
        elif cls == "double_charge":
            offer = s.store.make_offer("SKU-SHOE-01")
            key = uuid.uuid4().hex
            first = s.buyer.build_transaction(mandate, offer, idempotency_key=key)
            s.svc.authorize(first, offer)                          # ensure the key is used
            txn = s.buyer.build_transaction(mandate, offer, idempotency_key=key)
        else:
            raise HTTPException(400, f"unknown attack class: {cls}")

        out = s.svc.authorize(txn, offer)
        if cls == "state":
            repo.set_agent_frozen(s.conn, "buyer-1", False)        # unfreeze for later demos

    return {
        "attack_class": cls, "decision": out.result.decision, "reason": out.result.reason,
        "detail": out.result.detail, "checks": _checks(out.result),
        "receipt": out.receipt.to_json(),
    }


@app.post("/api/receipt/verify")
def receipt_verify(body: VerifyIn) -> dict:
    return {"valid": verify_receipt_json(body.receipt)}


@app.get("/api/audit")
def audit() -> dict:
    with _LOCK:
        chain = verify_chain(state().conn)
    return {"length": chain.length, "ok": chain.ok,
            "broken_at_seq": chain.broken_at_seq, "detail": chain.detail}


@app.get("/api/benchmark")
def benchmark() -> dict:
    path = Path(REPO_ROOT) / "benchmarks" / "out" / "scoreboard.json"
    if not path.exists():
        return {"status": "not_run", "hint": "run `make benchmark` to generate the scoreboard"}
    return {"status": "ok", "scoreboard": json.loads(path.read_text(encoding="utf-8"))}
