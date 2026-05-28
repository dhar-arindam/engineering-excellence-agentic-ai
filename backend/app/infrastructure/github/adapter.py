"""GitHub repository adapter — fetches metadata and file tree via GitHub REST API."""
from __future__ import annotations

import base64
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.exceptions import RepositoryAccessError
from app.core.logging import get_logger
from app.domain.value_objects import RepoMetadata

logger = get_logger(__name__)

GITHUB_API = "https://api.github.com"
MAX_TREE_ENTRIES = 1000


class GitHubAdapter:
    """Async GitHub REST API client for repository introspection."""

    def __init__(self, token: str | None = None) -> None:
        self._token = token or settings.github_token
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        self._client = httpx.AsyncClient(headers=headers, timeout=30.0)

    async def fetch_repo_metadata(self, repo_url: str) -> RepoMetadata:
        """Fetch repository metadata including file tree and README excerpt."""
        owner, repo = self._parse_url(repo_url)
        logger.info("github.fetch_metadata", owner=owner, repo=repo)

        try:
            repo_data = await self._get(f"/repos/{owner}/{repo}")
            default_branch = repo_data.get("default_branch", "main")
            primary_language = repo_data.get("language")

            tree = await self._fetch_file_tree(owner, repo, default_branch)
            readme = await self._fetch_readme(owner, repo)

            return RepoMetadata(
                name=repo_data["full_name"],
                default_branch=default_branch,
                primary_language=primary_language,
                file_tree=tree,
                readme_excerpt=readme[:500] if readme else None,
                repo_url=repo_url,
            )
        except RepositoryAccessError:
            raise
        except Exception as exc:
            raise RepositoryAccessError(repo_url, str(exc)) from exc

    async def fetch_file_content(self, owner: str, repo: str, path: str) -> str:
        """Fetch raw content of a single file."""
        data = await self._get(f"/repos/{owner}/{repo}/contents/{path}")
        if data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return data.get("content", "")

    async def _fetch_file_tree(self, owner: str, repo: str, branch: str) -> list[str]:
        try:
            data = await self._get(
                f"/repos/{owner}/{repo}/git/trees/{branch}",
                params={"recursive": "1"},
            )
            return [
                item["path"]
                for item in data.get("tree", [])[:MAX_TREE_ENTRIES]
                if item.get("type") == "blob"
            ]
        except Exception:
            return []

    async def _fetch_readme(self, owner: str, repo: str) -> str | None:
        try:
            data = await self._get(f"/repos/{owner}/{repo}/readme")
            if data.get("encoding") == "base64":
                return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        except Exception:
            pass
        return None

    async def _get(
        self, path: str, params: dict | None = None  # type: ignore[type-arg]
    ) -> dict:  # type: ignore[type-arg]
        url = f"{GITHUB_API}{path}"
        response = await self._client.get(url, params=params)
        if response.status_code == 404:
            raise RepositoryAccessError(path, "Repository not found (404).")
        if response.status_code == 403:
            raise RepositoryAccessError(path, "Access denied — check GITHUB_TOKEN (403).")
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    @staticmethod
    def _parse_url(repo_url: str) -> tuple[str, str]:
        """Parse 'https://github.com/owner/repo' → ('owner', 'repo')."""
        parsed = urlparse(repo_url.rstrip("/"))
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 2:
            raise RepositoryAccessError(repo_url, "Invalid GitHub URL format.")
        return parts[0], parts[1].removesuffix(".git")

    async def close(self) -> None:
        await self._client.aclose()
