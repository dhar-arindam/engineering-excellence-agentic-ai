"""Unit tests for scanner utilities."""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from app.infrastructure.repository_ingestion.scanner import (
    _detect_frameworks_sync,
    _detect_primary_language_sync,
    _walk_repo,
    build_file_index,
    count_lines_of_code,
    detect_frameworks,
    detect_primary_language,
)


# ---------------------------------------------------------------------------
# Fixtures — build a small temp repo tree on disk
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    """Create a minimal Python/FastAPI project layout for scanner tests."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text(
        textwrap.dedent("""\
        from fastapi import FastAPI
        app = FastAPI()

        @app.get("/")
        async def root():
            return {"status": "ok"}
        """)
    )
    (tmp_path / "app" / "service.py").write_text("def do_thing():\n    pass\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "conftest.py").write_text("import pytest\n")
    (tmp_path / "tests" / "test_main.py").write_text(
        "def test_root():\n    assert True\n"
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "sample"\nversion = "0.1.0"\n'
    )
    (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn\n")
    (tmp_path / "Dockerfile").write_text("FROM python:3.11-slim\n")
    (tmp_path / "docker-compose.yml").write_text("version: '3'\n")
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "workflows").mkdir()
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("on: push\n")

    # Add a binary file that should be skipped
    (tmp_path / "app" / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    # Add a node_modules-like dir that should be skipped
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lodash.js").write_text("// lodash\n")

    return tmp_path


# ---------------------------------------------------------------------------
# _walk_repo / build_file_index
# ---------------------------------------------------------------------------

class TestBuildFileIndex:
    @pytest.mark.asyncio
    async def test_returns_file_entries(self, sample_repo):
        entries = await build_file_index(str(sample_repo))
        paths = [e.path.replace("\\", "/") for e in entries]
        assert "app/main.py" in paths
        assert "app/service.py" in paths
        assert "tests/conftest.py" in paths

    @pytest.mark.asyncio
    async def test_skips_node_modules(self, sample_repo):
        entries = await build_file_index(str(sample_repo))
        paths = [e.path.replace("\\", "/") for e in entries]
        assert not any("node_modules" in p for p in paths)

    @pytest.mark.asyncio
    async def test_includes_binary_in_index(self, sample_repo):
        """Binary files appear in the index (with .png extension) but are skipped for LOC."""
        entries = await build_file_index(str(sample_repo))
        extensions = [e.extension for e in entries]
        assert ".png" in extensions

    @pytest.mark.asyncio
    async def test_entry_has_correct_size(self, sample_repo):
        entries = await build_file_index(str(sample_repo))
        py_entries = [e for e in entries if e.extension == ".py"]
        for e in py_entries:
            assert e.size > 0


# ---------------------------------------------------------------------------
# count_lines_of_code
# ---------------------------------------------------------------------------

class TestCountLinesOfCode:
    @pytest.mark.asyncio
    async def test_counts_python_lines(self, sample_repo):
        entries = await build_file_index(str(sample_repo))
        total = await count_lines_of_code(str(sample_repo), entries)
        assert total > 0

    @pytest.mark.asyncio
    async def test_skips_binary_files(self, sample_repo):
        entries = await build_file_index(str(sample_repo))
        # Only PNG is binary — lines without it should equal total minus any PNG lines
        binary_entries = [e for e in entries if e.extension == ".png"]
        source_entries = [e for e in entries if e.extension != ".png"]
        total = await count_lines_of_code(str(sample_repo), entries)
        source_only = await count_lines_of_code(str(sample_repo), source_entries)
        assert total == source_only  # PNG contributes 0 lines


# ---------------------------------------------------------------------------
# detect_primary_language
# ---------------------------------------------------------------------------

class TestDetectPrimaryLanguage:
    @pytest.mark.asyncio
    async def test_detects_python(self, sample_repo):
        entries = await build_file_index(str(sample_repo))
        lang = await detect_primary_language(entries)
        assert lang == "Python"

    def test_returns_none_for_empty(self):
        assert _detect_primary_language_sync([]) is None

    def test_ignores_config_only_extensions(self, tmp_path):
        # Only YAML files — should return None (YAML excluded from primary language)
        (tmp_path / "a.yml").write_text("key: val\n")
        entries = _walk_repo(str(tmp_path))
        result = _detect_primary_language_sync(entries)
        assert result is None


# ---------------------------------------------------------------------------
# detect_frameworks
# ---------------------------------------------------------------------------

class TestDetectFrameworks:
    @pytest.mark.asyncio
    async def test_detects_docker(self, sample_repo):
        entries = await build_file_index(str(sample_repo))
        frameworks = await detect_frameworks(str(sample_repo), entries)
        assert "Docker" in frameworks

    @pytest.mark.asyncio
    async def test_detects_github_actions(self, sample_repo):
        entries = await build_file_index(str(sample_repo))
        frameworks = await detect_frameworks(str(sample_repo), entries)
        assert "GitHub Actions" in frameworks

    @pytest.mark.asyncio
    async def test_detects_poetry(self, sample_repo):
        entries = await build_file_index(str(sample_repo))
        frameworks = await detect_frameworks(str(sample_repo), entries)
        assert "Poetry" in frameworks

    @pytest.mark.asyncio
    async def test_detects_pip(self, sample_repo):
        entries = await build_file_index(str(sample_repo))
        frameworks = await detect_frameworks(str(sample_repo), entries)
        assert "pip" in frameworks

    @pytest.mark.asyncio
    async def test_detects_pytest(self, sample_repo):
        entries = await build_file_index(str(sample_repo))
        frameworks = await detect_frameworks(str(sample_repo), entries)
        assert "pytest" in frameworks

    @pytest.mark.asyncio
    async def test_no_duplicates(self, sample_repo):
        entries = await build_file_index(str(sample_repo))
        frameworks = await detect_frameworks(str(sample_repo), entries)
        assert len(frameworks) == len(set(frameworks))

    def test_empty_repo_returns_empty_list(self, tmp_path):
        result = _detect_frameworks_sync(str(tmp_path), [])
        assert result == []
