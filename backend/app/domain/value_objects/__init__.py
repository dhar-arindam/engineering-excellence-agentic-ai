"""Value objects for domain inputs."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, model_validator


class RepositoryTarget(BaseModel):
    """Identifies what repository/path to analyze. Exactly one field must be set."""

    repo_url: Optional[str] = None
    local_path: Optional[str] = None

    @model_validator(mode="after")
    def validate_exactly_one(self) -> "RepositoryTarget":
        if not self.repo_url and not self.local_path:
            raise ValueError("Either repo_url or local_path must be provided.")
        if self.repo_url and self.local_path:
            raise ValueError("Provide only one of repo_url or local_path, not both.")
        return self

    model_config = {"frozen": True}


class RepoMetadata(BaseModel):
    """Metadata fetched from a repository before analysis begins."""

    name: str
    default_branch: str = "main"
    primary_language: Optional[str] = None
    file_tree: list[str] = []
    readme_excerpt: Optional[str] = None
    repo_url: Optional[str] = None
    local_path: Optional[str] = None

    model_config = {"frozen": True}
