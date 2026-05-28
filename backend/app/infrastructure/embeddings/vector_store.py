"""Vector store abstraction + in-memory implementation.

Abstract interface
------------------
``VectorStore`` defines the minimal contract:

* ``store``            — persist a chunk + its embedding
* ``similarity_search``— return the *top_k* most similar chunks
* ``delete``           — remove a chunk by ID
* ``clear``            — wipe the entire store
* ``size``             — number of stored vectors

In-memory implementation
-------------------------
``InMemoryVectorStore`` stores vectors in a plain Python dict and uses
pure-Python cosine similarity (no numpy required).  It is suitable for
development, testing, and small repositories.

PGVector / Pinecone / Qdrant replacement
-----------------------------------------
Create a new class that inherits ``VectorStore`` and implement the four
abstract methods.  Wire it in ``deps.py`` in place of
``InMemoryVectorStore`` — no other code needs to change.
"""
from __future__ import annotations

import math
import uuid
from abc import ABC, abstractmethod
from typing import Optional

from app.infrastructure.embeddings.models import CodeChunk, SearchResult


class VectorStore(ABC):
    """Abstract vector store interface."""

    @abstractmethod
    async def store(
        self,
        chunk: CodeChunk,
        embedding: list[float],
    ) -> None:
        """Persist *chunk* alongside its *embedding* vector."""

    @abstractmethod
    async def store_batch(
        self,
        chunks: list[CodeChunk],
        embeddings: list[list[float]],
    ) -> None:
        """
        Persist multiple chunk+embedding pairs in one call.

        Implementations should use a single bulk write where possible.
        ``len(chunks)`` must equal ``len(embeddings)``.
        """

    @abstractmethod
    async def similarity_search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        file_path_filter: Optional[str] = None,
    ) -> list[SearchResult]:
        """
        Return the *top_k* chunks most similar to *query_embedding*.

        Args:
            query_embedding:  The query vector to compare against.
            top_k:            Maximum number of results.
            file_path_filter: When provided, only consider chunks from this file.
        """

    @abstractmethod
    async def delete(self, chunk_id: uuid.UUID) -> None:
        """Remove the chunk with *chunk_id* from the store."""

    @abstractmethod
    async def clear(self) -> None:
        """Remove all stored vectors."""

    @property
    @abstractmethod
    def size(self) -> int:
        """Return the number of stored vectors."""


# ---------------------------------------------------------------------------
# In-memory implementation
# ---------------------------------------------------------------------------

class InMemoryVectorStore(VectorStore):
    """
    Thread-safe* in-memory vector store using pure-Python cosine similarity.

    Suitable for:
    * Unit and integration tests
    * Development / demo runs
    * Repositories with < ~50k chunks

    *Not truly thread-safe for concurrent writes; async code running in a
    single event loop is fine.  Add a lock if you need cross-thread safety.

    Replace with ``PGVectorStore``, ``PineconeVectorStore``, etc. for
    production deployments by implementing ``VectorStore``.
    """

    def __init__(self) -> None:
        # chunk_id → (chunk, unit-normalised embedding)
        self._store: dict[uuid.UUID, tuple[CodeChunk, list[float]]] = {}

    # ------------------------------------------------------------------
    # VectorStore interface
    # ------------------------------------------------------------------

    async def store(self, chunk: CodeChunk, embedding: list[float]) -> None:
        self._store[chunk.id] = (chunk, _unit(embedding))

    async def store_batch(
        self,
        chunks: list[CodeChunk],
        embeddings: list[list[float]],
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"chunks ({len(chunks)}) and embeddings ({len(embeddings)}) must have equal length."
            )
        for chunk, emb in zip(chunks, embeddings):
            self._store[chunk.id] = (chunk, _unit(emb))

    async def similarity_search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        file_path_filter: Optional[str] = None,
    ) -> list[SearchResult]:
        if not self._store:
            return []

        q = _unit(query_embedding)

        candidates = (
            (chunk, emb)
            for chunk, emb in self._store.values()
            if file_path_filter is None or chunk.file_path == file_path_filter
        )

        scored: list[tuple[float, CodeChunk]] = []
        for chunk, emb in candidates:
            score = _cosine_similarity(q, emb)
            scored.append((score, chunk))

        # Sort descending by score, then by chunk position for stability
        scored.sort(key=lambda x: (-x[0], x[1].file_path, x[1].chunk_index))

        return [
            SearchResult(chunk=chunk, score=max(0.0, min(1.0, score)))
            for score, chunk in scored[:top_k]
        ]

    async def delete(self, chunk_id: uuid.UUID) -> None:
        self._store.pop(chunk_id, None)

    async def clear(self) -> None:
        self._store.clear()

    @property
    def size(self) -> int:
        return len(self._store)

    # ------------------------------------------------------------------
    # Convenience helpers (not part of the abstract interface)
    # ------------------------------------------------------------------

    def get_chunks_for_file(self, file_path: str) -> list[CodeChunk]:
        """Return all stored chunks for a given file path."""
        return [c for c, _ in self._store.values() if c.file_path == file_path]


# ---------------------------------------------------------------------------
# Math helpers (pure Python, no numpy)
# ---------------------------------------------------------------------------

def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def _unit(v: list[float]) -> list[float]:
    """Return L2-normalised vector; returns unchanged if norm is 0."""
    n = _norm(v)
    return [x / n for x in v] if n > 0.0 else v


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """
    Cosine similarity between two vectors.

    Assumes both are already unit-normalised — reduces to a dot product.
    """
    return _dot(a, b)
