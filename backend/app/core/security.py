"""OpenAPI / Swagger security scheme helpers.

Defines the JWT Bearer scheme and injects global OpenAPI components into the
generated schema:

* ``BearerAuth`` — JWT HTTP Bearer security scheme (adds the Authorize button).
* ``components.headers`` — ``X-Request-ID``, ``X-RateLimit-*`` headers.
* ``components.responses`` — ``RateLimited`` (429) and ``InternalError`` (500)
  shared response objects.
* ``info.x-logo`` — platform logo for ReDoc.

Usage
-----
Import ``inject_security_scheme`` and call it once in ``create_app()`` after
the FastAPI instance is created::

    from app.core.security import inject_security_scheme
    inject_security_scheme(app)

Optional route-level protection
---------------------------------
For routes that *should* require a token, add the dependency::

    from app.core.security import require_bearer

    @router.get("/protected", dependencies=[Depends(require_bearer)])
    async def protected(): ...
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

if TYPE_CHECKING:
    from fastapi import FastAPI

# ---------------------------------------------------------------------------
# Bearer scheme — re-exported so routes can declare it as a dependency.
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(
    scheme_name="BearerAuth",
    description="JWT Bearer token.  Prefix: **Bearer &lt;token&gt;**",
    auto_error=False,
)


async def require_bearer(
    credentials: HTTPAuthorizationCredentials | None = None,
) -> HTTPAuthorizationCredentials:
    """Dependency that requires a Bearer token.

    Does **not** verify the token — add signature verification here if needed.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials


# ---------------------------------------------------------------------------
# OpenAPI component definitions
# ---------------------------------------------------------------------------

_SECURITY_SCHEMES: dict = {
    "BearerAuth": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": (
            "JWT Bearer authentication.  "
            "Click **Authorize**, enter your token, and all subsequent "
            "requests will include ``Authorization: Bearer <token>``."
        ),
    }
}

_HEADER_COMPONENTS: dict = {
    "X-Request-ID": {
        "description": (
            "Unique UUID trace identifier attached to every request and echoed "
            "on every response.  Supply your own value in the request header to "
            "propagate a correlation ID across service boundaries; the server "
            "generates one automatically when the header is absent."
        ),
        "schema": {"type": "string", "format": "uuid"},
        "example": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    },
    "X-RateLimit-Limit": {
        "description": "Maximum number of requests allowed in the current rate-limit window.",
        "schema": {"type": "integer"},
        "example": 100,
    },
    "X-RateLimit-Remaining": {
        "description": "Number of requests remaining in the current rate-limit window.",
        "schema": {"type": "integer"},
        "example": 94,
    },
    "X-RateLimit-Reset": {
        "description": (
            "Unix timestamp (seconds since epoch) at which the current "
            "rate-limit window resets and the counter is cleared."
        ),
        "schema": {"type": "integer", "format": "int64"},
        "example": 1737000000,
    },
}

_SHARED_RESPONSES: dict = {
    "RateLimited": {
        "description": (
            "**429 Too Many Requests** — the client has exceeded the allowed "
            "request rate.  Retry after the time indicated by ``X-RateLimit-Reset``."
        ),
        "headers": {
            "X-RateLimit-Limit":     {"$ref": "#/components/headers/X-RateLimit-Limit"},
            "X-RateLimit-Remaining": {"$ref": "#/components/headers/X-RateLimit-Remaining"},
            "X-RateLimit-Reset":     {"$ref": "#/components/headers/X-RateLimit-Reset"},
            "X-Request-ID":          {"$ref": "#/components/headers/X-Request-ID"},
            "Retry-After": {
                "description": "Seconds to wait before retrying.",
                "schema": {"type": "integer"},
            },
        },
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                "example": {
                    "error_code": "RATE_LIMITED",
                    "detail": "Too many requests. Please slow down.",
                    "status_code": 429,
                    "request_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "timestamp": "2025-01-15T12:34:56.789Z",
                    "path": "/api/scans/run",
                },
            }
        },
    },
    "InternalError": {
        "description": (
            "**500 Internal Server Error** — an unexpected server-side error "
            "occurred.  Include the ``request_id`` when reporting the issue."
        ),
        "headers": {
            "X-Request-ID": {"$ref": "#/components/headers/X-Request-ID"},
        },
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                "example": {
                    "error_code": "INTERNAL_ERROR",
                    "detail": "An unexpected error occurred.",
                    "status_code": 500,
                    "request_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "timestamp": "2025-01-15T12:34:56.789Z",
                    "path": "/api/scans/run",
                },
            }
        },
    },
}


def inject_security_scheme(app: "FastAPI") -> None:
    """Patch *app*.openapi() to inject JWT Bearer, rate-limit headers,
    and shared error responses into the OpenAPI schema.

    Idempotent — caches the result on ``app.openapi_schema``.
    """
    from fastapi.openapi.utils import get_openapi

    def _custom_openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema

        schema = get_openapi(
            title=app.title,
            version=app.version,
            openapi_version=app.openapi_version,
            description=app.description,
            terms_of_service=app.terms_of_service,
            contact=app.contact,
            license_info=app.license_info,
            routes=app.routes,
            tags=app.openapi_tags,
            servers=app.servers,
        )

        # ── Security schemes ────────────────────────────────────────────
        comps: dict = schema.setdefault("components", {})
        comps.setdefault("securitySchemes", {}).update(_SECURITY_SCHEMES)

        # ── Rate-limit + trace headers ──────────────────────────────────
        comps.setdefault("headers", {}).update(_HEADER_COMPONENTS)

        # ── Shared error responses ──────────────────────────────────────
        comps.setdefault("responses", {}).update(_SHARED_RESPONSES)

        app.openapi_schema = schema
        return schema

    app.openapi = _custom_openapi  # type: ignore[method-assign]

