"""Tests for RealCiCdIntelligenceService and CI/CD engine components."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.infrastructure.intelligence.cicd_engine import (
    analyse_cicd_sync,
    analyse_dockerfile_sync,
    analyse_pipeline_sync,
    build_cicd_metrics,
    classify_pipeline_file,
    is_dockerfile,
)
from app.infrastructure.intelligence.cicd_intelligence import RealCiCdIntelligenceService
from app.infrastructure.intelligence.cicd_models import CiCdAnalysisResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_repo(tmp_path: Path) -> Path:
    """Minimal repo with GHA workflow, Dockerfile, and source code."""
    # GitHub Actions workflow
    gha_dir = tmp_path / ".github" / "workflows"
    gha_dir.mkdir(parents=True)
    (gha_dir / "ci.yml").write_text(
        textwrap.dedent("""\
            name: CI
            on: [push, pull_request]
            jobs:
              lint:
                runs-on: ubuntu-latest
                steps:
                  - uses: actions/checkout@v3
                  - uses: actions/cache@v3
                    with:
                      path: ~/.cache/pip
                      key: pip-${{ hashFiles('requirements.txt') }}
                  - run: ruff check .
              test:
                runs-on: ubuntu-latest
                steps:
                  - uses: actions/checkout@v3
                  - run: pytest tests/
        """),
        encoding="utf-8",
    )

    # Dockerfile (multi-stage)
    (tmp_path / "Dockerfile").write_text(
        textwrap.dedent("""\
            FROM python:3.11-slim AS builder
            WORKDIR /app
            COPY requirements.txt .
            RUN pip install --no-cache-dir -r requirements.txt

            FROM python:3.11-slim
            WORKDIR /app
            COPY --from=builder /app /app
            EXPOSE 8000
            USER appuser
            CMD ["python", "-m", "uvicorn", "app.main:app"]
        """),
        encoding="utf-8",
    )

    # Source file (not a pipeline)
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "main.py").write_text("# main\n", encoding="utf-8")

    return tmp_path


@pytest.fixture()
def file_tree(sample_repo: Path) -> list[str]:
    result = []
    for p in sample_repo.rglob("*"):
        if p.is_file():
            result.append(str(p.relative_to(sample_repo)))
    return result


@pytest.fixture()
def service() -> RealCiCdIntelligenceService:
    return RealCiCdIntelligenceService()


# ---------------------------------------------------------------------------
# classify_pipeline_file
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path,expected_key", [
    (".github/workflows/ci.yml",    "github_actions"),
    (".github/workflows/release.yaml", "github_actions"),
    ("azure-pipelines.yml",         "azure_devops"),
    ("azure-pipelines-prod.yml",    "azure_devops"),
    (".gitlab-ci.yml",              "gitlab_ci"),
    (".circleci/config.yml",        "circleci"),
    ("bitbucket-pipelines.yml",     "bitbucket"),
    ("Jenkinsfile",                  "jenkins"),
    (".travis.yml",                  "travis"),
])
def test_classify_pipeline_file_known(path: str, expected_key: str):
    result = classify_pipeline_file(path)
    assert result is not None
    assert result[0] == expected_key


def test_classify_pipeline_file_unknown():
    assert classify_pipeline_file("app/main.py") is None
    assert classify_pipeline_file("requirements.txt") is None


# ---------------------------------------------------------------------------
# is_dockerfile
# ---------------------------------------------------------------------------


def test_is_dockerfile_root():
    assert is_dockerfile("Dockerfile") is True


def test_is_dockerfile_variant():
    assert is_dockerfile("Dockerfile.dev") is True
    assert is_dockerfile("Dockerfile.production") is True


def test_is_not_dockerfile():
    assert is_dockerfile("app/main.py") is False
    assert is_dockerfile(".dockerignore") is False


# ---------------------------------------------------------------------------
# analyse_dockerfile_sync
# ---------------------------------------------------------------------------


def test_analyse_dockerfile_multi_stage(sample_repo: Path):
    rel = "Dockerfile"
    abs_p = str(sample_repo / rel)
    da, errors = analyse_dockerfile_sync(abs_p, rel)
    assert errors == []
    assert da.multi_stage is True
    assert da.stage_count == 2
    assert len(da.base_images) == 2
    assert da.exposes_port is True
    assert da.uses_non_root_user is True


def test_analyse_dockerfile_single_stage(tmp_path: Path):
    f = tmp_path / "Dockerfile"
    f.write_text("FROM ubuntu:22.04\nRUN apt-get update\n", encoding="utf-8")
    da, errors = analyse_dockerfile_sync(str(f), "Dockerfile")
    assert da.stage_count == 1
    assert da.multi_stage is False
    assert da.uses_non_root_user is False
    assert da.exposes_port is False


def test_analyse_dockerfile_root_user(tmp_path: Path):
    f = tmp_path / "Dockerfile"
    f.write_text("FROM alpine\nUSER root\n", encoding="utf-8")
    da, _ = analyse_dockerfile_sync(str(f), "Dockerfile")
    assert da.uses_non_root_user is False


def test_analyse_dockerfile_missing(tmp_path: Path):
    _, errors = analyse_dockerfile_sync(str(tmp_path / "Dockerfile"), "Dockerfile")
    assert len(errors) == 1


# ---------------------------------------------------------------------------
# analyse_pipeline_sync — GitHub Actions
# ---------------------------------------------------------------------------


def test_analyse_pipeline_detects_tests(sample_repo: Path):
    rel = ".github/workflows/ci.yml"
    abs_p = str(sample_repo / rel)
    pf, signals, errors = analyse_pipeline_sync(abs_p, rel, "github_actions")
    assert errors == []
    assert signals["runs_tests"] is True
    assert signals["runs_lint"] is True
    assert signals["uses_cache"] is True
    assert pf.platform == "github_actions"
    assert pf.job_count == 2  # lint + test jobs


def test_analyse_pipeline_parallel_jobs(sample_repo: Path):
    rel = ".github/workflows/ci.yml"
    abs_p = str(sample_repo / rel)
    _, signals, _ = analyse_pipeline_sync(abs_p, rel, "github_actions")
    assert signals["has_parallel_jobs"] is True  # 2 jobs = parallel


def test_analyse_pipeline_detects_security(tmp_path: Path):
    f = tmp_path / "ci.yml"
    f.write_text(
        "jobs:\n  scan:\n    runs-on: ubuntu-latest\n    steps:\n      - run: trivy image myapp\n",
        encoding="utf-8",
    )
    _, signals, _ = analyse_pipeline_sync(str(f), "ci.yml", "github_actions")
    assert signals["has_security_scan"] is True


def test_analyse_pipeline_detects_deploy(tmp_path: Path):
    f = tmp_path / "ci.yml"
    f.write_text(
        "jobs:\n  deploy:\n    runs-on: ubuntu-latest\n    steps:\n      - run: kubectl apply -f k8s/\n",
        encoding="utf-8",
    )
    _, signals, _ = analyse_pipeline_sync(str(f), "ci.yml", "github_actions")
    assert signals["has_deploy_stage"] is True


def test_analyse_pipeline_single_job_not_parallel(tmp_path: Path):
    f = tmp_path / "ci.yml"
    f.write_text(
        "jobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hello\n",
        encoding="utf-8",
    )
    _, signals, _ = analyse_pipeline_sync(str(f), "ci.yml", "github_actions")
    assert signals["has_parallel_jobs"] is False


def test_analyse_pipeline_invalid_yaml(tmp_path: Path):
    f = tmp_path / "ci.yml"
    f.write_text("jobs: {\n  broken: [yaml\n", encoding="utf-8")
    _, _, errors = analyse_pipeline_sync(str(f), "ci.yml", "github_actions")
    assert len(errors) >= 1


# ---------------------------------------------------------------------------
# analyse_cicd_sync (integration of engine)
# ---------------------------------------------------------------------------


def test_analyse_cicd_sync_finds_pipeline(sample_repo: Path, file_tree: list[str]):
    pipelines, dockerfiles, signals, errors = analyse_cicd_sync(str(sample_repo), file_tree)
    assert len(pipelines) >= 1
    assert pipelines[0].platform == "github_actions"
    assert signals["runs_tests"] is True
    assert signals["runs_lint"] is True


def test_analyse_cicd_sync_finds_dockerfile(sample_repo: Path, file_tree: list[str]):
    _, dockerfiles, _, _ = analyse_cicd_sync(str(sample_repo), file_tree)
    assert len(dockerfiles) >= 1
    assert dockerfiles[0].multi_stage is True


def test_analyse_cicd_sync_no_ci_files(tmp_path: Path):
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    pipelines, dockerfiles, signals, errors = analyse_cicd_sync(str(tmp_path), ["main.py"])
    assert pipelines == []
    assert dockerfiles == []


# ---------------------------------------------------------------------------
# build_cicd_metrics
# ---------------------------------------------------------------------------


def test_build_metrics_platform_priority(sample_repo: Path, file_tree: list[str]):
    pipelines, dockerfiles, signals, _ = analyse_cicd_sync(str(sample_repo), file_tree)
    metrics = build_cicd_metrics(pipelines, dockerfiles, signals)
    assert metrics.ci_platform == "GitHub Actions"
    assert metrics.has_ci_pipeline is True
    assert metrics.dockerfile_present is True
    assert metrics.multi_stage_build is True


def test_build_metrics_stages_inferred(sample_repo: Path, file_tree: list[str]):
    pipelines, dockerfiles, signals, _ = analyse_cicd_sync(str(sample_repo), file_tree)
    metrics = build_cicd_metrics(pipelines, dockerfiles, signals)
    assert "lint" in metrics.stages_detected
    assert "test" in metrics.stages_detected


def test_build_metrics_no_pipelines():
    metrics = build_cicd_metrics([], [], {k: False for k in [
        "runs_tests", "runs_lint", "has_security_scan",
        "uses_cache", "has_parallel_jobs", "has_deploy_stage",
    ]})
    assert metrics.has_ci_pipeline is False
    assert metrics.ci_platform is None


# ---------------------------------------------------------------------------
# RealCiCdIntelligenceService
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_analyze_returns_dict(sample_repo: Path, file_tree: list[str], service: RealCiCdIntelligenceService):
    result = await service.analyze(file_tree, str(sample_repo))
    assert "ci_platform" in result
    assert result["ci_platform"] == "GitHub Actions"
    assert result["has_pipeline"] is True
    assert result["runs_tests"] is True
    assert result["runs_lint"] is True
    assert result["dockerfile_present"] is True
    assert result["multi_stage_build"] is True


@pytest.mark.asyncio()
async def test_analyze_structured_returns_typed(sample_repo: Path, file_tree: list[str], service: RealCiCdIntelligenceService):
    result = await service.analyze_structured(file_tree, str(sample_repo))
    assert isinstance(result, CiCdAnalysisResult)
    assert result.metrics.has_ci_pipeline is True
    assert len(result.pipeline_details) >= 1
    assert len(result.dockerfile_details) >= 1


@pytest.mark.asyncio()
async def test_analyze_no_local_path(service: RealCiCdIntelligenceService):
    result = await service.analyze([".github/workflows/ci.yml"], local_path=None)
    assert result["has_pipeline"] is True   # detected from file_tree pattern
    assert result["ci_metrics"] == {}


@pytest.mark.asyncio()
async def test_analyze_empty_repo(tmp_path: Path, service: RealCiCdIntelligenceService):
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    result = await service.analyze(["main.py"], str(tmp_path))
    assert result["has_pipeline"] is False
    assert result["dockerfile_present"] is False


@pytest.mark.asyncio()
async def test_analyze_backward_compatible_keys(sample_repo: Path, file_tree: list[str], service: RealCiCdIntelligenceService):
    """Verify stub contract keys are all present."""
    result = await service.analyze(file_tree, str(sample_repo))
    for key in ("ci_platform", "has_pipeline", "stages", "has_deploy_stage",
                "has_security_scan", "has_quality_gate"):
        assert key in result, f"Missing backward-compat key: {key}"


@pytest.mark.asyncio()
async def test_analyze_azure_devops(tmp_path: Path, service: RealCiCdIntelligenceService):
    (tmp_path / "azure-pipelines.yml").write_text(
        textwrap.dedent("""\
            trigger:
              - main
            stages:
              - stage: Test
                jobs:
                  - job: RunTests
                    steps:
                      - script: pytest tests/
              - stage: Deploy
                jobs:
                  - job: DeployProd
                    steps:
                      - script: kubectl apply -f k8s/
        """),
        encoding="utf-8",
    )
    result = await service.analyze(["azure-pipelines.yml"], str(tmp_path))
    assert result["ci_platform"] == "Azure DevOps"
    assert result["runs_tests"] is True
    assert result["has_deploy_stage"] is True
    assert result["has_parallel_jobs"] is True
