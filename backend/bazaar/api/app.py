"""FastAPI backend for the six demo screens.

Every endpoint runs the REAL system - the same gate, receipts, audit log, and
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
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from bazaar.adapters.ap2 import AP2VerificationError, to_bazaar, verify_cart_mandate
from bazaar.agents.ap2_buyer import AP2ShoppingAgent, tamper_signature
from bazaar.agents.buyer import BuyerAgent
from bazaar.agents.issuer import Issuer
from bazaar.agents.negotiation import negotiate
from bazaar.agents.seller import SellerAgent
from bazaar.catalog.attestation import MerchantSigner, signed_offer, verify_price_attestation
from bazaar.catalog.seed import seed_default_catalog
from bazaar.catalog.store import CatalogStore
from bazaar.config import REPO_ROOT, settings
from bazaar.db import repository as repo
from bazaar.db.database import connect, init_db
from bazaar.ledger.audit_log import verify_chain
from bazaar.models import Mandate, PriceSource
from bazaar.razorpay.client import RazorpayClient, RazorpayNotConfigured
from bazaar.razorpay.settlement import settle
from bazaar.razorpay.webhooks import handle_event, verify_webhook_signature
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
        self.issuer = Issuer()                       # trusted human authority (signs mandates)
        self.buyer = BuyerAgent("buyer-1")           # proposes only; holds no signing key
        repo.register_agent(self.conn, "buyer-1", "Buyer One", "buyer")
        # --- AP2 rail: a trust bridge + a registered credential provider ---
        # The bridge is a pinned trusted issuer; it only mints a BAZAAR mandate
        # AFTER a Cart Mandate verifies. The demo credential provider's ES256 key
        # is registered by kid so the merchant can trust carts it signs.
        self.ap2_issuer = Issuer()
        self.ap2_agent = AP2ShoppingAgent(cp_id="cp-athleto-1")
        self.ap2_trusted_keys = {self.ap2_agent.kid: self.ap2_agent.public_pem}
        # --- merchant-as-signer: the merchant signs the price it will honour ---
        self.merchant_signer = MerchantSigner("merch-athleto")
        self.trusted_merchant_keys = {self.merchant_signer.public_key}
        # Pin the gate to BOTH issuer keys: a mandate signed by anything else is a forgery.
        self.svc = AuthorizationService(
            self.conn,
            trusted_issuer_keys={self.issuer.public_key, self.ap2_issuer.public_key},
        )
        self.mandates: dict[str, Mandate] = {}
        self.last_nonce: str | None = None
        self.last_txn_id: str | None = None


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


def _cart_view(cart) -> dict:
    return {
        "payee": cart.payee_id, "sku": cart.sku, "title": cart.title,
        "amount": cart.total_amount, "amount_display": _rupees(cart.total_amount),
        "currency": cart.currency, "budget": cart.max_amount,
        "budget_display": _rupees(cart.max_amount),
        "issuer_kid": cart.issuer_kid, "expires_at": cart.expires_at,
    }


def _run_ap2(s: _State, token: str) -> dict:
    """Verify a Cart Mandate, translate it, and run it through the SAME gate."""
    try:
        cart = verify_cart_mandate(token, s.ap2_trusted_keys)
    except AP2VerificationError as exc:
        # Authenticity failed - the request never reaches the money gate.
        return {"rail": "AP2", "verified": False, "stage": "mandate_verification",
                "decision": "BLOCK", "reason": exc.reason, "detail": exc.detail}
    record = s.store.get(cart.sku)
    # Merchant-as-signer: the merchant signs the price it will honour, and the
    # gate then authorises against that SIGNED price - a two-sided handshake with
    # the buyer's signed cart.
    integrity = {"buyer_signed": True, "merchant_signed": False}
    if record is not None:
        att = s.merchant_signer.attest(record)
        ok, att_reason = verify_price_attestation(att, s.trusted_merchant_keys)
        integrity = {
            "buyer_signed": True, "merchant_signed": ok,
            "attestation_id": att.attestation_id, "attested_price": att.price,
            "attested_price_display": _rupees(att.price), "reason": att_reason,
        }
        if ok:
            record = signed_offer(record, att)   # gate checks against the signed price
    try:
        mandate, txn = to_bazaar(cart, record, s.ap2_issuer)
    except AP2VerificationError as exc:
        return {"rail": "AP2", "verified": True, "stage": "mapping",
                "decision": "BLOCK", "reason": exc.reason, "detail": exc.detail,
                "cart": _cart_view(cart), "price_integrity": integrity}
    repo.register_agent(s.conn, txn.agent_id, f"AP2 Buyer {cart.subject}", "buyer")
    repo.save_mandate(s.conn, mandate)
    out = s.svc.authorize(txn, record)
    return {
        "rail": "AP2", "verified": True, "stage": "gate", "cart": _cart_view(cart),
        "txn_id": txn.txn_id, "decision": out.result.decision, "reason": out.result.reason,
        "detail": out.result.detail, "risk_score": out.risk.score,
        "effective_decision": out.effective_decision, "checks": _checks(out.result),
        "price_integrity": integrity,
        "dual_signed": integrity["merchant_signed"] and out.result.decision == "ALLOW",
        "receipt": out.receipt.to_json(),
        "razorpay": {"status": "pending", "note": "settle via POST /api/settle"},
    }


def _mint_demo_cart(s: _State, variant: str) -> str:
    """Sign a demo Cart Mandate: a legit one, or one crafted to be caught."""
    a = s.ap2_agent
    sku = "SKU-SHOE-01"
    rec = s.store.get(sku)
    price, mid, title = rec.price, rec.merchant_id, rec.title
    if variant == "legit":
        return a.sign_cart(sku=sku, title=title, unit_amount=price, merchant_id=mid, budget=500_000)
    if variant == "price_tamper":   # validly signed, but disagrees with the merchant of record
        return a.sign_cart(sku=sku, title=title, unit_amount=price - 50_000,
                           merchant_id=mid, budget=500_000)
    if variant == "over_budget":    # amount == real price, but above the signed cap
        return a.sign_cart(sku=sku, title=title, unit_amount=price, merchant_id=mid,
                           budget=price - 50_000)
    if variant == "expired":
        return a.sign_cart(sku=sku, title=title, unit_amount=price, merchant_id=mid,
                           budget=500_000, exp_override=int(time.time()) - 30)
    if variant == "signature_tamper":
        return tamper_signature(a.sign_cart(sku=sku, title=title, unit_amount=price,
                                            merchant_id=mid, budget=500_000))
    if variant == "untrusted_issuer":
        rogue = AP2ShoppingAgent(cp_id="cp-rogue-9")   # never registered with the merchant
        return rogue.sign_cart(sku=sku, title=title, unit_amount=price, merchant_id=mid,
                               budget=500_000)
    raise HTTPException(400, f"unknown AP2 demo variant: {variant}")


# ----------------------------- endpoints -----------------------------
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "razorpay_settlement": "pending (Phase 2 - needs test keys)"}


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
        mandate = s.issuer.confirm_and_sign(unsigned)
        repo.save_mandate(s.conn, mandate)
        s.mandates[mandate.mandate_id] = mandate

        offer, outcome = negotiate(store=s.store, seller=s.seller,
                                   buyer_cap=mandate.max_amount, base_sku=body.base_sku,
                                   upsell=body.upsell)
        if offer is None:
            raise HTTPException(400, "no offer for that sku")
        txn = s.buyer.build_transaction(mandate, offer)
        s.last_nonce = txn.nonce
        s.last_txn_id = txn.txn_id
        out = s.svc.authorize(txn, offer)

    return {
        "txn_id": txn.txn_id,
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
        "razorpay": {"status": "pending", "note": "Phase 2 - real test-mode settlement"},
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
            mandate = s.issuer.confirm_and_sign(unsigned)
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
            # Forged mandate: the agent mints its own mandate with a DOUBLED cap and
            # signs it with ITS OWN key. The signature is internally valid, but the
            # key is not the trusted issuer -> blocked (MANDATE_IMMUTABLE). This is
            # the stronger attack: it defeats naive "just verify the signature" gates.
            offer = s.store.make_offer("SKU-SHOE-01")
            attacker = Issuer()
            forged_unsigned = dataclasses.replace(
                mandate, mandate_id=f"m-{uuid.uuid4().hex[:8]}",
                max_amount=mandate.max_amount * 2, signature="", public_key="", canonical_body="")
            forged = attacker.confirm_and_sign(forged_unsigned)
            repo.save_mandate(s.conn, forged)                     # satisfy the txn FK
            txn = s.buyer.build_transaction(forged, offer)
        elif cls == "expiry":
            # A VALIDLY SIGNED but expired mandate (so the signature passes and the
            # TTL check is what blocks it - otherwise we'd trip MANDATE_IMMUTABLE).
            import datetime as _dt

            from bazaar.models import to_rfc3339
            now = _dt.datetime.now(_dt.timezone.utc)
            unsigned_exp = dataclasses.replace(
                mandate, mandate_id=f"m-{uuid.uuid4().hex[:8]}", signature="",
                public_key="", canonical_body="",
                issued_at=to_rfc3339(now - _dt.timedelta(hours=1)),
                expires_at=to_rfc3339(now - _dt.timedelta(minutes=30)),
            )
            expired = s.issuer.confirm_and_sign(unsigned_exp)
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


class AP2CheckoutIn(BaseModel):
    cart_mandate_jwt: str


class AP2DemoIn(BaseModel):
    variant: str = "legit"


@app.get("/api/ap2/info")
def ap2_info() -> dict:
    """Which credential providers this merchant trusts, and the demo variants."""
    with _LOCK:
        s = state()
        return {
            "rail": "AP2 (Agent Payments Protocol)", "alg": "ES256",
            "trusted_credential_providers": list(s.ap2_trusted_keys.keys()),
            "demo_variants": ["legit", "price_tamper", "over_budget", "expired",
                              "signature_tamper", "untrusted_issuer"],
        }


@app.post("/api/ap2/checkout")
def ap2_checkout(body: AP2CheckoutIn) -> dict:
    """A real AI buyer presents an ES256-signed Cart Mandate; we verify + settle it."""
    with _LOCK:
        return _run_ap2(state(), body.cart_mandate_jwt)


@app.post("/api/ap2/demo")
def ap2_demo(body: AP2DemoIn) -> dict:
    """Mint a demo Cart Mandate (legit or a tamper case) and run it end to end."""
    with _LOCK:
        s = state()
        token = _mint_demo_cart(s, body.variant)
        result = _run_ap2(s, token)
    result["variant"] = body.variant
    # A redacted preview so the UI can show a real signed token without leaking it.
    result["cart_mandate_preview"] = f"{token[:24]}...{token[-8:]}  (ES256 JWS, {len(token)} chars)"
    return result


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


class SettleIn(BaseModel):
    txn_id: str | None = None


@app.post("/api/settle")
def settle_txn(body: SettleIn) -> dict:
    """Create a Razorpay Test Mode order for an authorized transaction.

    Honest behavior with no keys: returns 'not_configured' rather than pretending.
    With test keys set (Phase 2), this creates a real order; status stays
    'pending_settlement' until a verified captured-payment webhook arrives.
    """
    with _LOCK:
        s = state()
        txn_id = body.txn_id or s.last_txn_id
        if not txn_id:
            raise HTTPException(400, "no transaction to settle - run a purchase first")
        try:
            result = settle(s.conn, txn_id, RazorpayClient())
        except RazorpayNotConfigured as exc:
            return {"status": "not_configured", "txn_id": txn_id, "detail": str(exc)}
    return {
        "status": result.status, "txn_id": result.txn_id, "order_id": result.order_id,
        "amount": result.amount, "detail": result.detail,
        "key_id": settings.razorpay_key_id,   # public key id only (never the secret)
    }


@app.post("/api/webhook/razorpay")
async def razorpay_webhook(request: Request) -> dict:
    """Verified Razorpay webhook endpoint. Signature is checked before any state change."""
    raw = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")
    secret = settings.razorpay_webhook_secret
    if not secret:
        raise HTTPException(503, "webhook secret not configured (RAZORPAY_WEBHOOK_SECRET)")
    if not verify_webhook_signature(raw, signature, secret):
        raise HTTPException(400, "invalid webhook signature")
    event = json.loads(raw.decode("utf-8"))
    with _LOCK:
        result = handle_event(state().conn, event)
    return {"action": result.action, "txn_id": result.txn_id, "detail": result.detail}


# --------------------------------------------------------------------------- #
# Single-URL deploy: serve the built console from THIS same service, so the
# whole app lives at one address. Active only when BAZAAR_WEB_DIST points at a
# built `dist/` (the Docker image sets it). In dev and tests the variable is
# unset, so the API is unchanged and the Vite dev server serves the UI.
# --------------------------------------------------------------------------- #
_WEB_DIST = os.environ.get("BAZAAR_WEB_DIST", "")
if _WEB_DIST and Path(_WEB_DIST).is_dir():
    _dist = Path(_WEB_DIST)
    app.mount("/assets", StaticFiles(directory=str(_dist / "assets")), name="assets")

    @app.get("/")
    def _spa_root() -> FileResponse:
        return FileResponse(str(_dist / "index.html"))

    @app.get("/{full_path:path}")
    def _spa_fallback(full_path: str) -> FileResponse:
        # Never shadow the API; everything else falls back to the single page.
        if full_path.startswith("api"):
            raise HTTPException(404, "not found")
        candidate = _dist / full_path
        if candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(_dist / "index.html"))
