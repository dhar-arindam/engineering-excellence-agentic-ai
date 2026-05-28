"""Pydantic models for security intelligence analysis results.

All models are frozen value objects — produced by analysis, never mutated.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class SecretFinding(BaseModel):
    """A single potential secret or credential detected via regex."""

    file_path: str
    line_number: int = Field(ge=1)
    pattern_type: str = Field(
        description="'api_key' | 'secret_key' | 'password' | 'private_key' | 'token' | 'connection_string'"
    )
    # Redacted preview — never store actual values.
    # Shows only first/last 2 chars of the matched value with *** in between.
    redacted_preview: str

    model_config = {"frozen": True}


class InsecurePatternFinding(BaseModel):
    """A single insecure pattern (e.g., HTTP URL, weak algorithm reference) detected via regex."""

    file_path: str
    line_number: int = Field(ge=1)
    pattern_type: str = Field(
        description="'http_url' | 'weak_hash' | 'eval_usage' | 'shell_injection' | 'debug_enabled'"
    )
    snippet: str = Field(description="Short context snippet (truncated, safe to log)")

    model_config = {"frozen": True}


class SecurityMetrics(BaseModel):
    """Aggregate security signals for a repository."""

    # Required fields matching the spec
    potential_secrets_found: list[str] = Field(
        description="'file:line:pattern_type' strings for each potential secret detected"
    )
    insecure_patterns: list[str] = Field(
        description="'file:line:pattern_type' strings for each insecure pattern detected"
    )
    dependency_files: list[str] = Field(
        description="Relative paths to all dependency manifest files found"
    )
    uses_https: bool = Field(
        description="True when no plain HTTP URLs (outside test/doc files) are detected"
    )
    has_requirements_txt: bool
    hardcoded_password_instances: list[str] = Field(
        description="'file:line' strings for hardcoded passwords specifically"
    )

    # Extended fields
    secret_count: int = Field(ge=0, description="Total number of potential secrets found")
    insecure_pattern_count: int = Field(ge=0)
    has_dependency_scanner: bool = Field(
        description="Whether a known dependency scanner config is present (Dependabot, Snyk, etc.)"
    )
    has_security_policy: bool = Field(
        description="Whether a SECURITY.md or .github/SECURITY.md is present"
    )
    scanned_files: int = Field(ge=0, description="Number of files scanned")

    model_config = {"frozen": True}


class SecurityAnalysisResult(BaseModel):
    """Top-level result produced by RealSecurityIntelligenceService."""

    metrics: SecurityMetrics
    secret_findings: list[SecretFinding]
    insecure_findings: list[InsecurePatternFinding]
    scan_errors: list[str] = Field(
        description="Files that could not be scanned (encoding errors, OS errors)"
    )

    model_config = {"frozen": True}
