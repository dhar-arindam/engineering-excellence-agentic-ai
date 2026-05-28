"""SeniorDeveloperAgent — evaluates code quality, patterns, and maintainability via LLM."""
from __future__ import annotations

from typing import Any

from app.application.agents.base import BaseEngineeringAgent
from app.application.agents.llm_schemas import LLMAgentResponse
from app.core.exceptions import AgentExecutionError, LLMError
from app.core.logging import get_logger
from app.domain.entities import AgentFinding
from app.domain.enums import AgentName
from app.domain.value_objects import RepoMetadata
from app.infrastructure.llm.base import BaseLLMAdapter

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# System prompt — strictly constrains LLM output to JSON only.
# Kept compact to stay well under 1500 tokens.
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """\
You are a Senior Software Engineer performing a structured code quality review.

RULES (mandatory):
1. Respond with ONLY a valid JSON object — no prose, no markdown, no code fences.
2. The JSON must conform exactly to the schema below.
3. "score" is an integer 0–100 reflecting overall code quality.
4. "summary" is 1–3 sentences, factual, evidence-based.
5. "issues" contains at most 5 items; omit if none found.
6. "recommendations" contains at most 5 actionable strings.
7. "severity" must be one of: Low, Medium, High, Critical.
8. "confidence" is a float 0.0–1.0 reflecting certainty of this assessment based on signal completeness.
9. "confidence_reason" is a brief explanation of what drove the confidence level.

SCORING RUBRIC (use to derive score):
- code_quality      (30%) — readability, naming, cyclomatic complexity, duplication
- solid_principles  (25%) — SRP, OCP, LSP, ISP, DIP adherence
- error_handling    (20%) — consistent handling, no swallowed exceptions
- documentation     (15%) — inline docs, README, API docs
- dependency_mgmt   (10%) — pinned versions, no unused deps

REQUIRED JSON SCHEMA:
{
  "score": <integer 0-100>,
  "confidence": <float 0.0-1.0>,
  "confidence_reason": "<string>",
  "summary": "<string>",
  "issues": [
    {
      "severity": "<Low|Medium|High|Critical>",
      "file_path": "<string or null>",
      "line_number": <integer or null>,
      "title": "<string>",
      "description": "<string>",
      "recommendation": "<string>"
    }
  ],
  "recommendations": ["<string>"]
}"""


def _build_user_prompt(
    repo_metadata: RepoMetadata,
    tool_context: dict[str, Any],
) -> str:
    """Build a compact user prompt from repo metadata and tool context."""
    code = tool_context.get("code_intelligence", {})
    test = tool_context.get("test_intelligence", {})

    # Trim file tree to keep token count low
    file_sample = repo_metadata.file_tree[:40]
    file_list = "\n".join(f"  {f}" for f in file_sample)
    if len(repo_metadata.file_tree) > 40:
        file_list += f"\n  ... and {len(repo_metadata.file_tree) - 40} more files"

    parts = [
        f"Repository: {repo_metadata.name}",
        f"Primary language: {repo_metadata.primary_language or 'unknown'}",
        f"Total files: {code.get('total_files', len(repo_metadata.file_tree))}",
        f"Avg cyclomatic complexity: {code.get('avg_complexity', 'unknown')}",
        f"Code duplication ratio: {code.get('duplication_ratio', 'unknown')}",
        f"Test coverage: {test.get('coverage_percent', 'unknown')}%",
        f"Lint violations: {len(code.get('lint_violations', []))}",
        "",
        "File tree sample:",
        file_list,
    ]

    if repo_metadata.readme_excerpt:
        parts += ["", f"README excerpt:\n{repo_metadata.readme_excerpt[:300]}"]

    return "\n".join(parts)


class SeniorDeveloperAgent(BaseEngineeringAgent):
    """
    Evaluates code quality, design patterns, maintainability, and technical debt.

    Uses an LLM adapter to produce structured findings. Retries once on parse
    failure before raising AgentExecutionError.
    """

    def __init__(self, llm_adapter: BaseLLMAdapter) -> None:
        super().__init__(llm_adapter)

    @property
    def agent_name(self) -> AgentName:
        return AgentName.SENIOR_DEVELOPER

    @property
    def role_definition(self) -> str:
        return (
            "You are a Senior Software Engineer with 15+ years of experience across multiple "
            "languages and domains. You evaluate code quality, adherence to SOLID principles, "
            "design pattern usage, maintainability, documentation quality, and technical debt."
        )

    @property
    def evaluation_rubric(self) -> dict[str, Any]:
        return {
            "code_quality": {"weight": 0.30, "criteria": "Readability, naming, complexity, duplication"},
            "solid_principles": {"weight": 0.25, "criteria": "SRP, OCP, LSP, ISP, DIP adherence"},
            "error_handling": {"weight": 0.20, "criteria": "Consistent handling, no swallowed exceptions"},
            "documentation": {"weight": 0.15, "criteria": "Inline docs, README, API docs"},
            "dependency_management": {"weight": 0.10, "criteria": "Pinned versions, no unused deps"},
        }

    async def analyze(
        self,
        repo_metadata: RepoMetadata,
        tool_context: dict[str, Any],
    ) -> AgentFinding:
        """
        Run an LLM-backed code quality review using JSON-mode structured output.

        Uses `complete_structured` which:
        - Forces `response_format={"type": "json_object"}` (reliable JSON from OpenAI)
        - Validates the response against LLMAgentResponse via Pydantic
        - Retries up to 3 times with exponential backoff (handled by tenacity in the adapter)
        """
        assert self._llm is not None, "SeniorDeveloperAgent requires an LLM adapter."

        user_prompt = _build_user_prompt(repo_metadata, tool_context)

        try:
            response = await self._llm.complete_structured(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                response_model=LLMAgentResponse,
                temperature=0.2,
            )
            logger.info("developer_agent.parsed", score=response.score)
            return self._to_agent_finding(self.agent_name, response)
        except LLMError as exc:
            raise AgentExecutionError(
                self.agent_name.value,
                f"LLM call failed after retries: {exc}",
            ) from exc
