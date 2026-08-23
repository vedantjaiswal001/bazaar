"""DB-backed authorization service — the live adapter around the pure gate.

Flow for one transaction:
  1. read live state from the DB (nonce used? idempotency key used? agent frozen?)
  2. run the pure deterministic gate  -> authoritative decision + reason code
  3. compute the advisory risk signal  -> may tighten the *effective* decision only
  4. on ALLOW: reserve the nonce and record the transaction. The DB UNIQUE
     constraints are the final word: if a race slipped past step 1, the INSERT
     fails and we downgrade to the correct reason code (defense in depth).
  5. sign a Trust Receipt and append a hash-chained audit entry — always.

The deterministic reason code is what gets recorded and measured. The risk signal
is surfaced for display/escalation but never rewrites a deterministic reason.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from bazaar.crypto.jcs import canonical_str
from bazaar.crypto.keyring import get_authority_keypair
from bazaar.db import repository as repo
from bazaar.ledger.audit_log import append_event
from bazaar.models import GateResult, MerchantRecord, RiskSignal, TransactionRequest
from bazaar.receipt.trust_receipt import TrustReceipt, build_receipt
from bazaar.risk.model import assess
from bazaar.verifier.gate import apply_risk, authorize
from bazaar.verifier.reasons import Decision, Reason


@dataclass
class AuthorizationOutcome:
    result: GateResult          # authoritative deterministic decision
    risk: RiskSignal
    effective_decision: str     # after advisory risk tightening (live flow)
    receipt: TrustReceipt
    audit_seq: int
    persisted: bool


class AuthorizationService:
    def __init__(self, conn: sqlite3.Connection, authority_keys: tuple[str, str] | None = None):
        self.conn = conn
        self._sk, self._pk = authority_keys or get_authority_keypair()

    def authorize(
        self,
        txn: TransactionRequest,
        offer: MerchantRecord | None,
        *,
        razorpay_order_id: str | None = None,
        razorpay_payment_id: str | None = None,
    ) -> AuthorizationOutcome:
        frozen = repo.is_agent_frozen(self.conn, txn.agent_id)
        nseen = repo.nonce_seen(self.conn, txn.nonce)
        iseen = repo.idempotency_seen(self.conn, txn.idempotency_key)

        result = authorize(txn, offer, nonce_seen=nseen, idempotency_seen=iseen, agent_frozen=frozen)
        risk = assess(txn, offer)

        persisted = False
        if result.decision == Decision.ALLOW.value:
            # The database has the final say on replay / double-charge.
            try:
                repo.reserve_nonce(self.conn, txn.nonce, txn.mandate.mandate_id)
                repo.record_transaction(self.conn, txn, result.decision, result.reason,
                                        status="authorized")
                self.conn.commit()
                persisted = True
            except repo.NonceAlreadyUsed:
                self.conn.rollback()
                result = GateResult(Decision.BLOCK.value, Reason.NONCE_REPLAY.value,
                                    "nonce rejected by database constraint", result.checks)
            except repo.DuplicateTransaction:
                self.conn.rollback()
                result = GateResult(Decision.BLOCK.value, Reason.DUPLICATE_TRANSACTION.value,
                                    "idempotency key rejected by database constraint", result.checks)

        # Record blocked attempts too, so there is a full ledger of attempts and
        # the receipt has a transaction to reference. The partial unique index
        # applies only to ALLOW rows, so a blocked replay may reuse its key.
        if result.decision != Decision.ALLOW.value:
            repo.record_transaction(self.conn, txn, result.decision, result.reason,
                                    status="blocked")
            self.conn.commit()

        effective = apply_risk(result, risk).decision

        receipt = build_receipt(
            self._sk, self._pk, txn=txn, record=offer, result=result,
            razorpay_order_id=razorpay_order_id, razorpay_payment_id=razorpay_payment_id,
        )
        repo.save_receipt(self.conn, receipt.receipt_id, txn.txn_id,
                          canonical_str(receipt.body), receipt.public_key, receipt.signature)

        entry = append_event(self.conn, "authorization", {
            "txn_id": txn.txn_id,
            "agent_id": txn.agent_id,
            "amount": txn.amount,
            "decision": result.decision,
            "reason": result.reason,
            "effective_decision": effective,
            "risk_score": risk.score,
            "receipt_id": receipt.receipt_id,
        })

        return AuthorizationOutcome(
            result=result, risk=risk, effective_decision=effective,
            receipt=receipt, audit_seq=entry.seq, persisted=persisted,
        )
