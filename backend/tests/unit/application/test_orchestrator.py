"""Unit tests for the parallel agent execution in EngineeringReviewOrchestrator."""
from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.orchestrator import (
    EngineeringReviewOrchestrator,
    _FALLBACK_SUMMARY_PREFIX,
    _make_fallback_finding,
)
from app.application.scoring_engine import ScoringEngine
from app.domain.entities import AgentFinding
from app.domain.enums import AgentName, ReviewStatus, Severity
from app.domain.value_objects import RepoMetadata, RepositoryTarget
from app.infrastructure.repository_ingestion.models import FileEntry, RepositoryMetadata
from app.infrastructure.tools.stubs import (
    StubArchitectureAnalysisService,
    StubCiCdIntelligenceService,
    StubCodeIntelligenceService,
    StubSecurityIntelligenceService,
    StubTestIntelligenceService,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _good_finding(name: AgentName, score: int = 80) -> AgentFinding:
    return AgentFinding(
        agent_name=name, score=score, summary="ok", issues=[], recommendations=[]
    )


def _ingested_meta() -> RepositoryMetadata:
    return RepositoryMetadata(
        name="test/repo",
        root_path="/tmp/repo",
        primary_language="Python",
        total_files=2,
        total_lines=10,
        detected_frameworks=[],
        file_index=[FileEntry(path="main.py", size=100, extension=".py")],
    )


def _make_agent(name: AgentName, finding: AgentFinding | None = None, *, raises=None, delay=0.0):
    """Return a mock agent that returns *finding*, raises *raises*, or sleeps *delay*."""
    agent = MagicMock()
    agent.agent_name = name

    async def _analyze(repo_metadata, ctx):
        if delay:
            await asyncio.sleep(delay)
        if raises is not None:
            raise raises
        return finding or _good_finding(name)

    agent.analyze = _analyze
    return agent


def _make_orchestrator(agents, *, timeout: float = 5.0) -> EngineeringReviewOrchestrator:
    mock_repo = AsyncMock()
    mock_repo.save = AsyncMock(return_value=None)

    class _FakeGitHubLoader:
        @asynccontextmanager
        async def clone_context(self, url):
            yield _ingested_meta()

        async def load(self, url):
            return _ingested_meta()

    mock_local = AsyncMock()
    mock_local.load.return_value = _ingested_meta()

    return EngineeringReviewOrchestrator(
        agents=agents,
        scoring_engine=ScoringEngine(),
        repository=mock_repo,
        local_loader=mock_local,
        github_loader=_FakeGitHubLoader(),
        code_service=StubCodeIntelligenceService(),
        test_service=StubTestIntelligenceService(),
        cicd_service=StubCiCdIntelligenceService(),
        security_service=StubSecurityIntelligenceService(),
        architecture_service=StubArchitectureAnalysisService(),
        agent_timeout=timeout,
    )


# ---------------------------------------------------------------------------
# _make_fallback_finding
# ---------------------------------------------------------------------------

class TestMakeFallbackFinding:
    def test_score_is_zero(self):
        f = _make_fallback_finding(AgentName.SENIOR_QA, "boom")
        assert f.score == 0

    def test_summary_starts_with_prefix(self):
        f = _make_fallback_finding(AgentName.SENIOR_QA, "boom")
        assert f.summary.startswith(_FALLBACK_SUMMARY_PREFIX)

    def test_reason_in_summary(self):
        f = _make_fallback_finding(AgentName.SENIOR_QA, "timeout 30s")
        assert "timeout 30s" in f.summary

    def test_has_one_critical_issue(self):
        f = _make_fallback_finding(AgentName.SENIOR_DEVELOPER, "error")
        assert len(f.issues) == 1
        assert f.issues[0].severity == Severity.CRITICAL

    def test_issue_mentions_agent_name(self):
        f = _make_fallback_finding(AgentName.SECURITY_EXPERT, "err")
        assert "SecurityExpertAgent" in f.issues[0].description

    def test_has_recommendation(self):
        f = _make_fallback_finding(AgentName.SENIOR_SRE, "err")
        assert len(f.recommendations) == 1

    def test_agent_name_preserved(self):
        f = _make_fallback_finding(AgentName.SENIOR_ARCHITECT, "err")
        assert f.agent_name == AgentName.SENIOR_ARCHITECT


# ---------------------------------------------------------------------------
# _execute_agent_safe
# ---------------------------------------------------------------------------

class TestExecuteAgentSafe:
    @pytest.mark.asyncio
    async def test_returns_real_finding_on_success(self):
        orch = _make_orchestrator([])
        finding = _good_finding(AgentName.SENIOR_QA, score=77)
        agent = _make_agent(AgentName.SENIOR_QA, finding)
        repo = RepoMetadata(name="r", file_tree=[], primary_language=None, local_path="/tmp", repo_url=None)
        result = await orch._execute_agent_safe(agent, repo, {})
        assert result.score == 77
        assert not result.summary.startswith(_FALLBACK_SUMMARY_PREFIX)

    @pytest.mark.asyncio
    async def test_returns_fallback_on_exception(self):
        orch = _make_orchestrator([])
        agent = _make_agent(AgentName.SENIOR_QA, raises=RuntimeError("boom"))
        repo = RepoMetadata(name="r", file_tree=[], primary_language=None, local_path="/tmp", repo_url=None)
        result = await orch._execute_agent_safe(agent, repo, {})
        assert result.score == 0
        assert result.summary.startswith(_FALLBACK_SUMMARY_PREFIX)

    @pytest.mark.asyncio
    async def test_returns_fallback_on_timeout(self):
        orch = _make_orchestrator([], timeout=0.05)
        agent = _make_agent(AgentName.SENIOR_DEVELOPER, delay=5.0)
        repo = RepoMetadata(name="r", file_tree=[], primary_language=None, local_path="/tmp", repo_url=None)
        result = await orch._execute_agent_safe(agent, repo, {})
        assert result.score == 0
        assert "timed out" in result.summary

    @pytest.mark.asyncio
    async def test_fallback_has_critical_issue(self):
        orch = _make_orchestrator([])
        agent = _make_agent(AgentName.SENIOR_ARCHITECT, raises=ValueError("bad"))
        repo = RepoMetadata(name="r", file_tree=[], primary_language=None, local_path="/tmp", repo_url=None)
        result = await orch._execute_agent_safe(agent, repo, {})
        assert result.issues[0].severity == Severity.CRITICAL

    @pytest.mark.asyncio
    async def test_never_raises(self):
        """_execute_agent_safe must never propagate exceptions to the caller."""
        orch = _make_orchestrator([])
        agent = _make_agent(AgentName.SECURITY_EXPERT, raises=Exception("catastrophic"))
        repo = RepoMetadata(name="r", file_tree=[], primary_language=None, local_path="/tmp", repo_url=None)
        result = await orch._execute_agent_safe(agent, repo, {})
        assert isinstance(result, AgentFinding)


# ---------------------------------------------------------------------------
# Parallel execution via _run_agents
# ---------------------------------------------------------------------------

class TestRunAgentsParallel:
    @pytest.mark.asyncio
    async def test_all_agents_run(self):
        agents = [_make_agent(n) for n in AgentName]
        orch = _make_orchestrator(agents)
        target = RepositoryTarget(repo_url="https://github.com/test/repo")
        result = await orch.orchestrate(target)
        assert len(result.agent_results) == len(list(AgentName))

    @pytest.mark.asyncio
    async def test_one_failing_does_not_block_others(self):
        agents = [
            _make_agent(AgentName.SENIOR_QA, raises=RuntimeError("crash")),
            _make_agent(AgentName.SENIOR_DEVELOPER, _good_finding(AgentName.SENIOR_DEVELOPER, 90)),
            _make_agent(AgentName.SENIOR_ARCHITECT, _good_finding(AgentName.SENIOR_ARCHITECT, 85)),
            _make_agent(AgentName.SENIOR_SRE, _good_finding(AgentName.SENIOR_SRE, 70)),
            _make_agent(AgentName.SECURITY_EXPERT, _good_finding(AgentName.SECURITY_EXPERT, 80)),
        ]
        orch = _make_orchestrator(agents)
        target = RepositoryTarget(local_path="/tmp/repo")
        result = await orch.orchestrate(target)
        assert len(result.agent_results) == 5

    @pytest.mark.asyncio
    async def test_partial_failure_status_is_completed(self):
        """One agent fails → status is COMPLETED (not all failed)."""
        agents = [
            _make_agent(AgentName.SENIOR_QA, raises=RuntimeError("crash")),
            _make_agent(AgentName.SENIOR_DEVELOPER),
            _make_agent(AgentName.SENIOR_ARCHITECT),
            _make_agent(AgentName.SENIOR_SRE),
            _make_agent(AgentName.SECURITY_EXPERT),
        ]
        orch = _make_orchestrator(agents)
        target = RepositoryTarget(local_path="/tmp/repo")
        result = await orch.orchestrate(target)
        assert result.status == ReviewStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_all_fail_status_is_failed(self):
        agents = [
            _make_agent(n, raises=RuntimeError("crash")) for n in AgentName
        ]
        orch = _make_orchestrator(agents)
        target = RepositoryTarget(local_path="/tmp/repo")
        result = await orch.orchestrate(target)
        assert result.status == ReviewStatus.FAILED

    @pytest.mark.asyncio
    async def test_timed_out_agent_returns_fallback(self):
        agents = [
            _make_agent(AgentName.SENIOR_QA, delay=5.0),   # will time out
            _make_agent(AgentName.SENIOR_DEVELOPER),
            _make_agent(AgentName.SENIOR_ARCHITECT),
            _make_agent(AgentName.SENIOR_SRE),
            _make_agent(AgentName.SECURITY_EXPERT),
        ]
        orch = _make_orchestrator(agents, timeout=0.05)
        target = RepositoryTarget(local_path="/tmp/repo")
        result = await orch.orchestrate(target)
        qa_finding = next(f for f in result.agent_results if f.agent_name == AgentName.SENIOR_QA)
        assert qa_finding.score == 0
        assert "timed out" in qa_finding.summary

    @pytest.mark.asyncio
    async def test_concurrent_execution_is_faster_than_sequential(self):
        """5 agents each sleeping 0.1s should complete well under 0.5s when parallel."""
        agents = [_make_agent(n, delay=0.1) for n in AgentName]
        orch = _make_orchestrator(agents, timeout=5.0)
        target = RepositoryTarget(local_path="/tmp/repo")
        import time
        t0 = time.monotonic()
        await orch.orchestrate(target)
        elapsed = time.monotonic() - t0
        # Parallel: ~0.1s total. Sequential would be ~0.5s.
        assert elapsed < 0.4, f"Expected parallel execution; took {elapsed:.2f}s"

    @pytest.mark.asyncio
    async def test_failed_agent_score_is_zero_in_aggregate(self):
        agents = [
            _make_agent(AgentName.SENIOR_QA, raises=RuntimeError("crash")),
            _make_agent(AgentName.SENIOR_DEVELOPER),
            _make_agent(AgentName.SENIOR_ARCHITECT),
            _make_agent(AgentName.SENIOR_SRE),
            _make_agent(AgentName.SECURITY_EXPERT),
        ]
        orch = _make_orchestrator(agents)
        target = RepositoryTarget(local_path="/tmp/repo")
        result = await orch.orchestrate(target)
        qa = next(f for f in result.agent_results if f.agent_name == AgentName.SENIOR_QA)
        assert qa.score == 0
