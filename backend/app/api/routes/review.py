"""Review API routes.

HTTP concerns only — no business logic, no direct DB access, no scoring math.
All work is delegated to the injected orchestrator (write path) and repository
(read path).

Error handling strategy
-----------------------
Domain errors (NotFoundError, ValidationError, AgentExecutionError, etc.)
inherit from AppError and are caught by the global handler in main.py which
maps them to the correct HTTP status codes.  Routes therefore only need to
let those exceptions propagate; they do NOT need try/except for expected
domain errors.

Unexpected exceptions (e.g. database driver crashes) are NOT caught here —
FastAPI's default 500 handler returns a safe generic response.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from app.api.deps import get_orchestrator, get_repository
from app.api.schemas import (
    ErrorResponse,
    ReviewCreatedResponse,
    ReviewRequest,
    ReviewResponse,
    ReviewSummaryResponse,
)
from app.application.orchestrator import EngineeringReviewOrchestrator
from app.core.logging import get_logger
from app.domain.value_objects import RepositoryTarget
from app.infrastructure.db.repository import EngineeringReviewRepository

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/review",
    tags=["Reviews"],
)

# ---------------------------------------------------------------------------
# POST /api/review
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=ReviewCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit repository for engineering review",
    description=(
        "Triggers a full multi-agent engineering review for the given repository. "
        "The review runs synchronously; the response is returned once all agents "
        "have completed (or timed out).  Provide exactly one of `repo_url` or "
        "`local_path`."
    ),
    operation_id="create_review",
    responses={
        202: {"description": "Review completed; review_id returned."},
        422: {"model": ErrorResponse, "description": "Validation error — bad input or inaccessible repo."},
        500: {"model": ErrorResponse, "description": "Unexpected server error."},
        502: {"model": ErrorResponse, "description": "LLM upstream error."},
    },
)
async def create_review(
    request: ReviewRequest,
    orchestrator: EngineeringReviewOrchestrator = Depends(get_orchestrator),
) -> ReviewCreatedResponse:
    """Submit a repository for a full engineering review.

    Returns the ``review_id`` which can be used to fetch the full aggregate or
    the lightweight summary once the review is complete.
    """
    logger.info(
        "api.create_review.start",
        repo_url=request.repo_url,
        local_path=request.local_path,
    )
    target = RepositoryTarget(repo_url=request.repo_url, local_path=request.local_path)
    aggregate = await orchestrator.orchestrate(target)
    logger.info(
        "api.create_review.complete",
        review_id=str(aggregate.review_id),
        overall_score=aggregate.overall_score,
        risk_level=aggregate.risk_level.value,
        status=aggregate.status.value,
    )
    return ReviewCreatedResponse(
        review_id=aggregate.review_id,
        status=aggregate.status.value,
    )


# ---------------------------------------------------------------------------
# GET /api/review/{review_id}
# ---------------------------------------------------------------------------

@router.get(
    "/{review_id}",
    response_model=ReviewResponse,
    summary="Get full engineering review",
    description=(
        "Returns the complete `EngineeringReviewAggregate` including all agent "
        "findings, per-agent scores, issues, and recommendations."
    ),
    operation_id="get_review",
    responses={
        200: {"description": "Full review aggregate."},
        404: {"model": ErrorResponse, "description": "Review not found."},
    },
)
async def get_review(
    review_id: uuid.UUID,
    repository: EngineeringReviewRepository = Depends(get_repository),
) -> ReviewResponse:
    """Retrieve a previously completed engineering review by its ID.

    Raises ``404`` (via ``NotFoundError``) if the review does not exist.
    """
    logger.info("api.get_review", review_id=str(review_id))
    aggregate = await repository.get_by_id(review_id)
    return ReviewResponse(data=aggregate)


# ---------------------------------------------------------------------------
# GET /api/review/{review_id}/summary
# ---------------------------------------------------------------------------

@router.get(
    "/{review_id}/summary",
    response_model=ReviewSummaryResponse,
    summary="Get lightweight review summary",
    description=(
        "Returns only the overall score, risk level, status, and per-agent "
        "scores — without the full issue lists.  Suitable for dashboards and "
        "list views."
    ),
    operation_id="get_review_summary",
    responses={
        200: {"description": "Review summary (scores only)."},
        404: {"model": ErrorResponse, "description": "Review not found."},
    },
)
async def get_review_summary(
    review_id: uuid.UUID,
    repository: EngineeringReviewRepository = Depends(get_repository),
) -> ReviewSummaryResponse:
    """Retrieve a lightweight summary of a completed engineering review.

    Raises ``404`` (via ``NotFoundError``) if the review does not exist.
    """
    logger.info("api.get_review_summary", review_id=str(review_id))
    summary = await repository.get_summary(review_id)
    return ReviewSummaryResponse(data=summary)
