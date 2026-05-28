"""Validation pipeline — runs linters / test runners against a virtual workspace.

Executes available tools in the workspace directory:

+----------+----------------+---------------------------------------------------+
| Tool     | Language       | Command                                           |
+==========+================+===================================================+
| pytest   | Python         | ``python -m pytest --tb=short -q``                |
| mypy     | Python         | ``python -m mypy --ignore-missing-imports .``     |
| eslint   | JS/TS          | ``npx eslint . --ext .js,.ts,.jsx,.tsx``           |
| tsc      | TypeScript     | ``npx tsc --noEmit``                              |
+----------+----------------+---------------------------------------------------+

Each tool is:
- Only run if its binary / module is detectable in the workspace environment.
- Run as an async subprocess with a configurable timeout (default 120 s).
- Run in the workspace directory — never in the original source tree.
- Rejected if the command arguments are not in the hard-coded allow-list
  (prevents shell injection).

Usage::

    pipeline = ValidationPipeline()
    report = await pipeline.run(workspace)
    if not report.passed:
        print(report.errors)
"""
from __future__ import annotations

import asyncio
import shutil
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.application.virtual_workspace import VirtualWorkspace

logger = get_logger(__name__)

_DEFAULT_TOOL_TIMEOUT: float = 120.0
_MAX_OUTPUT_BYTES = 65_536  # 64 KB per tool


@dataclass
class ValidationReport:
    """Outcome of the validation pipeline."""

    lint_passed: bool = True
    tests_passed: bool = True
    type_check_passed: bool = True
    errors: list[str] = field(default_factory=list)
    tool_outputs: dict[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.lint_passed and self.tests_passed and self.type_check_passed

    def add_error(self, tool: str, detail: str) -> None:
        self.errors.append(f"[{tool}] {detail}")


class ValidationPipeline:
    """Runs available linting/testing tools against a virtual workspace.

    Args:
        tool_timeout: Per-tool subprocess timeout in seconds.
        run_pytest:   Whether to attempt running pytest (default True).
        run_mypy:     Whether to attempt running mypy (default True).
        run_eslint:   Whether to attempt running eslint (default True).
        run_tsc:      Whether to attempt running tsc (default True).
    """

    def __init__(
        self,
        tool_timeout: float = _DEFAULT_TOOL_TIMEOUT,
        run_pytest: bool = True,
        run_mypy: bool = True,
        run_eslint: bool = True,
        run_tsc: bool = True,
    ) -> None:
        self._timeout = tool_timeout
        self._run_pytest = run_pytest
        self._run_mypy = run_mypy
        self._run_eslint = run_eslint
        self._run_tsc = run_tsc

    async def run(self, workspace: "VirtualWorkspace") -> ValidationReport:
        """Run all available tools against *workspace* and return a report.

        Tools that are not installed are silently skipped (they do not
        contribute failures to the report).
        """
        report = ValidationReport()
        work_dir = workspace.work_path

        tasks = []
        if self._run_pytest:
            tasks.append(self._run_pytest_tool(work_dir, report))
        if self._run_mypy:
            tasks.append(self._run_mypy_tool(work_dir, report))
        if self._run_eslint:
            tasks.append(self._run_eslint_tool(work_dir, report))
        if self._run_tsc:
            tasks.append(self._run_tsc_tool(work_dir, report))

        await asyncio.gather(*tasks)

        logger.info(
            "validation_pipeline.done",
            passed=report.passed,
            errors=len(report.errors),
        )
        return report

    # ------------------------------------------------------------------
    # Individual tool runners
    # ------------------------------------------------------------------

    async def _run_pytest_tool(self, work_dir: str, report: ValidationReport) -> None:
        if not _module_available("pytest"):
            logger.debug("validation_pipeline.pytest_not_found")
            return

        ok, output = await self._run_subprocess(
            cmd=[sys.executable, "-m", "pytest", "--tb=short", "-q", "--no-header"],
            cwd=work_dir,
            tool="pytest",
        )
        report.tool_outputs["pytest"] = output
        if not ok:
            report.tests_passed = False
            report.add_error("pytest", _truncate(output))

    async def _run_mypy_tool(self, work_dir: str, report: ValidationReport) -> None:
        if not _module_available("mypy"):
            logger.debug("validation_pipeline.mypy_not_found")
            return

        ok, output = await self._run_subprocess(
            cmd=[
                sys.executable, "-m", "mypy",
                "--ignore-missing-imports",
                "--no-error-summary",
                ".",
            ],
            cwd=work_dir,
            tool="mypy",
        )
        report.tool_outputs["mypy"] = output
        if not ok:
            report.type_check_passed = False
            report.add_error("mypy", _truncate(output))

    async def _run_eslint_tool(self, work_dir: str, report: ValidationReport) -> None:
        npx = shutil.which("npx")
        if not npx:
            logger.debug("validation_pipeline.npx_not_found")
            return

        ok, output = await self._run_subprocess(
            cmd=[
                npx, "eslint", ".",
                "--ext", ".js,.ts,.jsx,.tsx",
                "--max-warnings", "0",
            ],
            cwd=work_dir,
            tool="eslint",
        )
        report.tool_outputs["eslint"] = output
        if not ok:
            report.lint_passed = False
            report.add_error("eslint", _truncate(output))

    async def _run_tsc_tool(self, work_dir: str, report: ValidationReport) -> None:
        npx = shutil.which("npx")
        if not npx:
            logger.debug("validation_pipeline.npx_not_found")
            return

        ok, output = await self._run_subprocess(
            cmd=[npx, "tsc", "--noEmit"],
            cwd=work_dir,
            tool="tsc",
        )
        report.tool_outputs["tsc"] = output
        if not ok:
            report.type_check_passed = False
            report.add_error("tsc", _truncate(output))

    # ------------------------------------------------------------------
    # Subprocess runner
    # ------------------------------------------------------------------

    async def _run_subprocess(
        self,
        cmd: list[str],
        cwd: str,
        tool: str,
    ) -> tuple[bool, str]:
        """Execute *cmd* in *cwd* with a timeout.  Returns (success, combined_output)."""
        logger.debug("validation_pipeline.run_tool", tool=tool, cmd=cmd)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=self._timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                msg = f"{tool} timed out after {self._timeout:.0f}s"
                logger.warning("validation_pipeline.tool_timeout", tool=tool)
                return False, msg

            output = stdout.decode("utf-8", errors="replace") if stdout else ""
            success = proc.returncode == 0
            logger.debug(
                "validation_pipeline.tool_done",
                tool=tool,
                returncode=proc.returncode,
                output_len=len(output),
            )
            return success, output

        except FileNotFoundError:
            logger.debug("validation_pipeline.tool_not_found", tool=tool)
            return True, ""  # Not installed → skip (not a failure)
        except Exception as exc:  # noqa: BLE001
            logger.error("validation_pipeline.tool_error", tool=tool, error=str(exc))
            return False, str(exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _module_available(module: str) -> bool:
    """Return True if *module* can be imported as a Python module."""
    import importlib.util
    return importlib.util.find_spec(module) is not None


def _truncate(text: str, max_chars: int = 2000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n… (truncated, {len(text) - max_chars} chars omitted)"
