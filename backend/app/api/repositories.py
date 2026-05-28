"""Repository routes — frontend-aligned responses.

Endpoint surface used by the UI:
  GET    /api/repositories                          — sidebar repo list
  POST   /api/repositories                          — create a new repository record
  GET    /api/repositories/{repo_id}                — repo detail page
  PATCH  /api/repositories/{repo_id}                — update repository metadata
  DELETE /api/repositories/{repo_id}                — remove record (NOT the actual code)
  GET    /api/repositories/{repo_id}/scans          — scan history for a repo
  GET    /api/repositories/{repo_id}/scans/{scan_id} — scan detail inside a repo
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.mappers import repo_to_full, repo_to_list_item, scan_to_full, scan_to_summary
from app.api.schemas import (
    AggregatedTrendSchema,
    CreateRepositoryBodyRequest,
    ErrorResponse,
    RepositoryFullSchema,
    RepositoryListEnvelope,
    RepositoryListItemSchema,
    RepositoryTrendsSchema,
    ScanFullSchema,
    ScanSummarySchema,
    TrendDataPointSchema,
    TrendRadarDimensionSchema,
    UpdateRepositoryBodyRequest,
)
from app.core.logging import get_logger
from app.infrastructure.db.models import RepositoryModel, ScanModel
from app.infrastructure.db.scan_repository import ScanRepository
from app.infrastructure.db.session import get_db_session

logger = get_logger(__name__)

router = APIRouter(prefix="/api/repositories", tags=["Repositories"])


# ── Dependency ───────────────────────────────────────────────────────────────

async def _get_repo(session: AsyncSession = Depends(get_db_session)) -> ScanRepository:
    return ScanRepository(session)


# ── GET /api/repositories ────────────────────────────────────────────────────

@router.get(
    "",
    response_model=RepositoryListEnvelope,
    summary="List all repositories",
    description=(
        "Returns a paginated list of repositories with their latest scan scores, "
        "risk levels, and issue counts."
    ),
    operation_id="list_repositories",
    responses={200: {"description": "Repository list."}},
)
async def list_repositories(
    limit: int = Query(default=20, ge=1, le=100, description="Max results."),
    offset: int = Query(default=0, ge=0, description="Pagination offset."),
    repo: ScanRepository = Depends(_get_repo),
) -> RepositoryListEnvelope:
    models = await repo.list_repositories(limit=limit, offset=offset)
    total = await repo.count_repositories()
    logger.info("api.list_repositories", count=len(models), total=total)

    items = []
    for model in models:
        latest_scan = await repo.get_latest_scan_for_repo(model.id)
        scan_count = await repo.count_scans(repository_id=model.id)
        items.append(repo_to_list_item(model, latest_scan, scan_count))

    return RepositoryListEnvelope(items=items, total=total)


# ── POST /api/repositories ───────────────────────────────────────────────────

@router.post(
    "",
    response_model=RepositoryListItemSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create a repository record",
    description=(
        "Registers a repository in the platform database. "
        "Does NOT clone or modify the actual repository — only creates a tracking record."
    ),
    operation_id="create_repository",
    responses={
        201: {"description": "Repository created."},
        422: {"description": "Validation error."},
    },
)
async def create_repository(
    body: CreateRepositoryBodyRequest,
    repo: ScanRepository = Depends(_get_repo),
) -> RepositoryListItemSchema:
    repo_url = body.repository_url if body.source_type == "github" else body.local_path
    model = await repo.create_repository(
        name=body.name,
        repo_url=repo_url,
        source_type=body.source_type,
        description=body.description,
        language=body.language,
        team_size=body.team_size,
    )
    logger.info("api.create_repository", id=str(model.id), name=model.name)
    return repo_to_list_item(model, latest_scan=None, scan_count=0)


# ── GET /api/repositories/{repo_id} ─────────────────────────────────────────

@router.get(
    "/{repo_id}",
    response_model=RepositoryFullSchema,
    summary="Get repository detail",
    description=(
        "Returns full repository details including agent scores from the latest "
        "scan, score trend, and scan history."
    ),
    operation_id="get_repository",
    responses={
        200: {"description": "Repository details."},
        404: {"model": ErrorResponse, "description": "Repository not found."},
    },
)
async def get_repository(
    repo_id: uuid.UUID,
    repo: ScanRepository = Depends(_get_repo),
) -> RepositoryFullSchema:
    model = await repo.get_repository(repo_id)
    scans = await repo.list_scans(
        repository_id=repo_id,
        limit=50,
        load_agents=True,
    )
    scan_count = await repo.count_scans(repository_id=repo_id)
    return repo_to_full(model, scans, scan_count)


# ── PATCH /api/repositories/{repo_id} ────────────────────────────────────────

@router.patch(
    "/{repo_id}",
    response_model=RepositoryListItemSchema,
    summary="Update repository metadata",
    description=(
        "Updates mutable fields (name, description, language, team_size). "
        "Source type and URL/path cannot be changed after creation."
    ),
    operation_id="update_repository",
    responses={
        200: {"description": "Updated repository."},
        404: {"model": ErrorResponse, "description": "Repository not found."},
    },
)
async def update_repository(
    repo_id: uuid.UUID,
    body: UpdateRepositoryBodyRequest,
    repo: ScanRepository = Depends(_get_repo),
) -> RepositoryListItemSchema:
    model = await repo.update_repository(
        repository_id=repo_id,
        name=body.name,
        description=body.description,
        language=body.language,
        team_size=body.team_size,
    )
    logger.info("api.update_repository", id=str(repo_id))
    latest_scan = await repo.get_latest_scan_for_repo(repo_id)
    scan_count = await repo.count_scans(repository_id=repo_id)
    return repo_to_list_item(model, latest_scan, scan_count)


# ── DELETE /api/repositories/{repo_id} ───────────────────────────────────────

@router.delete(
    "/{repo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a repository record",
    description=(
        "Removes the repository and all its scan history from the platform database. "
        "The actual git repository or local directory is NOT modified or deleted."
    ),
    operation_id="delete_repository",
    responses={
        204: {"description": "Repository deleted."},
        404: {"model": ErrorResponse, "description": "Repository not found."},
    },
)
async def delete_repository(
    repo_id: uuid.UUID,
    repo: ScanRepository = Depends(_get_repo),
) -> None:
    await repo.delete_repository(repo_id)
    logger.info("api.delete_repository", id=str(repo_id))


# ── GET /api/repositories/{repo_id}/scans ────────────────────────────────────

@router.get(
    "/{repo_id}/scans",
    response_model=list[ScanSummarySchema],
    summary="List scans for a repository",
    description="Returns all scans for the given repository, ordered newest first.",
    operation_id="list_repository_scans",
    responses={
        200: {"description": "Scan list."},
        404: {"model": ErrorResponse, "description": "Repository not found."},
    },
)
async def list_repository_scans(
    repo_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    repo: ScanRepository = Depends(_get_repo),
) -> list[ScanSummarySchema]:
    model = await repo.get_repository(repo_id)  # 404 guard
    scans = await repo.list_scans(repository_id=repo_id, limit=limit, offset=offset)
    return [scan_to_summary(s, model.name) for s in scans]


# ── GET /api/repositories/{repo_id}/scans/{scan_id} ─────────────────────────

@router.get(
    "/{repo_id}/scans/{scan_id}",
    response_model=ScanFullSchema,
    summary="Get scan detail within a repository",
    description=(
        "Returns the full scan result (agent scores, issues, drift, risk level, "
        "patch availability) for a specific scan that belongs to this repository."
    ),
    operation_id="get_repository_scan",
    responses={
        200: {"description": "Full scan detail."},
        404: {"model": ErrorResponse, "description": "Repository or scan not found."},
    },
)
async def get_repository_scan(
    repo_id: uuid.UUID,
    scan_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> ScanFullSchema:
    from app.core.exceptions import NotFoundError

    stmt = (
        select(ScanModel)
        .options(
            selectinload(ScanModel.agent_results),
            selectinload(ScanModel.repository),
        )
        .where(ScanModel.id == scan_id, ScanModel.repository_id == repo_id)
    )
    result = await session.execute(stmt)
    scan = result.scalar_one_or_none()
    if scan is None:
        raise NotFoundError("Scan", str(scan_id))

    repo_name = scan.repository.name if scan.repository else ""
    return scan_to_full(scan, repo_name)


# ── GET /api/repositories/{repo_id}/trends ───────────────────────────────────

@router.get(
    "/{repo_id}/trends",
    response_model=RepositoryTrendsSchema,
    summary="Get repository trend history",
    description=(
        "Returns a time-series of completed scans for the repository, "
        "with per-point confidence decay metadata and a weighted aggregate. "
        "Use ?branch=main to filter by branch. Use ?days=30 to limit the window."
    ),
    operation_id="get_repository_trends",
    responses={
        200: {"description": "Trend data."},
        404: {"model": ErrorResponse, "description": "Repository not found."},
    },
)
async def get_repository_trends(
    repo_id: uuid.UUID,
    branch: str | None = Query(default=None, description="Filter by branch name."),
    days: int = Query(default=90, ge=1, le=365, description="Lookback window in days."),
    session: AsyncSession = Depends(get_db_session),
) -> RepositoryTrendsSchema:
    from datetime import UTC, datetime, timedelta

    from app.application.trend_analysis import build_trend_payload
    from app.infrastructure.db.scan_repository import ScanRepository as SR

    repo_db = SR(session)

    # 404 guard
    await repo_db.get_repository(repo_id)

    since = datetime.now(UTC) - timedelta(days=days)
    scans = await repo_db.list_scans_for_trends(
        repository_id=repo_id,
        branch=branch,
        since=since,
    )

    payload = build_trend_payload(repo_id=str(repo_id), scans=scans)

    # Map plain dicts → Pydantic schemas (schema conversion lives in API layer)
    time_series = []
    for pt in payload["time_series"]:
        radar_mapped = {
            dim: TrendRadarDimensionSchema(
                score=v.get("score"),
                confidence=v.get("confidence"),
            )
            for dim, v in pt.get("radar", {}).items()
        }
        time_series.append(
            TrendDataPointSchema(
                timestamp=pt["timestamp"],
                overall_score=pt["overall_score"],
                overall_confidence=pt["overall_confidence"],
                effective_confidence=pt["effective_confidence"],
                radar=radar_mapped,
            )
        )

    agg = payload["aggregated_trend"]
    return RepositoryTrendsSchema(
        repo_id=payload["repo_id"],
        time_series=time_series,
        aggregated_trend=AggregatedTrendSchema(
            overall_score=agg["overall_score"],
            confidence=agg["confidence"],
            trend_warning=agg.get("trend_warning"),
        ),
    )
