"""Abstract interfaces for intelligence services (MCP tool abstraction layer).

These interfaces live in the application layer — infrastructure provides implementations.
Agents receive these via constructor injection, keeping them decoupled from infrastructure.
"""
from __future__ import annotations

import abc
from typing import Any


class CodeIntelligenceService(abc.ABC):
    """Provides static code analysis data: complexity, duplication, linting."""

    @abc.abstractmethod
    async def analyze(self, file_tree: list[str], local_path: str | None = None) -> dict[str, Any]:
        """
        Returns:
            {
              "languages": {"Python": 80, "YAML": 20},
              "total_files": int,
              "avg_complexity": float,
              "duplication_ratio": float,
              "lint_violations": [{"file": str, "rule": str, "severity": str}],
            }
        """


class TestIntelligenceService(abc.ABC):
    """Provides test coverage and test quality metrics."""

    @abc.abstractmethod
    async def analyze(self, file_tree: list[str], local_path: str | None = None) -> dict[str, Any]:
        """
        Returns:
            {
              "coverage_percent": float | None,
              "test_file_count": int,
              "test_frameworks": list[str],
              "has_ci_coverage_gate": bool,
              "flaky_test_indicators": list[str],
            }
        """


class CiCdIntelligenceService(abc.ABC):
    """Inspects CI/CD pipeline configurations."""

    @abc.abstractmethod
    async def analyze(self, file_tree: list[str], local_path: str | None = None) -> dict[str, Any]:
        """
        Returns:
            {
              "ci_platform": str | None,
              "has_pipeline": bool,
              "stages": list[str],
              "has_deploy_stage": bool,
              "has_security_scan": bool,
              "has_quality_gate": bool,
            }
        """


class SecurityIntelligenceService(abc.ABC):
    """Scans for secrets, dependency vulnerabilities, and security misconfigurations."""

    @abc.abstractmethod
    async def analyze(self, file_tree: list[str], local_path: str | None = None) -> dict[str, Any]:
        """
        Returns:
            {
              "hardcoded_secrets_found": bool,
              "secret_locations": list[str],
              "vulnerable_dependencies": [{"package": str, "cve": str, "severity": str}],
              "has_dependency_scanner": bool,
              "security_headers_configured": bool,
            }
        """


class ArchitectureAnalysisService(abc.ABC):
    """Analyses architectural patterns, module structure, and dependency graphs."""

    @abc.abstractmethod
    async def analyze(self, file_tree: list[str], local_path: str | None = None) -> dict[str, Any]:
        """
        Returns:
            {
              "detected_patterns": list[str],
              "layer_violations": list[str],
              "circular_dependencies": list[str],
              "external_dependencies": list[str],
              "has_api_contract": bool,
            }
        """
