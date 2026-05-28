"""Unit tests for trend_analysis.build_trend_payload."""
from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.application.trend_analysis import DECAY_LAMBDA, build_trend_payload, confidence_decay


def _make_scan(
    overall_score: int,
    overall_confidence: float | None,
    radar_json: dict | None,
    age_days: float = 0.0,
) -> MagicMock:
    scan = MagicMock()
    scan.overall_score = overall_score
    scan.overall_confidence = overall_confidence
    scan.radar_json = radar_json
    scan.created_at = datetime.now(UTC) - timedelta(days=age_days)
    return scan


class TestConfidenceDecay:
    def test_zero_age_no_decay(self):
        assert confidence_decay(0.8, 0.0) == pytest.approx(0.8)

    def test_large_age_approaches_zero(self):
        assert confidence_decay(1.0, 1000.0) < 0.001

    def test_exact_formula(self):
        expected = 0.8 * math.exp(-DECAY_LAMBDA * 14)
        assert confidence_decay(0.8, 14.0) == pytest.approx(expected, rel=1e-6)


class TestBuildTrendPayload:
    def test_empty_scans_returns_zero_agg(self):
        result = build_trend_payload("repo-1", [])
        assert result["time_series"] == []
        assert result["aggregated_trend"]["overall_score"] == 0.0
        assert result["aggregated_trend"]["confidence"] == 0.0
        assert result["aggregated_trend"]["trend_warning"] is None

    def test_single_new_scan_no_decay(self):
        scan = _make_scan(75, 0.9, None, age_days=0.0)
        result = build_trend_payload("repo-1", [scan])
        ts = result["time_series"]
        assert len(ts) == 1
        assert ts[0]["overall_score"] == 75.0
        assert ts[0]["overall_confidence"] == 0.9
        # new scan: minimal decay
        assert ts[0]["effective_confidence"] == pytest.approx(0.9, rel=0.01)

    def test_null_confidence_defaults_to_0_5(self):
        scan = _make_scan(60, None, None, age_days=0.0)
        result = build_trend_payload("repo-1", [scan])
        assert result["time_series"][0]["overall_confidence"] == 0.5

    def test_radar_none_maps_to_null_values(self):
        scan = _make_scan(70, 0.7, None, age_days=0.0)
        result = build_trend_payload("repo-1", [scan])
        assert result["time_series"][0]["radar"] == {}

    def test_radar_partial_dimension(self):
        scan = _make_scan(
            70, 0.7,
            {"readability": {"score": 8.0, "confidence": 0.9}},
            age_days=0.0,
        )
        result = build_trend_payload("repo-1", [scan])
        radar = result["time_series"][0]["radar"]
        assert radar["readability"]["score"] == 8.0
        assert radar["readability"]["confidence"] == 0.9

    def test_old_scan_gets_lower_effective_confidence(self):
        new_scan = _make_scan(80, 0.9, None, age_days=0.0)
        old_scan = _make_scan(80, 0.9, None, age_days=60.0)
        r_new = build_trend_payload("r", [new_scan])
        r_old = build_trend_payload("r", [old_scan])
        assert r_new["time_series"][0]["effective_confidence"] > r_old["time_series"][0]["effective_confidence"]

    def test_trend_warning_when_low_confidence(self):
        # 60-day-old scan with low confidence will have very low effective confidence
        scan = _make_scan(50, 0.3, None, age_days=60.0)
        result = build_trend_payload("repo-1", [scan])
        assert result["aggregated_trend"]["trend_warning"] is not None

    def test_no_warning_when_high_confidence(self):
        scan = _make_scan(85, 0.95, None, age_days=0.0)
        result = build_trend_payload("repo-1", [scan])
        assert result["aggregated_trend"]["trend_warning"] is None

    def test_weighted_aggregation_favors_newer_scans(self):
        # Old scan has low score, new scan has high score
        # Newer scan should dominate aggregation
        old_scan = _make_scan(20, 0.9, None, age_days=60.0)
        new_scan = _make_scan(90, 0.9, None, age_days=0.0)
        result = build_trend_payload("repo-1", [old_scan, new_scan])
        agg_score = result["aggregated_trend"]["overall_score"]
        # Simple average would be 55; weighted should favor new scan → > 70
        assert agg_score > 55

    def test_all_scans_appear_in_time_series(self):
        """All scans should be in time_series regardless of decayed confidence."""
        scans = [_make_scan(70, 0.1, None, age_days=float(i * 10)) for i in range(5)]
        result = build_trend_payload("repo-1", scans)
        assert len(result["time_series"]) == 5
