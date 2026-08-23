#!/usr/bin/env python3
"""Phase 3 checkpoint: Trust Receipt + hash-chained audit log, demonstrated live.

Shows, in order:
  1. a signed Trust Receipt verifying (pass),
  2. the same receipt failing after one field is tampered,
  3. an audit chain verifying end-to-end,
  4. the chain breaking at the exact entry when a past record is altered.

Everything here runs against a throwaway in-memory-style DB file; no network.
"""
from __future__ import annotations

import copy

# Reuse the test factory for realistic objects.
import sys
import tempfile
from pathlib import Path

from bazaar.crypto.signing import generate_keypair
from bazaar.db.database import connect, init_db
from bazaar.ledger.audit_log import append_event, verify_chain
from bazaar.receipt.trust_receipt import build_receipt, verify_receipt_json
from bazaar.verifier.gate import authorize

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from factory import (
    make_keypair,
    make_record,
    make_signed_mandate,
    make_txn,
)


def line(c: str = "-") -> None:
    print(c * 64)


def main() -> int:
    print("BAZAAR - Phase 3 checkpoint: receipts + hash-chained audit log")
    line("=")

    # --- 1 & 2: Trust Receipt verify-pass then tamper-fail ---
    sk, vk = make_keypair()
    mandate = make_signed_mandate(signing_key=sk, public_key=vk)
    record = make_record()
    txn = make_txn(mandate=mandate)
    result = authorize(txn, record, nonce_seen=False, idempotency_seen=False, agent_frozen=False)
    auth_sk, auth_vk = generate_keypair()
    receipt = build_receipt(auth_sk, auth_vk, txn=txn, record=record, result=result)

    print(f"1. Decision: {result.decision} ({result.reason})  amount={txn.amount} paise")
    print(f"   Trust Receipt {receipt.receipt_id} signed by authority key.")
    print(f"   verify() -> {receipt.verify()}   (expected: True)")
    line()
    forged = copy.deepcopy(receipt.to_json())
    forged["body"]["amount"] = 999_999
    print("2. Attacker rewrites amount 449900 -> 999999 in the receipt body.")
    print(f"   verify() -> {verify_receipt_json(forged)}   (expected: False)")
    line("=")

    # --- 3 & 4: audit chain verify then tamper-detect ---
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "chain.db")
        init_db(path, drop=True)
        conn = connect(path)
        for i in range(6):
            append_event(conn, "authorization",
                         {"txn": f"t{i}", "decision": "ALLOW" if i % 2 else "BLOCK",
                          "amount": 449900 + i})
        chain = verify_chain(conn)
        print(f"3. Appended {chain.length} audit entries.")
        print(f"   verify_chain() -> ok={chain.ok}  ({chain.detail})   (expected: ok=True)")
        line()
        conn.execute("UPDATE audit_logs SET payload = ? WHERE seq = 4",
                     ('{"txn":"t3","decision":"ALLOW","amount":50000000}',))
        conn.commit()
        broken = verify_chain(conn)
        print("4. Attacker edits the payload of audit entry seq=4 in the database.")
        print(f"   verify_chain() -> ok={broken.ok}  broken_at_seq={broken.broken_at_seq}"
              f"  ({broken.detail})")
        print("   (expected: ok=False, broken_at_seq=4) - tamper-evident without a blockchain.")
        conn.close()
    line("=")
    print("✓ Phase 3 checkpoint complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
