"""Breaking change detector — compares original source against a patched workspace.

Uses AST analysis for Python and regex-based symbol extraction for TypeScript/JS.

Detection coverage
------------------

Python (via ``ast`` module):
  - Deleted files that existed in original
  - Removed public functions / methods (names not starting with ``_``)
  - Changed function signatures (parameter list diff)
  - Changed class public API (added/removed methods)
  - Removed top-level assignments (exported constants)

TypeScript / JavaScript (regex-based):
  - Removed ``export`` statements
  - Removed exported function/class/interface/type/const/enum declarations
  - Renamed exported symbols

The detector is intentionally conservative: it reports a breaking change only
when something *present* in the original is *absent or different* in the
patched version.  Additions are never flagged as breaking.
"""
from __future__ import annotations

import ast
import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.application.virtual_workspace import VirtualWorkspace

logger = get_logger(__name__)

# Regex for TypeScript / JavaScript exports.
_TS_EXPORT_RE = re.compile(
    r"^export\s+(?:default\s+)?(?:async\s+)?(?:function|class|interface|type|const|enum|abstract\s+class)\s+([A-Za-z_$][A-Za-z0-9_$]*)",
    re.MULTILINE,
)
_TS_REEXPORT_RE = re.compile(
    r"^export\s*\{([^}]+)\}",
    re.MULTILINE,
)


@dataclass
class BreakingChangeReport:
    """Result of a breaking change analysis."""

    has_breaking_changes: bool
    details: list[str] = field(default_factory=list)

    def add(self, detail: str) -> None:
        self.details.append(detail)
        self.has_breaking_changes = True


class BreakingChangeDetector:
    """Detects breaking changes between original source and a patched workspace."""

    async def analyze(
        self,
        original_path: str,
        workspace: "VirtualWorkspace",
    ) -> BreakingChangeReport:
        """Compare *original_path* against the patched *workspace*.

        Args:
            original_path: Absolute path to the unmodified source tree.
            workspace:     The virtual workspace containing the patched files.

        Returns:
            A :class:`BreakingChangeReport`.
        """
        report = BreakingChangeReport(has_breaking_changes=False)

        orig_root = Path(original_path)
        work_root = Path(workspace.work_path)

        modified = await workspace.list_modified_files()
        if not modified:
            return report

        await asyncio.to_thread(
            self._analyze_sync, orig_root, work_root, modified, report
        )
        logger.info(
            "breaking_change_detector.done",
            modified_files=len(modified),
            has_breaking=report.has_breaking_changes,
            details_count=len(report.details),
        )
        return report

    # ------------------------------------------------------------------
    # Sync analysis (runs in thread via asyncio.to_thread)
    # ------------------------------------------------------------------

    def _analyze_sync(
        self,
        orig_root: Path,
        work_root: Path,
        modified: list[str],
        report: BreakingChangeReport,
    ) -> None:
        for rel in modified:
            orig_file = orig_root / rel
            work_file = work_root / rel

            # Deleted file check.
            if orig_file.exists() and not work_file.exists():
                report.add(f"File deleted: {rel}")
                continue

            if not orig_file.exists():
                # New file — not a breaking change.
                continue

            ext = Path(rel).suffix.lower()
            if ext == ".py":
                self._analyze_python(rel, orig_file, work_file, report)
            elif ext in {".ts", ".tsx", ".js", ".jsx", ".mjs"}:
                self._analyze_typescript(rel, orig_file, work_file, report)

    # ------------------------------------------------------------------
    # Python AST analysis
    # ------------------------------------------------------------------

    def _analyze_python(
        self,
        rel: str,
        orig_file: Path,
        work_file: Path,
        report: BreakingChangeReport,
    ) -> None:
        try:
            orig_tree = ast.parse(orig_file.read_text(encoding="utf-8", errors="replace"))
            work_tree = ast.parse(work_file.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as exc:
            report.add(f"Syntax error in patched {rel}: {exc}")
            return

        orig_api = _extract_python_api(orig_tree)
        work_api = _extract_python_api(work_tree)

        # Removed public symbols.
        for name in orig_api["functions"] - work_api["functions"]:
            report.add(f"Public function removed in {rel}: {name}()")

        for name in orig_api["classes"] - work_api["classes"]:
            report.add(f"Public class removed in {rel}: {name}")

        for name in orig_api["constants"] - work_api["constants"]:
            report.add(f"Exported constant removed in {rel}: {name}")

        # Changed function signatures.
        for sig in orig_api["signatures"]:
            name, orig_params = sig
            for wsig in work_api["signatures"]:
                wname, work_params = wsig
                if wname == name and orig_params != work_params:
                    report.add(
                        f"Function signature changed in {rel}: "
                        f"{name}({orig_params}) → {name}({work_params})"
                    )
                    break

        # Removed class methods.
        for cls_name, orig_methods in orig_api["class_methods"].items():
            work_methods = work_api["class_methods"].get(cls_name, set())
            for method in orig_methods - work_methods:
                report.add(
                    f"Public method removed from {cls_name} in {rel}: {method}()"
                )

    # ------------------------------------------------------------------
    # TypeScript / JS regex analysis
    # ------------------------------------------------------------------

    def _analyze_typescript(
        self,
        rel: str,
        orig_file: Path,
        work_file: Path,
        report: BreakingChangeReport,
    ) -> None:
        orig_exports = _extract_ts_exports(
            orig_file.read_text(encoding="utf-8", errors="replace")
        )
        work_exports = _extract_ts_exports(
            work_file.read_text(encoding="utf-8", errors="replace")
        )

        removed = orig_exports - work_exports
        for sym in sorted(removed):
            report.add(f"Exported symbol removed in {rel}: {sym}")


# ---------------------------------------------------------------------------
# Python API extraction helpers
# ---------------------------------------------------------------------------

def _extract_python_api(tree: ast.Module) -> dict:
    """Return sets of public names for functions, classes, constants, and sigs."""
    functions: set[str] = set()
    classes: set[str] = set()
    constants: set[str] = set()
    signatures: list[tuple[str, str]] = []
    class_methods: dict[str, set[str]] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if not node.name.startswith("_"):
                functions.add(node.name)
                params = _format_args(node.args)
                signatures.append((node.name, params))

        elif isinstance(node, ast.ClassDef):
            if not node.name.startswith("_"):
                classes.add(node.name)
                methods: set[str] = set()
                for item in node.body:
                    if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                        if not item.name.startswith("_"):
                            methods.add(item.name)
                class_methods[node.name] = methods

        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    constants.add(target.id)

    return {
        "functions": functions,
        "classes": classes,
        "constants": constants,
        "signatures": signatures,
        "class_methods": class_methods,
    }


def _format_args(args: ast.arguments) -> str:
    """Return a compact param string like ``a, b, *args, c=None``."""
    parts: list[str] = [a.arg for a in args.args]
    if args.vararg:
        parts.append(f"*{args.vararg.arg}")
    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}")
    for kw in args.kwonlyargs:
        parts.append(kw.arg)
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# TypeScript export extraction helper
# ---------------------------------------------------------------------------

def _extract_ts_exports(content: str) -> set[str]:
    """Return the set of exported symbol names from a TS/JS file."""
    symbols: set[str] = set()

    for m in _TS_EXPORT_RE.finditer(content):
        symbols.add(m.group(1))

    for m in _TS_REEXPORT_RE.finditer(content):
        for sym in m.group(1).split(","):
            sym = sym.strip()
            # Handle aliased exports: "Foo as Bar" → keep original name "Foo"
            if " as " in sym:
                sym = sym.split(" as ")[0].strip()
            if sym:
                symbols.add(sym)

    return symbols
