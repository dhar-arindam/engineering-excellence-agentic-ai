"""Pydantic models for code intelligence analysis results.

All models are frozen value objects — produced by analysis, never mutated.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class FileComplexity(BaseModel):
    """Cyclomatic complexity estimate for a single file."""

    path: str
    score: int = Field(ge=1, description="McCabe complexity (base=1 + decision points)")
    function_count: int = 0
    class_count: int = 0

    model_config = {"frozen": True}


class CodeSmell(BaseModel):
    """A single code quality issue detected via static analysis."""

    file_path: str
    smell_type: str  # "long_function" | "too_many_params" | "deep_nesting" | "god_class" | "long_file"
    detail: str
    line_number: int = 0

    model_config = {"frozen": True}


class CodeMetrics(BaseModel):
    """Aggregate code quality metrics for a repository."""

    total_files: int
    total_lines: int
    average_file_size: float = Field(description="Mean lines per file")
    largest_files: list[str] = Field(description="Top-10 files by line count, descending")
    files_over_500_lines: list[str]
    cyclomatic_complexity_estimate: dict[str, int] = Field(
        description="file_path → complexity score (McCabe)"
    )
    avg_complexity: float = Field(description="Mean complexity across all analysed Python files")
    high_complexity_files: list[str] = Field(
        description="Files with complexity score > 10"
    )

    model_config = {"frozen": True}


class ImportEdge(BaseModel):
    """A directed import dependency between two modules."""

    source: str  # relative module path, e.g. "app/core/config.py"
    target: str  # imported module identifier
    import_type: str  # "internal" | "stdlib" | "external"

    model_config = {"frozen": True}


class DependencyGraph(BaseModel):
    """Import dependency graph for the repository."""

    nodes: list[str] = Field(description="All module nodes (file paths for internal modules)")
    edges: list[tuple[str, str]] = Field(description="(source_path, target_module) pairs")
    internal_edges: list[tuple[str, str]] = Field(
        description="Edges where both ends are project-internal modules"
    )
    external_dependencies: list[str] = Field(
        description="Unique third-party package names imported"
    )
    stdlib_dependencies: list[str] = Field(
        description="Unique stdlib module names imported"
    )

    model_config = {"frozen": True}


class CodeAnalysisResult(BaseModel):
    """Top-level result produced by RealCodeIntelligenceService."""

    metrics: CodeMetrics
    dependency_graph: DependencyGraph
    code_smells: list[CodeSmell]
    analysed_files: int
    parse_errors: list[str] = Field(
        description="Files that could not be parsed (syntax errors, encoding issues)"
    )

    model_config = {"frozen": True}
