"""Tests for the vector embedding layer."""
from __future__ import annotations

import math
import textwrap
import uuid
from pathlib import Path

import pytest

from app.infrastructure.embeddings.chunker import (
    CodeChunker,
    _chunk_by_lines,
    _chunk_python,
    _should_chunk,
    detect_language,
)
from app.infrastructure.embeddings.embedding_provider import (
    StubEmbeddingProvider,
    _hash_to_unit_vector,
    _l2_normalise,
)
from app.infrastructure.embeddings.models import CodeChunk, SearchResult
from app.infrastructure.embeddings.retrieval_service import RetrievalService
from app.infrastructure.embeddings.vector_store import (
    InMemoryVectorStore,
    _cosine_similarity,
    _unit,
)


# ===========================================================================
# models.py
# ===========================================================================

class TestCodeChunk:
    def test_line_count(self):
        c = CodeChunk(file_path="f.py", start_line=1, end_line=10, content="x", language="python")
        assert c.line_count == 10

    def test_token_estimate_non_zero(self):
        c = CodeChunk(file_path="f.py", start_line=1, end_line=1,
                      content="hello world", language="python")
        assert c.token_estimate >= 1

    def test_default_uuid_assigned(self):
        c = CodeChunk(file_path="f.py", start_line=1, end_line=1, content="x", language="python")
        assert isinstance(c.id, uuid.UUID)

    def test_frozen(self):
        c = CodeChunk(file_path="f.py", start_line=1, end_line=1, content="x", language="python")
        with pytest.raises(Exception):
            c.content = "y"  # type: ignore[misc]

    def test_search_result_score_range(self):
        chunk = CodeChunk(file_path="f.py", start_line=1, end_line=1, content="x", language="python")
        sr = SearchResult(chunk=chunk, score=0.87)
        assert 0.0 <= sr.score <= 1.0


# ===========================================================================
# detect_language / _should_chunk
# ===========================================================================

class TestDetectLanguage:
    def test_python(self):
        assert detect_language("app/main.py") == "python"

    def test_typescript(self):
        assert detect_language("src/index.ts") == "typescript"

    def test_unknown(self):
        assert detect_language("README") == "unknown"

    def test_yaml(self):
        assert detect_language(".github/workflows/ci.yml") == "yaml"


class TestShouldChunk:
    def test_python_ok(self):
        assert _should_chunk("app/main.py") is True

    def test_lock_file_skipped(self):
        assert _should_chunk("package-lock.json") is False

    def test_png_skipped(self):
        assert _should_chunk("logo.png") is False

    def test_poetry_lock_skipped(self):
        assert _should_chunk("poetry.lock") is False


# ===========================================================================
# _chunk_by_lines
# ===========================================================================

class TestChunkByLines:
    def test_single_chunk_short_file(self):
        source = "\n".join(f"line {i}" for i in range(10))
        chunks = _chunk_by_lines("f.py", source, "python", chunk_lines=100)
        assert len(chunks) == 1
        assert chunks[0].start_line == 1
        assert chunks[0].end_line == 10

    def test_multiple_chunks_long_file(self):
        source = "\n".join(f"line {i}" for i in range(200))
        chunks = _chunk_by_lines("f.py", source, "python", chunk_lines=100, overlap_lines=0)
        assert len(chunks) == 2

    def test_overlap_means_fewer_gaps(self):
        source = "\n".join(f"line {i}" for i in range(150))
        chunks_no_ov = _chunk_by_lines("f.py", source, "python", chunk_lines=100, overlap_lines=0)
        chunks_ov    = _chunk_by_lines("f.py", source, "python", chunk_lines=100, overlap_lines=20)
        assert len(chunks_ov) >= len(chunks_no_ov)

    def test_empty_file_returns_empty(self):
        assert _chunk_by_lines("f.py", "", "python") == []

    def test_language_preserved(self):
        source = "\n".join(f"x {i}" for i in range(5))
        chunks = _chunk_by_lines("f.go", source, "go")
        assert all(c.language == "go" for c in chunks)

    def test_chunk_indices_sequential(self):
        source = "\n".join(f"line {i}" for i in range(200))
        chunks = _chunk_by_lines("f.py", source, "python", chunk_lines=50, overlap_lines=0)
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


# ===========================================================================
# _chunk_python (AST)
# ===========================================================================

SIMPLE_PY = textwrap.dedent("""\
    import os

    class Foo:
        def bar(self):
            pass

    def baz():
        return 42
""")

SYNTAX_ERROR_PY = "def broken(\n    x\n"  # missing closing paren


class TestChunkPython:
    def test_extracts_class_and_function(self):
        chunks = _chunk_python("app.py", SIMPLE_PY)
        names = {c.symbol_name for c in chunks}
        assert "Foo" in names
        assert "baz" in names

    def test_preamble_captured(self):
        chunks = _chunk_python("app.py", SIMPLE_PY)
        assert any(c.symbol_name == "<module_preamble>" for c in chunks)

    def test_syntax_error_falls_back_to_lines(self):
        chunks = _chunk_python("app.py", SYNTAX_ERROR_PY)
        assert len(chunks) >= 1
        # fallback chunks have no symbol_name
        assert all(c.symbol_name is None for c in chunks)

    def test_file_path_preserved(self):
        chunks = _chunk_python("my/module.py", SIMPLE_PY)
        assert all(c.file_path == "my/module.py" for c in chunks)

    def test_language_is_python(self):
        chunks = _chunk_python("m.py", SIMPLE_PY)
        assert all(c.language == "python" for c in chunks)

    def test_no_empty_content_chunks(self):
        chunks = _chunk_python("m.py", SIMPLE_PY)
        assert all(c.content.strip() for c in chunks)

    def test_empty_source_fallback(self):
        chunks = _chunk_python("m.py", "")
        assert chunks == []

    def test_module_without_defs_falls_back(self):
        source = "x = 1\ny = 2\n"
        chunks = _chunk_python("script.py", source)
        assert len(chunks) >= 1


# ===========================================================================
# CodeChunker (async facade)
# ===========================================================================

class TestCodeChunker:
    def test_chunk_source_python(self):
        chunker = CodeChunker()
        chunks = chunker.chunk_source("app.py", SIMPLE_PY)
        assert len(chunks) > 0

    def test_chunk_source_unknown_falls_back(self):
        chunker = CodeChunker()
        source = "\n".join(f"line {i}" for i in range(10))
        chunks = chunker.chunk_source("data.rb", source)
        assert len(chunks) >= 1

    @pytest.mark.asyncio
    async def test_chunk_file_reads_disk(self, tmp_path: Path):
        f = tmp_path / "mod.py"
        f.write_text(SIMPLE_PY, encoding="utf-8")
        chunker = CodeChunker()
        chunks = await chunker.chunk_file(str(f))
        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_chunk_file_missing_returns_empty(self):
        chunker = CodeChunker()
        chunks = await chunker.chunk_file("/nonexistent/file.py")
        assert chunks == []

    @pytest.mark.asyncio
    async def test_chunk_repository(self, tmp_path: Path):
        (tmp_path / "a.py").write_text(SIMPLE_PY, encoding="utf-8")
        (tmp_path / "b.py").write_text("x = 1\n", encoding="utf-8")
        chunker = CodeChunker()
        chunks = await chunker.chunk_repository(str(tmp_path), ["a.py", "b.py"])
        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_chunk_repository_skips_locks(self, tmp_path: Path):
        (tmp_path / "package-lock.json").write_text('{"version":1}', encoding="utf-8")
        chunker = CodeChunker()
        chunks = await chunker.chunk_repository(str(tmp_path), ["package-lock.json"])
        assert chunks == []


# ===========================================================================
# StubEmbeddingProvider
# ===========================================================================

class TestStubEmbeddingProvider:
    @pytest.mark.asyncio
    async def test_embed_returns_correct_dim(self):
        provider = StubEmbeddingProvider(dimensions=8)
        vec = await provider.embed("hello")
        assert len(vec) == 8

    @pytest.mark.asyncio
    async def test_embed_is_unit_length(self):
        provider = StubEmbeddingProvider(dimensions=16)
        vec = await provider.embed("test input")
        norm = math.sqrt(sum(x * x for x in vec))
        assert abs(norm - 1.0) < 1e-6

    @pytest.mark.asyncio
    async def test_embed_is_deterministic(self):
        provider = StubEmbeddingProvider(dimensions=32)
        v1 = await provider.embed("same text")
        v2 = await provider.embed("same text")
        assert v1 == v2

    @pytest.mark.asyncio
    async def test_different_texts_differ(self):
        provider = StubEmbeddingProvider(dimensions=32)
        v1 = await provider.embed("apple")
        v2 = await provider.embed("banana")
        assert v1 != v2

    @pytest.mark.asyncio
    async def test_embed_batch(self):
        provider = StubEmbeddingProvider(dimensions=8)
        vecs = await provider.embed_batch(["a", "b", "c"])
        assert len(vecs) == 3
        assert all(len(v) == 8 for v in vecs)

    @pytest.mark.asyncio
    async def test_embed_batch_empty(self):
        provider = StubEmbeddingProvider(dimensions=8)
        assert await provider.embed_batch([]) == []

    def test_dimensions_property(self):
        p = StubEmbeddingProvider(dimensions=512)
        assert p.dimensions == 512


class TestL2Normalise:
    def test_unit_vector_unchanged(self):
        v = [1.0, 0.0, 0.0]
        assert _l2_normalise(v) == [1.0, 0.0, 0.0]

    def test_zero_vector_unchanged(self):
        assert _l2_normalise([0.0, 0.0]) == [0.0, 0.0]

    def test_normalised_is_unit(self):
        v = [3.0, 4.0]
        n = _l2_normalise(v)
        assert abs(math.sqrt(n[0] ** 2 + n[1] ** 2) - 1.0) < 1e-9


# ===========================================================================
# InMemoryVectorStore
# ===========================================================================

def _make_chunk(file_path: str = "f.py", idx: int = 0) -> CodeChunk:
    return CodeChunk(
        file_path=file_path,
        start_line=idx * 10 + 1,
        end_line=idx * 10 + 10,
        content=f"content {idx}",
        language="python",
        chunk_index=idx,
    )


class TestInMemoryVectorStore:
    @pytest.mark.asyncio
    async def test_store_and_size(self):
        store = InMemoryVectorStore()
        await store.store(_make_chunk(), [0.1] * 8)
        assert store.size == 1

    @pytest.mark.asyncio
    async def test_store_batch(self):
        store = InMemoryVectorStore()
        chunks = [_make_chunk(idx=i) for i in range(3)]
        vecs   = [[float(i)] * 8 for i in range(3)]
        await store.store_batch(chunks, vecs)
        assert store.size == 3

    @pytest.mark.asyncio
    async def test_store_batch_length_mismatch(self):
        store = InMemoryVectorStore()
        with pytest.raises(ValueError):
            await store.store_batch([_make_chunk()], [[0.1] * 8, [0.2] * 8])

    @pytest.mark.asyncio
    async def test_similarity_search_returns_top_k(self):
        store = InMemoryVectorStore()
        for i in range(5):
            vec = [float(i)] + [0.0] * 7
            await store.store(_make_chunk(idx=i), vec)
        query = [4.0] + [0.0] * 7
        results = await store.similarity_search(query, top_k=2)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_similarity_search_empty_store(self):
        store = InMemoryVectorStore()
        results = await store.similarity_search([1.0, 0.0], top_k=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_most_similar_is_first(self):
        store = InMemoryVectorStore()
        # chunk_a is aligned with query; chunk_b is orthogonal
        chunk_a = _make_chunk(idx=0)
        chunk_b = _make_chunk(idx=1)
        await store.store(chunk_a, [1.0, 0.0])
        await store.store(chunk_b, [0.0, 1.0])
        results = await store.similarity_search([1.0, 0.0], top_k=2)
        assert results[0].chunk.id == chunk_a.id

    @pytest.mark.asyncio
    async def test_scores_in_range(self):
        store = InMemoryVectorStore()
        await store.store(_make_chunk(), [0.6, 0.8])
        results = await store.similarity_search([0.6, 0.8], top_k=1)
        assert 0.0 <= results[0].score <= 1.0

    @pytest.mark.asyncio
    async def test_file_path_filter(self):
        store = InMemoryVectorStore()
        await store.store(_make_chunk("a.py", 0), [1.0, 0.0])
        await store.store(_make_chunk("b.py", 1), [1.0, 0.0])
        results = await store.similarity_search([1.0, 0.0], top_k=5, file_path_filter="a.py")
        assert all(r.chunk.file_path == "a.py" for r in results)

    @pytest.mark.asyncio
    async def test_delete(self):
        store = InMemoryVectorStore()
        chunk = _make_chunk()
        await store.store(chunk, [1.0, 0.0])
        await store.delete(chunk.id)
        assert store.size == 0

    @pytest.mark.asyncio
    async def test_clear(self):
        store = InMemoryVectorStore()
        for i in range(3):
            await store.store(_make_chunk(idx=i), [float(i), 0.0])
        await store.clear()
        assert store.size == 0

    def test_get_chunks_for_file(self):
        store = InMemoryVectorStore()
        # Sync helper — use run to drive async
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            store.store(_make_chunk("x.py", 0), [1.0, 0.0])
        )
        asyncio.get_event_loop().run_until_complete(
            store.store(_make_chunk("y.py", 1), [0.0, 1.0])
        )
        assert len(store.get_chunks_for_file("x.py")) == 1


class TestCosineSimilarity:
    def test_identical_unit_vectors(self):
        v = [0.6, 0.8]
        assert abs(_cosine_similarity(_unit(v), _unit(v)) - 1.0) < 1e-9

    def test_orthogonal_vectors(self):
        assert abs(_cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-9

    def test_opposite_vectors(self):
        assert _cosine_similarity([1.0, 0.0], [-1.0, 0.0]) < 0


# ===========================================================================
# RetrievalService (integration — StubEmbeddingProvider + InMemoryVectorStore)
# ===========================================================================

class TestRetrievalService:
    def _make_service(self, dims: int = 8) -> RetrievalService:
        return RetrievalService(
            embedding_provider=StubEmbeddingProvider(dimensions=dims),
            vector_store=InMemoryVectorStore(),
            chunker=CodeChunker(),
        )

    @pytest.mark.asyncio
    async def test_index_and_search(self, tmp_path: Path):
        svc = self._make_service()
        f = tmp_path / "mod.py"
        f.write_text(SIMPLE_PY, encoding="utf-8")
        count = await svc.index_file(str(f))
        assert count > 0
        results = await svc.search("class Foo")
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_search_returns_search_results(self, tmp_path: Path):
        svc = self._make_service()
        f = tmp_path / "m.py"
        f.write_text("def hello(): pass\n", encoding="utf-8")
        await svc.index_file(str(f))
        results = await svc.search("hello")
        assert all(isinstance(r, SearchResult) for r in results)

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, tmp_path: Path):
        svc = self._make_service()
        f = tmp_path / "m.py"
        f.write_text("x = 1\n", encoding="utf-8")
        await svc.index_file(str(f))
        assert await svc.search("") == []

    @pytest.mark.asyncio
    async def test_index_count_matches(self, tmp_path: Path):
        svc = self._make_service()
        f = tmp_path / "m.py"
        f.write_text(SIMPLE_PY, encoding="utf-8")
        count = await svc.index_file(str(f))
        assert svc.indexed_count == count

    @pytest.mark.asyncio
    async def test_re_index_does_not_duplicate(self, tmp_path: Path):
        svc = self._make_service()
        f = tmp_path / "m.py"
        f.write_text("def foo(): pass\n", encoding="utf-8")
        await svc.index_file(str(f))
        count_before = svc.indexed_count
        await svc.index_file(str(f))   # re-index same file
        assert svc.indexed_count == count_before

    @pytest.mark.asyncio
    async def test_clear_empties_index(self, tmp_path: Path):
        svc = self._make_service()
        f = tmp_path / "m.py"
        f.write_text("x = 1\n", encoding="utf-8")
        await svc.index_file(str(f))
        await svc.clear()
        assert svc.indexed_count == 0

    @pytest.mark.asyncio
    async def test_index_repository(self, tmp_path: Path):
        svc = self._make_service()
        (tmp_path / "a.py").write_text("def a(): pass\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("def b(): pass\n", encoding="utf-8")
        total = await svc.index_repository(str(tmp_path), ["a.py", "b.py"])
        assert total >= 2

    @pytest.mark.asyncio
    async def test_top_k_respected(self, tmp_path: Path):
        svc = self._make_service()
        # Index many chunks
        source = "\n".join(f"def func_{i}(): pass" for i in range(20))
        f = tmp_path / "m.py"
        f.write_text(source, encoding="utf-8")
        await svc.index_file(str(f))
        results = await svc.search("func", top_k=3)
        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_index_with_source_string(self):
        svc = self._make_service()
        count = await svc.index_file("virtual/mod.py", source=SIMPLE_PY)
        assert count > 0

    @pytest.mark.asyncio
    async def test_skip_lock_file(self):
        svc = self._make_service()
        count = await svc.index_file("package-lock.json", source='{"x":1}')
        assert count == 0
