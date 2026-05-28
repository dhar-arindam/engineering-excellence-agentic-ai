"""GitHub repository cloner for scan-based workflows.

Unlike the generic GitHubRepositoryLoader, this helper clones directly into a
deterministic path ``/tmp/scans/{scan_id}/`` so the scan orchestrator can
reference files throughout the entire scan lifecycle and clean up explicitly.

Security controls
-----------------
- Shallow clone (--depth 1) to minimise I/O and attack surface.
- Configurable timeout (default 120 s) prevents hanging background tasks.
- Only ``https://github.com/`` URLs are accepted; bare ``git://`` or ``ssh://``
  schemes are rejected before a subprocess is spawned.
- Branch names are validated against a strict allowlist regex before they
  are passed to the subprocess (prevents shell injection).
- Private-repo support via the ``GITHUB_TOKEN`` env var (injected into the URL
  at clone time and never logged or surfaced in error messages).
- Clone errors are re-raised as ``RepositoryAccessError`` without leaking the
  enriched URL (which may contain a token).
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import uuid
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import RepositoryAccessError
from app.core.logging import get_logger

logger = get_logger(__name__)

_SCANS_TMP_BASE = Path("/tmp/scans")
_GIT_CLONE_TIMEOUT: int = 120  # seconds
_MAX_CLONE_DEPTH: int = 1

# Allow alphanumeric, dots, hyphens, underscores, and forward-slashes only.
_SAFE_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/\-]+$")


class GitHubCloner:
    """Clones a GitHub repository into ``/tmp/scans/{scan_id}/`` and manages cleanup.

    Usage::

        cloner = GitHubCloner()
        path = await cloner.clone(scan_id, "https://github.com/owner/repo", branch="main")
        # … use path …
        await cloner.cleanup(scan_id)
    """

    def __init__(self, timeout: int = _GIT_CLONE_TIMEOUT) -> None:
        self._timeout = timeout

    async def clone(
        self,
        scan_id: uuid.UUID,
        repo_url: str,
        branch: str | None = None,
    ) -> str:
        """Clone *repo_url* into ``/tmp/scans/{scan_id}/`` and return the path.

        Args:
            scan_id:  The scan UUID — used to derive an isolated clone directory.
            repo_url: A ``https://github.com/`` URL (with or without ``.git``).
            branch:   Optional branch/tag/ref to clone.  When ``None`` the remote's
                      default branch is used.  The value is validated against
                      ``_SAFE_BRANCH_RE`` to prevent injection attacks.

        Returns:
            Absolute path string of the cloned repository root.

        Raises:
            RepositoryAccessError: For invalid URLs/branches, clone failures, or
                timeouts.
        """
        self._validate_url(repo_url)
        if branch is not None:
            self._validate_branch(branch)

        clone_dir = _SCANS_TMP_BASE / str(scan_id)
        clone_dir.mkdir(parents=True, exist_ok=True)

        repo_name = self._extract_repo_name(repo_url)
        clone_target = clone_dir / repo_name

        clone_url = self._build_clone_url(repo_url)
        logger.info(
            "github_cloner.start",
            scan_id=str(scan_id),
            repo=repo_name,
            branch=branch or "<default>",
            target=str(clone_target),
        )

        await self._run_git_clone(clone_url, str(clone_target), repo_url, branch)
        logger.info("github_cloner.done", scan_id=str(scan_id), path=str(clone_target))
        return str(clone_target)

    async def cleanup(self, scan_id: uuid.UUID) -> None:
        """Remove the clone directory for *scan_id*. Safe to call even if absent."""
        clone_dir = _SCANS_TMP_BASE / str(scan_id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: shutil.rmtree(str(clone_dir), ignore_errors=True),
        )
        logger.debug("github_cloner.cleanup_done", scan_id=str(scan_id))

    async def _run_git_clone(
        self,
        clone_url: str,
        target: str,
        original_url: str,
        branch: str | None,
    ) -> None:
        """Execute ``git clone --depth 1`` (optionally with ``--branch``) as a
        non-blocking subprocess.

        Git 2.37+ rejects clones where the server's redirect changes the URL
        base (e.g. GitHub redirecting ``/repo.git`` → ``/repo``).  We add
        ``-c http.followRedirects=true`` to allow safe redirects, and set
        ``GIT_TERMINAL_PROMPT=0`` to prevent git from hanging on credential
        prompts for private repos without a token.
        """
        cmd = [
            "git",
            "-c", "http.followRedirects=true",
            "clone",
            "--depth", str(_MAX_CLONE_DEPTH),
            "--quiet",
        ]
        if branch:
            cmd += ["--branch", branch]
        cmd += [clone_url, target]

        # Prevent git from prompting for credentials (would hang the worker).
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo"}

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                _, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self._timeout
                )
            except asyncio.TimeoutError as exc:
                proc.kill()
                raise RepositoryAccessError(
                    original_url,
                    f"git clone timed out after {self._timeout}s.",
                ) from exc

            if proc.returncode != 0:
                err_text = stderr.decode("utf-8", errors="replace").strip()
                err_text = self._sanitise_error(err_text)
                raise RepositoryAccessError(original_url, f"git clone failed: {err_text}")

        except RepositoryAccessError:
            raise
        except FileNotFoundError as exc:
            raise RepositoryAccessError(
                original_url, "'git' executable not found on PATH."
            ) from exc
        except Exception as exc:
            raise RepositoryAccessError(original_url, "Unexpected clone error.") from exc

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_url(url: str) -> None:
        if not url.startswith("https://github.com/"):
            raise RepositoryAccessError(
                url,
                "Only https://github.com/ URLs are supported.",
            )

    @staticmethod
    def _validate_branch(branch: str) -> None:
        """Reject branch names with characters that could be used for injection."""
        if not _SAFE_BRANCH_RE.match(branch):
            raise RepositoryAccessError(
                branch,
                "Branch name contains invalid characters. "
                "Only alphanumeric characters, dots, hyphens, underscores, and "
                "forward-slashes are allowed.",
            )

    @staticmethod
    def _extract_repo_name(url: str) -> str:
        # Use removesuffix (Python 3.9+) — rstrip() removes individual chars,
        # not a suffix string, so "testing.git".rstrip(".git") → "testin" (bug).
        name = url.rstrip("/").split("/")[-1].removesuffix(".git")
        return name or "repository"

    @staticmethod
    def _build_clone_url(url: str) -> str:
        """Build the clone URL, injecting a GitHub token when available.

        We intentionally do NOT append ``.git`` — GitHub redirects the ``.git``
        URL to the bare URL in its smart-HTTP protocol, and Git 2.37+ rejects
        clones where the server's redirect changes the URL base.  Both forms
        work; the bare URL is canonical and avoids the redirect entirely.
        """
        url = url.rstrip("/").removesuffix(".git")

        token = settings.github_token
        if token:
            # https://token@github.com/owner/repo
            url = url.replace("https://", f"https://{token}@", 1)
        return url

    @staticmethod
    def _sanitise_error(text: str) -> str:
        """Remove potential token from error output before it reaches logs/DB."""
        token = settings.github_token
        if token and token in text:
            text = text.replace(token, "***")
        return text
