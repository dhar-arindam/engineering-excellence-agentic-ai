"""PRWebhookProcessor — orchestrates the PR review-and-comment flow.

This class sits between the webhook route (HTTP concerns) and the domain
layer (agents, scoring).  It owns the end-to-end sequence:

    webhook received
        → fetch PR diff
        → run engineering review (orchestrator)
        → format markdown comment
        → post comment to PR

Design notes
------------
* Injected dependencies only — testable without real GitHub or LLM.
* Errors from the GitHub API (comment post failure) are logged but do NOT
  surface as 500s to the webhook caller — GitHub retries webhooks on failure
  and we don't want retry storms from transient comment errors.
* Scanning errors DO propagate so the outer exception handler can decide.
"""
from __future__ import annotations

import logging

from app.application.orchestrator import EngineeringReviewOrchestrator
from app.domain.value_objects import RepositoryTarget
from app.infrastructure.github.client import GitHubAPIError, GitHubClient
from app.infrastructure.github.models import PRDiff, WebhookPayload
from app.infrastructure.github.pr_comment_formatter import PRCommentFormatter

logger = logging.getLogger(__name__)


class PRWebhookProcessor:
    """Process a ``pull_request`` webhook event end-to-end.

    Parameters
    ----------
    github_client:
        Authenticated :class:`GitHubClient` for API calls.
    orchestrator:
        :class:`EngineeringReviewOrchestrator` to run the engineering review.
    formatter:
        :class:`PRCommentFormatter` to generate the PR comment body.
    """

    def __init__(
        self,
        github_client: GitHubClient,
        orchestrator: EngineeringReviewOrchestrator,
        formatter: PRCommentFormatter | None = None,
    ) -> None:
        self._github = github_client
        self._orchestrator = orchestrator
        self._formatter = formatter or PRCommentFormatter()

    async def process(self, payload: WebhookPayload) -> None:
        """Run the full PR review pipeline for an actionable webhook event.

        Steps
        -----
        1. Fetch the PR diff (file list + metadata).
        2. Build a :class:`RepositoryTarget` from the clone URL.
        3. Run the engineering review via the orchestrator.
        4. Format a Markdown comment.
        5. Post the comment to the PR.

        Parameters
        ----------
        payload:
            Parsed and validated :class:`WebhookPayload`.  Caller must ensure
            ``payload.is_actionable`` is ``True`` before calling this method.
        """
        pr = payload.pull_request
        repo = payload.repository
        owner = repo.owner_login
        repo_name = repo.name

        logger.info(
            "webhook.pr_processing_started",
            extra={
                "owner": owner,
                "repo": repo_name,
                "pr_number": pr.number,
                "action": payload.action,
                "head_sha": pr.head_sha,
            },
        )

        # 1. Fetch diff
        pr_diff: PRDiff = await self._github.get_pr_diff(owner, repo_name, pr.number)

        # 2. Build scan target (repo URL so the orchestrator can clone/analyse)
        target = RepositoryTarget(repo_url=repo.clone_url)

        # 3. Run engineering review
        aggregate = await self._orchestrator.orchestrate(target)

        logger.info(
            "webhook.pr_review_completed",
            extra={
                "owner": owner,
                "repo": repo_name,
                "pr_number": pr.number,
                "overall_score": aggregate.overall_score,
                "risk_level": aggregate.risk_level.value,
            },
        )

        # 4. Format comment
        comment_body = self._formatter.generate_markdown_summary(aggregate, pr_diff)

        # 5. Post comment — errors are non-fatal for the webhook response
        await self._post_comment_safe(owner, repo_name, pr.number, comment_body)

    async def _post_comment_safe(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
    ) -> None:
        """Post the comment, swallowing API errors to avoid retry storms."""
        try:
            await self._github.post_comment(owner, repo, pr_number, body)
            logger.info(
                "webhook.comment_posted",
                extra={"owner": owner, "repo": repo, "pr_number": pr_number},
            )
        except GitHubAPIError as exc:
            logger.error(
                "webhook.comment_post_failed",
                extra={
                    "owner": owner,
                    "repo": repo,
                    "pr_number": pr_number,
                    "status_code": exc.status_code,
                    "error": exc.message,
                },
            )
