"""Ed25519 signing over canonical JSON.

We never implement cryptography ourselves. This is a thin, auditable wrapper over
PyNaCl (libsodium). Keys and signatures cross module boundaries as base64 strings
so they store cleanly in SQLite and render in the UI.
"""
from __future__ import annotations

import base64
from typing import Any

import nacl.exceptions
import nacl.signing

from bazaar.crypto.jcs import canonicalize


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def generate_keypair() -> tuple[str, str]:
    """Return (signing_key_b64, verify_key_b64). The signing key is secret."""
    sk = nacl.signing.SigningKey.generate()
    return _b64e(bytes(sk)), _b64e(bytes(sk.verify_key))


def verify_key_for(signing_key_b64: str) -> str:
    """Derive the public verify key (b64) from a signing key (b64)."""
    sk = nacl.signing.SigningKey(_b64d(signing_key_b64))
    return _b64e(bytes(sk.verify_key))


def sign_bytes(signing_key_b64: str, message: bytes) -> str:
    """Sign raw bytes; return the detached signature as base64."""
    sk = nacl.signing.SigningKey(_b64d(signing_key_b64))
    return _b64e(sk.sign(message).signature)


def verify_bytes(verify_key_b64: str, message: bytes, signature_b64: str) -> bool:
    """Verify a detached signature over raw bytes. Never raises."""
    try:
        vk = nacl.signing.VerifyKey(_b64d(verify_key_b64))
        vk.verify(message, _b64d(signature_b64))
        return True
    except (nacl.exceptions.BadSignatureError, ValueError, TypeError):
        return False


def sign_object(signing_key_b64: str, obj: Any) -> tuple[str, str]:
    """Canonicalize an object (JCS) and sign it.

    Returns (canonical_body_str, signature_b64) so the exact signed bytes are
    stored alongside the signature and can be re-verified later.
    """
    body = canonicalize(obj)
    signature = sign_bytes(signing_key_b64, body)
    return body.decode("utf-8"), signature


def verify_object(verify_key_b64: str, obj: Any, signature_b64: str) -> bool:
    """Re-canonicalize an object and verify the signature over it."""
    return verify_bytes(verify_key_b64, canonicalize(obj), signature_b64)
