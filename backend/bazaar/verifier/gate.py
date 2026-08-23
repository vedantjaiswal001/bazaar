"""The deterministic authorization gate — the heart of BAZAAR.

A fixed checklist. Every money action passes through it. All checks pass -> ALLOW.
Any check fails -> BLOCK with exactly one machine-readable reason code. There is
no probabilistic branch in here and no import from the LLM / agent layer.

The gate is a PURE FUNCTION of its inputs. Database state (nonce seen, idempotency
key seen, agent frozen) is passed in, not fetched, so the gate can be exhaustively
property-tested and fuzzed without any I/O. The DB-backed adapter that supplies
real state lives in verifier/service.py.

INVARIANT (the fuzzer's target): ALLOW  =>  txn.amount <= mandate.max_amount.
Because ALLOW additionally requires amount == merchant-of-record price, the gate
in fact guarantees ALLOW => amount == record.price <= cap.
"""
from __future__ import annotations

from datetime import datetime

from bazaar.models import (
    Check,
    GateResult,
    MerchantRecord,
    PriceSource,
    RiskAction,
    RiskSignal,
    TransactionRequest,
)
from bazaar.verifier.reasons import RISK_REVIEW, Decision, Reason


def _block(reason: Reason, detail: str, checks: list[Check]) -> GateResult:
    return GateResult(
        decision=Decision.BLOCK.value, reason=reason.value, detail=detail, checks=checks
    )


def authorize(
    txn: TransactionRequest,
    record: MerchantRecord | None,
    *,
    nonce_seen: bool,
    idempotency_seen: bool,
    agent_frozen: bool,
    at: datetime | None = None,
) -> GateResult:
    """Run the fixed checklist. Returns ALLOW or BLOCK(reason_code).

    The checks run in a fixed order; the FIRST failing check names the reason.
    """
    checks: list[Check] = []

    # 1. Mandate signature is valid and immutable (Policy attack -> MANDATE_IMMUTABLE).
    sig_ok = txn.mandate.verify_signature()
    checks.append(Check("mandate_signature_valid", sig_ok))
    if not sig_ok:
        return _block(
            Reason.MANDATE_IMMUTABLE,
            "mandate signature does not verify — a signed field was altered",
            checks,
        )

    # 2. Mandate agent matches the transacting agent.
    agent_ok = txn.mandate.agent_id == txn.agent_id
    checks.append(Check("mandate_agent_matches", agent_ok))
    if not agent_ok:
        return _block(
            Reason.MANDATE_IMMUTABLE,
            "transaction agent does not match the mandate's agent",
            checks,
        )

    # 3. Mandate not expired (Expiry attack -> MANDATE_EXPIRED).
    expired = txn.mandate.is_expired(at)
    checks.append(Check("mandate_not_expired", not expired))
    if expired:
        return _block(
            Reason.MANDATE_EXPIRED, "mandate is past its time-to-live", checks
        )

    # 4. Agent not frozen (State attack -> AGENT_FROZEN).
    checks.append(Check("agent_not_frozen", not agent_frozen))
    if agent_frozen:
        return _block(Reason.AGENT_FROZEN, "agent is frozen", checks)

    # 5. Money-fields sourced from the merchant of record (Injection -> UNTRUSTED_INSTRUCTION).
    provenance_ok = txn.price_source == PriceSource.MERCHANT_RECORD
    checks.append(Check("money_field_from_merchant_record", provenance_ok))
    if not provenance_ok:
        return _block(
            Reason.UNTRUSTED_INSTRUCTION,
            f"money-field provenance is '{txn.price_source.value}', not the merchant of record",
            checks,
        )

    # 6. A merchant-of-record row exists and is active (Price -> PRICE_MISMATCH_MERCHANT_RECORD).
    record_ok = record is not None and record.active and record.sku == txn.sku
    checks.append(Check("merchant_record_exists", bool(record_ok)))
    if not record_ok:
        return _block(
            Reason.PRICE_MISMATCH_MERCHANT_RECORD,
            "no active merchant-of-record row for this sku",
            checks,
        )
    assert record is not None  # for type-checkers; guaranteed by record_ok

    # 7. Price equals the merchant of record exactly (Price -> PRICE_MISMATCH_MERCHANT_RECORD).
    price_ok = txn.amount == record.price
    checks.append(Check("price_equals_merchant_record", price_ok,
                        f"amount={txn.amount} record={record.price}"))
    if not price_ok:
        return _block(
            Reason.PRICE_MISMATCH_MERCHANT_RECORD,
            f"amount {txn.amount} != merchant-of-record price {record.price}",
            checks,
        )

    # 8. Authoritative category is inside the mandate's allowlist
    #    (Category attack -> CATEGORY_OUTSIDE_MANDATE). We use the RECORD's
    #    category, never the agent's claim, so a lie about category cannot pass.
    category_ok = record.category in txn.mandate.allowed_categories
    checks.append(Check("category_in_allowlist", category_ok,
                        f"category={record.category} allow={list(txn.mandate.allowed_categories)}"))
    if not category_ok:
        return _block(
            Reason.CATEGORY_OUTSIDE_MANDATE,
            f"category '{record.category}' not in mandate allowlist",
            checks,
        )

    # 9. Amount within the signed cap (Budget attack -> MANDATE_LIMIT_EXCEEDED).
    #    THIS is the invariant the fuzzer targets.
    cap_ok = txn.amount <= txn.mandate.max_amount
    checks.append(Check("amount_within_cap", cap_ok,
                        f"amount={txn.amount} cap={txn.mandate.max_amount}"))
    if not cap_ok:
        return _block(
            Reason.MANDATE_LIMIT_EXCEEDED,
            f"amount {txn.amount} exceeds signed cap {txn.mandate.max_amount}",
            checks,
        )

    # 10. Nonce unused (Replay attack -> NONCE_REPLAY).
    checks.append(Check("nonce_unused", not nonce_seen))
    if nonce_seen:
        return _block(Reason.NONCE_REPLAY, "nonce has already been used", checks)

    # 11. Idempotency key unused (Double-charge attack -> DUPLICATE_TRANSACTION).
    checks.append(Check("idempotency_key_unused", not idempotency_seen))
    if idempotency_seen:
        return _block(
            Reason.DUPLICATE_TRANSACTION,
            "idempotency key has already been used",
            checks,
        )

    # All deterministic checks pass.
    return GateResult(
        decision=Decision.ALLOW.value,
        reason=Reason.OK.value,
        detail="all checks passed",
        checks=checks,
    )


def apply_risk(base: GateResult, signal: RiskSignal | None) -> GateResult:
    """Apply an advisory risk signal to a gate result.

    Tighten only: an ALLOW may become REVIEW or BLOCK; a BLOCK never becomes
    ALLOW, and a risk signal can never turn a block into an approval. If the base
    decision is already BLOCK, the deterministic reason code is preserved.
    """
    if signal is None or base.decision == Decision.BLOCK.value:
        return base
    if signal.action == RiskAction.BLOCK:
        return GateResult(
            decision=Decision.BLOCK.value,
            reason=RISK_REVIEW,
            detail=f"risk signal blocked (score={signal.score}): {'; '.join(signal.reasons)}",
            checks=base.checks,
        )
    if signal.action == RiskAction.REVIEW:
        return GateResult(
            decision=Decision.REVIEW.value,
            reason=RISK_REVIEW,
            detail=f"risk signal requests human review (score={signal.score})",
            checks=base.checks,
        )
    return base
