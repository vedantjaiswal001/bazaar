"""Merchant-as-signer: signed price attestations make price integrity two-sided."""
from __future__ import annotations

import dataclasses

from bazaar.catalog.attestation import (
    MerchantSigner,
    signed_offer,
    verify_price_attestation,
)
from bazaar.models import MerchantRecord

REC = MerchantRecord(
    sku="SKU-SHOE-01", merchant_id="merch-athleto", title="Trail Running Shoes",
    category="footwear", price=449_900, floor_price=400_000, return_policy_days=30,
)


def test_attest_then_verify_ok():
    m = MerchantSigner("merch-athleto")
    att = m.attest(REC)
    ok, reason = verify_price_attestation(att, {m.public_key})
    assert ok and reason == "OK"
    # the gate would authorise against the merchant-signed price
    off = signed_offer(REC, att)
    assert off.price == REC.price and off.category == REC.category


def test_price_tamper_breaks_the_signature():
    m = MerchantSigner("merch-athleto")
    att = m.attest(REC)
    tampered = dataclasses.replace(att, price=att.price - 100_000)  # edit after signing
    ok, reason = verify_price_attestation(tampered, {m.public_key})
    assert not ok and reason == "ATTESTATION_TAMPERED"


def test_untrusted_merchant_key_rejected():
    m = MerchantSigner("merch-athleto")
    att = m.attest(REC)
    ok, reason = verify_price_attestation(att, set())  # signer not trusted
    assert not ok and reason == "ATTESTATION_UNTRUSTED_MERCHANT"


def test_expired_attestation_rejected():
    m = MerchantSigner("merch-athleto")
    att = m.attest(REC, ttl_seconds=-10)  # already expired
    ok, reason = verify_price_attestation(att, {m.public_key})
    assert not ok and reason == "ATTESTATION_EXPIRED"
