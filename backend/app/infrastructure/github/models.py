"""Data models for the GitHub PR automation layer.

All models are immutable Pydantic v2 value objects.  They represent the
wire-level GitHub API responses mapped to domain-friendly shapes.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# PR file / diff models
# ---------------------------------------------------------------------------


class PRFileStatus(str, Enum):
    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"
    RENAMED = "renamed"
    COPIED = "copied"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


class PRFile(BaseModel):
    """A single file changed in a pull request."""

    filename: str
    status: PRFileStatus
    additions: int = Field(ge=0)
    deletions: int = Field(ge=0)
    changes: int = Field(ge=0)
    patch: Optional[str] = None

    model_config = {"frozen": True}

    @property
    def is_deleted(self) -> bool:
        return self.status == PRFileStatus.REMOVED

    @property
    def extension(self) -> str:
        parts = self.filename.rsplit(".", 1)
        return f".{parts[1]}" if len(parts) == 2 else ""


class PRDiff(BaseModel):
    """Aggregated diff information for a pull request."""

    owner: str
    repo: str
    pr_number: int = Field(ge=1)
    title: str
    base_sha: str
    head_sha: str
    head_ref: str
    author_login: str
    files: list[PRFile] = Field(default_factory=list)
    repo_clone_url: str

    model_config = {"frozen": True}

    @property
    def changed_filenames(self) -> list[str]:
        return sorted(f.filename for f in self.files)

    @property
    def non_deleted_filenames(self) -> list[str]:
        return sorted(f.filename for f in self.files if not f.is_deleted)


# ---------------------------------------------------------------------------
# Webhook payload models — mirror the GitHub API wire format
# ---------------------------------------------------------------------------


class WebhookPRAction(str, Enum):
    OPENED = "opened"
    SYNCHRONIZE = "synchronize"
    REOPENED = "reopened"
    CLOSED = "closed"
    EDITED = "edited"


# Internal nested shapes (order matters for Pydantic with from __future__ annotations)

class _PRBaseRepo(BaseModel):
    """Nested repo object inside the ``base`` ref."""
    clone_url: str
    model_config = {"frozen": True, "extra": "ignore"}


class _GitRef(BaseModel):
    """Nested git ref (head/base)."""
    sha: str
    ref: str = ""
    model_config = {"frozen": True, "extra": "ignore"}


class _GitBaseRef(_GitRef):
    """base ref carries an extra ``repo`` child object."""
    repo: _PRBaseRepo
    model_config = {"frozen": True, "extra": "ignore"}


class _User(BaseModel):
    login: str
    model_config = {"frozen": True, "extra": "ignore"}


class _OwnerObj(BaseModel):
    login: str
    model_config = {"frozen": True, "extra": "ignore"}


class WebhookPullRequest(BaseModel):
    """Minimal pull request data extracted from a GitHub webhook payload."""

    number: int
    title: str
    body: Optional[str] = None
    base: _GitBaseRef
    head: _GitRef
    user: _User

    model_config = {"frozen": True, "extra": "ignore"}

    @property
    def base_sha(self) -> str:
        return self.base.sha

    @property
    def head_sha(self) -> str:
        return self.head.sha

    @property
    def head_ref(self) -> str:
        return self.head.ref

    @property
    def author_login(self) -> str:
        return self.user.login


class WebhookRepository(BaseModel):
    """Minimal repository data extracted from a GitHub webhook payload."""

    name: str
    full_name: str
    owner: _OwnerObj
    clone_url: str
    html_url: str

    model_config = {"frozen": True, "extra": "ignore"}

    @property
    def owner_login(self) -> str:
        """String owner login — use this instead of ``owner`` directly."""
        return self.owner.login


class WebhookPayload(BaseModel):
    """Parsed GitHub ``pull_request`` event payload."""

    action: str
    pull_request: WebhookPullRequest
    repository: WebhookRepository

    model_config = {"frozen": True, "extra": "ignore"}

    @property
    def is_actionable(self) -> bool:
        """Return True for events that should trigger a scan."""
        return self.action in {
            WebhookPRAction.OPENED,
            WebhookPRAction.SYNCHRONIZE,
            WebhookPRAction.REOPENED,
        }
