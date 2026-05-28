"""FastAPI application factory."""
from __future__ import annotations

import datetime
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.agents_router import router as agents_router
from app.api.auth import router as auth_router
from app.api.repos import router as repos_router
from app.api.repositories import router as repositories_router
from app.api.routes.github import router as github_router
from app.api.routes.review import router as review_router
from app.api.scans import router as scans_router
from app.api.security_router import router as security_router
from app.api.websocket import router as websocket_router
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging
from app.core.security import inject_security_scheme
from app.middleware.request_id import REQUEST_ID_HEADER, RequestIDMiddleware

# ---------------------------------------------------------------------------
# OpenAPI tags metadata — controls display order and descriptions in Swagger.
# ---------------------------------------------------------------------------

_OPENAPI_TAGS: list[dict] = [
    {
        "name": "Repositories",
        "description": (
            "Register and manage source repositories.  Repositories are the "
            "top-level entity that groups scans.  Both GitHub URLs and local "
            "filesystem paths are supported."
        ),
    },
    {
        "name": "Fix",
        "description": (
            "Retrieve the auto-generated patch diff and create a validated "
            "GitHub pull request.  PR creation only proceeds if the patch "
            "passes lint, tests, type-check, and breaking-change detection."
        ),
    },
    {
        "name": "Annotations",
        "description": (
            "Code-level findings extracted from agent results.  "
            "``/annotations`` returns all findings; ``/patch-annotations`` "
            "returns only findings with file and line information, suitable "
            "for inline diff rendering."
        ),
    },
    {
        "name": "Auth",
        "description": "Lightweight identity endpoints for local development environments.",
    },
    {
        "name": "Scans",
        "description": (
            "Trigger multi-agent scans, poll progress, and cancel running jobs. "
            "Scans run asynchronously via the Arq task queue; use the status "
            "endpoint or the WebSocket stream to track execution in real time."
        ),
    },
    {
        "name": "Reviews",
        "description": (
            "Synchronous engineering reviews — submit a repository and receive "
            "a full multi-agent aggregate result in a single HTTP response."
        ),
    },
    {
        "name": "WebSocket",
        "description": (
            "Live scan log streaming over WebSocket.  Connect to "
            "``/ws/scans/{scan_id}`` to receive ``log``, ``progress``, and "
            "``status`` events in real time."
        ),
        "externalDocs": {
            "description": "WebSocket event schema",
            "url": "https://github.com/your-org/ai-multi-agent#websocket-events",
        },
    },
    {
        "name": "GitHub",
        "description": (
            "GitHub webhook receiver.  Handles ``pull_request`` events by "
            "triggering a targeted review and posting a summary comment."
        ),
    },
    {
        "name": "Agents",
        "description": "Agent performance analytics across completed scans",
    },
    {
        "name": "Security",
        "description": "Security posture analysis and per-repository security scores",
    },
    {
        "name": "Health",
        "description": "Liveness and readiness probes for infrastructure monitoring.",
    },
]

_API_DESCRIPTION = """\
**Engineering Intelligence Platform** — AI-powered backend for multi-agent
code analysis, validation, and automated PR generation.

## Key capabilities

- 🔍 **Multi-agent scan** — QA, Developer, Architect, SRE, and Security agents
  run in parallel to produce a scored engineering assessment.
- 🌿 **Branch & config support** — target any Git branch with `quick`, `deep`,
  or `security-only` scan modes.
- 🔧 **Auto-fix pipeline** — optional patch generation, validation, breaking-change
  detection, and safe PR creation.
- 📡 **Live streaming** — WebSocket endpoint streams log/progress/status events
  as the scan executes.
- 🔗 **GitHub webhooks** — automatically reviews pull requests on open/sync events.

## Authentication

All protected endpoints expect an ``Authorization: Bearer <token>`` header.
Click **Authorize** above to set your token for interactive testing.

## Trace headers

Every response includes an ``X-Request-ID`` header.  Pass your own value on
the request to propagate a correlation ID across service calls; a UUID is
auto-generated when absent.

## Rate limiting

Responses include ``X-RateLimit-Limit``, ``X-RateLimit-Remaining``, and
``X-RateLimit-Reset`` headers.  See the rate-limit banner below for details.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage app-level resources: Arq Redis pool."""
    from app.infrastructure.redis_client import create_redis_pool

    app.state.arq_pool = await create_redis_pool()
    yield
    await app.state.arq_pool.aclose()


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title="Engineering Intelligence Platform API",
        description=_API_DESCRIPTION,
        version="1.0.0",
        contact={
            "name": "Platform Engineering Team",
            "email": "platform-team@company.com",
            "url": "https://github.com/your-org/ai-multi-agent",
        },
        license_info={
            "name": "MIT",
            "url": "https://opensource.org/licenses/MIT",
        },
        servers=[
            {"url": "http://localhost:8000", "description": "Local development"},
            {"url": "https://api.engineeriq.example.com", "description": "Production"},
        ],
        openapi_tags=_OPENAPI_TAGS,
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url="/redoc" if settings.enable_docs else None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
        lifespan=lifespan,
    )

    # ── Middleware (outermost → innermost; declared in reverse application order)

    # Request-ID must be registered last (applied first) so that the
    # request_id is available to all downstream handlers and error handlers.
    app.add_middleware(RequestIDMiddleware)

    # CORS — restrict to configured origins; never wildcard in production.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*", REQUEST_ID_HEADER],
        expose_headers=[
            REQUEST_ID_HEADER,
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
        ],
    )

    # ── Error handler ───────────────────────────────────────────────────────

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        request_id: Optional[str] = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error_code": _status_to_error_code(exc.status_code),
                "detail": exc.message,
                "status_code": exc.status_code,
                "request_id": request_id,
                "timestamp": _utc_now(),
                "path": request.url.path,
            },
            headers={REQUEST_ID_HEADER: request_id} if request_id else {},
        )

    # ── Health endpoint ─────────────────────────────────────────────────────

    @app.get(
        "/health",
        tags=["Health"],
        summary="Health check",
        description="Returns service liveness status and the active environment name.",
        operation_id="health_check",
        responses={
            200: {
                "description": "Service is healthy.",
                "content": {
                    "application/json": {
                        "example": {"status": "ok", "env": "development"}
                    }
                },
            }
        },
    )
    async def health() -> dict:  # type: ignore[type-arg]
        return {"status": "ok", "env": settings.app_env}

    # ── Routers ─────────────────────────────────────────────────────────────

    app.include_router(repositories_router)
    app.include_router(review_router)
    app.include_router(github_router)
    app.include_router(scans_router)
    app.include_router(websocket_router)
    app.include_router(auth_router)
    app.include_router(repos_router)
    app.include_router(agents_router)
    app.include_router(security_router)

    # Inject JWT Bearer + rate-limit headers into the OpenAPI schema.
    inject_security_scheme(app)

    return app


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string with milliseconds."""
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.datetime.now(datetime.timezone.utc).microsecond // 1000:03d}Z"


def _status_to_error_code(status_code: int) -> str:
    """Map an HTTP status code to a machine-readable error category string."""
    _map = {
        400: "VALIDATION_ERROR",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "UNPROCESSABLE_ENTITY",
        429: "RATE_LIMITED",
        500: "INTERNAL_ERROR",
        502: "BAD_GATEWAY",
        503: "SERVICE_UNAVAILABLE",
    }
    return _map.get(status_code, f"HTTP_{status_code}")


app = create_app()

