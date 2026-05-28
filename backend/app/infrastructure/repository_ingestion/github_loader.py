"""GitHubRepositoryLoader — clones a public GitHub repo and returns RepositoryMetadata.

Cleanup strategy
----------------
A `tempfile.TemporaryDirectory` is created for every clone. The loader exposes two
usage patterns:

1. **Standalone** — ``await loader.load(url)``:
   Clones, scans, deletes the temp dir in a finally block, then returns metadata.
   The ``root_path`` in the returned metadata will point to a now-deleted directory.
   Use this when you only need the metadata (no file-level access after load).

2. **Context manager** — ``async with loader.clone_context(url) as meta``:
   Yields RepositoryMetadata with a live ``root_path``.
   The temp dir is deleted when the context exits.
   Use this when downstream code (e.g. agents) need to read actual files.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import urlparse

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

GIT_CLONE_TIMEOUT = 120  # seconds


class GitHubRepositoryLoader(RepositoryLoader):
    """
    Clones a GitHub (or any public git) repository into a temporary directory
    and returns structured RepositoryMetadata.

    Requires ``git`` to be available on PATH.
    """

    def __init__(self, clone_timeout: int = GIT_CLONE_TIMEOUT) -> None:
        self._clone_timeout = clone_timeout

    async def load(self, source: str) -> RepositoryMetadata:
        """
        Clone, scan, and immediately clean up the temp directory.

        The returned RepositoryMetadata.root_path will reference the deleted
        temp directory — suitable for metadata-only use cases.
        """
        tmp_dir = tempfile.mkdtemp(prefix="repo_ingestion_")
        try:
            return await self._clone_and_scan(source, tmp_dir)
        finally:
            await self._cleanup(tmp_dir)

    @asynccontextmanager
    async def clone_context(self, source: str) -> AsyncIterator[RepositoryMetadata]:
        """
        Async context manager — keeps the clone alive for the duration of the block.

        Usage::

            async with loader.clone_context(url) as meta:
                # meta.root_path is a valid directory here
                ...
            # temp dir deleted here
        """
        tmp_dir = tempfile.mkdtemp(prefix="repo_ingestion_")
        try:
            metadata = await self._clone_and_scan(source, tmp_dir)
            yield metadata
        finally:
            await self._cleanup(tmp_dir)

    async def _clone_and_scan(self, url: str, tmp_dir: str) -> RepositoryMetadata:
        """Clone the repo into tmp_dir then run all scanner utilities."""
        clone_url = self._normalise_url(url)
        repo_name = self._extract_repo_name(clone_url)
        clone_target = str(Path(tmp_dir) / repo_name)

        logger.info("github_loader.cloning", url=clone_url, target=clone_target)
        await self._git_clone(clone_url, clone_target)
        logger.info("github_loader.cloned", target=clone_target)

        file_index = await build_file_index(clone_target)

        total_lines, primary_language, frameworks = await asyncio.gather(
            count_lines_of_code(clone_target, file_index),
            detect_primary_language(file_index),
            detect_frameworks(clone_target, file_index),
        )

        metadata = RepositoryMetadata(
            name=repo_name,
            root_path=clone_target,
            primary_language=primary_language,
            total_files=len(file_index),
            total_lines=total_lines,
            detected_frameworks=frameworks,
            file_index=file_index,
        )
        logger.info(
            "github_loader.scanned",
            name=repo_name,
            total_files=metadata.total_files,
            total_lines=metadata.total_lines,
            language=metadata.primary_language,
        )
        return metadata

    async def _git_clone(self, url: str, target: str) -> None:
        """Run ``git clone --depth 1`` with redirect-safe settings.

        Git 2.37+ rejects clones where the server redirect changes the URL
        base.  ``-c http.followRedirects=true`` opts in to safe redirect
        following.  ``GIT_TERMINAL_PROMPT=0`` prevents hanging on prompts.
        """
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo"}
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "-c", "http.followRedirects=true",
                "clone", "--depth", "1", "--quiet", url, target,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self._clone_timeout
                )
            except asyncio.TimeoutError as exc:
                proc.kill()
                raise RepositoryAccessError(
                    url, f"git clone timed out after {self._clone_timeout}s."
                ) from exc

            if proc.returncode != 0:
                err_msg = stderr.decode("utf-8", errors="replace").strip()
                raise RepositoryAccessError(url, f"git clone failed: {err_msg}")

        except RepositoryAccessError:
            raise
        except FileNotFoundError as exc:
            raise RepositoryAccessError(
                url, "'git' executable not found on PATH."
            ) from exc
        except Exception as exc:
            raise RepositoryAccessError(url, str(exc)) from exc

    @staticmethod
    async def _cleanup(tmp_dir: str) -> None:
        """Delete the temporary directory in an executor to avoid blocking."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: shutil.rmtree(tmp_dir, ignore_errors=True),
        )
        logger.debug("github_loader.cleanup_done", tmp_dir=tmp_dir)

    @staticmethod
    def _normalise_url(url: str) -> str:
        """Return a redirect-safe clone URL.

        We strip the ``.git`` suffix (if present) rather than adding it.
        GitHub redirects ``/repo.git`` → ``/repo`` in its smart-HTTP
        protocol; Git 2.37+ treats that base-URL change as an error.
        Using the bare URL avoids the redirect entirely.
        """
        return url.rstrip("/").removesuffix(".git")

    @staticmethod
    def _extract_repo_name(url: str) -> str:
        """Extract the repository name from a git URL."""
        parsed = urlparse(url)
        name = Path(parsed.path).stem  # removes .git suffix
        return name or "repository"
