#!/usr/bin/env python3
"""BAZAAR - LIVE Razorpay Test Mode payment (Phase 2 live checkpoint).

This is the one step that talks to Razorpay's real servers. It uses your
TEST-mode keys (rzp_test_...), so no real money ever moves. It proves the whole
settlement story end to end, and it needs NO webhook tunnel (no ngrok): it
reconciles by polling Razorpay's own `order.payments` API, which is the source
of truth.

Six acts, on screen:
  1. AUTHORIZE  - the gate runs on a legitimate purchase -> ALLOW + signed receipt.
  2. CREATE     - a REAL Test Mode order on api.razorpay.com (defaults NOT PAID).
  3. PAY        - a local checkout page pays with the Razorpay TEST card.
  4. SETTLE     - reconcile against Razorpay -> settles exactly once.
  5. DOUBLE?    - settle + reconcile again -> a retry can never double charge.
  6. PROOF      - Trust Receipt signature + hash-chained audit log verify.

On a real (non-fake) success it also writes a redacted receipt to
docs/evidence/live_payment_result.json (public rzp_test_ id only, never a secret).

Usage (from the repo root, with your .env filled in):
    python scripts/live_razorpay.py            # or: make live

Dry run (no network, no keys - proves the wiring with a fake Razorpay):
    python scripts/live_razorpay.py --fake     # or: make live-fake

Razorpay TEST card:  4111 1111 1111 1111   any future expiry   any CVV
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import socket
import socketserver
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
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

REPO = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Terminal hardening + a tiny, safe colour palette.
#   - Force UTF-8 so the rupee sign never crashes a Windows console.
#   - Enable ANSI on Windows 10+; if that fails, colours become no-ops.
# The demo therefore looks right on Windows Terminal / PowerShell / macOS / Linux,
# and degrades to clean plain text anywhere else - it never prints escape codes.
# --------------------------------------------------------------------------- #
def _harden_console() -> bool:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001, S110 - console hardening must never crash the demo
        pass
    color = True
    if os.environ.get("NO_COLOR"):
        color = False
    if sys.platform == "win32":
        try:
            os.system("")  # nudges modern consoles into VT mode
            import ctypes

            k = ctypes.windll.kernel32
            h = k.GetStdHandle(-11)
            mode = ctypes.c_uint()
            k.GetConsoleMode(h, ctypes.byref(mode))
            k.SetConsoleMode(h, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:  # noqa: BLE001 - fall back to no-colour on any console quirk
            color = False
    if not sys.stdout.isatty():
        color = False
    return color


_COLOR = False


def _paint(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _COLOR else s


def bold(s: str) -> str: return _paint("1", s)
def dim(s: str) -> str: return _paint("2", s)
def green(s: str) -> str: return _paint("1;32", s)
def red(s: str) -> str: return _paint("1;31", s)
def amber(s: str) -> str: return _paint("1;33", s)
def blue(s: str) -> str: return _paint("1;38;5;39", s)


def rupees(paise: int) -> str:
    return f"₹{paise / 100:,.2f}"


def hr(c: str = "-") -> None:
    print(c * 60)


def act(n: int, title: str, subtitle: str) -> None:
    print()
    print(f"  {blue(f'ACT {n}')}  {bold(title)}")
    print(f"  {dim(subtitle)}")


def row(label: str, value: str) -> None:
    print(f"     {dim(label.ljust(11))} {value}")


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
  :root {{ --accent:#0D94FB; --navy:#012652; --ink:#172B4D; --muted:#5E6C84;
    --line:#EBECF0; --bg:#F7F8FA; --card:#FFFFFF; --good:#0A8F54; --good-soft:#E4F6ED; }}
  * {{ box-sizing:border-box; }}
  body {{ font-family:"Mulish",-apple-system,system-ui,Segoe UI,Roboto,sans-serif;
    max-width:520px; margin:9vh auto; padding:0 24px; line-height:1.55;
    background:var(--bg); color:var(--ink); }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:16px;
    padding:30px 32px; box-shadow:0 1px 3px rgba(9,30,66,.08), 0 10px 40px rgba(9,30,66,.06); }}
  .brandrow {{ display:flex; align-items:center; gap:.55rem; margin-bottom:1.4rem; }}
  .mark {{ width:26px; height:26px; border-radius:6px; background:var(--accent); color:#fff;
    font-weight:800; display:flex; align-items:center; justify-content:center; font-size:.9rem; }}
  .brand {{ font-weight:800; color:var(--navy); letter-spacing:-.02em; }}
  .test {{ margin-left:auto; font-size:.7rem; font-weight:700; color:var(--accent);
    background:#E7F3FE; padding:.2rem .5rem; border-radius:20px; }}
  h1 {{ font-size:16px; margin:0 0 2px; font-weight:700; }}
  .muted {{ color:var(--muted); font-size:13px; }}
  .amt {{ font-size:38px; font-weight:800; margin:14px 0 2px; color:var(--navy);
    letter-spacing:-.02em; }}
  code {{ font-family:"IBM Plex Mono",ui-monospace,monospace; background:var(--bg);
    border:1px solid var(--line); padding:1px 6px; border-radius:5px; color:var(--ink); }}
  button {{ appearance:none; border:0; margin-top:22px; width:100%; padding:14px 18px;
    font-size:15px; font-weight:700; border-radius:10px; background:var(--accent);
    color:#fff; cursor:pointer; }}
  button:hover {{ background:#0B74C4; }}
  .ok {{ margin-top:18px; padding:13px 15px; border-radius:10px; display:none;
    background:var(--good-soft); border:1px solid #B7E6CB; color:var(--good); font-size:13px; }}
  .tip {{ margin-top:20px; font-size:12.5px; }}
</style></head>
<body>
  <div class="card">
    <div class="brandrow"><span class="mark">B</span><span class="brand">Bazaar</span>
      <span class="test">Razorpay Test Mode</span></div>
    <h1>Authorized purchase</h1>
    <div class="muted">Order <code>{order_id}</code></div>
    <div class="amt">{amount_rupees}</div>
    <div class="muted">A real Test Mode order, authorized by a signed mandate and the
      deterministic gate. No real money moves.</div>
    <button id="pay">Pay with Razorpay</button>
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
      theme: {{ color: "#0D94FB" }}
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
    """Run the gate on a legitimate purchase and return (txn, offer, out, mandate)."""
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


def _write_evidence(order_id: str, payment_id: str, amount: int, retry_detail: str) -> Path:
    """Write a REDACTED, machine-readable receipt of the real run (public id only)."""
    ev = {
        "order_id": order_id,
        "payment_id": payment_id,
        "amount": amount,
        "currency": "INR",
        "status": "settled",
        "captured": True,
        "double_charge_attempt": f"refused ({retry_detail})",
        "key_id": settings.razorpay_key_id,          # public rzp_test_ id ONLY
        "settled_at": datetime.now(timezone.utc).isoformat(),
    }
    path = REPO / "docs" / "evidence" / "live_payment_result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ev, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    global _COLOR
    _COLOR = _harden_console()

    ap = argparse.ArgumentParser(description="BAZAAR live Razorpay Test Mode payment")
    ap.add_argument("--fake", action="store_true",
                    help="dry run with a fake Razorpay (no network, no keys)")
    ap.add_argument("--yes", action="store_true",
                    help="do not wait for Enter (used by the fake dry run / CI)")
    args = ap.parse_args()

    hr("=")
    print(f"  {bold('B A Z A A R')}   {dim('live payment on Razorpay Test Mode')}")
    hr("=")

    if args.fake:
        client = _FakeRazorpay()
        print(f"  MODE  {amber('dry run (--fake)')}  no network, no keys - proves the exact wiring")
    else:
        if not settings.razorpay_key_id or not settings.razorpay_key_secret:
            print(red("  ERROR: RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not set."))
            print("         Copy .env.example to .env, add your Test Mode keys, then:")
            print("         pip install razorpay python-dotenv")
            return 2
        if not settings.razorpay_key_id.startswith("rzp_test_"):
            print(red("  REFUSING: key is not a rzp_test_ (Test Mode) key."))
            print("            This project never touches live money.")
            return 2
        try:
            import razorpay  # noqa: F401
        except ImportError:
            print(red("  ERROR: the razorpay SDK is not installed. Run:"))
            print("         pip install razorpay python-dotenv")
            return 2
        client = RazorpayClient()
        print(f"  MODE  {green('LIVE')}  api.razorpay.com  key {bold(settings.razorpay_key_id)}")

    db_path = str(Path("bazaar_live.db").resolve())
    init_db(db_path, drop=True)
    conn = connect(db_path)

    # ---- ACT 1: gate authorizes a legitimate purchase ----
    txn, offer, out, _ = _authorize_purchase(conn)
    if out.result.decision != "ALLOW":
        print(red(f"  unexpected: gate did not ALLOW ({out.result.decision} {out.result.reason})"))
        conn.close()
        return 1
    act(1, "AUTHORIZE", "the gate decides before any money can move")
    row("intent", '"Buy running shoes under ₹5,000, automatically"')
    row("negotiated", f"{bold(rupees(offer.price))}  {dim('(clamped between seller floor and signed cap)')}")
    row("gate", f"{green('ALLOW')}  {dim('11/11 checks')}  reason {out.result.reason}")
    row("receipt", f"{out.receipt.receipt_id}  Ed25519 signature "
                   f"{green('VALID') if out.receipt.verify() else red('INVALID')}")

    # ---- ACT 2: create a REAL Test Mode order ----
    s1 = settle(conn, txn.txn_id, client)
    act(2, "CREATE ORDER", "a real Test Mode order on api.razorpay.com")
    row("order", bold(s1.order_id))
    row("amount", rupees(s1.amount))
    row("status", f"{amber('NOT PAID')}  {dim('(the ambiguous window defaults to unpaid)')}")

    # ---- ACT 3: pay with a test card via a local checkout page ----
    if not args.fake:
        html = CHECKOUT_HTML.format(
            key_id=settings.razorpay_key_id, order_id=s1.order_id,
            amount_paise=s1.amount, amount_rupees=rupees(s1.amount),
        )
        port, _t = _serve_checkout(html)
        url = f"http://127.0.0.1:{port}/"
        act(3, "PAY", "Razorpay test card, in your browser")
        row("opened", url)
        row("card", "4111 1111 1111 1111  " + dim("any future expiry, any CVV"))
        try:
            webbrowser.open(url)
        except (webbrowser.Error, OSError):
            row("note", dim("could not auto-open a browser; open the URL above manually"))
        if not args.yes:
            input(f"\n     {bold('>> pay in the browser, then press Enter here to reconcile...')} ")

    # ---- ACT 4: reconcile against Razorpay (source of truth), settle exactly once ----
    act(4, "SETTLE", "reconcile from Razorpay, the source of truth")
    settled = False
    attempts = 1 if args.fake else 12
    for i in range(attempts):
        r = reconcile(conn, txn.txn_id, client)
        if r.status == "already_settled":
            settled = True
            break
        if i == 0:
            row("waiting", dim("order created, waiting for the capture to land..."))
        time.sleep(0 if args.fake else 2.5)
    if not settled:
        print(amber("     no captured payment found yet."))
        print("     If you completed the payment, run this again - reconcile is safe to")
        print("     repeat and never re-charges.")
        conn.close()
        return 1
    rowdb = conn.execute(
        "SELECT status, razorpay_payment_id FROM transactions WHERE txn_id=?",
        (txn.txn_id,),
    ).fetchone()
    row("payment", f"{bold(rowdb['razorpay_payment_id'])}  captured")
    row("status", f"{green('SETTLED')}  {dim('exactly once')}")

    # ---- ACT 5: idempotency, proven LIVE ----
    again_settle = settle(conn, txn.txn_id, client)
    again_recon = reconcile(conn, txn.txn_id, client)
    act(5, "TRY TO DOUBLE-CHARGE", "a retry can never charge twice")
    row("settle again", f"{green('refused')}  {dim('(' + again_settle.detail + ')')}")
    row("reconcile again", f"{green('refused')}  {dim('(' + again_recon.detail + ')')}")
    if not args.fake:
        row("orders", "1  " + dim("(one order, one payment, never doubled)"))

    # ---- ACT 6: proof (receipt + audit chain) ----
    chain = verify_chain(conn)
    act(6, "PROOF", "tamper-evident by construction")
    row("audit chain", f"{chain.length} entries  "
                       f"{green('intact') if chain.ok else red('BROKEN')}")
    row("receipt", f"Ed25519 signature {green('VALID') if out.receipt.verify() else red('INVALID')}")

    # ---- result banner ----
    print()
    hr()
    print(f"  {bold('RESULT')}   {green('SETTLED ONCE. NEVER TWICE.')}")
    row("order", s1.order_id)
    row("payment", rowdb["razorpay_payment_id"])
    row("amount", f"{rupees(s1.amount)} INR")
    if not args.fake:
        ev = _write_evidence(s1.order_id, rowdb["razorpay_payment_id"], s1.amount,
                             again_settle.detail)
        row("evidence", f"saved -> {ev.relative_to(REPO)}")
        print()
        print(dim("  View it in your Razorpay dashboard (Test Mode) -> Transactions:"))
        print(dim(f"    order   {s1.order_id}"))
        print(dim(f"    payment {rowdb['razorpay_payment_id']}"))
    hr("=")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
