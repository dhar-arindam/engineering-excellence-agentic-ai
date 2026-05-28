"""SecurityExpertAgent — data-driven security evaluation from security intelligence."""
from __future__ import annotations

import uuid
from typing import Any

from app.application.agents.base import BaseEngineeringAgent
from app.domain.entities import AgentFinding, AgentIssue
from app.domain.enums import AgentName, Severity
from app.domain.value_objects import RepoMetadata


class SecurityExpertAgent(BaseEngineeringAgent):
    """Evaluates security posture, credentials exposure, insecure patterns, and dependency hygiene.

    Scoring is deterministic and derived from SecurityIntelligenceService and
    CiCdIntelligenceService data.  No LLM is used.
    """

    @property
    def agent_name(self) -> AgentName:
        return AgentName.SECURITY_EXPERT

    @property
    def role_definition(self) -> str:
        return (
            "You are a Principal Security Engineer and AppSec expert with 15+ years of experience "
            "in application security, threat modeling, and secure SDLC. You evaluate codebases for "
            "OWASP vulnerabilities, secrets exposure, dependency CVEs, authentication/authorization "
            "patterns, and security posture."
        )

    @property
    def evaluation_rubric(self) -> dict[str, Any]:
        return {
            "secrets_management": {"weight": 0.40, "criteria": "No hardcoded secrets or credentials"},
            "secure_transport":   {"weight": 0.15, "criteria": "HTTPS enforced, no plain HTTP"},
            "dependency_scanner": {"weight": 0.15, "criteria": "Automated dependency vulnerability scanning"},
            "insecure_patterns":  {"weight": 0.20, "criteria": "No eval, weak hashes, shell injection"},
            "security_policy":    {"weight": 0.10, "criteria": "SECURITY.md or equivalent present"},
        }

    async def analyze(
        self,
        repo_metadata: RepoMetadata,
        tool_context: dict[str, Any],
    ) -> AgentFinding:
        sec  = tool_context.get("security_intelligence", {})
        cicd = tool_context.get("cicd_intelligence", {})

        score, issues, recommendations = _score_security(
            repo_name=repo_metadata.name,
            sec_ctx=sec,
            cicd_ctx=cicd,
        )
        confidence, confidence_reason = _sec_confidence(sec, cicd)

        return AgentFinding(
            agent_name=self.agent_name,
            score=score,
            summary=_sec_summary(repo_metadata.name, score, sec),
            issues=issues,
            recommendations=recommendations,
            confidence=confidence,
            confidence_reason=confidence_reason,
        )


# ---------------------------------------------------------------------------
# Scoring logic
# ---------------------------------------------------------------------------

def _score_security(
    repo_name: str,
    sec_ctx: dict[str, Any],
    cicd_ctx: dict[str, Any],
) -> tuple[int, list[AgentIssue], list[str]]:
    score = 0
    issues: list[AgentIssue] = []
    recommendations: list[str] = []

    secret_count  = sec_ctx.get("secret_count", 0)
    insecure_count = sec_ctx.get("insecure_pattern_count", 0)
    secret_locations = sec_ctx.get("secret_locations", [])
    password_instances = sec_ctx.get("hardcoded_password_instances", [])

    # --- No hardcoded secrets (0-40 pts) ---
    if secret_count == 0:
        score += 40
    elif secret_count <= 2:
        score += 20
        issues.append(_issue(Severity.HIGH, None, "Potential secrets detected",
            f"{secret_count} potential secret(s) found: {', '.join(secret_locations[:3])}.",
            "Move all secrets to environment variables or a secrets manager (Vault, AWS Secrets Manager)."))
    elif secret_count <= 5:
        score += 10
        issues.append(_issue(Severity.CRITICAL, None, "Multiple hardcoded secrets",
            f"{secret_count} potential secret(s) detected across the codebase.",
            "Immediately rotate all exposed credentials and move to a secrets management solution."))
    else:
        issues.append(_issue(Severity.CRITICAL, None, "Pervasive credential exposure",
            f"{secret_count} secrets detected — this is a critical security breach risk.",
            "Treat as a security incident: rotate credentials, audit git history, implement secret scanning."))

    if password_instances:
        issues.append(_issue(Severity.CRITICAL, None, "Hardcoded passwords",
            f"{len(password_instances)} hardcoded password instance(s): {', '.join(password_instances[:3])}.",
            "Replace hardcoded passwords with environment variables immediately."))

    # --- HTTPS enforcement (0-15 pts) ---
    if sec_ctx.get("uses_https", True):
        score += 15
    else:
        insecure_patterns = sec_ctx.get("insecure_patterns", [])
        http_hits = [p for p in insecure_patterns if "http_url" in p]
        issues.append(_issue(Severity.HIGH, None, "Plain HTTP URLs detected",
            f"{len(http_hits)} plain HTTP URL(s) found in source code.",
            "Replace all http:// URLs with https:// and enforce TLS at the infrastructure level."))

    # --- Dependency scanner (0-15 pts) ---
    if sec_ctx.get("has_dependency_scanner") or cicd_ctx.get("has_security_scan"):
        score += 15
    else:
        issues.append(_issue(Severity.MEDIUM, None, "No dependency vulnerability scanner",
            "No Dependabot, Snyk, Trivy or equivalent scanner configuration found.",
            "Enable GitHub Dependabot alerts and add a dependency scanning step to CI."))
        recommendations.append(
            "Add `pip-audit` or Snyk to CI to catch known CVEs in dependencies automatically."
        )

    # --- Insecure coding patterns (0-20 pts) ---
    if insecure_count == 0:
        score += 20
    elif insecure_count <= 3:
        score += 12
        insecure_list = sec_ctx.get("insecure_patterns", [])
        recommendations.append(
            f"{insecure_count} insecure pattern(s) detected: "
            f"{', '.join(insecure_list[:3])}. Review and remediate."
        )
    elif insecure_count <= 8:
        score += 5
        issues.append(_issue(Severity.HIGH, None, "Multiple insecure coding patterns",
            f"{insecure_count} insecure patterns found (eval, weak hashes, shell injection, etc.).",
            "Run Bandit or Semgrep and address all HIGH/CRITICAL findings."))
    else:
        issues.append(_issue(Severity.CRITICAL, None, "Pervasive insecure coding patterns",
            f"{insecure_count} insecure pattern instances detected.",
            "Mandate SAST scanning in CI and block merges with critical security findings."))

    # --- Security policy (0-10 pts) ---
    if sec_ctx.get("has_security_policy"):
        score += 10
    else:
        recommendations.append(
            "Add a SECURITY.md file describing vulnerability disclosure policy and contact."
        )

    # --- Bonus: CI has security scan (+bonus already counted in dep scanner above) ---
    # Avoid double-counting — skip.

    return min(100, max(0, score)), issues, recommendations


def _sec_confidence(sec_ctx: dict, cicd_ctx: dict) -> tuple[float, str]:
    signals = {
        "security_scan_present": bool(sec_ctx),
        "secret_count_known": "secret_count" in sec_ctx,
        "insecure_patterns_known": "insecure_pattern_count" in sec_ctx,
        "dep_scanner_known": "has_dependency_scanner" in cicd_ctx or "dependency_scanner" in cicd_ctx,
    }
    available = sum(signals.values())
    confidence = min(1.0, round(0.4 + available * 0.15, 3))
    missing = [k for k, v in signals.items() if not v]
    if missing:
        reason = f"Confidence based on {available}/4 security signals; missing: {', '.join(missing)}"
    else:
        reason = "All 4 security intelligence signals available"
    return confidence, reason


def _sec_summary(
    repo_name: str,
    score: int,
    sec_ctx: dict[str, Any],
) -> str:
    secret_count  = sec_ctx.get("secret_count", 0)
    insecure_count = sec_ctx.get("insecure_pattern_count", 0)
    dep_scanner   = sec_ctx.get("has_dependency_scanner", False)
    scanner_str   = "dependency scanner configured" if dep_scanner else "no dependency scanner"
    secret_str    = f"{secret_count} potential secret(s)" if secret_count else "no secrets detected"
    return (
        f"Repository '{repo_name}' achieved a security score of {score}/100. "
        f"{secret_str.capitalize()}; {insecure_count} insecure pattern(s); {scanner_str}."
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
