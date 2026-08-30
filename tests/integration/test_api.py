"""The API runs the real system end-to-end for the six screens."""
from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from bazaar.api.app import app

EXPECTED = {
    "budget": "MANDATE_LIMIT_EXCEEDED",
    "policy": "MANDATE_IMMUTABLE",
    "price": "PRICE_MISMATCH_MERCHANT_RECORD",
    "replay": "NONCE_REPLAY",
    "double_charge": "DUPLICATE_TRANSACTION",
    "category": "CATEGORY_OUTSIDE_MANDATE",
    "injection": "UNTRUSTED_INSTRUCTION",
    "state": "AGENT_FROZEN",
    "expiry": "MANDATE_EXPIRED",
}


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_catalog_lists_items(client):
    skus = {i["sku"] for i in client.get("/api/catalog").json()["items"]}
    assert {"SKU-SHOE-01", "SKU-SHOE-PRO", "SKU-WATCH-9"} <= skus


def test_intent_is_confirmable(client):
    body = client.post("/api/intent", json={"text": "shoes under ₹5,000, 30-day returns, auto"})
    data = body.json()
    assert data["confirmable"] is True
    assert data["max_amount"] == 500_000
    assert data["allowed_categories"] == ["footwear"]


def test_purchase_happy_path(client):
    r = client.post("/api/purchase", json={"upsell": True}).json()
    assert r["decision"] == "ALLOW"
    assert r["negotiation"]["within_walls"] is True
    assert all(c["passed"] for c in r["checks"])
    # Receipt verifies through the API.
    assert client.post("/api/receipt/verify", json={"receipt": r["receipt"]}).json()["valid"]


def test_receipt_tamper_fails(client):
    r = client.post("/api/purchase", json={}).json()
    forged = copy.deepcopy(r["receipt"])
    forged["body"]["amount"] = 999_999
    assert client.post("/api/receipt/verify", json={"receipt": forged}).json()["valid"] is False


@pytest.mark.parametrize("cls,reason", list(EXPECTED.items()))
def test_each_attack_class_blocks_with_reason(client, cls, reason):
    # Ensure a mandate exists.
    client.post("/api/purchase", json={})
    out = client.post("/api/attack", json={"attack_class": cls}).json()
    assert out["decision"] == "BLOCK"
    assert out["reason"] == reason


def test_audit_chain_intact(client):
    client.post("/api/purchase", json={})
    a = client.get("/api/audit").json()
    assert a["ok"] is True and a["length"] > 0
