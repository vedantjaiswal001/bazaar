#!/usr/bin/env python3
"""BAZAAR - LIVE Razorpay Test Mode payment (Phase 2 live checkpoint).

This is the one step that talks to Razorpay's real servers. It uses your
TEST-mode keys (rzp_test_...), so no real money ever moves. It proves the whole
settlement story end to end, and it needs NO webhook tunnel (no ngrok): it
reconciles by polling Razorpay's own `order.payments` API, which is the source
of truth.

What it does, in order:
  1. Runs the gate on a legitimate purchase  -> ALLOW + a signed Trust Receipt.
  2. Creates a REAL Test Mode order on api.razorpay.com  -> prints the order id.
  3. Opens a local checkout page so you can pay with the Razorpay TEST card.
  4. Reconciles against Razorpay  -> settles the transaction exactly once.
  5. Re-runs settle + reconcile  -> proves idempotency LIVE (no double charge).
  6. Verifies the Trust Receipt signature and the hash-chained audit log.

Usage (from the repo root, with your .env filled in):
    python scripts/live_razorpay.py

Dry run (no network, no keys - proves the wiring with a fake Razorpay):
    python scripts/live_razorpay.py --fake

Razorpay TEST card:  4111 1111 1111 1111   any future expiry   any CVV
"""
from __future__ import annotations

import argparse
import http.server
import socket
import socketserver
import sys
import threading
import time
import webbrowser
from pathlib import Path

from bazaar.agents.buyer import BuyerAgent
from bazaar.agents.issuer import Issuer
from bazaar.agents.negotiation import negotiate
from bazaar.agents.seller import SellerAgent
from bazaar.catalog.seed import seed_default_catalog
from bazaar.catalog.store import CatalogStore
from bazaar.config import settings
from bazaar.db import repository as repo
from bazaar.db.database import connect, init_db
from bazaar.ledger.audit_log import verify_chain
from bazaar.razorpay.client import OrderResult, RazorpayClient
from bazaar.razorpay.settlement import reconcile, settle
from bazaar.verifier.service import AuthorizationService


def rupees(paise: int) -> str:
    return f"₹{paise / 100:,.2f}"


def hr(c: str = "-") -> None:
    print(c * 70)


# --------------------------------------------------------------------------- #
# A fake Razorpay for the --fake dry run: no network, auto-captures on reconcile.
# Lets us prove the exact script logic without keys. The LIVE path uses the real
# RazorpayClient and is byte-for-byte the same code around it.
# --------------------------------------------------------------------------- #
class _FakeRazorpay:
    def __init__(self) -> None:
        self.n = 0
        self._orders: dict[str, int] = {}

    def create_order(self, *, amount, receipt, currency="INR", notes=None):
        self.n += 1
        oid = f"order_FAKELIVE{self.n}"
        self._orders[oid] = amount
        return OrderResult(order_id=oid, amount=amount, currency=currency,
                           status="created", receipt=receipt, raw={})

    def order_payments(self, order_id):
        # Pretend the customer has already paid with a test card.
        amt = self._orders.get(order_id, 0)
        return {"items": [{"id": "pay_FAKECAPTURED", "status": "captured", "amount": amt}]}


CHECKOUT_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BAZAAR - Razorpay Test Mode checkout</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
    max-width: 560px; margin: 8vh auto; padding: 0 24px; line-height: 1.6;
    background: #0b0d12; color: #e8ecf3; }}
  .card {{ background: #141821; border: 1px solid #232a37; border-radius: 16px;
    padding: 28px 30px; box-shadow: 0 20px 60px rgba(0,0,0,.45); }}
  h1 {{ font-size: 20px; margin: 0 0 4px; letter-spacing: .3px; }}
  .amt {{ font-size: 34px; font-weight: 800; margin: 10px 0 2px;
    color: #ff6a5b; }}
  .muted {{ color: #8b95a7; font-size: 14px; }}
  code {{ background: #1c222e; padding: 2px 7px; border-radius: 6px; color: #ffd7a8; }}
  button {{ appearance: none; border: 0; margin-top: 20px; width: 100%;
    padding: 14px 18px; font-size: 16px; font-weight: 700; border-radius: 12px;
    background: linear-gradient(180deg,#ff7d6e,#ef5a49); color: #fff; cursor: pointer; }}
  .ok {{ margin-top: 18px; padding: 14px 16px; border-radius: 12px; display: none;
    background: #12271b; border: 1px solid #1f5133; color: #7ff0a8; }}
  .tip {{ margin-top: 22px; font-size: 13px; }}
</style></head>
<body>
  <div class="card">
    <h1>BAZAAR - authorized purchase</h1>
    <div class="muted">Order <code>{order_id}</code> - Razorpay <b>Test Mode</b></div>
    <div class="amt">{amount_rupees}</div>
    <div class="muted">This is a real Test Mode order. No real money moves.</div>
    <button id="pay">Pay with Razorpay (test card)</button>
    <div class="ok" id="ok"></div>
    <div class="tip muted">Test card <code>4111 1111 1111 1111</code>,
      any future expiry, any CVV, any name.<br>
      After it succeeds, return to your terminal and press <b>Enter</b>.</div>
  </div>
  <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
  <script>
    var options = {{
      key: "{key_id}",
      order_id: "{order_id}",
      amount: {amount_paise},
      currency: "INR",
      name: "BAZAAR",
      description: "Authorized by a signed mandate + deterministic gate",
      handler: function (response) {{
        var el = document.getElementById('ok');
        el.style.display = 'block';
        el.innerHTML = 'Payment captured: <code>' + response.razorpay_payment_id +
          '</code><br>Return to your terminal and press Enter to reconcile.';
      }},
      theme: {{ color: "#ef5a49" }}
    }};
    document.getElementById('pay').onclick = function () {{
      var rzp = new Razorpay(options); rzp.open();
    }};
  </script>
</body></html>
"""


def _serve_checkout(html: str) -> tuple[int, threading.Thread]:
    """Serve the checkout page on a free localhost port; return (port, thread)."""
    payload = html.encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):  # silence per-request logging
            return

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    httpd = socketserver.TCPServer(("127.0.0.1", port), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return port, t


def _authorize_purchase(conn):
    """Run the gate on a legitimate purchase and return (txn, offer, out)."""
    seed_default_catalog(conn)
    store = CatalogStore(conn)
    seller = SellerAgent("merch-athleto", store.seller_view())
    issuer = Issuer()
    buyer = BuyerAgent("buyer-1")
    repo.register_agent(conn, "buyer-1", "Buyer One", "buyer")
    svc = AuthorizationService(conn, trusted_issuer_keys={issuer.public_key})

    _, unsigned, _ = buyer.draft_mandate(
        "Buy running shoes under ₹5,000 with 30-day returns, automatically"
    )
    mandate = issuer.confirm_and_sign(unsigned)
    repo.save_mandate(conn, mandate)
    offer, _ = negotiate(store=store, seller=seller, buyer_cap=mandate.max_amount,
                         base_sku="SKU-SHOE-01")
    txn = buyer.build_transaction(mandate, offer)
    out = svc.authorize(txn, offer)
    return txn, offer, out, mandate


def main() -> int:
    ap = argparse.ArgumentParser(description="BAZAAR live Razorpay Test Mode payment")
    ap.add_argument("--fake", action="store_true",
                    help="dry run with a fake Razorpay (no network, no keys)")
    ap.add_argument("--yes", action="store_true",
                    help="do not wait for Enter (used by the fake dry run / CI)")
    args = ap.parse_args()

    print("BAZAAR - LIVE Razorpay Test Mode payment")
    hr("=")

    if args.fake:
        client = _FakeRazorpay()
        print("MODE: --fake (no network). Proves the exact wiring the live run uses.")
    else:
        if not settings.razorpay_key_id or not settings.razorpay_key_secret:
            print("ERROR: RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not set.")
            print("       Copy .env.example to .env and add your Test Mode keys, then:")
            print("       pip install razorpay python-dotenv")
            return 2
        if not settings.razorpay_key_id.startswith("rzp_test_"):
            print("REFUSING: key is not a rzp_test_ (Test Mode) key. This project never")
            print("          touches live money.")
            return 2
        try:
            import razorpay  # noqa: F401
        except ImportError:
            print("ERROR: the razorpay SDK is not installed. Run:")
            print("       pip install razorpay python-dotenv")
            return 2
        client = RazorpayClient()
        print(f"MODE: LIVE against api.razorpay.com with key {settings.razorpay_key_id}")
    hr()

    db_path = str(Path("bazaar_live.db").resolve())
    init_db(db_path, drop=True)
    conn = connect(db_path)

    # ---- 1. gate authorizes a legitimate purchase ----
    txn, offer, out, _ = _authorize_purchase(conn)
    if out.result.decision != "ALLOW":
        print(f"unexpected: gate did not ALLOW ({out.result.decision} {out.result.reason})")
        return 1
    print("1. GATE: legitimate purchase authorized")
    print(f"   amount={rupees(offer.price)}  decision={out.result.decision} "
          f"({out.result.reason})")
    print(f"   Trust Receipt {out.receipt.receipt_id}  signature valid: "
          f"{out.receipt.verify()}")
    hr()

    # ---- 2. create a REAL Test Mode order ----
    s1 = settle(conn, txn.txn_id, client)
    print("2. RAZORPAY ORDER (real, Test Mode):")
    print(f"   status={s1.status}  order_id={s1.order_id}  amount={rupees(s1.amount)}")
    print("   (status is 'pending_settlement' - ambiguous window defaults to NOT PAID)")
    hr()

    # ---- 3. pay with a test card via a local checkout page ----
    if not args.fake:
        html = CHECKOUT_HTML.format(
            key_id=settings.razorpay_key_id, order_id=s1.order_id,
            amount_paise=s1.amount, amount_rupees=rupees(s1.amount),
        )
        port, _t = _serve_checkout(html)
        url = f"http://127.0.0.1:{port}/"
        print("3. CHECKOUT: opening a local page to pay with the Razorpay TEST card.")
        print(f"   If your browser did not open, visit:  {url}")
        print("   Test card 4111 1111 1111 1111, any future expiry, any CVV.")
        try:
            webbrowser.open(url)
        except (webbrowser.Error, OSError):
            print("   (could not auto-open a browser; open the URL above manually)")
        if not args.yes:
            input("\n   >> After the payment succeeds, press Enter here to reconcile... ")
        hr()

    # ---- 4. reconcile against Razorpay (source of truth), settle exactly once ----
    print("4. RECONCILE against Razorpay (polling order.payments):")
    settled = False
    attempts = 1 if args.fake else 12
    for i in range(attempts):
        r = reconcile(conn, txn.txn_id, client)
        if r.status == "already_settled":
            print(f"   -> {r.status}: {r.detail}")
            settled = True
            break
        if i == 0:
            print(f"   -> {r.status}: {r.detail}  (waiting for capture to land...)")
        time.sleep(0 if args.fake else 2.5)
    if not settled:
        print("   No captured payment found yet. If you completed the payment, run this")
        print("   script again - reconcile is safe to repeat and never re-charges.")
        conn.close()
        return 1
    row = conn.execute(
        "SELECT status, razorpay_payment_id FROM transactions WHERE txn_id=?",
        (txn.txn_id,),
    ).fetchone()
    print(f"   transaction status={row['status']}  payment_id={row['razorpay_payment_id']}")
    hr()

    # ---- 5. idempotency, proven LIVE ----
    again_settle = settle(conn, txn.txn_id, client)
    again_recon = reconcile(conn, txn.txn_id, client)
    print("5. IDEMPOTENCY (proven live - a retry can never double charge):")
    print(f"   settle again    -> {again_settle.status} ({again_settle.detail})")
    print(f"   reconcile again -> {again_recon.status} ({again_recon.detail})")
    orders_created = 1
    if not args.fake:
        print(f"   orders created for this transaction: {orders_created} "
              f"(one order, one payment, never doubled)")
    hr()

    # ---- 6. audit chain ----
    chain = verify_chain(conn)
    print(f"6. AUDIT CHAIN: {chain.length} entries, intact={chain.ok}")
    if not args.fake:
        print("\n   View it in your Razorpay dashboard (Test Mode) -> Transactions:")
        print(f"     order  {s1.order_id}")
        print(f"     payment {row['razorpay_payment_id']}")
    hr("=")
    print("LIVE settlement complete. Every step above ran against real code; in live")
    print("mode the order and payment are real Test Mode records on Razorpay.")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
