"""ScanRepository — async repository for multi-repo historical scan storage.

Responsibilities
----------------
* ``get_or_create_repository``  — idempotent; finds by URL or name, or inserts
* ``save_scan``                 — persist a full ``EngineeringReviewAggregate``
                                  as a Scan + per-agent results + granular issues
* ``get_scan``                  — load one scan with all relationships eager-loaded
* ``list_scans``                — paginated scan history for a repository
* ``get_repository``            — load a repository by ID
* ``list_repositories``         — paginated list of tracked repositories
* ``get_score_trend``           — lightweight time-series of (created_at, score)
                                  for charting engineering health over time

Design notes
------------
* All writes are fire-and-forget from the caller's perspective; the session
  lifecycle (commit / rollback) is managed by the FastAPI dependency layer.
* ``_to_domain`` converts ORM rows back to immutable domain entities so
  application-layer code never deals with ORM state.
* Pagination uses LIMIT/OFFSET; cursor-based pagination can be added later
  without changing the public interface.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.domain.entities import AgentFinding, AgentIssue, EngineeringReviewAggregate
from app.domain.enums import AgentName, ReviewStatus, RiskLevel, Severity
from app.infrastructure.persistence.models import (
    IssueModel,
    RepositoryModel,
    ScanAgentResultModel,
    ScanModel,
)


class ScanRepository:
    """Async repository for multi-repo historical scan persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Repository management
    # ------------------------------------------------------------------

    async def get_or_create_repository(
        self,
        name: str,
        repo_url: Optional[str] = None,
    ) -> RepositoryModel:
        """
        Return an existing :class:`RepositoryModel` or create a new one.

        Lookup priority:
        1. Match by ``repo_url`` (when provided and non-empty)
        2. Match by ``name``
        3. Insert new row
        """
        if repo_url:
            stmt = select(RepositoryModel).where(RepositoryModel.repo_url == repo_url)
            result = await self._session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                return existing

        stmt = select(RepositoryModel).where(RepositoryModel.name == name)
        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        repo = RepositoryModel(name=name, repo_url=repo_url)
        self._session.add(repo)
        await self._session.flush()   # assigns PK without committing
        return repo

    async def get_repository(self, repository_id: uuid.UUID) -> RepositoryModel:
        """Load a repository by primary key."""
        result = await self._session.get(RepositoryModel, repository_id)
        if result is None:
            raise NotFoundError("Repository", str(repository_id))
        return result

    async def list_repositories(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RepositoryModel]:
        """Return all tracked repositories, newest-created first."""
        stmt = (
            select(RepositoryModel)
            .order_by(RepositoryModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Scan persistence
    # ------------------------------------------------------------------

    async def save_scan(
        self,
        repository_id: uuid.UUID,
        aggregate: EngineeringReviewAggregate,
        commit_sha: Optional[str] = None,
    ) -> ScanModel:
        """
        Persist a full engineering review aggregate as a normalised Scan.

        Inserts:
        * One :class:`ScanModel` row
        * One :class:`ScanAgentResultModel` per agent finding
        * One :class:`IssueModel` per issue inside each agent result

        Args:
            repository_id: FK to the target :class:`RepositoryModel`.
            aggregate:     Domain aggregate produced by the orchestrator.
            commit_sha:    Optional Git commit SHA for the scanned revision.

        Returns:
            The persisted :class:`ScanModel` with all children attached.
        """
        scan = ScanModel(
            id=aggregate.review_id,
            repository_id=repository_id,
            overall_score=aggregate.overall_score,
            risk_level=aggregate.risk_level.value,
            status=aggregate.status.value,
            commit_sha=commit_sha,
            created_at=aggregate.created_at,
        )

        for finding in aggregate.agent_results:
            agent_result = ScanAgentResultModel(
                scan_id=aggregate.review_id,
                agent_name=finding.agent_name.value,
                score=finding.score,
                summary=finding.summary,
            )
            for issue in finding.issues:
                agent_result.issues.append(
                    IssueModel(
                        id=issue.id,
                        agent_result_id=agent_result.id,
                        severity=issue.severity.value,
                        file_path=issue.file_path,
                        line_number=issue.line_number,
                        title=issue.title,
                        description=issue.description,
                        recommendation=issue.recommendation,
                    )
                )
            scan.agent_results.append(agent_result)

        self._session.add(scan)
        await self._session.flush()
        return scan

    # ------------------------------------------------------------------
    # Scan retrieval
    # ------------------------------------------------------------------

    async def get_scan(self, scan_id: uuid.UUID) -> ScanModel:
        """Load a scan with all agent results and issues eager-loaded."""
        stmt = (
            select(ScanModel)
            .options(
                selectinload(ScanModel.agent_results).selectinload(
                    ScanAgentResultModel.issues
                )
            )
            .where(ScanModel.id == scan_id)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            raise NotFoundError("Scan", str(scan_id))
        return model

    async def list_scans(
        self,
        repository_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ScanModel]:
        """Return paginated scans for a repository, newest first."""
        stmt = (
            select(ScanModel)
            .where(ScanModel.repository_id == repository_id)
            .order_by(ScanModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_scan(
        self, repository_id: uuid.UUID
    ) -> Optional[ScanModel]:
        """Return the most recent scan for a repository, or ``None``."""
        stmt = (
            select(ScanModel)
            .where(ScanModel.repository_id == repository_id)
            .order_by(ScanModel.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_scans(self, repository_id: uuid.UUID) -> int:
        """Return the total number of scans for a repository."""
        stmt = (
            select(func.count())
            .select_from(ScanModel)
            .where(ScanModel.repository_id == repository_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    # ------------------------------------------------------------------
    # Analytics / trend data
    # ------------------------------------------------------------------

    async def get_score_trend(
        self,
        repository_id: uuid.UUID,
        limit: int = 30,
    ) -> list[dict]:
        """
        Return a lightweight time-series of overall scores.

        Result format (oldest first for chart rendering)::

            [
                {"created_at": datetime, "overall_score": int, "risk_level": str},
                ...
            ]
        """
        stmt = (
            select(
                ScanModel.created_at,
                ScanModel.overall_score,
                ScanModel.risk_level,
                ScanModel.commit_sha,
            )
            .where(ScanModel.repository_id == repository_id)
            .order_by(ScanModel.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        rows = result.all()
        # Reverse so chart data flows left-to-right chronologically
        return [
            {
                "created_at": row.created_at,
                "overall_score": row.overall_score,
                "risk_level": row.risk_level,
                "commit_sha": row.commit_sha,
            }
            for row in reversed(rows)
        ]

    # ------------------------------------------------------------------
    # Domain conversion
    # ------------------------------------------------------------------

    @staticmethod
    def to_domain_aggregate(scan: ScanModel) -> EngineeringReviewAggregate:
        """
        Convert a :class:`ScanModel` (with relationships loaded) back to the
        domain :class:`EngineeringReviewAggregate`.

        Requires ``scan.agent_results`` and ``agent_result.issues`` to be
        already loaded (use :meth:`get_scan` which eager-loads both).
        """
        agent_results = [
            AgentFinding(
                agent_name=AgentName(ar.agent_name),
                score=ar.score,
                summary=ar.summary,
                issues=[
                    AgentIssue(
                        id=issue.id,
                        severity=Severity(issue.severity),
                        file_path=issue.file_path,
                        line_number=issue.line_number,
                        title=issue.title,
                        description=issue.description,
                        recommendation=issue.recommendation,
                    )
                    for issue in (ar.issues or [])
                ],
                recommendations=[],   # not stored in normalised schema
            )
            for ar in (scan.agent_results or [])
        ]
        return EngineeringReviewAggregate(
            review_id=scan.id,
            repo_url=scan.repository.repo_url if scan.repository else None,
            overall_score=scan.overall_score,
            risk_level=RiskLevel(scan.risk_level),
            agent_results=agent_results,
            status=ReviewStatus(scan.status),
            created_at=scan.created_at,
        )
