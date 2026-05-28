"""Vector embedding layer — public API."""
from app.infrastructure.embeddings.chunker import CodeChunker, detect_language
from app.infrastructure.embeddings.embedding_provider import (
    EmbeddingProvider,
    OpenAIEmbeddingProvider,
    StubEmbeddingProvider,
)
from app.infrastructure.embeddings.models import CodeChunk, SearchResult
from app.infrastructure.embeddings.retrieval_service import RetrievalService
from app.infrastructure.embeddings.vector_store import InMemoryVectorStore, VectorStore

__all__ = [
    "CodeChunk",
    "SearchResult",
    "CodeChunker",
    "detect_language",
    "EmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "StubEmbeddingProvider",
    "VectorStore",
    "InMemoryVectorStore",
    "RetrievalService",
]
