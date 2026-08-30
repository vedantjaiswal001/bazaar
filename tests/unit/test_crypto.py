"""Crypto is real, not decorative: valid signatures verify, tampering fails."""
from __future__ import annotations

from bazaar.crypto.jcs import canonicalize
from bazaar.crypto.signing import (
    generate_keypair,
    sign_object,
    verify_key_for,
    verify_object,
)


def test_jcs_is_stable_across_key_order():
    a = canonicalize({"b": 2, "a": 1, "amount": 500000})
    b = canonicalize({"amount": 500000, "a": 1, "b": 2})
    assert a == b == b'{"a":1,"amount":500000,"b":2}'


def test_sign_and_verify_round_trip():
    sk, vk = generate_keypair()
    assert verify_key_for(sk) == vk
    obj = {"mandate_id": "m1", "max_amount": 500000, "cats": ["footwear"]}
    body, sig = sign_object(sk, obj)
    assert verify_object(vk, obj, sig)


def test_tampering_any_field_fails_verification():
    sk, vk = generate_keypair()
    obj = {"mandate_id": "m1", "max_amount": 500000}
    _, sig = sign_object(sk, obj)
    tampered = {"mandate_id": "m1", "max_amount": 700000}  # raised the cap
    assert not verify_object(vk, tampered, sig)


def test_wrong_key_fails_verification():
    sk, _ = generate_keypair()
    _, other_vk = generate_keypair()
    obj = {"x": 1}
    _, sig = sign_object(sk, obj)
    assert not verify_object(other_vk, obj, sig)
