"""ORM model → frontend-aligned schema mappers.

Shared by scans.py and repositories.py route handlers to avoid duplication.
"""
from __future__ import annotations

from app.api.schemas import (
    AgentScoreSchema,
    ArchitectureDriftSchema,
    IssueSchema,
    RadarDimensionSchema,
    RepositoryFullSchema,
    RepositoryListItemSchema,
    ScanFullSchema,
    ScanSummarySchema,
    TrendPointSchema,
)
from app.infrastructure.db.models import RepositoryModel, ScanModel

# ---------------------------------------------------------------------------
# Agent name → frontend AgentType mapping
# ---------------------------------------------------------------------------

_AGENT_TYPE_MAP: dict[str, str] = {
    "seniorqaagent": "QA",
    "qa": "QA",
    "seniorarchitectagent": "Architect",
    "architect": "Architect",
    "seniordeveloperagent": "Dev",
    "seniordeveloper": "Dev",
    "developer": "Dev",
    "dev": "Dev",
    "seniorsreagent": "SRE",
    "seniorsre": "SRE",
    "sre": "SRE",
    "securityexpertagent": "Security",
    "securityexpert": "Security",
    "security": "Security",
}

_SEVERITY_NORM: dict[str, str] = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "info": "Info",
}

_RISK_NORM: dict[str, str] = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "critical": "Critical",
}


def _agent_type(agent_name: str) -> str:
    key = agent_name.lower().replace(" ", "")
    return _AGENT_TYPE_MAP.get(key, agent_name)


def _norm_severity(raw: str) -> str:
    return _SEVERITY_NORM.get(str(raw).lower(), "Medium")


def _norm_risk(raw: str | None) -> str:
    if not raw:
        return "Low"
    return _RISK_NORM.get(raw.lower(), raw.capitalize())


# ---------------------------------------------------------------------------
# Scan mappers
# ---------------------------------------------------------------------------


def scan_to_summary(scan: ScanModel, repo_name: str = "") -> ScanSummarySchema:
    """Map a ScanModel to the lightweight ScanSummarySchema (frontend ScanSummary)."""
    config = scan.scan_config_json or {}
    operation_mode = (
        config.get("operation_mode", "analyze") if isinstance(config, dict) else "analyze"
    )
    return ScanSummarySchema(
        id=str(scan.id),
        repository_id=str(scan.repository_id),
        repository_name=repo_name,
        branch=scan.branch or "main",
        commit_sha=getattr(scan, "commit_sha", None) or "",
        date=scan.created_at.isoformat() if scan.created_at else "",
        status=scan.status,
        mode=scan.scan_mode or "deep",
        operation_mode=operation_mode,
        source_type=scan.source_type or "github",
        overall_score=scan.overall_score or 0,
        risk=_norm_risk(scan.risk_level),
    )


def scan_to_full(scan: ScanModel, repo_name: str = "") -> ScanFullSchema:
    """Map a ScanModel (with eager-loaded agent_results) to the full ScanFullSchema.

    This matches the frontend ``Scan`` interface exactly so the scan detail
    page renders without crashes.
    """
    agents: list[AgentScoreSchema] = []
    all_issues: list[IssueSchema] = []

    for r in scan.agent_results or []:
        agent_type = _agent_type(r.agent_name)
        issue_list = r.issues if isinstance(r.issues, list) else []

        agents.append(
            AgentScoreSchema(
                agent=agent_type,
                score=r.score,
                delta=0,
                issue_count=len(issue_list),
                description=r.summary or "",
                confidence=float(getattr(r, "confidence", 0.5) or 0.5),
                confidence_reason=str(getattr(r, "confidence_reason", "") or ""),
            )
        )

        for i, issue in enumerate(issue_list):
            if not isinstance(issue, dict):
                continue
            line_raw = issue.get("line_number") or issue.get("line")
            try:
                line_num = int(line_raw) if line_raw is not None else 0
            except (TypeError, ValueError):
                line_num = 0

            short_id = f"{str(scan.id)[:8]}-{r.agent_name[:3].lower()}-{i}"
            raw_title = issue.get("title") or issue.get("description") or "Untitled"
            title = str(raw_title)[:120]
            all_issues.append(
                IssueSchema(
                    id=short_id,
                    severity=_norm_severity(str(issue.get("severity", "Medium"))),
                    agent=agent_type,
                    file_path=str(issue.get("file_path") or issue.get("location") or ""),
                    line_number=line_num,
                    title=title,
                    description=str(issue.get("description") or issue.get("message") or ""),
                    recommendation=str(
                        issue.get("recommendation") or issue.get("fix") or ""
                    ),
                )
            )

    summary_dict = scan_to_summary(scan, repo_name).model_dump()
    summary_dict["issue_count"] = len(all_issues)

    # Map radar from DB (old scans return {} — frontend handles empty gracefully)
    radar: dict[str, RadarDimensionSchema] = {}
    raw_radar = getattr(scan, "radar_json", None) or {}
    if isinstance(raw_radar, dict):
        for dim_name, dim_data in raw_radar.items():
            if isinstance(dim_data, dict):
                radar[dim_name] = RadarDimensionSchema(
                    score=float(dim_data.get("score", 0.0)),
                    confidence=float(dim_data.get("confidence", 0.0)),
                )

    # Build top_risks: top 5 issues sorted Critical > High > Medium > Low
    _sev_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
    top_risks = sorted(all_issues, key=lambda i: _sev_order.get(i.severity, 5))[:5]

    overall_confidence = float(getattr(scan, "overall_confidence", None) or 0.5)

    return ScanFullSchema(
        **summary_dict,
        repository_url=scan.source_reference if (scan.source_type or "") == "github" else None,
        agents=agents,
        issues=all_issues,
        drift=ArchitectureDriftSchema(),
        read_only=True,
        patch_available=bool(scan.patch_diff),
        overall_confidence=overall_confidence,
        radar=radar,
        top_risks=top_risks,
    )


# ---------------------------------------------------------------------------
# Repository mappers
# ---------------------------------------------------------------------------


def repo_to_list_item(
    repo: RepositoryModel,
    latest_scan: ScanModel | None,
    scan_count: int = 0,
) -> RepositoryListItemSchema:
    """Map a RepositoryModel + its latest scan to RepositoryListItemSchema."""
    overall_score = 0
    risk = "Low"
    last_scan_date = ""
    open_issues = 0

    if latest_scan:
        overall_score = latest_scan.overall_score or 0
        risk = _norm_risk(latest_scan.risk_level)
        last_scan_date = (
            latest_scan.created_at.isoformat() if latest_scan.created_at else ""
        )
        if latest_scan.agent_results:
            open_issues = sum(
                len(r.issues) if isinstance(r.issues, list) else 0
                for r in latest_scan.agent_results
            )

    source_type = repo.source_type or "local"
    # Don't expose internal filesystem paths in the API response.
    repository_url = repo.repo_url if source_type == "github" else None

    return RepositoryListItemSchema(
        id=str(repo.id),
        name=repo.name,
        description=repo.description or "",
        language=repo.language or "",
        source_type=source_type,
        repository_url=repository_url,
        local_path=None,
        overall_score=overall_score,
        delta=0,
        risk=risk,
        last_scan_date=last_scan_date,
        open_issues=open_issues,
        team_size=repo.team_size or 0,
        scan_count=scan_count,
    )


def repo_to_full(
    repo: RepositoryModel,
    scans: list[ScanModel],
    scan_count: int = 0,
) -> RepositoryFullSchema:
    """Map a RepositoryModel + all its scans (agents loaded) to RepositoryFullSchema."""
    sorted_scans = sorted(scans, key=lambda s: s.created_at or 0, reverse=True)
    latest = sorted_scans[0] if sorted_scans else None

    base = repo_to_list_item(repo, latest, scan_count)

    # Agent scores from the latest completed scan.
    agents: list[AgentScoreSchema] = []
    if latest and latest.agent_results:
        for r in latest.agent_results:
            issue_list = r.issues if isinstance(r.issues, list) else []
            agents.append(
                AgentScoreSchema(
                    agent=_agent_type(r.agent_name),
                    score=r.score,
                    delta=0,
                    issue_count=len(issue_list),
                    description=r.summary or "",
                )
            )

    # Trend: oldest-first, completed scans only.
    trend: list[TrendPointSchema] = []
    for scan in reversed(sorted_scans):
        if scan.status == "completed" and scan.overall_score:
            label = scan.created_at.strftime("%b %d") if scan.created_at else ""
            trend.append(
                TrendPointSchema(
                    label=label,
                    score=scan.overall_score,
                    date=scan.created_at.isoformat() if scan.created_at else "",
                )
            )

    # Scan history (summary, newest first, max 20).
    scan_summaries = [scan_to_summary(s, repo.name) for s in sorted_scans[:20]]

    return RepositoryFullSchema(
        **base.model_dump(),
        agents=agents,
        trend=trend,
        scans=scan_summaries,
    )
