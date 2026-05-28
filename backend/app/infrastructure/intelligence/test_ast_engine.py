"""AST-based analysis engine for test files.

Provides:
- is_test_file()          — determine whether a path is a test file
- TestCaseVisitor         — counts test functions, assertions, mock usages
- analyse_test_file_sync()— entry point: parse one test file and return TestFile
- analyse_tests_sync()    — entry point: scan all test files in a repo
- build_source_test_map() — heuristic mapping: source_file → test_files

No LLM calls. No side effects beyond reading files.
All heavy work is sync (designed to run in asyncio executor).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from app.infrastructure.intelligence.test_models import TestFile

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Patterns that identify a file as a test file
_TEST_FILE_PATTERNS: tuple[str, ...] = (
    "test_",   # pytest prefix: test_foo.py
    "_test",   # suffix before extension: foo_test.py
)

# Names that indicate mock usage when imported or called
_MOCK_MODULES = frozenset({"mock", "unittest.mock", "pytest_mock", "responses", "respx", "httpretty"})
_MOCK_NAMES = frozenset({"MagicMock", "Mock", "patch", "AsyncMock", "mocker", "create_autospec"})

# pytest assertion helpers that are function calls (not bare assert)
_PYTEST_ASSERTION_CALLS = frozenset({
    "pytest.raises", "pytest.warns", "pytest.approx",
})


# ---------------------------------------------------------------------------
# Test file detection
# ---------------------------------------------------------------------------

def is_test_file(path: str) -> bool:
    """Return True if the file path looks like a test file."""
    name = Path(path).stem.lower()
    return any(pat in name for pat in _TEST_FILE_PATTERNS) or _in_tests_dir(path)


def _in_tests_dir(path: str) -> bool:
    parts = Path(path).parts
    return any(p.lower() in ("tests", "test") for p in parts[:-1])


# ---------------------------------------------------------------------------
# Visitors
# ---------------------------------------------------------------------------

class TestCaseVisitor(ast.NodeVisitor):
    """
    Walks a test file's AST to collect:
    - test function / method names
    - assertion count (assert statements + self.assertX + pytest.raises)
    - mock usage count
    - test framework hint
    """

    def __init__(self, file_path: str) -> None:
        self._path = file_path
        self.test_cases: list[str] = []
        self.assertion_count: int = 0
        self.mock_count: int = 0
        self._imports_unittest: bool = False
        self._imports_pytest: bool = False
        self._mock_imported: bool = False

    # ── imports ─────────────────────────────────────────────────────────────

    def visit_Import(self, node: ast.Import) -> None:   # noqa: N802
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top == "pytest":
                self._imports_pytest = True
            if top == "unittest":
                self._imports_unittest = True
            if alias.name in _MOCK_MODULES:
                self._mock_imported = True
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:   # noqa: N802
        mod = node.module or ""
        top = mod.split(".")[0]
        if top == "pytest":
            self._imports_pytest = True
        if top == "unittest":
            self._imports_unittest = True
        if mod in _MOCK_MODULES:
            self._mock_imported = True
        # from unittest.mock import patch ...
        for alias in node.names:
            if alias.name in _MOCK_NAMES:
                self._mock_imported = True
        self.generic_visit(node)

    # ── test functions ───────────────────────────────────────────────────────

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:   # noqa: N802
        if node.name.startswith("test"):
            self.test_cases.append(node.name)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_ClassDef(self, node: ast.ClassDef) -> None:   # noqa: N802
        # unittest.TestCase subclasses: collect test methods inside
        self.generic_visit(node)

    # ── assertions ───────────────────────────────────────────────────────────

    def visit_Assert(self, node: ast.Assert) -> None:   # noqa: N802
        self.assertion_count += 1
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:   # noqa: N802
        call_str = _call_to_str(node.func)

        # self.assertEqual / self.assertTrue / … (any self.assert*)
        if re.match(r"self\.assert[A-Z]", call_str):
            self.assertion_count += 1

        # pytest.raises / pytest.warns / pytest.approx
        if call_str in _PYTEST_ASSERTION_CALLS:
            self.assertion_count += 1

        # Mock / patch usages
        if call_str in _MOCK_NAMES or call_str.startswith("mock.") or call_str.startswith("mocker."):
            self.mock_count += 1

        # patch as function decorator or context manager (patch("some.thing"))
        if call_str in ("patch", "mock.patch", "unittest.mock.patch"):
            self.mock_count += 1

        self.generic_visit(node)

    # ── helpers ──────────────────────────────────────────────────────────────

    @property
    def framework(self) -> str:
        if self._imports_pytest:
            return "pytest"
        if self._imports_unittest:
            return "unittest"
        # Fallback: infer from test function style
        if self.test_cases:
            return "pytest"  # bare functions without imports → likely pytest
        return "unknown"


def _call_to_str(node: ast.expr) -> str:
    """Convert a Call's func node to a dotted string for easy matching."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_call_to_str(node.value)}.{node.attr}"
    return ""


# ---------------------------------------------------------------------------
# File-level analysis (sync)
# ---------------------------------------------------------------------------

def analyse_test_file_sync(abs_path: str, rel_path: str) -> TestFile:
    """
    Parse and analyse a single test file.

    Returns TestFile. Sets test_cases=[], assertion_count=0 on parse error
    (does not raise — caller decides how to handle).
    """
    try:
        source = Path(abs_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return TestFile(path=rel_path, test_cases=[], assertion_count=0, mock_count=0, framework="unknown")

    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError:
        return TestFile(path=rel_path, test_cases=[], assertion_count=0, mock_count=0, framework="unknown")

    visitor = TestCaseVisitor(rel_path)
    visitor.visit(tree)

    return TestFile(
        path=rel_path,
        test_cases=visitor.test_cases,
        assertion_count=visitor.assertion_count,
        mock_count=visitor.mock_count,
        framework=visitor.framework,
    )


# ---------------------------------------------------------------------------
# Repository-level analysis (sync, runs in executor)
# ---------------------------------------------------------------------------

def analyse_tests_sync(root: str, test_files: list[str]) -> list[TestFile]:
    """
    Analyse all test files in the repository.

    Args:
        root:       Absolute path to repository root.
        test_files: Relative paths to test files.

    Returns:
        List of TestFile, one per file.
    """
    import os

    results: list[TestFile] = []
    for rel in test_files:
        abs_path = os.path.join(root, rel)
        results.append(analyse_test_file_sync(abs_path, rel))
    return results


# ---------------------------------------------------------------------------
# Source → test mapping (heuristic)
# ---------------------------------------------------------------------------

def build_source_test_map(
    all_files: list[str],
    test_files: list[str],
) -> dict[str, list[str]]:
    """
    Build a heuristic mapping: source_file → [test_files that might cover it].

    Strategy:
    1. For each source file `foo/bar.py`, look for test files whose stem
       contains `bar` (after stripping `test_` / `_test` affixes).
    2. Also match by directory: `foo/test_bar.py` → `foo/bar.py`.

    Returns a dict keyed by source files (non-test Python files) that have
    at least one matching test file.
    """
    source_files = [f for f in all_files if f.endswith(".py") and not is_test_file(f)]

    # Pre-compute normalised test stems: "test_bar" → "bar", "bar_test" → "bar"
    def _norm_stem(path: str) -> str:
        stem = Path(path).stem.lower()
        stem = re.sub(r"^test_", "", stem)
        stem = re.sub(r"_test$", "", stem)
        return stem

    test_norm: list[tuple[str, str]] = [(t, _norm_stem(t)) for t in test_files]

    mapping: dict[str, list[str]] = {}
    for src in source_files:
        src_stem = Path(src).stem.lower()
        matches = [t for t, tnorm in test_norm if tnorm == src_stem or src_stem in tnorm]
        if matches:
            mapping[src] = matches

    return mapping


# ---------------------------------------------------------------------------
# Files without tests detection
# ---------------------------------------------------------------------------

def find_untested_sources(
    all_files: list[str],
    source_test_map: dict[str, list[str]],
) -> list[str]:
    """Return source files that have no test file mapping."""
    source_files = [f for f in all_files if f.endswith(".py") and not is_test_file(f)]
    return [f for f in source_files if f not in source_test_map]
