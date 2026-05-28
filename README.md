# 🤖 AI Multi-Agent Engineering Intelligence Platform

A full-stack monorepo that analyses software repositories using a multi-agent AI pipeline and surfaces engineering health scores, architectural findings, security issues, and actionable recommendations.

```
┌──────────────────────────────────────────────────────────────────┐
│                          Monorepo layout                         │
│                                                                  │
│  ai-multi-agent/                                                 │
│  ├── ui/          Next.js 16 frontend (React 19, Tailwind 4)    │
│  ├── backend/     FastAPI backend + Arq worker                   │
│  ├── docker-compose.yml   All 5 services in one command         │
│  └── .env.example         Single env-var reference              │
└──────────────────────────────────────────────────────────────────┘
```

---

## Architecture

```
Browser
  │
  ▼
┌─────────────┐   HTTP/REST   ┌───────────────────────────────────────────┐
│  Frontend   │◄─────────────►│              FastAPI Backend              │
│  Next.js 16 │               │  /api/review   POST – synchronous review  │
│  :3000      │               │  /api/scans    POST /run – async scan      │
└─────────────┘               │              GET  /{id}/status             │
                               │              POST /{id}/cancel             │
                               │  /api/github  POST /webhook               │
                               └──────────────┬────────────────────────────┘
                                              │ enqueue_job()
                                              ▼
                               ┌─────────────────────────┐
                               │    Redis (Arq queue)     │
                               └────────────┬────────────┘
                                            │ dequeue
                                            ▼
                               ┌─────────────────────────┐
                               │    Arq Worker (×2)       │
                               │  ScanOrchestrator        │
                               │  ├── SourcePreparation   │
                               │  ├── 5 parallel agents   │
                               │  │   ├─ SeniorQA         │
                               │  │   ├─ SeniorDeveloper  │
                               │  │   ├─ SeniorArchitect  │
                               │  │   ├─ SeniorSRE        │
                               │  │   └─ SecurityExpert   │
                               │  └── ScoringEngine       │
                               └────────────┬────────────┘
                                            │
                               ┌────────────▼────────────┐
                               │      PostgreSQL          │
                               │  repositories / scans    │
                               │  scan_agent_results      │
                               │  engineering_reviews     │
                               └─────────────────────────┘
```

---

## Services

| Service | Port | Description |
|---------|------|-------------|
| `frontend` | **3000** | Next.js 16 dashboard — scan trigger, live progress, results |
| `backend` | **8000** | FastAPI REST API + OpenAPI docs at `/docs` |
| `worker` | — | Arq background scan workers (2 replicas by default) |
| `postgres` | 5432 | PostgreSQL 15 — persistent scan and review data |
| `redis` | 6379 | Redis 7 — Arq task queue, per-repo locks, cancellation flags |

---

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) ≥ 24 with Compose v2
- An OpenAI API key (or compatible endpoint)

### 1 — Clone & configure

```bash
git clone https://github.com/your-org/ai-multi-agent.git
cd ai-multi-agent
cp .env.example .env
```

Edit `.env` — the values you **must** change before starting:

```env
OPENAI_API_KEY=sk-...                  # required — AI agents won't work without this
SECRET_KEY=<long-random-string>        # required in production
GITHUB_TOKEN=ghp_...                   # optional — private repos & PR comments
```

Everything else has safe defaults for local development (Postgres, Redis, ports, timeouts).

### 2 — Build and run all services

```bash
docker-compose up --build
```

All five services start together. PostgreSQL and Redis must pass their health checks before the backend and worker come up.

| URL | What you get |
|-----|-------------|
| http://localhost:3000 | React dashboard |
| http://localhost:8000/docs | Interactive API docs (Swagger UI) |
| http://localhost:8000/redoc | ReDoc API reference |

### 3 — Run database migrations

Once the `backend` container is healthy, apply migrations:

```bash
docker-compose exec backend alembic upgrade head
```

> **Tip:** You only need to run migrations once on first start, and again after pulling changes that include new Alembic revision files.

---

## Local Development (without Docker)

### Backend

```bash
cd backend

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Start PostgreSQL + Redis via Docker (infrastructure only)
docker-compose up postgres redis -d

# Copy the backend-specific env template and adjust connection strings
cp backend/.env.example backend/.env
# Set DATABASE_URL and REDIS_URL to point at localhost:
#   DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/ai_multi_agent
#   REDIS_URL=redis://localhost:6379/0
# Also set OPENAI_API_KEY and any other required variables.

# Run migrations
alembic upgrade head

# Start API server
uvicorn app.main:app --reload --port 8000

# Start scan worker (separate terminal, same venv)
python -m arq app.infrastructure.arq_worker.WorkerSettings
```

### Frontend

```bash
cd ui
npm install

# Create local env file from the template
cp .env.example .env.local
# NEXT_PUBLIC_API_URL defaults to http://localhost:8000 — change if your backend runs elsewhere.

npm run dev          # → http://localhost:3000
```

---

## API Reference

### Scan endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/scans/run` | Trigger a new scan (returns immediately with `scan_id`) |
| `GET` | `/api/scans/{scan_id}/status` | Poll scan progress (`0–100 %`) and status |
| `POST` | `/api/scans/{scan_id}/cancel` | Request cancellation |

**POST `/api/scans/run` — request body**

```json
{
  "source_type": "github",
  "repository_url": "https://github.com/owner/repo"
}
```

```json
{
  "source_type": "local",
  "local_path": "/srv/repos/my-service"
}
```

**Response `202`**

```json
{
  "scan_id": "550e8400-e29b-41d4-a716-446655440000",
  "repository_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "status": "queued"
}
```

**GET `/api/scans/{scan_id}/status` — response `200`**

```json
{
  "scan_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "running",
  "progress_percentage": 45,
  "error_message": null
}
```

Possible `status` values: `queued` → `running` → `completed` | `failed` | `cancelled`

### Review endpoints (synchronous)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/review` | Synchronous review (waits for all agents) |
| `GET` | `/api/review/{review_id}` | Full aggregate with all findings |
| `GET` | `/api/review/{review_id}/summary` | Scores-only summary |

### GitHub webhook

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/github/webhook` | Receives `pull_request` events and auto-reviews PRs |

---

## Environment Variables

### Required to set

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI (or compatible) API key — all 5 AI agents use this |
| `SECRET_KEY` | App secret; use a long random string in production |

### Application

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `development` | `development` or `production` |
| `LOG_LEVEL` | `INFO` | Python log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

### Database (PostgreSQL)

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_USER` | `postgres` | PostgreSQL username (Docker Compose) |
| `POSTGRES_PASSWORD` | `postgres` | PostgreSQL password (Docker Compose) |
| `POSTGRES_DB` | `ai_multi_agent` | PostgreSQL database name (Docker Compose) |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@postgres:5432/ai_multi_agent` | Full asyncpg connection string used by FastAPI |

### Redis

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection string (Arq queue + distributed locks) |

### LLM / OpenAI

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_MODEL` | `gpt-4o` | Model name passed to the OpenAI API |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Override to point at a local or proxy model endpoint |
| `LLM_TIMEOUT_SECONDS` | `60` | Per-request timeout for LLM calls |
| `LLM_MAX_RETRIES` | `3` | Number of automatic retries on transient LLM errors |

### GitHub integration

| Variable | Default | Description |
|----------|---------|-------------|
| `GITHUB_TOKEN` | — | PAT for cloning private repos and posting PR review comments |


### Review & scan settings

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_CONCURRENT_AGENTS` | `5` | Max agents running in parallel within a single review/scan |
| `REVIEW_TIMEOUT_SECONDS` | `300` | Timeout for a synchronous `/api/review` request |
| `SCAN_MAX_CONCURRENT` | `3` | Max parallel scan jobs per worker process |
| `SCAN_TIMEOUT_SECONDS` | `600` | Hard pipeline timeout for a single scan job |
| `SCAN_LOCK_TTL_SECONDS` | `660` | TTL of the per-repository distributed lock (must exceed `SCAN_TIMEOUT_SECONDS`) |
| `SCAN_QUEUE_NAME` | `arq:scans` | Arq queue name for scan jobs |

### Frontend

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend URL visible to the browser and used for WebSocket connections. Injected at **runtime** by the Next.js server — change via container `environment`, no image rebuild required. |

---

## Project Structure

```
ai-multi-agent/
├── ui/                             # Next.js 16 frontend
│   ├── app/                        # App Router pages
│   │   ├── repo/[id]/              # Repository dashboard
│   │   └── layout.tsx
│   ├── components/                 # React components
│   │   ├── dashboard/              # Score cards, agent panels
│   │   ├── scan/                   # Scan trigger + progress
│   │   └── ui/                     # Shared primitives
│   ├── lib/
│   │   └── api-client.ts           # Typed fetch wrappers
│   ├── types/                      # TypeScript interfaces
│   ├── Dockerfile                  # Multi-stage production build
│   └── next.config.ts
│
├── backend/                        # FastAPI service
│   ├── app/
│   │   ├── api/                    # Route handlers + schemas
│   │   │   ├── routes/             # /review, /github webhooks
│   │   │   └── scans.py            # /scans routes
│   │   ├── application/            # Orchestrators + agents
│   │   │   ├── agents/             # 5 domain agents
│   │   │   ├── orchestrator.py     # Synchronous review
│   │   │   ├── scan_orchestrator.py# Async scan pipeline
│   │   │   └── source_preparation.py
│   │   ├── domain/                 # Entities, enums, value objects
│   │   ├── infrastructure/
│   │   │   ├── db/                 # SQLAlchemy models + repos
│   │   │   ├── arq_worker.py       # Arq task definitions
│   │   │   ├── background_tasks.py # Arq enqueue helper
│   │   │   ├── github_clone.py     # Async git clone
│   │   │   ├── local_repo_validator.py
│   │   │   ├── redis_client.py     # Lock + cancel helpers
│   │   │   └── repository_ingestion/
│   │   └── core/                   # Config, exceptions, logging
│   ├── alembic/                    # Database migrations
│   ├── tests/                      # 510+ unit + integration tests
│   ├── Dockerfile
│   └── pyproject.toml
│
├── docker-compose.yml              # All services
├── .env.example                    # Environment variable reference
└── README.md
```

---

## Running Tests

```bash
cd backend
pytest tests/ -q
```

All tests are isolated — no running Redis or PostgreSQL required (mocked via `tests/conftest.py`).

---

## Scaling Workers

By default, 2 worker replicas run. To scale up:

```bash
docker-compose up --scale worker=4
```

Each replica processes up to `SCAN_MAX_CONCURRENT` (default 3) scans in parallel. Horizontal scaling is safe because per-repository locking is enforced via Redis.

---

## Contributing

1. Fork the repo and create a feature branch.
2. Backend: follow the clean architecture layers (no business logic in routes, no infrastructure imports in domain).
3. Frontend: add typed API calls in `lib/api-client.ts`; co-locate components with their pages.
4. Run `pytest` (backend) and `npm run lint` (frontend) before opening a PR.
5. All environment secrets go in `.env` — never committed.
#   e n g i n e e r i n g - e x c e l l e n c e - a g e n t i c - a i  
 