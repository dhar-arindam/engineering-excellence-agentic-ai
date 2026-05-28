"""GitHub webhook API route.

Endpoint
--------
POST /api/github/webhook

Handles GitHub ``pull_request`` webhook events:
* Ignores non-``pull_request`` events gracefully (returns 200)
* Ignores ``pull_request`` events with non-actionable actions (closed, etc.)
* Runs the PR review pipeline via :class:`PRWebhookProcessor` as a
  FastAPI ``BackgroundTask`` so the webhook receives a fast 202 response
  before the scan completes (GitHub's webhook timeout is ~10 seconds)

Note
----
HMAC signature verification is disabled when using GitHub MCP server.
If you re-enable GitHub webhooks, add ``github_webhook_secret`` to config.py
and uncomment the verification logic in ``_verify_signature()``.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status

from app.api.deps import get_github_client, get_orchestrator_for_webhook
from app.core.config import settings
from app.infrastructure.github.models import WebhookPayload
from app.infrastructure.github.pr_comment_formatter import PRCommentFormatter
from app.infrastructure.github.webhook_processor import PRWebhookProcessor

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/github",
    tags=["GitHub"],
)

_PULL_REQUEST_EVENT = "pull_request"


# ---------------------------------------------------------------------------
# POST /api/github/webhook
# ---------------------------------------------------------------------------


@router.post(
    "/webhook",
    status_code=status.HTTP_202_ACCEPTED,
    summary="GitHub webhook receiver",
    description=(
        "Receives GitHub webhook events. "
        "Processes ``pull_request`` events (opened / synchronize / reopened) "
        "by running a targeted engineering review and posting a summary comment. "
        "All other events are acknowledged with 202 and ignored."
    ),
    operation_id="github_webhook",
    responses={
        202: {"description": "Event accepted and queued for processing."},
        400: {"description": "Malformed payload or invalid JSON."},
        401: {"description": "Signature verification failed."},
    },
)
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_github_event: str = Header(default="", alias="X-GitHub-Event"),
    x_hub_signature_256: str = Header(default="", alias="X-Hub-Signature-256"),
) -> dict:
    """Receive and process a GitHub webhook event.

    The handler returns **immediately** with 202; actual PR processing runs
    in the background to respect GitHub's webhook timeout.
    """
    raw_body: bytes = await request.body()

    # --- Signature verification ---
    _verify_signature(raw_body, x_hub_signature_256)

    logger.info(
        "webhook.received",
        extra={"event": x_github_event},
    )

    # --- Ignore non-PR events ---
    if x_github_event != _PULL_REQUEST_EVENT:
        logger.debug("webhook.ignored", extra={"event": x_github_event})
        return {"status": "ignored", "event": x_github_event}

    # --- Parse payload ---
    try:
        payload_dict = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON payload: {exc}",
        )

    try:
        payload = WebhookPayload.model_validate(payload_dict)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unexpected payload shape: {exc}",
        )

    # --- Ignore non-actionable actions (closed, edited, etc.) ---
    if not payload.is_actionable:
        logger.info(
            "webhook.pr_action_ignored",
            extra={"action": payload.action},
        )
        return {"status": "ignored", "action": payload.action}

    # --- Schedule background processing ---
    github_client = get_github_client()
    orchestrator = await get_orchestrator_for_webhook()
    processor = PRWebhookProcessor(
        github_client=github_client,
        orchestrator=orchestrator,
        formatter=PRCommentFormatter(),
    )

    background_tasks.add_task(_process_pr_event, processor, payload)

    logger.info(
        "webhook.pr_queued",
        extra={
            "owner": payload.repository.owner_login,
            "repo": payload.repository.name,
            "pr_number": payload.pull_request.number,
            "action": payload.action,
        },
    )
    return {
        "status": "queued",
        "pr_number": payload.pull_request.number,
        "action": payload.action,
    }


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------


async def _process_pr_event(
    processor: PRWebhookProcessor,
    payload: WebhookPayload,
) -> None:
    """Execute the PR review pipeline; log errors without re-raising."""
    try:
        await processor.process(payload)
    except Exception as exc:
        logger.exception(
            "webhook.pr_processing_failed",
            extra={
                "owner": payload.repository.owner_login,
                "repo": payload.repository.name,
                "pr_number": payload.pull_request.number,
                "error": str(exc),
            },
        )


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def _verify_signature(body: bytes, signature_header: str) -> None:
    """Verify the ``X-Hub-Signature-256`` HMAC-SHA256 signature.

    Currently a no-op; verification is disabled when using GitHub MCP server.

    Args:
        body:             Raw request body bytes.
        signature_header: Value of ``X-Hub-Signature-256`` header.
    """
    # Webhook verification is disabled when using GitHub MCP server.
    # If you re-enable webhooks, configure github_webhook_secret in settings.
    return

