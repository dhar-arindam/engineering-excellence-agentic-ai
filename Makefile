# Engineering Intelligence Platform — Makefile
#
# Targets
# -------
#   make dev             Start backend + frontend in dev mode
#   make test            Run the full Python test suite
#   make lint            Run ruff linter on backend
#   make export-openapi  Export versioned OpenAPI JSON to ui/src/generated/
#   make gen-types       Generate TypeScript types from v2 schema
#   make gen-client      Generate full typed API client from v2 schema
#   make docker-up       Build and start all Docker Compose services
#   make docker-down     Stop all services
#   make migrate         Run Alembic migrations (requires running Postgres)

PYTHON   ?= python
BACKEND  := backend
UI       := ui

.PHONY: dev test lint export-openapi gen-types gen-client docker-up docker-down migrate help

# ── Development ─────────────────────────────────────────────────────────────

dev:
	@echo "Starting backend (uvicorn) and frontend (next dev) in parallel..."
	@$(MAKE) -j2 _dev-backend _dev-frontend

_dev-backend:
	cd $(BACKEND) && uvicorn app.main:app --reload --port 8000

_dev-frontend:
	cd $(UI) && npm run dev

# ── Testing ──────────────────────────────────────────────────────────────────

test:
	cd $(BACKEND) && $(PYTHON) -m pytest tests/ -q

test-verbose:
	cd $(BACKEND) && $(PYTHON) -m pytest tests/ -v

# ── Linting ──────────────────────────────────────────────────────────────────

lint:
	cd $(BACKEND) && $(PYTHON) -m ruff check app/ tests/

lint-fix:
	cd $(BACKEND) && $(PYTHON) -m ruff check --fix app/ tests/

# ── OpenAPI export ───────────────────────────────────────────────────────────

export-openapi:
	@echo "Exporting OpenAPI schemas to ui/src/generated/..."
	$(PYTHON) $(BACKEND)/scripts/export_openapi.py

# ── TypeScript type generation ───────────────────────────────────────────────
# Requires: npm install -D openapi-typescript  (run once in ui/)

gen-types: export-openapi
	@echo "Generating TypeScript types from OpenAPI v2 schema..."
	cd $(UI) && npx openapi-typescript src/generated/openapi-v2.json \
	    --output src/generated/api-types.ts
	@echo "✅  TypeScript types written to ui/src/generated/api-types.ts"

# ── Typed API client generation ──────────────────────────────────────────────
# Requires: npm install -D openapi-typescript-codegen  (run once in ui/)

gen-client: export-openapi
	@echo "Generating typed API client from OpenAPI v2 schema..."
	cd $(UI) && npx openapi-typescript-codegen \
	    --input  src/generated/openapi-v2.json \
	    --output src/generated/api-client \
	    --client fetch \
	    --useOptions \
	    --useUnionTypes
	@echo "✅  API client written to ui/src/generated/api-client/"

# ── Docker ───────────────────────────────────────────────────────────────────

docker-up:
	docker compose up --build

docker-up-infra:
	docker compose up postgres redis -d

docker-down:
	docker compose down

docker-scale-workers:
	docker compose up --scale worker=4

# ── Database ─────────────────────────────────────────────────────────────────

migrate:
	cd $(BACKEND) && alembic upgrade head

migrate-new:
	@read -p "Migration message: " msg; \
	cd $(BACKEND) && alembic revision --autogenerate -m "$$msg"

# ── Help ──────────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "Engineering Intelligence Platform — available targets:"
	@echo ""
	@echo "  dev              Start backend + frontend (dev mode)"
	@echo "  test             Run Python test suite"
	@echo "  lint             Lint backend with ruff"
	@echo "  export-openapi   Export OpenAPI JSON to ui/src/generated/"
	@echo "  gen-types        Generate TypeScript types  (needs openapi-typescript)"
	@echo "  gen-client       Generate typed API client  (needs openapi-typescript-codegen)"
	@echo "  docker-up        Build and start all services"
	@echo "  docker-down      Stop all services"
	@echo "  migrate          Run Alembic migrations"
	@echo ""
