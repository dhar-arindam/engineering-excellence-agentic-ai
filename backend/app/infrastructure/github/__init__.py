"""GitHub infrastructure package.

Public surface
--------------
* :class:`GitHubClient`         — async REST API client
* :class:`GitHubAPIError`       — error raised on non-2xx responses
* :class:`PRCommentFormatter`   — generates Markdown PR review comments
* :class:`PRWebhookProcessor`   — end-to-end PR webhook pipeline
* Models: :class:`PRDiff`, :class:`PRFile`, :class:`WebhookPayload`, etc.
"""
from app.infrastructure.github.client import GitHubAPIError, GitHubClient
from app.infrastructure.github.models import (
    PRDiff,
    PRFile,
    PRFileStatus,
    WebhookPayload,
    WebhookPRAction,
    WebhookPullRequest,
    WebhookRepository,
)
from app.infrastructure.github.pr_comment_formatter import PRCommentFormatter
from app.infrastructure.github.webhook_processor import PRWebhookProcessor

__all__ = [
    "GitHubClient",
    "GitHubAPIError",
    "PRCommentFormatter",
    "PRWebhookProcessor",
    "PRDiff",
    "PRFile",
    "PRFileStatus",
    "WebhookPayload",
    "WebhookPRAction",
    "WebhookPullRequest",
    "WebhookRepository",
]
