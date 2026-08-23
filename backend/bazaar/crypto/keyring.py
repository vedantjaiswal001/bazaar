"""Authority keyring.

The gate signs Trust Receipts with an "authority" Ed25519 key. For local dev the
key is loaded from an env var, or generated once and persisted to a git-ignored
file so receipts stay verifiable across runs. Secrets never enter git.
"""
from __future__ import annotations

import os

from bazaar.config import REPO_ROOT
from bazaar.crypto.signing import generate_keypair, verify_key_for

_KEY_DIR = REPO_ROOT / ".keys"
_AUTHORITY_KEY_FILE = _KEY_DIR / "authority.key"  # matches *.key in .gitignore


def get_authority_keypair() -> tuple[str, str]:
    """Return (signing_key_b64, verify_key_b64) for the receipt authority.

    Priority: env var override -> persisted local key -> freshly generated key
    (persisted for next time).
    """
    env = os.environ.get("BAZAAR_AUTHORITY_SIGNING_KEY")
    if env:
        return env, verify_key_for(env)

    if _AUTHORITY_KEY_FILE.exists():
        signing_key = _AUTHORITY_KEY_FILE.read_text(encoding="utf-8").strip()
        return signing_key, verify_key_for(signing_key)

    signing_key, verify_key = generate_keypair()
    try:
        _KEY_DIR.mkdir(parents=True, exist_ok=True)
        _AUTHORITY_KEY_FILE.write_text(signing_key, encoding="utf-8")
        os.chmod(_AUTHORITY_KEY_FILE, 0o600)
    except OSError:
        pass  # ephemeral key is fine (e.g. read-only fs); receipts still verify in-run
    return signing_key, verify_key
