"""Request-ID middleware.

Every request is tagged with a unique trace identifier:

* Reads the incoming ``X-Request-ID`` header when present (caller-supplied
  correlation ID — useful for tracing across microservices).
* Falls back to a freshly-generated ``uuid4`` when the header is absent.

The resolved ID is:

1. Stored on ``request.state.request_id`` so any downstream handler or
   exception handler can read it without re-parsing headers.
2. Echoed back on the ``X-Request-ID`` **response** header so clients can
   correlate logs / error reports with the request that caused them.

Usage
-----
Register once in ``create_app()``::

    from app.middleware.request_id import RequestIDMiddleware
    app.add_middleware(RequestIDMiddleware)

Order matters — add this *before* (i.e. register *after*) other middleware
so the request ID is available to all subsequent layers.
"""
from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

REQUEST_ID_HEADER = "X-Request-ID"
"""Canonical header name for the request correlation identifier."""

_MAX_HEADER_LENGTH = 128
"""Guard against oversized caller-supplied IDs being echoed back."""


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that attaches a trace ID to every request.

    Attributes:
        generate_id: Callable used to mint a new ID when the header is absent.
            Defaults to :func:`uuid.uuid4` (rendered as a lowercase hex string).
    """

    def __init__(self, app: ASGIApp, *, generate_id=None) -> None:
        super().__init__(app)
        self._generate_id = generate_id or (lambda: str(uuid.uuid4()))

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        raw = request.headers.get(REQUEST_ID_HEADER, "").strip()
        # Accept caller-supplied IDs but sanitise length to prevent header inflation.
        request_id = raw[:_MAX_HEADER_LENGTH] if raw else self._generate_id()

        request.state.request_id = request_id

        response: Response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
