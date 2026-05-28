"""PRCommentFormatter — generate structured Markdown PR review comments.

Rules
-----
* Pure function: no I/O, no LLM, no async.
* Produces deterministic, readable Markdown.
* Surfaces only Critical-severity issues (to keep comments concise).
* Always includes a score badge and per-agent breakdown table.
* File references are rendered as inline code paths.
"""
from __future__ import annotations

from app.domain.entities import AgentFinding, EngineeringReviewAggregate
from app.domain.enums import RiskLevel, Severity
from app.infrastructure.github.models import PRDiff

# Score thresholds for badge colouring (emoji only — no external assets needed)
_SCORE_EMOJI: dict[str, str] = {
    "excellent": "🟢",   # 85–100
    "good": "🟡",        # 70–84
    "warning": "🟠",     # 50–69
    "critical": "🔴",    # <50
}

_RISK_EMOJI: dict[RiskLevel, str] = {
    RiskLevel.LOW: "🟢 Low",
    RiskLevel.MEDIUM: "🟡 Medium",
    RiskLevel.HIGH: "🟠 High",
    RiskLevel.CRITICAL: "🔴 Critical",
}

_MAX_CRITICAL_ISSUES = 10   # cap shown in comment to avoid very long posts
_MAX_FILES_SHOWN = 20       # cap on changed-files list


class PRCommentFormatter:
    """Format an ``EngineeringReviewAggregate`` as a GitHub PR comment.

    Usage
    -----
    ::

        body = PRCommentFormatter().generate_markdown_summary(aggregate, pr_diff)
        await github_client.post_comment(owner, repo, pr_number, body)
    """

    def generate_markdown_summary(
        self,
        aggregate: EngineeringReviewAggregate,
        pr_diff: PRDiff,
    ) -> str:
        """Return a Markdown string suitable for posting as a PR comment.

        Sections
        --------
        1. Header — overall score badge + risk level
        2. Changed files (collapsed ``<details>`` block)
        3. Agent score breakdown table
        4. Critical issues (if any)
        5. Footer with review ID
        """
        sections: list[str] = [
            self._header(aggregate),
            self._changed_files_section(pr_diff),
            self._agent_scores_table(aggregate),
            self._critical_issues_section(aggregate),
            self._footer(aggregate),
        ]
        return "\n\n".join(s for s in sections if s)

    # ------------------------------------------------------------------
    # Section renderers
    # ------------------------------------------------------------------

    def _header(self, aggregate: EngineeringReviewAggregate) -> str:
        score = aggregate.overall_score
        emoji = self._score_emoji(score)
        risk = _RISK_EMOJI[aggregate.risk_level]
        return (
            f"## {emoji} Engineering Review — Score: **{score}/100**\n\n"
            f"> **Risk Level:** {risk}"
        )

    def _changed_files_section(self, pr_diff: PRDiff) -> str:
        files = pr_diff.changed_filenames
        if not files:
            return ""
        shown = files[:_MAX_FILES_SHOWN]
        remaining = len(files) - len(shown)
        lines = [f"<details><summary>📂 Changed files ({len(files)})</summary>\n"]
        for filename in shown:
            lines.append(f"- `{filename}`")
        if remaining > 0:
            lines.append(f"- *… and {remaining} more*")
        lines.append("\n</details>")
        return "\n".join(lines)

    def _agent_scores_table(self, aggregate: EngineeringReviewAggregate) -> str:
        if not aggregate.agent_results:
            return ""
        rows = [
            "### 🤖 Agent Scores\n",
            "| Agent | Score | Issues |",
            "|---|---|---|",
        ]
        for finding in aggregate.agent_results:
            emoji = self._score_emoji(finding.score)
            issue_count = len(finding.issues)
            critical_count = sum(
                1 for i in finding.issues if i.severity == Severity.CRITICAL
            )
            issue_cell = (
                f"{issue_count} ({critical_count} critical)"
                if critical_count
                else str(issue_count)
            )
            rows.append(
                f"| {finding.agent_name.value} | {emoji} {finding.score}/100 | {issue_cell} |"
            )
        return "\n".join(rows)

    def _critical_issues_section(
        self, aggregate: EngineeringReviewAggregate
    ) -> str:
        critical_issues = [
            (finding, issue)
            for finding in aggregate.agent_results
            for issue in finding.issues
            if issue.severity == Severity.CRITICAL
        ]
        if not critical_issues:
            return ""

        shown = critical_issues[:_MAX_CRITICAL_ISSUES]
        remaining = len(critical_issues) - len(shown)

        lines = ["### 🚨 Critical Issues\n"]
        for finding, issue in shown:
            location = ""
            if issue.file_path:
                location = f"`{issue.file_path}`"
                if issue.line_number:
                    location += f":{issue.line_number}"
            agent_badge = f"*{finding.agent_name.value}*"
            header_parts = [f"**{issue.title}**", agent_badge]
            if location:
                header_parts.append(location)
            lines.append(f"#### {' · '.join(header_parts)}")
            lines.append(f"{issue.description}\n")
            lines.append(f"> 💡 **Recommendation:** {issue.recommendation}\n")

        if remaining > 0:
            lines.append(
                f"*… and {remaining} more critical issues. "
                "See the full review for details.*"
            )
        return "\n".join(lines)

    @staticmethod
    def _footer(aggregate: EngineeringReviewAggregate) -> str:
        return (
            "---\n"
            f"*Review ID: `{aggregate.review_id}` · "
            "Powered by [Engineering Intelligence Platform](https://github.com)*"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _score_emoji(score: int) -> str:
        if score >= 85:
            return _SCORE_EMOJI["excellent"]
        if score >= 70:
            return _SCORE_EMOJI["good"]
        if score >= 50:
            return _SCORE_EMOJI["warning"]
        return _SCORE_EMOJI["critical"]
