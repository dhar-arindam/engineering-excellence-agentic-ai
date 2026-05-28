"""Domain entities — pure Pydantic v2 models with no infrastructure dependencies."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.domain.enums import AgentName, RiskLevel, ReviewStatus, Severity


class AgentIssue(BaseModel):
    """A single issue discovered by an agent."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    severity: Severity
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    title: str
    description: str
    recommendation: str

    model_config = {"frozen": True}


class AgentFinding(BaseModel):
    """Complete structured output from one domain agent."""

    agent_name: AgentName
    score: int = Field(ge=0, le=100)
    summary: str
    issues: list[AgentIssue] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence_reason: str = Field(default="")

    model_config = {"frozen": True}


class EngineeringReviewAggregate(BaseModel):
    """Top-level aggregate result for a full engineering review."""

    review_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    repo_url: Optional[str] = None
    local_path: Optional[str] = None
    overall_score: int = Field(ge=0, le=100)
    risk_level: RiskLevel
    agent_results: list[AgentFinding]
    status: ReviewStatus = ReviewStatus.COMPLETED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = {"frozen": True}


class ReviewSummary(BaseModel):
    """Lightweight summary — overall + per-agent scores only."""

    review_id: uuid.UUID
    overall_score: int
    risk_level: RiskLevel
    status: ReviewStatus
    agent_scores: dict[str, int]
    created_at: datetime
