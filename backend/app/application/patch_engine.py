"""Patch engine — generates unified diffs from agent issues and applies them.

The patch engine works entirely within a :class:`~app.application.virtual_workspace.VirtualWorkspace`.
It never reads from or writes to the original repository.

Design
------
- ``generate_patch`` asks the LLM (via a simple prompt) to produce a unified
  diff that addresses the supplied issues.  If no LLM is configured the engine
  produces a ``no-op`` patch and logs a warning.
- ``apply_patch`` delegates to :meth:`VirtualWorkspace.apply_patch` — the actual
  hunk parsing lives in ``_patch_apply.py``.
- The output is always a standard unified diff string that can be stored,
  reviewed, and attached to a PR description.

Usage::

    engine = PatchEngine()
    patch = await engine.generate_patch(issues, workspace)
    changed = await engine.apply_patch(patch, workspace)
"""
from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.application.virtual_workspace import VirtualWorkspace
    from app.domain.entities import AgentIssue

logger = get_logger(__name__)


@dataclass
class PatchResult:
    """Outcome of a patch generation + application cycle."""

    patch_text: str
    """The unified diff string (may be empty if nothing to patch)."""

    modified_files: list[str]
    """Relative paths of files actually changed in the workspace."""

    errors: list[str]
    """Non-fatal errors encountered during generation or application."""


class PatchEngine:
    """Generates unified diffs from a list of issues and applies them to a workspace.

    The engine is intentionally LLM-agnostic: it accepts an optional
    ``llm_adapter`` callable.  If none is provided it falls back to a
    comment-only patch (safe no-op that documents the finding inline).
    """

    def __init__(self, llm_adapter=None) -> None:  # type: ignore[assignment]
        self._llm = llm_adapter

    async def generate_patch(
        self,
        issues: "list[AgentIssue]",
        workspace: "VirtualWorkspace",
        context_files: list[str] | None = None,
    ) -> str:
        """Generate a unified diff that addresses *issues* in *workspace*.

        Args:
            issues:        Agent issues to fix.
            workspace:     The virtual workspace containing source files.
            context_files: Subset of files to pass as context to the LLM.
                           When ``None``, all workspace files are used.

        Returns:
            A unified diff string (may be empty if no patches were generated).
        """
        if not issues:
            return ""

        files = await workspace.load_files()
        if context_files:
            files = {k: v for k, v in files.items() if k in context_files}

        if self._llm:
            try:
                patch = await self._generate_via_llm(issues, files)
                logger.info(
                    "patch_engine.generated",
                    issues=len(issues),
                    patch_lines=patch.count("\n"),
                )
                return patch
            except Exception as exc:  # noqa: BLE001
                logger.warning("patch_engine.llm_error", error=str(exc))

        # Fallback: inline comment-only patch documenting each issue.
        return self._generate_comment_patch(issues, files)

    async def apply_patch(
        self,
        patch: str,
        workspace: "VirtualWorkspace",
    ) -> PatchResult:
        """Apply *patch* to *workspace* and return a :class:`PatchResult`.

        Args:
            patch:     Unified diff string to apply.
            workspace: Target virtual workspace.

        Returns:
            :class:`PatchResult` with modified files and any non-fatal errors.
        """
        if not patch.strip():
            return PatchResult(patch_text=patch, modified_files=[], errors=[])

        errors: list[str] = []
        try:
            changed = await workspace.apply_patch(patch)
        except Exception as exc:  # noqa: BLE001
            msg = f"Patch application failed: {exc}"
            logger.error("patch_engine.apply_error", error=msg)
            errors.append(msg)
            changed = []

        return PatchResult(patch_text=patch, modified_files=changed, errors=errors)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _generate_via_llm(
        self,
        issues: "list[AgentIssue]",
        files: dict[str, str],
    ) -> str:
        """Delegate to the injected LLM adapter to produce a unified diff."""
        issue_block = "\n".join(
            f"- [{i.severity.value}] {i.title}: {i.description}"
            for i in issues
        )
        file_block = "\n\n".join(
            f"=== {path} ===\n{content[:4000]}"  # cap context per file
            for path, content in list(files.items())[:10]  # max 10 files
        )
        prompt = textwrap.dedent(f"""
            You are a senior engineer. Generate a minimal unified diff (git diff format)
            that fixes the following issues in the provided source files.

            ISSUES:
            {issue_block}

            SOURCE FILES:
            {file_block}

            RULES:
            - Output ONLY the unified diff, no explanations.
            - Use standard unified diff format (--- a/path  +++ b/path  @@ ... @@).
            - Make the smallest possible change that fixes each issue.
            - Do NOT add unrelated changes.
            - If an issue cannot be auto-fixed, skip it silently.
        """).strip()

        result = await self._llm(prompt)
        return result if isinstance(result, str) else ""

    @staticmethod
    def _generate_comment_patch(
        issues: "list[AgentIssue]",
        files: dict[str, str],
    ) -> str:
        """Produce a no-op diff that adds issue comments to the first Python file."""
        # Find first Python file with content.
        target: str | None = None
        original: str | None = None
        for path, content in files.items():
            if path.endswith(".py") and content.strip():
                target = path
                original = content
                break

        if not target or original is None:
            return ""

        comment_block = "\n".join(
            f"# TODO [{i.severity.value}] {i.title}: {i.description}"
            for i in issues
        )
        patched = f"# === AI Engineering Intelligence Findings ===\n{comment_block}\n\n{original}"

        # Build a minimal unified diff.
        orig_lines = original.splitlines(keepends=True)
        patch_lines = patched.splitlines(keepends=True)
        additions = len(patch_lines) - len(orig_lines)

        diff_lines = [
            f"--- a/{target}\n",
            f"+++ b/{target}\n",
            f"@@ -1,{len(orig_lines)} +1,{len(patch_lines)} @@\n",
        ]
        comment_lines = patched.splitlines(keepends=True)[: additions + 1]
        for line in comment_lines:
            diff_lines.append(f"+{line}")
        for line in orig_lines:
            diff_lines.append(f" {line}")

        return "".join(diff_lines)
