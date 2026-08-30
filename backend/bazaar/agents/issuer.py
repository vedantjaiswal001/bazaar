"""The Issuer - the trusted human/authority that confirms and SIGNS mandates.

This is the root of trust. Its Ed25519 signing key is what the verifier pins the
mandate to (see verifier/gate.py, trusted_issuer_keys). The buyer agent proposes a
mandate draft but NEVER holds this key, so a compromised agent cannot mint a valid
mandate of its own - the whole point of "the human authorizes, the agent proposes."
"""
from __future__ import annotations

from bazaar.crypto.signing import generate_keypair
from bazaar.models import Mandate, sign_mandate


class Issuer:
    def __init__(self, signing_key: str | None = None, public_key: str | None = None) -> None:
        if signing_key is None or public_key is None:
            signing_key, public_key = generate_keypair()
        self._sk = signing_key
        self.public_key = public_key

    def confirm_and_sign(self, unsigned: Mandate) -> Mandate:
        """The confirmation gate: only a confirmable, human-approved draft is signed.

        Signing happens ONLY here, with the issuer's key, so a bad parse can never
        become a signed, 'valid' boundary and an agent can never self-issue authority.
        """
        if unsigned.max_amount <= 0 or not unsigned.allowed_categories:
            raise ValueError("mandate draft is not confirmable (missing cap or category)")
        return sign_mandate(self._sk, self.public_key, unsigned)
