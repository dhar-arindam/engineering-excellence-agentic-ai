"""Safe pull-request service — creates fix PRs only after full safety verification.

Safety rules (all must pass before a PR is created)
----------------------------------------------------
1. ``ValidationReport.passed`` must be ``True`` — no lint / test / type errors.
2. ``BreakingChangeReport.has_breaking_changes`` must be ``False``.
3. ``workspace.list_modified_files()`` must be non-empty.
4. Only ``https://github.com/`` repositories are supported.
5. A ``GITHUB_TOKEN`` environment variable must be set.

PR branch naming
----------------
``fix/engineering-intelligence-{scan_id}``

The branch is created against *base_branch*, committed with the workspace
changes, and a structured PR is opened with:
- Summary of changes
- Validation results table
- Breaking change check result
- List of modified files
- ``ai-suggested`` label

GitHub API calls use ``asyncio.to_thread`` so they never block the event loop.

Usage::

    svc = SafePullRequestService()
    outcome = await svc.create_fix_pr(
        repo_url="https://github.com/owner/repo",
        base_branch="main",
        scan_id=scan_id,
        workspace=workspace,
        validation_report=v_report,
        breaking_report=b_report,
    )
    if outcome.created:
        print(outcome.pr_url)
    else:
        print(outcome.reason)
"""
from __future__ import annotations

import asyncio
import base64
import json
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.core.config import settings
from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.application.breaking_change_detector import BreakingChangeReport
    from app.application.validation_pipeline import ValidationReport
    from app.application.virtual_workspace import VirtualWorkspace

logger = get_logger(__name__)

_PR_LABEL = "ai-suggested"
_BRANCH_PREFIX = "fix/engineering-intelligence-"
_MAX_FILES_PER_COMMIT = 50  # Guard against huge commits


@dataclass
class PROutcome:
    """Result of a ``SafePullRequestService.create_fix_pr`` call."""

    created: bool
    """``True`` if a PR was opened."""

    pr_url: str = ""
    """URL of the created PR (empty if not created)."""

    pr_number: int = 0
    """GitHub PR number (0 if not created)."""

    branch_name: str = ""
    """Name of the fix branch that was pushed."""

    reason: str = ""
    """Human-readable explanation when ``created == False``."""

    warnings: list[str] = field(default_factory=list)
    """Non-blocking warnings attached to the outcome."""


class SafePullRequestService:
    """Creates fix PRs on GitHub only after validation and breaking-change checks pass.

    Args:
        github_token: GitHub personal access token.  Defaults to
            ``settings.github_token``.
    """

    def __init__(self, github_token: str | None = None) -> None:
        self._token = github_token or settings.github_token or ""

    async def create_fix_pr(
        self,
        repo_url: str,
        base_branch: str,
        scan_id: uuid.UUID,
        workspace: "VirtualWorkspace",
        validation_report: "ValidationReport",
        breaking_report: "BreakingChangeReport",
    ) -> PROutcome:
        """Validate safety checks, push a fix branch, and open a PR.

        Returns a :class:`PROutcome` in all cases — never raises for
        recoverable errors (missing token, failed checks, API errors).
        """
        # ------------------------------------------------------------------
        # Pre-flight checks
        # ------------------------------------------------------------------
        outcome = self._pre_flight(
            repo_url, validation_report, breaking_report
        )
        if not outcome.created:
            return outcome

        modified = await workspace.list_modified_files()
        if not modified:
            return PROutcome(
                created=False,
                reason="No files were modified in the workspace — nothing to commit.",
            )
        if len(modified) > _MAX_FILES_PER_COMMIT:
            return PROutcome(
                created=False,
                reason=(
                    f"Too many modified files ({len(modified)} > {_MAX_FILES_PER_COMMIT}). "
                    "Review the patch before creating a PR."
                ),
            )

        # ------------------------------------------------------------------
        # GitHub operations (all in thread to keep event loop free)
        # ------------------------------------------------------------------
        owner, repo_name = _parse_repo(repo_url)
        branch_name = f"{_BRANCH_PREFIX}{str(scan_id)[:8]}"
        pr_body = _build_pr_body(
            modified=modified,
            validation_report=validation_report,
            breaking_report=breaking_report,
            branch_name=branch_name,
        )

        try:
            pr_url, pr_number = await asyncio.to_thread(
                self._github_create_pr,
                owner=owner,
                repo=repo_name,
                base_branch=base_branch,
                new_branch=branch_name,
                workspace=workspace,
                modified_files=modified,
                pr_body=pr_body,
            )
        except Exception as exc:  # noqa: BLE001
            msg = f"GitHub API error: {exc}"
            logger.error("safe_pr_service.github_error", error=msg)
            return PROutcome(created=False, reason=msg)

        logger.info(
            "safe_pr_service.pr_created",
            owner=owner,
            repo=repo_name,
            branch=branch_name,
            pr_number=pr_number,
            pr_url=pr_url,
        )
        return PROutcome(
            created=True,
            pr_url=pr_url,
            pr_number=pr_number,
            branch_name=branch_name,
        )

    # ------------------------------------------------------------------
    # Pre-flight gate
    # ------------------------------------------------------------------

    def _pre_flight(
        self,
        repo_url: str,
        validation_report: "ValidationReport",
        breaking_report: "BreakingChangeReport",
    ) -> PROutcome:
        """Return a blocking PROutcome if any safety check fails, else a sentinel."""
        if not self._token:
            return PROutcome(
                created=False,
                reason="GITHUB_TOKEN is not configured — cannot create PR.",
            )
        if not repo_url.startswith("https://github.com/"):
            return PROutcome(
                created=False,
                reason=f"Unsupported repository URL: {repo_url}. Only GitHub is supported.",
            )
        if breaking_report.has_breaking_changes:
            return PROutcome(
                created=False,
                reason=(
                    "PR not created — breaking changes detected:\n"
                    + "\n".join(f"  • {d}" for d in breaking_report.details)
                ),
            )
        if not validation_report.passed:
            return PROutcome(
                created=False,
                reason=(
                    "PR not created — validation failed:\n"
                    + "\n".join(f"  • {e}" for e in validation_report.errors)
                ),
            )
        # Return a truthy sentinel (caller must still check modified files).
        return PROutcome(created=True)

    # ------------------------------------------------------------------
    # GitHub API helpers (sync — called via asyncio.to_thread)
    # ------------------------------------------------------------------

    def _github_create_pr(
        self,
        owner: str,
        repo: str,
        base_branch: str,
        new_branch: str,
        workspace: "VirtualWorkspace",
        modified_files: list[str],
        pr_body: str,
    ) -> tuple[str, int]:
        """Create branch, commit files, and open a PR.  Returns (pr_url, pr_number)."""
        import urllib.error
        import urllib.request

        headers = {
            "Authorization": f"token {self._token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        base = f"https://api.github.com/repos/{owner}/{repo}"

        # 1 — Get base branch SHA.
        base_sha = self._gh_get(f"{base}/git/ref/heads/{base_branch}", headers)["object"]["sha"]

        # 2 — Create new branch.
        self._gh_post(f"{base}/git/refs", headers, {
            "ref": f"refs/heads/{new_branch}",
            "sha": base_sha,
        })

        # 3 — Commit each modified file via the contents API.
        import asyncio as _asyncio
        from pathlib import Path
        work_root = Path(workspace.work_path)

        for rel in modified_files:
            abs_path = work_root / rel
            if not abs_path.exists():
                # Deleted file — use the delete API.
                try:
                    current = self._gh_get(
                        f"{base}/contents/{rel}?ref={new_branch}", headers
                    )
                    self._gh_put(f"{base}/contents/{rel}", headers, {
                        "message": f"fix: remove {rel}",
                        "sha": current["sha"],
                        "branch": new_branch,
                    })
                except Exception:  # noqa: BLE001
                    pass
                continue

            content_b64 = base64.b64encode(
                abs_path.read_bytes()
            ).decode("ascii")

            payload: dict = {
                "message": f"fix: update {rel}",
                "content": content_b64,
                "branch": new_branch,
            }
            # If file exists on branch, include its SHA for updates.
            try:
                existing = self._gh_get(
                    f"{base}/contents/{rel}?ref={new_branch}", headers
                )
                payload["sha"] = existing["sha"]
            except Exception:  # noqa: BLE001
                pass  # New file — no SHA required

            self._gh_put(f"{base}/contents/{rel}", headers, payload)

        # 4 — Ensure the label exists.
        self._ensure_label(base, headers, _PR_LABEL)

        # 5 — Open the PR.
        pr_data = self._gh_post(f"{base}/pulls", headers, {
            "title": f"fix: AI Engineering Intelligence suggestions [{new_branch}]",
            "body": pr_body,
            "head": new_branch,
            "base": base_branch,
            "draft": False,
        })
        pr_number: int = pr_data["number"]
        pr_url: str = pr_data["html_url"]

        # 6 — Add label.
        try:
            self._gh_post(
                f"{base}/issues/{pr_number}/labels",
                headers,
                {"labels": [_PR_LABEL]},
            )
        except Exception:  # noqa: BLE001
            pass

        return pr_url, pr_number

    def _ensure_label(self, base: str, headers: dict, name: str) -> None:
        try:
            self._gh_get(f"{base}/labels/{name}", headers)
        except Exception:  # noqa: BLE001
            try:
                self._gh_post(f"{base}/labels", headers, {
                    "name": name,
                    "color": "0075ca",
                    "description": "AI-suggested code improvements",
                })
            except Exception:  # noqa: BLE001
                pass

    def _gh_get(self, url: str, headers: dict) -> dict:
        return self._gh_request("GET", url, headers, None)

    def _gh_post(self, url: str, headers: dict, body: dict) -> dict:
        return self._gh_request("POST", url, headers, body)

    def _gh_put(self, url: str, headers: dict, body: dict) -> dict:
        return self._gh_request("PUT", url, headers, body)

    def _gh_request(self, method: str, url: str, headers: dict, body: dict | None) -> dict:
        import urllib.error
        import urllib.request

        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"GitHub API {method} {url} → {exc.code}: {error_body}"
            ) from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_repo(repo_url: str) -> tuple[str, str]:
    """Return (owner, repo_name) from a GitHub URL."""
    clean = repo_url.rstrip("/").rstrip(".git")
    parts = clean.split("/")
    if len(parts) < 5:
        raise ValueError(f"Cannot parse owner/repo from URL: {repo_url}")
    return parts[-2], parts[-1]


def _build_pr_body(
    modified: list[str],
    validation_report: "ValidationReport",
    breaking_report: "BreakingChangeReport",
    branch_name: str,
) -> str:
    """Build a structured PR description."""
    val = validation_report
    brk = breaking_report

    modified_block = "\n".join(f"- `{f}`" for f in modified) or "_None_"
    errors_block = "\n".join(f"- {e}" for e in val.errors) or "_None_"
    breaking_block = "\n".join(f"- {d}" for d in brk.details) or "_None_"

    return f"""## 🤖 AI Engineering Intelligence — Automated Fix

> This PR was created automatically by the Engineering Intelligence platform.
> Branch: `{branch_name}`

---

### 📝 Summary of Changes

The following files were modified to address findings from the scan:

{modified_block}

---

### ✅ Validation Results

| Check | Result |
|-------|--------|
| Tests (pytest) | {"✅ Passed" if val.tests_passed else "❌ Failed"} |
| Type check (mypy/tsc) | {"✅ Passed" if val.type_check_passed else "❌ Failed"} |
| Lint (eslint/ruff) | {"✅ Passed" if val.lint_passed else "❌ Failed"} |

**Errors:**
{errors_block}

---

### 🔍 Breaking Change Analysis

| Status | Details |
|--------|---------|
| {"⚠️ Breaking changes detected" if brk.has_breaking_changes else "✅ No breaking changes"} | See below |

{breaking_block}

---

### ⚠️ Review Checklist

- [ ] Review each changed file manually before merging
- [ ] Run the full test suite locally
- [ ] Verify no unintended side-effects
- [ ] **Do not auto-merge** — human review required

---
_Generated by AI Engineering Intelligence Platform — label: `ai-suggested`_
"""
