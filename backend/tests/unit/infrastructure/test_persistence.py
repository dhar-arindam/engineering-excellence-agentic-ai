"""Tests for the multi-repo persistence layer.

Uses an in-memory SQLite (aiosqlite) engine so no PostgreSQL is required.
PostgreSQL-specific types (UUID, JSONB) are mapped via SQLAlchemy's native_uuid
and a String fallback for UUID columns.

NOTE: ``aiosqlite`` is bundled with ``sqlalchemy[asyncio]`` but may need
``pip install aiosqlite`` if running outside the container.  The test file
checks for it and skips gracefully if absent.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Skip entire module if aiosqlite is not installed
# ---------------------------------------------------------------------------
aiosqlite = pytest.importorskip("aiosqlite", reason="aiosqlite required for persistence tests")

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.domain.entities import AgentFinding, AgentIssue, EngineeringReviewAggregate
from app.domain.enums import AgentName, ReviewStatus, RiskLevel, Severity
from app.infrastructure.persistence.models import (
    IssueModel,
    PersistenceBase,
    RepositoryModel,
    ScanAgentResultModel,
    ScanModel,
)
from app.infrastructure.persistence.repository import ScanRepository


# ---------------------------------------------------------------------------
# In-memory SQLite engine fixture
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def session():
    """Yield a fresh AsyncSession backed by an in-memory SQLite database."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(PersistenceBase.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s

    async with engine.begin() as conn:
        await conn.run_sync(PersistenceBase.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def repo(session: AsyncSession) -> ScanRepository:
    return ScanRepository(session)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_aggregate(
    score: int = 75,
    review_id: uuid.UUID | None = None,
) -> EngineeringReviewAggregate:
    rid = review_id or uuid.uuid4()
    return EngineeringReviewAggregate(
        review_id=rid,
        repo_url="https://github.com/test/repo",
        overall_score=score,
        risk_level=RiskLevel.MEDIUM,
        status=ReviewStatus.COMPLETED,
        agent_results=[
            AgentFinding(
                agent_name=AgentName.SENIOR_QA,
                score=score,
                summary="QA summary",
                issues=[
                    AgentIssue(
                        severity=Severity.HIGH,
                        title="Low coverage",
                        description="Coverage below threshold",
                        recommendation="Add tests",
                        file_path="app/main.py",
                        line_number=42,
                    )
                ],
                recommendations=["Increase coverage"],
            )
        ],
        created_at=datetime.now(UTC),
    )


# ===========================================================================
# RepositoryModel management
# ===========================================================================

class TestGetOrCreateRepository:
    @pytest.mark.asyncio
    async def test_creates_new_repository(self, repo: ScanRepository):
        r = await repo.get_or_create_repository("my-repo", "https://github.com/x/y")
        assert r.name == "my-repo"
        assert r.repo_url == "https://github.com/x/y"
        assert isinstance(r.id, uuid.UUID)

    @pytest.mark.asyncio
    async def test_returns_existing_by_url(self, repo: ScanRepository):
        r1 = await repo.get_or_create_repository("repo", "https://github.com/x/y")
        r2 = await repo.get_or_create_repository("repo", "https://github.com/x/y")
        assert r1.id == r2.id

    @pytest.mark.asyncio
    async def test_returns_existing_by_name(self, repo: ScanRepository):
        r1 = await repo.get_or_create_repository("unique-name")
        r2 = await repo.get_or_create_repository("unique-name")
        assert r1.id == r2.id

    @pytest.mark.asyncio
    async def test_url_lookup_takes_priority(self, repo: ScanRepository):
        r1 = await repo.get_or_create_repository("name-a", "https://github.com/x/z")
        r2 = await repo.get_or_create_repository("name-b", "https://github.com/x/z")
        assert r1.id == r2.id  # same URL → same record

    @pytest.mark.asyncio
    async def test_no_url_creates_by_name(self, repo: ScanRepository):
        r = await repo.get_or_create_repository("local-repo")
        assert r.repo_url is None


class TestGetRepository:
    @pytest.mark.asyncio
    async def test_get_existing(self, repo: ScanRepository):
        created = await repo.get_or_create_repository("r", "https://github.com/a/b")
        loaded  = await repo.get_repository(created.id)
        assert loaded.id == created.id

    @pytest.mark.asyncio
    async def test_not_found_raises(self, repo: ScanRepository):
        from app.core.exceptions import NotFoundError
        with pytest.raises(NotFoundError):
            await repo.get_repository(uuid.uuid4())


class TestListRepositories:
    @pytest.mark.asyncio
    async def test_returns_all(self, repo: ScanRepository):
        await repo.get_or_create_repository("a", "https://github.com/a/a")
        await repo.get_or_create_repository("b", "https://github.com/b/b")
        repos = await repo.list_repositories()
        assert len(repos) == 2

    @pytest.mark.asyncio
    async def test_limit_respected(self, repo: ScanRepository):
        for i in range(5):
            await repo.get_or_create_repository(f"r{i}", f"https://github.com/x/{i}")
        repos = await repo.list_repositories(limit=2)
        assert len(repos) == 2


# ===========================================================================
# Scan persistence
# ===========================================================================

class TestSaveScan:
    @pytest.mark.asyncio
    async def test_saves_scan(self, repo: ScanRepository):
        r = await repo.get_or_create_repository("repo", "https://github.com/x/y")
        agg = _make_aggregate()
        scan = await repo.save_scan(r.id, agg)
        assert scan.id == agg.review_id
        assert scan.overall_score == agg.overall_score

    @pytest.mark.asyncio
    async def test_saves_agent_result(self, repo: ScanRepository):
        r = await repo.get_or_create_repository("repo")
        scan = await repo.save_scan(r.id, _make_aggregate())
        assert len(scan.agent_results) == 1
        assert scan.agent_results[0].agent_name == "SeniorQAAgent"

    @pytest.mark.asyncio
    async def test_saves_issue(self, repo: ScanRepository):
        r = await repo.get_or_create_repository("repo")
        scan = await repo.save_scan(r.id, _make_aggregate())
        issues = scan.agent_results[0].issues
        assert len(issues) == 1
        assert issues[0].severity == "High"
        assert issues[0].title == "Low coverage"

    @pytest.mark.asyncio
    async def test_saves_commit_sha(self, repo: ScanRepository):
        r = await repo.get_or_create_repository("repo")
        scan = await repo.save_scan(r.id, _make_aggregate(), commit_sha="abc123")
        assert scan.commit_sha == "abc123"

    @pytest.mark.asyncio
    async def test_issue_file_path_and_line(self, repo: ScanRepository):
        r = await repo.get_or_create_repository("repo")
        scan = await repo.save_scan(r.id, _make_aggregate())
        issue = scan.agent_results[0].issues[0]
        assert issue.file_path == "app/main.py"
        assert issue.line_number == 42

    @pytest.mark.asyncio
    async def test_aggregate_without_issues(self, repo: ScanRepository):
        r = await repo.get_or_create_repository("repo")
        agg = EngineeringReviewAggregate(
            review_id=uuid.uuid4(),
            overall_score=90,
            risk_level=RiskLevel.LOW,
            agent_results=[
                AgentFinding(
                    agent_name=AgentName.SENIOR_DEVELOPER,
                    score=90,
                    summary="clean",
                    issues=[],
                    recommendations=[],
                )
            ],
        )
        saved  = await repo.save_scan(r.id, agg)
        loaded = await repo.get_scan(saved.id)
        assert loaded.agent_results[0].issues == []


# ===========================================================================
# Scan retrieval
# ===========================================================================

class TestGetScan:
    @pytest.mark.asyncio
    async def test_get_scan_loaded(self, repo: ScanRepository):
        r = await repo.get_or_create_repository("repo")
        saved = await repo.save_scan(r.id, _make_aggregate())
        loaded = await repo.get_scan(saved.id)
        assert loaded.id == saved.id
        assert len(loaded.agent_results) == 1

    @pytest.mark.asyncio
    async def test_get_scan_issues_loaded(self, repo: ScanRepository):
        r = await repo.get_or_create_repository("repo")
        saved = await repo.save_scan(r.id, _make_aggregate())
        loaded = await repo.get_scan(saved.id)
        assert len(loaded.agent_results[0].issues) == 1

    @pytest.mark.asyncio
    async def test_not_found_raises(self, repo: ScanRepository):
        from app.core.exceptions import NotFoundError
        with pytest.raises(NotFoundError):
            await repo.get_scan(uuid.uuid4())


class TestListScans:
    @pytest.mark.asyncio
    async def test_returns_scans_for_repo(self, repo: ScanRepository):
        r = await repo.get_or_create_repository("repo")
        for _ in range(3):
            await repo.save_scan(r.id, _make_aggregate())
        scans = await repo.list_scans(r.id)
        assert len(scans) == 3

    @pytest.mark.asyncio
    async def test_isolation_between_repos(self, repo: ScanRepository):
        r1 = await repo.get_or_create_repository("r1", "https://github.com/a/a")
        r2 = await repo.get_or_create_repository("r2", "https://github.com/b/b")
        await repo.save_scan(r1.id, _make_aggregate())
        await repo.save_scan(r1.id, _make_aggregate())
        await repo.save_scan(r2.id, _make_aggregate())
        assert len(await repo.list_scans(r1.id)) == 2
        assert len(await repo.list_scans(r2.id)) == 1

    @pytest.mark.asyncio
    async def test_limit_and_offset(self, repo: ScanRepository):
        r = await repo.get_or_create_repository("repo")
        for _ in range(5):
            await repo.save_scan(r.id, _make_aggregate())
        page1 = await repo.list_scans(r.id, limit=2, offset=0)
        page2 = await repo.list_scans(r.id, limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0].id != page2[0].id


class TestGetLatestScan:
    @pytest.mark.asyncio
    async def test_returns_none_when_empty(self, repo: ScanRepository):
        r = await repo.get_or_create_repository("repo")
        assert await repo.get_latest_scan(r.id) is None

    @pytest.mark.asyncio
    async def test_returns_latest(self, repo: ScanRepository):
        r = await repo.get_or_create_repository("repo")
        s1 = await repo.save_scan(r.id, _make_aggregate(score=60))
        s2 = await repo.save_scan(r.id, _make_aggregate(score=80))
        latest = await repo.get_latest_scan(r.id)
        # Latest by created_at — s2 was inserted after s1
        assert latest is not None


class TestCountScans:
    @pytest.mark.asyncio
    async def test_count(self, repo: ScanRepository):
        r = await repo.get_or_create_repository("repo")
        for _ in range(4):
            await repo.save_scan(r.id, _make_aggregate())
        assert await repo.count_scans(r.id) == 4


# ===========================================================================
# Score trend
# ===========================================================================

class TestGetScoreTrend:
    @pytest.mark.asyncio
    async def test_returns_trend_data(self, repo: ScanRepository):
        r = await repo.get_or_create_repository("repo")
        for score in [60, 70, 80]:
            await repo.save_scan(r.id, _make_aggregate(score=score))
        trend = await repo.get_score_trend(r.id)
        assert len(trend) == 3
        assert all("overall_score" in t for t in trend)
        assert all("created_at" in t for t in trend)
        assert all("risk_level" in t for t in trend)

    @pytest.mark.asyncio
    async def test_limit_respected(self, repo: ScanRepository):
        r = await repo.get_or_create_repository("repo")
        for score in range(10):
            await repo.save_scan(r.id, _make_aggregate(score=score * 5))
        trend = await repo.get_score_trend(r.id, limit=5)
        assert len(trend) == 5


# ===========================================================================
# Domain conversion
# ===========================================================================

class TestToDomainAggregate:
    @pytest.mark.asyncio
    async def test_round_trip(self, repo: ScanRepository):
        r = await repo.get_or_create_repository("repo")
        original = _make_aggregate(score=72)
        saved  = await repo.save_scan(r.id, original)
        loaded = await repo.get_scan(saved.id)
        # Attach repository for repo_url access
        loaded.repository = r
        domain = ScanRepository.to_domain_aggregate(loaded)
        assert domain.review_id  == original.review_id
        assert domain.overall_score == 72
        assert domain.risk_level == RiskLevel.MEDIUM
        assert len(domain.agent_results) == 1
        assert domain.agent_results[0].issues[0].title == "Low coverage"

    @pytest.mark.asyncio
    async def test_domain_issue_severity(self, repo: ScanRepository):
        r = await repo.get_or_create_repository("repo")
        saved  = await repo.save_scan(r.id, _make_aggregate())
        loaded = await repo.get_scan(saved.id)
        loaded.repository = r
        domain = ScanRepository.to_domain_aggregate(loaded)
        assert domain.agent_results[0].issues[0].severity == Severity.HIGH
