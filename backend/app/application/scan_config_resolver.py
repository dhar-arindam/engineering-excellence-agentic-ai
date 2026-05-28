"""Scan configuration resolver.

Translates a raw ``ScanConfig`` dict (from the API request or DB JSON) into a
:class:`ScanExecutionPlan` that the :class:`~app.application.scan_orchestrator.ScanOrchestrator`
uses to control which agents run and how deeply to scan.

Mode defaults
-------------
+-----------------+-----------+-----+-----+----------+----------+
| mode            | max_files | QA  | Dev | Security | Architect|
+=================+===========+=====+=====+==========+==========+
| quick           |       200 |  ✔  |  ✔  |    ✔     |    ✗     |
| deep (default)  |     10000 |  ✔  |  ✔  |    ✔     |    ✔     |
| security-only   |     10000 |  ✗  |  ✗  |    ✔     |    ✗     |
+-----------------+-----------+-----+-----+----------+----------+

If ``include_agents`` is provided it *replaces* the mode's agent selection.
If ``exclude_agents`` is provided it is subtracted after include/mode selection.
``max_files`` in the config object always overrides the mode default.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.enums import AgentName

# All five agents as their short alias names for config resolution.
_ALL_AGENT_ALIASES: list[str] = ["qa", "dev", "architect", "sre", "security"]

# Alias → AgentName mapping.
_ALIAS_TO_AGENT: dict[str, AgentName] = {
    "qa":        AgentName.SENIOR_QA,
    "dev":       AgentName.SENIOR_DEVELOPER,
    "architect": AgentName.SENIOR_ARCHITECT,
    "sre":       AgentName.SENIOR_SRE,
    "security":  AgentName.SECURITY_EXPERT,
}

# Mode → (default_max_files, enabled_aliases, enable_drift)
_MODE_DEFAULTS: dict[str, tuple[int, list[str], bool]] = {
    "quick": (
        200,
        ["qa", "dev", "security", "sre"],
        False,  # skip architecture drift in quick mode
    ),
    "standard": (
        2_000,
        _ALL_AGENT_ALIASES,
        True,
    ),
    "deep": (
        10_000,
        _ALL_AGENT_ALIASES,
        True,
    ),
    "security-only": (
        10_000,
        ["security"],
        False,
    ),
    # Underscore alias sent by the frontend (maps to same config as "security-only")
    "security_only": (
        10_000,
        ["security"],
        False,
    ),
}


@dataclass(frozen=True)
class ScanExecutionPlan:
    """Resolved, immutable execution plan consumed by :class:`ScanOrchestrator`."""

    agents_to_run: list[AgentName]
    """Ordered list of agents that should execute for this scan."""

    max_files: int
    """Maximum number of files to include during ingestion."""

    enable_drift: bool
    """Whether architecture drift detection should run."""

    enable_trend_update: bool = True
    """Whether to record trend data after scoring."""

    fail_on_high_severity: bool = False
    """If True, a HIGH/CRITICAL finding transitions the scan to 'failed'."""

    allow_auto_fix: bool = False
    """If True, the orchestrator will attempt to generate and submit a fix PR."""


class ScanConfigResolver:
    """Resolves a raw config dict into a :class:`ScanExecutionPlan`.

    Usage::

        plan = ScanConfigResolver().resolve({"mode": "quick", "exclude_agents": ["sre"]})
    """

    def resolve(self, config: dict | None) -> ScanExecutionPlan:
        """Build a :class:`ScanExecutionPlan` from a raw config dict.

        All keys are optional; missing values fall back to the mode defaults.

        Args:
            config: Dict from ``ScanConfig.model_dump()`` or ``None`` for
                    full defaults.

        Returns:
            An immutable :class:`ScanExecutionPlan`.
        """
        cfg = config or {}

        mode: str = cfg.get("mode") or "deep"
        if mode not in _MODE_DEFAULTS:
            mode = "deep"

        default_max_files, default_aliases, default_drift = _MODE_DEFAULTS[mode]

        # Mapping from frontend AgentType (uppercase) to lowercase alias.
        _FRONTEND_TO_ALIAS: dict[str, str] = {
            "QA": "qa",
            "Dev": "dev",
            "Architect": "architect",
            "SRE": "sre",
            "Security": "security",
        }

        # Determine which agent aliases will run.
        include_aliases: list[str] | None = cfg.get("include_agents")
        exclude_aliases: list[str] | None = cfg.get("exclude_agents")

        # If include_agents is not set, check the frontend `agents` field
        # (uppercase AgentType[]) and map it to lowercase aliases.
        if include_aliases is None:
            frontend_agents: list[str] | None = cfg.get("agents")
            if frontend_agents:
                include_aliases = [
                    _FRONTEND_TO_ALIAS[a]
                    for a in frontend_agents
                    if a in _FRONTEND_TO_ALIAS
                ] or None

        if include_aliases is not None:
            # Explicit include list overrides mode defaults.
            active_aliases = [a for a in include_aliases if a in _ALIAS_TO_AGENT]
        else:
            active_aliases = list(default_aliases)

        if exclude_aliases:
            active_aliases = [a for a in active_aliases if a not in exclude_aliases]

        agents_to_run = [
            _ALIAS_TO_AGENT[alias]
            for alias in active_aliases
            if alias in _ALIAS_TO_AGENT
        ]

        # max_files: explicit config value overrides mode default.
        raw_max = cfg.get("max_files")
        max_files = int(raw_max) if raw_max and int(raw_max) > 0 else default_max_files

        # drift is disabled in quick/security-only modes or if no architect agent.
        has_architect = AgentName.SENIOR_ARCHITECT in agents_to_run
        enable_drift = default_drift and has_architect

        return ScanExecutionPlan(
            agents_to_run=agents_to_run,
            max_files=max_files,
            enable_drift=enable_drift,
            fail_on_high_severity=bool(cfg.get("fail_on_high_severity", False)),
            allow_auto_fix=bool(cfg.get("allow_auto_fix", False)),
        )
