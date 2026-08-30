# Live settlement - evidence

The one claim that cannot be reproduced from this repo alone is the **real
Razorpay Test Mode payment** (it needs your own `rzp_test_` credentials and an
interactive test-card payment). This folder is where you capture reproducible
proof of it. No real money moves - the client refuses any key that is not
`rzp_test_`.

## Reproduce it yourself

```bash
cp .env.example .env         # then add your RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET (test mode)
make live
```

`make live` runs the full flow: the gate **authorizes** → a **real** Test Mode
`order_...` is created on `api.razorpay.com` (status defaults to NOT PAID) → you
pay with Razorpay's **test card `4111 1111 1111 1111`** → `reconcile` settles it
**exactly once** → a repeated `settle`/`reconcile` **refuses to double-charge**.

## What to capture (record before you submit)

1. **Screen recording** of the whole flow - the authorization, the created order,
   the checkout, the captured payment, and the "already settled / no double
   charge" retry. Host this with your submission video; **do not commit the raw
   `.mp4`** (it is git-ignored here).
2. **`live_payment_result.json`** - the printed settlement result, **redacted**:
   keep `order_id`, `payment_id`, `amount`, `currency`, `status`, timestamps, and
   the **public** `key_id` (the `rzp_test_...` id only). Template:

   ```json
   {
     "order_id": "order_XXXXXXXXXXXXXX",
     "payment_id": "pay_XXXXXXXXXXXXXX",
     "amount": 449900,
     "currency": "INR",
     "status": "settled",
     "captured": true,
     "double_charge_attempt": "refused (already settled)",
     "key_id": "rzp_test_XXXXXXXXXXXX",
     "settled_at": "2026-08-DDT..Z"
   }
   ```
3. **`live_payment.png`** - a screenshot of the settled state (optional), redacted.

## Redaction - never commit these

- `RAZORPAY_KEY_SECRET`, the webhook secret, or any full `Authorization` header.
- `.env` itself (already git-ignored at the repo root).

Test-mode `order_`/`pay_` ids are low-risk, but mask a few middle characters if
you prefer. The screen recording is the strongest single piece of proof - the
JSON is the machine-readable backup.
