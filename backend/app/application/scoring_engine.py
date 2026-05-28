"""Backward-compatibility shim — canonical implementation is in ``scoring``."""
# ruff: noqa: F401
from app.application.scoring import (
    AGENT_WEIGHTS,
    ScoringEngine,
    compute_risk_level,
    compute_weighted_score,
)
