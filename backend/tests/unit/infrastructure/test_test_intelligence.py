"""Tests for RealTestIntelligenceService and test AST engine components."""
from __future__ import annotations

import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from app.infrastructure.intelligence.test_ast_engine import (
    TestCaseVisitor,
    analyse_test_file_sync,
    analyse_tests_sync,
    build_source_test_map,
    find_untested_sources,
    is_test_file,
)
from app.infrastructure.intelligence.test_intelligence import (
    RealTestIntelligenceService,
    parse_coverage_xml,
)
from app.infrastructure.intelligence.test_models import TestAnalysisResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_repo(tmp_path: Path) -> Path:
    """Minimal repo with source files and test files."""
    pkg = tmp_path / "myapp"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "utils.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (pkg / "service.py").write_text("class MyService:\n    pass\n", encoding="utf-8")
    (pkg / "untested.py").write_text("x = 1\n", encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("", encoding="utf-8")
    (tests_dir / "test_utils.py").write_text(
        textwrap.dedent("""\
            import pytest
            from myapp.utils import add

            def test_add():
                assert add(1, 2) == 3

            def test_add_negative():
                assert add(-1, 1) == 0
        """),
        encoding="utf-8",
    )
    (tests_dir / "test_service.py").write_text(
        textwrap.dedent("""\
            import unittest
            from unittest.mock import MagicMock, patch

            class TestMyService(unittest.TestCase):
                def test_init(self):
                    svc = MagicMock()
                    self.assertEqual(svc, svc)

                def test_patch(self):
                    with patch("myapp.service.MyService") as mock_cls:
                        self.assertIsNotNone(mock_cls)
        """),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def file_tree(sample_repo: Path) -> list[str]:
    result = []
    for p in sample_repo.rglob("*"):
        if p.is_file():
            result.append(str(p.relative_to(sample_repo)))
    return result


@pytest.fixture()
def service() -> RealTestIntelligenceService:
    return RealTestIntelligenceService()


# ---------------------------------------------------------------------------
# is_test_file
# ---------------------------------------------------------------------------


def test_is_test_file_prefix():
    assert is_test_file("tests/test_foo.py") is True


def test_is_test_file_suffix():
    assert is_test_file("foo_test.py") is True


def test_is_test_file_in_tests_dir():
    assert is_test_file("tests/utils.py") is True


def test_is_not_test_file():
    assert is_test_file("myapp/service.py") is False


def test_is_not_test_file_config():
    assert is_test_file("pytest.ini") is False


# ---------------------------------------------------------------------------
# TestCaseVisitor
# ---------------------------------------------------------------------------


def _visit(source: str, path: str = "tests/test_mod.py") -> TestCaseVisitor:
    import ast

    tree = ast.parse(textwrap.dedent(source))
    v = TestCaseVisitor(path)
    v.visit(tree)
    return v


def test_visitor_detects_pytest_test_functions():
    v = _visit("import pytest\ndef test_one(): assert True\ndef test_two(): assert False")
    assert "test_one" in v.test_cases
    assert "test_two" in v.test_cases
    assert v.framework == "pytest"


def test_visitor_detects_unittest():
    src = textwrap.dedent("""\
        import unittest

        class MyTest(unittest.TestCase):
            def test_foo(self):
                self.assertEqual(1, 1)
    """)
    v = _visit(src)
    assert "test_foo" in v.test_cases
    assert v.framework == "unittest"


def test_visitor_counts_assert_statements():
    v = _visit("def test_x():\n    assert 1 == 1\n    assert True")
    assert v.assertion_count == 2


def test_visitor_counts_self_assertX():
    src = textwrap.dedent("""\
        import unittest
        class T(unittest.TestCase):
            def test_y(self):
                self.assertEqual(1, 1)
                self.assertTrue(True)
    """)
    v = _visit(src)
    assert v.assertion_count >= 2


def test_visitor_counts_pytest_raises():
    src = textwrap.dedent("""\
        import pytest
        def test_err():
            with pytest.raises(ValueError):
                raise ValueError
    """)
    v = _visit(src)
    assert v.assertion_count >= 1


def test_visitor_detects_mock_import():
    src = "from unittest.mock import MagicMock\n"
    v = _visit(src)
    assert v._mock_imported is True


def test_visitor_counts_mock_usage():
    src = textwrap.dedent("""\
        from unittest.mock import MagicMock, patch
        def test_m():
            m = MagicMock()
            with patch("os.path.exists"):
                pass
    """)
    v = _visit(src)
    assert v.mock_count >= 1


def test_visitor_unknown_framework_no_imports():
    v = _visit("def test_plain():\n    assert 1")
    # no imports but has test_ functions → inferred as pytest
    assert v.framework == "pytest"


# ---------------------------------------------------------------------------
# analyse_test_file_sync
# ---------------------------------------------------------------------------


def test_analyse_test_file_sync(sample_repo: Path):
    rel = "tests/test_utils.py"
    abs_p = str(sample_repo / rel)
    result = analyse_test_file_sync(abs_p, rel)
    assert result.path == rel
    assert len(result.test_cases) == 2
    assert result.assertion_count == 2
    assert result.framework == "pytest"


def test_analyse_test_file_sync_with_mocks(sample_repo: Path):
    rel = "tests/test_service.py"
    abs_p = str(sample_repo / rel)
    result = analyse_test_file_sync(abs_p, rel)
    assert result.framework == "unittest"
    assert result.mock_count > 0


def test_analyse_test_file_sync_missing_file():
    result = analyse_test_file_sync("/nonexistent/test_x.py", "test_x.py")
    assert result.test_cases == []
    assert result.framework == "unknown"


def test_analyse_test_file_sync_broken_syntax(tmp_path: Path):
    f = tmp_path / "test_bad.py"
    f.write_text("def (:\n", encoding="utf-8")
    result = analyse_test_file_sync(str(f), "test_bad.py")
    assert result.test_cases == []


# ---------------------------------------------------------------------------
# build_source_test_map + find_untested_sources
# ---------------------------------------------------------------------------


def test_source_test_map_maps_correctly(file_tree: list[str]):
    test_files = [f for f in file_tree if is_test_file(f) and f.endswith(".py")]
    mapping = build_source_test_map(file_tree, test_files)
    # test_utils.py should map to myapp/utils.py
    matched_sources = list(mapping.keys())
    assert any("utils.py" in s for s in matched_sources)


def test_find_untested_sources(file_tree: list[str]):
    test_files = [f for f in file_tree if is_test_file(f) and f.endswith(".py")]
    mapping = build_source_test_map(file_tree, test_files)
    untested = find_untested_sources(file_tree, mapping)
    # untested.py has no matching test file
    assert any("untested.py" in f for f in untested)


# ---------------------------------------------------------------------------
# parse_coverage_xml
# ---------------------------------------------------------------------------


def _write_coverage_xml(path: Path, line_rate: float = 0.75) -> None:
    """Write a minimal Cobertura-format coverage.xml."""
    xml = f"""<?xml version="1.0" ?>
<coverage version="7.0" timestamp="1700000000" lines-valid="100"
          lines-covered="{int(line_rate * 100)}" line-rate="{line_rate}"
          branches-covered="0" branches-valid="0" branch-rate="0" complexity="0">
  <packages>
    <package name="myapp" line-rate="{line_rate}" branch-rate="0" complexity="0">
      <classes>
        <class name="utils.py" filename="myapp/utils.py" line-rate="{line_rate}" branch-rate="0" complexity="0">
          <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="1"/>
            <line number="3" hits="0"/>
            <line number="4" hits="1"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>"""
    path.write_text(xml, encoding="utf-8")


def test_parse_coverage_xml(tmp_path: Path):
    xml_file = tmp_path / "coverage.xml"
    _write_coverage_xml(xml_file, line_rate=0.75)
    report = parse_coverage_xml(str(xml_file))
    assert report.overall_line_rate == pytest.approx(0.75)
    assert report.overall_coverage_pct == pytest.approx(75.0)
    assert len(report.files) == 1
    assert report.files[0].path == "myapp/utils.py"


def test_parse_coverage_xml_full_coverage(tmp_path: Path):
    xml_file = tmp_path / "coverage.xml"
    _write_coverage_xml(xml_file, line_rate=1.0)
    report = parse_coverage_xml(str(xml_file))
    assert report.overall_coverage_pct == pytest.approx(100.0)


def test_parse_coverage_xml_counts_hits(tmp_path: Path):
    xml_file = tmp_path / "coverage.xml"
    _write_coverage_xml(xml_file, line_rate=0.75)
    report = parse_coverage_xml(str(xml_file))
    # 3 of 4 lines have hits="1"
    assert report.files[0].lines_covered == 3
    assert report.files[0].lines_valid == 4


# ---------------------------------------------------------------------------
# RealTestIntelligenceService
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_analyze_returns_dict(sample_repo: Path, file_tree: list[str], service: RealTestIntelligenceService):
    result = await service.analyze(file_tree, str(sample_repo))
    assert "coverage_percent" in result
    assert "test_file_count" in result
    assert result["test_file_count"] >= 2
    assert "total_test_cases" in result
    assert result["total_test_cases"] >= 2


@pytest.mark.asyncio()
async def test_analyze_structured_returns_typed(sample_repo: Path, file_tree: list[str], service: RealTestIntelligenceService):
    result = await service.analyze_structured(file_tree, str(sample_repo))
    assert isinstance(result, TestAnalysisResult)
    assert result.metrics.total_test_files >= 2
    assert result.metrics.total_test_cases >= 2


@pytest.mark.asyncio()
async def test_analyze_no_local_path(service: RealTestIntelligenceService):
    result = await service.analyze(["tests/test_foo.py"], local_path=None)
    assert result["test_file_count"] == 1
    assert result["total_test_cases"] == 0
    assert result["test_metrics"] == {}


@pytest.mark.asyncio()
async def test_analyze_detects_frameworks(sample_repo: Path, file_tree: list[str], service: RealTestIntelligenceService):
    result = await service.analyze_structured(file_tree, str(sample_repo))
    frameworks = result.metrics.frameworks_detected
    assert "pytest" in frameworks or "unittest" in frameworks


@pytest.mark.asyncio()
async def test_analyze_detects_mock_usage(sample_repo: Path, file_tree: list[str], service: RealTestIntelligenceService):
    result = await service.analyze_structured(file_tree, str(sample_repo))
    assert len(result.metrics.mock_usage_files) >= 1
    assert any("test_service" in f for f in result.metrics.mock_usage_files)


@pytest.mark.asyncio()
async def test_analyze_source_to_test_map(sample_repo: Path, file_tree: list[str], service: RealTestIntelligenceService):
    result = await service.analyze_structured(file_tree, str(sample_repo))
    assert any("utils.py" in k for k in result.source_to_test_map)


@pytest.mark.asyncio()
async def test_analyze_files_without_tests(sample_repo: Path, file_tree: list[str], service: RealTestIntelligenceService):
    result = await service.analyze_structured(file_tree, str(sample_repo))
    assert any("untested.py" in f for f in result.metrics.files_without_tests)


@pytest.mark.asyncio()
async def test_analyze_with_coverage_xml(sample_repo: Path, file_tree: list[str], service: RealTestIntelligenceService):
    _write_coverage_xml(sample_repo / "coverage.xml", line_rate=0.80)
    result = await service.analyze_structured(file_tree + ["coverage.xml"], str(sample_repo))
    assert result.metrics.coverage_percentage == pytest.approx(80.0)
    assert result.coverage_report is not None


@pytest.mark.asyncio()
async def test_analyze_coverage_none_when_missing(sample_repo: Path, file_tree: list[str], service: RealTestIntelligenceService):
    result = await service.analyze_structured(file_tree, str(sample_repo))
    assert result.metrics.coverage_percentage is None
    assert result.coverage_report is None
