"""Unit tests for SeniorSREAgent data-driven scoring."""
from __future__ import annotations

import pytest

from app.application.agents.sre_agent import _score_sre


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cicd(**kwargs):
    defaults = {
        "has_pipeline": False,
        "runs_tests": False,
        "dockerfile_present": False,
        "multi_stage_build": False,
        "has_security_scan": False,
        "runs_lint": False,
        "uses_cache": False,
        "has_parallel_jobs": False,
        "has_deploy_stage": False,
    }
    return {**defaults, **kwargs}


# ---------------------------------------------------------------------------
# Score ceiling / floor
# ---------------------------------------------------------------------------

def test_perfect_score():
    ctx = _cicd(
        has_pipeline=True,
        runs_tests=True,
        dockerfile_present=True,
        multi_stage_build=True,
        has_security_scan=True,
        runs_lint=True,
        uses_cache=True,
        has_parallel_jobs=True,
        has_deploy_stage=True,
    )
    score, issues, recs = _score_sre("repo", ctx, {})
    assert score == 100
    assert issues == []


def test_zero_score_no_pipeline():
    ctx = _cicd()
    score, issues, recs = _score_sre("repo", ctx, {})
    assert score == 0
    assert any("pipeline" in i.title.lower() for i in issues)


# ---------------------------------------------------------------------------
# Individual pillars
# ---------------------------------------------------------------------------

def test_pipeline_adds_20():
    score_without, _, _ = _score_sre("r", _cicd(), {})
    score_with, _, _ = _score_sre("r", _cicd(has_pipeline=True), {})
    assert score_with - score_without == 20


def test_runs_tests_adds_15():
    base = _cicd(has_pipeline=True)
    s_without, _, _ = _score_sre("r", base, {})
    s_with, _, _ = _score_sre("r", _cicd(has_pipeline=True, runs_tests=True), {})
    assert s_with - s_without == 15


def test_dockerfile_adds_10():
    base = _cicd(has_pipeline=True, runs_tests=True)
    s_without, _, _ = _score_sre("r", base, {})
    s_with, _, _ = _score_sre("r", {**base, "dockerfile_present": True}, {})
    assert s_with - s_without == 10


def test_multi_stage_adds_10():
    base = _cicd(has_pipeline=True, dockerfile_present=True)
    s_without, _, _ = _score_sre("r", base, {})
    s_with, _, _ = _score_sre("r", {**base, "multi_stage_build": True}, {})
    assert s_with - s_without == 10


def test_security_scan_adds_15():
    base = _cicd(has_pipeline=True)
    s_without, _, _ = _score_sre("r", base, {})
    s_with, _, _ = _score_sre("r", {**base, "has_security_scan": True}, {})
    assert s_with - s_without == 15


def test_lint_adds_10():
    base = _cicd(has_pipeline=True)
    s_without, _, _ = _score_sre("r", base, {})
    s_with, _, _ = _score_sre("r", {**base, "runs_lint": True}, {})
    assert s_with - s_without == 10


def test_cache_adds_5():
    base = _cicd(has_pipeline=True)
    s_without, _, _ = _score_sre("r", base, {})
    s_with, _, _ = _score_sre("r", {**base, "uses_cache": True}, {})
    assert s_with - s_without == 5


def test_parallel_jobs_adds_5():
    base = _cicd(has_pipeline=True)
    s_without, _, _ = _score_sre("r", base, {})
    s_with, _, _ = _score_sre("r", {**base, "has_parallel_jobs": True}, {})
    assert s_with - s_without == 5


def test_deploy_stage_adds_10():
    base = _cicd(has_pipeline=True)
    s_without, _, _ = _score_sre("r", base, {})
    s_with, _, _ = _score_sre("r", {**base, "has_deploy_stage": True}, {})
    assert s_with - s_without == 10


# ---------------------------------------------------------------------------
# Issues and recommendations
# ---------------------------------------------------------------------------

def test_no_pipeline_issue_is_high_severity():
    _, issues, _ = _score_sre("r", _cicd(), {})
    assert any(i.severity.value == "High" for i in issues)


def test_pipeline_without_tests_raises_issue():
    ctx = _cicd(has_pipeline=True, runs_tests=False)
    _, issues, _ = _score_sre("r", ctx, {})
    assert any("tests" in i.title.lower() for i in issues)


def test_no_dockerfile_raises_issue():
    ctx = _cicd(has_pipeline=True)
    _, issues, _ = _score_sre("r", ctx, {})
    assert any("dockerfile" in i.title.lower() for i in issues)


def test_no_security_scan_raises_issue():
    ctx = _cicd(has_pipeline=True)
    _, issues, _ = _score_sre("r", ctx, {})
    assert any("security" in i.title.lower() for i in issues)


def test_multi_stage_recommendation_when_only_dockerfile():
    ctx = _cicd(has_pipeline=True, dockerfile_present=True, multi_stage_build=False)
    _, _, recs = _score_sre("r", ctx, {})
    assert any("multi-stage" in r.lower() for r in recs)


# ---------------------------------------------------------------------------
# Score is bounded
# ---------------------------------------------------------------------------

def test_score_never_exceeds_100():
    ctx = _cicd(**{k: True for k in [
        "has_pipeline", "runs_tests", "dockerfile_present", "multi_stage_build",
        "has_security_scan", "runs_lint", "uses_cache", "has_parallel_jobs", "has_deploy_stage",
    ]})
    score, _, _ = _score_sre("r", ctx, {})
    assert score <= 100


def test_score_never_below_zero():
    score, _, _ = _score_sre("r", _cicd(), {})
    assert score >= 0
