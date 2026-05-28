"""SQLAlchemy async ORM models."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class EngineeringReviewModel(Base):
    __tablename__ = "engineering_reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repo_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    local_path: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    overall_score: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, default=lambda: datetime.now(UTC)
    )

    agent_results: Mapped[list[AgentResultModel]] = relationship(
        "AgentResultModel", back_populates="review", cascade="all, delete-orphan"
    )


class AgentResultModel(Base):
    __tablename__ = "agent_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engineering_reviews.id", ondelete="CASCADE"), nullable=False
    )
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    issues: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)  # type: ignore[assignment]
    recommendations: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)  # type: ignore[assignment]

    review: Mapped[EngineeringReviewModel] = relationship(
        "EngineeringReviewModel", back_populates="agent_results"
    )


# ---------------------------------------------------------------------------
# New scan-based models (repositories / scans / scan_agent_results)
# ---------------------------------------------------------------------------


class RepositoryModel(Base):
    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    repo_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    default_branch: Mapped[str | None] = mapped_column(String(256), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(100), nullable=True)
    team_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    scans: Mapped[list[ScanModel]] = relationship(
        "ScanModel", back_populates="repository", cascade="all, delete-orphan"
    )


class ScanModel(Base):
    __tablename__ = "scans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    overall_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="Low")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    progress_percentage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_reference: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(256), nullable=True)
    scan_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="deep")
    scan_config_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # type: ignore[assignment]
    log_stream_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    patch_diff: Mapped[str | None] = mapped_column(Text, nullable=True)
    overall_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    radar_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # type: ignore[assignment]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    repository: Mapped[RepositoryModel] = relationship("RepositoryModel", back_populates="scans")
    agent_results: Mapped[list[ScanAgentResultModel]] = relationship(
        "ScanAgentResultModel", back_populates="scan", cascade="all, delete-orphan"
    )


class ScanAgentResultModel(Base):
    __tablename__ = "scan_agent_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scans.id", ondelete="CASCADE"), nullable=False
    )
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    confidence_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    issues: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)  # type: ignore[assignment]
    recommendations: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)  # type: ignore[assignment]

    scan: Mapped[ScanModel] = relationship("ScanModel", back_populates="agent_results")
