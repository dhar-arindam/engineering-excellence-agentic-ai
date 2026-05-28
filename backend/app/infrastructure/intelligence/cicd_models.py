"""Pydantic models for CI/CD intelligence analysis results.

All models are frozen value objects — produced by analysis, never mutated.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class PipelineFile(BaseModel):
    """Metadata for a detected CI/CD pipeline configuration file."""

    path: str
    platform: str = Field(description="'github_actions' | 'azure_devops' | 'gitlab_ci' | 'circleci' | 'jenkins' | 'bitbucket' | 'unknown'")
    job_count: int = Field(ge=0, description="Number of top-level jobs/stages detected")

    model_config = {"frozen": True}


class DockerfileAnalysis(BaseModel):
    """Result of Dockerfile inspection."""

    path: str
    stage_count: int = Field(ge=0, description="Number of FROM instructions (>1 = multi-stage)")
    multi_stage: bool
    base_images: list[str] = Field(description="Base image names from each FROM instruction")
    exposes_port: bool = Field(description="Whether any EXPOSE instruction is present")
    uses_non_root_user: bool = Field(description="Whether a USER instruction for non-root is present")

    model_config = {"frozen": True}


class CiCdMetrics(BaseModel):
    """Aggregate CI/CD health metrics for a repository."""

    has_ci_pipeline: bool
    pipeline_files: list[str] = Field(description="Relative paths to all detected pipeline config files")
    ci_platform: Optional[str] = Field(
        default=None,
        description="Primary CI platform detected (e.g. 'GitHub Actions', 'Azure DevOps')",
    )
    uses_cache: bool = Field(description="Whether any pipeline step uses dependency caching")
    runs_tests: bool = Field(description="Whether the pipeline runs tests (pytest, jest, etc.)")
    runs_lint: bool = Field(description="Whether the pipeline runs a linter or formatter check")
    has_security_scan: bool = Field(description="Whether a security scanning tool is configured")
    has_parallel_jobs: bool = Field(description="Whether the pipeline defines parallel jobs/stages")
    has_deploy_stage: bool = Field(description="Whether any deploy/release stage is detected")
    dockerfile_present: bool
    multi_stage_build: bool = Field(description="Whether any Dockerfile uses multi-stage builds")
    stages_detected: list[str] = Field(description="High-level stage names inferred from pipeline")

    model_config = {"frozen": True}


class CiCdAnalysisResult(BaseModel):
    """Top-level result produced by RealCiCdIntelligenceService."""

    metrics: CiCdMetrics
    pipeline_details: list[PipelineFile]
    dockerfile_details: list[DockerfileAnalysis]
    parse_errors: list[str] = Field(
        description="Files that could not be parsed (YAML errors, encoding issues)"
    )

    model_config = {"frozen": True}
