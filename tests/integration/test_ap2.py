"""AP2 rail: a real ES256-signed Cart Mandate is verified and settled through the
SAME deterministic gate - and every tamper case is caught, at the right layer."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from bazaar.adapters.ap2 import AP2VerificationError, verify_cart_mandate
from bazaar.agents.ap2_buyer import AP2ShoppingAgent
from bazaar.api.app import app, state


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_ap2_info_lists_trusted_provider(client):
    info = client.get("/api/ap2/info").json()
    assert info["alg"] == "ES256"
    assert "cp-athleto-1" in info["trusted_credential_providers"]


def test_ap2_legit_cart_clears_the_untouched_gate(client):
    out = client.post("/api/ap2/demo", json={"variant": "legit"}).json()
    assert out["verified"] is True
    assert out["stage"] == "gate"
    assert out["decision"] == "ALLOW"
    assert all(c["passed"] for c in out["checks"])          # all 11 gate checks pass
    assert out["cart"]["issuer_kid"] == "cp-athleto-1"
    # two-sided price integrity: buyer's cart signed AND merchant's price signed
    assert out["dual_signed"] is True
    assert out["price_integrity"]["buyer_signed"] is True
    assert out["price_integrity"]["merchant_signed"] is True
    # the receipt issued for the AP2 purchase verifies
    assert client.post("/api/receipt/verify", json={"receipt": out["receipt"]}).json()["valid"]


# variant -> (verified-through-AP2?, expected reason code)
TAMPER_CASES = {
    "price_tamper": (True, "PRICE_MISMATCH_MERCHANT_RECORD"),  # signed, but disagrees w/ record -> GATE
    "over_budget": (True, "MANDATE_LIMIT_EXCEEDED"),           # signed, above cap -> GATE
    "expired": (False, "AP2_EXPIRED"),                        # never reaches the gate
    "signature_tamper": (False, "AP2_INVALID_SIGNATURE"),
    "untrusted_issuer": (False, "AP2_UNTRUSTED_ISSUER"),
}


@pytest.mark.parametrize("variant,expected", list(TAMPER_CASES.items()))
def test_ap2_tamper_cases_are_caught(client, variant, expected):
    verified, reason = expected
    out = client.post("/api/ap2/demo", json={"variant": variant}).json()
    assert out["decision"] == "BLOCK"
    assert out["reason"] == reason
    assert out["verified"] is verified


def test_ap2_checkout_accepts_an_externally_signed_token(client):
    """Sign a Cart Mandate with the merchant's registered provider and POST it."""
    s = state()
    rec = s.store.get("SKU-SHOE-01")
    token = s.ap2_agent.sign_cart(
        sku=rec.sku, title=rec.title, unit_amount=rec.price,
        merchant_id=rec.merchant_id, budget=500_000,
    )
    out = client.post("/api/ap2/checkout", json={"cart_mandate_jwt": token}).json()
    assert out["verified"] is True
    assert out["decision"] == "ALLOW"
    assert out["cart"]["amount"] == rec.price


# ------------------------- pure verification unit tests -------------------------
def _agent_and_keys():
    a = AP2ShoppingAgent(cp_id="cp-test-1")
    return a, {a.kid: a.public_pem}


def test_verify_rejects_untrusted_issuer():
    a, _ = _agent_and_keys()
    token = a.sign_cart(sku="X", title="x", unit_amount=100, merchant_id="m", budget=1000)
    with pytest.raises(AP2VerificationError) as e:
        verify_cart_mandate(token, {})   # no trusted keys registered
    assert e.value.code == "untrusted_issuer"


def test_verify_rejects_cart_total_mismatch():
    a, keys = _agent_and_keys()
    token = a.sign_cart(sku="X", title="x", unit_amount=100, quantity=2,
                        merchant_id="m", budget=1000, total_override=150)  # 150 != 100x2
    with pytest.raises(AP2VerificationError) as e:
        verify_cart_mandate(token, keys)
    assert e.value.code == "cart_total_mismatch"


def test_verify_rejects_payee_not_allowed():
    a, keys = _agent_and_keys()
    token = a.sign_cart(sku="X", title="x", unit_amount=100, merchant_id="m-evil",
                        budget=1000, allowed_payees=["m-good"])
    with pytest.raises(AP2VerificationError) as e:
        verify_cart_mandate(token, keys)
    assert e.value.code == "payee_not_allowed"


def test_verify_rejects_expired():
    a, keys = _agent_and_keys()
    token = a.sign_cart(sku="X", title="x", unit_amount=100, merchant_id="m",
                        budget=1000, exp_override=int(time.time()) - 5)
    with pytest.raises(AP2VerificationError) as e:
        verify_cart_mandate(token, keys)
    assert e.value.code == "expired"
