"""Central configuration. Secrets come from the environment only, never code.

Nothing in this file hardcodes an API key, secret, or private key. Local dev
reads a .env file (see .env.example); the values themselves stay out of git.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:  # optional: load .env if python-dotenv is installed
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional at runtime
    pass

# Repo root = three levels up from this file (backend/bazaar/config.py -> repo/)
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "bazaar.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "db" / "schema.sql"

# The genesis previous-hash for the audit chain (64 hex zeros).
GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class Settings:
    db_path: str
    razorpay_key_id: str | None
    razorpay_key_secret: str | None
    razorpay_webhook_secret: str | None
    # Mandate default TTL in seconds (minutes, not seconds -- generous but bounded).
    mandate_ttl_seconds: int

    @staticmethod
    def load() -> Settings:
        return Settings(
            db_path=os.environ.get("BAZAAR_DB_PATH", str(DEFAULT_DB_PATH)),
            razorpay_key_id=os.environ.get("RAZORPAY_KEY_ID"),
            razorpay_key_secret=os.environ.get("RAZORPAY_KEY_SECRET"),
            razorpay_webhook_secret=os.environ.get("RAZORPAY_WEBHOOK_SECRET"),
            mandate_ttl_seconds=int(os.environ.get("BAZAAR_MANDATE_TTL_SECONDS", "900")),
        )


settings = Settings.load()
