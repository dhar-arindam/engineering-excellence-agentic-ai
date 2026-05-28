"""Weighted scoring engine — pure function, no I/O, no LLM.

This is the canonical module.  ``scoring_engine`` re-exports from here for
backward compatibility.

Weights
-------
QA            25 %
Developer     25 %
Architecture  20 %
SRE           15 %
Security      15 %

Risk mapping
------------
85–100  → Low
70–84   → Medium
50–69   → High
< 50    → Critical
"""
from __future__ import annotations

from app.domain.entities import AgentFinding
from app.domain.enums import AgentName, RiskLevel

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AGENT_WEIGHTS: dict[AgentName, float] = {
    AgentName.SENIOR_QA:        0.25,
    AgentName.SENIOR_DEVELOPER: 0.25,
    AgentName.SENIOR_ARCHITECT: 0.20,
    AgentName.SENIOR_SRE:       0.15,
    AgentName.SECURITY_EXPERT:  0.15,
}

_RISK_THRESHOLDS: list[tuple[int, RiskLevel]] = [
    (85, RiskLevel.LOW),
    (70, RiskLevel.MEDIUM),
    (50, RiskLevel.HIGH),
    (0,  RiskLevel.CRITICAL),
]


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------

def compute_risk_level(score: int) -> RiskLevel:
    """Map a 0–100 integer score to a :class:`RiskLevel`.

    >>> compute_risk_level(100)
    <RiskLevel.LOW: 'Low'>
    >>> compute_risk_level(84)
    <RiskLevel.MEDIUM: 'Medium'>
    >>> compute_risk_level(69)
    <RiskLevel.HIGH: 'High'>
    >>> compute_risk_level(49)
    <RiskLevel.CRITICAL: 'Critical'>
    """
    for threshold, level in _RISK_THRESHOLDS:
        if score >= threshold:
            return level
    return RiskLevel.CRITICAL  # unreachable but satisfies type checker


def compute_weighted_score(findings: list[AgentFinding]) -> int:
    """Compute weighted score combining agent domain weights with confidence².

    effective_weight = AGENT_WEIGHTS[agent] * confidence²
    This preserves domain importance while discounting low-confidence agents.
    Falls back to equal confidence (0.5) for missing weights.
    """
    total = total_w = 0.0
    for f in findings:
        domain_weight = AGENT_WEIGHTS.get(f.agent_name, 1.0 / len(AGENT_WEIGHTS))
        eff_weight = domain_weight * (f.confidence ** 2)
        total += f.score * eff_weight
        total_w += eff_weight
    if total_w == 0.0:
        return 0
    return max(0, min(100, round(total / total_w)))


# ---------------------------------------------------------------------------
# Radar computation (6 dimensions → per-dimension score + confidence)
# ---------------------------------------------------------------------------

_RADAR_DIMENSIONS: dict[str, list[AgentName]] = {
    "readability":     [AgentName.SENIOR_DEVELOPER],
    "complexity":      [AgentName.SENIOR_ARCHITECT],
    "reliability":     [AgentName.SENIOR_QA, AgentName.SENIOR_SRE],
    "security":        [AgentName.SECURITY_EXPERT],
    "maintainability": [AgentName.SENIOR_ARCHITECT],
    "stability":       [AgentName.SENIOR_SRE],
}


def _confidence_weighted_dim(agents: list[AgentFinding]) -> dict[str, float]:
    """Return score (0–10) and confidence for a radar dimension.

    Score = Σ(score_i × conf_i²) / Σ(conf_i²), normalised to 0–10.
    Confidence = weighted-average confidence (weights = AGENT_WEIGHTS).
    """
    if not agents:
        return {"score": 0.0, "confidence": 0.0}
    total = total_w = 0.0
    total_conf = total_cw = 0.0
    for f in agents:
        eff = f.confidence ** 2
        total += f.score * eff
        total_w += eff
        cw = AGENT_WEIGHTS.get(f.agent_name, 0.2)
        total_conf += f.confidence * cw
        total_cw += cw
    score = round((total / total_w) / 10, 2) if total_w > 0 else 0.0
    conf = round(total_conf / total_cw, 3) if total_cw > 0 else 0.0
    return {"score": max(0.0, min(10.0, score)), "confidence": max(0.0, min(1.0, conf))}


def compute_radar(findings: list[AgentFinding]) -> dict[str, dict[str, float]]:
    """Compute 6-dimension radar chart data from agent findings.

    Returns dict mapping dimension name → {"score": float 0–10, "confidence": float 0–1}.
    """
    by_name: dict[AgentName, AgentFinding] = {f.agent_name: f for f in findings}
    result: dict[str, dict[str, float]] = {}
    for dimension, agent_names in _RADAR_DIMENSIONS.items():
        dim_findings = [by_name[n] for n in agent_names if n in by_name]
        result[dimension] = _confidence_weighted_dim(dim_findings)
    return result


def compute_overall_confidence(findings: list[AgentFinding]) -> float:
    """Compute overall confidence as AGENT_WEIGHTS-weighted average of agent confidences."""
    if not findings:
        return 0.0
    total = total_w = 0.0
    for f in findings:
        w = AGENT_WEIGHTS.get(f.agent_name, 0.2)
        total += f.confidence * w
        total_w += w
    return round(total / total_w, 3) if total_w > 0 else 0.0


# ---------------------------------------------------------------------------
# Stateless class wrapper (inject where DI is required)
# ---------------------------------------------------------------------------

class ScoringEngine:
    """Stateless wrapper around the pure scoring functions.

    Prefer injecting this class over calling the module-level functions
    directly so callers can be swapped with a test double.
    """

    def compute(
        self,
        findings: list[AgentFinding],
    ) -> tuple[int, RiskLevel]:
        """Return ``(overall_score, risk_level)`` for *findings*."""
        score = compute_weighted_score(findings)
        risk  = compute_risk_level(score)
        return score, risk

    def compute_radar(self, findings: list[AgentFinding]) -> dict[str, dict[str, float]]:
        return compute_radar(findings)

    def compute_overall_confidence(self, findings: list[AgentFinding]) -> float:
        return compute_overall_confidence(findings)
