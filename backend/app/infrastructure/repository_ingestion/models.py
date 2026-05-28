"""Pydantic models for the repository ingestion layer.

These are infrastructure-layer models — richer than the domain RepoMetadata
value object, and NOT used by the domain or application layers directly.
"""
from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field


class FileEntry(BaseModel):
    """A single file entry in the repository index."""

    path: str
    size: int
    extension: str

    model_config = {"frozen": True}


class RepositoryMetadata(BaseModel):
    """Full structured metadata produced by a RepositoryLoader."""

    repo_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: str
    root_path: str
    primary_language: Optional[str] = None
    total_files: int = 0
    total_lines: int = 0
    detected_frameworks: list[str] = Field(default_factory=list)
    file_index: list[FileEntry] = Field(default_factory=list)

    model_config = {"frozen": True}
