"""Tests for RealCodeIntelligenceService and AST engine components."""
from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path

import pytest

from app.infrastructure.intelligence.ast_engine import (
    COMPLEXITY_HIGH_THRESHOLD,
    ComplexityVisitor,
    ImportExtractor,
    SmellVisitor,
    analyse_file_sync,
    analyse_repo_sync,
)
from app.infrastructure.intelligence.code_intelligence import (
    RealCodeIntelligenceService,
    _build_dependency_graph,
    _build_metrics,
    _count_languages,
)
from app.infrastructure.intelligence.models import FileComplexity


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_repo(tmp_path: Path) -> Path:
    """Create a minimal fake Python repo."""
    pkg = tmp_path / "myapp"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("# package init\n", encoding="utf-8")

    (pkg / "simple.py").write_text(
        textwrap.dedent("""\
            def add(a, b):
                return a + b

            def multiply(a, b):
                return a * b
        """),
        encoding="utf-8",
    )

    (pkg / "complex.py").write_text(
        textwrap.dedent("""\
            import os
            import sys
            from myapp.simple import add

            def complex_func(a, b, c, d, e, f):
                if a:
                    for i in range(b):
                        while c:
                            try:
                                pass
                            except ValueError:
                                pass
                return add(a, b)

            def another(x):
                return x if x > 0 else -x
        """),
        encoding="utf-8",
    )

    (pkg / "broken.py").write_text(
        "def incomplete(:\n", encoding="utf-8"
    )

    # A non-Python file
    (tmp_path / "README.md").write_text("# My App\n", encoding="utf-8")

    return tmp_path


# ---------------------------------------------------------------------------
# ComplexityVisitor
# ---------------------------------------------------------------------------


def _parse_and_visit(source: str) -> ComplexityVisitor:
    import ast

    tree = ast.parse(textwrap.dedent(source))
    v = ComplexityVisitor()
    v.visit(tree)
    return v


def test_base_score_is_one():
    v = _parse_and_visit("x = 1")
    assert v.score == 1


def test_if_increments():
    v = _parse_and_visit("if True:\n    pass")
    assert v.score == 2


def test_for_increments():
    v = _parse_and_visit("for i in []:\n    pass")
    assert v.score == 2


def test_while_increments():
    v = _parse_and_visit("while False:\n    pass")
    assert v.score == 2


def test_except_increments():
    v = _parse_and_visit("try:\n    pass\nexcept:\n    pass")
    assert v.score == 2


def test_bool_op_increments():
    # "a and b and c" → 2 additional operands → +2
    v = _parse_and_visit("x = a and b and c")
    assert v.score == 3  # base 1 + 2


def test_ternary_increments():
    v = _parse_and_visit("y = 1 if cond else 2")
    assert v.score == 2


def test_function_count():
    v = _parse_and_visit("""\
        def foo(): pass
        def bar(): pass
    """)
    assert v.function_count == 2


def test_class_count():
    v = _parse_and_visit("class A: pass\nclass B: pass")
    assert v.class_count == 2


# ---------------------------------------------------------------------------
# SmellVisitor
# ---------------------------------------------------------------------------


def _smell_visit(source: str, path: str = "test.py") -> SmellVisitor:
    import ast

    tree = ast.parse(textwrap.dedent(source))
    v = SmellVisitor(path)
    v.visit(tree)
    return v


def test_long_function_smell():
    # 51 lines inside function body
    body = "\n".join(f"    x_{i} = {i}" for i in range(52))
    source = f"def long_fn(a):\n{body}\n"
    v = _smell_visit(source)
    types = {s.smell_type for s in v.smells}
    assert "long_function" in types


def test_too_many_params_smell():
    v = _smell_visit("def f(a, b, c, d, e, g): pass")
    types = {s.smell_type for s in v.smells}
    assert "too_many_params" in types


def test_god_class_smell():
    methods = "\n".join(f"    def m{i}(self): pass" for i in range(11))
    source = f"class BigClass:\n{methods}\n"
    v = _smell_visit(source)
    types = {s.smell_type for s in v.smells}
    assert "god_class" in types


def test_no_smells_for_clean_code():
    v = _smell_visit("def clean(a, b):\n    return a + b")
    assert v.smells == []


# ---------------------------------------------------------------------------
# ImportExtractor
# ---------------------------------------------------------------------------


def _extract_imports(source: str, root_pkg: str = "myapp") -> list:
    import ast

    tree = ast.parse(textwrap.dedent(source))
    extractor = ImportExtractor("myapp/mod.py", root_pkg)
    extractor.visit(tree)
    return extractor.imports


def test_stdlib_import_classified():
    imports = _extract_imports("import os")
    assert imports[0].import_type == "stdlib"
    assert imports[0].target == "os"


def test_internal_import_classified():
    imports = _extract_imports("from myapp.utils import helper")
    assert imports[0].import_type == "internal"


def test_external_import_classified():
    imports = _extract_imports("import httpx")
    assert imports[0].import_type == "external"


def test_multiple_imports():
    source = "import os\nimport httpx\nfrom myapp.x import y"
    imports = _extract_imports(source)
    types = [i.import_type for i in imports]
    assert "stdlib" in types
    assert "external" in types
    assert "internal" in types


# ---------------------------------------------------------------------------
# analyse_file_sync
# ---------------------------------------------------------------------------


def test_analyse_simple_file(tmp_path: Path):
    f = tmp_path / "mod.py"
    f.write_text("def hello():\n    return 1\n", encoding="utf-8")
    result = analyse_file_sync(str(f), "mod.py", "myapp")
    assert result.parse_error is None
    assert result.line_count == 2
    assert result.complexity is not None
    assert result.complexity.function_count == 1


def test_analyse_broken_file_sets_parse_error(tmp_path: Path):
    f = tmp_path / "bad.py"
    f.write_text("def (:\n", encoding="utf-8")
    result = analyse_file_sync(str(f), "bad.py", "myapp")
    assert result.parse_error is not None
    assert result.complexity is None


def test_large_file_smell_added(tmp_path: Path):
    lines = "\n".join(f"x_{i} = {i}" for i in range(510))
    f = tmp_path / "big.py"
    f.write_text(lines, encoding="utf-8")
    result = analyse_file_sync(str(f), "big.py", "myapp")
    smell_types = {s.smell_type for s in result.smells}
    assert "long_file" in smell_types


# ---------------------------------------------------------------------------
# analyse_repo_sync
# ---------------------------------------------------------------------------


def test_analyse_repo_sync(sample_repo: Path):
    py_files = [
        "myapp/__init__.py",
        "myapp/simple.py",
        "myapp/complex.py",
        "myapp/broken.py",
    ]
    results = analyse_repo_sync(str(sample_repo), py_files)
    assert len(results) == 4

    by_path = {r.path: r for r in results}
    assert by_path["myapp/simple.py"].parse_error is None
    assert by_path["myapp/broken.py"].parse_error is not None

    # complex.py has if + for + while + except + ternary = at least 5 extra
    complex_score = by_path["myapp/complex.py"].complexity.score
    assert complex_score >= 5


# ---------------------------------------------------------------------------
# RealCodeIntelligenceService
# ---------------------------------------------------------------------------


@pytest.fixture()
def service() -> RealCodeIntelligenceService:
    return RealCodeIntelligenceService()


@pytest.mark.asyncio()
async def test_analyze_returns_dict(sample_repo: Path, service: RealCodeIntelligenceService):
    py_files = ["myapp/__init__.py", "myapp/simple.py", "myapp/complex.py"]
    all_files = py_files + ["README.md"]
    result = await service.analyze(all_files, str(sample_repo))

    assert "total_files" in result
    assert result["total_files"] == 4
    assert "code_metrics" in result
    assert "dependency_graph" in result
    assert "code_smells" in result
    assert "parse_errors" in result


@pytest.mark.asyncio()
async def test_analyze_structured_returns_typed(sample_repo: Path, service: RealCodeIntelligenceService):
    py_files = ["myapp/__init__.py", "myapp/simple.py", "myapp/complex.py"]
    result = await service.analyze_structured(py_files, str(sample_repo))

    from app.infrastructure.intelligence.models import CodeAnalysisResult
    assert isinstance(result, CodeAnalysisResult)
    assert result.metrics.total_files == 3
    assert result.metrics.total_lines > 0


@pytest.mark.asyncio()
async def test_analyze_no_local_path(service: RealCodeIntelligenceService):
    result = await service.analyze(["myapp/mod.py"], local_path=None)
    assert result["total_files"] == 1
    assert result["code_metrics"] == {}


@pytest.mark.asyncio()
async def test_analyze_parse_errors_tracked(sample_repo: Path, service: RealCodeIntelligenceService):
    py_files = ["myapp/broken.py"]
    result = await service.analyze_structured(py_files, str(sample_repo))
    assert len(result.parse_errors) == 1


@pytest.mark.asyncio()
async def test_dependency_graph_populated(sample_repo: Path, service: RealCodeIntelligenceService):
    py_files = ["myapp/__init__.py", "myapp/simple.py", "myapp/complex.py"]
    result = await service.analyze_structured(py_files, str(sample_repo))
    dg = result.dependency_graph
    # complex.py imports os, sys (stdlib) and myapp.simple (internal)
    assert "os" in dg.stdlib_dependencies or "sys" in dg.stdlib_dependencies


@pytest.mark.asyncio()
async def test_high_complexity_files_identified(tmp_path: Path, service: RealCodeIntelligenceService):
    # Create a very complex file (score > COMPLEXITY_HIGH_THRESHOLD)
    code = "def f(a):\n"
    code += "\n".join(f"    if a == {i}:\n        pass" for i in range(15))
    f = tmp_path / "complex.py"
    f.write_text(code, encoding="utf-8")
    result = await service.analyze_structured(["complex.py"], str(tmp_path))
    assert "complex.py" in result.metrics.high_complexity_files


# ---------------------------------------------------------------------------
# _count_languages
# ---------------------------------------------------------------------------


def test_count_languages_mixed():
    files = ["a.py", "b.py", "c.js", "d.ts", "e.yaml", "f.go"]
    counts = _count_languages(files)
    assert counts.get("Python") == 2
    assert counts.get("JavaScript") == 1
    assert counts.get("TypeScript") == 1
    assert counts.get("Go") == 1
    assert "YAML" not in counts  # .yaml not mapped
