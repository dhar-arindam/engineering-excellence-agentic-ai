"""Real CiCdIntelligenceService — deterministic YAML + Dockerfile analysis.

Implements the CiCdIntelligenceService ABC from the application layer.
All blocking I/O (file reads, YAML parsing) runs in an asyncio executor
so the event loop is never blocked.

No LLM calls. No side effects beyond reading files.
"""
from __future__ import annotations

import asyncio
from typing import Any

from app.application.tool_interfaces import CiCdIntelligenceService
from app.core.logging import get_logger
from app.infrastructure.intelligence.cicd_engine import (
    analyse_cicd_sync,
    build_cicd_metrics,
)
from app.infrastructure.intelligence.cicd_models import CiCdAnalysisResult

logger = get_logger(__name__)


class RealCiCdIntelligenceService(CiCdIntelligenceService):
    """
    Deterministic CI/CD intelligence using YAML safe-loading and Dockerfile parsing.

    Supports:
    - GitHub Actions (.github/workflows/*.yml)
    - Azure DevOps  (azure-pipelines.yml)
    - GitLab CI     (.gitlab-ci.yml)
    - CircleCI      (.circleci/config.yml)
    - Bitbucket     (bitbucket-pipelines.yml)
    - Jenkins       (Jenkinsfile)
    - Travis CI     (.travis.yml)
    - Dockerfile    (multi-stage builds, EXPOSE, USER)

    The ``analyze()`` method satisfies the ``CiCdIntelligenceService`` ABC
    and returns a dict that is a superset of the stub contract.

    For callers that want typed results, use ``analyze_structured()``.
    """

    async def analyze(
        self,
        file_tree: list[str],
        local_path: str | None = None,
    ) -> dict[str, Any]:
        """
        Run CI/CD analysis and return a dict compatible with the agent tool context.

        Extends the stub output with:
          - ``stages``             inferred stage names (lint, test, security, deploy)
          - ``ci_platform``        detected platform display name
          - ``pipeline_details``   list of PipelineFile dicts
          - ``dockerfile_details`` list of DockerfileAnalysis dicts
          - ``parse_errors``       files that failed to parse
        """
        if not local_path:
            logger.warning("cicd_intelligence.no_local_path")
            return self._empty_result(file_tree)

        result = await self.analyze_structured(file_tree, local_path)
        m = result.metrics

        return {
            # Backward-compatible keys (match stub + ABC contract)
            "ci_platform": m.ci_platform,
            "has_pipeline": m.has_ci_pipeline,
            "stages": m.stages_detected,
            "has_deploy_stage": m.has_deploy_stage,
            "has_security_scan": m.has_security_scan,
            "has_quality_gate": m.runs_lint or m.runs_tests,
            # Extended keys
            "runs_tests": m.runs_tests,
            "runs_lint": m.runs_lint,
            "uses_cache": m.uses_cache,
            "has_parallel_jobs": m.has_parallel_jobs,
            "dockerfile_present": m.dockerfile_present,
            "multi_stage_build": m.multi_stage_build,
            "pipeline_files": m.pipeline_files,
            "ci_metrics": m.model_dump(),
            "pipeline_details": [pd.model_dump() for pd in result.pipeline_details],
            "dockerfile_details": [dd.model_dump() for dd in result.dockerfile_details],
            "parse_errors": result.parse_errors,
        }

    async def analyze_structured(
        self,
        file_tree: list[str],
        local_path: str,
    ) -> CiCdAnalysisResult:
        """Run analysis and return typed ``CiCdAnalysisResult``."""
        logger.info(
            "cicd_intelligence.start",
            total_files=len(file_tree),
            root=local_path,
        )

        loop = asyncio.get_running_loop()
        pipeline_files, dockerfile_analyses, signals, parse_errors = await loop.run_in_executor(
            None, analyse_cicd_sync, local_path, file_tree
        )

        metrics = build_cicd_metrics(pipeline_files, dockerfile_analyses, signals)

        logger.info(
            "cicd_intelligence.done",
            pipelines=len(pipeline_files),
            dockerfiles=len(dockerfile_analyses),
            platform=metrics.ci_platform,
            parse_errors=len(parse_errors),
        )

        return CiCdAnalysisResult(
            metrics=metrics,
            pipeline_details=pipeline_files,
            dockerfile_details=dockerfile_analyses,
            parse_errors=parse_errors,
        )

    @staticmethod
    def _empty_result(file_tree: list[str]) -> dict[str, Any]:
        from app.infrastructure.intelligence.cicd_engine import (
            classify_pipeline_file,
            is_dockerfile,
        )

        pipeline_count = sum(1 for f in file_tree if classify_pipeline_file(f))
        dockerfile_count = sum(1 for f in file_tree if is_dockerfile(f))
        return {
            "ci_platform": None,
            "has_pipeline": pipeline_count > 0,
            "stages": [],
            "has_deploy_stage": False,
            "has_security_scan": False,
            "has_quality_gate": False,
            "runs_tests": False,
            "runs_lint": False,
            "uses_cache": False,
            "has_parallel_jobs": False,
            "dockerfile_present": dockerfile_count > 0,
            "multi_stage_build": False,
            "pipeline_files": [],
            "ci_metrics": {},
            "pipeline_details": [],
            "dockerfile_details": [],
            "parse_errors": [],
        }
