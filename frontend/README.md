# BAZAAR - Frontend

A single Razorpay-brand console (React + TypeScript + Vite) over the BAZAAR API.
Functional and clean, not flashy. It drives the real backend, nothing is mocked.

## Run

```bash
# 1. backend (from the repo root)
make run              # FastAPI on http://localhost:8000

# 2. frontend (in another terminal)
make web-install      # first time only
make web              # Vite dev server on http://localhost:5173
```

The dev server proxies `/api` to the backend on `:8000`. For a production build,
set `VITE_API_BASE` to the backend origin and run `make web-build`.

## Two tabs

1. **Console** - pick an AI buyer and watch one transaction resolve end to end.
   Choose a real AP2 signed cart or a red-team attack; the pipeline advances live:
   AP2 authenticity check, then the deterministic 11-check gate resolving pass or
   fail per check with its reason code, a hash-chained audit log streaming, and a
   signed Trust Receipt issuing on ALLOW.
2. **Results** - the live scoreboard read straight from the backend: the advisory
   risk brain (calibrated, tighten-only) with its readable top risk-driver weights,
   the AP2 rail conformance table (1/1 legit, 5/5 tampers), and the bounded-upsell
   revenue line. Every figure is computed by the backend, not hard-coded here.
