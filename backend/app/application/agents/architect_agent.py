"""SeniorArchitectAgent — data-driven architecture evaluation from code + architecture intelligence."""
from __future__ import annotations

import uuid
from typing import Any

from app.application.agents.base import BaseEngineeringAgent
from app.domain.entities import AgentFinding, AgentIssue
from app.domain.enums import AgentName, Severity
from app.domain.value_objects import RepoMetadata


class SeniorArchitectAgent(BaseEngineeringAgent):
    """Evaluates architecture patterns, modularity, scalability, and coupling.

    Scoring is deterministic and derived from CodeIntelligenceService and
    ArchitectureAnalysisService data.  No LLM is used.
    """

    @property
    def agent_name(self) -> AgentName:
        return AgentName.SENIOR_ARCHITECT

    @property
    def role_definition(self) -> str:
        return (
            "You are a Principal Software Architect with 20+ years of experience designing "
            "distributed, cloud-native systems. You evaluate architecture patterns, service "
            "boundaries, coupling, cohesion, scalability, and evolutionary design."
        )

    @property
    def evaluation_rubric(self) -> dict[str, Any]:
        return {
            "complexity":         {"weight": 0.30, "criteria": "Low cyclomatic complexity"},
            "large_file_ratio":   {"weight": 0.20, "criteria": "No files over 500 lines"},
            "dependency_health":  {"weight": 0.20, "criteria": "Limited external dependencies"},
            "code_smells":        {"weight": 0.15, "criteria": "No god classes, long functions"},
            "patterns_detected":  {"weight": 0.15, "criteria": "Known architectural patterns found"},
        }

    async def analyze(
        self,
        repo_metadata: RepoMetadata,
        tool_context: dict[str, Any],
    ) -> AgentFinding:
        code = tool_context.get("code_intelligence", {})
        arch = tool_context.get("architecture_intelligence", {})

        score, issues, recommendations = _score_architect(
            repo_name=repo_metadata.name,
            code_ctx=code,
            arch_ctx=arch,
        )
        confidence, confidence_reason = _arch_confidence(code, arch)

        return AgentFinding(
            agent_name=self.agent_name,
            score=score,
            summary=_arch_summary(repo_metadata.name, score, code, arch),
            issues=issues,
            recommendations=recommendations,
            confidence=confidence,
            confidence_reason=confidence_reason,
        )


# ---------------------------------------------------------------------------
# Scoring logic
# ---------------------------------------------------------------------------

def _score_architect(
    repo_name: str,
    code_ctx: dict[str, Any],
    arch_ctx: dict[str, Any],
) -> tuple[int, list[AgentIssue], list[str]]:
    score = 0
    issues: list[AgentIssue] = []
    recommendations: list[str] = []

    total_files = max(code_ctx.get("total_files", 1), 1)

    # --- Complexity (0-30 pts) ---
    avg_complexity = code_ctx.get("avg_complexity") or code_ctx.get("code_metrics", {}).get("avg_complexity")
    if avg_complexity is None:
        score += 15  # neutral when no data
    elif avg_complexity <= 3.0:
        score += 30
    elif avg_complexity <= 5.0:
        score += 24
    elif avg_complexity <= 8.0:
        score += 16
        recommendations.append(
            f"Average cyclomatic complexity is {avg_complexity:.1f}. "
            "Refactor complex functions to reduce decision points."
        )
    elif avg_complexity <= 12.0:
        score += 8
        issues.append(_issue(Severity.HIGH, None, "High cyclomatic complexity",
            f"Average complexity is {avg_complexity:.1f} (threshold 8).",
            "Decompose large functions; apply the single-responsibility principle."))
    else:
        score += 2
        issues.append(_issue(Severity.CRITICAL, None, "Critically high complexity",
            f"Average complexity is {avg_complexity:.1f} — severely impacts maintainability.",
            "Immediate refactoring required; introduce complexity limits in CI."))

    # --- Large file ratio (0-20 pts) ---
    code_metrics = code_ctx.get("code_metrics", {})
    large_files = (
        code_ctx.get("files_over_500_lines") or
        code_metrics.get("files_over_500_lines", [])
    )
    if isinstance(large_files, list):
        ratio = len(large_files) / total_files
        if ratio == 0:
            score += 20
        elif ratio < 0.03:
            score += 16
        elif ratio < 0.08:
            score += 10
            recommendations.append(
                f"{len(large_files)} file(s) exceed 500 lines — consider splitting."
            )
        else:
            score += 4
            issues.append(_issue(Severity.MEDIUM, None, "Many oversized files",
                f"{len(large_files)} files exceed 500 lines ({ratio:.0%} of codebase).",
                "Break large files into focused modules of ≤300 lines."))

    # --- Dependency health (0-20 pts) ---
    dep_graph = code_ctx.get("dependency_graph", {})
    ext_deps = dep_graph.get("external_dependencies", [])
    arch_ext = arch_ctx.get("external_dependencies", [])
    all_ext = list({*ext_deps, *arch_ext})  # deduplicate

    if len(all_ext) <= 5:
        score += 20
    elif len(all_ext) <= 12:
        score += 14
    elif len(all_ext) <= 25:
        score += 8
        recommendations.append(
            f"Repository imports {len(all_ext)} external packages. "
            "Review for opportunities to reduce the dependency footprint."
        )
    else:
        score += 3
        issues.append(_issue(Severity.MEDIUM, None, "High external dependency count",
            f"{len(all_ext)} unique external packages imported.",
            "Audit dependencies; remove unused packages and prefer stdlib alternatives."))

    # --- Code smells (0-15 pts) ---
    smells = code_ctx.get("code_smells", [])
    if isinstance(smells, list):
        god_classes = [s for s in smells if isinstance(s, dict) and s.get("smell_type") == "god_class"]
        long_fns    = [s for s in smells if isinstance(s, dict) and s.get("smell_type") == "long_function"]
        smell_total = len(god_classes) + len(long_fns)

        if smell_total == 0:
            score += 15
        elif smell_total <= 3:
            score += 10
            if god_classes:
                recommendations.append(
                    f"{len(god_classes)} god class(es) detected — apply SRP to decompose them."
                )
        elif smell_total <= 8:
            score += 5
            issues.append(_issue(Severity.MEDIUM, None, "Multiple code smells detected",
                f"{len(god_classes)} god classes and {len(long_fns)} long functions found.",
                "Schedule a refactoring sprint focusing on the highest-complexity modules."))
        else:
            issues.append(_issue(Severity.HIGH, None, "Extensive code smells",
                f"{smell_total} smell instances detected (god classes: {len(god_classes)}, long fns: {len(long_fns)}).",
                "Enforce code smell checks in CI using a static analysis tool."))

    # --- Architectural patterns (0-15 pts) ---
    patterns = arch_ctx.get("detected_patterns", [])
    violations = arch_ctx.get("layer_violations", [])

    if violations:
        issues.append(_issue(Severity.HIGH, None, "Architectural layer violations",
            f"{len(violations)} layer violation(s) detected: {', '.join(violations[:3])}.",
            "Enforce dependency rules with a tool such as import-linter or ArchUnit."))
    elif patterns:
        score += min(15, len(patterns) * 5)
    else:
        score += 8  # neutral — no data
        recommendations.append(
            "Document the intended architecture (e.g., C4 model) to help static analysis detect patterns."
        )

    circular = arch_ctx.get("circular_dependencies", [])
    if circular:
        issues.append(_issue(Severity.HIGH, None, "Circular dependencies detected",
            f"{len(circular)} circular dependency cycle(s) found.",
            "Break circular dependencies by introducing interfaces or inverting control."))

    return min(100, max(0, score)), issues, recommendations


def _arch_confidence(code_ctx: dict, arch_ctx: dict) -> tuple[float, str]:
    signals = {
        "complexity_known": code_ctx.get("avg_complexity") is not None,
        "file_count_known": "total_files" in code_ctx,
        "arch_data_present": bool(arch_ctx),
        "large_files_known": "large_file_count" in code_ctx or "total_files" in code_ctx,
    }
    available = sum(signals.values())
    confidence = min(1.0, round(0.3 + available * 0.175, 3))
    missing = [k for k, v in signals.items() if not v]
    if missing:
        reason = f"Confidence based on {available}/4 signals; missing: {', '.join(missing)}"
    else:
        reason = "All 4 architecture intelligence signals available"
    return confidence, reason


def _arch_summary(
    repo_name: str,
    score: int,
    code_ctx: dict[str, Any],
    arch_ctx: dict[str, Any],
) -> str:
    avg = code_ctx.get("avg_complexity") or code_ctx.get("code_metrics", {}).get("avg_complexity")
    patterns = arch_ctx.get("detected_patterns", [])
    c_str = f"{avg:.1f}" if avg is not None else "unknown"
    p_str = ", ".join(patterns[:3]) if patterns else "none detected"
    return (
        f"Repository '{repo_name}' achieved an architecture score of {score}/100. "
        f"Average cyclomatic complexity: {c_str}. "
        f"Detected patterns: {p_str}."
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
