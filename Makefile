# BAZAAR - one Makefile drives the whole project.
#   make setup      create venv, install backend, initialize the database
#   make test       run the full test suite (unit + property + security + integration)
#   make fuzz       run the property-based fuzzer against the spend-cap invariant
#   make benchmark  regenerate datasets, run gate + fuzzer, print the scoreboard
#   make run        start the FastAPI backend
#   make demo       run the scripted end-to-end demo
#   make showcase   cinematic one-command demo (for the video)
#   make live       LIVE Razorpay Test Mode payment (needs .env test keys)
#   make lint       ruff
#   make clean      remove venv, db, caches

SHELL := /bin/bash
VENV  := .venv
PY    := $(VENV)/Scripts/python.exe
PIP   := $(VENV)/Scripts/pip.exe

.DEFAULT_GOAL := help

.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

$(VENV)/Scripts/python.exe:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip >/dev/null

.PHONY: setup
setup: $(VENV)/Scripts/python.exe ## Create venv, install backend + dev deps, init the database
	$(PIP) install -e "backend[dev]"
	$(PY) scripts/init_db.py
	@echo ""
	@echo "✓ setup complete. Try:  make test"

.PHONY: db
db: ## (Re)initialize the SQLite database from the schema
	$(PY) scripts/init_db.py

.PHONY: test
test: ## Run the full test suite
	$(PY) -m pytest -q

.PHONY: test-property
test-property: ## Run only the property-based tests
	$(PY) -m pytest -q tests/property

.PHONY: fuzz
fuzz: ## Run the spend-cap fuzzer and print the REAL violation count
	$(PY) -m bazaar.redteam.fuzz_cli

.PHONY: benchmark
benchmark: ## Regenerate datasets, run gate + fuzzer, print the scoreboard
	$(PY) benchmarks/runner.py

.PHONY: train
train: ## Train + evaluate the calibrated risk brain
	$(PY) scripts/train_risk.py

.PHONY: ap2
ap2: ## AP2 rail conformance demo (real ES256 Cart Mandates)
	$(PY) scripts/ap2_demo.py

.PHONY: run
run: ## Start the FastAPI backend on :8000
	$(PY) -m uvicorn bazaar.api.app:app --reload --port 8000

.PHONY: web-install
web-install: ## Install frontend dependencies
	cd frontend && npm install

.PHONY: web
web: ## Start the frontend dev server on :5173 (proxies /api -> :8000)
	cd frontend && npm run dev

.PHONY: web-build
web-build: ## Type-check and build the frontend
	cd frontend && npm run build

.PHONY: demo
demo: ## Run the scripted end-to-end demo (no Razorpay network needed)
	$(PY) scripts/demo.py

.PHONY: showcase
showcase: ## Cinematic one-command demo for the video (drives the real backend)
	$(PY) scripts/showcase.py --pace 0.6

.PHONY: live
live: ## LIVE Razorpay Test Mode payment (needs .env test keys). Dry run: make live-fake
	$(PY) scripts/live_razorpay.py

.PHONY: live-fake
live-fake: ## Dry run of the live settlement flow (no network, no keys)
	$(PY) scripts/live_razorpay.py --fake --yes

.PHONY: verify
verify: ## Phase 3 checkpoint: receipt verify/tamper + audit-chain verify/tamper
	$(PY) scripts/verify_chain.py

.PHONY: lint
lint: ## Lint the backend with ruff
	$(VENV)/Scripts/ruff.exe check backend

.PHONY: clean
clean: ## Remove venv, database, and caches
	rm -rf $(VENV) bazaar.db benchmarks/out
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '.pytest_cache' -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "✓ cleaned"
