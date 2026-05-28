"""Unit tests for SeniorDeveloperAgent LLM integration."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.application.agents.developer_agent import SeniorDeveloperAgent, _build_user_prompt
from app.application.agents.llm_schemas import LLMAgentResponse
from app.core.exceptions import AgentExecutionError, LLMError
from app.domain.entities import AgentFinding
from app.domain.enums import AgentName
from app.domain.value_objects import RepoMetadata
from app.infrastructure.llm.mock_adapter import MockLLMAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_response() -> LLMAgentResponse:
    return LLMAgentResponse.model_validate({
        "score": 82,
        "summary": "Repository demonstrates good coding standards with minor documentation gaps.",
        "issues": [
            {
                "severity": "Medium",
                "file_path": "app/service.py",
                "line_number": 42,
                "title": "Missing docstring on public method",
                "description": "The `process()` method lacks a docstring explaining its contract.",
                "recommendation": "Add a Google-style docstring to all public methods.",
            }
        ],
        "recommendations": [
            "Add type annotations to all public functions.",
            "Enforce linting and complexity checks in CI.",
        ],
    })


def _make_repo() -> RepoMetadata:
    return RepoMetadata(
        name="owner/repo",
        primary_language="Python",
        file_tree=["app/main.py", "tests/test_main.py"],
        repo_url="https://github.com/owner/repo",
    )


def _make_agent(response: LLMAgentResponse | None = None) -> SeniorDeveloperAgent:
    """Create agent with complete_structured mocked to return a fixed response."""
    adapter = MockLLMAdapter()
    adapter.complete_structured = AsyncMock(return_value=response or _valid_response())  # type: ignore[method-assign]
    return SeniorDeveloperAgent(llm_adapter=adapter)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSeniorDeveloperAgentAnalyze:
    @pytest.mark.asyncio
    async def test_returns_agent_finding_on_valid_response(self):
        agent = _make_agent()
        finding = await agent.analyze(_make_repo(), {})

        assert isinstance(finding, AgentFinding)
        assert finding.agent_name == AgentName.SENIOR_DEVELOPER
        assert finding.score == 82
        assert len(finding.issues) == 1
        assert finding.issues[0].severity.value == "Medium"
        assert finding.issues[0].file_path == "app/service.py"
        assert len(finding.recommendations) == 2

    @pytest.mark.asyncio
    async def test_uses_complete_structured_not_complete_text(self):
        """Agent must use complete_structured (JSON mode) rather than complete_text."""
        adapter = MockLLMAdapter()
        adapter.complete_structured = AsyncMock(return_value=_valid_response())  # type: ignore[method-assign]
        adapter.complete_text = AsyncMock()  # type: ignore[method-assign]
        agent = SeniorDeveloperAgent(llm_adapter=adapter)

        await agent.analyze(_make_repo(), {})

        adapter.complete_structured.assert_called_once()
        adapter.complete_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_agent_execution_error_on_llm_failure(self):
        """LLMError from the adapter must surface as AgentExecutionError."""
        adapter = MockLLMAdapter()
        adapter.complete_structured = AsyncMock(  # type: ignore[method-assign]
            side_effect=LLMError("OpenAI auth error")
        )
        agent = SeniorDeveloperAgent(llm_adapter=adapter)

        with pytest.raises(AgentExecutionError, match="SeniorDeveloperAgent"):
            await agent.analyze(_make_repo(), {})

    @pytest.mark.asyncio
    async def test_uses_mock_adapter_directly(self):
        """MockLLMAdapter returns valid output without an API key."""
        agent = SeniorDeveloperAgent(llm_adapter=MockLLMAdapter())
        finding = await agent.analyze(_make_repo(), {})
        assert 0 <= finding.score <= 100

    @pytest.mark.asyncio
    async def test_complete_structured_called_with_llm_agent_response_model(self):
        """complete_structured must be called with LLMAgentResponse as response_model."""
        adapter = MockLLMAdapter()
        adapter.complete_structured = AsyncMock(return_value=_valid_response())  # type: ignore[method-assign]
        agent = SeniorDeveloperAgent(llm_adapter=adapter)

        await agent.analyze(_make_repo(), {})

        _, kwargs = adapter.complete_structured.call_args
        assert kwargs.get("response_model") is LLMAgentResponse


class TestBuildUserPrompt:
    def test_includes_repo_name(self):
        repo = _make_repo()
        prompt = _build_user_prompt(repo, {})
        assert "owner/repo" in prompt

    def test_trims_long_file_tree(self):
        repo = RepoMetadata(
            name="big/repo",
            file_tree=[f"file_{i}.py" for i in range(100)],
        )
        prompt = _build_user_prompt(repo, {})
        assert "60 more files" in prompt

    def test_includes_code_metrics(self):
        repo = _make_repo()
        ctx = {"code_intelligence": {"avg_complexity": 7.5, "duplication_ratio": 0.12}}
        prompt = _build_user_prompt(repo, ctx)
        assert "7.5" in prompt
        assert "0.12" in prompt
