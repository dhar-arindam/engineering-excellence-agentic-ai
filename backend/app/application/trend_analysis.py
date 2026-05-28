"""Confidence-decay trend analysis for scan history.

All functions are pure (no I/O, no DB).  The route handler calls these after
fetching scan rows, then maps the result dicts into Pydantic response schemas.

Decay model
-----------
    effective_confidence = original_confidence × exp(−λ × age_days)

where age_days = (now − scan.created_at).total_seconds() / 86400
and λ defaults to DECAY_LAMBDA = 0.05.

Design decisions (rubber-duck reviewed):
- We do NOT filter time_series by decayed confidence — all scans in the
  requested window stay visible for the user.
- Decay only affects aggregation weighting.
- Radar dimensions with no data remain None, not 0.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

DECAY_LAMBDA: float = 0.05
MIN_DISPLAY_CONFIDENCE: float = 0.0  # kept for future use; currently unused


def confidence_decay(original_confidence: float, age_days: float, lambda_: float = DECAY_LAMBDA) -> float:
    """Return effective_confidence after exponential decay."""
    return original_confidence * math.exp(-lambda_ * age_days)


def build_trend_payload(
    repo_id: str,
    scans: list[Any],  # list of ScanModel (avoid import cycle)
    decay_lambda: float = DECAY_LAMBDA,
) -> dict[str, Any]:
    """Compute trend time-series + aggregated stats from a list of ScanModel rows.

    Parameters
    ----------
    repo_id : str
        UUID string of the repository.
    scans : list
        ScanModel rows ordered ASC by created_at. Must have attrs:
        id, created_at (datetime, tz-aware), overall_score (int|None),
        overall_confidence (float|None), radar_json (dict|None).
    decay_lambda : float
        Decay constant λ. Higher = faster decay of old scans' weight.

    Returns
    -------
    dict with keys:
        repo_id        : str
        time_series    : list[dict]  — one per scan, ordered ASC
        aggregated_trend: dict       — weighted stats
    """
    now = datetime.now(UTC)
    time_series: list[dict[str, Any]] = []

    for scan in scans:
        created_at = scan.created_at
        # Handle naive datetimes (shouldn't happen in prod but be safe)
        if created_at is not None and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)

        age_days = (
            (now - created_at).total_seconds() / 86400.0
            if created_at is not None
            else 0.0
        )

        # Use None-safe reads (migration backfill uses 0.5 but could be NULL for very old rows)
        original_conf = scan.overall_confidence if scan.overall_confidence is not None else 0.5
        eff_conf = confidence_decay(original_conf, age_days, decay_lambda)

        # Build radar: each dimension is {score: float|None, confidence: float|None}
        raw_radar = scan.radar_json if isinstance(scan.radar_json, dict) else {}
        radar: dict[str, dict[str, float | None]] = {}
        for dim, data in raw_radar.items():
            if isinstance(data, dict):
                radar[dim] = {
                    "score": float(data["score"]) if data.get("score") is not None else None,
                    "confidence": float(data["confidence"]) if data.get("confidence") is not None else None,
                }
            else:
                radar[dim] = {"score": None, "confidence": None}

        time_series.append({
            "timestamp": created_at.isoformat() if created_at else "",
            "overall_score": float(scan.overall_score or 0),
            "overall_confidence": original_conf,
            "effective_confidence": round(eff_conf, 4),
            "radar": radar,
        })

    # Aggregation: confidence²-decay-weighted score
    total_eff_conf = sum(p["effective_confidence"] for p in time_series)
    if total_eff_conf > 0.0 and time_series:
        agg_score = sum(p["overall_score"] * p["effective_confidence"] for p in time_series) / total_eff_conf
    elif time_series:
        agg_score = sum(p["overall_score"] for p in time_series) / len(time_series)
    else:
        agg_score = 0.0

    avg_eff_conf = total_eff_conf / len(time_series) if time_series else 0.0

    trend_warning: str | None = None
    if time_series and avg_eff_conf < 0.5:
        trend_warning = "Low confidence trend — interpret cautiously"

    return {
        "repo_id": repo_id,
        "time_series": time_series,
        "aggregated_trend": {
            "overall_score": round(agg_score, 1),
            "confidence": round(avg_eff_conf, 4),
            "trend_warning": trend_warning,
        },
    }
