"""Request/response schemas for the API layer.

Kept separate from domain models to:
- Allow API versioning without touching domain entities
- Prevent domain internals leaking into the public contract
- Enable field-level documentation in OpenAPI
"""
from __future__ import annotations

import re
import uuid
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.entities import EngineeringReviewAggregate, ReviewSummary


class ReviewRequest(BaseModel):
    """Input payload for ``POST /api/review``."""

    repo_url: Optional[str] = Field(
        default=None,
        description="Public GitHub (or compatible) repository URL to clone and review.",
        examples=["https://github.com/owner/repo"],
    )
    local_path: Optional[str] = Field(
        default=None,
        description="Absolute path to a local repository on the server filesystem.",
        examples=["/srv/repos/my-service"],
    )

    @model_validator(mode="after")
    def _validate_one_source(self) -> "ReviewRequest":
        if not self.repo_url and not self.local_path:
            raise ValueError("Provide either repo_url or local_path.")
        if self.repo_url and self.local_path:
            raise ValueError("Provide only one of repo_url or local_path, not both.")
        return self


class ReviewCreatedResponse(BaseModel):
    """Response envelope for ``POST /api/review``."""

    review_id: uuid.UUID = Field(description="Unique identifier of the created review.")
    status: str = Field(
        default="completed",
        description="Final review status (completed | failed).",
    )


class ReviewResponse(BaseModel):
    """Full aggregate response for ``GET /api/review/{review_id}``."""

    data: EngineeringReviewAggregate = Field(
        description="Complete engineering review aggregate including all agent findings."
    )


class ReviewSummaryResponse(BaseModel):
    """Lightweight summary response for ``GET /api/review/{review_id}/summary``."""

    data: ReviewSummary = Field(
        description="Review summary containing overall score and per-agent scores only."
    )


class ErrorResponse(BaseModel):
    """Standardised error envelope returned for all application-level errors.

    Every error response includes a ``request_id`` that matches the
    ``X-Request-ID`` response header so clients can correlate client-side
    logs with server-side traces.

    Example::

        {
          "error_code": "NOT_FOUND",
          "detail": "Scan 'abc' does not exist.",
          "status_code": 404,
          "request_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
          "timestamp": "2025-01-15T12:34:56.789Z",
          "path": "/api/scans/abc/status"
        }
    """

    model_config = {
        "json_schema_extra": {
            "example": {
                "error_code": "NOT_FOUND",
                "detail": "Scan '3fa85f64' does not exist.",
                "status_code": 404,
                "request_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "timestamp": "2025-01-15T12:34:56.789Z",
                "path": "/api/scans/3fa85f64/status",
            }
        }
    }

    error_code: str = Field(
        description=(
            "Machine-readable error category.  Common values: "
            "``VALIDATION_ERROR``, ``NOT_FOUND``, ``SCAN_ALREADY_RUNNING``, "
            "``INTERNAL_ERROR``, ``RATE_LIMITED``."
        ),
        examples=["NOT_FOUND", "VALIDATION_ERROR"],
    )
    detail: str = Field(description="Human-readable error message.")
    status_code: int = Field(description="HTTP status code.", ge=400, le=599)
    request_id: Optional[str] = Field(
        default=None,
        description=(
            "Echoes the ``X-Request-ID`` header value from the request so "
            "clients can correlate this error with their trace logs."
        ),
    )
    timestamp: Optional[str] = Field(
        default=None,
        description="ISO-8601 UTC timestamp of when the error was generated.",
        examples=["2025-01-15T12:34:56.789Z"],
    )
    path: Optional[str] = Field(
        default=None,
        description="Request path that triggered this error.",
        examples=["/api/scans/abc/status"],
    )


# ---------------------------------------------------------------------------
# Scan run schemas  (POST /api/scans/run  &  GET /api/scans/{id}/status)
# ---------------------------------------------------------------------------

_SAFE_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/\-]+$")
_AGENT_ALIASES = {"qa", "dev", "architect", "sre", "security"}
_GITHUB_TREE_RE = re.compile(
    r"^(https://github\.com/[^/]+/[^/]+)/tree/(.+)$"
)


def _parse_github_web_url(url: str) -> tuple[str, str | None]:
    """Split a GitHub web tree URL into (base_clone_url, branch).

    Handles URLs of the form::

        https://github.com/owner/repo/tree/feature/my-branch
        https://github.com/owner/repo/tree/main

    For plain clone URLs the branch is ``None`` and the URL is returned
    unchanged (minus any trailing ``.git``).
    """
    url = url.rstrip("/").removesuffix(".git")
    m = _GITHUB_TREE_RE.match(url)
    if m:
        return m.group(1), m.group(2).rstrip("/") or None
    return url, None


class ScanConfig(BaseModel):
    """Optional scan configuration flags."""

    mode: Literal["quick", "deep", "security-only", "standard", "security_only"] = Field(
        default="deep",
        description="Scan depth mode.",
    )
    include_agents: Optional[list[str]] = Field(
        default=None,
        description=(
            "Whitelist of agent aliases to run: 'qa', 'dev', 'architect', 'sre', 'security'. "
            "When set, overrides the mode's default agent selection."
        ),
        examples=[["qa", "security"]],
    )
    exclude_agents: Optional[list[str]] = Field(
        default=None,
        description="Agent aliases to exclude from the run.",
        examples=[["architect"]],
    )
    max_files: Optional[Annotated[int, Field(ge=1, le=10_000)]] = Field(
        default=None,
        description="Maximum number of files to include in the scan. Overrides mode default.",
    )
    fail_on_high_severity: bool = Field(
        default=False,
        description="If true, a HIGH or CRITICAL finding will set scan status to 'failed'.",
    )
    allow_auto_fix: bool = Field(
        default=False,
        description=(
            "If true, the scan orchestrator will attempt to generate a patch, "
            "validate it, check for breaking changes, and create a GitHub PR. "
            "Disabled by default. Only effective for GitHub source scans."
        ),
    )
    # Frontend-facing fields stored in scan_config_json for round-trip fidelity
    operation_mode: str = Field(
        default="analyze",
        description="What to do with findings: analyze | suggest | auto-fix.",
    )
    depth: Optional[str] = Field(
        default=None,
        description="Scan depth: shallow | standard | deep.",
    )
    agents: Optional[list[str]] = Field(
        default=None,
        description=(
            "Frontend AgentType[] — subset of agents to run "
            "(uppercase: QA | Dev | Architect | SRE | Security)."
        ),
    )

    @field_validator("include_agents", "exclude_agents", mode="before")
    @classmethod
    def _validate_agent_aliases(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return v
        invalid = set(v) - _AGENT_ALIASES
        if invalid:
            raise ValueError(
                f"Unknown agent aliases: {sorted(invalid)}. "
                f"Valid aliases: {sorted(_AGENT_ALIASES)}."
            )
        return v


class ScanRunRequest(BaseModel):
    """Input payload for ``POST /api/scans/run``."""

    source_type: Literal["github", "local"] = Field(
        description="Origin of the code to scan: a GitHub repo or a local folder."
    )
    repository_url: Optional[str] = Field(
        default=None,
        description="GitHub repository URL (required when source_type='github').",
        examples=["https://github.com/owner/repo"],
    )
    local_path: Optional[str] = Field(
        default=None,
        description="Absolute path to a local directory (required when source_type='local').",
        examples=["/srv/repos/my-service"],
    )
    branch: Optional[str] = Field(
        default=None,
        description=(
            "Git branch to clone (GitHub only). Defaults to the repository's default branch. "
            "Only alphanumeric characters, dots, hyphens, underscores, and forward-slashes "
            "are permitted."
        ),
        max_length=256,
        examples=["main", "feature/my-branch"],
    )
    config: Optional[ScanConfig] = Field(
        default=None,
        description="Optional scan configuration flags.",
    )

    @model_validator(mode="after")
    def _validate_source(self) -> "ScanRunRequest":
        if self.source_type == "github":
            if not self.repository_url:
                raise ValueError("repository_url is required when source_type='github'.")
            # Normalise GitHub web tree/blob URLs → clean clone URL + branch.
            # E.g. https://github.com/owner/repo/tree/feature/my-branch
            #   → repository_url=https://github.com/owner/repo, branch=feature/my-branch
            base_url, extracted_branch = _parse_github_web_url(self.repository_url)
            self.repository_url = base_url
            if extracted_branch and not self.branch:
                self.branch = extracted_branch
            if not self.repository_url.startswith("https://github.com/"):
                raise ValueError(
                    "repository_url must start with 'https://github.com/'."
                )
            if self.branch and not _SAFE_BRANCH_RE.match(self.branch):
                raise ValueError(
                    "branch contains invalid characters. Use only alphanumeric "
                    "characters, dots, hyphens, underscores, or forward-slashes."
                )
        elif self.source_type == "local":
            if not self.local_path:
                raise ValueError("local_path is required when source_type='local'.")
            if self.branch is not None:
                raise ValueError("branch is only supported for source_type='github'.")
        return self

    @field_validator("repository_url")
    @classmethod
    def _strip_repository_url(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v else v

    @field_validator("local_path")
    @classmethod
    def _strip_local_path(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v else v


class ScanRunResponse(BaseModel):
    """Response envelope for ``POST /api/scans/run``."""

    model_config = {"json_schema_extra": {"example": {
        "scan_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "repository_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
        "status": "queued",
    }}}

    scan_id: uuid.UUID = Field(description="Unique identifier of the queued scan.")
    repository_id: uuid.UUID = Field(description="Unique identifier of the repository record.")
    status: str = Field(default="queued", description="Initial scan status (always 'queued').")


class ScanStatusResponse(BaseModel):
    """Response envelope for ``GET /api/scans/{scan_id}/status``."""

    model_config = {"json_schema_extra": {"example": {
        "scan_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "status": "running",
        "progress_percentage": 45,
        "error_message": None,
    }}}

    scan_id: uuid.UUID = Field(description="Unique identifier of the scan.")
    status: str = Field(
        description="Current scan status: queued | running | completed | failed | cancelled."
    )
    progress_percentage: int = Field(
        ge=0, le=100,
        description="Progress as a percentage from 0 to 100.",
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Human-readable error description, present only when status='failed'.",
    )


class ScanCancelResponse(BaseModel):
    """Response envelope for ``POST /api/scans/{scan_id}/cancel``."""

    scan_id: uuid.UUID = Field(description="Unique identifier of the scan.")
    status: str = Field(
        default="cancellation_requested",
        description="Acknowledgement that cancellation has been requested.",
    )


# ---------------------------------------------------------------------------
# Rich scan detail  (returned by a future GET /api/scans/{id} endpoint)
# ---------------------------------------------------------------------------


class AgentFindingSummary(BaseModel):
    """Per-agent finding summary embedded in ScanDetailResponse."""

    agent_name: str = Field(description="Agent identifier, e.g. 'security', 'qa'.")
    score: int = Field(ge=0, le=100, description="Agent score from 0 (worst) to 100 (best).")
    summary: str = Field(description="One-paragraph agent assessment summary.")
    issue_count: int = Field(ge=0, description="Number of issues found by this agent.")
    recommendation_count: int = Field(ge=0, description="Number of recommendations.")

    model_config = {"json_schema_extra": {"example": {
        "agent_name": "security",
        "score": 71,
        "summary": "Two high-severity dependency vulnerabilities detected.",
        "issue_count": 2,
        "recommendation_count": 3,
    }}}


class ScanDetailResponse(BaseModel):
    """Full scan result including overall score and per-agent breakdowns.

    Returned by ``GET /api/scans/{scan_id}``.
    """

    model_config = {"json_schema_extra": {"example": {
        "scan_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "repository_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
        "status": "completed",
        "progress_percentage": 100,
        "overall_score": 82,
        "risk_level": "medium",
        "scan_mode": "deep",
        "branch": "main",
        "source_type": "github",
        "agent_findings": [],
        "error_message": None,
        "patch_available": False,
    }}}

    scan_id: uuid.UUID = Field(description="Unique identifier of the scan.")
    repository_id: uuid.UUID = Field(description="Unique identifier of the repository.")
    status: str = Field(description="Current scan status.")
    progress_percentage: int = Field(ge=0, le=100, description="Progress 0–100.")
    overall_score: Optional[int] = Field(
        default=None, ge=0, le=100,
        description="Aggregated score from all agents (0–100). Null until completed.",
    )
    risk_level: Optional[str] = Field(
        default=None,
        description="Risk classification: low | medium | high | critical.",
    )
    scan_mode: str = Field(default="deep", description="Scan mode used: quick | deep | security-only.")
    branch: Optional[str] = Field(default=None, description="Git branch that was scanned.")
    source_type: str = Field(description="Source origin: github | local.")
    agent_findings: list[AgentFindingSummary] = Field(
        default_factory=list,
        description="Per-agent score summaries.",
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error details when status='failed'.",
    )
    patch_available: bool = Field(
        default=False,
        description="True if the auto-fix pipeline produced a patch PR.",
    )


# ---------------------------------------------------------------------------
# Validation report  (surfaced in auto-fix pipeline results)
# ---------------------------------------------------------------------------


class ValidationReportResponse(BaseModel):
    """Public representation of the auto-fix validation pipeline results."""

    model_config = {"json_schema_extra": {"example": {
        "lint_passed": True,
        "tests_passed": True,
        "type_check_passed": False,
        "passed": False,
        "errors": ["[mypy] app/main.py:12: error: Incompatible return value type"],
    }}}

    lint_passed: bool = Field(description="True if linting passed (or no linter available).")
    tests_passed: bool = Field(description="True if test suite passed (or no tests available).")
    type_check_passed: bool = Field(description="True if type checker passed (or unavailable).")
    passed: bool = Field(description="True only when all three checks passed.")
    errors: list[str] = Field(default_factory=list, description="Collected error messages.")


# ---------------------------------------------------------------------------
# Breaking change report
# ---------------------------------------------------------------------------


class BreakingChangeReportResponse(BaseModel):
    """Public representation of the breaking-change detector output."""

    model_config = {"json_schema_extra": {"example": {
        "has_breaking_changes": False,
        "details": [],
    }}}

    has_breaking_changes: bool = Field(
        description="True if the patch introduces API / signature breaking changes."
    )
    details: list[str] = Field(
        default_factory=list,
        description="Human-readable descriptions of each detected breaking change.",
    )


# ---------------------------------------------------------------------------
# PR creation response
# ---------------------------------------------------------------------------


class PRResponse(BaseModel):
    """Result of a safe auto-fix PR creation attempt."""

    model_config = {"json_schema_extra": {"example": {
        "created": True,
        "pr_url": "https://github.com/owner/repo/pull/42",
        "pr_number": 42,
        "branch_name": "fix/engineering-intelligence-3fa85f64",
        "reason": None,
        "warnings": [],
    }}}

    created: bool = Field(description="True if the PR was successfully created.")
    pr_url: Optional[str] = Field(default=None, description="URL of the created PR.")
    pr_number: Optional[int] = Field(default=None, description="PR number on GitHub.")
    branch_name: Optional[str] = Field(default=None, description="Name of the fix branch.")
    reason: Optional[str] = Field(
        default=None,
        description="Reason the PR was NOT created (present when created=False).",
    )
    warnings: list[str] = Field(default_factory=list, description="Non-fatal warnings.")


# ---------------------------------------------------------------------------
# Repository schemas
# ---------------------------------------------------------------------------


class RepositoryCreateRequest(BaseModel):
    """Input payload for ``POST /api/v1/repositories``."""

    name: str = Field(max_length=512, description="Display name for the repository.")
    source_type: Literal["github", "local"] = Field(description="Origin type of the repository.")
    url_or_path: str = Field(
        max_length=4096,
        description="GitHub URL (https://github.com/owner/repo) or absolute local path.",
        examples=["https://github.com/owner/repo", "/srv/repos/my-service"],
    )
    default_branch: Optional[str] = Field(
        default="main",
        max_length=256,
        description="Default git branch name.",
        examples=["main", "master"],
    )

    @field_validator("url_or_path")
    @classmethod
    def _validate_url_or_path(cls, v: str) -> str:
        return v.strip()


class RepositoryUpdateRequest(BaseModel):
    """Input payload for ``PUT /api/v1/repositories/{repo_id}``."""

    name: Optional[str] = Field(default=None, max_length=512)
    default_branch: Optional[str] = Field(default=None, max_length=256)


class RepositoryResponse(BaseModel):
    """Response schema for repository CRUD endpoints."""

    model_config = {"from_attributes": True}

    id: uuid.UUID = Field(description="Unique repository identifier.")
    name: str = Field(description="Display name.")
    source_type: Optional[str] = Field(default=None, description="Origin type: github | local.")
    url_or_path: str = Field(description="GitHub URL or local filesystem path.")
    default_branch: Optional[str] = Field(default=None, description="Default git branch.")
    created_at: str = Field(description="ISO-8601 creation timestamp.")

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {"example": {
            "id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
            "name": "my-service",
            "source_type": "github",
            "url_or_path": "https://github.com/owner/my-service",
            "default_branch": "main",
            "created_at": "2025-01-15T12:00:00Z",
        }},
    }


# ---------------------------------------------------------------------------
# Scan list schema (lightweight, used by GET /api/v1/scans)
# ---------------------------------------------------------------------------


class ScanSummaryResponse(BaseModel):
    """Lightweight scan record, used in list responses."""

    model_config = {"from_attributes": True}

    scan_id: uuid.UUID = Field(description="Unique scan identifier.")
    repository_id: uuid.UUID = Field(description="Owning repository.")
    branch: Optional[str] = Field(default=None, description="Git branch scanned.")
    scan_mode: str = Field(default="deep", description="Scan mode: quick | deep | security-only.")
    status: str = Field(description="queued | running | completed | failed | cancelled.")
    overall_score: Optional[int] = Field(default=None, ge=0, le=100)
    created_at: str = Field(description="ISO-8601 creation timestamp.")

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {"example": {
            "scan_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
            "repository_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
            "branch": "main",
            "scan_mode": "deep",
            "status": "completed",
            "overall_score": 82,
            "created_at": "2025-01-15T12:00:00Z",
        }},
    }


# ---------------------------------------------------------------------------
# Patch schema
# ---------------------------------------------------------------------------


class PatchResponse(BaseModel):
    """Unified diff generated by the auto-fix pipeline."""

    scan_id: uuid.UUID = Field(description="Scan that produced this patch.")
    unified_diff: str = Field(description="Unified diff string (GNU patch format).")

    model_config = {"json_schema_extra": {"example": {
        "scan_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "unified_diff": "--- a/app/main.py\n+++ b/app/main.py\n@@ -1,3 +1,3 @@\n-bad\n+good\n",
    }}}


# ---------------------------------------------------------------------------
# Annotation schema
# ---------------------------------------------------------------------------

_SEVERITY_VALUES = Literal["low", "medium", "high", "critical"]
_CATEGORY_VALUES = Literal["qa", "dev", "arch", "sre", "security"]


class AnnotationResponse(BaseModel):
    """A single code-level finding extracted from agent results."""

    file_path: Optional[str] = Field(
        default=None, description="Relative path to the affected file."
    )
    line_number: Optional[int] = Field(
        default=None, ge=1, description="Line number of the finding."
    )
    severity: str = Field(description="low | medium | high | critical.")
    category: str = Field(description="Agent category: qa | dev | arch | sre | security.")
    message: str = Field(description="Human-readable finding description.")

    model_config = {"json_schema_extra": {"example": {
        "file_path": "app/auth.py",
        "line_number": 42,
        "severity": "high",
        "category": "security",
        "message": "Hardcoded secret detected in authentication module.",
    }}}


# ---------------------------------------------------------------------------
# Auth schema
# ---------------------------------------------------------------------------


class LocalUserResponse(BaseModel):
    """Local system user, returned by ``GET /api/v1/auth/local-user``."""

    id: str = Field(description="System username used as identifier.")
    name: str = Field(description="Display name (same as system username).")
    email: str = Field(description="Synthetic email derived from username.")

    model_config = {"json_schema_extra": {"example": {
        "id": "developer",
        "name": "developer",
        "email": "developer@localhost",
    }}}


# ---------------------------------------------------------------------------
# Trend analysis schemas  (GET /api/repositories/{repo_id}/trends)
# ---------------------------------------------------------------------------


class TrendRadarDimensionSchema(BaseModel):
    """Radar dimension for a trend data point.

    score and confidence may be None for old scans that predate radar tracking.
    """

    score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=10.0,
        description="Dimension score 0–10. None when radar data was not collected.",
    )
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence 0–1. None when radar data was not collected.",
    )


class TrendDataPointSchema(BaseModel):
    """Single scan result in a historical trend series."""

    timestamp: str = Field(description="ISO-8601 UTC timestamp of the scan.")
    overall_score: float = Field(ge=0.0, le=100.0, description="Aggregated engineering score.")
    overall_confidence: float = Field(ge=0.0, le=1.0, description="Agent confidence at scan time.")
    effective_confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence after exponential time-decay (older scans weigh less).",
    )
    radar: dict[str, TrendRadarDimensionSchema] = Field(
        default_factory=dict,
        description="Radar dimension scores. Empty dict for scans without radar data.",
    )


class AggregatedTrendSchema(BaseModel):
    """Confidence-decay-weighted aggregation across all trend data points."""

    overall_score: float = Field(ge=0.0, le=100.0, description="Decay-weighted average score.")
    confidence: float = Field(ge=0.0, le=1.0, description="Mean effective confidence.")
    trend_warning: Optional[str] = Field(
        default=None,
        description="Set when average effective_confidence < 0.5.",
    )


class RepositoryTrendsSchema(BaseModel):
    """Full trend response for GET /api/repositories/{repo_id}/trends."""

    repo_id: str = Field(description="Repository UUID string.")
    time_series: list[TrendDataPointSchema] = Field(
        default_factory=list,
        description="Scan history ordered oldest-first with decay metadata.",
    )
    aggregated_trend: AggregatedTrendSchema = Field(
        description="Confidence-weighted summary of the whole trend window.",
    )


# ---------------------------------------------------------------------------
# Frontend-aligned schemas (match ui/generated/api-client.ts exactly)
# These are used by the legacy /api/ routes consumed by the UI.
# ---------------------------------------------------------------------------


class RadarDimensionSchema(BaseModel):
    """Score + confidence for one radar chart dimension."""

    score: float = Field(ge=0.0, le=10.0, description="Dimension score 0–10.")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence 0–1 for this dimension.")


class AgentScoreSchema(BaseModel):
    """Per-agent score summary matching the frontend AgentScore type."""

    agent: str = Field(description="Agent type: QA | Dev | Architect | SRE | Security.")
    score: int = Field(ge=0, le=100)
    delta: int = Field(default=0, description="Score change vs previous scan.")
    issue_count: int = Field(ge=0)
    description: str = Field(default="")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Agent confidence 0–1.")
    confidence_reason: str = Field(default="", description="Why this confidence level was assigned.")


class TrendPointSchema(BaseModel):
    """Single data point in a repository's score trend."""

    label: str = Field(description="Short date label, e.g. 'Jan 15'.")
    score: int = Field(ge=0, le=100)
    date: str = Field(description="ISO-8601 timestamp.")


class IssueSchema(BaseModel):
    """A single finding as returned in the full scan response."""

    id: str
    severity: str = Field(description="Critical | High | Medium | Low | Info")
    agent: str = Field(description="QA | Dev | Architect | SRE | Security")
    file_path: str = Field(default="")
    line_number: int = Field(default=0)
    title: str
    description: str = Field(default="")
    recommendation: str = Field(default="")


class ArchitectureDriftSchema(BaseModel):
    """Architecture drift metrics (all zero until drift detection is implemented)."""

    circular_dependency_delta: int = 0
    layer_violations_delta: int = 0
    coupling_delta: str = "+0%"
    previous_circular: int = 0
    current_circular: int = 0
    previous_violations: int = 0
    current_violations: int = 0


class FixPRSchema(BaseModel):
    """Minimal PR creation result embedded in a scan detail."""

    created: bool
    pr_url: Optional[str] = None


class ScanSummarySchema(BaseModel):
    """Lightweight scan summary matching the frontend ScanSummary type."""

    id: str
    repository_id: str
    repository_name: str
    branch: str
    commit_sha: str
    date: str
    status: str
    mode: str = Field(description="quick | standard | security_only | deep")
    operation_mode: str = Field(description="analyze | suggest | auto-fix")
    source_type: str = Field(default="github", description="github | local")
    overall_score: int = Field(ge=0, le=100)
    risk: str = Field(description="Low | Medium | High")
    delta: int = Field(default=0)
    duration: str = Field(default="")
    issue_count: int = Field(ge=0, default=0)


class ScanFullSchema(ScanSummarySchema):
    """Full scan detail matching the frontend Scan type."""

    repository_url: Optional[str] = Field(default=None, description="GitHub URL for github scans.")
    agents: list[AgentScoreSchema] = Field(default_factory=list)
    issues: list[IssueSchema] = Field(default_factory=list)
    drift: ArchitectureDriftSchema = Field(default_factory=ArchitectureDriftSchema)
    read_only: bool = True
    patch_available: bool = False
    validation_report: Optional[ValidationReportResponse] = None
    breaking_change_report: Optional[BreakingChangeReportResponse] = None
    fix_pr: Optional[FixPRSchema] = None
    overall_confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Weighted average agent confidence.")
    radar: dict[str, RadarDimensionSchema] = Field(default_factory=dict, description="6-dimension radar chart data.")
    top_risks: list[IssueSchema] = Field(default_factory=list, description="Top issues by severity (Critical > High > Medium > Low).")


class ScanListEnvelope(BaseModel):
    """Paginated scan list matching the frontend ScanListResponse."""

    items: list[ScanSummarySchema]
    total: int


class RepositoryListItemSchema(BaseModel):
    """Repository list item matching the frontend RepositoryListItem type."""

    id: str
    name: str
    description: str = Field(default="")
    language: str = Field(default="")
    source_type: str
    repository_url: Optional[str] = None
    local_path: Optional[str] = None
    overall_score: int = Field(ge=0, le=100, default=0)
    delta: int = Field(default=0)
    risk: str = Field(default="Low")
    last_scan_date: str = Field(default="")
    open_issues: int = Field(ge=0, default=0)
    team_size: int = Field(ge=0, default=0)
    scan_count: int = Field(ge=0, default=0)


class RepositoryFullSchema(RepositoryListItemSchema):
    """Full repository detail matching the frontend Repository type."""

    agents: list[AgentScoreSchema] = Field(default_factory=list)
    trend: list[TrendPointSchema] = Field(default_factory=list)
    scans: list[ScanSummarySchema] = Field(default_factory=list)


class RepositoryListEnvelope(BaseModel):
    """Paginated repository list matching the frontend RepositoryListResponse."""

    items: list[RepositoryListItemSchema]
    total: int


class CreateRepositoryBodyRequest(BaseModel):
    """Input payload for ``POST /api/repositories`` (frontend-facing)."""

    name: str = Field(max_length=512)
    description: Optional[str] = None
    language: Optional[str] = Field(default=None, max_length=100)
    source_type: Literal["github", "local"]
    repository_url: Optional[str] = Field(default=None, max_length=2048)
    local_path: Optional[str] = Field(default=None, max_length=4096)
    team_size: Optional[int] = Field(default=None, ge=0)


class UpdateRepositoryBodyRequest(BaseModel):
    """Input payload for ``PATCH /api/repositories/{id}`` (frontend-facing)."""

    name: Optional[str] = Field(default=None, max_length=512)
    description: Optional[str] = None
    language: Optional[str] = Field(default=None, max_length=100)
    team_size: Optional[int] = Field(default=None, ge=0)


class BranchesResponse(BaseModel):
    """Response for ``GET /api/repos/branches``."""

    branches: list[str]
    default_branch: str


class PullRequestItem(BaseModel):
    """Single pull request summary for ``GET /api/repos/pulls``."""

    number: int = Field(description="PR number.")
    title: str = Field(description="PR title.")
    state: str = Field(description="PR state: open | closed.")
    draft: bool = Field(default=False, description="True if the PR is a draft.")
    head_ref: str = Field(description="Head branch name (the branch being merged).")
    base_ref: str = Field(description="Base branch name (the merge target).")
    author: str = Field(description="GitHub login of the PR author.")
    url: str = Field(description="HTML URL of the PR on GitHub.")
    created_at: str = Field(description="ISO-8601 creation timestamp.")
    updated_at: str = Field(description="ISO-8601 last-updated timestamp.")


class PullRequestsResponse(BaseModel):
    """Response for ``GET /api/repos/pulls``."""

    pull_requests: list[PullRequestItem]
    total: int = Field(description="Total number of PRs returned.")


class CreatePRResponse(BaseModel):
    """Simplified PR response matching the frontend CreatePRResponse type."""

    created: bool
    pr_url: Optional[str] = None
    message: Optional[str] = None


# PatchAnnotations shapes matching the frontend PatchAnnotations type

class HunkAnnotationSchema(BaseModel):
    """Annotation for a single @@ hunk in the diff."""

    hunk_index: int = Field(default=0)
    reason: str
    risk_score: int = Field(ge=1, le=10)
    risk_level: str = Field(description="Low | Medium | High")
    impact: str = Field(description="Low | Medium | High")
    references: Optional[list[str]] = Field(default_factory=list)


class FileAnnotationSchema(BaseModel):
    """All annotations for a single file in the diff."""

    file: str
    impact: str = Field(description="Low | Medium | High")
    risk_score: int = Field(ge=1, le=10)
    hunks: list[HunkAnnotationSchema]


class PatchAnnotationsSchema(BaseModel):
    """Full patch annotation result matching the frontend PatchAnnotations type."""

    files: list[FileAnnotationSchema] = Field(default_factory=list)
    overall_impact: str = Field(default="Low")


# ---------------------------------------------------------------------------
# Agent performance schemas  (GET /api/agents/performance)
# ---------------------------------------------------------------------------


class AgentRecentScore(BaseModel):
    """A single recent score entry for an agent."""

    scan_id: str
    repository_name: str
    score: int
    date: str


class AgentPerformanceEntry(BaseModel):
    """Performance summary for a single agent across completed scans."""

    name: str = Field(description="Agent name: QA | Dev | Architect | SRE | Security")
    avg_score: float
    total_runs: int
    description: str = Field(description="What this agent analyses")
    recent_scores: list[AgentRecentScore]


class AgentsPerformanceResponse(BaseModel):
    """Response envelope for GET /api/agents/performance."""

    agents: list[AgentPerformanceEntry]
    total_scans_analysed: int


# ---------------------------------------------------------------------------
# Security overview schemas  (GET /api/security/overview)
# ---------------------------------------------------------------------------


class SecurityRepoEntry(BaseModel):
    """Security posture summary for a single repository."""

    repository_id: str
    repository_name: str
    security_score: int
    risk: str = Field(description="Low | Medium | High | Critical")
    open_issues: int
    last_scan_date: str
    scan_id: str


class SecurityOverviewResponse(BaseModel):
    """Response envelope for GET /api/security/overview."""

    repositories: list[SecurityRepoEntry]
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int

