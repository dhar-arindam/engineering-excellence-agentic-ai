"""AST-based analysis engine for Python source files.

Provides:
- ComplexityVisitor  — counts McCabe cyclomatic complexity decision points
- SmellVisitor       — detects long functions, too many params, deep nesting, god classes
- ImportExtractor    — extracts import edges for dependency graph construction
- analyse_file()     — entry point: parse one file and return all metrics
- analyse_repo()     — entry point: scan all .py files under a root directory

All heavy work (file I/O + AST parsing) is designed to run in an executor;
the async wrappers are in code_intelligence.py.

No LLM calls. No side effects beyond reading files.
"""
from __future__ import annotations

import ast
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.infrastructure.intelligence.models import (
    CodeSmell,
    FileComplexity,
    ImportEdge,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMPLEXITY_HIGH_THRESHOLD = 10
FUNCTION_LENGTH_THRESHOLD = 50   # lines
PARAM_COUNT_THRESHOLD = 5
NESTING_DEPTH_THRESHOLD = 4
GOD_CLASS_METHOD_THRESHOLD = 10
LARGE_FILE_THRESHOLD = 500       # lines

# Python stdlib top-level module names (3.11+)
_STDLIB_NAMES: frozenset[str] = frozenset(sys.stdlib_module_names)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Data containers (sync, internal)
# ---------------------------------------------------------------------------

@dataclass
class FileAnalysis:
    """Raw analysis results for a single Python file."""
    path: str                                     # relative path from repo root
    line_count: int = 0
    complexity: FileComplexity | None = None
    imports: list[ImportEdge] = field(default_factory=list)
    smells: list[CodeSmell] = field(default_factory=list)
    parse_error: str | None = None


# ---------------------------------------------------------------------------
# Visitors
# ---------------------------------------------------------------------------

class ComplexityVisitor(ast.NodeVisitor):
    """
    Counts McCabe cyclomatic complexity for a module.

    Starting at 1 (base path), increments for each decision point:
      - if / elif
      - for
      - while
      - except handler
      - BoolOp (and / or) — each additional operand adds 1
      - assert (optional, disabled by default)
      - conditional expression (ternary)
    """

    def __init__(self) -> None:
        self.score = 1  # base
        self.function_count = 0
        self.class_count = 0

    def visit_If(self, node: ast.If) -> None:       # noqa: N802
        self.score += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:     # noqa: N802
        self.score += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None: # noqa: N802
        self.score += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:  # noqa: N802
        self.score += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:  # noqa: N802
        # Each additional operand after the first is a branch
        self.score += len(node.values) - 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:  # noqa: N802
        # Ternary expression: value if cond else other
        self.score += 1
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self.function_count += 1
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.class_count += 1
        self.generic_visit(node)


class SmellVisitor(ast.NodeVisitor):
    """
    Detects common code smells by walking the AST.

    Tracks:
    - Long functions (> FUNCTION_LENGTH_THRESHOLD lines)
    - Functions with too many parameters (> PARAM_COUNT_THRESHOLD)
    - Deeply nested blocks (nesting depth > NESTING_DEPTH_THRESHOLD)
    - God classes (> GOD_CLASS_METHOD_THRESHOLD methods)
    """

    def __init__(self, file_path: str) -> None:
        self._path = file_path
        self.smells: list[CodeSmell] = []
        self._nesting_depth = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._check_function(node)
        self._nesting_depth += 1
        self.generic_visit(node)
        self._nesting_depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        method_count = sum(
            1 for n in ast.walk(node)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        if method_count > GOD_CLASS_METHOD_THRESHOLD:
            self.smells.append(CodeSmell(
                file_path=self._path,
                smell_type="god_class",
                detail=f"Class '{node.name}' has {method_count} methods (threshold: {GOD_CLASS_METHOD_THRESHOLD})",
                line_number=node.lineno,
            ))
        self._nesting_depth += 1
        self.generic_visit(node)
        self._nesting_depth -= 1

    def visit_If(self, node: ast.If) -> None:       # noqa: N802
        self._check_nesting(node)
        self._nesting_depth += 1
        self.generic_visit(node)
        self._nesting_depth -= 1

    def visit_For(self, node: ast.For) -> None:     # noqa: N802
        self._check_nesting(node)
        self._nesting_depth += 1
        self.generic_visit(node)
        self._nesting_depth -= 1

    def visit_While(self, node: ast.While) -> None: # noqa: N802
        self._check_nesting(node)
        self._nesting_depth += 1
        self.generic_visit(node)
        self._nesting_depth -= 1

    def _check_function(self, node: ast.FunctionDef) -> None:
        # Long function
        end_line = getattr(node, "end_lineno", node.lineno)
        length = end_line - node.lineno
        if length > FUNCTION_LENGTH_THRESHOLD:
            self.smells.append(CodeSmell(
                file_path=self._path,
                smell_type="long_function",
                detail=f"Function '{node.name}' is {length} lines (threshold: {FUNCTION_LENGTH_THRESHOLD})",
                line_number=node.lineno,
            ))
        # Too many parameters
        all_args = node.args
        param_count = (
            len(all_args.args)
            + len(all_args.posonlyargs)
            + len(all_args.kwonlyargs)
            + (1 if all_args.vararg else 0)
            + (1 if all_args.kwarg else 0)
        )
        if param_count > PARAM_COUNT_THRESHOLD:
            self.smells.append(CodeSmell(
                file_path=self._path,
                smell_type="too_many_params",
                detail=f"Function '{node.name}' has {param_count} parameters (threshold: {PARAM_COUNT_THRESHOLD})",
                line_number=node.lineno,
            ))

    def _check_nesting(self, node: ast.stmt) -> None:
        if self._nesting_depth >= NESTING_DEPTH_THRESHOLD:
            self.smells.append(CodeSmell(
                file_path=self._path,
                smell_type="deep_nesting",
                detail=f"Nesting depth {self._nesting_depth + 1} exceeds threshold {NESTING_DEPTH_THRESHOLD}",
                line_number=getattr(node, "lineno", 0),
            ))


class ImportExtractor(ast.NodeVisitor):
    """Extracts import statements and classifies them as internal/stdlib/external."""

    def __init__(self, file_path: str, project_root_package: str) -> None:
        self._path = file_path
        self._root_pkg = project_root_package
        self.imports: list[ImportEdge] = []

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            top_level = alias.name.split(".")[0]
            self.imports.append(ImportEdge(
                source=self._path,
                target=alias.name,
                import_type=self._classify(top_level),
            ))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        if node.module:
            top_level = node.module.split(".")[0]
            self.imports.append(ImportEdge(
                source=self._path,
                target=node.module,
                import_type=self._classify(top_level),
            ))

    def _classify(self, top_level: str) -> str:
        if top_level == self._root_pkg:
            return "internal"
        if top_level in _STDLIB_NAMES:
            return "stdlib"
        return "external"


# ---------------------------------------------------------------------------
# File-level analysis (sync)
# ---------------------------------------------------------------------------

def analyse_file_sync(abs_path: str, rel_path: str, project_root_package: str) -> FileAnalysis:
    """
    Parse and fully analyse a single Python file.

    Returns FileAnalysis with complexity, imports, and smells.
    Sets parse_error if the file cannot be parsed.
    """
    result = FileAnalysis(path=rel_path)

    try:
        source = Path(abs_path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        result.parse_error = f"Cannot read: {exc}"
        return result

    result.line_count = source.count("\n") + (1 if source and not source.endswith("\n") else 0)

    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError as exc:
        result.parse_error = f"SyntaxError at line {exc.lineno}: {exc.msg}"
        result.line_count = source.count("\n")
        return result

    # Complexity
    complexity_visitor = ComplexityVisitor()
    complexity_visitor.visit(tree)
    result.complexity = FileComplexity(
        path=rel_path,
        score=complexity_visitor.score,
        function_count=complexity_visitor.function_count,
        class_count=complexity_visitor.class_count,
    )

    # Imports
    import_extractor = ImportExtractor(rel_path, project_root_package)
    import_extractor.visit(tree)
    result.imports = import_extractor.imports

    # Smells
    smell_visitor = SmellVisitor(rel_path)
    smell_visitor.visit(tree)
    result.smells = smell_visitor.smells

    # Large file smell
    if result.line_count > LARGE_FILE_THRESHOLD:
        result.smells.append(CodeSmell(
            file_path=rel_path,
            smell_type="long_file",
            detail=f"File has {result.line_count} lines (threshold: {LARGE_FILE_THRESHOLD})",
            line_number=0,
        ))

    return result


# ---------------------------------------------------------------------------
# Repository-level analysis (sync, runs in executor)
# ---------------------------------------------------------------------------

def analyse_repo_sync(root: str, py_files: list[str]) -> list[FileAnalysis]:
    """
    Analyse all Python files in the repository.

    Args:
        root:     Absolute path to repository root.
        py_files: List of relative paths to .py files.

    Returns:
        List of FileAnalysis, one per file (including files with parse errors).
    """
    # Determine project root package name from first path segment
    root_pkg = _infer_root_package(py_files)
    results: list[FileAnalysis] = []

    for rel_path in py_files:
        abs_path = os.path.join(root, rel_path)
        results.append(analyse_file_sync(abs_path, rel_path, root_pkg))

    return results


def _infer_root_package(py_files: list[str]) -> str:
    """Guess the top-level package name from the file list (most common first segment)."""
    counts: dict[str, int] = {}
    for path in py_files:
        first = path.replace("\\", "/").split("/")[0]
        if first and not first.startswith("."):
            counts[first] = counts.get(first, 0) + 1
    if not counts:
        return ""
    return max(counts, key=lambda k: counts[k])
