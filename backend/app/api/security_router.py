"""
GET /api/security/overview — returns per-repository security posture based on
the latest completed scan that contains a Security agent result.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.mappers import _agent_type
from app.api.schemas import SecurityOverviewResponse, SecurityRepoEntry
from app.core.logging import get_logger
from app.infrastructure.db.models import RepositoryModel, ScanAgentResultModel, ScanModel
from app.infrastructure.db.session import get_db_session

logger = get_logger(__name__)

router = APIRouter(prefix="/api/security", tags=["Security"])


def _score_to_risk(score: int) -> str:
    """Map a security score to a risk label."""
    if score >= 80:
        return "Low"
    if score >= 60:
        return "Medium"
    if score >= 40:
        return "High"
    return "Critical"


@router.get(
    "/overview",
    response_model=SecurityOverviewResponse,
    summary="Security posture overview",
    description=(
        "Returns a per-repository security summary derived from the latest completed "
        "scan that has a Security agent result. Repositories with no completed security "
        "scans are omitted. Risk is derived from the security score: "
        ">=80 → Low, >=60 → Medium, >=40 → High, <40 → Critical."
    ),
    operation_id="get_security_overview",
)
async def get_security_overview(
    session: AsyncSession = Depends(get_db_session),
) -> SecurityOverviewResponse:
    try:
        # Fetch all repositories
        repos_result = await session.execute(
            select(RepositoryModel).order_by(RepositoryModel.created_at.desc())
        )
        repositories = list(repos_result.scalars().all())

        if not repositories:
            return SecurityOverviewResponse(
                repositories=[],
                critical_count=0,
                high_count=0,
                medium_count=0,
                low_count=0,
            )

        repo_ids = [repo.id for repo in repositories]

        # Fetch all completed scans for those repos, with agent results eagerly loaded
        scans_result = await session.execute(
            select(ScanModel)
            .where(
                ScanModel.repository_id.in_(repo_ids),
                ScanModel.status == "completed",
            )
            .options(selectinload(ScanModel.agent_results))
            .order_by(ScanModel.created_at.desc())
        )
        all_scans = list(scans_result.scalars().all())

        # Build a map: repo_id → latest scan with a Security agent result
        repo_id_to_repo: dict[str, RepositoryModel] = {str(r.id): r for r in repositories}
        best_scan_per_repo: dict[str, tuple[ScanModel, ScanAgentResultModel]] = {}

        for scan in all_scans:
            repo_key = str(scan.repository_id)
            if repo_key in best_scan_per_repo:
                # Already found a newer scan with security result for this repo
                continue
            for ar in scan.agent_results or []:
                if _agent_type(ar.agent_name) == "Security":
                    best_scan_per_repo[repo_key] = (scan, ar)
                    break  # found security result for this scan; move to next scan

        # Build response entries
        entries: list[SecurityRepoEntry] = []
        for repo_key, (scan, security_result) in best_scan_per_repo.items():
            repo = repo_id_to_repo.get(repo_key)
            if repo is None:
                continue

            score = security_result.score
            open_issues = (
                len(security_result.issues)
                if isinstance(security_result.issues, list)
                else 0
            )
            last_scan_date = scan.created_at.isoformat() if scan.created_at else ""

            entries.append(
                SecurityRepoEntry(
                    repository_id=repo_key,
                    repository_name=repo.name,
                    security_score=score,
                    risk=_score_to_risk(score),
                    open_issues=open_issues,
                    last_scan_date=last_scan_date,
                    scan_id=str(scan.id),
                )
            )

        # Count by risk level
        critical_count = sum(1 for e in entries if e.risk == "Critical")
        high_count = sum(1 for e in entries if e.risk == "High")
        medium_count = sum(1 for e in entries if e.risk == "Medium")
        low_count = sum(1 for e in entries if e.risk == "Low")

        return SecurityOverviewResponse(
            repositories=entries,
            critical_count=critical_count,
            high_count=high_count,
            medium_count=medium_count,
            low_count=low_count,
        )

    except Exception:
        logger.exception("Failed to fetch security overview data")
        raise
