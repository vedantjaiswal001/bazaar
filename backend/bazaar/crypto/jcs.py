"""Canonical JSON (RFC 8785 JCS).

Everything that gets signed or hash-chained is first canonicalized here, so the
exact same bytes are produced regardless of key order or whitespace. We do not
hand-roll this — we use the `rfc8785` library.
"""
from __future__ import annotations

from typing import Any

import rfc8785


def canonicalize(obj: Any) -> bytes:
    """Return the RFC 8785 canonical byte serialization of a JSON-like object.

    Money must already be integer paise; JCS forbids anything that would make
    floats non-deterministic, which is one more reason money never uses floats.
    """
    return rfc8785.dumps(obj)


def canonical_str(obj: Any) -> str:
    """Canonical JSON as a UTF-8 string (for storage / display)."""
    return canonicalize(obj).decode("utf-8")
