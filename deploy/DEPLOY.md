# Deploy BAZAAR live (one URL, no secrets)

The whole app - the console **and** its API - runs from a **single** Docker
service, so there is nothing to wire together after it deploys. No Razorpay keys
are needed: the interactive demo (the deterministic gate, the nine attacks, and
the benchmark) runs without them.

## Render (free, one click)

1. Push this repo to GitHub.
2. Create a free account at https://render.com and connect your GitHub.
3. Click **New +** -> **Blueprint**, pick this repo, and click **Apply**.
   Render reads `render.yaml` (at the repo root) and builds one web service
   named `bazaar`.
4. Wait for the build (about 5 minutes). When it is live, open the service URL
   (for example `https://bazaar.onrender.com`) - it serves the full console.

There are **no environment variables to set**. The health check is `/api/health`.

### Alternative: a plain Web Service (no blueprint)

**New +** -> **Web Service** -> pick this repo -> **Runtime: Docker** ->
Dockerfile path `deploy/Dockerfile` -> Instance type **Free** -> **Create**.

## Notes

- **The free tier sleeps** after about 15 minutes idle; the first request then
  takes ~30-60 seconds to wake it. Open the URL once to warm it up before a demo.
- **Run it locally the same way:**
  `docker build -f deploy/Dockerfile -t bazaar . && docker run -p 8000:8000 bazaar`,
  then open http://localhost:8000.
- The real live payment (`make live`) is a separate local step that needs your
  own `rzp_test_` keys; it is intentionally not part of the hosted demo, so the
  deployed site never touches money or secrets.
