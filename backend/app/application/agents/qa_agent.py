"""SeniorQAAgent — data-driven QA evaluation from test + CI/CD intelligence."""
from __future__ import annotations

import uuid
from typing import Any

from app.application.agents.base import BaseEngineeringAgent
from app.domain.entities import AgentFinding, AgentIssue
from app.domain.enums import AgentName, Severity
from app.domain.value_objects import RepoMetadata


class SeniorQAAgent(BaseEngineeringAgent):
    """Evaluates test coverage, test quality, CI test pipelines, and QA maturity.

    Scoring is deterministic and derived from TestIntelligenceService and
    CiCdIntelligenceService data.  No LLM is used.
    """

    @property
    def agent_name(self) -> AgentName:
        return AgentName.SENIOR_QA

    @property
    def role_definition(self) -> str:
        return (
            "You are a Senior QA Engineer with 15+ years of experience in test strategy, "
            "test automation, and quality engineering. You evaluate repositories for test "
            "coverage, test quality, testing pyramid adherence, flakiness, and CI integration."
        )

    @property
    def evaluation_rubric(self) -> dict[str, Any]:
        return {
            "test_coverage":     {"weight": 0.30, "criteria": "Line coverage %"},
            "test_volume":       {"weight": 0.20, "criteria": "Adequate number of test cases"},
            "ci_integration":    {"weight": 0.15, "criteria": "Tests run in CI pipeline"},
            "mock_isolation":    {"weight": 0.10, "criteria": "Test isolation via mocking"},
            "assertion_density": {"weight": 0.10, "criteria": "Assertions per test case"},
            "source_coverage":   {"weight": 0.15, "criteria": "Source files have matching tests"},
        }

    async def analyze(
        self,
        repo_metadata: RepoMetadata,
        tool_context: dict[str, Any],
    ) -> AgentFinding:
        test  = tool_context.get("test_intelligence", {})
        cicd  = tool_context.get("cicd_intelligence", {})

        score, issues, recommendations = _score_qa(
            repo_name=repo_metadata.name,
            test_ctx=test,
            cicd_ctx=cicd,
        )
        confidence, confidence_reason = _qa_confidence(test, cicd)

        return AgentFinding(
            agent_name=self.agent_name,
            score=score,
            summary=_qa_summary(repo_metadata.name, score, test, cicd),
            issues=issues,
            recommendations=recommendations,
            confidence=confidence,
            confidence_reason=confidence_reason,
        )


# ---------------------------------------------------------------------------
# Scoring logic (pure functions — easy to unit test)
# ---------------------------------------------------------------------------

def _score_qa(
    repo_name: str,
    test_ctx: dict[str, Any],
    cicd_ctx: dict[str, Any],
) -> tuple[int, list[AgentIssue], list[str]]:
    score = 0
    issues: list[AgentIssue] = []
    recommendations: list[str] = []

    # --- Coverage (0-35 pts) ---
    coverage = test_ctx.get("coverage_percent")
    if coverage is None:
        score += 10  # unknown — mild penalty vs full credit
        recommendations.append(
            "Integrate pytest-cov and publish a coverage.xml artifact in CI."
        )
    elif coverage >= 80:
        score += 35
    elif coverage >= 65:
        score += 25
        recommendations.append(f"Raise coverage from {coverage:.0f}% to ≥80% (currently {coverage:.0f}%).")
    elif coverage >= 50:
        score += 15
        issues.append(_issue(Severity.HIGH, None, "Low test coverage",
            f"Coverage is {coverage:.0f}% — below the recommended 80% threshold.",
            "Add unit tests for untested modules; enforce coverage gate in CI."))
    else:
        score += 5
        issues.append(_issue(Severity.CRITICAL, None, "Critical test coverage gap",
            f"Coverage is only {coverage:.0f}%.",
            "Immediately add tests; block merges below 60% coverage."))

    # --- Test volume (0-20 pts) ---
    total_cases = test_ctx.get("total_test_cases", 0)
    test_files  = test_ctx.get("test_file_count", 0)

    if total_cases == 0:
        issues.append(_issue(Severity.CRITICAL, None, "No test cases found",
            "Zero test functions detected across the repository.",
            "Introduce a pytest test suite covering at minimum the core business logic."))
    elif total_cases >= 30:
        score += 20
    elif total_cases >= 10:
        score += 12
    elif total_cases >= 3:
        score += 6

    # --- CI runs tests (0-15 pts) ---
    if cicd_ctx.get("runs_tests"):
        score += 15
    else:
        issues.append(_issue(Severity.MEDIUM, None, "Tests not wired into CI pipeline",
            "No test execution step detected in any CI pipeline configuration.",
            "Add a `pytest` step to the CI workflow before any deploy stage."))
        recommendations.append("Enforce a CI quality gate: fail the pipeline when tests fail.")

    # --- Mock / isolation (0-10 pts) ---
    mock_files = test_ctx.get("mock_usage_files", [])
    if mock_files:
        score += 10
    elif total_cases > 0:
        recommendations.append(
            "Use unittest.mock or pytest-mock to isolate tests from external dependencies."
        )

    # --- Assertion density (0-10 pts) ---
    assertion_density = test_ctx.get("assertion_density", {})
    if assertion_density:
        avg_density = sum(assertion_density.values()) / len(assertion_density)
        if avg_density >= 3:
            score += 10
        elif avg_density >= 1.5:
            score += 6
        elif avg_density > 0:
            score += 3
            recommendations.append(
                "Increase assertion density — aim for ≥3 assertions per test function."
            )
        else:
            issues.append(_issue(Severity.MEDIUM, None, "Tests lack assertions",
                "Many test files have zero assertion statements.",
                "Replace pass-through tests with meaningful assertions."))

    # --- Source coverage (0-10 pts) ---
    metrics = test_ctx.get("test_metrics", {})
    without_tests = metrics.get("files_without_tests", [])
    if isinstance(without_tests, list):
        if len(without_tests) == 0:
            score += 10
        elif len(without_tests) <= 3:
            score += 6
        elif len(without_tests) <= 10:
            score += 3
            recommendations.append(
                f"{len(without_tests)} source files have no corresponding test file."
            )
        else:
            issues.append(_issue(Severity.MEDIUM, None, "Many untested source files",
                f"{len(without_tests)} source files have no matching test file.",
                "Create test modules mirroring the source layout."))

    return min(100, max(0, score)), issues, recommendations


def _qa_confidence(test_ctx: dict, cicd_ctx: dict) -> tuple[float, str]:
    signals = {
        "coverage_known": test_ctx.get("coverage_percent") is not None,
        "test_count_known": "total_test_cases" in test_ctx,
        "ci_detected": "runs_tests" in cicd_ctx,
        "test_files_found": test_ctx.get("test_file_count", -1) >= 0,
    }
    available = sum(signals.values())
    confidence = min(1.0, round(0.4 + available * 0.15, 3))
    missing = [k for k, v in signals.items() if not v]
    if missing:
        reason = f"Confidence based on {available}/4 signals; missing: {', '.join(missing)}"
    else:
        reason = "All 4 test intelligence signals available"
    return confidence, reason


def _qa_summary(
    repo_name: str,
    score: int,
    test_ctx: dict[str, Any],
    cicd_ctx: dict[str, Any],
) -> str:
    coverage = test_ctx.get("coverage_percent")
    total_cases = test_ctx.get("total_test_cases", 0)
    ci_tests = cicd_ctx.get("runs_tests", False)
    cov_str = f"{coverage:.0f}%" if coverage is not None else "unknown"
    ci_str = "CI pipeline executes tests" if ci_tests else "tests not found in CI"
    return (
        f"Repository '{repo_name}' achieved a QA score of {score}/100. "
        f"Coverage: {cov_str}. {total_cases} test case(s) detected; {ci_str}."
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
