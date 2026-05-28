"""Unit tests for domain models (Pydantic validation)."""
from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.domain.entities import AgentFinding, AgentIssue, EngineeringReviewAggregate
from app.domain.enums import AgentName, RiskLevel, ReviewStatus, Severity
from app.domain.value_objects import RepositoryTarget


class TestAgentIssue:
    def test_valid_issue(self):
        issue = AgentIssue(
            severity=Severity.HIGH,
            title="Test issue",
            description="Description",
            recommendation="Fix it",
        )
        assert isinstance(issue.id, uuid.UUID)
        assert issue.severity == Severity.HIGH

    def test_optional_fields_default_none(self):
        issue = AgentIssue(
            severity=Severity.LOW,
            title="x",
            description="y",
            recommendation="z",
        )
        assert issue.file_path is None
        assert issue.line_number is None


class TestAgentFinding:
    def test_score_bounds(self):
        with pytest.raises(ValidationError):
            AgentFinding(agent_name=AgentName.SENIOR_QA, score=101, summary="x")
        with pytest.raises(ValidationError):
            AgentFinding(agent_name=AgentName.SENIOR_QA, score=-1, summary="x")

    def test_valid_finding(self):
        f = AgentFinding(agent_name=AgentName.SENIOR_QA, score=75, summary="Good")
        assert f.issues == []
        assert f.recommendations == []


class TestRepositoryTarget:
    def test_requires_at_least_one(self):
        with pytest.raises(ValidationError):
            RepositoryTarget()

    def test_rejects_both(self):
        with pytest.raises(ValidationError):
            RepositoryTarget(repo_url="https://github.com/a/b", local_path="/tmp")

    def test_valid_with_url(self):
        t = RepositoryTarget(repo_url="https://github.com/owner/repo")
        assert t.repo_url == "https://github.com/owner/repo"
        assert t.local_path is None

    def test_valid_with_path(self):
        t = RepositoryTarget(local_path="/some/path")
        assert t.local_path == "/some/path"
