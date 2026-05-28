"""Unit tests for LocalRepositoryLoader."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.exceptions import RepositoryAccessError
from app.infrastructure.repository_ingestion.local_loader import LocalRepositoryLoader
from app.infrastructure.repository_ingestion.models import RepositoryMetadata


@pytest.fixture
def python_repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main():\n    pass\n")
    (tmp_path / "src" / "utils.py").write_text("def helper():\n    return 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("def test_main():\n    assert True\n")
    (tmp_path / "requirements.txt").write_text("pytest\n")
    (tmp_path / "Makefile").write_text("test:\n\tpytest\n")
    return tmp_path


class TestLocalRepositoryLoader:
    @pytest.mark.asyncio
    async def test_returns_repository_metadata(self, python_repo):
        loader = LocalRepositoryLoader()
        meta = await loader.load(str(python_repo))
        assert isinstance(meta, RepositoryMetadata)

    @pytest.mark.asyncio
    async def test_name_is_directory_basename(self, python_repo):
        loader = LocalRepositoryLoader()
        meta = await loader.load(str(python_repo))
        assert meta.name == python_repo.name

    @pytest.mark.asyncio
    async def test_root_path_is_absolute(self, python_repo):
        loader = LocalRepositoryLoader()
        meta = await loader.load(str(python_repo))
        assert Path(meta.root_path).is_absolute()

    @pytest.mark.asyncio
    async def test_detects_python_language(self, python_repo):
        loader = LocalRepositoryLoader()
        meta = await loader.load(str(python_repo))
        assert meta.primary_language == "Python"

    @pytest.mark.asyncio
    async def test_total_files_positive(self, python_repo):
        loader = LocalRepositoryLoader()
        meta = await loader.load(str(python_repo))
        assert meta.total_files > 0

    @pytest.mark.asyncio
    async def test_total_lines_positive(self, python_repo):
        loader = LocalRepositoryLoader()
        meta = await loader.load(str(python_repo))
        assert meta.total_lines > 0

    @pytest.mark.asyncio
    async def test_file_index_populated(self, python_repo):
        loader = LocalRepositoryLoader()
        meta = await loader.load(str(python_repo))
        assert len(meta.file_index) == meta.total_files

    @pytest.mark.asyncio
    async def test_detects_makefile(self, python_repo):
        loader = LocalRepositoryLoader()
        meta = await loader.load(str(python_repo))
        assert "Makefile" in meta.detected_frameworks

    @pytest.mark.asyncio
    async def test_raises_on_nonexistent_path(self):
        loader = LocalRepositoryLoader()
        with pytest.raises(RepositoryAccessError):
            await loader.load("/nonexistent/path/xyz")

    @pytest.mark.asyncio
    async def test_raises_on_file_not_directory(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hello")
        loader = LocalRepositoryLoader()
        with pytest.raises(RepositoryAccessError):
            await loader.load(str(f))

    @pytest.mark.asyncio
    async def test_repo_id_is_unique_per_call(self, python_repo):
        loader = LocalRepositoryLoader()
        meta1 = await loader.load(str(python_repo))
        meta2 = await loader.load(str(python_repo))
        assert meta1.repo_id != meta2.repo_id
