"""ScanTrendService — historical trend analysis for a tracked repository.

Responsibilities
----------------
* Compute overall score delta between the two most recent scans.
* Compute per-agent score deltas (latest vs previous scan).
* Compute a rolling average of the last 5 overall scores.
* Handle the edge case where the repository has only one scan (or none).

Design notes
------------
* Pure application-layer service: depends only on ``ScanRepository`` (via
  constructor injection) and domain entities.
* No LLM calls, no direct DB access — all data access goes through the
  repository abstraction.
* ``RepositoryTrend`` is an immutable Pydantic v2 model returned to callers
  (API routes, other use-cases).
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.exceptions import NotFoundError
from app.infrastructure.persistence.models import ScanModel
from app.infrastructure.persistence.repository import ScanRepository

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------


class RepositoryTrend(BaseModel):
    """Trend summary for a single repository across its last 5 scans.

    Attributes
    ----------
    repository_id:
        The repository being analysed.
    scan_count:
        How many scans are available (may be less than 5 for new repos).
    latest_score:
        Overall engineering score from the most recent scan.
    previous_score:
        Overall score from the second-most-recent scan, or ``None`` if this
        is the repository's first scan.
    score_delta:
        Difference ``latest_score - previous_score``.  Positive means
        improvement; negative means regression.  ``None`` when there is no
        previous scan.
    agent_deltas:
        Per-agent score change (latest minus previous).  Only agents present
        in *both* scans contribute; absent agents are omitted.
    rolling_average_last_5:
        Mean overall score across the last five scans (or however many exist).
    """

    repository_id: UUID
    scan_count: int = Field(ge=0)
    latest_score: int = Field(ge=0, le=100)
    previous_score: Optional[int] = Field(default=None, ge=0, le=100)
    score_delta: Optional[int] = None
    agent_deltas: dict[str, int] = Field(default_factory=dict)
    rolling_average_last_5: float = Field(ge=0.0, le=100.0)

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ScanTrendService:
    """Compute historical trend data for a tracked repository.

    Parameters
    ----------
    scan_repository:
        Injected ``ScanRepository`` instance bound to the current async
        database session.

    Usage
    -----
    ::

        trend = await ScanTrendService(scan_repo).compute_repository_trend(repo_id)
    """

    def __init__(self, scan_repository: ScanRepository) -> None:
        self._repo = scan_repository

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def compute_repository_trend(
        self, repository_id: UUID
    ) -> RepositoryTrend:
        """Return trend metrics for *repository_id* based on its last 5 scans.

        Parameters
        ----------
        repository_id:
            Primary key of the target :class:`~app.infrastructure.persistence.models.RepositoryModel`.

        Raises
        ------
        NotFoundError
            If the repository does not exist **and** has no scans at all.
        """
        logger.info(
            "computing_trend",
            extra={"repository_id": str(repository_id)},
        )

        # 1. Fetch up to 5 most-recent scans (lightweight rows, no agent data).
        recent_scans: list[ScanModel] = await self._repo.list_scans(
            repository_id, limit=5, offset=0
        )

        if not recent_scans:
            raise NotFoundError("Repository", str(repository_id))

        # 2. Rolling average uses overall_score from all fetched rows.
        scores = [s.overall_score for s in recent_scans]
        rolling_avg = sum(scores) / len(scores)

        latest_score: int = recent_scans[0].overall_score
        previous_score: Optional[int] = None
        score_delta: Optional[int] = None
        agent_deltas: dict[str, int] = {}

        # 3. Per-agent deltas require loading the top-2 scans with relationships.
        if len(recent_scans) >= 2:
            previous_score = recent_scans[1].overall_score
            score_delta = latest_score - previous_score

            latest_full, previous_full = await self._load_two_scans(
                recent_scans[0], recent_scans[1]
            )
            agent_deltas = self._compute_agent_deltas(latest_full, previous_full)

        trend = RepositoryTrend(
            repository_id=repository_id,
            scan_count=len(recent_scans),
            latest_score=latest_score,
            previous_score=previous_score,
            score_delta=score_delta,
            agent_deltas=agent_deltas,
            rolling_average_last_5=round(rolling_avg, 2),
        )

        logger.info(
            "trend_computed",
            extra={
                "repository_id": str(repository_id),
                "latest_score": latest_score,
                "score_delta": score_delta,
                "rolling_average": trend.rolling_average_last_5,
            },
        )
        return trend

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_two_scans(
        self,
        latest_row: ScanModel,
        previous_row: ScanModel,
    ) -> tuple[ScanModel, ScanModel]:
        """Eager-load agent results for the two most-recent scans.

        ``list_scans`` returns rows without relationships populated.  We use
        ``get_scan`` (which applies ``selectinload``) for the two rows we
        actually need for the delta calculation.
        """
        latest_full = await self._repo.get_scan(latest_row.id)
        previous_full = await self._repo.get_scan(previous_row.id)
        return latest_full, previous_full

    @staticmethod
    def _compute_agent_deltas(
        latest: ScanModel, previous: ScanModel
    ) -> dict[str, int]:
        """Build a ``{agent_name: score_delta}`` mapping.

        Only agents present in *both* scans produce a delta entry.  New or
        removed agents are silently omitted so callers always get clean data.
        """
        previous_scores: dict[str, int] = {
            ar.agent_name: ar.score for ar in (previous.agent_results or [])
        }
        deltas: dict[str, int] = {}
        for ar in latest.agent_results or []:
            if ar.agent_name in previous_scores:
                deltas[ar.agent_name] = ar.score - previous_scores[ar.agent_name]
        return deltas
