"""Deterministic analysis engine for CI/CD pipeline configurations and Dockerfiles.

Provides:
- classify_pipeline_file()  — identify the CI platform from a file path
- analyse_pipeline_sync()   — parse a YAML pipeline file and extract CiCd signals
- analyse_dockerfile_sync() — parse a Dockerfile for multi-stage builds and best practices
- analyse_cicd_sync()       — entry point: scan all CI/CD files in a repo

No LLM calls. No side effects beyond reading files.
All heavy work is sync (designed to run in asyncio executor).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from app.infrastructure.intelligence.cicd_models import (
    CiCdMetrics,
    DockerfileAnalysis,
    PipelineFile,
)

# ---------------------------------------------------------------------------
# Platform classification
# ---------------------------------------------------------------------------

# (path_pattern, platform_key, display_name)
_PIPELINE_PATTERNS: list[tuple[str, str, str]] = [
    # GitHub Actions — any YAML under .github/workflows/
    (r"\.github[/\\]workflows[/\\].+\.ya?ml$",  "github_actions",  "GitHub Actions"),
    # Azure DevOps
    (r"azure-pipelines.*\.ya?ml$",               "azure_devops",    "Azure DevOps"),
    # GitLab CI
    (r"\.gitlab-ci\.ya?ml$",                     "gitlab_ci",       "GitLab CI"),
    # CircleCI
    (r"\.circleci[/\\]config\.ya?ml$",           "circleci",        "CircleCI"),
    # Bitbucket Pipelines
    (r"bitbucket-pipelines\.ya?ml$",             "bitbucket",       "Bitbucket Pipelines"),
    # Jenkins
    (r"Jenkinsfile$",                             "jenkins",         "Jenkins"),
    # Travis CI
    (r"\.travis\.ya?ml$",                         "travis",          "Travis CI"),
]

_DOCKERFILE_PATTERN = re.compile(r"^Dockerfile(.+)?$", re.IGNORECASE)


def classify_pipeline_file(path: str) -> Optional[tuple[str, str]]:
    """
    Return ``(platform_key, display_name)`` if the path looks like a CI/CD file,
    else ``None``.
    """
    for pattern, key, name in _PIPELINE_PATTERNS:
        if re.search(pattern, path, re.IGNORECASE):
            return key, name
    return None


def is_dockerfile(path: str) -> bool:
    return bool(_DOCKERFILE_PATTERN.match(Path(path).name))


# ---------------------------------------------------------------------------
# Keyword signals
# ---------------------------------------------------------------------------

# Each set: if ANY keyword is found in the file's text → flag is True
_TEST_KEYWORDS = frozenset({
    "pytest", "python -m pytest", "npm test", "yarn test", "npx jest",
    "jest", "mocha", "go test", "cargo test", "dotnet test", "mvn test",
    "gradle test", "rspec", "phpunit",
})
_LINT_KEYWORDS = frozenset({
    "flake8", "pylint", "ruff", "mypy", "black", "isort",
    "eslint", "tslint", "prettier", "shellcheck", "golangci-lint",
    "rubocop", "php_codesniffer", "dotnet format", "hadolint",
})
_SECURITY_KEYWORDS = frozenset({
    "sonar", "sonarqube", "sonarcloud", "trivy", "snyk", "bandit",
    "safety", "semgrep", "owasp", "dependency-check", "grype",
    "checkov", "tfsec", "gitleaks", "trufflehog", "detect-secrets",
})
_CACHE_KEYWORDS = frozenset({
    "cache", "actions/cache", "cache-dependency-path",
    "pip cache", "npm cache", "yarn cache", "gradle cache", "maven cache",
})
_DEPLOY_KEYWORDS = frozenset({
    "deploy", "release", "publish", "push to", "helm upgrade",
    "kubectl apply", "terraform apply", "ansible-playbook",
    "az webapp deploy", "gcloud app deploy", "eb deploy",
    "heroku container:push", "docker push",
})

# Primary platform display name priority (for picking the "main" platform)
_PLATFORM_PRIORITY = [
    "github_actions", "azure_devops", "gitlab_ci",
    "circleci", "bitbucket", "jenkins", "travis",
]


def _text_matches_any(text: str, keywords: frozenset[str]) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in keywords)


# ---------------------------------------------------------------------------
# YAML pipeline analysis
# ---------------------------------------------------------------------------

def analyse_pipeline_sync(abs_path: str, rel_path: str, platform_key: str) -> tuple[PipelineFile, dict[str, bool], list[str]]:
    """
    Parse a YAML pipeline file and extract CI/CD signals.

    Returns:
        (PipelineFile, signals_dict, errors)

    signals_dict keys: runs_tests, runs_lint, has_security_scan, uses_cache,
                       has_parallel_jobs, has_deploy_stage
    """
    errors: list[str] = []
    signals: dict[str, bool] = {
        "runs_tests": False,
        "runs_lint": False,
        "has_security_scan": False,
        "uses_cache": False,
        "has_parallel_jobs": False,
        "has_deploy_stage": False,
    }
    job_count = 0

    try:
        import yaml  # PyYAML — optional dep; graceful fallback if missing
    except ImportError:
        errors.append(f"PyYAML not installed — cannot parse {rel_path}")
        return PipelineFile(path=rel_path, platform=platform_key, job_count=0), signals, errors

    try:
        text = Path(abs_path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        errors.append(f"Cannot read {rel_path}: {exc}")
        return PipelineFile(path=rel_path, platform=platform_key, job_count=0), signals, errors

    # Text-level keyword scan (fastest, covers all platforms uniformly)
    signals["runs_tests"]        = _text_matches_any(text, _TEST_KEYWORDS)
    signals["runs_lint"]         = _text_matches_any(text, _LINT_KEYWORDS)
    signals["has_security_scan"] = _text_matches_any(text, _SECURITY_KEYWORDS)
    signals["uses_cache"]        = _text_matches_any(text, _CACHE_KEYWORDS)
    signals["has_deploy_stage"]  = _text_matches_any(text, _DEPLOY_KEYWORDS)

    # Structured YAML analysis for job count + parallel detection
    try:
        data: Any = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        errors.append(f"YAML parse error in {rel_path}: {exc}")
        return PipelineFile(path=rel_path, platform=platform_key, job_count=0), signals, errors

    if isinstance(data, dict):
        job_count, parallel = _extract_job_info(data, platform_key)
        signals["has_parallel_jobs"] = parallel

    return PipelineFile(path=rel_path, platform=platform_key, job_count=job_count), signals, errors


def _extract_job_info(data: dict, platform_key: str) -> tuple[int, bool]:
    """Extract job count and whether jobs run in parallel from parsed YAML."""
    if platform_key == "github_actions":
        # GitHub Actions: jobs: {job_name: {...}, ...}
        jobs = data.get("jobs", {})
        if isinstance(jobs, dict):
            count = len(jobs)
            return count, count > 1

    elif platform_key == "azure_devops":
        # Azure DevOps: stages[].jobs[] or jobs[]
        stages = data.get("stages", [])
        if isinstance(stages, list) and len(stages) > 1:
            return len(stages), True
        jobs = data.get("jobs", [])
        if isinstance(jobs, list):
            return len(jobs), len(jobs) > 1

    elif platform_key == "gitlab_ci":
        # GitLab CI: top-level keys that are not reserved = jobs
        _reserved = {"stages", "variables", "include", "workflow", "default", "image", "services"}
        jobs = [k for k in data if k not in _reserved and isinstance(data[k], dict)]
        return len(jobs), len(jobs) > 1

    elif platform_key == "circleci":
        workflows = data.get("workflows", {})
        if isinstance(workflows, dict):
            # Count jobs in first workflow
            for wf in workflows.values():
                if isinstance(wf, dict):
                    wf_jobs = wf.get("jobs", [])
                    if isinstance(wf_jobs, list):
                        return len(wf_jobs), len(wf_jobs) > 1

    return 0, False


# ---------------------------------------------------------------------------
# Dockerfile analysis
# ---------------------------------------------------------------------------

def analyse_dockerfile_sync(abs_path: str, rel_path: str) -> tuple[DockerfileAnalysis, list[str]]:
    """
    Parse a Dockerfile and detect multi-stage builds and best practices.

    Returns (DockerfileAnalysis, errors).
    """
    errors: list[str] = []

    try:
        text = Path(abs_path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        errors.append(f"Cannot read {rel_path}: {exc}")
        return DockerfileAnalysis(
            path=rel_path, stage_count=0, multi_stage=False,
            base_images=[], exposes_port=False, uses_non_root_user=False,
        ), errors

    lines = text.splitlines()
    base_images: list[str] = []
    exposes_port = False
    non_root_user = False

    for line in lines:
        stripped = line.strip()
        upper = stripped.upper()

        if upper.startswith("FROM "):
            # FROM <image> [AS <stage>]
            parts = stripped.split()
            if len(parts) >= 2:
                image = parts[1]
                if image.upper() != "SCRATCH":
                    base_images.append(image)
                else:
                    base_images.append("scratch")

        elif upper.startswith("EXPOSE "):
            exposes_port = True

        elif upper.startswith("USER "):
            # USER root or USER 0 → still root; anything else → non-root
            user_val = stripped[5:].strip().lower()
            if user_val not in ("root", "0"):
                non_root_user = True

    stage_count = len(base_images)

    return DockerfileAnalysis(
        path=rel_path,
        stage_count=stage_count,
        multi_stage=stage_count > 1,
        base_images=base_images,
        exposes_port=exposes_port,
        uses_non_root_user=non_root_user,
    ), errors


# ---------------------------------------------------------------------------
# Repository-level CI/CD analysis (sync, runs in executor)
# ---------------------------------------------------------------------------

def analyse_cicd_sync(
    root: str,
    file_tree: list[str],
) -> tuple[list[PipelineFile], list[DockerfileAnalysis], dict[str, bool], list[str]]:
    """
    Analyse all CI/CD-related files in the repository.

    Args:
        root:      Absolute path to repository root.
        file_tree: Full list of relative file paths.

    Returns:
        (pipeline_files, dockerfile_analyses, aggregate_signals, parse_errors)
    """
    import os

    pipeline_files: list[PipelineFile] = []
    dockerfile_analyses: list[DockerfileAnalysis] = []
    parse_errors: list[str] = []

    aggregate_signals: dict[str, bool] = {
        "runs_tests": False,
        "runs_lint": False,
        "has_security_scan": False,
        "uses_cache": False,
        "has_parallel_jobs": False,
        "has_deploy_stage": False,
    }

    for rel in file_tree:
        abs_path = os.path.join(root, rel)

        # Check pipeline files
        classification = classify_pipeline_file(rel)
        if classification:
            platform_key, _display = classification
            pf, signals, errors = analyse_pipeline_sync(abs_path, rel, platform_key)
            pipeline_files.append(pf)
            parse_errors.extend(errors)
            for key in aggregate_signals:
                aggregate_signals[key] = aggregate_signals[key] or signals.get(key, False)

        # Check Dockerfiles
        if is_dockerfile(rel):
            da, errors = analyse_dockerfile_sync(abs_path, rel)
            dockerfile_analyses.append(da)
            parse_errors.extend(errors)

    return pipeline_files, dockerfile_analyses, aggregate_signals, parse_errors


# ---------------------------------------------------------------------------
# Metrics builder
# ---------------------------------------------------------------------------

def build_cicd_metrics(
    pipeline_files: list[PipelineFile],
    dockerfile_analyses: list[DockerfileAnalysis],
    signals: dict[str, bool],
) -> CiCdMetrics:
    """Aggregate analysis results into a ``CiCdMetrics`` model."""

    # Determine primary CI platform (highest-priority platform found)
    platform_keys_found = {pf.platform for pf in pipeline_files}
    primary_platform_key: Optional[str] = None
    for key in _PLATFORM_PRIORITY:
        if key in platform_keys_found:
            primary_platform_key = key
            break

    # Map key → display name
    platform_display_map = {k: name for _, k, name in _PIPELINE_PATTERNS}
    primary_platform = platform_display_map.get(primary_platform_key, None) if primary_platform_key else None

    # Stages: heuristic — infer from signal flags
    stages: list[str] = []
    if signals.get("runs_lint"):
        stages.append("lint")
    if signals.get("runs_tests"):
        stages.append("test")
    if signals.get("has_security_scan"):
        stages.append("security")
    if signals.get("has_deploy_stage"):
        stages.append("deploy")

    multi_stage = any(da.multi_stage for da in dockerfile_analyses)

    return CiCdMetrics(
        has_ci_pipeline=len(pipeline_files) > 0,
        pipeline_files=[pf.path for pf in pipeline_files],
        ci_platform=primary_platform,
        uses_cache=signals.get("uses_cache", False),
        runs_tests=signals.get("runs_tests", False),
        runs_lint=signals.get("runs_lint", False),
        has_security_scan=signals.get("has_security_scan", False),
        has_parallel_jobs=signals.get("has_parallel_jobs", False),
        has_deploy_stage=signals.get("has_deploy_stage", False),
        dockerfile_present=len(dockerfile_analyses) > 0,
        multi_stage_build=multi_stage,
        stages_detected=stages,
    )
