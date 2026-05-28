"""Local repository path validator.

Used for **path-based** local scanning (when the backend has direct filesystem
access, e.g. local development without Docker).

For Docker / Azure deployments use ``POST /api/scans/upload`` instead --
it accepts a folder upload from any OS without requiring filesystem access.
"""
from __future__ import annotations

import os
from pathlib import Path

from app.core.exceptions import ValidationError
from app.core.logging import get_logger

logger = get_logger(__name__)

_SOURCE_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".java", ".kt", ".scala",
    ".go",
    ".rb",
    ".php",
    ".cs",
    ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp",
    ".rs",
    ".swift",
    ".dart",
    ".r",
    ".sh", ".bash",
})

_MAX_WALK_DEPTH: int = 6


class LocalRepoValidator:
    """Validates a local filesystem path for use as a scan source.

    Intended for direct path-based scanning only.  In containerised
    deployments use the /upload endpoint instead.
    """

    async def validate(self, local_path: str) -> str:
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._validate_sync, local_path)

    def _validate_sync(self, local_path: str) -> str:
        try:
            resolved = Path(local_path).resolve()
        except (ValueError, OSError) as exc:
            raise ValidationError(f"Invalid path: cannot resolve '{local_path}'.") from exc

        self._check_path_traversal(local_path)
        self._check_exists(local_path, resolved)
        self._check_is_directory(local_path, resolved)
        self._check_has_source_files(local_path, resolved)

        logger.info("local_validator.ok", original=local_path, resolved=str(resolved))
        return str(resolved)

    @staticmethod
    def _check_path_traversal(original: str) -> None:
        raw = str(original)
        if "\x00" in raw:
            raise ValidationError("Path contains a null byte.")
        if "%2e" in raw.lower() or "%2f" in raw.lower():
            raise ValidationError("Path contains encoded traversal sequences.")

    @staticmethod
    def _check_exists(original: str, resolved: Path) -> None:
        if not resolved.exists():
            raise ValidationError(
                f"Path does not exist: '{original}'.\n"
                "If the backend is running in Docker or Azure, use 'Upload Folder' "
                "in the scan dialog instead of providing a local path."
            )

    @staticmethod
    def _check_is_directory(original: str, resolved: Path) -> None:
        if not resolved.is_dir():
            raise ValidationError(f"Path is not a directory: '{original}'.")

    @staticmethod
    def _check_has_source_files(original: str, resolved: Path) -> None:
        root_str = str(resolved)
        for dirpath, _dirnames, filenames in os.walk(root_str):
            rel = os.path.relpath(dirpath, root_str)
            depth = 0 if rel == "." else rel.count(os.sep) + 1
            if depth > _MAX_WALK_DEPTH:
                break
            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext in _SOURCE_EXTENSIONS:
                    return
        raise ValidationError(
            f"No recognised source files found in '{original}'. "
            f"Expected at least one file with extensions: "
            f"{', '.join(sorted(_SOURCE_EXTENSIONS))}."
        )
