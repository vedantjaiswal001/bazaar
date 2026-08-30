"""Trust Receipts verify when intact and fail when any field is tampered."""
from __future__ import annotations

import copy

from bazaar.crypto.signing import generate_keypair
from bazaar.receipt.trust_receipt import build_receipt, verify_receipt_json
from bazaar.verifier.gate import authorize
from tests.factory import make_keypair, make_record, make_signed_mandate, make_txn


def _decision_and_receipt():
    sk, vk = make_keypair()               # mandate signing key
    m = make_signed_mandate(signing_key=sk, public_key=vk)
    record = make_record()
    txn = make_txn(mandate=m)
    result = authorize(txn, record, nonce_seen=False, idempotency_seen=False, agent_frozen=False)
    auth_sk, auth_vk = generate_keypair()  # authority key that signs the receipt
    receipt = build_receipt(auth_sk, auth_vk, txn=txn, record=record, result=result)
    return result, receipt


def test_intact_receipt_verifies():
    result, receipt = _decision_and_receipt()
    assert result.decision == "ALLOW"
    assert receipt.verify()
    assert verify_receipt_json(receipt.to_json())


def test_tampering_amount_fails_verification():
    _, receipt = _decision_and_receipt()
    forged = copy.deepcopy(receipt.to_json())
    forged["body"]["amount"] = 999_999      # attacker inflates the amount
    assert not verify_receipt_json(forged)


def test_tampering_decision_fails_verification():
    _, receipt = _decision_and_receipt()
    forged = copy.deepcopy(receipt.to_json())
    forged["body"]["decision"] = "ALLOW" if receipt.body["decision"] != "ALLOW" else "BLOCK"
    forged["body"]["reason"] = "OK"
    assert not verify_receipt_json(forged)


def test_receipt_records_the_reason_code():
    sk, vk = make_keypair()
    m = make_signed_mandate(signing_key=sk, public_key=vk, max_amount=100)
    record = make_record(price=700_000)     # far above the tiny cap
    txn = make_txn(mandate=m, amount=700_000)
    result = authorize(txn, record, nonce_seen=False, idempotency_seen=False, agent_frozen=False)
    auth_sk, auth_vk = generate_keypair()
    receipt = build_receipt(auth_sk, auth_vk, txn=txn, record=record, result=result)
    assert receipt.body["decision"] == "BLOCK"
    assert receipt.body["reason"] == "MANDATE_LIMIT_EXCEEDED"
    assert receipt.verify()
