"""Async GitHub REST API client.

Responsibilities
----------------
* ``get_pr_diff``   — fetch PR metadata + per-file diff from GitHub API
* ``post_comment``  — post a markdown comment on a PR (via Issues API)

Design notes
------------
* Uses ``httpx.AsyncClient`` — fully async, no blocking I/O.
* Token is injected at construction time; the client never reads settings
  directly (keeping infrastructure code testable and environment-agnostic).
* A single ``AsyncClient`` is reused across calls; callers are responsible
  for lifecycle management (or use the async context manager).
* All GitHub API errors are raised as ``GitHubAPIError`` so callers have a
  single exception type to handle without importing httpx.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.infrastructure.github.models import (
    PRDiff,
    PRFile,
    PRFileStatus,
    WebhookPayload,
)

logger = logging.getLogger(__name__)

_GITHUB_API_BASE = "https://api.github.com"
_ACCEPT_HEADER = "application/vnd.github+json"
_API_VERSION_HEADER = "2022-11-28"
_DEFAULT_TIMEOUT = 20.0  # seconds


class GitHubAPIError(Exception):
    """Raised when the GitHub API returns an error response."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"GitHub API {status_code}: {message}")
        self.status_code = status_code
        self.message = message


class GitHubClient:
    """Async client for the GitHub REST API.

    Parameters
    ----------
    token:
        GitHub personal-access token or GitHub App installation token.
        May be empty for unauthenticated requests (lower rate limits).
    base_url:
        Override for testing against GitHub Enterprise or mocks.
    timeout:
        Per-request timeout in seconds.
    """

    def __init__(
        self,
        token: str = "",
        base_url: str = _GITHUB_API_BASE,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        headers: dict[str, str] = {
            "Accept": _ACCEPT_HEADER,
            "X-GitHub-Api-Version": _API_VERSION_HEADER,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "GitHubClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_pr_diff(
        self,
        owner: str,
        repo: str,
        pr_number: int,
    ) -> PRDiff:
        """Fetch PR metadata and the list of changed files.

        Combines two GitHub API calls:
        1. ``GET /repos/{owner}/{repo}/pulls/{pr_number}`` — PR metadata
        2. ``GET /repos/{owner}/{repo}/pulls/{pr_number}/files`` — file list

        Parameters
        ----------
        owner:   Repository owner (user or org).
        repo:    Repository name.
        pr_number: Pull request number.

        Returns
        -------
        PRDiff
            Immutable snapshot of PR metadata + file-level diff information.

        Raises
        ------
        GitHubAPIError
            When the API returns a non-2xx status.
        """
        pr_data = await self._get(f"/repos/{owner}/{repo}/pulls/{pr_number}")
        files_data = await self._get_paginated(
            f"/repos/{owner}/{repo}/pulls/{pr_number}/files"
        )

        files = [self._parse_pr_file(f) for f in files_data]

        logger.info(
            "github.pr_diff_fetched",
            extra={
                "owner": owner,
                "repo": repo,
                "pr_number": pr_number,
                "file_count": len(files),
            },
        )

        return PRDiff(
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            title=pr_data.get("title", ""),
            base_sha=pr_data["base"]["sha"],
            head_sha=pr_data["head"]["sha"],
            head_ref=pr_data["head"]["ref"],
            author_login=pr_data["user"]["login"],
            files=files,
            repo_clone_url=pr_data["base"]["repo"]["clone_url"],
        )

    async def list_pull_requests(
        self,
        owner: str,
        repo: str,
        state: str = "open",
    ) -> list[dict[str, Any]]:
        """List pull requests for a repository.

        Parameters
        ----------
        owner:  Repository owner.
        repo:   Repository name.
        state:  PR state filter — ``"open"`` (default), ``"closed"``, or ``"all"``.

        Returns
        -------
        list[dict]
            Raw GitHub API pull request objects.

        Raises
        ------
        GitHubAPIError
            When the API returns a non-2xx status.
        """
        return await self._get_paginated(
            f"/repos/{owner}/{repo}/pulls",
            extra_params={"state": state, "sort": "updated", "direction": "desc"},
        )

    async def post_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
    ) -> dict[str, Any]:
        """Post a markdown comment on a pull request.

        Uses the Issues Comments API (PRs are Issues in GitHub's model).

        Parameters
        ----------
        owner:     Repository owner.
        repo:      Repository name.
        pr_number: Pull request number.
        body:      Markdown comment body.

        Returns
        -------
        dict
            Raw GitHub API response (includes ``id``, ``html_url``, etc.).

        Raises
        ------
        GitHubAPIError
            When the API returns a non-2xx status.
        """
        response = await self._post(
            f"/repos/{owner}/{repo}/issues/{pr_number}/comments",
            json={"body": body},
        )
        logger.info(
            "github.comment_posted",
            extra={
                "owner": owner,
                "repo": repo,
                "pr_number": pr_number,
                "comment_id": response.get("id"),
            },
        )
        return response

    # ------------------------------------------------------------------
    # Private HTTP helpers
    # ------------------------------------------------------------------

    async def _get(self, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await self._client.get(path, **kwargs)
        self._raise_for_status(response)
        result: dict[str, Any] = response.json()
        return result

    async def _get_paginated(
        self,
        path: str,
        per_page: int = 100,
        extra_params: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Fetch all pages for a list endpoint (Link header pagination)."""
        params: dict[str, Any] = {"per_page": per_page, "page": 1, **(extra_params or {})}
        items: list[dict[str, Any]] = []
        while True:
            response = await self._client.get(path, params=params)
            self._raise_for_status(response)
            page: list[dict[str, Any]] = response.json()
            items.extend(page)
            if len(page) < per_page:
                break
            params["page"] += 1
        return items

    async def _post(
        self, path: str, json: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        response = await self._client.post(path, json=json)
        self._raise_for_status(response)
        result: dict[str, Any] = response.json()
        return result

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.is_error:
            try:
                message = response.json().get("message", response.text)
            except Exception:
                message = response.text
            raise GitHubAPIError(response.status_code, message)

    @staticmethod
    def _parse_pr_file(raw: dict[str, Any]) -> PRFile:
        try:
            status = PRFileStatus(raw.get("status", "changed"))
        except ValueError:
            status = PRFileStatus.CHANGED
        return PRFile(
            filename=raw["filename"],
            status=status,
            additions=raw.get("additions", 0),
            deletions=raw.get("deletions", 0),
            changes=raw.get("changes", 0),
            patch=raw.get("patch"),
        )
