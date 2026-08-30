# The two moments that win it

Two takes, rehearsed until they are flawless: **one real payment** on Razorpay
Test Mode, and **one attack** that the gate refuses in front of the judge. Record
each once, clean. Everything below is real, reproducible, and already on your
machine.

## Prep (once, before you hit record)

```bash
make setup                 # venv + install + init db  (if not done)
make train                 # writes the risk artifact + eval plots
make benchmark             # fills the scoreboard the Results tab reads
make web-build             # rebuild the console after the latest changes
```

Put your Razorpay **Test Mode** keys (`rzp_test_...`) in `.env` for the payment.

---

## Moment 1 - the live payment (terminal)

One command, one clean take. The terminal cannot glitch on camera, so this is the
safest place to prove a real Razorpay Test Mode payment settles exactly once.

```bash
make live
```

What the screen does, in six acts (say the line, let the act land):

1. **AUTHORIZE** - the gate runs first. `ALLOW`, 11/11 checks, a signed receipt.
   *"Before any money moves, a deterministic gate authorizes the purchase."*
2. **CREATE ORDER** - a real Test Mode order appears on `api.razorpay.com`, and its
   status is **NOT PAID**. *"A real order. And notice it defaults to not paid."*
3. **PAY** - a clean Razorpay-branded page opens. Pay with test card
   `4111 1111 1111 1111`, any future expiry, any CVV. Return to the terminal, press Enter.
4. **SETTLE** - it reconciles from Razorpay itself and flips to **SETTLED**, exactly once.
   *"It settles against Razorpay as the source of truth."*
5. **TRY TO DOUBLE-CHARGE** - a retry is **refused**. *"A retry can never charge twice."*
6. **PROOF** - the audit chain is intact and the receipt signature is valid.

Close on the banner: **SETTLED ONCE. NEVER TWICE.** It prints the `order_...` and
`pay_...` ids, and writes a redacted receipt to `docs/evidence/live_payment_result.json`
automatically (public `rzp_test_` id only, never a secret). That JSON is your evidence.

> If the network wobbles mid-take, `make live` is safe to re-run - reconcile never
> re-charges. Record this clip in advance so the settlement moment is always safe.

---

## Moment 2 - the attack the gate refuses (console)

This is the climax. Run the console, then attack it live and watch each attack march
through the 11 checks and hit the wall in red, with a machine-readable reason code.

```bash
make run     # backend on :8000   (terminal 1)
make web     # console on :5173   (terminal 2)  ->  open http://localhost:5173
```

Stay on the **Console** tab. Fire these in order (each is one click under
*Red-team - direct rail*), and let the checks cascade and the failing one land red:

1. **Budget** - spend above the cap. Blocks at check 9: `MANDATE_LIMIT_EXCEEDED`.
   *"It tries to spend more than it is allowed. Refused at the cap."*
2. **Replay** - reuse a spent nonce. `NONCE_REPLAY`. *"It replays a used payment. Refused."*
3. **Prompt injection** - a money value smuggled through catalog text.
   `UNTRUSTED_INSTRUCTION`. *"Even a prompt-injection attack cannot move the price."*
4. **Policy forgery** (end on this) - the agent mints its **own** mandate with a
   **doubled cap**, signed with its **own** key. Blocks at the trusted-issuer check:
   `MANDATE_IMMUTABLE`. *"This is the whole thesis. The agent tries to rewrite its own
   spending limit, and the forgery is caught. An agent cannot escalate its own authority."*

Then, if you want the protocol angle, switch to the AP2 rail and click
**Signature tamper**: one byte of the ES256 signature is flipped, and it is rejected
at AP2 verification, **before** the gate is ever reached.

Every refusal writes a line to the hash-chained **Audit log** on the right, and a
signed **Trust Receipt** is issued for every decision. Nothing here is mocked; each
click hits the real backend.

---

## Close (either take)

> **Don't trust the agent. Test the authorization boundary.** Intelligence proposes;
> a fixed, cryptographic verifier decides. That is BAZAAR.
