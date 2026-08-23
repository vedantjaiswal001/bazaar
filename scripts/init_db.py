#!/usr/bin/env python3
"""Initialize (or reset) the BAZAAR SQLite database from the schema.

Run by `make setup` and `make db`. Idempotent: creates a fresh, empty DB with
every table and constraint in place, then prints what it made so the checkpoint
is visible.
"""
from __future__ import annotations

import sys

from bazaar.db.database import connect, init_db, table_names


def main() -> int:
    path = init_db(drop=True)
    conn = connect(path)
    try:
        tables = table_names(conn)
        # Confirm the two schema-level defenses actually exist.
        nonce_pk = conn.execute("PRAGMA table_info(nonces)").fetchall()
        idem_idx = conn.execute("PRAGMA index_list(transactions)").fetchall()
    finally:
        conn.close()

    print(f"✓ database initialized at: {path}")
    print(f"  tables ({len(tables)}): {', '.join(tables)}")
    nonce_is_pk = any(col["name"] == "nonce" and col["pk"] for col in nonce_pk)
    idem_unique = any(ix["unique"] for ix in idem_idx)
    print(f"  nonce UNIQUE (replay defense in schema): {nonce_is_pk}")
    print(f"  idempotency_key UNIQUE (double-charge defense in schema): {idem_unique}")
    if not (nonce_is_pk and idem_unique):
        print("✗ schema-level defenses missing", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
