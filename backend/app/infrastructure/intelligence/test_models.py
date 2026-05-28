"""Pydantic models for test intelligence analysis results.

All models are frozen value objects — produced by analysis, never mutated.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class TestFile(BaseModel):
    """Analysis results for a single test file."""

    path: str
    test_cases: list[str] = Field(description="Names of all test functions/methods found")
    assertion_count: int = Field(ge=0, description="Total assert statements + assertX calls")
    mock_count: int = Field(ge=0, description="Number of mock/patch usages detected")
    framework: str = Field(description="'pytest' | 'unittest' | 'unknown'")

    model_config = {"frozen": True}


class TestMetrics(BaseModel):
    """Aggregate test quality metrics for a repository."""

    total_test_files: int = Field(ge=0)
    total_test_cases: int = Field(ge=0)
    test_files: list[str] = Field(description="Relative paths to all detected test files")
    files_without_tests: list[str] = Field(
        description="Source files that have no corresponding test file"
    )
    coverage_percentage: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Line coverage % from coverage.xml, or None if not available",
    )
    assertion_density: dict[str, int] = Field(
        description="file_path → assertion count per test file"
    )
    mock_usage_files: list[str] = Field(
        description="Test files that use mocking"
    )
    frameworks_detected: list[str] = Field(
        description="Test frameworks detected ('pytest', 'unittest')"
    )

    model_config = {"frozen": True}


class CoverageFileResult(BaseModel):
    """Per-file coverage data from coverage.xml."""

    path: str
    line_rate: float = Field(ge=0.0, le=1.0)
    lines_covered: int = Field(ge=0)
    lines_valid: int = Field(ge=0)

    model_config = {"frozen": True}


class CoverageReport(BaseModel):
    """Parsed coverage.xml summary."""

    overall_line_rate: float = Field(ge=0.0, le=1.0)
    overall_coverage_pct: float = Field(ge=0.0, le=100.0)
    files: list[CoverageFileResult] = Field(default_factory=list)
    timestamp: Optional[str] = None

    model_config = {"frozen": True}


class TestAnalysisResult(BaseModel):
    """Top-level result produced by RealTestIntelligenceService."""

    metrics: TestMetrics
    test_file_details: list[TestFile]
    source_to_test_map: dict[str, list[str]] = Field(
        description="source_file → list of test files that cover it (heuristic)"
    )
    coverage_report: Optional[CoverageReport] = None

    model_config = {"frozen": True}
