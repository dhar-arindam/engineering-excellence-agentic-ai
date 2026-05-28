"""Engineering Review Orchestrator — coordinates all agents and produces the final aggregate.

Flow:
1. Load repository via RepositoryLoader (local or GitHub clone)
2. Run all intelligence services in parallel (I/O-bound and independent)
3. Build per-agent tool context (each agent receives only its relevant service slices)
4. Execute all agents **concurrently** via asyncio.gather
5. Aggregate structured findings (failed agents produce a zero-score fallback finding)
6. Compute weighted engineering health score
7. Persist and return EngineeringReviewAggregate

Design rules enforced here:
- Agents NEVER call each other
- No business logic lives in the API layer
- Every dependency is injected — nothing is instantiated inside this class
- Agent failures produce a structured fallback AgentFinding; they do NOT abort the review
- A configurable per-agent timeout prevents one slow agent from blocking the pipeline
- asyncio.gather with return_exceptions=True is used so a crash in one agent
  cannot propagate and cancel sibling coroutines
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from app.application.agents.base import BaseEngineeringAgent
from app.application.scoring_engine import ScoringEngine
from app.application.tool_interfaces import (
    ArchitectureAnalysisService,
    CiCdIntelligenceService,
    CodeIntelligenceService,
    SecurityIntelligenceService,
    TestIntelligenceService,
)
from app.core.exceptions import AgentExecutionError
from app.core.logging import get_logger
from app.domain.entities import AgentFinding, AgentIssue, EngineeringReviewAggregate
from app.domain.enums import AgentName, ReviewStatus, Severity
from app.domain.value_objects import RepoMetadata, RepositoryTarget
from app.infrastructure.db.repository import EngineeringReviewRepository
from app.infrastructure.repository_ingestion.github_loader import GitHubRepositoryLoader
from app.infrastructure.repository_ingestion.local_loader import LocalRepositoryLoader
from app.infrastructure.repository_ingestion.models import RepositoryMetadata

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Per-agent context slicing
# ---------------------------------------------------------------------------
# Each agent receives only the service keys it needs.  Keeping contexts small
# reduces token usage for LLM-backed agents and makes the contract explicit.

_AGENT_CONTEXT_KEYS: dict[AgentName, list[str]] = {
    AgentName.SENIOR_QA:        ["test_intelligence", "cicd_intelligence"],
    AgentName.SENIOR_DEVELOPER: ["code_intelligence", "test_intelligence"],
    AgentName.SENIOR_ARCHITECT: ["code_intelligence", "architecture_intelligence"],
    AgentName.SENIOR_SRE:       ["cicd_intelligence", "code_intelligence"],
    AgentName.SECURITY_EXPERT:  ["security_intelligence", "cicd_intelligence"],
}

# Default per-agent timeout (seconds).  Overridable via constructor.
_DEFAULT_AGENT_TIMEOUT: float = 30.0

# Prefix used on fallback AgentFinding summaries so _run_pipeline can detect
# whether every agent failed without adding extra fields to the domain model.
_FALLBACK_SUMMARY_PREFIX = "Agent execution failed"


class EngineeringReviewOrchestrator:
    """
    Orchestrates the full engineering review pipeline.

    Constructor parameters are all injected — no singletons, no global state.
    """

    def __init__(
        self,
        agents: list[BaseEngineeringAgent],
        scoring_engine: ScoringEngine,
        repository: EngineeringReviewRepository,
        local_loader: LocalRepositoryLoader,
        github_loader: GitHubRepositoryLoader,
        code_service: CodeIntelligenceService,
        test_service: TestIntelligenceService,
        cicd_service: CiCdIntelligenceService,
        security_service: SecurityIntelligenceService,
        architecture_service: ArchitectureAnalysisService,
        agent_timeout: float = _DEFAULT_AGENT_TIMEOUT,
    ) -> None:
        self._agents = agents
        self._scoring_engine = scoring_engine
        self._repository = repository
        self._local_loader = local_loader
        self._github_loader = github_loader
        self._code_svc = code_service
        self._test_svc = test_service
        self._cicd_svc = cicd_service
        self._security_svc = security_service
        self._arch_svc = architecture_service
        self._agent_timeout = agent_timeout

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def orchestrate(self, target: RepositoryTarget) -> EngineeringReviewAggregate:
        """
        Run the full review pipeline for a repository target.

        For GitHub URLs the clone is kept alive for the entire pipeline duration
        via an async context manager and cleaned up automatically on exit.
        """
        review_id = uuid.uuid4()
        logger.info(
            "orchestrator.start",
            review_id=str(review_id),
            repo_url=target.repo_url,
            local_path=target.local_path,
        )

        if target.repo_url:
            async with self._github_loader.clone_context(target.repo_url) as ingested:
                return await self._run_pipeline(review_id, target, ingested)
        else:
            assert target.local_path is not None
            ingested = await self._local_loader.load(target.local_path)
            return await self._run_pipeline(review_id, target, ingested)

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------

    async def _run_pipeline(
        self,
        review_id: uuid.UUID,
        target: RepositoryTarget,
        ingested: RepositoryMetadata,
    ) -> EngineeringReviewAggregate:
        """Core pipeline: tool context → agents → score → persist."""
        t0 = time.monotonic()

        repo_metadata = self._to_repo_metadata(ingested, target)
        logger.info(
            "orchestrator.metadata_loaded",
            name=repo_metadata.name,
            files=len(repo_metadata.file_tree),
            language=repo_metadata.primary_language,
        )

        # Stage 1 — intelligence services run in parallel (I/O-bound, independent)
        tool_context = await self._gather_tool_context(repo_metadata)
        logger.info(
            "orchestrator.tool_context_ready",
            services=list(tool_context.keys()),
            elapsed_s=round(time.monotonic() - t0, 2),
        )

        # Stage 2 — all agents run concurrently; failures produce fallback findings
        findings = await self._run_agents(repo_metadata, tool_context)
        failed_count = sum(
            1 for f in findings if f.summary.startswith(_FALLBACK_SUMMARY_PREFIX)
        )
        logger.info(
            "orchestrator.agents_complete",
            total=len(findings),
            failed=failed_count,
            elapsed_s=round(time.monotonic() - t0, 2),
        )

        # Stage 3 — scoring
        overall_score, risk_level = self._scoring_engine.compute(findings)
        logger.info(
            "orchestrator.scored",
            overall_score=overall_score,
            risk_level=risk_level.value,
            elapsed_s=round(time.monotonic() - t0, 2),
        )

        # Stage 4 — build aggregate and persist
        # FAILED only when every single agent produced a fallback finding
        status = (
            ReviewStatus.FAILED
            if failed_count == len(self._agents)
            else ReviewStatus.COMPLETED
        )
        aggregate = EngineeringReviewAggregate(
            review_id=review_id,
            repo_url=target.repo_url,
            local_path=target.local_path,
            overall_score=overall_score,
            risk_level=risk_level,
            agent_results=findings,
            status=status,
        )
        await self._repository.save(aggregate)
        logger.info(
            "orchestrator.persisted",
            review_id=str(review_id),
            status=status.value,
            total_elapsed_s=round(time.monotonic() - t0, 2),
        )
        return aggregate

    async def _gather_tool_context(self, repo_metadata: RepoMetadata) -> dict[str, Any]:
        """
        Run all intelligence services concurrently.

        Services are I/O-bound and fully independent so parallel execution is safe.
        Individual failures are captured and replaced with empty dicts so the
        pipeline never aborts due to a single service failure.
        """
        file_tree = list(repo_metadata.file_tree)
        local_path = repo_metadata.local_path

        results = await asyncio.gather(
            self._code_svc.analyze(file_tree, local_path),
            self._test_svc.analyze(file_tree, local_path),
            self._cicd_svc.analyze(file_tree, local_path),
            self._security_svc.analyze(file_tree, local_path),
            self._arch_svc.analyze(file_tree, local_path),
            return_exceptions=True,
        )

        keys = [
            "code_intelligence",
            "test_intelligence",
            "cicd_intelligence",
            "security_intelligence",
            "architecture_intelligence",
        ]
        context: dict[str, Any] = {}
        for key, result in zip(keys, results):
            if isinstance(result, Exception):
                logger.warning(
                    "tool_context.service_failed",
                    service=key,
                    error=str(result),
                    error_type=type(result).__name__,
                )
                context[key] = {}
            else:
                context[key] = result

        return context

    async def _run_agents(
        self,
        repo_metadata: RepoMetadata,
        tool_context: dict[str, Any],
    ) -> list[AgentFinding]:
        """
        Execute all agents **concurrently** via asyncio.gather.

        Each agent is wrapped in :meth:`_execute_agent_safe` which:

        * applies the per-agent timeout (``self._agent_timeout``)
        * catches every possible exception
        * returns a structured fallback :class:`AgentFinding` (score=0) on failure

        Because every coroutine is wrapped, ``asyncio.gather`` never sees an
        exception — it always receives a list of AgentFindings.  The caller
        can inspect ``finding.summary.startswith(_FALLBACK_SUMMARY_PREFIX)`` to
        identify failed agents.
        """
        tasks = [
            self._execute_agent_safe(
                agent=agent,
                repo_metadata=repo_metadata,
                agent_ctx=self._build_agent_context(agent.agent_name, tool_context),
            )
            for agent in self._agents
        ]
        results: list[AgentFinding] = list(await asyncio.gather(*tasks))
        return results

    async def _execute_agent_safe(
        self,
        agent: BaseEngineeringAgent,
        repo_metadata: RepoMetadata,
        agent_ctx: dict[str, Any],
    ) -> AgentFinding:
        """
        Execute a single agent with timeout and full exception safety.

        **Always** returns an :class:`AgentFinding` — never raises.

        On success the genuine finding is returned.
        On any failure (timeout, execution error, unexpected exception) a
        fallback finding is returned with:

        * ``score = 0``
        * ``summary`` prefixed with :data:`_FALLBACK_SUMMARY_PREFIX`
        * a single ``AgentIssue`` of ``CRITICAL`` severity describing the cause
        """
        t0 = time.monotonic()
        agent_name = agent.agent_name
        logger.info("agent.start", agent=agent_name.value)

        try:
            finding = await asyncio.wait_for(
                agent.analyze(repo_metadata, agent_ctx),
                timeout=self._agent_timeout,
            )
            logger.info(
                "agent.succeeded",
                agent=agent_name.value,
                score=finding.score,
                elapsed_s=round(time.monotonic() - t0, 2),
            )
            return finding

        except asyncio.TimeoutError:
            reason = f"timed out after {self._agent_timeout}s"
            logger.error(
                "agent.timeout",
                agent=agent_name.value,
                timeout_s=self._agent_timeout,
                elapsed_s=round(time.monotonic() - t0, 2),
            )

        except AgentExecutionError as exc:
            reason = str(exc)
            logger.error(
                "agent.execution_error",
                agent=agent_name.value,
                error=reason,
                elapsed_s=round(time.monotonic() - t0, 2),
            )

        except Exception as exc:  # noqa: BLE001
            reason = f"{type(exc).__name__}: {exc}"
            logger.error(
                "agent.unexpected_error",
                agent=agent_name.value,
                error=reason,
                error_type=type(exc).__name__,
                elapsed_s=round(time.monotonic() - t0, 2),
            )

        return _make_fallback_finding(agent_name, reason)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_agent_context(
        agent_name: AgentName,
        tool_context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Return a filtered view of *tool_context* containing only the service
        keys relevant to the given agent.

        Falls back to the full context for agent names not in the map
        (forward compatibility with new agents).
        """
        keys = _AGENT_CONTEXT_KEYS.get(agent_name)
        if keys is None:
            return dict(tool_context)
        return {k: tool_context.get(k, {}) for k in keys}

    @staticmethod
    def _to_repo_metadata(
        ingested: RepositoryMetadata,
        target: RepositoryTarget,
    ) -> RepoMetadata:
        """Convert infrastructure ``RepositoryMetadata`` → domain ``RepoMetadata`` VO."""
        return RepoMetadata(
            name=ingested.name,
            primary_language=ingested.primary_language,
            file_tree=[e.path for e in ingested.file_index],
            local_path=ingested.root_path,
            repo_url=target.repo_url,
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _make_fallback_finding(agent_name: AgentName, reason: str) -> AgentFinding:
    """
    Build a zero-score fallback :class:`AgentFinding` for a failed agent.

    The summary is prefixed with :data:`_FALLBACK_SUMMARY_PREFIX` so callers
    can detect fallbacks without inspecting issues or scores.
    """
    return AgentFinding(
        agent_name=agent_name,
        score=0,
        summary=f"{_FALLBACK_SUMMARY_PREFIX}: {reason}",
        issues=[
            AgentIssue(
                severity=Severity.CRITICAL,
                title="Agent Execution Failed",
                description=(
                    f"Agent '{agent_name.value}' did not produce a finding. "
                    f"Reason: {reason}"
                ),
                recommendation=(
                    "Check application logs for the full stack trace. "
                    "Verify LLM connectivity, timeouts, and agent configuration."
                ),
            )
        ],
        recommendations=[
            f"Investigate why {agent_name.value} failed and re-run the review."
        ],
    )
