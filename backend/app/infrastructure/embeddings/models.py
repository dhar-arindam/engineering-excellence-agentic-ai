"""Domain models for the vector embedding layer."""
from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field


class CodeChunk(BaseModel):
    """A semantically meaningful slice of source code ready for embedding."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    file_path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    content: str
    language: str
    # Optional metadata carried through to search results
    symbol_name: Optional[str] = None  # class / function name when AST-extracted
    chunk_index: int = 0               # position within file (0-based)

    model_config = {"frozen": True}

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1

    @property
    def token_estimate(self) -> int:
        """Very rough token count (chars / 4) — useful for prompt budget checks."""
        return max(1, len(self.content) // 4)


class SearchResult(BaseModel):
    """A code chunk returned from a vector similarity search."""

    chunk: CodeChunk
    score: float = Field(ge=0.0, le=1.0, description="Cosine similarity [0, 1].")

    model_config = {"frozen": True}
