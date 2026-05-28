"""Tests for ArchitectureDriftService (app/application/architecture_drift.py)."""
from __future__ import annotations

import pytest

from app.application.architecture_drift import (
    ArchitectureDriftReport,
    ArchitectureDriftService,
    ArchitectureSnapshot,
    PreviousScanArchitectureSnapshot,
    CurrentScanArchitectureSnapshot,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snap(
    circular: int = 0,
    violations: int = 0,
    modules: dict[str, int] | None = None,
    edges: int = 0,
    nodes: int = 0,
) -> ArchitectureSnapshot:
    return ArchitectureSnapshot(
        circular_dependencies_count=circular,
        layer_violations_count=violations,
        module_sizes=modules or {},
        dependency_graph_edge_count=edges,
        dependency_graph_node_count=nodes,
    )


SVC = ArchitectureDriftService()


# ---------------------------------------------------------------------------
# ArchitectureSnapshot — derived properties
# ---------------------------------------------------------------------------


class TestArchitectureSnapshot:
    def test_coupling_ratio_empty_graph(self):
        s = _snap(nodes=0, edges=0)
        assert s.coupling_ratio == 0.0

    def test_coupling_ratio_computed(self):
        s = _snap(edges=10, nodes=5)
        assert s.coupling_ratio == 2.0

    def test_coupling_ratio_fractional(self):
        s = _snap(edges=3, nodes=7)
        assert round(s.coupling_ratio, 4) == round(3 / 7, 4)

    def test_frozen(self):
        s = _snap()
        with pytest.raises(Exception):
            s.circular_dependencies_count = 99  # type: ignore[misc]

    def test_alias_types(self):
        """PreviousScan* and CurrentScan* are the same class."""
        assert PreviousScanArchitectureSnapshot is ArchitectureSnapshot
        assert CurrentScanArchitectureSnapshot is ArchitectureSnapshot


# ---------------------------------------------------------------------------
# ArchitectureDriftReport — construction guard
# ---------------------------------------------------------------------------


class TestArchitectureDriftReport:
    def test_frozen(self):
        r = ArchitectureDriftReport(
            new_circular_dependencies=0,
            circular_dependency_delta=0,
            resolved_circular_dependencies=0,
            new_layer_violations=0,
            layer_violation_delta=0,
            coupling_ratio_previous=1.0,
            coupling_ratio_current=1.0,
            coupling_delta=0.0,
            coupling_regressed=False,
            modules_with_abnormal_growth=[],
            has_drift=False,
        )
        with pytest.raises(Exception):
            r.has_drift = True  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ArchitectureDriftService — constructor validation
# ---------------------------------------------------------------------------


class TestServiceInit:
    def test_invalid_growth_threshold(self):
        with pytest.raises(ValueError):
            ArchitectureDriftService(growth_threshold=0.0)

    def test_invalid_coupling_threshold(self):
        with pytest.raises(ValueError):
            ArchitectureDriftService(coupling_threshold=-0.1)

    def test_custom_thresholds_accepted(self):
        svc = ArchitectureDriftService(growth_threshold=0.5, coupling_threshold=0.3)
        assert svc._growth_threshold == 0.5
        assert svc._coupling_threshold == 0.3


# ---------------------------------------------------------------------------
# Circular dependency drift
# ---------------------------------------------------------------------------


class TestCircularDependencies:
    def test_no_change(self):
        r = SVC.compute_drift(_snap(circular=3), _snap(circular=3))
        assert r.circular_dependency_delta == 0
        assert r.new_circular_dependencies == 0
        assert r.resolved_circular_dependencies == 0

    def test_new_circular_deps(self):
        r = SVC.compute_drift(_snap(circular=2), _snap(circular=5))
        assert r.circular_dependency_delta == 3
        assert r.new_circular_dependencies == 3
        assert r.resolved_circular_dependencies == 0

    def test_resolved_circular_deps(self):
        r = SVC.compute_drift(_snap(circular=5), _snap(circular=2))
        assert r.circular_dependency_delta == -3
        assert r.new_circular_dependencies == 0
        assert r.resolved_circular_dependencies == 3

    def test_all_circular_deps_resolved(self):
        r = SVC.compute_drift(_snap(circular=4), _snap(circular=0))
        assert r.resolved_circular_dependencies == 4
        assert r.new_circular_dependencies == 0

    def test_from_zero_circular(self):
        r = SVC.compute_drift(_snap(circular=0), _snap(circular=1))
        assert r.new_circular_dependencies == 1
        assert r.has_drift is True


# ---------------------------------------------------------------------------
# Layer violation drift
# ---------------------------------------------------------------------------


class TestLayerViolations:
    def test_no_change(self):
        r = SVC.compute_drift(_snap(violations=2), _snap(violations=2))
        assert r.layer_violation_delta == 0
        assert r.new_layer_violations == 0

    def test_new_violations(self):
        r = SVC.compute_drift(_snap(violations=1), _snap(violations=4))
        assert r.layer_violation_delta == 3
        assert r.new_layer_violations == 3

    def test_violations_resolved(self):
        r = SVC.compute_drift(_snap(violations=6), _snap(violations=3))
        assert r.layer_violation_delta == -3
        assert r.new_layer_violations == 0

    def test_layer_violations_contribute_to_drift(self):
        r = SVC.compute_drift(_snap(violations=0), _snap(violations=1))
        assert r.has_drift is True


# ---------------------------------------------------------------------------
# Coupling delta
# ---------------------------------------------------------------------------


class TestCouplingDelta:
    def test_no_coupling_change(self):
        r = SVC.compute_drift(
            _snap(edges=10, nodes=5),
            _snap(edges=10, nodes=5),
        )
        assert r.coupling_delta == 0.0
        assert r.coupling_regressed is False

    def test_coupling_improved(self):
        r = SVC.compute_drift(
            _snap(edges=20, nodes=5),   # ratio = 4.0
            _snap(edges=10, nodes=5),   # ratio = 2.0
        )
        assert r.coupling_delta < 0
        assert r.coupling_regressed is False

    def test_coupling_slight_increase_not_flagged(self):
        """5 % increase should NOT trigger the 15 % threshold."""
        r = SVC.compute_drift(
            _snap(edges=100, nodes=50),   # ratio = 2.0
            _snap(edges=105, nodes=50),   # ratio = 2.1 (+5%)
        )
        assert r.coupling_regressed is False

    def test_coupling_over_threshold_flagged(self):
        """20 % increase SHOULD trigger the 15 % threshold."""
        r = SVC.compute_drift(
            _snap(edges=100, nodes=50),   # ratio = 2.0
            _snap(edges=120, nodes=50),   # ratio = 2.4 (+20%)
        )
        assert r.coupling_regressed is True
        assert r.has_drift is True

    def test_coupling_exactly_threshold_not_flagged(self):
        """Exactly 15 % is not strictly greater, so should NOT be flagged."""
        r = SVC.compute_drift(
            _snap(edges=100, nodes=50),   # ratio = 2.0
            _snap(edges=115, nodes=50),   # ratio = 2.3 (+15% exactly)
        )
        assert r.coupling_regressed is False

    def test_coupling_from_empty_graph_below_threshold(self):
        """First scan with coupling ratio below threshold — not regression."""
        r = SVC.compute_drift(
            _snap(edges=0, nodes=0),
            _snap(edges=5, nodes=50),   # ratio = 0.1 < 0.15 threshold
        )
        assert r.coupling_regressed is False

    def test_coupling_from_empty_graph_above_threshold(self):
        """First scan with coupling ratio above threshold — regression."""
        r = SVC.compute_drift(
            _snap(edges=0, nodes=0),
            _snap(edges=20, nodes=50),   # ratio = 0.4 > 0.15 threshold
        )
        assert r.coupling_regressed is True


# ---------------------------------------------------------------------------
# Module growth detection
# ---------------------------------------------------------------------------


class TestModuleGrowth:
    def test_no_growth(self):
        prev = _snap(modules={"app/core.py": 100})
        curr = _snap(modules={"app/core.py": 100})
        r = SVC.compute_drift(prev, curr)
        assert r.modules_with_abnormal_growth == []

    def test_growth_below_threshold_not_flagged(self):
        """10 % growth < 15 % threshold."""
        prev = _snap(modules={"app/core.py": 100})
        curr = _snap(modules={"app/core.py": 110})
        r = SVC.compute_drift(prev, curr)
        assert r.modules_with_abnormal_growth == []

    def test_growth_above_threshold_flagged(self):
        """20 % growth > 15 % threshold."""
        prev = _snap(modules={"app/core.py": 100})
        curr = _snap(modules={"app/core.py": 120})
        r = SVC.compute_drift(prev, curr)
        assert "app/core.py" in r.modules_with_abnormal_growth

    def test_growth_exactly_threshold_not_flagged(self):
        """Exactly 15 % is not strictly greater."""
        prev = _snap(modules={"app/core.py": 100})
        curr = _snap(modules={"app/core.py": 115})
        r = SVC.compute_drift(prev, curr)
        assert r.modules_with_abnormal_growth == []

    def test_new_module_not_flagged(self):
        """A module absent in previous snapshot is new, not drift."""
        prev = _snap(modules={})
        curr = _snap(modules={"app/new.py": 500})
        r = SVC.compute_drift(prev, curr)
        assert r.modules_with_abnormal_growth == []

    def test_shrinking_module_not_flagged(self):
        prev = _snap(modules={"app/core.py": 200})
        curr = _snap(modules={"app/core.py": 100})
        r = SVC.compute_drift(prev, curr)
        assert r.modules_with_abnormal_growth == []

    def test_multiple_flagged_modules_sorted(self):
        prev = _snap(modules={"b.py": 100, "a.py": 100, "c.py": 100})
        curr = _snap(modules={"b.py": 200, "a.py": 200, "c.py": 200})
        r = SVC.compute_drift(prev, curr)
        assert r.modules_with_abnormal_growth == ["a.py", "b.py", "c.py"]

    def test_partial_module_overlap(self):
        """Only modules present in both snapshots are candidates."""
        prev = _snap(modules={"old.py": 100})
        curr = _snap(modules={"old.py": 200, "new.py": 5000})
        r = SVC.compute_drift(prev, curr)
        assert "old.py" in r.modules_with_abnormal_growth
        assert "new.py" not in r.modules_with_abnormal_growth

    def test_abnormal_growth_contributes_to_drift(self):
        prev = _snap(modules={"big.py": 100})
        curr = _snap(modules={"big.py": 300})
        r = SVC.compute_drift(prev, curr)
        assert r.has_drift is True


# ---------------------------------------------------------------------------
# has_drift flag
# ---------------------------------------------------------------------------


class TestHasDrift:
    def test_no_drift_when_everything_stable(self):
        snap = _snap(circular=2, violations=1, modules={"a.py": 100}, edges=5, nodes=5)
        r = SVC.compute_drift(snap, snap)
        assert r.has_drift is False

    def test_no_drift_on_improvements_only(self):
        """Improvements (lower values) should NOT set has_drift."""
        prev = _snap(circular=5, violations=4, edges=20, nodes=5)
        curr = _snap(circular=2, violations=1, edges=10, nodes=5)
        r = SVC.compute_drift(prev, curr)
        assert r.has_drift is False

    def test_drift_from_single_regression(self):
        prev = _snap(circular=0)
        curr = _snap(circular=1)
        r = SVC.compute_drift(prev, curr)
        assert r.has_drift is True


# ---------------------------------------------------------------------------
# Custom threshold
# ---------------------------------------------------------------------------


class TestCustomThreshold:
    def test_stricter_growth_threshold(self):
        """With a 5 % threshold, 10 % growth IS flagged."""
        svc = ArchitectureDriftService(growth_threshold=0.05)
        prev = _snap(modules={"app/core.py": 100})
        curr = _snap(modules={"app/core.py": 110})
        r = svc.compute_drift(prev, curr)
        assert "app/core.py" in r.modules_with_abnormal_growth

    def test_lenient_growth_threshold(self):
        """With a 50 % threshold, 20 % growth is NOT flagged."""
        svc = ArchitectureDriftService(growth_threshold=0.50)
        prev = _snap(modules={"app/core.py": 100})
        curr = _snap(modules={"app/core.py": 120})
        r = svc.compute_drift(prev, curr)
        assert r.modules_with_abnormal_growth == []

    def test_stricter_coupling_threshold(self):
        """With a 5 % coupling threshold, 10 % increase IS regression."""
        svc = ArchitectureDriftService(coupling_threshold=0.05)
        r = svc.compute_drift(
            _snap(edges=100, nodes=50),   # ratio = 2.0
            _snap(edges=110, nodes=50),   # ratio = 2.2 (+10%)
        )
        assert r.coupling_regressed is True
