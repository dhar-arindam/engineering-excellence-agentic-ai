"""Repository ingestion infrastructure package."""
from app.infrastructure.repository_ingestion.base import RepositoryLoader
from app.infrastructure.repository_ingestion.github_loader import GitHubRepositoryLoader
from app.infrastructure.repository_ingestion.local_loader import LocalRepositoryLoader
from app.infrastructure.repository_ingestion.models import FileEntry, RepositoryMetadata
from app.infrastructure.repository_ingestion.scanner import (
    build_file_index,
    count_lines_of_code,
    detect_frameworks,
    detect_primary_language,
)

__all__ = [
    "RepositoryLoader",
    "LocalRepositoryLoader",
    "GitHubRepositoryLoader",
    "RepositoryMetadata",
    "FileEntry",
    "build_file_index",
    "count_lines_of_code",
    "detect_frameworks",
    "detect_primary_language",
]
