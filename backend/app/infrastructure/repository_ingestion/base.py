"""Abstract base class for repository loaders."""
from __future__ import annotations

import abc

from app.infrastructure.repository_ingestion.models import RepositoryMetadata


class RepositoryLoader(abc.ABC):
    """
    Contract for all repository loaders.

    Rules:
    - No business logic here.
    - No LLM calls.
    - No agent calls.
    - Must be async.
    """

    @abc.abstractmethod
    async def load(self, source: str) -> RepositoryMetadata:
        """
        Load a repository from a source identifier and return structured metadata.

        Args:
            source: A local filesystem path or a GitHub HTTPS URL.

        Returns:
            RepositoryMetadata with root_path, file index, language, and frameworks.

        Raises:
            RepositoryAccessError: If the source cannot be read or cloned.
        """
