"""Source preparation service.

Bridges the API contract (source_type + source_reference) to a concrete
filesystem path ready for the scan pipeline.

Responsibilities
----------------
- Validate GitHub URLs / local paths (delegates to infrastructure helpers).
- Clone GitHub repos into ``/tmp/scans/{scan_id}/`` via :class:`GitHubCloner`.
- Reference local paths directly (no copy) via :class:`LocalRepoValidator`.
- Return both the resolved path and the folder name (used as repo name).

This module contains **no** HTTP, **no** database, and **no** agent logic.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.infrastructure.github_clone import GitHubCloner
from app.infrastructure.local_repo_validator import LocalRepoValidator

logger = get_logger(__name__)


@dataclass(frozen=True)
class PreparedSource:
    """Result of source preparation — a validated, accessible filesystem path."""

    path: str
    """Absolute path to the repository root on the local filesystem."""

    repo_name: str
    """Human-readable repository name (derived from URL or folder name)."""

    source_type: str
    """Either ``"github"`` or ``"local"``."""


class SourcePreparationService:
    """Prepares a code source for scanning.

    Injected dependencies allow full unit-test mocking without touching the
    filesystem or network.
    """

    def __init__(
        self,
        github_cloner: GitHubCloner | None = None,
        local_validator: LocalRepoValidator | None = None,
    ) -> None:
        self._cloner = github_cloner or GitHubCloner()
        self._validator = local_validator or LocalRepoValidator()

    async def prepare(
        self,
        scan_id: uuid.UUID,
        source_type: str,
        repository_url: str | None,
        local_path: str | None,
        branch: str | None = None,
    ) -> PreparedSource:
        """Prepare the source and return a :class:`PreparedSource`.

        Args:
            scan_id:        UUID of the scan (used as a clone directory name).
            source_type:    ``"github"`` or ``"local"``.
            repository_url: Required when source_type == "github".
            local_path:     Required when source_type == "local".
            branch:         Optional git branch (GitHub only).

        Returns:
            :class:`PreparedSource` with the resolved path and repo name.

        Raises:
            ValidationError: If the source cannot be validated or cloned.
        """
        if source_type == "github":
            return await self._prepare_github(scan_id, repository_url, branch)
        if source_type == "local":
            return await self._prepare_local(local_path)
        raise ValidationError(f"Unsupported source_type: '{source_type}'.")

    # ------------------------------------------------------------------
    # GitHub preparation
    # ------------------------------------------------------------------

    async def _prepare_github(
        self, scan_id: uuid.UUID, repository_url: str | None, branch: str | None = None
    ) -> PreparedSource:
        if not repository_url:
            raise ValidationError("repository_url is required for source_type='github'.")

        path = await self._cloner.clone(scan_id, repository_url, branch=branch)
        repo_name = Path(path).name

        logger.info(
            "source_prep.github_ready",
            scan_id=str(scan_id),
            path=path,
            repo_name=repo_name,
            branch=branch or "<default>",
        )
        return PreparedSource(path=path, repo_name=repo_name, source_type="github")

    # ------------------------------------------------------------------
    # Local preparation
    # ------------------------------------------------------------------

    async def _prepare_local(self, local_path: str | None) -> PreparedSource:
        if not local_path:
            raise ValidationError("local_path is required for source_type='local'.")

        resolved = await self._validator.validate(local_path)
        repo_name = Path(resolved).name

        logger.info(
            "source_prep.local_ready",
            resolved=resolved,
            repo_name=repo_name,
        )
        return PreparedSource(path=resolved, repo_name=repo_name, source_type="local")
