"""AP2 rail adapter - make a BAZAAR merchant sellable to a real AI buyer.

Implements the merchant side of Google's Agent Payments Protocol (AP2): it
verifies an ES256-signed **Cart Mandate** (a JWS carrying the user-authorised
cart and its spending constraints), then translates the verified mandate into
BAZAAR's canonical domain - a trusted-issuer-signed `Mandate` and a
`TransactionRequest`. From there the SAME untouched 11-check gate decides.

Division of trust, on purpose:
  * AP2 layer (here) proves AUTHENTICITY - the cart was signed by a registered
    credential provider, is unexpired, well-formed, and self-consistent.
  * the deterministic gate enforces MONEY - the authorised amount must equal the
    merchant of record's price and sit within the signed cap, or it is blocked
    with the usual reason code. A validly-signed cart whose price disagrees with
    the merchant of record is a price tamper, and the gate catches it.

This module imports only bazaar.models + PyJWT. It never touches the verifier;
it prepares inputs for it. (Full SD-JWT selective disclosure is a documented
extension; this bridge verifies the ES256-signed Cart Mandate JWS.)
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import jwt

from bazaar.models import (
    Mandate,
    MerchantRecord,
    PriceSource,
    TransactionRequest,
    now_utc,
    to_rfc3339,
)

CART_VCT = "mandate.cart.1"   # AP2 verifiable-credential type for a Cart Mandate


class AP2VerificationError(Exception):
    """Raised when a Cart Mandate fails authenticity/structure checks.

    `code` is a stable, machine-readable slug surfaced as an `AP2_<CODE>` reason.
    """

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")

    @property
    def reason(self) -> str:
        return f"AP2_{self.code.upper()}"


@dataclass(frozen=True)
class AP2CartMandate:
    """A verified AP2 Cart Mandate, parsed into plain fields."""

    transaction_id: str
    issuer_kid: str
    subject: str
    payee_id: str
    currency: str
    sku: str
    title: str
    unit_amount: int
    quantity: int
    total_amount: int
    max_amount: int
    allowed_payees: tuple[str, ...]
    expires_at: str          # RFC3339, derived from the JWT `exp`


def verify_cart_mandate(
    token: str,
    trusted_keys: dict[str, str],
    *,
    at: datetime | None = None,
) -> AP2CartMandate:
    """Verify an ES256 Cart Mandate against the registered credential-provider keys.

    `trusted_keys` maps a credential-provider `kid` -> its PEM public key. A cart
    signed by a key we have not registered is rejected before anything else -
    this is what stops a rogue agent minting its own authorisation.
    """
    at = at or now_utc()
    try:
        header = jwt.get_unverified_header(token)
    except Exception as exc:  # malformed token
        raise AP2VerificationError("malformed", str(exc)) from exc

    kid = header.get("kid")
    if not kid or kid not in trusted_keys:
        raise AP2VerificationError("untrusted_issuer",
                                   f"kid {kid!r} is not a registered credential provider")
    if header.get("alg") != "ES256":
        raise AP2VerificationError("bad_alg", f"alg {header.get('alg')!r} != ES256")

    try:
        claims = jwt.decode(
            token, trusted_keys[kid], algorithms=["ES256"],
            options={"require": ["exp"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AP2VerificationError("expired", "cart mandate has expired") from exc
    except Exception as exc:  # bad signature, malformed claims, ...
        raise AP2VerificationError("invalid_signature", type(exc).__name__) from exc

    if claims.get("vct") != CART_VCT:
        raise AP2VerificationError("wrong_type", f"vct {claims.get('vct')!r} != {CART_VCT}")

    cart = claims.get("cart") or {}
    items = cart.get("items") or []
    if len(items) != 1:
        raise AP2VerificationError("unsupported_cart",
                                   "this bridge settles single-line carts")
    item = items[0]
    try:
        unit = int(item["unit_amount"])
        qty = int(item.get("quantity", 1))
        total = int(cart["total_amount"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AP2VerificationError("malformed", f"cart fields: {exc}") from exc

    # Cart self-consistency: the signed total must equal the signed line maths.
    if total != unit * qty:
        raise AP2VerificationError("cart_total_mismatch", f"total {total} != {unit}x{qty}")

    payee = (cart.get("payee") or {}).get("merchant_id", "")
    constraints = claims.get("constraints") or {}
    allowed = tuple(constraints.get("allowed_payees", []))
    if allowed and payee not in allowed:
        raise AP2VerificationError("payee_not_allowed", f"payee {payee!r} not in {allowed}")

    exp_dt = datetime.fromtimestamp(int(claims["exp"]), tz=timezone.utc)
    return AP2CartMandate(
        transaction_id=str(claims.get("transaction_id") or uuid.uuid4().hex),
        issuer_kid=kid,
        subject=str(claims.get("sub", "ap2-user")),
        payee_id=payee,
        currency=str(cart.get("currency", "INR")),
        sku=str(item["sku"]),
        title=str(item.get("title", "")),
        unit_amount=unit,
        quantity=qty,
        total_amount=total,
        max_amount=int(constraints.get("max_amount", total)),
        allowed_payees=allowed,
        expires_at=to_rfc3339(exp_dt),
    )


def to_bazaar(
    cart: AP2CartMandate,
    record: MerchantRecord | None,
    issuer,
    *,
    agent_id: str | None = None,
) -> tuple[Mandate, TransactionRequest]:
    """Translate a verified Cart Mandate into a signed BAZAAR Mandate + txn.

    `issuer` is the AP2 trust bridge - a pinned trusted issuer (duck-typed:
    anything with `confirm_and_sign(unsigned) -> Mandate`). It signs the BAZAAR
    Mandate ONLY after AP2 verification has passed, so the gate's issuer pin holds
    and no agent can self-issue. Requires an active merchant-of-record row.
    """
    if record is None or not record.active:
        raise AP2VerificationError("sku_not_found",
                                   f"no active merchant-of-record row for {cart.sku!r}")

    agent_id = agent_id or f"ap2:{cart.subject}"
    issued = now_utc()
    draft = Mandate(
        mandate_id=f"ap2-{cart.transaction_id[:8]}",
        agent_id=agent_id,
        max_amount=cart.max_amount,
        allowed_categories=(record.category,),
        return_policy_days=record.return_policy_days,
        issued_at=to_rfc3339(issued),
        expires_at=cart.expires_at,
    )
    mandate = issuer.confirm_and_sign(draft)   # Ed25519, pinned issuer key

    txn = TransactionRequest(
        txn_id=f"ap2-{uuid.uuid4().hex[:10]}",
        mandate=mandate,
        agent_id=agent_id,
        sku=cart.sku,
        category=record.category,
        # The amount the USER authorised in the signed cart. The gate compares it
        # to the merchant of record's price: agree -> ALLOW, disagree -> PRICE tamper.
        amount=cart.total_amount,
        price_source=PriceSource.MERCHANT_RECORD,
        nonce=uuid.uuid4().hex,
        idempotency_key=cart.transaction_id,
    )
    return mandate, txn
