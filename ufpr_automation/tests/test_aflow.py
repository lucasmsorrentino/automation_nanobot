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


class TestOptimizerTieBreakLogic:
    """Isolate pick_best_topology's ordering logic by mocking evaluate().

    The default integration tests above cannot reliably discriminate tie-break
    paths because the stub invoker always returns the expected categoria. These
    tests inject synthetic EvalResults so we can assert each precedence rung:

        1. higher accuracy wins (regardless of latency/errors)
        2. on accuracy tie, lower latency_mean_ms wins
        3. on accuracy+latency tie, fewer errors wins
    """

    def _patch_evaluate(self, monkeypatch, results_by_name):
        from ufpr_automation.aflow import optimizer as opt

        def fake_evaluate(name, examples, invoke_fn=None, **_kwargs):
            return results_by_name[name]

        monkeypatch.setattr(opt, "evaluate", fake_evaluate)

    def test_higher_accuracy_wins_despite_higher_latency(self, monkeypatch, tmp_path):
        self._patch_evaluate(
            monkeypatch,
            {
                "baseline": EvalResult(
                    topology="baseline",
                    n_examples=10,
                    accuracy=0.6,
                    latency_mean_ms=100.0,
                    errors=0,
                ),
                "fleet": EvalResult(
                    topology="fleet",
                    n_examples=10,
                    accuracy=0.9,
                    latency_mean_ms=1000.0,
                    errors=5,
                ),
            },
        )
        best, _ = pick_best_topology(
            topologies=["baseline", "fleet"],
            examples=[{"email": {}, "expected_categoria": "x"}],
            report_dir=tmp_path,
        )
        assert best == "fleet"

    def test_accuracy_tie_prefers_lower_latency(self, monkeypatch, tmp_path):
        self._patch_evaluate(
            monkeypatch,
            {
                "a": EvalResult(
                    topology="a",
                    n_examples=10,
                    accuracy=0.8,
                    latency_mean_ms=500.0,
                    errors=0,
                ),
                "b": EvalResult(
                    topology="b",
                    n_examples=10,
                    accuracy=0.8,
                    latency_mean_ms=200.0,
                    errors=0,
                ),
                "c": EvalResult(
                    topology="c",
                    n_examples=10,
                    accuracy=0.8,
                    latency_mean_ms=800.0,
                    errors=0,
                ),
            },
        )
        best, _ = pick_best_topology(
            topologies=["a", "b", "c"],
            examples=[{"email": {}, "expected_categoria": "x"}],
            report_dir=tmp_path,
        )
        assert best == "b"

    def test_accuracy_and_latency_tie_prefers_fewer_errors(self, monkeypatch, tmp_path):
        self._patch_evaluate(
            monkeypatch,
            {
                "noisy": EvalResult(
                    topology="noisy",
                    n_examples=10,
                    accuracy=0.8,
                    latency_mean_ms=500.0,
                    errors=3,
                ),
                "clean": EvalResult(
                    topology="clean",
                    n_examples=10,
                    accuracy=0.8,
                    latency_mean_ms=500.0,
                    errors=0,
                ),
            },
        )
        best, _ = pick_best_topology(
            topologies=["noisy", "clean"],
            examples=[{"email": {}, "expected_categoria": "x"}],
            report_dir=tmp_path,
        )
        assert best == "clean"

    def test_report_contains_every_evaluated_topology(self, monkeypatch, tmp_path):
        self._patch_evaluate(
            monkeypatch,
            {
                "a": EvalResult(topology="a", n_examples=1, accuracy=0.5),
                "b": EvalResult(topology="b", n_examples=1, accuracy=0.9),
            },
        )
        pick_best_topology(
            topologies=["a", "b"],
            examples=[{"email": {}, "expected_categoria": "x"}],
            report_dir=tmp_path,
        )
        import json

        report = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
        assert report["best"] == "b"
        assert {r["topology"] for r in report["results"]} == {"a", "b"}


class TestAblationBehavior:
    """Verify that ablation topologies actually alter behavior."""

    def test_no_self_refine_skips_refine(self, monkeypatch):
        """When AFLOW_TOPOLOGY=no_self_refine, _classify_with_litellm skips self_refine_async."""
        monkeypatch.setenv("AFLOW_TOPOLOGY", "no_self_refine")

        from unittest.mock import AsyncMock, MagicMock, patch

        from ufpr_automation.core.models import EmailClassification, EmailData

        email = EmailData(sender="test@test.com", subject="Test", body="body")
        email.compute_stable_id()

        mock_cls = EmailClassification(
            categoria="Outros", resumo="test", acao_necessaria="none", sugestao_resposta="x"
        )

        mock_client = MagicMock()
        mock_client.classify_email_async = AsyncMock(return_value=mock_cls)
        mock_client.self_refine_async = AsyncMock(return_value=mock_cls)

        with patch("ufpr_automation.llm.client.LLMClient", return_value=mock_client):
            from ufpr_automation.graph.nodes import _classify_with_litellm

            result = _classify_with_litellm([email], {email.stable_id: "context"})

        # classify was called but self_refine was NOT
        mock_client.classify_email_async.assert_called_once()
        mock_client.self_refine_async.assert_not_called()
        assert email.stable_id in result

    def test_fleet_topology_calls_self_refine(self, monkeypatch):
        """When AFLOW_TOPOLOGY=fleet (default), self_refine IS called."""
        monkeypatch.setenv("AFLOW_TOPOLOGY", "fleet")

        from unittest.mock import AsyncMock, MagicMock, patch

        from ufpr_automation.core.models import EmailClassification, EmailData

        email = EmailData(sender="test@test.com", subject="Test", body="body")
        email.compute_stable_id()

        mock_cls = EmailClassification(
            categoria="Outros", resumo="test", acao_necessaria="none", sugestao_resposta="x"
        )

        mock_client = MagicMock()
        mock_client.classify_email_async = AsyncMock(return_value=mock_cls)
        mock_client.self_refine_async = AsyncMock(return_value=mock_cls)

        with patch("ufpr_automation.llm.client.LLMClient", return_value=mock_client):
            from ufpr_automation.graph.nodes import _classify_with_litellm

            _classify_with_litellm([email], {email.stable_id: "context"})

        mock_client.classify_email_async.assert_called_once()
        mock_client.self_refine_async.assert_called_once()

    def test_skip_rag_high_tier0_skips_near_miss_emails(self, monkeypatch):
        """When AFLOW_TOPOLOGY=skip_rag_high_tier0, rag_retrieve skips emails
        whose Tier 0 near-miss score exceeded the threshold."""
        monkeypatch.setenv("AFLOW_TOPOLOGY", "skip_rag_high_tier0")
        monkeypatch.setenv("SKIP_RAG_NEAR_MISS_THRESHOLD", "0.75")

        from unittest.mock import MagicMock, patch

        from ufpr_automation.core.models import EmailData
        from ufpr_automation.graph.nodes import rag_retrieve

        email_high = EmailData(sender="a@a.com", subject="High near-miss", body="body1")
        email_high.compute_stable_id()
        email_low = EmailData(sender="b@b.com", subject="Low near-miss", body="body2")
        email_low.compute_stable_id()

        state = {
            "emails": [email_high, email_low],
            "tier0_hits": [],
            "tier0_near_miss_scores": {
                email_high.stable_id: 0.85,  # above 0.75 -> skip
                email_low.stable_id: 0.60,  # below 0.75 -> keep
            },
        }

        # Stub the retriever — we just need to see which emails get queried
        searched_subjects: list[str] = []

        fake_retriever = MagicMock()

        def fake_search(query, conselho=None, top_k=5):
            searched_subjects.append(query[:20])
            return []

        fake_retriever.search_formatted.side_effect = lambda q, top_k=5: (
            searched_subjects.append(q[:20]) or ""
        )

        with (
            patch("ufpr_automation.graph.nodes._get_retriever", return_value=fake_retriever),
            patch("ufpr_automation.graph.nodes._get_graph_context", return_value=""),
            patch("ufpr_automation.graph.nodes._get_reflexion_context_single", return_value=""),
        ):
            rag_retrieve(state)

        # The high-near-miss email should NOT have been queried
        high_subject_queried = any("High near-miss" in s for s in searched_subjects)
        low_subject_queried = any("Low near-miss" in s for s in searched_subjects)
        assert high_subject_queried is False
        assert low_subject_queried is True

    def test_fleet_no_siga_skips_siga_in_process_one_email(self, monkeypatch):
        """When AFLOW_TOPOLOGY=fleet_no_siga, process_one_email skips SIGA."""
        monkeypatch.setenv("AFLOW_TOPOLOGY", "fleet_no_siga")

        from unittest.mock import patch

        from ufpr_automation.core.models import EmailClassification, EmailData

        email = EmailData(sender="test@test.com", subject="Estágio TCE", body="TCE aluno")
        email.compute_stable_id()

        mock_cls = EmailClassification(
            categoria="Estágios",
            resumo="TCE",
            acao_necessaria="Abrir Processo SEI",
            sugestao_resposta="...",
        )

        with (
            patch("ufpr_automation.graph.nodes._should_use_dspy", return_value=False),
            patch(
                "ufpr_automation.graph.nodes._classify_with_litellm",
                return_value={email.stable_id: mock_cls},
            ),
            patch("ufpr_automation.graph.nodes._get_retriever", side_effect=Exception("no rag")),
            patch("ufpr_automation.graph.nodes._get_graph_context", return_value=""),
            patch("ufpr_automation.graph.nodes._get_reflexion_context_single", return_value=""),
            patch(
                "ufpr_automation.graph.nodes._consult_sei_for_email", return_value=None
            ) as mock_sei,
            patch(
                "ufpr_automation.graph.nodes._consult_siga_for_email", return_value=None
            ) as mock_siga,
        ):
            from ufpr_automation.graph.fleet import process_one_email

            process_one_email({"email": email, "stable_id": email.stable_id})

        mock_sei.assert_called_once()
        mock_siga.assert_not_called()  # SIGA was skipped


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
