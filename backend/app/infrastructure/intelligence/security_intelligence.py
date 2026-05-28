"""Real SecurityIntelligenceService — deterministic regex-based security scanning.

Implements the SecurityIntelligenceService ABC from the application layer.
All blocking I/O (file reads, regex scanning) runs in an asyncio executor
so the event loop is never blocked.

No LLM calls. No external scanners. No side effects beyond reading files.
Secret values are NEVER stored or logged — only redacted previews.
"""
from __future__ import annotations

import asyncio
from typing import Any

from app.application.tool_interfaces import SecurityIntelligenceService
from app.core.logging import get_logger
from app.infrastructure.intelligence.security_engine import (
    build_security_metrics,
    detect_dependency_files,
    scan_repo_sync,
)
from app.infrastructure.intelligence.security_models import SecurityAnalysisResult

logger = get_logger(__name__)

# Cap findings to keep response payloads manageable
_MAX_SECRET_FINDINGS = 50
_MAX_INSECURE_FINDINGS = 100


class RealSecurityIntelligenceService(SecurityIntelligenceService):
    """
    Deterministic security intelligence using regex pattern matching.

    Scans for:
    - Potential secrets / credentials (API keys, passwords, tokens, private keys)
    - Insecure patterns (HTTP URLs, weak hashes, eval usage, shell injection)
    - Dependency manifest files
    - Security tooling configuration (Dependabot, Snyk, SECURITY.md)

    The ``analyze()`` method satisfies the ``SecurityIntelligenceService`` ABC
    and returns a dict that is a superset of the stub contract.

    For callers that want typed results, use ``analyze_structured()``.
    """

    async def analyze(
        self,
        file_tree: list[str],
        local_path: str | None = None,
    ) -> dict[str, Any]:
        """
        Run security scan and return a dict compatible with the agent tool context.

        Extends the stub output with:
          - ``secret_count``                total potential secrets found
          - ``insecure_pattern_count``
          - ``has_security_policy``         SECURITY.md or equivalent
          - ``hardcoded_password_instances``
          - ``security_metrics``            SecurityMetrics (serialised)
          - ``secret_findings``             list of SecretFinding dicts (capped)
          - ``insecure_findings``           list of InsecurePatternFinding dicts (capped)
          - ``scan_errors``
        """
        if not local_path:
            logger.warning("security_intelligence.no_local_path")
            return self._empty_result(file_tree)

        result = await self.analyze_structured(file_tree, local_path)
        m = result.metrics

        return {
            # Backward-compatible keys (match stub + ABC contract)
            "hardcoded_secrets_found": m.secret_count > 0,
            "secret_locations": m.potential_secrets_found,
            "vulnerable_dependencies": [],        # requires pip-audit / safety subprocess
            "has_dependency_scanner": m.has_dependency_scanner,
            "security_headers_configured": False, # requires HTTP request — out of scope
            # Extended keys
            "secret_count": m.secret_count,
            "insecure_pattern_count": m.insecure_pattern_count,
            "insecure_patterns": m.insecure_patterns,
            "dependency_files": m.dependency_files,
            "uses_https": m.uses_https,
            "has_requirements_txt": m.has_requirements_txt,
            "hardcoded_password_instances": m.hardcoded_password_instances,
            "has_security_policy": m.has_security_policy,
            "scanned_files": m.scanned_files,
            "security_metrics": m.model_dump(),
            "secret_findings": [sf.model_dump() for sf in result.secret_findings],
            "insecure_findings": [inf.model_dump() for inf in result.insecure_findings],
            "scan_errors": result.scan_errors,
        }

    async def analyze_structured(
        self,
        file_tree: list[str],
        local_path: str,
    ) -> SecurityAnalysisResult:
        """Run analysis and return typed ``SecurityAnalysisResult``."""
        logger.info(
            "security_intelligence.start",
            total_files=len(file_tree),
            root=local_path,
        )

        loop = asyncio.get_running_loop()
        all_secrets, all_insecure, scan_errors = await loop.run_in_executor(
            None, scan_repo_sync, local_path, file_tree
        )

        # Count scanned files (files that passed _should_scan filter)
        from app.infrastructure.intelligence.security_engine import _should_scan
        scanned = sum(1 for f in file_tree if _should_scan(f))

        # Cap findings before building metrics to prevent huge payloads
        capped_secrets = all_secrets[:_MAX_SECRET_FINDINGS]
        capped_insecure = all_insecure[:_MAX_INSECURE_FINDINGS]

        metrics = build_security_metrics(all_secrets, all_insecure, file_tree, scanned)

        logger.info(
            "security_intelligence.done",
            secrets=len(all_secrets),
            insecure=len(all_insecure),
            dep_files=len(metrics.dependency_files),
            scan_errors=len(scan_errors),
        )

        return SecurityAnalysisResult(
            metrics=metrics,
            secret_findings=capped_secrets,
            insecure_findings=capped_insecure,
            scan_errors=scan_errors,
        )

    @staticmethod
    def _empty_result(file_tree: list[str]) -> dict[str, Any]:
        dep_files = detect_dependency_files(file_tree)
        has_req = any(
            f.endswith("requirements.txt") or f.endswith("requirements-dev.txt")
            for f in file_tree
        )
        return {
            "hardcoded_secrets_found": False,
            "secret_locations": [],
            "vulnerable_dependencies": [],
            "has_dependency_scanner": False,
            "security_headers_configured": False,
            "secret_count": 0,
            "insecure_pattern_count": 0,
            "insecure_patterns": [],
            "dependency_files": dep_files,
            "uses_https": True,
            "has_requirements_txt": has_req,
            "hardcoded_password_instances": [],
            "has_security_policy": False,
            "scanned_files": 0,
            "security_metrics": {},
            "secret_findings": [],
            "insecure_findings": [],
            "scan_errors": [],
        }
