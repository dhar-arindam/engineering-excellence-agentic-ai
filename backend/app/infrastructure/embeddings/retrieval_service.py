"""Retrieval service — ties together chunker, embedding provider, and vector store.

Responsibilities
----------------
* ``index_repository``   — scan all files, chunk them, embed in batches, store
* ``index_file``         — index / re-index a single file
* ``search``             — embed a query string and return the most similar chunks
* ``remove_file``        — remove all chunks belonging to a file
* ``clear``              — wipe the entire index

Design notes
------------
* Embedding is batched to minimise API round-trips.
* All public methods are async.
* The service is stateless beyond its injected dependencies — safe to share
  as a singleton (backed by ``InMemoryVectorStore``) or instantiated per
  request (backed by an external store).
* ``index_repository`` is idempotent: calling it twice on the same path
  re-indexes all files (useful when content changes).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Sequence

from app.core.logging import get_logger
from app.infrastructure.embeddings.chunker import CodeChunker, _should_chunk
from app.infrastructure.embeddings.embedding_provider import EmbeddingProvider
from app.infrastructure.embeddings.models import CodeChunk, SearchResult
from app.infrastructure.embeddings.vector_store import VectorStore

logger = get_logger(__name__)

# Number of chunks to embed in a single API batch
_DEFAULT_BATCH_SIZE = 64


class RetrievalService:
    """
    High-level RAG retrieval service for repository source code.

    Args:
        embedding_provider: Generates embedding vectors.
        vector_store:       Persists and searches vectors.
        chunker:            Splits source files into :class:`CodeChunk` objects.
        batch_size:         Chunks per embedding API call.
    """

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
        chunker: CodeChunker | None = None,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> None:
        self._provider   = embedding_provider
        self._store      = vector_store
        self._chunker    = chunker or CodeChunker()
        self._batch_size = batch_size

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    async def index_repository(
        self,
        root_path: str,
        file_paths: Sequence[str],
    ) -> int:
        """
        Chunk, embed, and index all files in *file_paths*.

        *file_paths* are relative paths resolved against *root_path*.

        Returns the total number of chunks indexed.
        """
        logger.info("retrieval.index_start", root=root_path, files=len(file_paths))

        chunks = await self._chunker.chunk_repository(root_path, file_paths)
        if not chunks:
            logger.info("retrieval.index_empty", root=root_path)
            return 0

        total = await self._embed_and_store(chunks)
        logger.info("retrieval.index_complete", root=root_path, chunks=total)
        return total

    async def index_file(self, file_path: str, source: str | None = None) -> int:
        """
        Index (or re-index) a single file.

        If *source* is supplied the file is not read from disk.  Otherwise
        the chunker reads it directly.

        Returns the number of chunks indexed.
        """
        if not _should_chunk(file_path):
            return 0

        if source is not None:
            chunks = self._chunker.chunk_source(file_path, source)
        else:
            chunks = await self._chunker.chunk_file(file_path)

        if not chunks:
            return 0

        # Remove any previously indexed chunks for this file first
        await self.remove_file(file_path)
        return await self._embed_and_store(chunks)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        top_k: int = 5,
        file_path_filter: str | None = None,
    ) -> list[SearchResult]:
        """
        Embed *query* and return the *top_k* most similar code chunks.

        Args:
            query:            Natural language or code search query.
            top_k:            Maximum results to return.
            file_path_filter: When set, restrict results to a single file.

        Returns:
            List of :class:`SearchResult` ordered by descending similarity.
        """
        if not query.strip():
            return []

        query_embedding = await self._provider.embed(query)
        results = await self._store.similarity_search(
            query_embedding,
            top_k=top_k,
            file_path_filter=file_path_filter,
        )
        logger.info(
            "retrieval.search",
            query_len=len(query),
            top_k=top_k,
            results=len(results),
        )
        return results

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    async def remove_file(self, file_path: str) -> None:
        """Remove all indexed chunks for *file_path*."""
        if isinstance(self._store, _SupportsFileRemoval):
            await self._store.remove_file_chunks(file_path)
        else:
            # Fallback: retrieve-then-delete for generic VectorStore impls
            results = await self._store.similarity_search(
                [0.0] * self._provider.dimensions,
                top_k=10_000,
                file_path_filter=file_path,
            )
            for r in results:
                await self._store.delete(r.chunk.id)

    async def clear(self) -> None:
        """Clear the entire vector index."""
        await self._store.clear()

    @property
    def indexed_count(self) -> int:
        """Number of chunks currently in the store."""
        return self._store.size

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _embed_and_store(self, chunks: list[CodeChunk]) -> int:
        """Embed *chunks* in batches and store them.  Returns count stored."""
        total = 0
        for batch_start in range(0, len(chunks), self._batch_size):
            batch = chunks[batch_start : batch_start + self._batch_size]
            texts = [c.content for c in batch]

            try:
                embeddings = await self._provider.embed_batch(texts)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "retrieval.embed_batch_failed",
                    batch_start=batch_start,
                    batch_size=len(batch),
                    error=str(exc),
                )
                continue

            await self._store.store_batch(batch, embeddings)
            total += len(batch)

        return total


class _SupportsFileRemoval:
    """Structural protocol — duck-typed check for stores that expose bulk file removal."""
    async def remove_file_chunks(self, file_path: str) -> None: ...
