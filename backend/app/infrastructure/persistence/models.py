"""SQLAlchemy ORM models for multi-repo historical storage.

Table hierarchy
---------------
repositories
    └── scans                  (one repo → many scans)
          └── scan_agent_results (one scan → one result per agent)
                └── issues       (one agent result → many issues)

These models use their own ``Base`` instance (``PersistenceBase``) so that
they can be tested against SQLite without pulling in the PostgreSQL-specific
JSONB columns that live in ``db/models.py``.

Alembic discovers both metadata sets via the combined target in ``env.py``.

Design decisions
----------------
* UUIDs for all PKs — portable across environments, no sequence contention.
* ``CASCADE DELETE`` propagates from parent to all children so deleting a
  repository removes every associated scan, agent result, and issue.
* ``commit_sha`` on ``Scan`` is nullable — local-path reviews have no SHA.
* ``line_number`` on ``Issue`` is nullable — some issues are file-level only.
* ``file_path`` on ``Issue`` is nullable — some issues are repo-level only.
* ``DateTime(timezone=True)`` stores UTC everywhere; consumers localise on read.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid


class PersistenceBase(DeclarativeBase):
    """Separate declarative base for multi-repo persistence models."""
    pass


class RepositoryModel(PersistenceBase):
    """Represents a tracked repository (GitHub URL or local path)."""

    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    repo_url: Mapped[str | None] = mapped_column(String(2048), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    scans: Mapped[list[ScanModel]] = relationship(
        "ScanModel",
        back_populates="repository",
        cascade="all, delete-orphan",
        order_by="ScanModel.created_at.desc()",
    )

    __table_args__ = (
        Index("ix_repositories_name", "name"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RepositoryModel id={self.id} name={self.name!r}>"


class ScanModel(PersistenceBase):
    """One engineering review scan of a repository at a point in time."""

    __tablename__ = "scans"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    overall_score: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    overall_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )

    repository: Mapped[RepositoryModel] = relationship(
        "RepositoryModel", back_populates="scans"
    )
    agent_results: Mapped[list[ScanAgentResultModel]] = relationship(
        "ScanAgentResultModel",
        back_populates="scan",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ScanModel id={self.id} repo={self.repository_id} "
            f"score={self.overall_score}>"
        )


class ScanAgentResultModel(PersistenceBase):
    """Structured result from a single domain agent within a scan."""

    __tablename__ = "scan_agent_results"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("scans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    confidence_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")

    scan: Mapped[ScanModel] = relationship(
        "ScanModel", back_populates="agent_results"
    )
    issues: Mapped[list[IssueModel]] = relationship(
        "IssueModel",
        back_populates="agent_result",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_scan_agent_results_scan_agent", "scan_id", "agent_name"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ScanAgentResultModel agent={self.agent_name!r} score={self.score}>"
        )


class IssueModel(PersistenceBase):
    """A single finding raised by a domain agent."""

    __tablename__ = "issues"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_result_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("scan_agent_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    line_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)

    agent_result: Mapped[ScanAgentResultModel] = relationship(
        "ScanAgentResultModel", back_populates="issues"
    )

    __table_args__ = (
        Index("ix_issues_severity", "severity"),
        Index("ix_issues_file_path", "file_path"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<IssueModel severity={self.severity!r} title={self.title!r}>"
        )

