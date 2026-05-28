# GitHub Copilot Instructions — ai-multi-agent

This file gives Copilot workspace context. Read it before generating code for this repository.

---

## Project overview

**EngineerIQ — AI Multi-Agent Engineering Intelligence Platform** — a monorepo:

| Path | Stack | Purpose |
|------|-------|---------|
| `ui/` | Next.js 16, React 19, TypeScript, Tailwind 4, TanStack Query v5 | Dashboard for triggering scans and viewing results |
| `backend/` | Python 3.11, FastAPI, SQLAlchemy 2 (async), Alembic, Arq, Redis, PostgreSQL | REST API + background scan workers |

Full architecture docs: `docs/architecture.md`

---

## Backend architecture layers

```
app/api/           ← Route handlers + Pydantic schemas ONLY — no business logic
app/application/   ← Orchestrators, agents, use-case services — no I/O
app/domain/        ← Entities, enums, value objects — NO infrastructure imports
app/infrastructure/← DB, Redis, LLM adapters, git clone, Arq worker
app/core/          ← Config (Settings), exceptions, logging
```

**Import rules (enforced by convention):**
- `api` → `application` → `domain` (downward only)
- `infrastructure` → `domain` (allowed)
- `api` → `infrastructure` is **forbidden** (always go through application services)
- `domain` → nothing (zero external imports)

---

## Two distinct pipelines

| | Async Scan | Sync Review |
|--|-----------|-------------|
| Endpoint | `POST /api/scans/run` | `POST /api/review` |
| Execution | Arq background job | Blocks until done |
| Progress | DB % + WebSocket events | None |
| Lock | Redis per-repo `SET NX` | None |
| Cancel | Redis flag + polling | None |
| DB models | `repositories`, `scans`, `scan_agent_results` | `engineering_reviews`, `agent_results` |

---

## Scan pipeline progress checkpoints

```
5%  → status="running"
15% → source prepared (clone / local validate)
25% → file index + language/framework detection
35% → 5 intelligence services gathered
35–90% → 5 agents in parallel (+~11% each)
95% → scored + persisted
100% → status="completed"
```

Cancellation is polled between every stage. Auto-fix (patch → validate → PR) runs as a best-effort Stage 7 after 100% — failures do not fail the scan.

---

## Agents

Five agents inherit `BaseEngineeringAgent` and implement `async analyse(repo_metadata, tool_context) → AgentFinding`:

| Agent | Alias | Tool context it receives |
|-------|-------|--------------------------|
| `SeniorQAAgent` | `qa` | test_intelligence, cicd_intelligence |
| `SeniorDeveloperAgent` | `dev` | code_intelligence, test_intelligence |
| `SeniorArchitectAgent` | `architect` | code_intelligence, architecture_intelligence |
| `SeniorSREAgent` | `sre` | cicd_intelligence, code_intelligence |
| `SecurityExpertAgent` | `security` | security_intelligence, cicd_intelligence |

All agents run with `asyncio.gather(return_exceptions=True)` — a failed agent produces a zero-score fallback, never crashes the pipeline.

LLM response is structured via `llm_schemas.LLMAgentResponse` (score 0–100, ≤10 issues, ≤8 recommendations). Temperature 0.2 for structured, 0.3 for free text.

---

## Database (SQLAlchemy async)

Two ORM model sets exist:
- `app/infrastructure/db/models.py` — PostgreSQL production models (UUID + JSONB columns)
- `app/infrastructure/persistence/models.py` — SQLite-compatible models (for unit tests)

Key production models:

| Model | Table | Notes |
|-------|-------|-------|
| `RepositoryModel` | `repositories` | `repo_url` nullable for local paths |
| `ScanModel` | `scans` | `status`, `progress_percentage`, `scan_config_json` (JSONB), `source_type` |
| `ScanAgentResultModel` | `scan_agent_results` | JSONB `issues` + `recommendations` |
| `EngineeringReviewModel` | `engineering_reviews` | Legacy sync review |

Migrations: `cd backend && alembic revision --autogenerate -m "…" && alembic upgrade head`

---

## Redis key patterns

| Key | TTL | Purpose |
|-----|-----|---------|
| `scan:lock:repo:{repo_id}` | 660s | Distributed lock; value = scan_id for ownership check |
| `scan:cancel:{scan_id}` | 1h | Cancellation flag |

Lock is acquired by the API handler, always released by the Arq worker's `finally` block. Lock value = `scan_id` so mismatched releases are silently ignored.

---

## WebSocket streaming

Endpoint: `GET /ws/scans/{scan_id}` (max 5 concurrent, keepalive every 30s, 1h max lifetime)

```
Orchestrator → ScanEventBus.log/progress/status()
             → ConnectionManager.publish(scan_id, event)
             → asyncio.Queue per scan  [max 1000, drops oldest]
             → consumed by WS endpoint handler
             → ws.send_json(event)
```

Sentinel `None` in the queue signals scan end and closes the WebSocket.

---

## Auto-fix pipeline (Stage 7, best-effort)

When `allow_auto_fix=True` in `ScanConfig`:
1. Collect HIGH/CRITICAL issues
2. Create virtual workspace (temp copy)
3. `PatchEngine` generates unified diff
4. `_patch_apply` applies it
5. `ValidationPipeline` runs lint + tests + type-check
6. `BreakingChangeDetector` analyses diff
7. `SafePullRequestService` creates PR **only if** validation passed + no breaking changes

All failures are swallowed — scan stays `completed`.

---

## Testing

```bash
cd backend && pytest tests/ -q
```

**Critical:** `tests/conftest.py` has a session-scoped autouse fixture patching `create_redis_pool` with an `AsyncMock`. Never remove it — all API tests depend on it to avoid Redis timeouts.

Two test locations:
- `tests/unit/` — per-layer unit tests (mock all I/O)
- `tests/integration/` — orchestrator-level tests

Use `app/infrastructure/llm/mock_adapter.py` (deterministic) when testing agent logic.

---

## Common backend tasks

### Add a new API endpoint
1. Pydantic schema → `app/api/schemas.py`
2. Thin route handler → relevant file in `app/api/` (validate → call service → return schema)
3. Business logic → method on orchestrator/service in `app/application/`
4. Schema change → Alembic migration
5. Tests → `backend/tests/unit/api/`

### Add a new agent
1. Create `app/application/agents/your_agent.py` inheriting `BaseEngineeringAgent`
2. Implement `async def analyse(self, repo_metadata, tool_context) -> AgentFinding`
3. Add alias to `ScanConfig` validator in `app/api/schemas.py`
4. Register in `ScanOrchestrator` **and** `EngineeringReviewOrchestrator`
5. Tests → `tests/unit/application/`

---

## Frontend conventions

- **All backend calls** go through `ui/lib/api-client.ts` — add new endpoints there
- **Server state** via TanStack Query (`useQuery` / `useMutation`) — never `useState` for async data
- **WebSocket** via `useScanLogs` hook — not TanStack Query
- **Tailwind 4 only** — no CSS modules or inline styles; use `cn()` from `lib/utils.ts`
- **Types** — every API response needs a matching interface in `ui/types/`
- **Components** — co-locate with the page that owns them; put in `ui/components/` if shared

### Runtime env — `NEXT_PUBLIC_API_URL`
The variable is **not** baked at build time. `layout.tsx` (Server Component) injects it into `window.__ENV` on every request. `api-client.ts` reads `window.__ENV` first. Changing the backend URL only requires restarting the container.

### Mock data boundary
`lib/mock-data.ts` drives the repo dashboard and scan detail pages (`MOCK_REPOSITORIES`, `MOCK_PATCH_DATA`, etc.). The live API surface (scan trigger, status polling, WebSocket logs, patch/PR) is fully integrated. To wire a page to real data: replace mock imports with TanStack Query hooks.

### Scan modal flow (state machine in `providers.tsx`)
```
null → "trigger" (ScanTriggerModal) → "progress" (ScanProgressDialog) → null
                                    ↑ retry ←──────────────────────────┘
```

### Add a new frontend page
1. Create `ui/app/your-page/page.tsx`
2. Add typed API calls to `ui/lib/api-client.ts`
3. Add TypeScript interfaces to `ui/types/`
4. Use TanStack Query for data fetching

---

## Environment variables

See `.env.example` (root), `backend/.env.example`, and `ui/.env.example` for full descriptions.

| Variable | Required | Used by |
|----------|----------|---------|
| `OPENAI_API_KEY` | **Yes** | All 5 AI agents |
| `DATABASE_URL` | **Yes** | SQLAlchemy async engine |
| `REDIS_URL` | **Yes** | Arq worker + lock/cancel helpers |
| `SECRET_KEY` | Prod | FastAPI app |
| `GITHUB_TOKEN` | Optional | Private repo cloning + PR comments |
| `NEXT_PUBLIC_API_URL` | No | Frontend → runtime injected, default `http://localhost:8000` |

---

## Docker Compose

```bash
docker compose up --build                    # All 5 services
docker compose up postgres redis -d          # Infra only (local dev)
docker compose up --scale worker=4          # Scale scan workers
docker compose exec backend alembic upgrade head  # Run migrations (first start)
```

Backend `Dockerfile` is reused for both `backend` and `worker` services — only the `command` differs.

