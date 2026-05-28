"""Embedding provider abstraction.

Abstract base class + two implementations:

* ``OpenAIEmbeddingProvider``  — calls the OpenAI Embeddings API (or any
  OpenAI-compatible endpoint).  Model is configurable; defaults to
  ``text-embedding-3-small`` (1536-dim, fast, cheap).

* ``StubEmbeddingProvider``    — deterministic fake embeddings derived from a
  hash of the input text.  Dimension is configurable (default 1536 to match
  OpenAI).  Used in tests and offline development — no API key required.
"""
from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod
from typing import Sequence


class EmbeddingProvider(ABC):
    """Abstract interface for embedding generation."""

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Return a single embedding vector for *text*."""

    @abstractmethod
    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """
        Return an embedding vector for each item in *texts*.

        Implementations should prefer a single batched API call over
        calling :meth:`embed` in a loop.
        """

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Dimensionality of the produced embedding vectors."""


# ---------------------------------------------------------------------------
# OpenAI implementation
# ---------------------------------------------------------------------------

class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    Embedding provider backed by the OpenAI Embeddings API.

    Works with any OpenAI-compatible endpoint (Azure OpenAI, LiteLLM, etc.)
    by passing a custom ``base_url`` and ``api_key``.

    Args:
        model:    Embedding model name.  Defaults to ``text-embedding-3-small``.
        api_key:  OpenAI API key.  Falls back to the ``OPENAI_API_KEY`` env var.
        base_url: Optional custom endpoint base URL.
        dimensions: Override output dimensions (only supported by v3 models).
    """

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        base_url: str | None = None,
        dimensions: int = 1536,
    ) -> None:
        # Import lazily so tests that don't use this provider don't need a key
        from openai import AsyncOpenAI  # noqa: PLC0415

        client_kwargs: dict = {}
        if api_key:
            client_kwargs["api_key"] = api_key
        if base_url:
            client_kwargs["base_url"] = base_url

        self._client     = AsyncOpenAI(**client_kwargs)
        self._model      = model
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(
            model=self._model,
            input=text,
            dimensions=self._dimensions,
        )
        return response.data[0].embedding

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self._client.embeddings.create(
            model=self._model,
            input=list(texts),
            dimensions=self._dimensions,
        )
        # API returns items ordered by index
        ordered = sorted(response.data, key=lambda d: d.index)
        return [item.embedding for item in ordered]


# ---------------------------------------------------------------------------
# Stub / test implementation
# ---------------------------------------------------------------------------

class StubEmbeddingProvider(EmbeddingProvider):
    """
    Deterministic fake embedding provider for tests and offline development.

    Produces unit-normalised vectors derived from the SHA-256 hash of *text*.
    The vectors are not semantically meaningful but are consistent — the same
    input always produces the same vector, which is sufficient for testing
    similarity search logic.

    Args:
        dimensions: Vector dimensionality.  Defaults to 1536 (same as
                    ``text-embedding-3-small``) so the stub is a drop-in
                    replacement for schema purposes.
    """

    def __init__(self, dimensions: int = 1536) -> None:
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, text: str) -> list[float]:
        return _hash_to_unit_vector(text, self._dimensions)

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        return [_hash_to_unit_vector(t, self._dimensions) for t in texts]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _hash_to_unit_vector(text: str, dimensions: int) -> list[float]:
    """
    Derive a deterministic unit vector from *text* using SHA-256.

    The hash bytes are consumed in 4-byte windows to produce float values,
    cycling the hash digest as needed.  The result is L2-normalised.
    """
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).digest()
    # Extend digest to cover all requested dimensions
    reps   = math.ceil(dimensions * 4 / len(digest))
    raw    = (digest * reps)[: dimensions * 4]

    vec: list[float] = []
    for i in range(dimensions):
        offset = i * 4
        # Interpret 4 bytes as a signed integer, map to [-1, 1]
        val = int.from_bytes(raw[offset : offset + 4], "big", signed=True)
        vec.append(val / (2**31))

    return _l2_normalise(vec)


def _l2_normalise(vec: list[float]) -> list[float]:
    """Return the L2-normalised version of *vec*.  Returns zeros if norm is 0."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return vec
    return [x / norm for x in vec]
