"""Code chunker — splits source files into semantically meaningful CodeChunks.

Strategy:
  1. Python files → AST walk: each top-level class/function becomes a chunk.
     Nested classes/methods are grouped with their parent to keep context intact.
  2. All other files (or Python files that fail AST parsing) → fixed-size line
     splits of ``chunk_lines`` lines with ``overlap_lines`` lines of overlap so
     no context is lost across chunk boundaries.

The chunker is synchronous internally (AST parsing is CPU-bound) but exposed
via an async facade so it integrates cleanly with the async pipeline.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import Sequence

from app.infrastructure.embeddings.models import CodeChunk

# Languages we attempt AST-level chunking for
_AST_LANGUAGES = frozenset({"python"})

# File-extension → language name mapping
_EXT_TO_LANG: dict[str, str] = {
    ".py":   "python",
    ".js":   "javascript",
    ".ts":   "typescript",
    ".tsx":  "typescript",
    ".jsx":  "javascript",
    ".go":   "go",
    ".java": "java",
    ".rb":   "ruby",
    ".rs":   "rust",
    ".cpp":  "cpp",
    ".c":    "c",
    ".cs":   "csharp",
    ".kt":   "kotlin",
    ".swift":"swift",
    ".php":  "php",
    ".yaml": "yaml",
    ".yml":  "yaml",
    ".json": "json",
    ".md":   "markdown",
    ".sh":   "shell",
    ".sql":  "sql",
}

_DEFAULT_CHUNK_LINES   = 100   # target lines per non-AST chunk
_DEFAULT_OVERLAP_LINES = 10    # overlap between adjacent line-split chunks


def detect_language(file_path: str) -> str:
    """Return a lowercase language name from the file extension."""
    ext = Path(file_path).suffix.lower()
    return _EXT_TO_LANG.get(ext, "unknown")


# ---------------------------------------------------------------------------
# AST-based Python chunking
# ---------------------------------------------------------------------------

class _TopLevelVisitor(ast.NodeVisitor):
    """Collect top-level class and function definitions with their line ranges."""

    def __init__(self) -> None:
        self.symbols: list[tuple[str, int, int]] = []  # (name, start, end)

    # Only visit top-level — do NOT recurse into nested class/function bodies
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.symbols.append((node.name, node.lineno, node.end_lineno or node.lineno))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.symbols.append((node.name, node.lineno, node.end_lineno or node.lineno))

    visit_AsyncFunctionDef = visit_FunctionDef  # same handling


def _chunk_python(file_path: str, source: str) -> list[CodeChunk]:
    """AST-based Python chunking.  Falls back to line-split on parse failure."""
    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return _chunk_by_lines(file_path, source, "python")

    lines = source.splitlines()
    visitor = _TopLevelVisitor()
    visitor.visit(tree)

    if not visitor.symbols:
        # Module has no top-level definitions (e.g. script with only statements)
        return _chunk_by_lines(file_path, source, "python")

    chunks: list[CodeChunk] = []
    for idx, (name, start, end) in enumerate(visitor.symbols):
        content = "\n".join(lines[start - 1 : end])
        if not content.strip():
            continue
        chunks.append(
            CodeChunk(
                file_path=file_path,
                start_line=start,
                end_line=end,
                content=content,
                language="python",
                symbol_name=name,
                chunk_index=idx,
            )
        )

    # Capture any top-of-file content (imports, module docstring, etc.) that
    # sits before the first symbol
    if visitor.symbols:
        first_start = visitor.symbols[0][1]
        if first_start > 1:
            preamble = "\n".join(lines[: first_start - 1]).strip()
            if preamble:
                chunks.insert(
                    0,
                    CodeChunk(
                        file_path=file_path,
                        start_line=1,
                        end_line=first_start - 1,
                        content=preamble,
                        language="python",
                        symbol_name="<module_preamble>",
                        chunk_index=-1,
                    ),
                )

    return chunks or _chunk_by_lines(file_path, source, "python")


# ---------------------------------------------------------------------------
# Line-split fallback
# ---------------------------------------------------------------------------

def _chunk_by_lines(
    file_path: str,
    source: str,
    language: str,
    chunk_lines: int = _DEFAULT_CHUNK_LINES,
    overlap_lines: int = _DEFAULT_OVERLAP_LINES,
) -> list[CodeChunk]:
    """Split *source* into overlapping fixed-size line windows."""
    lines = source.splitlines()
    total = len(lines)
    if total == 0:
        return []

    step   = max(1, chunk_lines - overlap_lines)
    chunks = []
    idx    = 0
    start  = 0  # 0-based

    while start < total:
        end_exclusive = min(start + chunk_lines, total)
        content = "\n".join(lines[start:end_exclusive])
        if content.strip():
            chunks.append(
                CodeChunk(
                    file_path=file_path,
                    start_line=start + 1,        # 1-based
                    end_line=end_exclusive,       # inclusive
                    content=content,
                    language=language,
                    chunk_index=idx,
                )
            )
        start += step
        idx   += 1

    return chunks


# ---------------------------------------------------------------------------
# Public async facade
# ---------------------------------------------------------------------------

class CodeChunker:
    """
    Async-compatible code chunker.

    * Python files are chunked by top-level AST symbols.
    * All other files use a fixed-size overlapping line split.
    * Both strategies respect ``chunk_lines`` / ``overlap_lines`` for the
      fallback path.

    Chunking is CPU-bound; heavy workloads can be dispatched to a thread
    executor via :meth:`chunk_file_async`.
    """

    def __init__(
        self,
        chunk_lines: int = _DEFAULT_CHUNK_LINES,
        overlap_lines: int = _DEFAULT_OVERLAP_LINES,
    ) -> None:
        self._chunk_lines   = chunk_lines
        self._overlap_lines = overlap_lines

    # ------------------------------------------------------------------
    # Synchronous helpers (usable directly in tests / CPU executor)
    # ------------------------------------------------------------------

    def chunk_source(self, file_path: str, source: str) -> list[CodeChunk]:
        """Chunk *source* synchronously.  Caller supplies the content."""
        language = detect_language(file_path)
        if language in _AST_LANGUAGES:
            return _chunk_python(file_path, source)
        return _chunk_by_lines(
            file_path, source, language,
            self._chunk_lines, self._overlap_lines,
        )

    def chunk_file_sync(self, file_path: str) -> list[CodeChunk]:
        """Read *file_path* from disk and chunk it synchronously."""
        try:
            source = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        return self.chunk_source(file_path, source)

    # ------------------------------------------------------------------
    # Async facade
    # ------------------------------------------------------------------

    async def chunk_file(self, file_path: str) -> list[CodeChunk]:
        """Read and chunk a file, offloading I/O+CPU to a thread executor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.chunk_file_sync, file_path)

    async def chunk_repository(
        self,
        root_path: str,
        file_paths: Sequence[str],
    ) -> list[CodeChunk]:
        """
        Chunk all *file_paths* under *root_path* concurrently.

        *file_paths* should be relative paths; they are resolved against
        *root_path* before reading.
        """
        root = Path(root_path)
        tasks = [
            self.chunk_file(str(root / p))
            for p in file_paths
            if _should_chunk(p)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        chunks: list[CodeChunk] = []
        for r in results:
            if isinstance(r, Exception):
                continue
            chunks.extend(r)  # type: ignore[arg-type]
        return chunks


def _should_chunk(file_path: str) -> bool:
    """Skip binary-like files and lock files."""
    skip_exts = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
                 ".woff", ".ttf", ".eot", ".pdf", ".zip", ".tar",
                 ".gz", ".lock", ".pyc"}
    skip_names = {"package-lock.json", "yarn.lock", "poetry.lock",
                  "Pipfile.lock", "Gemfile.lock"}
    p = Path(file_path)
    return p.suffix.lower() not in skip_exts and p.name not in skip_names
