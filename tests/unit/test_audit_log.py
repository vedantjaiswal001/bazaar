"""The audit chain is tamper-evident: intact chains verify, edits are caught."""
from __future__ import annotations

from bazaar.ledger.audit_log import append_event, verify_chain


def test_empty_chain_is_valid(db):
    result = verify_chain(db)
    assert result.ok and result.length == 0


def test_appended_chain_verifies(db):
    for i in range(10):
        append_event(db, "authorization", {"txn": f"t{i}", "decision": "ALLOW"})
    result = verify_chain(db)
    assert result.ok
    assert result.length == 10
    assert result.broken_at_seq is None


def test_tampering_a_past_payload_breaks_the_chain(db):
    for i in range(5):
        append_event(db, "authorization", {"txn": f"t{i}", "amount": 100 * i})
    # Tamper: rewrite the payload of seq 3 directly in the DB (simulating an attacker).
    db.execute("UPDATE audit_logs SET payload = ? WHERE seq = 3",
               ('{"txn":"t2","amount":999999}',))
    db.commit()

    result = verify_chain(db)
    assert not result.ok
    assert result.broken_at_seq == 3


def test_reordering_hashes_breaks_the_chain(db):
    for i in range(4):
        append_event(db, "authorization", {"i": i})
    # Swap two entry hashes -> chain linkage breaks.
    db.execute("UPDATE audit_logs SET entry_hash = 'deadbeef' WHERE seq = 2")
    db.commit()
    result = verify_chain(db)
    assert not result.ok
    assert result.broken_at_seq in (2, 3)
