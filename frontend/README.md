# BAZAAR - Frontend

Six demo screens (React + TypeScript + Vite) over the BAZAAR API. Functional and
clean, not flashy - every screen drives the real backend, nothing is mocked.

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

## Screens

1. **Intent** - natural language → a confirmable mandate (human confirms before signing).
2. **Transaction** - bounded negotiation inside the two walls (cap + floor) → gate decision.
3. **Verifier** - the fixed checklist, pass/fail per check, with the reason code.
4. **Trust Receipt** - verify a signed receipt; tamper one field and watch it fail.
5. **Red Team** - fire any of the nine attack classes live; each returns its reason code.
6. **Benchmark** - the scoreboard from `make benchmark` (four numbers + per class + revenue).
