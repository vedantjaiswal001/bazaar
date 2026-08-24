"""Append-only, hash-chained audit log - tamper-evident without a blockchain.

Each entry commits to the previous entry's hash AND its own event_type + payload:

    entry_hash = SHA-256( prev_hash_hex || event_type || JCS(payload) )

so altering any past entry's event_type or payload breaks its hash and every
subsequent hash. `verify_chain` walks the log and returns the exact seq where it
first breaks, if any. This is how "every authorization is reproducible from the
audit log" is made checkable.

Scope note (honest): this detects any modification or reordering of retained
entries. It does not by itself detect truncation of the most-recent entries -
that requires anchoring the tip externally (out of scope here, named as future
work). We never claim more than the construction provides.
"""
from __future__ import annotations

import hashlib
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from bazaar.config import GENESIS_HASH
from bazaar.crypto.jcs import canonicalize


def _hash(prev_hash: str, event_type: str, payload_bytes: bytes) -> str:
    return hashlib.sha256(
        prev_hash.encode("ascii") + event_type.encode("utf-8") + payload_bytes
    ).hexdigest()


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    event_type: str
    payload: str          # canonical JSON string
    prev_hash: str
    entry_hash: str


def append_event(conn: sqlite3.Connection, event_type: str, payload: dict[str, Any]) -> AuditEntry:
    """Append one event, chaining it to the current tip of the log."""
    # A per-event id keeps otherwise-identical payloads producing distinct hashes.
    payload = {"_event_id": uuid.uuid4().hex, **payload}
    body = canonicalize(payload)

    tip = conn.execute(
        "SELECT entry_hash FROM audit_logs ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    prev_hash = tip["entry_hash"] if tip else GENESIS_HASH
    entry_hash = _hash(prev_hash, event_type, body)

    cur = conn.execute(
        "INSERT INTO audit_logs (event_type, payload, prev_hash, entry_hash) VALUES (?, ?, ?, ?)",
        (event_type, body.decode("utf-8"), prev_hash, entry_hash),
    )
    conn.commit()
    return AuditEntry(
        seq=int(cur.lastrowid),
        event_type=event_type,
        payload=body.decode("utf-8"),
        prev_hash=prev_hash,
        entry_hash=entry_hash,
    )


@dataclass(frozen=True)
class ChainResult:
    ok: bool
    length: int
    broken_at_seq: int | None = None
    detail: str = ""


def verify_chain(conn: sqlite3.Connection) -> ChainResult:
    """Verify the whole chain. Returns the first broken seq if tampering is found."""
    rows = conn.execute(
        "SELECT seq, event_type, payload, prev_hash, entry_hash FROM audit_logs ORDER BY seq ASC"
    ).fetchall()
    prev = GENESIS_HASH
    for r in rows:
        expected = _hash(prev, r["event_type"], r["payload"].encode("utf-8"))
        if r["prev_hash"] != prev:
            return ChainResult(False, len(rows), r["seq"], "prev_hash does not match chain tip")
        if r["entry_hash"] != expected:
            return ChainResult(False, len(rows), r["seq"], "entry_hash does not match payload")
        prev = r["entry_hash"]
    return ChainResult(True, len(rows), None, "chain intact")
