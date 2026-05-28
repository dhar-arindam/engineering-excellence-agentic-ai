"""Real TestIntelligenceService — deterministic AST-based test analysis.

Implements the TestIntelligenceService ABC from the application layer.
All blocking I/O (file reads, AST parsing, coverage.xml parsing) runs
in an asyncio executor so the event loop is never blocked.

No LLM calls. No side effects beyond reading files.
"""
from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional

from app.application.tool_interfaces import TestIntelligenceService
from app.core.logging import get_logger
from app.infrastructure.intelligence.test_ast_engine import (
    analyse_tests_sync,
    build_source_test_map,
    find_untested_sources,
    is_test_file,
)
from app.infrastructure.intelligence.test_models import (
    CoverageFileResult,
    CoverageReport,
    TestAnalysisResult,
    TestFile,
    TestMetrics,
)

logger = get_logger(__name__)

# Candidate coverage report file names (checked in order)
_COVERAGE_XML_NAMES = ("coverage.xml", "coverage-report.xml", ".coverage.xml")


class RealTestIntelligenceService(TestIntelligenceService):
    """
    Deterministic test intelligence using Python's built-in ``ast`` module
    and standard XML parsing for coverage reports.

    The ``analyze()`` method satisfies the ``TestIntelligenceService`` ABC
    and returns a dict that is a superset of the stub contract.

    For callers that want typed results, use ``analyze_structured()``.
    """

    async def analyze(
        self,
        file_tree: list[str],
        local_path: str | None = None,
    ) -> dict[str, Any]:
        """
        Run test analysis and return a dict compatible with the agent tool context.

        Extends the stub output with:
          - ``total_test_cases``   total number of test functions found
          - ``test_metrics``       TestMetrics (serialised)
          - ``source_to_test_map``
          - ``mock_usage_files``
          - ``assertion_density``  per-file assertion counts
        """
        if not local_path:
            logger.warning("test_intelligence.no_local_path")
            return self._empty_result(file_tree)

        result = await self.analyze_structured(file_tree, local_path)
        m = result.metrics

        return {
            # Backward-compatible keys (match stub contract)
            "coverage_percent": m.coverage_percentage,
            "test_file_count": m.total_test_files,
            "test_frameworks": m.frameworks_detected,
            "has_ci_coverage_gate": False,      # requires CI config parsing
            "flaky_test_indicators": [],         # requires historical run data
            # Extended keys
            "total_test_cases": m.total_test_cases,
            "test_metrics": m.model_dump(),
            "source_to_test_map": result.source_to_test_map,
            "mock_usage_files": m.mock_usage_files,
            "assertion_density": m.assertion_density,
            "coverage_report": result.coverage_report.model_dump() if result.coverage_report else None,
        }

    async def analyze_structured(
        self,
        file_tree: list[str],
        local_path: str,
    ) -> TestAnalysisResult:
        """Run analysis and return typed ``TestAnalysisResult``."""
        test_files = [f for f in file_tree if is_test_file(f) and f.endswith(".py")]

        logger.info(
            "test_intelligence.start",
            total_files=len(file_tree),
            test_files=len(test_files),
            root=local_path,
        )

        loop = asyncio.get_running_loop()

        # AST analysis of test files (blocking)
        file_details: list[TestFile] = await loop.run_in_executor(
            None, analyse_tests_sync, local_path, test_files
        )

        # Coverage XML (blocking, optional)
        coverage_report: Optional[CoverageReport] = await loop.run_in_executor(
            None, _find_and_parse_coverage, local_path
        )

        # Source-to-test mapping
        source_test_map = build_source_test_map(file_tree, test_files)
        untested = find_untested_sources(file_tree, source_test_map)

        metrics = _build_metrics(file_details, test_files, untested, coverage_report)

        logger.info(
            "test_intelligence.done",
            test_cases=metrics.total_test_cases,
            coverage=metrics.coverage_percentage,
            untested_files=len(untested),
        )

        return TestAnalysisResult(
            metrics=metrics,
            test_file_details=file_details,
            source_to_test_map=source_test_map,
            coverage_report=coverage_report,
        )

    @staticmethod
    def _empty_result(file_tree: list[str]) -> dict[str, Any]:
        test_files = [f for f in file_tree if is_test_file(f) and f.endswith(".py")]
        return {
            "coverage_percent": None,
            "test_file_count": len(test_files),
            "test_frameworks": [],
            "has_ci_coverage_gate": False,
            "flaky_test_indicators": [],
            "total_test_cases": 0,
            "test_metrics": {},
            "source_to_test_map": {},
            "mock_usage_files": [],
            "assertion_density": {},
            "coverage_report": None,
        }


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def _build_metrics(
    file_details: list[TestFile],
    test_file_paths: list[str],
    untested_sources: list[str],
    coverage_report: Optional[CoverageReport],
) -> TestMetrics:
    total_cases = sum(len(f.test_cases) for f in file_details)
    assertion_density = {f.path: f.assertion_count for f in file_details}
    mock_files = [f.path for f in file_details if f.mock_count > 0]

    frameworks: set[str] = set()
    for f in file_details:
        if f.framework != "unknown":
            frameworks.add(f.framework)

    coverage_pct: Optional[float] = None
    if coverage_report is not None:
        coverage_pct = round(coverage_report.overall_coverage_pct, 2)

    return TestMetrics(
        total_test_files=len(test_file_paths),
        total_test_cases=total_cases,
        test_files=test_file_paths,
        files_without_tests=untested_sources,
        coverage_percentage=coverage_pct,
        assertion_density=assertion_density,
        mock_usage_files=mock_files,
        frameworks_detected=sorted(frameworks),
    )


# ---------------------------------------------------------------------------
# coverage.xml parser
# ---------------------------------------------------------------------------

def _find_and_parse_coverage(root: str) -> Optional[CoverageReport]:
    """
    Look for a coverage.xml file under ``root`` and parse it.

    Returns ``None`` if no coverage report is found or parsing fails.
    Supports both Cobertura (coverage.py) and generic Cobertura XML formats.
    """
    root_path = Path(root)
    xml_path: Optional[Path] = None

    # 1. Check known top-level names
    for name in _COVERAGE_XML_NAMES:
        candidate = root_path / name
        if candidate.is_file():
            xml_path = candidate
            break

    # 2. Recursive search (first match only, depth-limited)
    if xml_path is None:
        for candidate in root_path.rglob("coverage*.xml"):
            xml_path = candidate
            break

    if xml_path is None:
        logger.debug("test_intelligence.no_coverage_xml", root=root)
        return None

    try:
        return parse_coverage_xml(str(xml_path))
    except Exception as exc:  # pragma: no cover
        logger.warning("test_intelligence.coverage_parse_error", path=str(xml_path), error=str(exc))
        return None


def parse_coverage_xml(xml_path: str) -> CoverageReport:
    """
    Parse a Cobertura-format coverage.xml file.

    Supports the format produced by ``coverage.py --xml`` and most CI coverage tools.

    Raises:
        ET.ParseError  — if the XML is malformed
        ValueError     — if the required attributes are missing
    """
    tree = ET.parse(xml_path)  # noqa: S314 — local file, controlled input
    root = tree.getroot()

    # The root element may be <coverage> or <report>
    coverage_el = root if root.tag == "coverage" else root.find("coverage")
    if coverage_el is None:
        raise ValueError(f"Cannot find <coverage> element in {xml_path}")

    line_rate = float(coverage_el.get("line-rate", "0"))
    timestamp = coverage_el.get("timestamp")

    file_results: list[CoverageFileResult] = []
    for cls_el in coverage_el.iter("class"):
        filename = cls_el.get("filename", "")
        file_line_rate = float(cls_el.get("line-rate", "0"))
        lines_el = cls_el.find("lines")
        lines_valid = int(cls_el.get("complexity", "0"))  # Cobertura overloads this field

        covered = 0
        valid = 0
        if lines_el is not None:
            all_lines = lines_el.findall("line")
            valid = len(all_lines)
            covered = sum(1 for ln in all_lines if ln.get("hits", "0") != "0")

        file_results.append(CoverageFileResult(
            path=filename,
            line_rate=file_line_rate,
            lines_covered=covered,
            lines_valid=valid,
        ))

    return CoverageReport(
        overall_line_rate=line_rate,
        overall_coverage_pct=round(line_rate * 100, 2),
        files=file_results,
        timestamp=timestamp,
    )
