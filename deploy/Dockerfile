# BAZAAR backend - FastAPI on uvicorn. Works on Render / Railway / Fly / any
# container host. Build context is the repo root:  docker build -f deploy/Dockerfile .
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY backend/ ./backend/
COPY benchmarks/ ./benchmarks/
COPY scripts/ ./scripts/

# pynacl / cryptography / scikit-learn ship manylinux wheels, so slim is enough.
RUN pip install -e ./backend

# Precompute the honest scoreboard at build time so the deployed Results tab
# serves real, reproduced numbers (the risk-model artifact is already in the repo).
RUN python benchmarks/runner.py || true

EXPOSE 8000
# Render / Railway inject $PORT; default to 8000 for local `docker run`.
CMD ["sh", "-c", "python -m uvicorn bazaar.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
