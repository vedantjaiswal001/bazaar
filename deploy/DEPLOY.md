# Deploy BAZAAR (a clickable URL for judges)

Two moving parts: a **FastAPI backend** and a **static React console**. CORS is
already open (`allow_origins=["*"]`), and the frontend reads `VITE_API_BASE`, so
the two can live on different hosts. Pick one path.

---

## Option A - Render for both (one blueprint, free)

1. Push this repo to GitHub.
2. Render dashboard -> **New -> Blueprint** -> select this repo. It reads
   [`deploy/render.yaml`](render.yaml) and creates two services:
   `bazaar-api` (Docker) and `bazaar-web` (static).
3. Wait for **bazaar-api** to go live; copy its URL (e.g.
   `https://bazaar-api.onrender.com`). Check `.../api/health` returns `{"status":"ok"}`.
4. Open **bazaar-web -> Environment**, set `VITE_API_BASE` to that API URL, and
   **Manual Deploy -> Clear build cache & deploy**.
5. Open the **bazaar-web** URL - that is your judge link.

> Free Render instances sleep when idle; the first request after a nap takes
> ~30s to wake. Hit the API URL once before you demo.

---

## Option B - Vercel (frontend) + Render or Railway (backend)

**Backend** (Render): New -> **Web Service** -> this repo -> Runtime **Docker**,
Dockerfile `deploy/Dockerfile`, context `.`. Deploy; note the URL.
*(Railway/Fly work too - any Docker host. Start command is baked into the image.)*

**Frontend** (Vercel): New Project -> this repo -> **Root Directory = `frontend`**
(Vercel auto-detects Vite). Add an env var **`VITE_API_BASE`** = your backend URL.
Deploy. The Vercel URL is your judge link.

---

## Local Docker (optional sanity check)

```bash
docker build -f deploy/Dockerfile -t bazaar-api .
docker run -p 8000:8000 bazaar-api            # http://localhost:8000/api/health
# then run the UI against it:
cd frontend && VITE_API_BASE=http://localhost:8000 npm run dev
```

## Notes

- **Live Razorpay settlement** is intentionally *not* wired into the public demo -
  it needs your `rzp_test_` keys and an interactive test-card payment. Keep that as
  the `make live` moment in your video, run locally. The public demo shows the
  gate, the AP2 rail, the risk brain and the audit trail - all the safety story -
  with settlement reported as `pending` (honest, not faked).
- The backend recomputes its benchmark scoreboard at build time, so the deployed
  **Results** tab shows real, reproduced numbers.
