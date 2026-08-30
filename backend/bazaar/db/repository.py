"""Persistence helpers. The DB is where the replay + double-charge defenses live.

`reserve_nonce` and `record_transaction` rely on the UNIQUE constraints in the
schema: a duplicate raises sqlite3.IntegrityError, which the service turns into
the correct reason code. Even if an in-memory check ever missed a race, the
database would still refuse the second write.
"""
from __future__ import annotations

import json
import sqlite3

from bazaar.models import Mandate, MerchantRecord, TransactionRequest


class NonceAlreadyUsed(Exception):
    pass


class DuplicateTransaction(Exception):
    pass


# ---- agents ----
def register_agent(conn: sqlite3.Connection, agent_id: str, display_name: str, role: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO agents (agent_id, display_name, role) VALUES (?, ?, ?)",
        (agent_id, display_name, role),
    )
    conn.commit()


def set_agent_frozen(conn: sqlite3.Connection, agent_id: str, frozen: bool) -> None:
    conn.execute("UPDATE agents SET frozen = ? WHERE agent_id = ?", (1 if frozen else 0, agent_id))
    conn.commit()


def is_agent_frozen(conn: sqlite3.Connection, agent_id: str) -> bool:
    row = conn.execute("SELECT frozen FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
    return bool(row["frozen"]) if row else False


# ---- mandates ----
def save_mandate(conn: sqlite3.Connection, m: Mandate) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO mandates
           (mandate_id, agent_id, max_amount, currency, allowed_categories,
            return_policy_days, issued_at, expires_at, public_key, signature, canonical_body)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (m.mandate_id, m.agent_id, m.max_amount, m.currency,
         json.dumps(sorted(m.allowed_categories)), m.return_policy_days,
         m.issued_at, m.expires_at, m.public_key, m.signature, m.canonical_body),
    )
    conn.commit()


# ---- nonce / idempotency state (read by the gate) ----
def nonce_seen(conn: sqlite3.Connection, nonce: str) -> bool:
    return conn.execute("SELECT 1 FROM nonces WHERE nonce = ?", (nonce,)).fetchone() is not None


def idempotency_seen(conn: sqlite3.Connection, key: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM transactions WHERE idempotency_key = ? AND decision = 'ALLOW'", (key,)
    ).fetchone() is not None


def reserve_nonce(conn: sqlite3.Connection, nonce: str, mandate_id: str) -> None:
    """Reserve a nonce. Raises NonceAlreadyUsed if the DB UNIQUE constraint rejects it."""
    try:
        conn.execute("INSERT INTO nonces (nonce, mandate_id) VALUES (?, ?)", (nonce, mandate_id))
    except sqlite3.IntegrityError as exc:
        raise NonceAlreadyUsed(nonce) from exc


# ---- transactions ----
def record_transaction(
    conn: sqlite3.Connection, txn: TransactionRequest, decision: str, reason: str, status: str
) -> None:
    """Insert a transaction row. Raises DuplicateTransaction on idempotency clash for an ALLOW."""
    try:
        conn.execute(
            """INSERT INTO transactions
               (txn_id, mandate_id, agent_id, sku, category, amount, price_source,
                nonce, idempotency_key, decision, reason_code, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (txn.txn_id, txn.mandate.mandate_id, txn.agent_id, txn.sku, txn.category,
             txn.amount, txn.price_source.value, txn.nonce, txn.idempotency_key,
             decision, reason, status),
        )
    except sqlite3.IntegrityError as exc:
        # Only the idempotency partial-unique index means "already authorized".
        # Re-raise anything else (e.g. a real FK bug) rather than mislabeling it.
        if "unique" in str(exc).lower():
            raise DuplicateTransaction(txn.idempotency_key) from exc
        raise


def set_transaction_settlement(
    conn: sqlite3.Connection, txn_id: str, *, status: str,
    razorpay_order_id: str | None = None, razorpay_payment_id: str | None = None,
) -> None:
    conn.execute(
        """UPDATE transactions
           SET status = ?, razorpay_order_id = COALESCE(?, razorpay_order_id),
               razorpay_payment_id = COALESCE(?, razorpay_payment_id),
               executed_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
           WHERE txn_id = ?""",
        (status, razorpay_order_id, razorpay_payment_id, txn_id),
    )
    conn.commit()


# ---- receipts ----
def save_receipt(conn: sqlite3.Connection, receipt_id: str, txn_id: str,
                 canonical_body: str, public_key: str, signature: str) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO receipts
           (receipt_id, txn_id, canonical_body, public_key, signature)
           VALUES (?, ?, ?, ?, ?)""",
        (receipt_id, txn_id, canonical_body, public_key, signature),
    )
    conn.commit()


# ---- merchant catalog (write path is admin-only; see catalog/store.py) ----
def upsert_catalog_item(conn: sqlite3.Connection, r: MerchantRecord) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO merchant_catalog
           (sku, merchant_id, title, category, price, currency, return_policy_days,
            description, floor_price, active)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (r.sku, r.merchant_id, r.title, r.category, r.price, r.currency,
         r.return_policy_days, r.description, r.floor_price, 1 if r.active else 0),
    )
    conn.commit()


def get_catalog_item(conn: sqlite3.Connection, sku: str) -> MerchantRecord | None:
    row = conn.execute("SELECT * FROM merchant_catalog WHERE sku = ?", (sku,)).fetchone()
    if row is None:
        return None
    return MerchantRecord(
        sku=row["sku"], merchant_id=row["merchant_id"], title=row["title"],
        category=row["category"], price=row["price"], currency=row["currency"],
        return_policy_days=row["return_policy_days"], description=row["description"],
        floor_price=row["floor_price"], active=bool(row["active"]),
    )


def list_catalog_items(conn: sqlite3.Connection) -> list[MerchantRecord]:
    rows = conn.execute("SELECT sku FROM merchant_catalog WHERE active = 1 ORDER BY sku").fetchall()
    items = [get_catalog_item(conn, r["sku"]) for r in rows]
    return [i for i in items if i is not None]
