"""LocalRepositoryLoader — loads a repository from an existing local filesystem path."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from app.core.exceptions import RepositoryAccessError
from app.core.logging import get_logger
from app.infrastructure.repository_ingestion.base import RepositoryLoader
from app.infrastructure.repository_ingestion.models import RepositoryMetadata
from app.infrastructure.repository_ingestion.scanner import (
    build_file_index,
    count_lines_of_code,
    detect_frameworks,
    detect_primary_language,
)

logger = get_logger(__name__)


class LocalRepositoryLoader(RepositoryLoader):
    """
    Loads a repository from an existing local filesystem path.

    No cloning, no network I/O — pure filesystem scan delegated to scanner utilities.
    """

    async def load(self, source: str) -> RepositoryMetadata:
        """
        Scan a local directory and return structured RepositoryMetadata.

        Args:
            source: Absolute or relative filesystem path to the repository root.

        Returns:
            RepositoryMetadata with full file index, language, and frameworks.

        Raises:
            RepositoryAccessError: If the path does not exist or is not a directory.
        """
        root = os.path.abspath(source)

        if not os.path.exists(root):
            raise RepositoryAccessError(source, "Path does not exist.")
        if not os.path.isdir(root):
            raise RepositoryAccessError(source, "Path is not a directory.")

        name = Path(root).name
        logger.info("local_loader.start", root=root, name=name)

        # All scanning runs concurrently: file index first, then derived metrics in parallel
        file_index = await build_file_index(root)

        total_lines, primary_language, frameworks = await asyncio.gather(
            count_lines_of_code(root, file_index),
            detect_primary_language(file_index),
            detect_frameworks(root, file_index),
        )

        metadata = RepositoryMetadata(
            name=name,
            root_path=root,
            primary_language=primary_language,
            total_files=len(file_index),
            total_lines=total_lines,
            detected_frameworks=frameworks,
            file_index=file_index,
        )

        logger.info(
            "local_loader.done",
            name=name,
            total_files=metadata.total_files,
            total_lines=metadata.total_lines,
            language=metadata.primary_language,
            frameworks=metadata.detected_frameworks,
        )
        return metadata
