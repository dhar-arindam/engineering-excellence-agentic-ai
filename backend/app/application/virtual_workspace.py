"""Virtual workspace — in-memory isolated copy of a repository for safe patching.

The VirtualWorkspace creates a temporary directory copy of a source repository,
allowing the patch engine and validation pipeline to modify files without ever
touching the original checkout.

Design principles
-----------------
- The original ``source_path`` is **never** written to.
- All file operations are performed on an isolated tempdir that is owned by
  this object and cleaned up explicitly via :meth:`cleanup`.
- Modified files are tracked in a set so callers know exactly what changed.
- All blocking I/O runs via ``asyncio.to_thread`` to keep the event loop free.

Usage::

    async with VirtualWorkspace.create(source_path) as ws:
        files = await ws.load_files()
        await ws.write_file("src/main.py", new_content)
        modified = await ws.list_modified_files()
"""
from __future__ import annotations

import asyncio
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from app.core.logging import get_logger

logger = get_logger(__name__)

# File extensions considered source code — others are tracked but not loaded
# into the in-memory content dict by default.
_SOURCE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".go", ".java", ".kt", ".rs", ".rb",
    ".c", ".cpp", ".h", ".hpp",
    ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg",
    ".md", ".txt", ".sh", ".bash",
    ".html", ".css", ".scss",
    ".sql", ".proto",
}
_MAX_FILE_SIZE_BYTES = 512 * 1024  # 512 KB — skip huge generated files


class VirtualWorkspace:
    """An isolated, writable copy of a repository directory.

    Do not instantiate directly; use :meth:`create` or the async context manager
    :func:`VirtualWorkspace.create`.
    """

    def __init__(self, source_path: str, work_dir: str) -> None:
        self._source_path = Path(source_path).resolve()
        self._work_dir = Path(work_dir)
        self._modified: set[str] = set()

    # ------------------------------------------------------------------
    # Factory / context manager
    # ------------------------------------------------------------------

    @classmethod
    @asynccontextmanager
    async def create(cls, source_path: str) -> "AsyncIterator[VirtualWorkspace]":
        """Async context manager that creates a VirtualWorkspace and cleans up on exit.

        Usage::

            async with VirtualWorkspace.create("/path/to/repo") as ws:
                ...
        """
        work_dir = await asyncio.to_thread(tempfile.mkdtemp, prefix="vws_")
        try:
            # Copy source tree into work_dir/repo/
            target = Path(work_dir) / "repo"
            await asyncio.to_thread(
                shutil.copytree,
                source_path,
                str(target),
                symlinks=False,
                ignore_dangling_symlinks=True,
            )
            logger.debug(
                "virtual_workspace.created",
                source=source_path,
                work_dir=work_dir,
            )
            ws = cls(source_path=source_path, work_dir=str(target))
            yield ws
        finally:
            await asyncio.to_thread(shutil.rmtree, work_dir, True)
            logger.debug("virtual_workspace.cleaned_up", work_dir=work_dir)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def work_path(self) -> str:
        """Absolute path to the isolated workspace root."""
        return str(self._work_dir)

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    async def load_files(self) -> dict[str, str]:
        """Return a dict of ``{relative_path: content}`` for all source files.

        Files larger than ``_MAX_FILE_SIZE_BYTES`` or with non-text encodings
        are silently skipped.
        """
        return await asyncio.to_thread(self._load_files_sync)

    def _load_files_sync(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for path in sorted(self._work_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix not in _SOURCE_EXTENSIONS:
                continue
            if path.stat().st_size > _MAX_FILE_SIZE_BYTES:
                continue
            rel = str(path.relative_to(self._work_dir))
            try:
                result[rel] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
        return result

    async def get_file_content(self, relative_path: str) -> str:
        """Return the current content of *relative_path* from the workspace.

        Raises:
            FileNotFoundError: If the path does not exist in the workspace.
        """
        abs_path = self._resolve_safe(relative_path)
        return await asyncio.to_thread(abs_path.read_text, "utf-8")

    async def write_file(self, relative_path: str, content: str) -> None:
        """Write *content* to *relative_path* inside the workspace.

        The parent directories are created if they do not exist.
        The file is tracked in the modified-files set.

        Raises:
            ValueError: If *relative_path* escapes the workspace root (path traversal).
        """
        abs_path = self._resolve_safe(relative_path)
        await asyncio.to_thread(self._write_file_sync, abs_path, content)
        self._modified.add(relative_path)

    def _write_file_sync(self, abs_path: Path, content: str) -> None:
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding="utf-8")

    async def delete_file(self, relative_path: str) -> None:
        """Delete *relative_path* from the workspace (tracks as modified)."""
        abs_path = self._resolve_safe(relative_path)
        await asyncio.to_thread(abs_path.unlink, missing_ok=True)
        self._modified.add(relative_path)

    async def apply_patch(self, diff_patch: str) -> list[str]:
        """Apply a unified-diff patch to the workspace files.

        Parses the patch text and applies each hunk.  Returns the list of
        file paths that were actually modified.

        Args:
            diff_patch: A string in unified diff format (``diff --git a/… b/…``
                        or standard ``--- a/…  +++ b/…`` headers).

        Returns:
            List of relative paths that were modified.

        Raises:
            PatchApplyError: If a hunk cannot be applied cleanly.
        """
        changed = await asyncio.to_thread(self._apply_patch_sync, diff_patch)
        self._modified.update(changed)
        return changed

    def _apply_patch_sync(self, diff_patch: str) -> list[str]:
        """Pure-sync unified-diff applier (no shell, no external deps)."""
        from app.application._patch_apply import apply_unified_diff
        return apply_unified_diff(self._work_dir, diff_patch)

    async def list_modified_files(self) -> list[str]:
        """Return a sorted list of relative paths modified since workspace creation."""
        return sorted(self._modified)

    # ------------------------------------------------------------------
    # Safety helper
    # ------------------------------------------------------------------

    def _resolve_safe(self, relative_path: str) -> Path:
        """Resolve *relative_path* under work_dir and guard against traversal.

        Raises:
            ValueError: If the resolved path escapes the workspace root.
        """
        # Normalise OS separators and strip leading slashes/dots
        clean = relative_path.replace("\\", "/").lstrip("/.")
        abs_path = (self._work_dir / clean).resolve()
        try:
            abs_path.relative_to(self._work_dir.resolve())
        except ValueError as exc:
            raise ValueError(
                f"Path traversal detected: '{relative_path}' escapes workspace root."
            ) from exc
        return abs_path
