"""Repository pattern for Scan and Repository persistence.

Provides both request-scoped usage (injected AsyncSession) and background-task
usage via :func:`open_scan_repository` which manages its own session lifecycle.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import AsyncIterator

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.domain.enums import ScanStatus
from app.infrastructure.db.models import RepositoryModel, ScanAgentResultModel, ScanModel

logger = get_logger(__name__)


class ScanRepository:
    """Async repository for Scan and Repository persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Repository (source repo) operations
    # ------------------------------------------------------------------

    async def find_repository_by_url(self, repo_url: str) -> RepositoryModel | None:
        """Return an existing RepositoryModel with the given URL, or None."""
        stmt = select(RepositoryModel).where(RepositoryModel.repo_url == repo_url)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_repository(self, repository_id: uuid.UUID) -> RepositoryModel:
        """Return a RepositoryModel by ID; raises NotFoundError if absent."""
        stmt = select(RepositoryModel).where(RepositoryModel.id == repository_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            raise NotFoundError("Repository", str(repository_id))
        return model

    async def list_repositories(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> list[RepositoryModel]:
        """Return a paginated list of all repositories, ordered by creation time desc."""
        stmt = (
            select(RepositoryModel)
            .order_by(RepositoryModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create_repository(
        self,
        name: str,
        repo_url: str | None = None,
        source_type: str | None = None,
        default_branch: str | None = None,
        description: str | None = None,
        language: str | None = None,
        team_size: int | None = None,
    ) -> RepositoryModel:
        """Persist a new RepositoryModel and flush to obtain its ID."""
        model = RepositoryModel(
            id=uuid.uuid4(),
            name=name,
            repo_url=repo_url,
            source_type=source_type,
            default_branch=default_branch,
            description=description,
            language=language,
            team_size=team_size,
            created_at=datetime.now(UTC),
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.commit()
        logger.info("scan_repo.repository_created", id=str(model.id), name=name)
        return model

    async def find_or_create_repository(
        self,
        name: str,
        repo_url: str | None = None,
        source_type: str | None = None,
        default_branch: str | None = None,
        description: str | None = None,
        language: str | None = None,
        team_size: int | None = None,
    ) -> RepositoryModel:
        """Return existing repository (matched by URL) or create a new one."""
        if repo_url:
            existing = await self.find_repository_by_url(repo_url)
            if existing:
                logger.info("scan_repo.repository_reused", id=str(existing.id))
                return existing
        return await self.create_repository(
            name=name,
            repo_url=repo_url,
            source_type=source_type,
            default_branch=default_branch,
            description=description,
            language=language,
            team_size=team_size,
        )

    async def update_repository(
        self,
        repository_id: uuid.UUID,
        name: str | None = None,
        default_branch: str | None = None,
        description: str | None = None,
        language: str | None = None,
        team_size: int | None = None,
    ) -> RepositoryModel:
        """Update mutable fields on a repository; raises NotFoundError if absent."""
        model = await self.get_repository(repository_id)
        if name is not None:
            model.name = name
        if default_branch is not None:
            model.default_branch = default_branch
        if description is not None:
            model.description = description
        if language is not None:
            model.language = language
        if team_size is not None:
            model.team_size = team_size
        await self._session.commit()
        await self._session.refresh(model)
        return model

    async def delete_repository(self, repository_id: uuid.UUID) -> None:
        """Delete a repository and cascade-delete its scans; raises NotFoundError if absent."""
        await self.get_repository(repository_id)  # existence check
        stmt = delete(RepositoryModel).where(RepositoryModel.id == repository_id)
        await self._session.execute(stmt)
        await self._session.commit()
        logger.info("scan_repo.repository_deleted", id=str(repository_id))

    # ------------------------------------------------------------------
    # Scan operations
    # ------------------------------------------------------------------

    async def create_scan(
        self,
        repository_id: uuid.UUID,
        source_type: str,
        source_reference: str,
        scan_id: uuid.UUID | None = None,
        branch: str | None = None,
        scan_mode: str = "deep",
        scan_config_json: dict | None = None,
    ) -> ScanModel:
        """Create a new scan record with status=queued.

        Args:
            scan_id:          Optional pre-generated UUID.  The API handler
                              pre-generates this so the same UUID can be stored
                              in the Redis repo lock.
            branch:           Git branch (GitHub scans only).
            scan_mode:        Resolved mode string ("quick" / "deep" / "security-only").
            scan_config_json: Raw config dict from the API request.
        """
        scan = ScanModel(
            id=scan_id or uuid.uuid4(),
            repository_id=repository_id,
            status=ScanStatus.QUEUED.value,
            progress_percentage=0,
            source_type=source_type,
            source_reference=source_reference,
            branch=branch,
            scan_mode=scan_mode,
            scan_config_json=scan_config_json,
            overall_score=0,
            risk_level="Low",
            created_at=datetime.now(UTC),
        )
        self._session.add(scan)
        await self._session.flush()
        logger.info(
            "scan_repo.scan_created",
            scan_id=str(scan.id),
            source_type=source_type,
            branch=branch,
            scan_mode=scan_mode,
        )
        return scan

    async def list_scans(
        self,
        repository_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
        load_agents: bool = False,
        load_repo: bool = False,
    ) -> list[ScanModel]:
        """Return a paginated list of scans, optionally filtered by repository/status."""
        stmt = (
            select(ScanModel)
            .order_by(ScanModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        opts = []
        if load_agents:
            opts.append(selectinload(ScanModel.agent_results))
        if load_repo:
            opts.append(selectinload(ScanModel.repository))
        if opts:
            stmt = stmt.options(*opts)
        if repository_id is not None:
            stmt = stmt.where(ScanModel.repository_id == repository_id)
        if status is not None:
            stmt = stmt.where(ScanModel.status == status)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_scans_for_trends(
        self,
        repository_id: uuid.UUID,
        branch: str | None = None,
        since: datetime | None = None,
        limit: int = 200,
    ) -> list[ScanModel]:
        """Return completed scans for trend analysis, ordered oldest-first.

        Args:
            repository_id: Filter by repository.
            branch:        Optional branch filter.
            since:         Only scans created on or after this datetime.
            limit:         Max rows (default 200, capped to avoid OOM).
        """
        stmt = (
            select(ScanModel)
            .where(
                ScanModel.repository_id == repository_id,
                ScanModel.status == "completed",
            )
            .order_by(ScanModel.created_at.asc())
            .limit(limit)
        )
        if branch:
            stmt = stmt.where(ScanModel.branch == branch)
        if since is not None:
            stmt = stmt.where(ScanModel.created_at >= since)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_scan(self, scan_id: uuid.UUID) -> ScanModel:
        """Return a ScanModel by ID; raises NotFoundError if absent."""
        stmt = (
            select(ScanModel)
            .options(selectinload(ScanModel.agent_results))
            .where(ScanModel.id == scan_id)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            raise NotFoundError("Scan", str(scan_id))
        return model

    async def get_scan_with_repo(self, scan_id: uuid.UUID) -> ScanModel:
        """Return a ScanModel with agent_results and repository eagerly loaded."""
        stmt = (
            select(ScanModel)
            .options(
                selectinload(ScanModel.agent_results),
                selectinload(ScanModel.repository),
            )
            .where(ScanModel.id == scan_id)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            raise NotFoundError("Scan", str(scan_id))
        return model

    async def count_repositories(self) -> int:
        """Return total count of all repositories."""
        from sqlalchemy import func
        result = await self._session.execute(
            select(func.count()).select_from(RepositoryModel)
        )
        return result.scalar_one() or 0

    async def count_scans(
        self,
        repository_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> int:
        """Return total count of scans, optionally filtered."""
        from sqlalchemy import func
        stmt = select(func.count()).select_from(ScanModel)
        if repository_id is not None:
            stmt = stmt.where(ScanModel.repository_id == repository_id)
        if status is not None:
            stmt = stmt.where(ScanModel.status == status)
        result = await self._session.execute(stmt)
        return result.scalar_one() or 0

    async def get_latest_scan_for_repo(
        self, repository_id: uuid.UUID
    ) -> ScanModel | None:
        """Return the most recent scan for a repository, with agent_results loaded."""
        stmt = (
            select(ScanModel)
            .options(selectinload(ScanModel.agent_results))
            .where(ScanModel.repository_id == repository_id)
            .order_by(ScanModel.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
        """Return a ScanModel by ID; raises NotFoundError if absent."""
        stmt = (
            select(ScanModel)
            .options(selectinload(ScanModel.agent_results))
            .where(ScanModel.id == scan_id)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            raise NotFoundError("Scan", str(scan_id))
        return model

    async def update_scan_progress(self, scan_id: uuid.UUID, progress: int) -> None:
        """Update only the progress_percentage column."""
        stmt = (
            update(ScanModel)
            .where(ScanModel.id == scan_id)
            .values(progress_percentage=progress)
        )
        await self._session.execute(stmt)
        await self._session.commit()

    async def update_scan_status(
        self,
        scan_id: uuid.UUID,
        status: ScanStatus,
        progress: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update scan status (and optionally progress/error)."""
        values: dict = {"status": status.value}
        if progress is not None:
            values["progress_percentage"] = progress
        if error_message is not None:
            values["error_message"] = error_message[:4096]  # guard against large traces
        stmt = update(ScanModel).where(ScanModel.id == scan_id).values(**values)
        await self._session.execute(stmt)
        await self._session.commit()
        logger.info(
            "scan_repo.status_updated",
            scan_id=str(scan_id),
            status=status.value,
            progress=progress,
        )

    async def save_scan_results(
        self,
        scan_id: uuid.UUID,
        overall_score: int,
        risk_level: str,
        agent_findings: list[dict],
        overall_confidence: float = 0.5,
        radar_json: dict | None = None,
    ) -> None:
        """Persist final scan scores, per-agent findings with confidence, then mark completed."""
        for finding in agent_findings:
            agent_model = ScanAgentResultModel(
                id=uuid.uuid4(),
                scan_id=scan_id,
                agent_name=finding["agent_name"],
                score=finding["score"],
                summary=finding["summary"],
                confidence=finding.get("confidence", 0.5),
                confidence_reason=finding.get("confidence_reason", ""),
                issues=finding.get("issues", []),
                recommendations=finding.get("recommendations", []),
            )
            self._session.add(agent_model)

        update_vals: dict = {
            "overall_score": overall_score,
            "risk_level": risk_level,
            "status": ScanStatus.COMPLETED.value,
            "progress_percentage": 100,
            "overall_confidence": overall_confidence,
        }
        if radar_json is not None:
            update_vals["radar_json"] = radar_json

        stmt = update(ScanModel).where(ScanModel.id == scan_id).values(**update_vals)
        await self._session.execute(stmt)
        await self._session.commit()
        logger.info(
            "scan_repo.results_saved",
            scan_id=str(scan_id),
            overall_score=overall_score,
            risk_level=risk_level,
            overall_confidence=overall_confidence,
        )

    async def save_patch_diff(self, scan_id: uuid.UUID, patch_diff: str) -> None:
        """Persist the generated patch diff for later retrieval via the patch endpoint."""
        stmt = (
            update(ScanModel)
            .where(ScanModel.id == scan_id)
            .values(patch_diff=patch_diff[:1_000_000])  # cap at 1 MB
        )
        await self._session.execute(stmt)
        await self._session.commit()
        logger.info("scan_repo.patch_saved", scan_id=str(scan_id))


@asynccontextmanager
async def open_scan_repository() -> AsyncIterator[ScanRepository]:
    """Async context manager that provides a ScanRepository with its own session.

    Intended for use **outside** the FastAPI request lifecycle (background tasks).
    The session is committed and closed on exit.
    """
    from app.infrastructure.db.session import AsyncSessionFactory

    async with AsyncSessionFactory() as session:
        yield ScanRepository(session)

