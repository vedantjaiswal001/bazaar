"""Property: no nonce is ever authorized twice; no idempotency key settles twice.

Models the stateful defense: a stream of otherwise-valid transactions, some
deliberately reusing nonces / idempotency keys from a small pool so collisions
occur. Processed in order while maintaining the "seen" sets exactly as the
DB-backed service would, the gate must authorize each nonce at most once.
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from bazaar.crypto.signing import generate_keypair
from bazaar.verifier.gate import authorize
from bazaar.verifier.reasons import Decision
from tests.factory import make_record, make_signed_mandate, make_txn

_SK, _VK = generate_keypair()

# Small pools so reuse is frequent.
_nonce_pool = st.sampled_from([f"nonce-{i}" for i in range(5)])
_idem_pool = st.sampled_from([f"idem-{i}" for i in range(5)])
_stream = st.lists(st.tuples(_nonce_pool, _idem_pool), min_size=1, max_size=40)


@settings(max_examples=500, deadline=None)
@given(_stream)
def test_nonce_and_idempotency_authorized_at_most_once(stream):
    mandate = make_signed_mandate(signing_key=_SK, public_key=_VK)
    record = make_record()  # a valid, in-allowlist, in-cap purchase

    used_nonces: set[str] = set()
    used_idem: set[str] = set()
    authorized_nonces: list[str] = []
    authorized_idem: list[str] = []

    for nonce, idem in stream:
        txn = make_txn(mandate=mandate, nonce=nonce, idempotency_key=idem)
        result = authorize(
            txn, record,
            nonce_seen=(nonce in used_nonces),
            idempotency_seen=(idem in used_idem),
            agent_frozen=False,
        )
        if result.decision == Decision.ALLOW.value:
            # Commit exactly what the service would commit on an ALLOW.
            used_nonces.add(nonce)
            used_idem.add(idem)
            authorized_nonces.append(nonce)
            authorized_idem.append(idem)

    assert len(authorized_nonces) == len(set(authorized_nonces))
    assert len(authorized_idem) == len(set(authorized_idem))
