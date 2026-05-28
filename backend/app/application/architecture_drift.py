"""ArchitectureDriftService — deterministic drift detection between two scans.

Compares two architecture snapshots and surfaces structural regressions:
  * New or resolved circular dependencies
  * Layer violation growth
  * Coupling changes (ratio of dependency-graph edges to nodes)
  * Modules whose line-count grew more than the configured growth threshold

Design notes
------------
* Pure deterministic engine — no LLM, no I/O, no global state.
* All inputs and outputs are immutable Pydantic v2 value objects.
* The 15% growth threshold is configurable at construction time so callers
  (and tests) can override it without patching globals.
* ``ArchitectureDriftService`` is a stateless class; create one per request.
"""
from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default thresholds
# ---------------------------------------------------------------------------

_DEFAULT_GROWTH_THRESHOLD: float = 0.15   # flag module if size grows > 15 %
_DEFAULT_COUPLING_THRESHOLD: float = 0.15  # flag coupling if ratio grows > 15 %


# ---------------------------------------------------------------------------
# Input snapshots
# ---------------------------------------------------------------------------


class ArchitectureSnapshot(BaseModel):
    """A point-in-time architecture measurement for one scan.

    Attributes
    ----------
    circular_dependencies_count:
        Number of import cycles detected in the codebase.
    layer_violations_count:
        Number of cross-layer dependency rule violations (e.g. domain →
        infrastructure imports).
    module_sizes:
        Mapping of ``module_name → line_count``.  Only modules of interest
        need to be included; absent keys are treated as 0 lines.
    dependency_graph_edge_count:
        Total directed edges in the import dependency graph.  Used to derive
        a coupling ratio (edges / nodes).  Defaults to 0.
    dependency_graph_node_count:
        Total nodes (modules) in the dependency graph.  Defaults to 0.
    """

    circular_dependencies_count: int = Field(default=0, ge=0)
    layer_violations_count: int = Field(default=0, ge=0)
    module_sizes: dict[str, int] = Field(default_factory=dict)
    dependency_graph_edge_count: int = Field(default=0, ge=0)
    dependency_graph_node_count: int = Field(default=0, ge=0)

    model_config = {"frozen": True}

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def coupling_ratio(self) -> float:
        """Edges-per-node ratio; 0.0 when graph is empty."""
        if self.dependency_graph_node_count == 0:
            return 0.0
        return self.dependency_graph_edge_count / self.dependency_graph_node_count


# Convenience aliases matching the spec names
PreviousScanArchitectureSnapshot = ArchitectureSnapshot
CurrentScanArchitectureSnapshot = ArchitectureSnapshot


# ---------------------------------------------------------------------------
# Output report
# ---------------------------------------------------------------------------


class ArchitectureDriftReport(BaseModel):
    """Structured diff between two architecture snapshots.

    Attributes
    ----------
    new_circular_dependencies:
        Count of *additional* circular dependencies introduced (0 when
        circular deps decreased or stayed the same).
    circular_dependency_delta:
        Signed change: current − previous.  Negative means improvement.
    resolved_circular_dependencies:
        Count of circular dependencies that were fixed.
    new_layer_violations:
        Count of *additional* layer violations introduced.
    layer_violation_delta:
        Signed change: current − previous.  Negative means improvement.
    coupling_ratio_previous:
        Edges-per-node ratio of the previous snapshot.
    coupling_ratio_current:
        Edges-per-node ratio of the current snapshot.
    coupling_delta:
        ``coupling_ratio_current − coupling_ratio_previous``.  Positive
        means the codebase became more coupled.
    coupling_regressed:
        ``True`` when coupling grew by more than the configured threshold.
    modules_with_abnormal_growth:
        Names of modules whose line count grew by more than the configured
        growth threshold (default 15 %).
    has_drift:
        ``True`` when any regression metric is non-zero.
    """

    new_circular_dependencies: int = Field(ge=0)
    circular_dependency_delta: int
    resolved_circular_dependencies: int = Field(ge=0)

    new_layer_violations: int = Field(ge=0)
    layer_violation_delta: int

    coupling_ratio_previous: float = Field(ge=0.0)
    coupling_ratio_current: float = Field(ge=0.0)
    coupling_delta: float
    coupling_regressed: bool

    modules_with_abnormal_growth: list[str]

    has_drift: bool

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ArchitectureDriftService:
    """Compare two :class:`ArchitectureSnapshot` objects and report drift.

    Parameters
    ----------
    growth_threshold:
        Fraction above which a module size increase is considered abnormal.
        Defaults to ``0.15`` (15 %).
    coupling_threshold:
        Fraction above which an increase in the coupling ratio is flagged.
        Defaults to ``0.15`` (15 %).

    Usage
    -----
    ::

        svc = ArchitectureDriftService()
        report = svc.compute_drift(previous_snapshot, current_snapshot)
    """

    def __init__(
        self,
        growth_threshold: float = _DEFAULT_GROWTH_THRESHOLD,
        coupling_threshold: float = _DEFAULT_COUPLING_THRESHOLD,
    ) -> None:
        if growth_threshold <= 0:
            raise ValueError("growth_threshold must be > 0")
        if coupling_threshold <= 0:
            raise ValueError("coupling_threshold must be > 0")
        self._growth_threshold = growth_threshold
        self._coupling_threshold = coupling_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_drift(
        self,
        previous: PreviousScanArchitectureSnapshot,
        current: CurrentScanArchitectureSnapshot,
    ) -> ArchitectureDriftReport:
        """Produce an :class:`ArchitectureDriftReport` from two snapshots.

        Parameters
        ----------
        previous:
            Snapshot from the earlier scan (baseline).
        current:
            Snapshot from the most recent scan (candidate).

        Returns
        -------
        ArchitectureDriftReport
            Fully populated, immutable drift report.
        """
        circ_delta = current.circular_dependencies_count - previous.circular_dependencies_count
        layer_delta = current.layer_violations_count - previous.layer_violations_count
        coupling_delta = current.coupling_ratio - previous.coupling_ratio
        coupling_regressed = self._coupling_regressed(
            previous.coupling_ratio, current.coupling_ratio
        )
        abnormal_modules = self._abnormal_growth_modules(
            previous.module_sizes, current.module_sizes
        )

        has_drift = (
            circ_delta > 0
            or layer_delta > 0
            or coupling_regressed
            or len(abnormal_modules) > 0
        )

        report = ArchitectureDriftReport(
            new_circular_dependencies=max(0, circ_delta),
            circular_dependency_delta=circ_delta,
            resolved_circular_dependencies=max(0, -circ_delta),
            new_layer_violations=max(0, layer_delta),
            layer_violation_delta=layer_delta,
            coupling_ratio_previous=round(previous.coupling_ratio, 4),
            coupling_ratio_current=round(current.coupling_ratio, 4),
            coupling_delta=round(coupling_delta, 4),
            coupling_regressed=coupling_regressed,
            modules_with_abnormal_growth=abnormal_modules,
            has_drift=has_drift,
        )

        self._log(previous, current, report)
        return report

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _coupling_regressed(self, prev_ratio: float, curr_ratio: float) -> bool:
        """Return True if coupling increased by more than the threshold.

        When the previous ratio is 0 (empty graph) any non-zero current ratio
        is treated as a regression only when curr_ratio itself exceeds the
        threshold value — avoids false positives for first meaningful scans.
        """
        if prev_ratio == 0.0:
            return curr_ratio > self._coupling_threshold
        increase = (curr_ratio - prev_ratio) / prev_ratio
        return increase > self._coupling_threshold

    def _abnormal_growth_modules(
        self,
        previous_sizes: dict[str, int],
        current_sizes: dict[str, int],
    ) -> list[str]:
        """Return modules whose line count grew by more than the threshold.

        * New modules (absent in previous) are not flagged — their first
          appearance cannot constitute *drift*.
        * Modules that shrank are not flagged.
        * Modules with a previous size of 0 are treated as new and skipped.
        """
        flagged: list[str] = []
        for module, curr_size in current_sizes.items():
            prev_size = previous_sizes.get(module, 0)
            if prev_size == 0:
                # Module is new or had no lines previously — not drift.
                continue
            growth = (curr_size - prev_size) / prev_size
            if growth > self._growth_threshold:
                flagged.append(module)
        return sorted(flagged)  # deterministic ordering

    @staticmethod
    def _log(
        previous: ArchitectureSnapshot,
        current: ArchitectureSnapshot,
        report: ArchitectureDriftReport,
    ) -> None:
        logger.info(
            "architecture_drift_computed",
            extra={
                "circular_dependency_delta": report.circular_dependency_delta,
                "layer_violation_delta": report.layer_violation_delta,
                "coupling_delta": report.coupling_delta,
                "coupling_regressed": report.coupling_regressed,
                "abnormal_modules": report.modules_with_abnormal_growth,
                "has_drift": report.has_drift,
            },
        )
