"""Unit tests for the ScoringEngine."""
from __future__ import annotations

import pytest

from app.application.scoring_engine import ScoringEngine, compute_risk_level, compute_weighted_score
from app.domain.entities import AgentFinding
from app.domain.enums import AgentName, RiskLevel


def _finding(agent: AgentName, score: int) -> AgentFinding:
    return AgentFinding(agent_name=agent, score=score, summary="test")


class TestComputeRiskLevel:
    def test_low(self):
        assert compute_risk_level(100) == RiskLevel.LOW
        assert compute_risk_level(85) == RiskLevel.LOW

    def test_medium(self):
        assert compute_risk_level(84) == RiskLevel.MEDIUM
        assert compute_risk_level(70) == RiskLevel.MEDIUM

    def test_high(self):
        assert compute_risk_level(69) == RiskLevel.HIGH
        assert compute_risk_level(50) == RiskLevel.HIGH

    def test_critical(self):
        assert compute_risk_level(49) == RiskLevel.CRITICAL
        assert compute_risk_level(0) == RiskLevel.CRITICAL


class TestComputeWeightedScore:
    def test_all_agents_equal_score(self):
        findings = [
            _finding(AgentName.SENIOR_QA, 80),
            _finding(AgentName.SENIOR_DEVELOPER, 80),
            _finding(AgentName.SENIOR_ARCHITECT, 80),
            _finding(AgentName.SENIOR_SRE, 80),
            _finding(AgentName.SECURITY_EXPERT, 80),
        ]
        assert compute_weighted_score(findings) == 80

    def test_weights_applied_correctly(self):
        # QA=100 (25%) + Dev=0 (25%) + rest=0 → 25
        findings = [
            _finding(AgentName.SENIOR_QA, 100),
            _finding(AgentName.SENIOR_DEVELOPER, 0),
            _finding(AgentName.SENIOR_ARCHITECT, 0),
            _finding(AgentName.SENIOR_SRE, 0),
            _finding(AgentName.SECURITY_EXPERT, 0),
        ]
        assert compute_weighted_score(findings) == 25

    def test_partial_agents_normalised(self):
        # Only QA (25%) and Dev (25%) present — total weight 0.5 → normalised to 50%
        findings = [
            _finding(AgentName.SENIOR_QA, 100),
            _finding(AgentName.SENIOR_DEVELOPER, 0),
        ]
        score = compute_weighted_score(findings)
        assert score == 50

    def test_empty_returns_zero(self):
        assert compute_weighted_score([]) == 0


class TestScoringEngine:
    def test_compute_returns_tuple(self):
        engine = ScoringEngine()
        findings = [_finding(AgentName.SENIOR_QA, 90)] * 5  # same agent but tests interface
        score, risk = engine.compute(
            [
                _finding(AgentName.SENIOR_QA, 90),
                _finding(AgentName.SENIOR_DEVELOPER, 90),
                _finding(AgentName.SENIOR_ARCHITECT, 90),
                _finding(AgentName.SENIOR_SRE, 90),
                _finding(AgentName.SECURITY_EXPERT, 90),
            ]
        )
        assert score == 90
        assert risk == RiskLevel.LOW
