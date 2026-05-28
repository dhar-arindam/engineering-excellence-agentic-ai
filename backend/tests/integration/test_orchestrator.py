"""Integration test for the full review pipeline (no DB, no external calls)."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.application.agents import (
    SecurityExpertAgent,
    SeniorArchitectAgent,
    SeniorDeveloperAgent,
    SeniorQAAgent,
    SeniorSREAgent,
)
from app.application.orchestrator import EngineeringReviewOrchestrator
from app.application.scoring_engine import ScoringEngine
from app.domain.entities import EngineeringReviewAggregate
from app.domain.value_objects import RepoMetadata, RepositoryTarget
from app.infrastructure.llm.mock_adapter import MockLLMAdapter
from app.infrastructure.tools.stubs import (
    StubArchitectureAnalysisService,
    StubCiCdIntelligenceService,
    StubCodeIntelligenceService,
    StubSecurityIntelligenceService,
    StubTestIntelligenceService,
)


@pytest.fixture
def mock_repo_metadata():
    return RepoMetadata(
        name="test/repo",
        default_branch="main",
        primary_language="Python",
        file_tree=["app/main.py", "tests/test_main.py"],
        repo_url="https://github.com/test/repo",
    )


@pytest.fixture
def mock_local_loader(mock_repo_metadata):
    from app.infrastructure.repository_ingestion.models import FileEntry, RepositoryMetadata
    ingested = RepositoryMetadata(
        name="test/repo",
        root_path="/tmp/test_repo",
        primary_language="Python",
        total_files=2,
        total_lines=10,
        detected_frameworks=["pytest"],
        file_index=[
            FileEntry(path="app/main.py", size=100, extension=".py"),
            FileEntry(path="tests/test_main.py", size=80, extension=".py"),
        ],
    )
    loader = AsyncMock()
    loader.load.return_value = ingested
    return loader


@pytest.fixture
def mock_github_loader(mock_repo_metadata):
    from app.infrastructure.repository_ingestion.models import FileEntry, RepositoryMetadata
    from contextlib import asynccontextmanager

    ingested = RepositoryMetadata(
        name="repo",
        root_path="/tmp/cloned_repo",
        primary_language="Python",
        total_files=2,
        total_lines=10,
        detected_frameworks=["pytest"],
        file_index=[
            FileEntry(path="app/main.py", size=100, extension=".py"),
            FileEntry(path="tests/test_main.py", size=80, extension=".py"),
        ],
    )

    class FakeGitHubLoader:
        @asynccontextmanager
        async def clone_context(self, url):
            yield ingested

        async def load(self, url):
            return ingested

    return FakeGitHubLoader()


@pytest.fixture
def mock_repository():
    repo = AsyncMock()
    repo.save = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def orchestrator(mock_local_loader, mock_github_loader, mock_repository):
    mock_llm = MockLLMAdapter()
    return EngineeringReviewOrchestrator(
        agents=[
            SeniorQAAgent(),
            SeniorDeveloperAgent(llm_adapter=mock_llm),
            SeniorArchitectAgent(),
            SeniorSREAgent(),
            SecurityExpertAgent(),
        ],
        scoring_engine=ScoringEngine(),
        repository=mock_repository,
        local_loader=mock_local_loader,
        github_loader=mock_github_loader,
        code_service=StubCodeIntelligenceService(),
        test_service=StubTestIntelligenceService(),
        cicd_service=StubCiCdIntelligenceService(),
        security_service=StubSecurityIntelligenceService(),
        architecture_service=StubArchitectureAnalysisService(),
    )


@pytest.mark.asyncio
async def test_orchestrate_returns_aggregate(orchestrator, mock_repository):
    target = RepositoryTarget(repo_url="https://github.com/test/repo")
    result = await orchestrator.orchestrate(target)

    assert isinstance(result, EngineeringReviewAggregate)
    assert isinstance(result.review_id, uuid.UUID)
    assert 0 <= result.overall_score <= 100
    assert len(result.agent_results) == 5
    mock_repository.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_orchestrate_scores_all_agents(orchestrator):
    target = RepositoryTarget(repo_url="https://github.com/test/repo")
    result = await orchestrator.orchestrate(target)

    agent_names = {f.agent_name.value for f in result.agent_results}
    assert "SeniorQAAgent" in agent_names
    assert "SeniorDeveloperAgent" in agent_names
    assert "SecurityExpertAgent" in agent_names
    assert len(agent_names) == 5

