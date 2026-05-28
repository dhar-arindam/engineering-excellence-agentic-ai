"""Real CodeIntelligenceService — deterministic AST-based analysis.

Implements the CodeIntelligenceService ABC from the application layer.
Runs all blocking I/O (file reads + AST parsing) in an asyncio executor
so the event loop is never blocked.

No LLM calls. No agent calls. No side effects beyond reading files.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.application.tool_interfaces import CodeIntelligenceService
from app.core.logging import get_logger
from app.infrastructure.intelligence.ast_engine import (
    COMPLEXITY_HIGH_THRESHOLD,
    LARGE_FILE_THRESHOLD,
    FileAnalysis,
    analyse_repo_sync,
)
from app.infrastructure.intelligence.models import (
    CodeAnalysisResult,
    CodeMetrics,
    DependencyGraph,
)

logger = get_logger(__name__)

_TOP_LARGEST_FILES = 10
_MAX_SMELLS_PER_TYPE = 20  # cap to keep payload size reasonable


class RealCodeIntelligenceService(CodeIntelligenceService):
    """
    Deterministic code intelligence using Python's built-in ``ast`` module.

    Analyses only ``.py`` files. Non-Python files contribute to total_files
    and total_lines counts (via a fast line-count pass) but are excluded from
    complexity and smell analysis.

    The ``analyze()`` method satisfies the ``CodeIntelligenceService`` ABC
    and returns a dict that is a superset of the stub — agents can use the
    same keys they used before, plus richer structured data.

    For callers that want typed results, use ``analyze_structured()`` instead.
    """

    async def analyze(
        self,
        file_tree: list[str],
        local_path: str | None = None,
    ) -> dict[str, Any]:
        """
        Run full code analysis and return a ``dict`` compatible with the agent tool context.

        Extends the stub's output with:
          - ``code_metrics``        CodeMetrics (serialised)
          - ``dependency_graph``    DependencyGraph (serialised)
          - ``code_smells``         list of CodeSmell dicts
          - ``parse_errors``        list of files that couldn't be parsed
          - ``high_complexity_files``
        """
        if not local_path:
            logger.warning("code_intelligence.no_local_path")
            return self._empty_result(file_tree)

        result = await self.analyze_structured(file_tree, local_path)

        # Build the dict that agents and the orchestrator expect
        complexity_map = result.metrics.cyclomatic_complexity_estimate
        return {
            # Backward-compatible keys (match stub contract)
            "languages": _count_languages(file_tree),
            "total_files": result.metrics.total_files,
            "avg_complexity": result.metrics.avg_complexity,
            "duplication_ratio": 0.0,  # not computed — requires external tooling
            "lint_violations": [],      # not computed — requires flake8/ruff subprocess
            # Extended keys
            "code_metrics": result.metrics.model_dump(),
            "dependency_graph": result.dependency_graph.model_dump(),
            "code_smells": [s.model_dump() for s in result.code_smells],
            "parse_errors": result.parse_errors,
            "high_complexity_files": result.metrics.high_complexity_files,
            "files_over_500_lines": result.metrics.files_over_500_lines,
        }

    async def analyze_structured(
        self,
        file_tree: list[str],
        local_path: str,
    ) -> CodeAnalysisResult:
        """Run analysis and return typed ``CodeAnalysisResult``."""
        py_files = [f for f in file_tree if f.endswith(".py")]
        logger.info(
            "code_intelligence.start",
            total_files=len(file_tree),
            py_files=len(py_files),
            root=local_path,
        )

        loop = asyncio.get_running_loop()
        file_analyses: list[FileAnalysis] = await loop.run_in_executor(
            None, analyse_repo_sync, local_path, py_files
        )

        metrics = _build_metrics(file_tree, local_path, file_analyses)
        dep_graph = _build_dependency_graph(file_analyses)
        smells = _collect_smells(file_analyses)
        parse_errors = [fa.parse_error for fa in file_analyses if fa.parse_error]  # type: ignore[misc]

        logger.info(
            "code_intelligence.done",
            analysed=len(file_analyses),
            smells=len(smells),
            parse_errors=len(parse_errors),
            avg_complexity=metrics.avg_complexity,
        )

        return CodeAnalysisResult(
            metrics=metrics,
            dependency_graph=dep_graph,
            code_smells=smells,
            analysed_files=len(file_analyses),
            parse_errors=parse_errors,
        )

    @staticmethod
    def _empty_result(file_tree: list[str]) -> dict[str, Any]:
        return {
            "languages": _count_languages(file_tree),
            "total_files": len(file_tree),
            "avg_complexity": 0.0,
            "duplication_ratio": 0.0,
            "lint_violations": [],
            "code_metrics": {},
            "dependency_graph": {"nodes": [], "edges": [], "internal_edges": [],
                                  "external_dependencies": [], "stdlib_dependencies": []},
            "code_smells": [],
            "parse_errors": [],
            "high_complexity_files": [],
            "files_over_500_lines": [],
        }


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def _build_metrics(
    file_tree: list[str],
    local_path: str,
    analyses: list[FileAnalysis],
) -> CodeMetrics:
    """Aggregate FileAnalysis results into a CodeMetrics model."""
    # Line counts — fast pass for all files (not just .py)
    line_counts = _count_all_lines(local_path, file_tree)
    total_lines = sum(line_counts.values())
    total_files = len(file_tree)
    avg_size = round(total_lines / total_files, 2) if total_files else 0.0

    # Largest files (by line count)
    sorted_by_size = sorted(line_counts.items(), key=lambda kv: kv[1], reverse=True)
    largest_files = [path for path, _ in sorted_by_size[:_TOP_LARGEST_FILES]]
    files_over_500 = [path for path, lines in line_counts.items() if lines > LARGE_FILE_THRESHOLD]

    # Complexity from AST analyses
    complexity_map: dict[str, int] = {}
    for fa in analyses:
        if fa.complexity is not None:
            complexity_map[fa.path] = fa.complexity.score

    high_complexity = [
        path for path, score in complexity_map.items()
        if score > COMPLEXITY_HIGH_THRESHOLD
    ]

    avg_complexity = (
        round(sum(complexity_map.values()) / len(complexity_map), 2)
        if complexity_map else 0.0
    )

    return CodeMetrics(
        total_files=total_files,
        total_lines=total_lines,
        average_file_size=avg_size,
        largest_files=largest_files,
        files_over_500_lines=files_over_500,
        cyclomatic_complexity_estimate=complexity_map,
        avg_complexity=avg_complexity,
        high_complexity_files=high_complexity,
    )


def _build_dependency_graph(analyses: list[FileAnalysis]) -> DependencyGraph:
    """Build import dependency graph from all FileAnalysis import edges."""
    nodes: set[str] = set()
    all_edges: list[tuple[str, str]] = []
    internal_edges: list[tuple[str, str]] = []
    external_deps: set[str] = set()
    stdlib_deps: set[str] = set()

    for fa in analyses:
        nodes.add(fa.path)
        for imp in fa.imports:
            edge = (imp.source, imp.target)
            all_edges.append(edge)
            if imp.import_type == "internal":
                internal_edges.append(edge)
            elif imp.import_type == "external":
                external_deps.add(imp.target.split(".")[0])
            elif imp.import_type == "stdlib":
                stdlib_deps.add(imp.target.split(".")[0])

    return DependencyGraph(
        nodes=sorted(nodes),
        edges=all_edges,
        internal_edges=internal_edges,
        external_dependencies=sorted(external_deps),
        stdlib_dependencies=sorted(stdlib_deps),
    )


def _collect_smells(analyses: list[FileAnalysis]) -> list[dict]:  # type: ignore[type-arg]
    """Collect and cap smells from all file analyses."""
    from collections import defaultdict
    by_type: dict[str, list] = defaultdict(list)  # type: ignore[type-arg]

    for fa in analyses:
        for smell in fa.smells:
            by_type[smell.smell_type].append(smell)

    result = []
    for smell_type, items in by_type.items():
        result.extend(items[:_MAX_SMELLS_PER_TYPE])
    return result  # type: ignore[return-value]


def _count_all_lines(root: str, file_tree: list[str]) -> dict[str, int]:
    """Fast line count for all files using newline counting."""
    counts: dict[str, int] = {}
    for rel in file_tree:
        abs_path = Path(root) / rel
        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
            counts[rel] = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        except OSError:
            counts[rel] = 0
    return counts


def _count_languages(file_tree: list[str]) -> dict[str, int]:
    """Count files per language by extension."""
    ext_map = {
        ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
        ".tsx": "TypeScript", ".jsx": "JavaScript", ".java": "Java",
        ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".cs": "C#",
        ".cpp": "C++", ".c": "C", ".swift": "Swift", ".kt": "Kotlin",
    }
    counts: dict[str, int] = {}
    for f in file_tree:
        ext = Path(f).suffix.lower()
        lang = ext_map.get(ext)
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    return counts
