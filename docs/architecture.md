# Architecture Documentation — AI Multi-Agent Engineering Intelligence Platform

> **Last updated:** April 2026  
> Generated from codebase analysis covering `backend/` and `ui/`.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [High-Level Architecture Diagram](#2-high-level-architecture-diagram)
3. [Backend Architecture](#3-backend-architecture)
   - [Layer Structure](#31-layer-structure)
   - [API Layer](#32-api-layer)
   - [Application Layer](#33-application-layer)
   - [Infrastructure Layer](#34-infrastructure-layer)
   - [Domain Layer](#35-domain-layer)
4. [Scan Pipeline — End-to-End Flow](#4-scan-pipeline--end-to-end-flow)
5. [Review Pipeline — Synchronous Flow](#5-review-pipeline--synchronous-flow)
6. [Agent Architecture](#6-agent-architecture)
7. [WebSocket Streaming Flow](#7-websocket-streaming-flow)
8. [GitHub Webhook Flow](#8-github-webhook-flow)
9. [Frontend Architecture](#9-frontend-architecture)
   - [Component Tree](#91-component-tree)
   - [State Management](#92-state-management)
   - [Data Flow](#93-data-flow)
10. [Scan Modal State Machine](#10-scan-modal-state-machine)
11. [Data Models](#11-data-models)
12. [Environment & Configuration](#12-environment--configuration)
13. [Key Design Decisions](#13-key-design-decisions)

---

## 1. System Overview

**EngineerIQ** is a full-stack monorepo that analyses software repositories using five parallel AI agents and surfaces engineering health scores, architectural findings, security issues, and actionable recommendations.

| Service | Stack | Port |
|---------|-------|------|
| `frontend` | Next.js 16, React 19, TypeScript, Tailwind 4, TanStack Query v5 | 3000 |
| `backend` | Python 3.11, FastAPI, SQLAlchemy 2 async, Arq | 8000 |
| `worker` | Same image as backend, different entrypoint | — |
| `postgres` | PostgreSQL 15 | 5432 |
| `redis` | Redis 7 | 6379 |

Two distinct analysis pipelines exist:

| Pipeline | Endpoint | Mode | Workers |
|----------|----------|------|---------|
| **Scan** | `POST /api/scans/run` | Async background job with progress tracking | Arq + Redis |
| **Review** | `POST /api/review` | Synchronous, blocks until complete | In-process |

---

## 2. High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Browser (Next.js 16)                              │
│                                                                             │
│  ┌─────────────┐   ┌──────────────────────┐   ┌──────────────────────────┐ │
│  │   Sidebar   │   │  ScanTriggerModal    │   │   Repo / Scan Pages      │ │
│  │  (mock nav) │   │  ScanProgressDialog  │   │   (mock data + charts)   │ │
│  └─────────────┘   └──────────┬───────────┘   └──────────────────────────┘ │
│                               │ hooks: useRunScan, useScanStatus,           │
│                               │        useScanLogs (WebSocket)              │
└───────────────────────────────┼─────────────────────────────────────────────┘
                                │ HTTP REST + WebSocket
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FastAPI Backend (:8000)                             │
│                                                                             │
│  POST /api/scans/run ──► Acquire Redis lock ──► Create ScanModel            │
│  GET  /api/scans/{id}/status                   ──► Read DB                  │
│  POST /api/scans/{id}/cancel ──► Set Redis flag                             │
│  GET  /ws/scans/{id}  ──► WebSocket stream (asyncio.Queue per scan)         │
│  POST /api/review     ──► Synchronous orchestrator                          │
│  POST /api/github/webhook ──► HMAC verify ──► BackgroundTask                │
│  GET  /health                                                               │
└───────────┬──────────────────────────────────────────────────┬─────────────┘
            │ enqueue_job()                                     │ async/await
            ▼                                                   ▼
┌───────────────────────┐                         ┌────────────────────────────┐
│   Redis (:6379)       │                         │  ScanOrchestrator /        │
│                       │  ◄── dequeue ───────    │  EngineeringReviewOrch.    │
│  • Arq task queue     │                         │                            │
│  • scan:lock:repo:{}  │                         │  SourcePreparationService  │
│  • scan:cancel:{}     │                         │  RepositoryIngestion       │
└───────────────────────┘                         │  Intelligence Services     │
                                                  │  5× Agent.analyse()        │
            ┌─────────────────────────────────────│  ScoringEngine             │
            │                                     └────────────┬───────────────┘
            ▼                                                  │
┌───────────────────────┐                                      │ persist
│  Arq Worker (×2)      │                                      ▼
│  scan_task()          │                         ┌────────────────────────────┐
│  max_jobs = 3         │                         │  PostgreSQL (:5432)        │
│  job_timeout = 600s   │                         │  repositories / scans      │
└───────────────────────┘                         │  scan_agent_results        │
                                                  │  engineering_reviews       │
                                                  └────────────────────────────┘
```

---

## 3. Backend Architecture

### 3.1 Layer Structure

```
backend/app/
├── api/            ← HTTP handlers + Pydantic schemas ONLY — no business logic
│   ├── routes/
│   │   ├── review.py       POST /api/review, GET /api/review/{id}
│   │   └── github.py       POST /api/github/webhook
│   ├── scans.py            POST /api/scans/run, GET /status, POST /cancel
│   ├── websocket.py        GET /ws/scans/{id}
│   ├── schemas.py          All request/response Pydantic models
│   └── deps.py             FastAPI dependency injectors
│
├── application/    ← Orchestrators, agents, use-case services — NO I/O
│   ├── scan_orchestrator.py     Async scan pipeline (5%→100%)
│   ├── orchestrator.py          Synchronous review pipeline
│   ├── source_preparation.py    GitHub clone / local path routing
│   ├── scoring_engine.py        Weighted score + risk calculation
│   ├── scan_event_bus.py        Typed façade over WebSocket queue
│   ├── scan_config_resolver.py  ScanExecutionPlan from config JSON
│   ├── architecture_drift.py    Circular deps / layer violations
│   ├── patch_engine.py          Unified diff generation
│   ├── validation_pipeline.py   Lint / test / type-check validation
│   ├── safe_pr_service.py       PR creation gating
│   ├── breaking_change_detector.py
│   ├── virtual_workspace.py     Temp workspace for patch application
│   ├── tool_interfaces.py       Abstract tool contracts (5 services)
│   └── agents/
│       ├── base.py              BaseEngineeringAgent ABC
│       ├── llm_schemas.py       LLMIssue, LLMAgentResponse Pydantic models
│       ├── qa_agent.py
│       ├── developer_agent.py
│       ├── architect_agent.py
│       ├── sre_agent.py
│       └── security_agent.py
│
├── infrastructure/ ← All I/O: DB, Redis, LLM, Git, filesystem
│   ├── db/
│   │   ├── models.py            PostgreSQL SQLAlchemy models (JSONB)
│   │   ├── session.py           Async engine + session factory
│   │   ├── repository.py        Review/EngReview CRUD
│   │   └── scan_repository.py   Scan CRUD + progress updates
│   ├── persistence/
│   │   └── models.py            SQLite-compatible models (for tests)
│   ├── llm/
│   │   ├── base.py              BaseLLMAdapter ABC
│   │   ├── openai_adapter.py    OpenAI implementation
│   │   └── mock_adapter.py      Deterministic mock for tests
│   ├── embeddings/              RAG: chunker, vector store, retrieval
│   ├── intelligence/            Code/test/CI/security/AST analysis engines
│   ├── repository_ingestion/    File scanner, language/framework detection
│   ├── github/                  GitHub API client, webhook processor, PR formatter
│   ├── arq_worker.py            WorkerSettings + scan_task()
│   ├── background_tasks.py      Arq enqueue helper
│   ├── redis_client.py          Lock + cancel flag helpers
│   ├── github_clone.py          Async git clone to /tmp/scans/{scan_id}/
│   ├── local_repo_validator.py  Local path safety checks
│   └── websocket_manager.py     Per-scan asyncio.Queue + WS connection registry
│
├── domain/         ← Entities, enums, value objects — zero infrastructure imports
│   ├── entities/               AgentFinding, AgentIssue, etc.
│   ├── enums/                  AgentName, ScanStatus, Severity, RiskLevel
│   └── value_objects/          RepoMetadata, etc.
│
└── core/           ← Cross-cutting: config, exceptions, logging
    ├── config.py               Pydantic BaseSettings (reads .env)
    ├── exceptions.py           AppError hierarchy
    └── logging.py              Structured logging setup
```

**Dependency rules (enforced by convention):**
- `api` → `application` → `domain` (import allowed downward)
- `infrastructure` → `domain` (allowed)
- `domain` → nothing (no infrastructure imports ever)
- `api` → `infrastructure` is **forbidden** (go through application services)

---

### 3.2 API Layer

#### Routers

| Router | Prefix | Key Endpoints |
|--------|--------|---------------|
| `scans.py` | `/api/scans` | `POST /run`, `GET /{id}/status`, `POST /{id}/cancel`, `GET /{id}/patch`, `POST /{id}/create-pr` |
| `review.py` | `/api/review` | `POST /`, `GET /{id}`, `GET /{id}/summary` |
| `github.py` | `/api/github` | `POST /webhook` |
| `websocket.py` | `/ws` | `GET /scans/{id}` (WebSocket upgrade) |

#### `POST /api/scans/run` detailed flow

```
Request arrives
     │
     ▼
Validate source (github URL format / local path exists)
     │
     ▼
Resolve or create RepositoryModel (upsert by URL/path)
     │
     ▼
Acquire Redis lock: SET NX scan:lock:repo:{repository_id} = scan_id  TTL=660s
     │ 409 if already locked
     ▼
INSERT ScanModel  status="queued"  progress=0
     │
     ▼
arq_pool.enqueue_job("scan_task", scan_id, repository_id)
     │
     ▼
Return 202  { scan_id, repository_id, status: "queued" }
```

#### `ScanConfig` schema (from `schemas.py`)

```python
class ScanConfig(BaseModel):
    mode: Literal["quick", "deep", "security-only"]  # controls agents + file cap
    include_agents: list[str] | None    # whitelist by alias: qa/dev/architect/sre/security
    exclude_agents: list[str] | None    # blacklist
    max_files: int | None               # cap on files scanned
    fail_on_high_severity: bool = False # marks scan failed if HIGH/CRITICAL found
    allow_auto_fix: bool = False        # enables patch + PR creation stage
```

---

### 3.3 Application Layer

#### ScanOrchestrator progress pipeline

```
scan_task() called by Arq worker
         │
         ├─► Check cancel flag (bail early)
         │
         ▼
[5%]  Set status="running", emit log event
         │
[15%] SourcePreparationService.prepare()
         │   GitHub → git clone to /tmp/scans/{scan_id}/
         │   Local  → validate path, reference in-place
         │
[25%] RepositoryIngestion
         │   build_file_index() [in executor]
         │   detect_primary_language()
         │   detect_frameworks()
         │
[35%] Gather intelligence tool context
         │   CodeIntelligenceService
         │   TestIntelligenceService
         │   CiCdIntelligenceService
         │   SecurityIntelligenceService
         │   ArchitectureAnalysisService
         │   (each failure → empty dict, pipeline continues)
         │
[35-90%] asyncio.gather(*[agent.analyse() for agent in agents])
         │   Each agent: +~11% progress when complete
         │   Failures → zero-score fallback AgentFinding
         │   All agents run even if some fail
         │
[95%]  ScoringEngine.compute_weighted_score()
         │   Persist ScanAgentResultModel for each agent
         │   Persist final ScanModel score + risk_level
         │
[100%] status="completed"  emit status event  cleanup clone
```

**Cancellation check points:** after each `[%]` stage and between agent dispatches.

#### EngineeringReviewOrchestrator (synchronous path)

```
POST /api/review received
         │
         ▼
Load repository (GitHub clone or local)
         │
         ▼
Run 5 intelligence services concurrently (asyncio.gather)
         │
         ▼
Build per-agent context slice (only relevant services per agent)
         │
         ▼
Run 5 agents concurrently (asyncio.gather, return_exceptions=True)
         │   30s per-agent timeout
         │   Failed agents → fallback zero-score AgentFinding
         │
         ▼
Compute weighted score → risk level
         │
         ▼
Persist EngineeringReviewModel + AgentResultModel records
         │
         ▼
Return review_id  (client then GET /api/review/{id})
```

#### Agent context slicing

Each agent receives only the intelligence services relevant to its domain:

| Agent | Services received |
|-------|------------------|
| `SENIOR_QA` | test_intelligence, cicd_intelligence |
| `SENIOR_DEVELOPER` | code_intelligence, test_intelligence |
| `SENIOR_ARCHITECT` | code_intelligence, architecture_intelligence |
| `SENIOR_SRE` | cicd_intelligence, code_intelligence |
| `SECURITY_EXPERT` | security_intelligence, cicd_intelligence |

---

### 3.4 Infrastructure Layer

#### Redis key patterns

| Key | TTL | Purpose |
|-----|-----|---------|
| `scan:lock:repo:{repository_id}` | 660s | Distributed lock; value = scan_id for ownership check |
| `scan:cancel:{scan_id}` | 1h | Cancellation flag set by `/cancel` endpoint |
| `arq:scans` | — | Arq job queue (default queue name) |

#### WebSocket connection manager (`websocket_manager.py`)

```
connect(scan_id, websocket)
     │ Reject (1008) if > 5 connections for this scan
     ▼
_connections[scan_id].append(ws)
_queues[scan_id] = asyncio.Queue()

publish(scan_id, event)          → put on queue (drop oldest if queue full at 1000)
consume(scan_id)                 → returns the queue (creates if absent)
cleanup_scan(scan_id)            → put sentinel None, remove state
```

#### Arq worker settings (`arq_worker.py`)

```python
class WorkerSettings:
    functions    = [scan_task]
    max_jobs     = settings.scan_max_concurrent   # default 3
    job_timeout  = settings.scan_timeout_seconds  # default 600s
    retry_jobs   = False                          # scans are not idempotent
```

#### LLM adapter interface (`llm/base.py`)

```python
class BaseLLMAdapter:
    async def complete_structured(
        system_prompt: str, user_prompt: str, response_model: Type[T]
    ) -> T   # Structured JSON (Pydantic model, temp=0.2)

    async def complete_text(
        system_prompt: str, user_prompt: str
    ) -> str  # Free-form text (temp=0.3)
```

---

### 3.5 Domain Layer

#### Enums

```python
AgentName:    SENIOR_QA | SENIOR_DEVELOPER | SENIOR_ARCHITECT | SENIOR_SRE | SECURITY_EXPERT
ScanStatus:   QUEUED | RUNNING | COMPLETED | FAILED | CANCELLED
ReviewStatus: PENDING | RUNNING | COMPLETED | FAILED
Severity:     LOW | MEDIUM | HIGH | CRITICAL
RiskLevel:    LOW | MEDIUM | HIGH | CRITICAL
```

---

## 4. Scan Pipeline — End-to-End Flow

```mermaid
sequenceDiagram
    participant Browser
    participant API as FastAPI :8000
    participant Redis
    participant DB as PostgreSQL
    participant Arq as Arq Worker
    participant LLM as OpenAI LLM
    participant WS as WebSocket

    Browser->>API: POST /api/scans/run {url, config}
    API->>Redis: SET NX scan:lock:repo:{repo_id} = scan_id  TTL=660s
    Redis-->>API: OK (or 409 if locked)
    API->>DB: INSERT scans status="queued"
    API->>Redis: enqueue_job("scan_task", scan_id, repo_id)
    API-->>Browser: 202 {scan_id, status:"queued"}

    Browser->>WS: CONNECT /ws/scans/{scan_id}
    Browser->>API: GET /api/scans/{scan_id}/status  (every 3s)

    Arq->>Redis: dequeue scan_task
    Arq->>DB: UPDATE status="running" progress=5
    Arq->>WS: emit log("Starting scan…")

    Arq->>Arq: git clone repo  OR  validate local path
    Arq->>DB: UPDATE progress=15
    Arq->>WS: emit progress(15)

    Arq->>Arq: build_file_index() detect language/frameworks
    Arq->>DB: UPDATE progress=25

    Arq->>Arq: run 5 intelligence services concurrently
    Arq->>DB: UPDATE progress=35

    par 5 Agents in parallel
        Arq->>LLM: complete_structured(qa_prompt)
        Arq->>LLM: complete_structured(dev_prompt)
        Arq->>LLM: complete_structured(arch_prompt)
        Arq->>LLM: complete_structured(sre_prompt)
        Arq->>LLM: complete_structured(security_prompt)
    end

    Arq->>DB: UPDATE progress=90
    Arq->>Arq: compute_weighted_score()
    Arq->>DB: INSERT scan_agent_results (×5)
    Arq->>DB: UPDATE scans status="completed" progress=100
    Arq->>Redis: release lock, clear cancel flag
    Arq->>WS: emit status("completed") + sentinel None

    WS-->>Browser: final status event + close

    Browser->>API: GET /api/scans/{scan_id}/status
    API-->>Browser: {status:"completed", progress:100}
    Browser->>Browser: navigate to /repo/{id}/scan/{scan_id}
```

---

## 5. Review Pipeline — Synchronous Flow

```mermaid
sequenceDiagram
    participant Browser
    participant API as FastAPI :8000
    participant DB as PostgreSQL
    participant LLM as OpenAI LLM

    Browser->>API: POST /api/review {repo_url}
    API->>API: EngineeringReviewOrchestrator.run()

    par 5 Intelligence Services
        API->>API: CodeIntelligenceService.analyze()
        API->>API: TestIntelligenceService.analyze()
        API->>API: CiCdIntelligenceService.analyze()
        API->>API: SecurityIntelligenceService.analyze()
        API->>API: ArchitectureAnalysisService.analyze()
    end

    par 5 Agents (30s timeout each)
        API->>LLM: qa agent prompt
        API->>LLM: dev agent prompt
        API->>LLM: architect agent prompt
        API->>LLM: sre agent prompt
        API->>LLM: security agent prompt
    end

    API->>API: compute_weighted_score()
    API->>DB: INSERT engineering_reviews + agent_results (×5)
    API-->>Browser: 202 {review_id}

    Browser->>API: GET /api/review/{review_id}
    API-->>Browser: Full aggregate with all findings
```

---

## 6. Agent Architecture

All five agents share a common base contract:

```
BaseEngineeringAgent (ABC)
├── agent_name: AgentName           (enum, unique identity)
├── role_definition: str            (system prompt preamble)
├── evaluation_rubric: str          (scoring criteria injected into prompt)
└── async analyse(repo_metadata, tool_context) → AgentFinding

Concrete agents:
├── SeniorQAAgent           → "test_intelligence", "cicd_intelligence"
├── SeniorDeveloperAgent    → "code_intelligence", "test_intelligence"
├── SeniorArchitectAgent    → "code_intelligence", "architecture_intelligence"
├── SeniorSREAgent          → "cicd_intelligence", "code_intelligence"
└── SecurityExpertAgent     → "security_intelligence", "cicd_intelligence"
```

#### Agent execution flow

```
agent.analyse(repo_metadata, tool_context)
          │
          ▼
Build system_prompt (role_definition + rubric + tool_context as JSON)
          │
          ▼
llm_adapter.complete_structured(system_prompt, user_prompt, LLMAgentResponse)
          │   response_model enforces schema:
          │   { score: 0-100, summary: str, issues: Issue[≤10], recommendations: str[≤8] }
          ▼
_to_agent_finding(llm_response) → AgentFinding (domain entity)
          │
          ▼
Return AgentFinding  (never raises, wraps exceptions into fallback finding)
```

#### LLM response schema (`llm_schemas.py`)

```python
class LLMIssue(BaseModel):
    severity: Literal["Low", "Medium", "High", "Critical"]
    file_path: str | None
    line_number: int | None
    title: str
    description: str
    recommendation: str

class LLMAgentResponse(BaseModel):
    score: int           # 0–100
    summary: str
    issues: list[LLMIssue]        # max 10
    recommendations: list[str]    # max 8
```

---

## 7. WebSocket Streaming Flow

```
Orchestrator (in Arq worker process)
        │
        ▼
ScanEventBus.log("Cloning repo…")
        │
        ▼
ConnectionManager.publish(scan_id, {"type":"log","message":"…"})
        │
        ▼
asyncio.Queue per scan_id   [max 1000 events, drops oldest]
        │
        ▼  (consumed by WS endpoint handler)
GET /ws/scans/{scan_id}
  ├── accept WebSocket connection (reject if > 5 connections)
  ├── queue = manager.consume(scan_id)
  ├── loop:
  │     event = await queue.get()
  │     if event is None: break          ← sentinel: scan finished
  │     await ws.send_json(event)
  │     if idle > 30s: send keepalive ping
  └── close WebSocket
```

**Event envelope format:**
```json
{ "type": "log",      "message": "Cloning repository…",  "timestamp": "…" }
{ "type": "progress", "progress": 35,                     "timestamp": "…" }
{ "type": "status",   "status": "completed",              "timestamp": "…" }
```

---

## 8. GitHub Webhook Flow

```
POST /api/github/webhook
        │
        ▼
Verify HMAC-SHA256 (X-Hub-Signature-256 header vs GITHUB_WEBHOOK_SECRET)
        │  401 if invalid
        ▼
Check X-GitHub-Event header
        │  200 (no-op) for non "pull_request" events
        ▼
Check action in {opened, synchronize, reopened}
        │  200 (no-op) for other actions
        ▼
FastAPI BackgroundTask: PRWebhookProcessor.process(payload)
        │
        ▼
Return 202 immediately (processing continues in background)

PRWebhookProcessor:
  ├── Extract PR metadata (repo URL, head SHA, branch)
  ├── Run EngineeringReviewOrchestrator (full sync review)
  ├── Format findings via PRCommentFormatter
  └── Post comment to PR via GitHub API client
```

---

## 9. Frontend Architecture

### 9.1 Component Tree

```
RootLayout (Server Component)
│  Injects window.__ENV = { NEXT_PUBLIC_API_URL }  ← runtime env config
│
├── Providers (Client Component)
│   ├── QueryClientProvider (TanStack Query)
│   ├── ScanModalContext  (trigger | progress | null)
│   │   ├── ScanTriggerModal  (shown when mode="trigger")
│   │   │   ├── Source selector (GitHub URL / local path)
│   │   │   ├── ScanModeSelector (quick/standard/security_only/deep)
│   │   │   ├── Agent picker (QA/Dev/Architect/SRE/Security)
│   │   │   ├── Operation mode (analyze/suggest/auto-fix)
│   │   │   └── useRunScan() → POST /api/scans/run
│   │   └── ScanProgressDialog  (shown when mode="progress")
│   │       ├── useScanStatus() → GET /api/scans/{id}/status  [polls 3s]
│   │       ├── useScanLogs()  → WS /api/scans/{id}/logs  [auto-reconnect 2s]
│   │       └── Step progress bar (8 labeled milestones)
│   │
│   └── children
│       ├── Sidebar (Client Component)
│       │   └── MOCK_REPOSITORIES (hardcoded nav links)
│       │
│       └── Pages
│           ├── / → redirect to /repo/retail-core
│           │
│           ├── /repo/[id]  (Server Component)
│           │   ├── Header
│           │   ├── RepoSummary
│           │   ├── AgentScoreCards
│           │   ├── TrendChart (Recharts)
│           │   ├── AgentBarChart (Recharts)
│           │   └── ScanHistory → links to /repo/[id]/scan/[scanId]
│           │
│           └── /repo/[id]/scan/[scanId]  (Server Component)
│               ├── Header (breadcrumbs)
│               ├── Scan overview card (score, risk, meta)
│               ├── AgentScoreCards
│               ├── AgentBarChart  ─┐
│               ├── DriftPanel      ├─ side-by-side grid
│               ├── IssuesTable    ─┘
│               ├── PatchPreviewModal  (if patch_available)
│               ├── ValidationPanel    (lint/test/type-check results)
│               ├── BreakingChangeAlert
│               └── CreatePRPanel → useCreatePR() → POST /api/scans/{id}/create-pr
```

### 9.2 State Management

| State type | Mechanism | Location |
|-----------|-----------|----------|
| Scan modal visibility | React context (`ScanModalContext`) | `providers.tsx` |
| Async server data | TanStack Query (`useQuery` / `useMutation`) | Custom hooks |
| WebSocket log stream | `useState` + `useEffect` | `useScanLogs.ts` |
| Recent repos | `localStorage` key `iq-recent-scans` (max 5, deduplicated by URL) | `ScanTriggerModal.tsx` |
| Theme preference | `localStorage` key `theme`, falls back to `prefers-color-scheme` | `Header.tsx` |
| Repository/scan data | **Mock data** (not from API yet) | `lib/mock-data.ts` |

> ⚠️ **Current state:** The repo dashboard and scan detail pages render entirely from `MOCK_REPOSITORIES` in `lib/mock-data.ts`. The live API integration (scans/run + WebSocket) is wired and functional, but historical scan results are not yet fetched from the backend.

**Mock data constants available in `lib/mock-data.ts`:**

| Export | Purpose |
|--------|---------|
| `MOCK_REPOSITORY` | Single repo fixture (`retail-core`) |
| `MOCK_REPOSITORIES` | Array wrapping the above (used by Sidebar + pages) |
| `MOCK_PATCH_DATA` | Map of scan ID → unified diff string |
| `MOCK_VALIDATION_PASS` | Successful lint/test/typecheck report |
| `MOCK_VALIDATION_PARTIAL` | Partial failure (test failures) scenario |
| `MOCK_BREAKING` | Breaking change detection report |

### 9.3 Data Flow

```
User opens ScanTriggerModal
         │
         ├── Types GitHub URL
         │     └── useRepoBranches() fires (debounced 600ms, validated by regex)
         │           GET /api/repos/branches?repository_url=…
         │           → populates branch selector
         │
         ├── Configures mode + depth (quick/standard/security_only/deep)
         │     └── Estimated time shown: quick=30–60s, standard=2–5m, deep=8–15m
         │
         ├── Picks agents (all 5 default, any subset allowed)
         │
         ├── Picks operation_mode (analyze / suggest / auto-fix)
         │
         └── Clicks "Run Scan"
               useRunScan().mutate(request)
                 POST /api/scans/run
                 → { scan_id, repository_id }
                 │
                 ├── Saves repo to localStorage (iq-recent-scans, max 5)
                 │
                 ▼
               ctx.startProgress(scan_id, repository_id)
               ScanProgressDialog opens
                 │
                 ├── useScanStatus() polls every 3s
                 │     GET /api/scans/{scan_id}/status
                 │     Auto-stops when status = "completed" | "failed"
                 │
                 └── useScanLogs() opens WebSocket
                       WS /api/scans/{scan_id}/logs
                       Auto-reconnects every 2s on disconnect
                       Stops reconnecting when scan finishes

On completion → auto-navigate to /repo/{repositoryId}/scan/{scan_id} after 2s
```

#### ScanProgressDialog step milestones

```typescript
const STEPS = [
  { label: 'Cloning repository',      min: 0,  max: 12  },
  { label: 'Parsing structure',       min: 12, max: 25  },
  { label: 'Running QA agent',        min: 25, max: 42  },
  { label: 'Running Dev agent',       min: 42, max: 57  },
  { label: 'Running Architect agent', min: 57, max: 71  },
  { label: 'Running SRE agent',       min: 71, max: 84  },
  { label: 'Running Security agent',  min: 84, max: 95  },
  { label: 'Generating report',       min: 95, max: 100 },
]
```

Steps activate when `progress_percentage` enters their `min`–`max` range — aligned to the backend orchestrator's progress checkpoints.

---

## 10. Scan Modal State Machine

```
         ┌─────────────────────────────────────────────────────┐
         │                    null (closed)                     │
         └────────────────┬────────────────────────────────────┘
                          │ openTrigger()
                          ▼
         ┌────────────────────────────────────────────────────┐
         │              "trigger" mode                         │
         │   ScanTriggerModal open                             │
         └──────┬───────────────────────────────┬─────────────┘
                │ POST /api/scans/run succeeds   │ close()
                │ startProgress(scanId, repoId)  │
                ▼                               ▼
         ┌──────────────────────────┐     ┌──────────────┐
         │      "progress" mode      │     │  null (closed)│
         │   ScanProgressDialog open │     └──────────────┘
         └──────┬──────────┬────────┘
                │ close()  │ retry()
                ▼          ▼
         ┌──────────────┐  Back to "trigger"
         │  null (closed)│
         └──────────────┘
```

---

## 11. Data Models

### Backend PostgreSQL (production models in `db/models.py`)

```
repositories
 ├── id           UUID PK
 ├── name         VARCHAR
 ├── repo_url     VARCHAR nullable  (null for local paths)
 └── created_at   TIMESTAMP

scans
 ├── id                UUID PK
 ├── repository_id     UUID FK → repositories
 ├── status            VARCHAR  (queued|running|completed|failed|cancelled)
 ├── progress_percentage  INT
 ├── overall_score     FLOAT nullable
 ├── risk_level        VARCHAR nullable
 ├── error_message     TEXT nullable
 ├── source_type       VARCHAR  (github|local)
 ├── source_reference  VARCHAR  (URL or path)
 ├── branch            VARCHAR nullable
 ├── scan_mode         VARCHAR nullable
 ├── scan_config_json  JSONB nullable
 ├── log_stream_enabled BOOLEAN
 └── created_at        TIMESTAMP

scan_agent_results
 ├── id           UUID PK
 ├── scan_id      UUID FK → scans (CASCADE DELETE)
 ├── agent_name   VARCHAR
 ├── score        FLOAT
 ├── summary      TEXT
 ├── issues       JSONB   [{"severity","file_path","line_number","title",…}]
 └── recommendations  JSONB  [str, …]

engineering_reviews        (legacy synchronous reviews)
agent_results              (legacy, per-review agent findings)
```

### Frontend TypeScript types (`types/index.ts`, `types/scan.ts`)

```typescript
Repository { id, name, description, language, overallScore, delta, risk,
             lastScanDate, agents: AgentScore[], trend: TrendPoint[], scans: Scan[] }

Scan       { id, date, overallScore, risk, delta, agents, issues, drift,
             duration, commitSha, branch, operation_mode?, patch_available?,
             validation_report?, breaking_change_report?, fix_pr? }

AgentScore { agent: AgentType, score, delta, issueCount, description }

Issue      { id, severity, agent, filePath, lineNumber, title, description, recommendation }
```

---

## 12. Environment & Configuration

All variables are read by `app/core/config.py` (Pydantic BaseSettings). See `.env.example` at the repo root.

| Variable | Default | Required | Used by |
|----------|---------|----------|---------|
| `OPENAI_API_KEY` | — | **Yes** | All 5 AI agents |
| `SECRET_KEY` | `change-me` | Prod | FastAPI app |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@postgres:5432/ai_multi_agent` | **Yes** | SQLAlchemy engine |
| `REDIS_URL` | `redis://redis:6379/0` | **Yes** | Arq + lock/cancel |
| `OPENAI_MODEL` | `gpt-4o` | No | LLM adapter |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | No | Override for local LLMs |
| `LLM_TIMEOUT_SECONDS` | `60` | No | Per-LLM-call timeout |
| `LLM_MAX_RETRIES` | `3` | No | LLM retry policy |
| `GITHUB_TOKEN` | — | Optional | Private repos + PR comments |
| `SCAN_MAX_CONCURRENT` | `3` | No | Arq `max_jobs` |
| `SCAN_TIMEOUT_SECONDS` | `600` | No | Arq `job_timeout` |
| `SCAN_LOCK_TTL_SECONDS` | `660` | No | Redis lock TTL (must > timeout) |
| `SCAN_QUEUE_NAME` | `arq:scans` | No | Arq queue name |
| `MAX_CONCURRENT_AGENTS` | `5` | No | Review pipeline concurrency |
| `REVIEW_TIMEOUT_SECONDS` | `300` | No | Sync review timeout |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | No | Frontend → injected at runtime |

**Runtime env injection (frontend):**  
`NEXT_PUBLIC_API_URL` is read by the Next.js Node server in `layout.tsx` and injected into `window.__ENV` on every request — no image rebuild needed when changing the backend URL.

---

## 13. Key Design Decisions

### Two-tier orchestration
The system has **two separate review pipelines** — a synchronous `EngineeringReviewOrchestrator` (legacy `/api/review`) and an async `ScanOrchestrator` with progress tracking (`/api/scans`). They share agent implementations and scoring logic but have separate DB models and no shared cancellation/locking infrastructure.

### Distributed lock ownership
The Redis lock value is set to `scan_id` (not a random token). On release, the worker verifies `GET lock_key == scan_id` before `DEL`. This prevents a crashed/restarted worker from releasing a lock acquired by a different scan.

### Agent failure resilience
`asyncio.gather(return_exceptions=True)` is used for agent execution. Each exception is caught and replaced with a zero-score fallback `AgentFinding` that signals degradation without blocking the pipeline. The overall review/scan is only marked `failed` if **all** agents fail.

### Intelligence service isolation
The five intelligence services (code, test, CI/CD, security, architecture) run as separate stateless analysers. Each agent receives only its relevant service outputs (context slicing). This minimises token usage and creates explicit, testable contracts per agent.

### Mock data boundary
The frontend repo/scan dashboard is currently driven entirely by `lib/mock-data.ts`. The live API surface (scan triggering, progress polling, WebSocket logs) is fully integrated. The boundary between live and mock data is the `MOCK_REPOSITORIES` export.

### WebSocket event queue
Each scan gets a dedicated `asyncio.Queue`. Events are produced by the orchestrator (Arq worker process) and consumed by the WebSocket endpoint handler. The sentinel `None` unblocks waiting consumers when a scan ends. Queue capacity is 1000 events; overflow drops oldest (not newest) to preserve liveness.

### Runtime-configurable frontend URL
`NEXT_PUBLIC_API_URL` bypasses Next.js build-time baking via `window.__ENV` injection in the root Server Component. The same Docker image works across environments — only a container restart is needed to pick up a new backend URL.
