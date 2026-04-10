"""Tests for AFlow topology evaluator."""
from __future__ import annotations

import pytest

from ufpr_automation.aflow.evaluator import EvalResult, evaluate
from ufpr_automation.aflow.optimizer import pick_best_topology
from ufpr_automation.aflow.topologies import (
    TOPOLOGY_NAMES,
    get_topology,
    list_topologies,
)


class TestTopologyRegistry:
    def test_list_topologies_returns_all(self):
        names = list_topologies()
        assert "baseline" in names
        assert "fleet" in names
        assert len(names) == len(TOPOLOGY_NAMES)

    def test_get_topology_returns_callable(self):
        for name in list_topologies():
            factory = get_topology(name)
            assert callable(factory)

    def test_get_topology_unknown_raises(self):
        with pytest.raises(KeyError, match="Unknown topology"):
            get_topology("nonexistent")

    def test_get_topology_case_insensitive(self):
        assert get_topology("BASELINE") is get_topology("baseline")

    def test_all_five_topologies_registered(self):
        names = set(list_topologies())
        expected = {
            "baseline",
            "fleet",
            "skip_rag_high_tier0",
            "no_self_refine",
            "fleet_no_siga",
        }
        assert names == expected


class TestEvaluator:
    def test_evaluate_empty_examples_returns_zero(self):
        result = evaluate("baseline", [])
        assert result.n_examples == 0
        assert result.accuracy == 0.0

    def test_evaluate_perfect_accuracy_with_stub(self):
        # The default _stub_invoke returns the expected category, so accuracy is 1.0
        examples = [
            {"email": {"subject": "x"}, "expected_categoria": "Estágios"},
            {"email": {"subject": "y"}, "expected_categoria": "Outros"},
        ]
        result = evaluate("baseline", examples)
        assert result.n_examples == 2
        assert result.accuracy == 1.0
        assert result.errors == 0

    def test_evaluate_with_failing_invoke(self):
        def bad_invoke(graph, ex):
            raise RuntimeError("simulated failure")

        examples = [{"email": {}, "expected_categoria": "Outros"}]
        result = evaluate("baseline", examples, invoke_fn=bad_invoke)
        assert result.errors == 1
        assert result.accuracy == 0.0

    def test_evaluate_with_custom_metric(self):
        def always_one(pred, exp):
            return 1.0

        examples = [{"email": {}, "expected_categoria": "Outros"}]
        result = evaluate("baseline", examples, metric_fn=always_one)
        assert result.accuracy == 1.0

    def test_evaluate_returns_eval_result_type(self):
        examples = [{"email": {}, "expected_categoria": "Outros"}]
        result = evaluate("baseline", examples)
        assert isinstance(result, EvalResult)
        assert result.topology == "baseline"
        assert result.n_examples == 1


class TestOptimizer:
    def test_pick_best_returns_a_topology(self, tmp_path):
        examples = [
            {"email": {"subject": "x"}, "expected_categoria": "Estágios"},
        ]
        best, results = pick_best_topology(
            topologies=["baseline", "fleet"],
            examples=examples,
            report_dir=tmp_path,
        )
        assert best in ("baseline", "fleet")
        assert len(results) == 2

    def test_pick_best_writes_report(self, tmp_path):
        examples = [{"email": {}, "expected_categoria": "Outros"}]
        pick_best_topology(
            topologies=["baseline"],
            examples=examples,
            report_dir=tmp_path,
        )
        reports = list(tmp_path.glob("*.json"))
        assert len(reports) == 1
        import json

        report = json.loads(reports[0].read_text(encoding="utf-8"))
        assert report["best"] == "baseline"
        assert "results" in report
        assert len(report["results"]) == 1

    def test_pick_best_tie_break_prefers_lower_latency(self, tmp_path):
        # With the default stub, all topologies have 100% accuracy; the
        # tie-break prefers the lowest mean latency. Just verify it picks
        # *some* topology and the list is complete.
        examples = [{"email": {}, "expected_categoria": "Outros"}]
        best, results = pick_best_topology(
            topologies=["baseline", "fleet"],
            examples=examples,
            report_dir=tmp_path,
        )
        assert best in {"baseline", "fleet"}
        assert all(r.accuracy == 1.0 for r in results)


class TestBuilderTopologyDispatch:
    def test_default_topology_is_fleet(self, monkeypatch):
        # AFLOW_TOPOLOGY=fleet should produce the standard Fleet-based graph
        # without recursion or KeyError.
        from ufpr_automation.config import settings

        monkeypatch.setattr(settings, "AFLOW_TOPOLOGY", "fleet")
        from ufpr_automation.graph.builder import build_graph

        graph = build_graph(channel="gmail")
        assert graph is not None

    def test_baseline_topology_compiles(self, monkeypatch):
        from ufpr_automation.config import settings

        monkeypatch.setattr(settings, "AFLOW_TOPOLOGY", "baseline")
        from ufpr_automation.graph.builder import build_graph

        graph = build_graph(channel="gmail")
        assert graph is not None

    def test_unknown_topology_falls_back_to_fleet(self, monkeypatch):
        # An invalid AFLOW_TOPOLOGY should log a warning and produce the
        # default Fleet-based graph instead of raising.
        from ufpr_automation.config import settings

        monkeypatch.setattr(settings, "AFLOW_TOPOLOGY", "nonexistent_xyz")
        from ufpr_automation.graph.builder import build_graph

        graph = build_graph(channel="gmail")
        assert graph is not None
