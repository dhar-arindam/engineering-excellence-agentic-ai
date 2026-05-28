"""
GET /api/agents/performance — returns per-agent performance summary across all completed scans.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.mappers import _agent_type
from app.api.schemas import AgentPerformanceEntry, AgentRecentScore, AgentsPerformanceResponse
from app.core.logging import get_logger
from app.infrastructure.db.models import RepositoryModel, ScanAgentResultModel, ScanModel
from app.infrastructure.db.session import get_db_session

logger = get_logger(__name__)

router = APIRouter(prefix="/api/agents", tags=["Agents"])

KNOWN_AGENTS: list[str] = ["QA", "Dev", "Architect", "SRE", "Security"]

_AGENT_DESCRIPTIONS: dict[str, str] = {
    "QA": "Test coverage, assertion quality, and test-to-code ratio analysis",
    "Dev": "Code quality, patterns, complexity, and implementation best practices",
    "Architect": "Architecture patterns, layer violations, and dependency analysis",
    "SRE": "CI/CD configuration, infrastructure readiness, and operational concerns",
    "Security": "Vulnerability detection, secret scanning, and security pattern analysis",
}


@router.get(
    "/performance",
    response_model=AgentsPerformanceResponse,
    summary="Agent performance analytics",
    description=(
        "Returns a per-agent performance summary aggregated across the latest 50 "
        "completed scans. Agents with no runs still appear with avg_score=0 and "
        "total_runs=0. Security is listed first; remaining agents are sorted alphabetically."
    ),
    operation_id="get_agents_performance",
)
async def get_agents_performance(
    session: AsyncSession = Depends(get_db_session),
) -> AgentsPerformanceResponse:
    try:
        # Step 1: subquery — latest 50 completed scan IDs ordered by created_at DESC
        latest_scan_ids_sq = (
            select(ScanModel.id)
            .where(ScanModel.status == "completed")
            .order_by(ScanModel.created_at.desc())
            .limit(50)
            .subquery()
        )

        # Step 2: fetch agent results for those scans, eagerly loading scan + repository
        stmt = (
            select(ScanAgentResultModel)
            .where(ScanAgentResultModel.scan_id.in_(select(latest_scan_ids_sq)))
            .options(
                selectinload(ScanAgentResultModel.scan).selectinload(ScanModel.repository)
            )
        )
        result = await session.execute(stmt)
        agent_results = list(result.scalars().all())

        # Step 3: collect the set of distinct completed scan IDs found in results
        scanned_ids: set[str] = set()
        for ar in agent_results:
            scanned_ids.add(str(ar.scan_id))

        # Step 4: group by normalised agent name
        grouped: dict[str, list[ScanAgentResultModel]] = {name: [] for name in KNOWN_AGENTS}
        for ar in agent_results:
            normalised = _agent_type(ar.agent_name)
            if normalised in grouped:
                grouped[normalised].append(ar)
            else:
                # Unknown agent type — still collect under its normalised name
                grouped.setdefault(normalised, []).append(ar)

        # Step 5 & 6: build AgentPerformanceEntry per known agent
        entries: list[AgentPerformanceEntry] = []
        for name in KNOWN_AGENTS:
            runs = grouped.get(name, [])
            total_runs = len(runs)
            avg_score = round(sum(r.score for r in runs) / total_runs, 2) if total_runs else 0.0

            # Up to 5 most recent scores (results already came back unordered; sort by scan date)
            sorted_runs = sorted(
                runs,
                key=lambda r: (r.scan.created_at if r.scan else None) or "",
                reverse=True,
            )
            recent_scores: list[AgentRecentScore] = []
            for r in sorted_runs[:5]:
                repo_name = ""
                scan_date = ""
                if r.scan:
                    scan_date = r.scan.created_at.isoformat() if r.scan.created_at else ""
                    if r.scan.repository:
                        repo_name = r.scan.repository.name
                recent_scores.append(
                    AgentRecentScore(
                        scan_id=str(r.scan_id),
                        repository_name=repo_name,
                        score=r.score,
                        date=scan_date,
                    )
                )

            entries.append(
                AgentPerformanceEntry(
                    name=name,
                    avg_score=avg_score,
                    total_runs=total_runs,
                    description=_AGENT_DESCRIPTIONS.get(name, ""),
                    recent_scores=recent_scores,
                )
            )

        # Step 7: Security first, then alphabetically
        entries.sort(key=lambda e: (0 if e.name == "Security" else 1, e.name))

        return AgentsPerformanceResponse(
            agents=entries,
            total_scans_analysed=len(scanned_ids),
        )

    except Exception:
        logger.exception("Failed to fetch agent performance data")
        raise
