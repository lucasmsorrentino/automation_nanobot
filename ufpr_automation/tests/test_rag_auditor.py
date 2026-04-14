"""Tests for agent_sdk/rag_auditor — RAG Quality Auditor."""

from __future__ import annotations

import json
from dataclasses import dataclass

from ufpr_automation.agent_sdk.rag_auditor import (
    AuditReport,
    QueryResult,
    aggregate_metrics,
    compare_to_baseline,
    format_report,
    load_ground_truth,
    run_audit,
    run_query,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@dataclass
class FakeSearchResult:
    text: str
    score: float
    conselho: str = ""
    tipo: str = ""
    arquivo: str = ""
    caminho: str = ""
    chunk_idx: int = 0


class FakeRetriever:
    """In-memory retriever for tests.

    Maps query substring → list of (arquivo, score) tuples.
    """

    def __init__(self, responses: dict[str, list[tuple[str, float]]]):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def search(self, query: str, *, conselho=None, tipo=None, top_k: int = 10):
        self.calls.append((query, {"conselho": conselho, "top_k": top_k}))
        # Find the matching response by longest query-substring match
        best_match = None
        for key in self.responses:
            if key.lower() in query.lower():
                best_match = key
                break
        if best_match is None:
            return []
        return [
            FakeSearchResult(
                text=f"content of {name}",
                score=score,
                arquivo=name,
                caminho=f"/path/{name}",
                conselho=conselho or "",
            )
            for name, score in self.responses[best_match][:top_k]
        ]


# ---------------------------------------------------------------------------
# load_ground_truth
# ---------------------------------------------------------------------------

class TestLoadGroundTruth:
    def test_loads_valid_yaml(self, tmp_path):
        gt = tmp_path / "gt.yaml"
        gt.write_text(
            "queries:\n"
            "  - id: q1\n"
            "    query: 'test query'\n"
            "    expected_doc_substring: 'regulamento'\n"
            "    expected_in_top_k: 3\n"
            "    subset: estagio\n",
            encoding="utf-8",
        )
        queries = load_ground_truth(gt)
        assert len(queries) == 1
        assert queries[0]["id"] == "q1"

    def test_missing_file_returns_empty(self, tmp_path):
        assert load_ground_truth(tmp_path / "nope.yaml") == []

    def test_malformed_returns_empty(self, tmp_path):
        gt = tmp_path / "gt.yaml"
        gt.write_text("not a mapping", encoding="utf-8")
        assert load_ground_truth(gt) == []


# ---------------------------------------------------------------------------
# run_query
# ---------------------------------------------------------------------------

class TestRunQuery:
    def test_query_hit_at_rank_0(self):
        retriever = FakeRetriever({
            "regulamento": [("Regulamento_Estagio.pdf", 0.85), ("other.pdf", 0.60)],
        })
        spec = {
            "id": "q1",
            "query": "regulamento de estágio",
            "expected_doc_substring": "Regulamento_Estagio",
            "expected_in_top_k": 3,
            "subset": "estagio",
        }
        result = run_query(spec, retriever)
        assert result.is_hit is True
        assert result.found_at_rank == 0
        assert result.top_score == 0.85

    def test_query_miss(self):
        retriever = FakeRetriever({
            "regulamento": [("OtherDoc.pdf", 0.70)],
        })
        spec = {
            "id": "q2",
            "query": "regulamento de estágio",
            "expected_doc_substring": "ExpectedDoc",
            "expected_in_top_k": 3,
            "subset": "estagio",
        }
        result = run_query(spec, retriever)
        assert result.is_hit is False
        assert result.found_at_rank == -1

    def test_query_measures_latency(self):
        retriever = FakeRetriever({"q": [("doc.pdf", 0.5)]})
        spec = {
            "id": "q3", "query": "q", "expected_doc_substring": "doc",
            "expected_in_top_k": 1, "subset": "",
        }
        result = run_query(spec, retriever)
        assert result.latency_ms >= 0

    def test_empty_results_returns_miss(self):
        retriever = FakeRetriever({})
        spec = {
            "id": "q4", "query": "nothing", "expected_doc_substring": "x",
            "expected_in_top_k": 3, "subset": "",
        }
        result = run_query(spec, retriever)
        assert result.is_hit is False
        assert result.top_score == 0.0


# ---------------------------------------------------------------------------
# aggregate_metrics
# ---------------------------------------------------------------------------

class TestAggregateMetrics:
    def test_per_subset_aggregation(self):
        results = [
            QueryResult("q1", "a", "estagio", "x", 3, found_at_rank=0, top_score=0.9, latency_ms=100),
            QueryResult("q2", "b", "estagio", "y", 3, found_at_rank=-1, top_score=0.5, latency_ms=120),
            QueryResult("q3", "c", "cepe", "z", 3, found_at_rank=1, top_score=0.8, latency_ms=200),
        ]
        metrics = aggregate_metrics(results)
        assert metrics["estagio"].recall == 0.5  # 1/2
        assert metrics["cepe"].recall == 1.0
        assert metrics["estagio"].n_queries == 2

    def test_empty_subset_counted_as_unknown(self):
        results = [QueryResult("q", "x", "", "", 3, found_at_rank=0, top_score=0.9)]
        metrics = aggregate_metrics(results)
        assert "unknown" in metrics


# ---------------------------------------------------------------------------
# compare_to_baseline
# ---------------------------------------------------------------------------

class TestCompareToBaseline:
    def _make_report(self, recall=1.0, score=0.85, latency=100.0):
        return AuditReport(
            run_id="r1", timestamp="2026-04-12T00:00:00Z",
            total_queries=5,
            overall_recall=recall, avg_score=score, avg_latency_ms=latency,
            per_subset={},
        )

    def test_low_recall_triggers_alert(self):
        report = self._make_report(recall=0.50)
        alerts = compare_to_baseline(report, None)
        assert any("recall" in a for a in alerts)

    def test_perfect_recall_no_alert(self):
        report = self._make_report(recall=1.0)
        alerts = compare_to_baseline(report, None)
        assert alerts == []

    def test_score_drift_triggers_alert(self):
        report = self._make_report(score=0.50)
        baseline = {"avg_score": 0.85, "avg_latency_ms": 100}
        alerts = compare_to_baseline(report, baseline)
        assert any("avg_score dropped" in a for a in alerts)

    def test_latency_regression_triggers_alert(self):
        report = self._make_report(latency=300.0)
        baseline = {"avg_score": 0.85, "avg_latency_ms": 100}
        alerts = compare_to_baseline(report, baseline)
        assert any("latency increased" in a for a in alerts)


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------

class TestFormatReport:
    def test_report_contains_key_sections(self):
        report = AuditReport(
            run_id="r1", timestamp="2026-04-12T00:00:00Z",
            total_queries=2, overall_recall=0.5, avg_score=0.7, avg_latency_ms=150,
            per_query=[
                QueryResult("q1", "test", "estagio", "doc", 3, found_at_rank=0, top_score=0.9),
            ],
            per_subset={},
            alerts=["ALERT: test alert"],
        )
        md = format_report(report)
        assert "# RAG Quality Audit" in md
        assert "r1" in md
        assert "Alerts" in md
        assert "test alert" in md
        assert "Per-Query Detail" in md


# ---------------------------------------------------------------------------
# run_audit (integration)
# ---------------------------------------------------------------------------

class TestRunAudit:
    def test_end_to_end_no_baseline(self, tmp_path):
        gt = tmp_path / "gt.yaml"
        gt.write_text(
            "queries:\n"
            "  - id: q1\n"
            "    query: 'regulamento'\n"
            "    expected_doc_substring: 'regulamento'\n"
            "    expected_in_top_k: 3\n"
            "    subset: estagio\n",
            encoding="utf-8",
        )

        retriever = FakeRetriever({
            "regulamento": [("Regulamento.pdf", 0.88)],
        })

        report = run_audit(
            ground_truth_path=gt,
            baseline_path=tmp_path / "baseline.json",
            report_dir=tmp_path / "reports",
            retriever=retriever,
        )

        assert report.total_queries == 1
        assert report.overall_recall == 1.0
        # Report written
        reports = list((tmp_path / "reports").rglob("report.md"))
        assert len(reports) == 1
        # Baseline created on success
        assert (tmp_path / "baseline.json").exists()

    def test_baseline_not_updated_when_alert(self, tmp_path):
        gt = tmp_path / "gt.yaml"
        gt.write_text(
            "queries:\n"
            "  - id: q1\n"
            "    query: 'nothing'\n"
            "    expected_doc_substring: 'missing'\n"
            "    expected_in_top_k: 3\n"
            "    subset: estagio\n",
            encoding="utf-8",
        )

        retriever = FakeRetriever({})  # empty => recall 0

        baseline_path = tmp_path / "baseline.json"
        baseline_path.write_text(json.dumps({"avg_score": 0.9, "avg_latency_ms": 100}), encoding="utf-8")
        original_baseline = baseline_path.read_text(encoding="utf-8")

        report = run_audit(
            ground_truth_path=gt,
            baseline_path=baseline_path,
            report_dir=tmp_path / "reports",
            retriever=retriever,
        )

        assert len(report.alerts) > 0
        # Baseline NOT overwritten
        assert baseline_path.read_text(encoding="utf-8") == original_baseline

    def test_empty_ground_truth(self, tmp_path):
        gt = tmp_path / "empty.yaml"
        gt.write_text("queries: []\n", encoding="utf-8")

        report = run_audit(
            ground_truth_path=gt,
            baseline_path=tmp_path / "bl.json",
            report_dir=tmp_path / "reports",
            retriever=FakeRetriever({}),
        )
        assert report.total_queries == 0
