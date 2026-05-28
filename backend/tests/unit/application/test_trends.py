"""Tests for ScanTrendService (app/application/trends.py)."""
from __future__ import annotations

import uuid
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.trends import RepositoryTrend, ScanTrendService
from app.core.exceptions import NotFoundError
from app.infrastructure.persistence.models import ScanAgentResultModel, ScanModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scan(
    overall_score: int,
    agent_scores: Optional[dict[str, int]] = None,
    scan_id: Optional[uuid.UUID] = None,
) -> ScanModel:
    """Build a minimal ScanModel (no real ORM session needed)."""
    m = MagicMock(spec=ScanModel)
    m.id = scan_id or uuid.uuid4()
    m.overall_score = overall_score
    m.agent_results = []
    for name, score in (agent_scores or {}).items():
        ar = MagicMock(spec=ScanAgentResultModel)
        ar.agent_name = name
        ar.score = score
        ar.issues = []
        m.agent_results.append(ar)
    return m


def _make_repo(scans: list[ScanModel]) -> ScanRepository:
    """Return a ScanRepository whose list_scans / get_scan return canned data."""
    repo = MagicMock()
    # list_scans returns a plain list (awaitable)
    repo.list_scans = AsyncMock(return_value=scans)
    # get_scan returns the scan whose id matches
    by_id = {s.id: s for s in scans}
    repo.get_scan = AsyncMock(side_effect=lambda sid: by_id[sid])
    return repo


# Import after helper so the mock import doesn't shadow the real one.
from app.infrastructure.persistence.repository import ScanRepository  # noqa: E402


# ---------------------------------------------------------------------------
# RepositoryTrend model
# ---------------------------------------------------------------------------


class TestRepositoryTrend:
    def test_minimal_construction(self):
        t = RepositoryTrend(
            repository_id=uuid.uuid4(),
            scan_count=1,
            latest_score=80,
            rolling_average_last_5=80.0,
        )
        assert t.previous_score is None
        assert t.score_delta is None
        assert t.agent_deltas == {}

    def test_frozen(self):
        t = RepositoryTrend(
            repository_id=uuid.uuid4(),
            scan_count=1,
            latest_score=70,
            rolling_average_last_5=70.0,
        )
        with pytest.raises(Exception):
            t.latest_score = 99  # type: ignore[misc]

    def test_score_bounds(self):
        with pytest.raises(Exception):
            RepositoryTrend(
                repository_id=uuid.uuid4(),
                scan_count=1,
                latest_score=101,
                rolling_average_last_5=101.0,
            )


# ---------------------------------------------------------------------------
# ScanTrendService — first scan (no previous)
# ---------------------------------------------------------------------------


class TestFirstScan:
    @pytest.mark.asyncio
    async def test_single_scan_no_delta(self):
        repo_id = uuid.uuid4()
        repo = _make_repo([_scan(75)])
        svc = ScanTrendService(repo)
        trend = await svc.compute_repository_trend(repo_id)

        assert trend.latest_score == 75
        assert trend.previous_score is None
        assert trend.score_delta is None
        assert trend.agent_deltas == {}
        assert trend.rolling_average_last_5 == 75.0
        assert trend.scan_count == 1

    @pytest.mark.asyncio
    async def test_single_scan_rolling_avg_equals_score(self):
        repo_id = uuid.uuid4()
        repo = _make_repo([_scan(60)])
        svc = ScanTrendService(repo)
        trend = await svc.compute_repository_trend(repo_id)
        assert trend.rolling_average_last_5 == 60.0


# ---------------------------------------------------------------------------
# ScanTrendService — two scans
# ---------------------------------------------------------------------------


class TestTwoScans:
    @pytest.mark.asyncio
    async def test_positive_delta(self):
        repo_id = uuid.uuid4()
        s1 = _scan(80)
        s2 = _scan(70)
        repo = _make_repo([s1, s2])
        svc = ScanTrendService(repo)
        trend = await svc.compute_repository_trend(repo_id)

        assert trend.latest_score == 80
        assert trend.previous_score == 70
        assert trend.score_delta == 10

    @pytest.mark.asyncio
    async def test_negative_delta(self):
        repo_id = uuid.uuid4()
        s1 = _scan(60)
        s2 = _scan(80)
        repo = _make_repo([s1, s2])
        svc = ScanTrendService(repo)
        trend = await svc.compute_repository_trend(repo_id)

        assert trend.score_delta == -20

    @pytest.mark.asyncio
    async def test_zero_delta(self):
        repo_id = uuid.uuid4()
        s1 = _scan(75)
        s2 = _scan(75)
        repo = _make_repo([s1, s2])
        svc = ScanTrendService(repo)
        trend = await svc.compute_repository_trend(repo_id)

        assert trend.score_delta == 0

    @pytest.mark.asyncio
    async def test_rolling_average_two_scans(self):
        repo_id = uuid.uuid4()
        repo = _make_repo([_scan(80), _scan(60)])
        svc = ScanTrendService(repo)
        trend = await svc.compute_repository_trend(repo_id)
        assert trend.rolling_average_last_5 == 70.0


# ---------------------------------------------------------------------------
# ScanTrendService — agent deltas
# ---------------------------------------------------------------------------


class TestAgentDeltas:
    @pytest.mark.asyncio
    async def test_agent_deltas_computed(self):
        repo_id = uuid.uuid4()
        agents_latest = {"SeniorQAAgent": 80, "SeniorDeveloperAgent": 70}
        agents_prev = {"SeniorQAAgent": 60, "SeniorDeveloperAgent": 90}
        s1 = _scan(75, agents_latest)
        s2 = _scan(75, agents_prev)
        repo = _make_repo([s1, s2])
        svc = ScanTrendService(repo)
        trend = await svc.compute_repository_trend(repo_id)

        assert trend.agent_deltas["SeniorQAAgent"] == 20
        assert trend.agent_deltas["SeniorDeveloperAgent"] == -20

    @pytest.mark.asyncio
    async def test_new_agent_omitted_from_deltas(self):
        """Agent only in latest scan should NOT appear in deltas."""
        repo_id = uuid.uuid4()
        s1 = _scan(80, {"SeniorQAAgent": 80, "SecurityExpertAgent": 70})
        s2 = _scan(70, {"SeniorQAAgent": 60})  # SecurityExpertAgent missing
        repo = _make_repo([s1, s2])
        svc = ScanTrendService(repo)
        trend = await svc.compute_repository_trend(repo_id)

        assert "SecurityExpertAgent" not in trend.agent_deltas
        assert "SeniorQAAgent" in trend.agent_deltas

    @pytest.mark.asyncio
    async def test_removed_agent_omitted_from_deltas(self):
        """Agent only in previous scan should NOT appear in deltas."""
        repo_id = uuid.uuid4()
        s1 = _scan(80, {"SeniorQAAgent": 80})
        s2 = _scan(70, {"SeniorQAAgent": 60, "SeniorSREAgent": 70})
        repo = _make_repo([s1, s2])
        svc = ScanTrendService(repo)
        trend = await svc.compute_repository_trend(repo_id)

        assert "SeniorSREAgent" not in trend.agent_deltas
        assert "SeniorQAAgent" in trend.agent_deltas

    @pytest.mark.asyncio
    async def test_all_five_agents_delta(self):
        all_agents = [
            "SeniorQAAgent",
            "SeniorDeveloperAgent",
            "SeniorArchitectAgent",
            "SeniorSREAgent",
            "SecurityExpertAgent",
        ]
        latest_scores = {a: 80 for a in all_agents}
        prev_scores = {a: 70 for a in all_agents}
        repo_id = uuid.uuid4()
        repo = _make_repo([_scan(80, latest_scores), _scan(70, prev_scores)])
        svc = ScanTrendService(repo)
        trend = await svc.compute_repository_trend(repo_id)

        assert len(trend.agent_deltas) == 5
        for delta in trend.agent_deltas.values():
            assert delta == 10


# ---------------------------------------------------------------------------
# ScanTrendService — rolling average with 5 scans
# ---------------------------------------------------------------------------


class TestRollingAverage:
    @pytest.mark.asyncio
    async def test_rolling_average_five_scans(self):
        scores = [100, 80, 60, 40, 20]
        repo_id = uuid.uuid4()
        repo = _make_repo([_scan(s) for s in scores])
        svc = ScanTrendService(repo)
        trend = await svc.compute_repository_trend(repo_id)
        assert trend.rolling_average_last_5 == 60.0

    @pytest.mark.asyncio
    async def test_rolling_average_rounded(self):
        """Average of 3 values that don't divide evenly → rounded to 2 dp."""
        scores = [100, 100, 99]
        repo_id = uuid.uuid4()
        repo = _make_repo([_scan(s) for s in scores])
        svc = ScanTrendService(repo)
        trend = await svc.compute_repository_trend(repo_id)
        assert trend.rolling_average_last_5 == round(299 / 3, 2)

    @pytest.mark.asyncio
    async def test_scan_count_reflects_actual_scans(self):
        repo_id = uuid.uuid4()
        repo = _make_repo([_scan(70), _scan(80), _scan(90)])
        svc = ScanTrendService(repo)
        trend = await svc.compute_repository_trend(repo_id)
        assert trend.scan_count == 3


# ---------------------------------------------------------------------------
# ScanTrendService — no scans (repository not found)
# ---------------------------------------------------------------------------


class TestNoScans:
    @pytest.mark.asyncio
    async def test_raises_not_found_when_no_scans(self):
        repo_id = uuid.uuid4()
        repo = _make_repo([])
        svc = ScanTrendService(repo)
        with pytest.raises(NotFoundError):
            await svc.compute_repository_trend(repo_id)

    @pytest.mark.asyncio
    async def test_repository_id_preserved_in_result(self):
        repo_id = uuid.uuid4()
        repo = _make_repo([_scan(85)])
        svc = ScanTrendService(repo)
        trend = await svc.compute_repository_trend(repo_id)
        assert trend.repository_id == repo_id
