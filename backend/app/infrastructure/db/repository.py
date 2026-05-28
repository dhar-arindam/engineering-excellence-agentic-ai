"""Repository pattern for EngineeringReview persistence."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.domain.entities import AgentFinding, AgentIssue, EngineeringReviewAggregate, ReviewSummary
from app.domain.enums import AgentName, ReviewStatus, RiskLevel, Severity
from app.infrastructure.db.models import AgentResultModel, EngineeringReviewModel


class EngineeringReviewRepository:
    """Async repository for persisting and loading EngineeringReviewAggregate."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, review: EngineeringReviewAggregate) -> None:
        """Persist a full review aggregate (insert or upsert)."""
        review_model = EngineeringReviewModel(
            id=review.review_id,
            repo_url=review.repo_url,
            local_path=review.local_path,
            overall_score=review.overall_score,
            risk_level=review.risk_level.value,
            status=review.status.value,
            created_at=review.created_at,
        )
        for finding in review.agent_results:
            agent_model = AgentResultModel(
                review_id=review.review_id,
                agent_name=finding.agent_name.value,
                score=finding.score,
                summary=finding.summary,
                issues=[issue.model_dump(mode="json") for issue in finding.issues],
                recommendations=finding.recommendations,
            )
            review_model.agent_results.append(agent_model)

        self._session.add(review_model)

    async def get_by_id(self, review_id: uuid.UUID) -> EngineeringReviewAggregate:
        """Load a full review aggregate by ID."""
        stmt = (
            select(EngineeringReviewModel)
            .options(selectinload(EngineeringReviewModel.agent_results))
            .where(EngineeringReviewModel.id == review_id)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            raise NotFoundError("EngineeringReview", str(review_id))
        return self._to_domain(model)

    async def get_summary(self, review_id: uuid.UUID) -> ReviewSummary:
        """Load only the summary projection."""
        stmt = (
            select(EngineeringReviewModel)
            .options(selectinload(EngineeringReviewModel.agent_results))
            .where(EngineeringReviewModel.id == review_id)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            raise NotFoundError("EngineeringReview", str(review_id))

        agent_scores = {r.agent_name: r.score for r in model.agent_results}
        return ReviewSummary(
            review_id=model.id,
            overall_score=model.overall_score,
            risk_level=RiskLevel(model.risk_level),
            status=ReviewStatus(model.status),
            agent_scores=agent_scores,
            created_at=model.created_at,
        )

    @staticmethod
    def _to_domain(model: EngineeringReviewModel) -> EngineeringReviewAggregate:
        agent_results = [
            AgentFinding(
                agent_name=AgentName(r.agent_name),
                score=r.score,
                summary=r.summary,
                issues=[
                    AgentIssue(
                        id=uuid.UUID(str(i["id"])),
                        severity=Severity(i["severity"]),
                        file_path=i.get("file_path"),
                        line_number=i.get("line_number"),
                        title=i["title"],
                        description=i["description"],
                        recommendation=i["recommendation"],
                    )
                    for i in (r.issues or [])
                ],
                recommendations=r.recommendations or [],
            )
            for r in model.agent_results
        ]
        return EngineeringReviewAggregate(
            review_id=model.id,
            repo_url=model.repo_url,
            local_path=model.local_path,
            overall_score=model.overall_score,
            risk_level=RiskLevel(model.risk_level),
            agent_results=agent_results,
            status=ReviewStatus(model.status),
            created_at=model.created_at,
        )
