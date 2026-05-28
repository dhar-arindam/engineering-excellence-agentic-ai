"""Tests for GitHub infrastructure layer.

Covers:
* PRFile / PRDiff model properties
* WebhookPayload parsing and is_actionable
* GitHubClient HTTP interactions (via httpx mock transport)
* PRCommentFormatter output
* PRWebhookProcessor orchestration
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.domain.entities import AgentFinding, AgentIssue, EngineeringReviewAggregate
from app.domain.enums import AgentName, ReviewStatus, RiskLevel, Severity
from app.infrastructure.github.client import GitHubAPIError, GitHubClient
from app.infrastructure.github.models import (
    PRDiff,
    PRFile,
    PRFileStatus,
    WebhookPayload,
    WebhookPRAction,
)
from app.infrastructure.github.pr_comment_formatter import PRCommentFormatter
from app.infrastructure.github.webhook_processor import PRWebhookProcessor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_aggregate(
    score: int = 75,
    risk: RiskLevel = RiskLevel.MEDIUM,
    issues: list[AgentIssue] | None = None,
) -> EngineeringReviewAggregate:
    return EngineeringReviewAggregate(
        review_id=uuid.uuid4(),
        overall_score=score,
        risk_level=risk,
        agent_results=[
            AgentFinding(
                agent_name=AgentName.SENIOR_DEVELOPER,
                score=score,
                summary="test summary",
                issues=issues or [],
                recommendations=[],
            )
        ],
    )


def _make_pr_diff(files: list[PRFile] | None = None) -> PRDiff:
    return PRDiff(
        owner="acme",
        repo="backend",
        pr_number=42,
        title="feat: add caching",
        base_sha="abc123",
        head_sha="def456",
        head_ref="feature/caching",
        author_login="alice",
        files=files or [],
        repo_clone_url="https://github.com/acme/backend.git",
    )


def _make_webhook_payload(action: str = "opened") -> dict:
    return {
        "action": action,
        "pull_request": {
            "number": 42,
            "title": "feat: add caching",
            "body": "description",
            "base": {
                "sha": "abc123",
                "ref": "main",
                "repo": {"clone_url": "https://github.com/acme/backend.git"},
            },
            "head": {"sha": "def456", "ref": "feature/caching"},
            "user": {"login": "alice"},
        },
        "repository": {
            "name": "backend",
            "full_name": "acme/backend",
            "owner": {"login": "acme"},
            "clone_url": "https://github.com/acme/backend.git",
            "html_url": "https://github.com/acme/backend",
        },
    }


# ---------------------------------------------------------------------------
# PRFile model
# ---------------------------------------------------------------------------


class TestPRFile:
    def test_is_deleted_true(self):
        f = PRFile(filename="old.py", status=PRFileStatus.REMOVED,
                   additions=0, deletions=10, changes=10)
        assert f.is_deleted is True

    def test_is_deleted_false(self):
        f = PRFile(filename="new.py", status=PRFileStatus.ADDED,
                   additions=50, deletions=0, changes=50)
        assert f.is_deleted is False

    def test_extension_python(self):
        f = PRFile(filename="app/core.py", status=PRFileStatus.MODIFIED,
                   additions=5, deletions=2, changes=7)
        assert f.extension == ".py"

    def test_extension_no_dot(self):
        f = PRFile(filename="Makefile", status=PRFileStatus.MODIFIED,
                   additions=1, deletions=0, changes=1)
        assert f.extension == ""

    def test_frozen(self):
        f = PRFile(filename="a.py", status=PRFileStatus.ADDED,
                   additions=1, deletions=0, changes=1)
        with pytest.raises(Exception):
            f.filename = "b.py"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PRDiff model
# ---------------------------------------------------------------------------


class TestPRDiff:
    def test_changed_filenames_sorted(self):
        diff = _make_pr_diff([
            PRFile(filename="b.py", status=PRFileStatus.MODIFIED, additions=1, deletions=0, changes=1),
            PRFile(filename="a.py", status=PRFileStatus.ADDED, additions=5, deletions=0, changes=5),
        ])
        assert diff.changed_filenames == ["a.py", "b.py"]

    def test_non_deleted_filenames_excludes_removed(self):
        diff = _make_pr_diff([
            PRFile(filename="keep.py", status=PRFileStatus.MODIFIED, additions=1, deletions=0, changes=1),
            PRFile(filename="gone.py", status=PRFileStatus.REMOVED, additions=0, deletions=5, changes=5),
        ])
        assert diff.non_deleted_filenames == ["keep.py"]

    def test_empty_diff(self):
        diff = _make_pr_diff([])
        assert diff.changed_filenames == []
        assert diff.non_deleted_filenames == []


# ---------------------------------------------------------------------------
# WebhookPayload
# ---------------------------------------------------------------------------


class TestWebhookPayload:
    def test_parse_opened(self):
        p = WebhookPayload.model_validate(_make_webhook_payload("opened"))
        assert p.action == "opened"
        assert p.pull_request.number == 42
        assert p.repository.owner_login == "acme"
        assert p.is_actionable is True

    def test_parse_synchronize(self):
        p = WebhookPayload.model_validate(_make_webhook_payload("synchronize"))
        assert p.is_actionable is True

    def test_parse_reopened(self):
        p = WebhookPayload.model_validate(_make_webhook_payload("reopened"))
        assert p.is_actionable is True

    def test_closed_not_actionable(self):
        p = WebhookPayload.model_validate(_make_webhook_payload("closed"))
        assert p.is_actionable is False

    def test_edited_not_actionable(self):
        p = WebhookPayload.model_validate(_make_webhook_payload("edited"))
        assert p.is_actionable is False

    def test_extra_fields_ignored(self):
        raw = _make_webhook_payload()
        raw["sender"] = {"login": "bot"}  # extra field
        p = WebhookPayload.model_validate(raw)
        assert p.pull_request.number == 42

    def test_repository_full_name(self):
        p = WebhookPayload.model_validate(_make_webhook_payload())
        assert p.repository.full_name == "acme/backend"


# ---------------------------------------------------------------------------
# GitHubClient — HMAC and HTTP (mock transport)
# ---------------------------------------------------------------------------


def _mock_transport(responses: dict[str, Any]) -> httpx.MockTransport:
    """Build an httpx mock transport from a {path: response_data} dict."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path not in responses:
            return httpx.Response(404, json={"message": "Not Found"})
        data = responses[path]
        if isinstance(data, httpx.Response):
            return data
        return httpx.Response(200, json=data)

    return httpx.MockTransport(handler)


class TestGitHubClient:
    def _client(self, responses: dict) -> GitHubClient:
        transport = _mock_transport(responses)
        client = GitHubClient(token="test-token")
        client._client = httpx.AsyncClient(
            base_url="https://api.github.com",
            transport=transport,
        )
        return client

    @pytest.mark.asyncio
    async def test_get_pr_diff_success(self):
        pr_resp = {
            "title": "feat: add caching",
            "base": {"sha": "abc", "repo": {"clone_url": "https://github.com/a/b.git"}},
            "head": {"sha": "def", "ref": "feature/x"},
            "user": {"login": "alice"},
        }
        files_resp = [
            {"filename": "app/main.py", "status": "modified",
             "additions": 5, "deletions": 2, "changes": 7, "patch": "@@ ..."},
        ]
        client = self._client({
            "/repos/acme/backend/pulls/1": pr_resp,
            "/repos/acme/backend/pulls/1/files": files_resp,
        })
        diff = await client.get_pr_diff("acme", "backend", 1)
        assert diff.pr_number == 1
        assert diff.head_sha == "def"
        assert len(diff.files) == 1
        assert diff.files[0].filename == "app/main.py"
        await client.close()

    @pytest.mark.asyncio
    async def test_get_pr_diff_api_error(self):
        client = self._client({})   # all paths → 404
        with pytest.raises(GitHubAPIError) as exc_info:
            await client.get_pr_diff("acme", "backend", 999)
        assert exc_info.value.status_code == 404
        await client.close()

    @pytest.mark.asyncio
    async def test_post_comment_success(self):
        comment_resp = {"id": 123, "html_url": "https://github.com/..."}
        client = self._client({
            "/repos/acme/backend/issues/42/comments": comment_resp,
        })
        result = await client.post_comment("acme", "backend", 42, "hello")
        assert result["id"] == 123
        await client.close()

    @pytest.mark.asyncio
    async def test_post_comment_api_error(self):
        client = self._client({
            "/repos/acme/backend/issues/42/comments": httpx.Response(
                403, json={"message": "Forbidden"}
            ),
        })
        with pytest.raises(GitHubAPIError) as exc_info:
            await client.post_comment("acme", "backend", 42, "hello")
        assert exc_info.value.status_code == 403
        await client.close()

    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with GitHubClient(token="tok") as client:
            assert client is not None


# ---------------------------------------------------------------------------
# PRCommentFormatter
# ---------------------------------------------------------------------------


class TestPRCommentFormatter:
    fmt = PRCommentFormatter()

    def test_header_contains_score(self):
        agg = _make_aggregate(score=82)
        body = self.fmt.generate_markdown_summary(agg, _make_pr_diff())
        assert "82/100" in body

    def test_header_emoji_excellent(self):
        body = self.fmt.generate_markdown_summary(_make_aggregate(85), _make_pr_diff())
        assert "🟢" in body

    def test_header_emoji_good(self):
        body = self.fmt.generate_markdown_summary(_make_aggregate(72), _make_pr_diff())
        assert "🟡" in body

    def test_header_emoji_warning(self):
        body = self.fmt.generate_markdown_summary(_make_aggregate(55), _make_pr_diff())
        assert "🟠" in body

    def test_header_emoji_critical(self):
        body = self.fmt.generate_markdown_summary(_make_aggregate(30), _make_pr_diff())
        assert "🔴" in body

    def test_agent_score_table_present(self):
        body = self.fmt.generate_markdown_summary(_make_aggregate(80), _make_pr_diff())
        assert "Agent Scores" in body
        assert "SeniorDeveloperAgent" in body

    def test_changed_files_section(self):
        diff = _make_pr_diff([
            PRFile(filename="app/main.py", status=PRFileStatus.MODIFIED,
                   additions=5, deletions=0, changes=5),
        ])
        body = self.fmt.generate_markdown_summary(_make_aggregate(), diff)
        assert "app/main.py" in body

    def test_no_files_section_when_empty(self):
        body = self.fmt.generate_markdown_summary(_make_aggregate(), _make_pr_diff([]))
        assert "Changed files" not in body

    def test_critical_issues_shown(self):
        issue = AgentIssue(
            severity=Severity.CRITICAL,
            title="SQL Injection",
            description="Raw SQL used.",
            recommendation="Use ORM.",
            file_path="app/db.py",
            line_number=42,
        )
        agg = _make_aggregate(issues=[issue])
        body = self.fmt.generate_markdown_summary(agg, _make_pr_diff())
        assert "SQL Injection" in body
        assert "app/db.py" in body
        assert "42" in body

    def test_low_severity_issues_not_shown(self):
        issue = AgentIssue(
            severity=Severity.LOW,
            title="Minor Style",
            description="Nit.",
            recommendation="Fix it.",
        )
        agg = _make_aggregate(issues=[issue])
        body = self.fmt.generate_markdown_summary(agg, _make_pr_diff())
        assert "Critical Issues" not in body

    def test_footer_contains_review_id(self):
        agg = _make_aggregate()
        body = self.fmt.generate_markdown_summary(agg, _make_pr_diff())
        assert str(agg.review_id) in body


# ---------------------------------------------------------------------------
# PRWebhookProcessor
# ---------------------------------------------------------------------------


class TestPRWebhookProcessor:
    def _build_processor(
        self,
        diff: PRDiff | None = None,
        aggregate: EngineeringReviewAggregate | None = None,
        post_comment_raises: Exception | None = None,
    ) -> PRWebhookProcessor:
        github_client = MagicMock()
        github_client.get_pr_diff = AsyncMock(return_value=diff or _make_pr_diff())
        if post_comment_raises:
            github_client.post_comment = AsyncMock(side_effect=post_comment_raises)
        else:
            github_client.post_comment = AsyncMock(return_value={"id": 1})

        orchestrator = MagicMock()
        orchestrator.orchestrate = AsyncMock(return_value=aggregate or _make_aggregate())

        return PRWebhookProcessor(
            github_client=github_client,
            orchestrator=orchestrator,
        )

    @pytest.mark.asyncio
    async def test_process_calls_get_pr_diff(self):
        processor = self._build_processor()
        payload = WebhookPayload.model_validate(_make_webhook_payload())
        await processor.process(payload)
        processor._github.get_pr_diff.assert_called_once_with("acme", "backend", 42)

    @pytest.mark.asyncio
    async def test_process_calls_orchestrate(self):
        processor = self._build_processor()
        payload = WebhookPayload.model_validate(_make_webhook_payload())
        await processor.process(payload)
        processor._orchestrator.orchestrate.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_posts_comment(self):
        processor = self._build_processor()
        payload = WebhookPayload.model_validate(_make_webhook_payload())
        await processor.process(payload)
        processor._github.post_comment.assert_called_once()
        _, kwargs = processor._github.post_comment.call_args
        # Check the positional args include owner, repo, pr_number
        call_args = processor._github.post_comment.call_args[0]
        assert "acme" in call_args
        assert "backend" in call_args
        assert 42 in call_args

    @pytest.mark.asyncio
    async def test_comment_post_failure_is_swallowed(self):
        """A GitHub API error on comment posting should NOT propagate."""
        processor = self._build_processor(
            post_comment_raises=GitHubAPIError(403, "Forbidden")
        )
        payload = WebhookPayload.model_validate(_make_webhook_payload())
        # Should not raise
        await processor.process(payload)

    @pytest.mark.asyncio
    async def test_process_synchronize_action(self):
        processor = self._build_processor()
        payload = WebhookPayload.model_validate(_make_webhook_payload("synchronize"))
        await processor.process(payload)
        processor._orchestrator.orchestrate.assert_called_once()
