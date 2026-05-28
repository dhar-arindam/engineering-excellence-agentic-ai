"""Scan Orchestrator — drives the full async scan pipeline with progress tracking.

Pipeline stages and progress checkpoints
-----------------------------------------
  5 %  → scan status set to "running"
 15 %  → source prepared (clone complete / local path validated)
 25 %  → repository ingested (file index built, language detected)
 35 %  → intelligence tool context gathered
 35–90% → per-agent progress increments (~11 % per agent, 5 agents)
 95 %  → results scored and persisted
100 %  → scan marked "completed"

Execution plan
--------------
A :class:`~app.application.scan_config_resolver.ScanExecutionPlan` is resolved
from the scan's ``scan_config_json`` + ``scan_mode`` columns at the start of
the pipeline.  It controls which agents run, the file cap, and whether
architecture drift analysis is enabled.

WebSocket events
----------------
A :class:`~app.application.scan_event_bus.ScanEventBus` is optionally injected.
When present, the orchestrator emits ``log``, ``progress``, and ``status``
events at every meaningful stage so browser clients can stream live updates
via ``/ws/scans/{scan_id}``.

Timeout
-------
The entire pipeline is wrapped in ``asyncio.wait_for(timeout=pipeline_timeout)``.
When the timeout fires, the scan is marked "failed" and the GitHub clone (if any)
is cleaned up.  The Arq worker's ``job_timeout`` provides a second, outer timeout
that cancels the asyncio task if the pipeline wrapper itself hangs.

Cancellation
------------
:class:`~app.infrastructure.redis_client.RedisClient` is polled between each major
stage.  When a cancel flag is detected, :class:`~app.core.exceptions.ScanCancelledError`
is raised and the scan is marked "cancelled".  The Redis cancel flag and the
per-repository distributed lock are cleaned up by the Arq task wrapper in
:mod:`app.infrastructure.arq_worker`.

Design rules
------------
- Fully async; no blocking calls.
- No HTTP or API-layer concerns.
- Progress is written to the DB after every major stage.
- Each agent runs concurrently via asyncio.gather; individual timeouts are
  enforced by :meth:`_execute_agent_safe`.
- GitHub clones are always cleaned up in the ``finally`` block.
"""
from __future__ import annotations

import asyncio
import re
import time
import uuid
from typing import TYPE_CHECKING, Any

from app.application.agents.base import BaseEngineeringAgent
from app.application.scan_config_resolver import ScanConfigResolver, ScanExecutionPlan
from app.application.scoring_engine import ScoringEngine
from app.application.source_preparation import SourcePreparationService
from app.application.tool_interfaces import (
    ArchitectureAnalysisService,
    CiCdIntelligenceService,
    CodeIntelligenceService,
    SecurityIntelligenceService,
    TestIntelligenceService,
)
from app.core.exceptions import AgentExecutionError, ScanCancelledError
from app.core.logging import get_logger
from app.domain.entities import AgentFinding, AgentIssue
from app.domain.enums import AgentName, ScanStatus, Severity
from app.domain.value_objects import RepoMetadata
from app.infrastructure.db.scan_repository import ScanRepository, open_scan_repository
from app.infrastructure.github_clone import GitHubCloner
from app.infrastructure.repository_ingestion.github_loader import GitHubRepositoryLoader
from app.infrastructure.repository_ingestion.local_loader import LocalRepositoryLoader
from app.infrastructure.repository_ingestion.scanner import (
    build_file_index,
    count_lines_of_code,
    detect_frameworks,
    detect_primary_language,
)

if TYPE_CHECKING:
    from app.application.scan_event_bus import ScanEventBus
    from app.infrastructure.redis_client import RedisClient

logger = get_logger(__name__)

_DEFAULT_AGENT_TIMEOUT: float = 120.0  # LLM timeout is 60s; allow one retry + backoff
_DEFAULT_PIPELINE_TIMEOUT: float = 600.0
_FALLBACK_SUMMARY_PREFIX = "Agent execution failed"

# Context keys consumed by each agent (mirrors the existing orchestrator mapping).
_AGENT_CONTEXT_KEYS: dict[AgentName, list[str]] = {
    AgentName.SENIOR_QA:        ["test_intelligence", "cicd_intelligence"],
    AgentName.SENIOR_DEVELOPER: ["code_intelligence", "test_intelligence"],
    AgentName.SENIOR_ARCHITECT: ["code_intelligence", "architecture_intelligence"],
    AgentName.SENIOR_SRE:       ["cicd_intelligence", "code_intelligence"],
    AgentName.SECURITY_EXPERT:  ["security_intelligence", "cicd_intelligence"],
}

_config_resolver = ScanConfigResolver()


class ScanOrchestrator:
    """Drives the scan pipeline for a single scan record, updating progress in DB."""

    def __init__(
        self,
        scan_repository: ScanRepository,
        source_preparation: SourcePreparationService,
        agents: list[BaseEngineeringAgent],
        scoring_engine: ScoringEngine,
        local_loader: LocalRepositoryLoader,
        github_loader: GitHubRepositoryLoader,
        code_service: CodeIntelligenceService,
        test_service: TestIntelligenceService,
        cicd_service: CiCdIntelligenceService,
        security_service: SecurityIntelligenceService,
        architecture_service: ArchitectureAnalysisService,
        agent_timeout: float = _DEFAULT_AGENT_TIMEOUT,
        github_cloner: GitHubCloner | None = None,
        redis_client: "RedisClient | None" = None,
        pipeline_timeout: float = _DEFAULT_PIPELINE_TIMEOUT,
        event_bus: "ScanEventBus | None" = None,
    ) -> None:
        self._scan_repo = scan_repository
        self._source_prep = source_preparation
        self._agents = agents
        self._scoring_engine = scoring_engine
        self._local_loader = local_loader
        self._github_loader = github_loader
        self._code_svc = code_service
        self._test_svc = test_service
        self._cicd_svc = cicd_service
        self._security_svc = security_service
        self._arch_svc = architecture_service
        self._agent_timeout = agent_timeout
        self._github_cloner = github_cloner or GitHubCloner()
        self._redis = redis_client
        self._pipeline_timeout = pipeline_timeout
        self._event_bus = event_bus

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run_scan(self, scan_id: uuid.UUID) -> None:
        """Execute the full scan pipeline for *scan_id* with timeout and cancel support."""
        t0 = time.monotonic()
        logger.info("scan_orchestrator.start", scan_id=str(scan_id))

        try:
            await asyncio.wait_for(
                self._run_pipeline(scan_id),
                timeout=self._pipeline_timeout,
            )

        except asyncio.TimeoutError:
            timeout_msg = f"Scan timed out after {self._pipeline_timeout:.0f}s."
            logger.error(
                "scan_orchestrator.timeout",
                scan_id=str(scan_id),
                timeout_s=self._pipeline_timeout,
                elapsed_s=round(time.monotonic() - t0, 2),
            )
            await self._scan_repo.update_scan_status(
                scan_id, ScanStatus.FAILED, error_message=timeout_msg
            )
            await self._emit_status("failed", timeout_msg)

        except ScanCancelledError:
            logger.info(
                "scan_orchestrator.cancelled",
                scan_id=str(scan_id),
                elapsed_s=round(time.monotonic() - t0, 2),
            )
            await self._scan_repo.update_scan_status(scan_id, ScanStatus.CANCELLED)
            await self._emit_status("cancelled", "Scan was cancelled.")

        except Exception as exc:  # noqa: BLE001
            error_msg = self._safe_error_message(exc)
            logger.error(
                "scan_orchestrator.failed",
                scan_id=str(scan_id),
                error=error_msg,
                error_type=type(exc).__name__,
                elapsed_s=round(time.monotonic() - t0, 2),
            )
            await self._scan_repo.update_scan_status(
                scan_id, ScanStatus.FAILED, error_message=error_msg
            )
            await self._emit_status("failed", error_msg)

        finally:
            await self._github_cloner.cleanup(scan_id)
            if self._event_bus:
                await self._event_bus.cleanup()

    # ------------------------------------------------------------------
    # Pipeline (inner — raises on error rather than swallowing)
    # ------------------------------------------------------------------

    async def _run_pipeline(self, scan_id: uuid.UUID) -> None:
        """Inner pipeline coroutine — wrapped by run_scan with timeout/error handling."""
        t0 = time.monotonic()

        # Stage 0 — mark running
        await self._scan_repo.update_scan_status(
            scan_id, ScanStatus.RUNNING, progress=5
        )
        await self._emit_status("running", "Scan started.")
        await self._emit_progress(5, "Initialising scan pipeline…")

        # Stage 1 — fetch scan record (reads branch + config)
        scan = await self._scan_repo.get_scan(scan_id)
        source_type = scan.source_type or ""
        source_reference = scan.source_reference or ""
        branch = scan.branch  # may be None
        scan_config: dict | None = scan.scan_config_json

        # Resolve execution plan from stored config.
        plan: ScanExecutionPlan = _config_resolver.resolve(scan_config)
        active_agents = self._filter_agents(plan)

        await self._emit_log(
            f"Execution plan: mode={getattr(scan, 'scan_mode', 'deep')}, "
            f"agents={[a.agent_name.value for a in active_agents]}, "
            f"max_files={plan.max_files}"
        )
        await self._check_cancel(scan_id)

        # Stage 2 — prepare source
        await self._emit_log(
            f"Preparing source ({source_type})"
            + (f", branch={branch}" if branch else "")
            + "…"
        )
        prepared = await self._source_prep.prepare(
            scan_id=scan_id,
            source_type=source_type,
            repository_url=source_reference if source_type == "github" else None,
            local_path=source_reference if source_type == "local" else None,
            branch=branch,
        )
        await self._scan_repo.update_scan_progress(scan_id, 15)
        await self._emit_progress(15, f"Source ready at {prepared.repo_name}.")

        await self._check_cancel(scan_id)

        # Stage 3 — ingest repository (apply max_files from plan)
        await self._emit_log(f"Ingesting repository (max_files={plan.max_files})…")
        repo_metadata = await self._ingest(prepared.path, max_files=plan.max_files)
        await self._scan_repo.update_scan_progress(scan_id, 25)
        await self._emit_progress(25, f"Ingested {len(repo_metadata.file_tree)} files.")

        await self._check_cancel(scan_id)

        # Stage 4 — gather tool context
        await self._emit_log("Gathering intelligence tool context…")
        tool_context = await self._gather_tool_context(repo_metadata)
        await self._scan_repo.update_scan_progress(scan_id, 35)
        await self._emit_progress(35, "Tool context ready.")

        await self._check_cancel(scan_id)

        # Stage 5 — run agents with per-agent progress increments
        findings = await self._run_agents_with_progress(
            scan_id, repo_metadata, tool_context, active_agents
        )

        # Stage 6 — score and persist
        await self._emit_log("Computing overall score…")
        overall_score, risk_level = self._scoring_engine.compute(findings)
        overall_confidence = self._scoring_engine.compute_overall_confidence(findings)
        radar = self._scoring_engine.compute_radar(findings)
        await self._scan_repo.save_scan_results(
            scan_id=scan_id,
            overall_score=overall_score,
            risk_level=risk_level.value,
            agent_findings=[
                {
                    "agent_name": f.agent_name.value,
                    "score": f.score,
                    "summary": f.summary,
                    "confidence": f.confidence,
                    "confidence_reason": f.confidence_reason,
                    "issues": [i.model_dump(mode="json") for i in f.issues],
                    "recommendations": f.recommendations,
                }
                for f in findings
            ],
            overall_confidence=overall_confidence,
            radar_json=radar,
        )
        await self._emit_progress(100, f"Scan complete. Score: {overall_score} (confidence: {overall_confidence:.0%}), Risk: {risk_level.value}.")
        await self._emit_status("completed", f"Scan completed. Score: {overall_score}, Confidence: {overall_confidence:.0%}.")
        logger.info(
            "scan_orchestrator.complete",
            scan_id=str(scan_id),
            overall_score=overall_score,
            risk_level=risk_level.value,
            elapsed_s=round(time.monotonic() - t0, 2),
        )

        # Stage 7 (optional) — auto-fix: patch → validate → PR
        if plan.allow_auto_fix and source_type == "github":
            await self._run_auto_fix(
                scan_id=scan_id,
                source_path=prepared.path,
                repo_url=source_reference,
                base_branch=branch or "main",
                findings=findings,
            )

    # ------------------------------------------------------------------
    # Agent filtering
    # ------------------------------------------------------------------

    def _filter_agents(self, plan: ScanExecutionPlan) -> list[BaseEngineeringAgent]:
        """Return only the agents listed in the execution plan, preserving order."""
        plan_set = set(plan.agents_to_run)
        return [a for a in self._agents if a.agent_name in plan_set]

    # ------------------------------------------------------------------
    # Auto-fix pipeline (Stage 7 — only when plan.allow_auto_fix is True)
    # ------------------------------------------------------------------

    async def _run_auto_fix(
        self,
        scan_id: uuid.UUID,
        source_path: str,
        repo_url: str,
        base_branch: str,
        findings: list,
    ) -> None:
        """Attempt to generate a fix patch, validate it, and open a PR.

        This stage is best-effort — any failure is logged and emitted as a
        warning but does NOT transition the scan to 'failed'.

        Pipeline:
            1. Collect all HIGH/CRITICAL issues from findings.
            2. Create a VirtualWorkspace from the cloned source.
            3. Generate + apply a unified diff patch.
            4. Run the ValidationPipeline in the workspace.
            5. Run the BreakingChangeDetector.
            6. If both pass → call SafePullRequestService.
            7. Emit result via event bus.
        """
        from app.application.breaking_change_detector import BreakingChangeDetector
        from app.application.patch_engine import PatchEngine
        from app.application.safe_pr_service import SafePullRequestService
        from app.application.validation_pipeline import ValidationPipeline
        from app.application.virtual_workspace import VirtualWorkspace
        from app.domain.enums import Severity

        await self._emit_log("Auto-fix: collecting issues for patch generation…")

        # Collect HIGH + CRITICAL issues across all agents.
        high_issues = [
            issue
            for finding in findings
            for issue in finding.issues
            if issue.severity in (Severity.HIGH, Severity.CRITICAL)
        ]

        if not high_issues:
            await self._emit_log("Auto-fix: no HIGH/CRITICAL issues found — skipping PR.")
            return

        await self._emit_log(
            f"Auto-fix: {len(high_issues)} issue(s) to address. Creating virtual workspace…"
        )

        try:
            async with VirtualWorkspace.create(source_path) as workspace:
                # Step 1 — generate + apply patch.
                await self._emit_log("Auto-fix: generating patch…")
                engine = PatchEngine()
                patch_text = await engine.generate_patch(high_issues, workspace)
                if not patch_text.strip():
                    await self._emit_log("Auto-fix: patch engine returned empty diff — skipping.")
                    return

                patch_result = await engine.apply_patch(patch_text, workspace)
                if patch_result.errors:
                    await self._emit_log(
                        f"Auto-fix: patch application errors: {patch_result.errors} — skipping."
                    )
                    return

                # Persist the unified diff so it can be retrieved via the patch endpoint.
                try:
                    async with open_scan_repository() as patch_repo:
                        await patch_repo.save_patch_diff(scan_id, patch_text)
                except Exception as _pe:  # noqa: BLE001
                    await self._emit_log(f"Auto-fix: failed to persist patch — {_pe}")

                await self._emit_log(
                    f"Auto-fix: patch applied to {len(patch_result.modified_files)} file(s). "
                    "Running validation…"
                )

                # Step 2 — validate.
                pipeline = ValidationPipeline()
                v_report = await pipeline.run(workspace)

                # Step 3 — breaking change detection.
                detector = BreakingChangeDetector()
                b_report = await detector.analyze(source_path, workspace)

                await self._emit_log(
                    f"Auto-fix: validation={'passed' if v_report.passed else 'FAILED'}, "
                    f"breaking_changes={b_report.has_breaking_changes}"
                )

                # Step 4 — create PR if safe.
                svc = SafePullRequestService()
                outcome = await svc.create_fix_pr(
                    repo_url=repo_url,
                    base_branch=base_branch,
                    scan_id=scan_id,
                    workspace=workspace,
                    validation_report=v_report,
                    breaking_report=b_report,
                )

                if outcome.created:
                    await self._emit_log(
                        f"Auto-fix: PR created ✅ {outcome.pr_url} "
                        f"(branch={outcome.branch_name})"
                    )
                    await self._emit_status(
                        "completed",
                        f"Fix PR created: {outcome.pr_url}",
                    )
                else:
                    await self._emit_log(
                        f"Auto-fix: PR not created — {outcome.reason}"
                    )

        except Exception as exc:  # noqa: BLE001
            msg = self._safe_error_message(exc)
            logger.error("scan_orchestrator.auto_fix_error", scan_id=str(scan_id), error=msg)
            await self._emit_log(f"Auto-fix: unexpected error — {msg}")

    # ------------------------------------------------------------------
    # Cancellation checkpoint
    # ------------------------------------------------------------------

    async def _check_cancel(self, scan_id: uuid.UUID) -> None:
        """Raise :class:`ScanCancelledError` if a cancellation flag is set in Redis."""
        if self._redis and await self._redis.is_cancel_requested(scan_id):
            raise ScanCancelledError(str(scan_id))

    # ------------------------------------------------------------------
    # Pipeline helpers
    # ------------------------------------------------------------------

    async def _ingest(self, root_path: str, max_files: int = 10_000) -> RepoMetadata:
        """Build file index (capped at *max_files*) and detect language/frameworks."""
        from pathlib import Path

        file_index = await build_file_index(root_path)
        # Apply the plan's file cap.
        if len(file_index) > max_files:
            file_index = file_index[:max_files]

        total_lines, primary_language, frameworks = await asyncio.gather(
            count_lines_of_code(root_path, file_index),
            detect_primary_language(file_index),
            detect_frameworks(root_path, file_index),
        )
        return RepoMetadata(
            name=Path(root_path).name,
            primary_language=primary_language,
            file_tree=[e.path for e in file_index],
            local_path=root_path,
            repo_url=None,
        )

    async def _gather_tool_context(self, repo_metadata: RepoMetadata) -> dict[str, Any]:
        """Run all intelligence services concurrently; replace failures with {}."""
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
                    "scan_orchestrator.service_failed",
                    service=key,
                    error=str(result),
                )
                context[key] = {}
            else:
                context[key] = result
        return context

    async def _run_agents_with_progress(
        self,
        scan_id: uuid.UUID,
        repo_metadata: RepoMetadata,
        tool_context: dict[str, Any],
        active_agents: list[BaseEngineeringAgent],
    ) -> list[AgentFinding]:
        """Run agents concurrently; update DB progress and emit events per completion.

        Progress range for agents: 35 % → 90 % (55 % / n_agents per agent).
        """
        n = len(active_agents)
        step = 55 // n if n else 55
        completed_count = 0
        count_lock = asyncio.Lock()
        db_lock = asyncio.Lock()   # SQLAlchemy AsyncSession is not concurrent-safe

        async def _run_and_track(agent: BaseEngineeringAgent) -> AgentFinding:
            nonlocal completed_count
            await self._emit_log(f"Agent starting: {agent.agent_name.value}")
            finding = await self._execute_agent_safe(
                agent=agent,
                repo_metadata=repo_metadata,
                agent_ctx=self._build_agent_context(agent.agent_name, tool_context),
            )
            async with count_lock:
                completed_count += 1
                new_progress = min(35 + completed_count * step, 90)
            # Serialize DB writes — multiple agents finishing simultaneously would
            # otherwise trigger concurrent access on the same AsyncSession.
            async with db_lock:
                await self._scan_repo.update_scan_progress(scan_id, new_progress)
            await self._emit_progress(
                new_progress,
                f"Agent {agent.agent_name.value} done (score={finding.score}).",
            )
            await self._emit_log(
                f"Agent {agent.agent_name.value} completed: score={finding.score}, "
                f"issues={len(finding.issues)}"
            )
            return finding

        # Emit one log line listing all agents about to run.
        await self._emit_log(
            f"Running {n} agent(s) in parallel: "
            f"{[a.agent_name.value for a in active_agents]}"
        )

        findings: list[AgentFinding] = list(
            await asyncio.gather(*[_run_and_track(a) for a in active_agents])
        )
        return findings

    async def _execute_agent_safe(
        self,
        agent: BaseEngineeringAgent,
        repo_metadata: RepoMetadata,
        agent_ctx: dict[str, Any],
    ) -> AgentFinding:
        """Execute a single agent with timeout and exception safety; never raises."""
        t0 = time.monotonic()
        agent_name = agent.agent_name
        logger.info("scan_agent.start", agent=agent_name.value)

        try:
            finding = await asyncio.wait_for(
                agent.analyze(repo_metadata, agent_ctx),
                timeout=self._agent_timeout,
            )
            logger.info(
                "scan_agent.succeeded",
                agent=agent_name.value,
                score=finding.score,
                elapsed_s=round(time.monotonic() - t0, 2),
            )
            return finding

        except asyncio.TimeoutError:
            reason = f"timed out after {self._agent_timeout}s"
        except AgentExecutionError as exc:
            reason = str(exc)
        except Exception as exc:  # noqa: BLE001
            reason = f"{type(exc).__name__}: {exc}"

        logger.error(
            "scan_agent.failed",
            agent=agent_name.value,
            reason=reason,
            elapsed_s=round(time.monotonic() - t0, 2),
        )
        return _make_fallback_finding(agent_name, reason)

    # ------------------------------------------------------------------
    # Event bus helpers (no-op when bus is not injected)
    # ------------------------------------------------------------------

    async def _emit_log(self, message: str) -> None:
        if self._event_bus:
            await self._event_bus.log(message)

    async def _emit_progress(self, pct: int, message: str = "") -> None:
        if self._event_bus:
            await self._event_bus.progress(pct, message)

    async def _emit_status(self, status: str, message: str = "") -> None:
        if self._event_bus:
            await self._event_bus.status(status, message)

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_agent_context(
        agent_name: AgentName,
        tool_context: dict[str, Any],
    ) -> dict[str, Any]:
        keys = _AGENT_CONTEXT_KEYS.get(agent_name)
        if keys is None:
            return dict(tool_context)
        return {k: tool_context.get(k, {}) for k in keys}

    @staticmethod
    def _safe_error_message(exc: Exception) -> str:
        """Return an error string with internal filesystem paths removed."""
        msg = f"{type(exc).__name__}: {exc}"
        msg = re.sub(r"(/[^\s,;'\"]+|[A-Za-z]:\\[^\s,;'\"]+)", "<path>", msg)
        return msg[:2048]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _make_fallback_finding(agent_name: AgentName, reason: str) -> AgentFinding:
    return AgentFinding(
        agent_name=agent_name,
        score=0,
        summary=f"{_FALLBACK_SUMMARY_PREFIX}: {reason}",
        confidence=0.0,
        confidence_reason=f"Agent failed: {reason}",
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
            f"Investigate why {agent_name.value} failed and re-run the scan."
        ],
    )

