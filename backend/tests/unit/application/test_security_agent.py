"""Unit tests for SecurityExpertAgent data-driven scoring."""
from __future__ import annotations

import pytest

from app.application.agents.security_agent import _score_security


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sec(**kwargs):
    defaults = {
        "secret_count": 0,
        "secret_locations": [],
        "insecure_pattern_count": 0,
        "insecure_patterns": [],
        "uses_https": True,
        "has_dependency_scanner": False,
        "has_security_policy": False,
        "hardcoded_password_instances": [],
    }
    return {**defaults, **kwargs}


def _cicd(**kwargs):
    defaults = {"has_security_scan": False}
    return {**defaults, **kwargs}


# ---------------------------------------------------------------------------
# Perfect and zero scores
# ---------------------------------------------------------------------------

def test_perfect_score():
    sec = _sec(
        secret_count=0,
        insecure_pattern_count=0,
        uses_https=True,
        has_dependency_scanner=True,
        has_security_policy=True,
        hardcoded_password_instances=[],
    )
    score, issues, recs = _score_security("repo", sec, {})
    assert score == 100
    assert issues == []


def test_maximum_penalty():
    """All bad signals → critical score."""
    sec = _sec(
        secret_count=10,
        insecure_pattern_count=15,
        uses_https=False,
        has_dependency_scanner=False,
        has_security_policy=False,
    )
    score, issues, _ = _score_security("repo", sec, {})
    assert score < 50  # Critical risk threshold


# ---------------------------------------------------------------------------
# Secret scoring
# ---------------------------------------------------------------------------

def test_zero_secrets_adds_40():
    s_no_sec, _, _ = _score_security("r", _sec(secret_count=0), {})
    assert s_no_sec >= 40  # 40 pts for no secrets + https(15) = 55 base


def test_1_to_2_secrets_adds_20():
    s_clean, _, _ = _score_security("r", _sec(secret_count=0), {})
    s_few, _, _ = _score_security("r", _sec(secret_count=1), {})
    assert s_clean - s_few == 20  # 40 vs 20 pts for secrets component


def test_3_to_5_secrets_adds_10():
    s_few, _, _ = _score_security("r", _sec(secret_count=1), {})
    s_more, _, _ = _score_security("r", _sec(secret_count=3), {})
    assert s_few - s_more == 10  # 20 vs 10


def test_many_secrets_adds_0():
    s_more, _, _ = _score_security("r", _sec(secret_count=5), {})
    s_many, _, _ = _score_security("r", _sec(secret_count=6), {})
    assert s_more - s_many == 10  # 10 vs 0


def test_critical_issue_for_many_secrets():
    _, issues, _ = _score_security("r", _sec(secret_count=10), {})
    assert any(i.severity.value == "Critical" for i in issues)


# ---------------------------------------------------------------------------
# HTTPS
# ---------------------------------------------------------------------------

def test_https_adds_15():
    s_with, _, _ = _score_security("r", _sec(uses_https=True), {})
    s_without, _, _ = _score_security("r", _sec(uses_https=False), {})
    assert s_with - s_without == 15


def test_no_https_creates_high_issue():
    _, issues, _ = _score_security("r", _sec(uses_https=False), {})
    assert any(i.severity.value == "High" for i in issues)


# ---------------------------------------------------------------------------
# Dependency scanner
# ---------------------------------------------------------------------------

def test_dep_scanner_from_sec_ctx_adds_15():
    s_with, _, _ = _score_security("r", _sec(has_dependency_scanner=True), {})
    s_without, _, _ = _score_security("r", _sec(has_dependency_scanner=False), {})
    assert s_with - s_without == 15


def test_dep_scanner_from_cicd_adds_15():
    s_with, _, _ = _score_security("r", _sec(), _cicd(has_security_scan=True))
    s_without, _, _ = _score_security("r", _sec(), _cicd())
    assert s_with - s_without == 15


# ---------------------------------------------------------------------------
# Insecure patterns
# ---------------------------------------------------------------------------

def test_zero_insecure_patterns_adds_20():
    s_clean, _, _ = _score_security("r", _sec(insecure_pattern_count=0), {})
    s_some, _, _ = _score_security("r", _sec(insecure_pattern_count=1), {})
    assert s_clean > s_some


def test_1_to_3_insecure_partial_score():
    s_clean, _, _ = _score_security("r", _sec(insecure_pattern_count=0), {})
    s_few, _, _ = _score_security("r", _sec(insecure_pattern_count=2), {})
    assert s_clean - s_few == 8  # 20 - 12


def test_many_insecure_patterns_critical_issue():
    _, issues, _ = _score_security("r", _sec(insecure_pattern_count=10), {})
    assert any("insecure" in i.title.lower() for i in issues)


# ---------------------------------------------------------------------------
# Security policy
# ---------------------------------------------------------------------------

def test_security_policy_adds_10():
    s_with, _, _ = _score_security("r", _sec(has_security_policy=True), {})
    s_without, _, _ = _score_security("r", _sec(has_security_policy=False), {})
    assert s_with - s_without == 10


def test_no_security_policy_adds_recommendation():
    _, _, recs = _score_security("r", _sec(has_security_policy=False), {})
    assert any("SECURITY.md" in r for r in recs)


# ---------------------------------------------------------------------------
# Hardcoded passwords
# ---------------------------------------------------------------------------

def test_hardcoded_password_creates_critical_issue():
    sec = _sec(hardcoded_password_instances=["config.py:42"])
    _, issues, _ = _score_security("r", sec, {})
    assert any(i.severity.value == "Critical" for i in issues)


# ---------------------------------------------------------------------------
# Score bounds
# ---------------------------------------------------------------------------

def test_score_bounded_0_to_100():
    for secret_count in [0, 1, 3, 6, 10]:
        for insecure in [0, 2, 5, 10]:
            sec = _sec(secret_count=secret_count, insecure_pattern_count=insecure)
            score, _, _ = _score_security("r", sec, {})
            assert 0 <= score <= 100, f"score={score} out of range for secret={secret_count}, insecure={insecure}"
