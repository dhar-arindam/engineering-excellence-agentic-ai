"""SeniorSREAgent — data-driven SRE evaluation from CI/CD and code intelligence."""
from __future__ import annotations

import uuid
from typing import Any

from app.application.agents.base import BaseEngineeringAgent
from app.domain.entities import AgentFinding, AgentIssue
from app.domain.enums import AgentName, Severity
from app.domain.value_objects import RepoMetadata


class SeniorSREAgent(BaseEngineeringAgent):
    """Evaluates reliability, observability, deployment safety, and operational readiness.

    Scoring is deterministic and derived from CiCdIntelligenceService data.
    No LLM is used.
    """

    @property
    def agent_name(self) -> AgentName:
        return AgentName.SENIOR_SRE

    @property
    def role_definition(self) -> str:
        return (
            "You are a Senior Site Reliability Engineer with 15+ years of experience operating "
            "large-scale distributed systems. You evaluate reliability engineering, SLO definitions, "
            "error budgets, operational runbooks, deployment safety, and incident response readiness."
        )

    @property
    def evaluation_rubric(self) -> dict[str, Any]:
        return {
            "ci_pipeline":       {"weight": 0.20, "criteria": "CI pipeline present and functional"},
            "tests_in_ci":       {"weight": 0.15, "criteria": "Tests executed in pipeline"},
            "containerisation":  {"weight": 0.20, "criteria": "Dockerfile with multi-stage build"},
            "security_scan":     {"weight": 0.15, "criteria": "Security scanning in pipeline"},
            "quality_gates":     {"weight": 0.10, "criteria": "Lint and quality checks in CI"},
            "caching":           {"weight": 0.05, "criteria": "Dependency caching in CI"},
            "parallel_jobs":     {"weight": 0.05, "criteria": "Parallel pipeline jobs"},
            "deploy_stage":      {"weight": 0.10, "criteria": "Automated deploy/release stage"},
        }

    async def analyze(
        self,
        repo_metadata: RepoMetadata,
        tool_context: dict[str, Any],
    ) -> AgentFinding:
        cicd = tool_context.get("cicd_intelligence", {})
        code = tool_context.get("code_intelligence", {})

        score, issues, recommendations = _score_sre(
            repo_name=repo_metadata.name,
            cicd_ctx=cicd,
            code_ctx=code,
        )
        confidence, confidence_reason = _sre_confidence(cicd, code)

        return AgentFinding(
            agent_name=self.agent_name,
            score=score,
            summary=_sre_summary(repo_metadata.name, score, cicd),
            issues=issues,
            recommendations=recommendations,
            confidence=confidence,
            confidence_reason=confidence_reason,
        )


# ---------------------------------------------------------------------------
# Scoring logic
# ---------------------------------------------------------------------------

def _score_sre(
    repo_name: str,
    cicd_ctx: dict[str, Any],
    code_ctx: dict[str, Any],
) -> tuple[int, list[AgentIssue], list[str]]:
    score = 0
    issues: list[AgentIssue] = []
    recommendations: list[str] = []

    # --- CI pipeline present (0-20 pts) ---
    if cicd_ctx.get("has_pipeline"):
        score += 20
        platform = cicd_ctx.get("ci_platform") or "a CI platform"
        # bonus: detect platform-specific recommendations
    else:
        issues.append(_issue(Severity.HIGH, None, "No CI pipeline detected",
            "No GitHub Actions, Azure DevOps, GitLab CI or equivalent pipeline found.",
            "Set up a CI pipeline to automate testing, linting, and deployments."))
        recommendations.append(
            "Start with GitHub Actions — add a minimal ci.yml running tests on every push."
        )

    # --- Tests in CI (0-15 pts) ---
    if cicd_ctx.get("runs_tests"):
        score += 15
    elif cicd_ctx.get("has_pipeline"):
        issues.append(_issue(Severity.HIGH, None, "Pipeline does not run tests",
            "CI pipeline is present but no test execution step was detected.",
            "Add a test step (e.g., `pytest tests/`) before any build or deploy stage."))

    # --- Dockerfile + multi-stage build (0-20 pts) ---
    if cicd_ctx.get("dockerfile_present"):
        score += 10
        if cicd_ctx.get("multi_stage_build"):
            score += 10
        else:
            recommendations.append(
                "Convert the Dockerfile to a multi-stage build to reduce image size "
                "and separate build dependencies from the runtime image."
            )
    else:
        issues.append(_issue(Severity.MEDIUM, None, "No Dockerfile found",
            "No container definition detected in the repository.",
            "Add a Dockerfile; use a multi-stage build for production images."))

    # --- Security scan in CI (0-15 pts) ---
    if cicd_ctx.get("has_security_scan"):
        score += 15
    else:
        issues.append(_issue(Severity.MEDIUM, None, "No security scan in CI",
            "Pipeline does not include a security scanning step (Trivy, Snyk, Bandit, etc.).",
            "Add a SAST/SCA scan stage to the CI pipeline."))
        recommendations.append("Integrate Trivy image scanning or Snyk dependency checking into CI.")

    # --- Linting / quality gate (0-10 pts) ---
    if cicd_ctx.get("runs_lint") or cicd_ctx.get("has_quality_gate"):
        score += 10
    else:
        recommendations.append(
            "Add a linting step (ruff, flake8, eslint) as a mandatory CI quality gate."
        )

    # --- Caching (0-5 pts) ---
    if cicd_ctx.get("uses_cache"):
        score += 5
    else:
        recommendations.append("Enable dependency caching in CI to reduce build times.")

    # --- Parallel jobs (0-5 pts) ---
    if cicd_ctx.get("has_parallel_jobs"):
        score += 5

    # --- Deploy stage (0-10 pts) ---
    if cicd_ctx.get("has_deploy_stage"):
        score += 10
    else:
        recommendations.append(
            "Add an automated deploy stage to enable repeatable, audited releases."
        )

    # --- Bonus: low complexity improves deployability signal (0-5 pts implicit via code_ctx) ---
    # Not scored separately here — complexity is the architect's domain.

    return min(100, max(0, score)), issues, recommendations


def _sre_confidence(cicd_ctx: dict, code_ctx: dict) -> tuple[float, str]:
    signals = {
        "cicd_present": bool(cicd_ctx),
        "platform_detected": "pipeline_platforms" in cicd_ctx,
        "tests_in_ci_known": "runs_tests" in cicd_ctx,
        "dockerfile_known": "has_dockerfile" in cicd_ctx or "has_multi_stage_docker" in cicd_ctx,
    }
    available = sum(signals.values())
    confidence = min(1.0, round(0.3 + available * 0.175, 3))
    missing = [k for k, v in signals.items() if not v]
    if missing:
        reason = f"Confidence based on {available}/4 CI/CD signals; missing: {', '.join(missing)}"
    else:
        reason = "All 4 CI/CD intelligence signals available"
    return confidence, reason


def _sre_summary(
    repo_name: str,
    score: int,
    cicd_ctx: dict[str, Any],
) -> str:
    platform = cicd_ctx.get("ci_platform") or "no CI platform"
    stages = cicd_ctx.get("stages", [])
    stage_str = ", ".join(stages) if stages else "none detected"
    has_docker = cicd_ctx.get("dockerfile_present", False)
    docker_str = "Dockerfile present" if has_docker else "no Dockerfile"
    return (
        f"Repository '{repo_name}' achieved an SRE score of {score}/100. "
        f"CI: {platform}. Detected stages: {stage_str}. {docker_str}."
    )


def _issue(
    severity: Severity,
    file_path: str | None,
    title: str,
    description: str,
    recommendation: str,
) -> AgentIssue:
    return AgentIssue(
        id=uuid.uuid4(),
        severity=severity,
        file_path=file_path,
        title=title,
        description=description,
        recommendation=recommendation,
    )
