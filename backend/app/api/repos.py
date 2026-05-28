"""Repository utility endpoints (not the CRUD — that lives in repositories.py).

Endpoints
---------
GET /api/repos/branches  — list available branches for a GitHub repository URL.
GET /api/repos/pulls     — list pull requests for a GitHub repository URL.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query, status

from app.api.schemas import BranchesResponse, PullRequestItem, PullRequestsResponse
from app.core.config import settings
from app.core.logging import get_logger
from app.infrastructure.github.client import GitHubAPIError, GitHubClient

logger = get_logger(__name__)

router = APIRouter(prefix="/api/repos", tags=["Repositories"])

_GITHUB_URL_RE = re.compile(
    r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)


@router.get(
    "/branches",
    response_model=BranchesResponse,
    summary="List branches for a GitHub repository",
    description=(
        "Fetches the list of available branches and the default branch for the "
        "given GitHub repository URL.  Requires ``GITHUB_TOKEN`` for private repos."
    ),
    operation_id="get_repo_branches",
    responses={
        200: {"description": "Branch list returned."},
        400: {"description": "Invalid or non-GitHub URL."},
        502: {"description": "GitHub API error."},
    },
)
async def get_repo_branches(
    repository_url: str = Query(
        ...,
        description="Full GitHub repository URL, e.g. https://github.com/owner/repo",
        examples=["https://github.com/fastapi/fastapi"],
    ),
) -> BranchesResponse:
    match = _GITHUB_URL_RE.match(repository_url.strip())
    if not match:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="repository_url must be a valid GitHub URL "
                   "(https://github.com/owner/repo).",
        )

    owner = match.group("owner")
    repo = match.group("repo")

    token: str = getattr(settings, "github_token", "") or ""

    async with GitHubClient(token=token) as client:
        try:
            repo_data = await client._get(f"/repos/{owner}/{repo}")
            branches_data = await client._get_paginated(
                f"/repos/{owner}/{repo}/branches"
            )
        except GitHubAPIError as exc:
            logger.warning(
                "api.get_repo_branches.github_error",
                owner=owner,
                repo=repo,
                status_code=exc.status_code,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"GitHub API error: {exc.message}",
            ) from exc

    default_branch: str = repo_data.get("default_branch", "main")
    branch_names: list[str] = [b["name"] for b in branches_data]

    # Ensure the default branch is first in the list.
    if default_branch in branch_names:
        branch_names.remove(default_branch)
    branch_names.insert(0, default_branch)

    return BranchesResponse(branches=branch_names, default_branch=default_branch)


@router.get(
    "/pulls",
    response_model=PullRequestsResponse,
    summary="List pull requests for a GitHub repository",
    description=(
        "Fetches open (or all) pull requests for the given GitHub repository URL. "
        "Requires ``GITHUB_TOKEN`` for private repos."
    ),
    operation_id="get_repo_pulls",
    responses={
        200: {"description": "Pull request list returned."},
        400: {"description": "Invalid or non-GitHub URL."},
        502: {"description": "GitHub API error."},
    },
)
async def get_repo_pulls(
    repository_url: str = Query(
        ...,
        description="Full GitHub repository URL, e.g. https://github.com/owner/repo",
    ),
    state: str = Query(
        default="open",
        description="PR state filter: 'open' (default), 'closed', or 'all'.",
    ),
) -> PullRequestsResponse:
    match = _GITHUB_URL_RE.match(repository_url.strip())
    if not match:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="repository_url must be a valid GitHub URL "
                   "(https://github.com/owner/repo).",
        )

    if state not in ("open", "closed", "all"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="state must be 'open', 'closed', or 'all'.",
        )

    owner = match.group("owner")
    repo = match.group("repo")
    token: str = getattr(settings, "github_token", "") or ""

    async with GitHubClient(token=token) as client:
        try:
            prs_data = await client.list_pull_requests(owner, repo, state=state)
        except GitHubAPIError as exc:
            logger.warning(
                "api.get_repo_pulls.github_error",
                owner=owner,
                repo=repo,
                status_code=exc.status_code,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"GitHub API error: {exc.message}",
            ) from exc

    pull_requests = [
        PullRequestItem(
            number=pr["number"],
            title=pr["title"],
            state=pr["state"],
            draft=pr.get("draft", False),
            head_ref=pr["head"]["ref"],
            base_ref=pr["base"]["ref"],
            author=pr["user"]["login"],
            url=pr["html_url"],
            created_at=pr["created_at"],
            updated_at=pr["updated_at"],
        )
        for pr in prs_data
    ]

    return PullRequestsResponse(pull_requests=pull_requests, total=len(pull_requests))
