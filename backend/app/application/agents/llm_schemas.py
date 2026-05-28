"""Pydantic models for structured LLM responses.

These are the shapes the LLM must return — intentionally simpler than domain
entities (no UUIDs, no computed fields) to keep prompts small and parsing robust.
They are converted to domain entities after validation.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class LLMIssue(BaseModel):
    """Single issue as returned by the LLM."""

    severity: Literal["Low", "Medium", "High", "Critical"]
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=10, max_length=500)
    recommendation: str = Field(min_length=10, max_length=300)


class LLMAgentResponse(BaseModel):
    """Top-level structured response every LLM-backed agent must produce."""

    score: int = Field(ge=0, le=100)
    summary: str = Field(min_length=20, max_length=600)
    issues: list[LLMIssue] = Field(default_factory=list, max_length=10)
    recommendations: list[str] = Field(default_factory=list, max_length=8)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    confidence_reason: str = Field(default="", max_length=300)
