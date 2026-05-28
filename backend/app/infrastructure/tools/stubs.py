"""Stub implementations of all intelligence services.

These return plausible static data. Replace with real static analysis tools
(tree-sitter, semgrep, coverage.py, etc.) without changing the interfaces.
"""
from __future__ import annotations

from typing import Any

from app.application.tool_interfaces import (
    ArchitectureAnalysisService,
    CiCdIntelligenceService,
    CodeIntelligenceService,
    SecurityIntelligenceService,
    TestIntelligenceService,
)


class StubCodeIntelligenceService(CodeIntelligenceService):
    async def analyze(self, file_tree: list[str], local_path: str | None = None) -> dict[str, Any]:
        py_files = [f for f in file_tree if f.endswith(".py")]
        return {
            "languages": {"Python": 90, "YAML": 10},
            "total_files": len(file_tree),
            "python_file_count": len(py_files),
            "avg_complexity": 4.2,
            "duplication_ratio": 0.08,
            "lint_violations": [],
        }


class StubTestIntelligenceService(TestIntelligenceService):
    async def analyze(self, file_tree: list[str], local_path: str | None = None) -> dict[str, Any]:
        test_files = [f for f in file_tree if "test" in f.lower()]
        return {
            "coverage_percent": 68.5,
            "test_file_count": len(test_files),
            "test_frameworks": ["pytest"],
            "has_ci_coverage_gate": False,
            "flaky_test_indicators": [],
        }


class StubCiCdIntelligenceService(CiCdIntelligenceService):
    async def analyze(self, file_tree: list[str], local_path: str | None = None) -> dict[str, Any]:
        has_gha = any(".github/workflows" in f for f in file_tree)
        return {
            "ci_platform": "GitHub Actions" if has_gha else None,
            "has_pipeline": has_gha,
            "stages": ["lint", "test", "build"] if has_gha else [],
            "has_deploy_stage": False,
            "has_security_scan": False,
            "has_quality_gate": False,
            "runs_tests": has_gha,
            "runs_lint": has_gha,
            "dockerfile_present": False,
            "multi_stage_build": False,
            "uses_cache": False,
            "has_parallel_jobs": False,
        }


class StubSecurityIntelligenceService(SecurityIntelligenceService):
    async def analyze(self, file_tree: list[str], local_path: str | None = None) -> dict[str, Any]:
        return {
            "hardcoded_secrets_found": False,
            "secret_count": 0,
            "secret_locations": [],
            "insecure_pattern_count": 0,
            "insecure_patterns": [],
            "uses_https": True,
            "has_dependency_scanner": False,
            "has_security_policy": False,
            "hardcoded_password_instances": [],
            "vulnerable_dependencies": [],
            "security_headers_configured": False,
        }


class StubArchitectureAnalysisService(ArchitectureAnalysisService):
    async def analyze(self, file_tree: list[str], local_path: str | None = None) -> dict[str, Any]:
        return {
            "detected_patterns": ["layered", "repository"],
            "layer_violations": [],
            "circular_dependencies": [],
            "external_dependencies": ["fastapi", "sqlalchemy", "openai"],
            "has_api_contract": any("openapi" in f.lower() for f in file_tree),
        }
