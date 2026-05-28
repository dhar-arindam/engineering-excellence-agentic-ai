"""File scanning utilities for repository analysis.

All functions are pure (no side effects beyond reading the filesystem) and
run blocking I/O in asyncio executors so they don't block the event loop.

No LLM calls. No agent calls. No business logic.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from app.infrastructure.repository_ingestion.models import FileEntry

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Map file extensions → canonical language names
_EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".java": "Java",
    ".kt": "Kotlin",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".c": "C",
    ".h": "C",
    ".swift": "Swift",
    ".scala": "Scala",
    ".r": "R",
    ".R": "R",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".json": "JSON",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sql": "SQL",
    ".tf": "Terraform",
    ".dart": "Dart",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".clj": "Clojure",
    ".lua": "Lua",
}

# Framework detection rules: (display_name, list_of_indicator_paths_or_filenames)
_FRAMEWORK_INDICATORS: list[tuple[str, list[str]]] = [
    # Python ecosystems
    ("FastAPI",          ["main.py"]),          # heuristic; refined by content check below
    ("Django",           ["manage.py"]),
    ("Flask",            ["wsgi.py", "app.py"]),
    ("Poetry",           ["pyproject.toml"]),
    ("pip",              ["requirements.txt"]),
    ("pytest",           ["pytest.ini", "conftest.py"]),
    # JavaScript/TypeScript
    ("Node.js",          ["package.json"]),
    ("Next.js",          ["next.config.js", "next.config.ts", "next.config.mjs"]),
    ("React",            ["src/App.tsx", "src/App.jsx", "src/App.js"]),
    ("Vue",              ["vue.config.js"]),
    ("Vite",             ["vite.config.ts", "vite.config.js"]),
    # JVM
    ("Maven",            ["pom.xml"]),
    ("Gradle",           ["build.gradle", "build.gradle.kts"]),
    ("Spring Boot",      ["src/main/resources/application.properties",
                          "src/main/resources/application.yml"]),
    # Go
    ("Go Modules",       ["go.mod"]),
    # Rust
    ("Cargo",            ["Cargo.toml"]),
    # Ruby
    ("Bundler",          ["Gemfile"]),
    ("Rails",            ["config/routes.rb"]),
    # Infrastructure
    ("Docker",           ["Dockerfile", "docker-compose.yml", "docker-compose.yaml"]),
    ("Kubernetes",       ["k8s/", "kubernetes/", "helm/"]),
    ("Terraform",        ["main.tf", "terraform.tfvars"]),
    ("GitHub Actions",   [".github/workflows"]),
    ("Makefile",         ["Makefile", "GNUmakefile"]),
    # DB / migrations
    ("Alembic",          ["alembic.ini", "alembic/"]),
    ("Flyway",           ["db/migration/"]),
]

# Directories to always skip during scanning
_SKIP_DIRS: frozenset[str] = frozenset({
    ".git", ".hg", ".svn",
    "node_modules", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".tox",
    "venv", ".venv", "env", ".env",
    "dist", "build", ".next", "target",
    ".idea", ".vscode",
})

# Binary / non-source extensions to skip when counting lines
_BINARY_EXTENSIONS: frozenset[str] = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z",
    ".exe", ".dll", ".so", ".dylib", ".whl", ".egg",
    ".lock", ".sum",
    ".pyc", ".pyo", ".class",
    ".mp3", ".mp4", ".avi", ".mov",
    ".ttf", ".woff", ".woff2", ".eot",
    ".db", ".sqlite", ".sqlite3",
})

MAX_FILE_SIZE_BYTES = 1_000_000  # skip files > 1 MB for line counting


# ---------------------------------------------------------------------------
# Sync helpers (intended to run inside executor)
# ---------------------------------------------------------------------------

def _walk_repo(root: str) -> list[FileEntry]:
    """Recursively walk a repository directory and collect FileEntry records."""
    entries: list[FileEntry] = []
    root_path = Path(root)

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skip-dirs in place so os.walk does not descend into them
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]

        for filename in filenames:
            full = Path(dirpath) / filename
            try:
                size = full.stat().st_size
            except OSError:
                continue
            rel = str(full.relative_to(root_path))
            ext = full.suffix.lower()
            entries.append(FileEntry(path=rel, size=size, extension=ext))

    return entries


def _count_lines_sync(root: str, entries: list[FileEntry]) -> int:
    """Count total source lines of code, skipping binary and oversized files."""
    total = 0
    root_path = Path(root)

    for entry in entries:
        if entry.extension in _BINARY_EXTENSIONS:
            continue
        if entry.size > MAX_FILE_SIZE_BYTES:
            continue
        full = root_path / entry.path
        try:
            text = full.read_text(encoding="utf-8", errors="replace")
            total += text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        except OSError:
            continue

    return total


def _detect_primary_language_sync(entries: list[FileEntry]) -> str | None:
    """Return the language with the highest file count, ignoring config-only extensions."""
    counts: dict[str, int] = {}
    for entry in entries:
        lang = _EXTENSION_LANGUAGE_MAP.get(entry.extension)
        if lang and lang not in {"YAML", "TOML", "JSON", "Makefile"}:
            counts[lang] = counts.get(lang, 0) + 1

    if not counts:
        return None
    return max(counts, key=lambda l: counts[l])


def _detect_frameworks_sync(root: str, entries: list[FileEntry]) -> list[str]:
    """Detect frameworks present in the repository based on file indicators."""
    file_set = {e.path.replace("\\", "/") for e in entries}
    file_names = {Path(e.path).name for e in entries}
    root_path = Path(root)
    found: list[str] = []

    for framework, indicators in _FRAMEWORK_INDICATORS:
        for indicator in indicators:
            # Match by filename, relative path prefix, or directory presence
            indicator_name = Path(indicator).name
            matched = (
                indicator in file_set
                or indicator_name in file_names
                or any(p.startswith(indicator.rstrip("/")) for p in file_set)
                or (root_path / indicator).exists()
            )
            if matched:
                found.append(framework)
                break

    # Deduplicate while preserving order
    seen: set[str] = set()
    return [f for f in found if not (f in seen or seen.add(f))]  # type: ignore[func-returns-value]


# ---------------------------------------------------------------------------
# Async public API
# ---------------------------------------------------------------------------

async def build_file_index(root: str) -> list[FileEntry]:
    """Return a FileEntry list for all non-skipped files under root."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _walk_repo, root)


async def count_lines_of_code(root: str, entries: list[FileEntry]) -> int:
    """Count total lines of source code, running in executor to avoid blocking."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _count_lines_sync, root, entries)


async def detect_primary_language(entries: list[FileEntry]) -> str | None:
    """Detect the primary programming language from file extension frequency."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _detect_primary_language_sync, entries)


async def detect_frameworks(root: str, entries: list[FileEntry]) -> list[str]:
    """Detect frameworks and tooling present in the repository."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _detect_frameworks_sync, root, entries)
