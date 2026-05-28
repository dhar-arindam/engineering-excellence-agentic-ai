"""Abstract base class for all domain engineering agents."""
from __future__ import annotations

import abc
import uuid
from typing import TYPE_CHECKING, Any

from app.application.agents.llm_schemas import LLMAgentResponse
from app.domain.entities import AgentFinding, AgentIssue
from app.domain.enums import AgentName, Severity
from app.domain.value_objects import RepoMetadata

if TYPE_CHECKING:
    from app.infrastructure.llm.base import BaseLLMAdapter


class AnalysisInput(dict):  # type: ignore[type-arg]
    """Typed alias — agents receive a structured dict built from tool services."""


class BaseEngineeringAgent(abc.ABC):
    """
    Contract every domain agent must satisfy.

    Rules:
    - Agents must NOT call each other.
    - All LLM interaction happens through the injected LLM adapter.
    - analyze() must be fully async and return a validated AgentFinding.
    """

    def __init__(self, llm_adapter: "BaseLLMAdapter | None" = None) -> None:
        self._llm = llm_adapter

    @property
    @abc.abstractmethod
    def agent_name(self) -> AgentName:
        """Unique identifier for this agent."""

    @property
    @abc.abstractmethod
    def role_definition(self) -> str:
        """System prompt / role description sent to the LLM."""

    @property
    @abc.abstractmethod
    def evaluation_rubric(self) -> dict[str, Any]:
        """Structured rubric used to guide scoring. Serialized into the LLM prompt."""

    @abc.abstractmethod
    async def analyze(
        self,
        repo_metadata: RepoMetadata,
        tool_context: dict[str, Any],
    ) -> AgentFinding:
        """
        Run structured analysis and return a validated AgentFinding.

        Args:
            repo_metadata: Repository metadata (name, file tree, language, etc.)
            tool_context: Pre-fetched data from intelligence services, keyed by service name.

        Returns:
            AgentFinding with score 0-100, summary, issues, and recommendations.
        """

    @staticmethod
    def _to_agent_finding(
        agent_name: AgentName, response: LLMAgentResponse
    ) -> AgentFinding:
        """Convert a validated LLMAgentResponse into a domain AgentFinding."""
        return AgentFinding(
            agent_name=agent_name,
            score=response.score,
            summary=response.summary,
            confidence=response.confidence,
            confidence_reason=response.confidence_reason,
            issues=[
                AgentIssue(
                    id=uuid.uuid4(),
                    severity=Severity(issue.severity),
                    file_path=issue.file_path,
                    line_number=issue.line_number,
                    title=issue.title,
                    description=issue.description,
                    recommendation=issue.recommendation,
                )
                for issue in response.issues
            ],
            recommendations=response.recommendations,
        )
