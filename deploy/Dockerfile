# BAZAAR - one container that serves BOTH the console and its API at a single
# URL. No secrets needed: the interactive demo (gate, attacks, benchmark) runs
# without Razorpay keys. Build context is the repo root:
#   docker build -f deploy/Dockerfile -t bazaar .

# ---- stage 1: build the React + TypeScript console ----
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- stage 2: FastAPI backend that also serves the built console ----
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 BAZAAR_WEB_DIST=/app/frontend_dist

# pynacl / cryptography / scikit-learn ship manylinux wheels, so slim is enough.
COPY backend/ ./backend/
COPY benchmarks/ ./benchmarks/
COPY scripts/ ./scripts/
RUN pip install -e ./backend

# Precompute the honest scoreboard at build time so the Results tab serves real,
# reproduced numbers (the trained risk-model artifact is already in the repo).
RUN python benchmarks/runner.py || true

# Bring in the console built in stage 1.
COPY --from=web /web/dist ./frontend_dist

EXPOSE 8000
# Render / Railway inject $PORT; default to 8000 for a local `docker run`.
CMD ["sh", "-c", "python -m uvicorn bazaar.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
