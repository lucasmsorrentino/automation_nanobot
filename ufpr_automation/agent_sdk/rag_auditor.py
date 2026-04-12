"""RAG Quality Auditor — monitors RAG retrieval quality over time.

Runs a curated set of queries against the RAG store and measures recall,
score drift, and latency vs a stored baseline. Flags regressions above
configurable thresholds.

See ``SDD_CLAUDE_CODE_AUTOMATIONS.md §6`` for the full spec.

Ground truth format (``eval_sets/rag_ground_truth.yaml``)::

    queries:
      - id: estagio_regulamento_dg
        query: "regulamento de estágio do curso de Design Gráfico"
        expected_doc_substring: "Regulamento de Estágio Design"
        expected_in_top_k: 3
        subset: estagio
        notes: "Doc canônico, deveria sempre ser top-1"

CLI::

    python -m ufpr_automation.agent_sdk.rag_auditor
    python -m ufpr_automation.agent_sdk.rag_auditor --quick
    python -m ufpr_automation.agent_sdk.rag_auditor --ground-truth custom.yaml
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ufpr_automation.config import settings

logger = logging.getLogger(__name__)

AUDITOR_DIR = settings.PACKAGE_ROOT / "procedures_data" / "agent_sdk" / "rag_auditor"
BASELINE_FILE = AUDITOR_DIR / "baseline.json"
DEFAULT_GROUND_TRUTH = settings.PACKAGE_ROOT / "agent_sdk" / "eval_sets" / "rag_ground_truth.yaml"

# Thresholds for alerts
RECALL_THRESHOLD = 0.90
SCORE_DRIFT_THRESHOLD = 0.10
LATENCY_DRIFT_THRESHOLD = 0.50  # 50% slower than baseline


@dataclass
class QueryResult:
    """Result of running a single ground-truth query."""

    query_id: str
    query: str
    subset: str
    expected_substring: str
    expected_in_top_k: int
    # Measured
    found_at_rank: int = -1  # -1 means not found in top_k
    top_score: float = 0.0
    latency_ms: int = 0
    top_docs: list[str] = field(default_factory=list)

    @property
    def is_hit(self) -> bool:
        """True if expected doc was found within expected_in_top_k."""
        return 0 <= self.found_at_rank < self.expected_in_top_k


@dataclass
class SubsetMetrics:
    """Aggregate metrics per RAG subset."""

    subset: str
    n_queries: int = 0
    n_hits: int = 0
    avg_score: float = 0.0
    avg_latency_ms: float = 0.0

    @property
    def recall(self) -> float:
        return self.n_hits / self.n_queries if self.n_queries else 0.0


@dataclass
class AuditReport:
    """Full audit run report."""

    run_id: str
    timestamp: str
    total_queries: int
    overall_recall: float
    avg_score: float
    avg_latency_ms: float
    per_query: list[QueryResult] = field(default_factory=list)
    per_subset: dict[str, SubsetMetrics] = field(default_factory=dict)
    alerts: list[str] = field(default_factory=list)


def load_ground_truth(path: Path | None = None) -> list[dict]:
    """Load the ground truth YAML file."""
    p = path or DEFAULT_GROUND_TRUTH
    if not p.exists():
        logger.warning("Ground truth file not found: %s", p)
        return []

    import yaml

    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return []
    return data.get("queries", [])


def run_query(
    query_spec: dict,
    retriever: Any,
) -> QueryResult:
    """Execute one ground-truth query and measure recall + latency."""
    q_id = query_spec.get("id", "?")
    query = query_spec.get("query", "")
    subset = query_spec.get("subset", "")
    expected_sub = query_spec.get("expected_doc_substring", "")
    top_k = int(query_spec.get("expected_in_top_k", 3))

    result = QueryResult(
        query_id=q_id,
        query=query,
        subset=subset,
        expected_substring=expected_sub,
        expected_in_top_k=top_k,
    )

    # Optional conselho filter derived from subset
    conselho = subset if subset in {"cepe", "coun", "coplad", "concur", "estagio"} else None

    t0 = time.monotonic()
    try:
        results = retriever.search(query, conselho=conselho, top_k=max(top_k, 5))
    except Exception as e:
        logger.warning("Query '%s' failed: %s", q_id, e)
        result.latency_ms = int((time.monotonic() - t0) * 1000)
        return result

    result.latency_ms = int((time.monotonic() - t0) * 1000)

    if not results:
        return result

    result.top_score = float(results[0].score)
    result.top_docs = [r.arquivo for r in results[:top_k]]

    # Find the expected doc by substring match on arquivo / caminho / text
    for i, r in enumerate(results[:top_k]):
        haystack = f"{r.arquivo} {r.caminho} {r.text[:200]}"
        if expected_sub.lower() in haystack.lower():
            result.found_at_rank = i
            break

    return result


def aggregate_metrics(results: list[QueryResult]) -> dict[str, SubsetMetrics]:
    """Compute per-subset aggregate metrics."""
    by_subset: dict[str, list[QueryResult]] = {}
    for r in results:
        by_subset.setdefault(r.subset or "unknown", []).append(r)

    out: dict[str, SubsetMetrics] = {}
    for subset, recs in by_subset.items():
        scores = [r.top_score for r in recs if r.top_score > 0]
        latencies = [r.latency_ms for r in recs]
        out[subset] = SubsetMetrics(
            subset=subset,
            n_queries=len(recs),
            n_hits=sum(1 for r in recs if r.is_hit),
            avg_score=statistics.mean(scores) if scores else 0.0,
            avg_latency_ms=statistics.mean(latencies) if latencies else 0.0,
        )
    return out


def compare_to_baseline(
    report: AuditReport,
    baseline: dict | None,
) -> list[str]:
    """Compare current metrics to baseline and generate alerts."""
    alerts: list[str] = []

    # Hard thresholds (independent of baseline)
    if report.overall_recall < RECALL_THRESHOLD:
        alerts.append(
            f"ALERT: overall recall {report.overall_recall:.2%} is below "
            f"threshold {RECALL_THRESHOLD:.0%}"
        )

    for subset_name, m in report.per_subset.items():
        if m.recall < RECALL_THRESHOLD:
            alerts.append(
                f"ALERT: subset '{subset_name}' recall {m.recall:.2%} is below "
                f"threshold {RECALL_THRESHOLD:.0%} ({m.n_hits}/{m.n_queries})"
            )

    # Drift vs baseline
    if baseline:
        base_score = baseline.get("avg_score", 0.0)
        if base_score > 0:
            drift = (base_score - report.avg_score) / base_score
            if drift > SCORE_DRIFT_THRESHOLD:
                alerts.append(
                    f"ALERT: avg_score dropped {drift:.1%} vs baseline "
                    f"({base_score:.3f} -> {report.avg_score:.3f})"
                )

        base_lat = baseline.get("avg_latency_ms", 0.0)
        if base_lat > 0:
            lat_drift = (report.avg_latency_ms - base_lat) / base_lat
            if lat_drift > LATENCY_DRIFT_THRESHOLD:
                alerts.append(
                    f"ALERT: avg latency increased {lat_drift:.1%} vs baseline "
                    f"({base_lat:.0f}ms -> {report.avg_latency_ms:.0f}ms)"
                )

    return alerts


def run_audit(
    *,
    ground_truth_path: Path | None = None,
    baseline_path: Path | None = None,
    report_dir: Path | None = None,
    retriever: Any = None,
    quick: bool = False,
) -> AuditReport:
    """Run the full RAG quality audit."""
    queries = load_ground_truth(ground_truth_path)
    if not queries:
        logger.warning("No ground truth queries loaded; aborting audit")
        return AuditReport(
            run_id="empty",
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_queries=0,
            overall_recall=0.0,
            avg_score=0.0,
            avg_latency_ms=0.0,
        )

    if quick:
        queries = queries[:5]

    if retriever is None:
        from ufpr_automation.rag.retriever import Retriever

        retriever = Retriever()

    results = [run_query(q, retriever) for q in queries]

    run_id = uuid.uuid4().hex[:12]
    scores = [r.top_score for r in results if r.top_score > 0]
    latencies = [r.latency_ms for r in results]
    hits = sum(1 for r in results if r.is_hit)

    report = AuditReport(
        run_id=run_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        total_queries=len(results),
        overall_recall=hits / len(results) if results else 0.0,
        avg_score=statistics.mean(scores) if scores else 0.0,
        avg_latency_ms=statistics.mean(latencies) if latencies else 0.0,
        per_query=results,
        per_subset=aggregate_metrics(results),
    )

    # Compare to baseline
    bl_path = baseline_path or BASELINE_FILE
    baseline = None
    if bl_path.exists():
        try:
            baseline = json.loads(bl_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Failed to read baseline %s: %s", bl_path, e)

    report.alerts = compare_to_baseline(report, baseline)

    # Write report
    out_dir = report_dir or AUDITOR_DIR
    run_dir = out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    report_md = run_dir / "report.md"
    report_md.write_text(format_report(report), encoding="utf-8")
    logger.info("Audit report written: %s", report_md)

    # Update baseline atomically if no alerts
    if not report.alerts:
        bl_data = {
            "timestamp": report.timestamp,
            "run_id": report.run_id,
            "total_queries": report.total_queries,
            "overall_recall": report.overall_recall,
            "avg_score": report.avg_score,
            "avg_latency_ms": report.avg_latency_ms,
        }
        bl_path.parent.mkdir(parents=True, exist_ok=True)
        bl_path.write_text(json.dumps(bl_data, indent=2), encoding="utf-8")
        logger.info("Baseline updated: %s", bl_path)

    return report


def format_report(report: AuditReport) -> str:
    """Format the AuditReport as Markdown."""
    lines = [
        f"# RAG Quality Audit — {report.run_id}",
        "",
        f"Timestamp: {report.timestamp}",
        f"Total queries: {report.total_queries}",
        f"Overall recall: {report.overall_recall:.2%}",
        f"Avg top-1 score: {report.avg_score:.4f}",
        f"Avg latency: {report.avg_latency_ms:.0f} ms",
        "",
    ]

    if report.alerts:
        lines.append("## Alerts")
        for a in report.alerts:
            lines.append(f"- {a}")
        lines.append("")

    lines.append("## Per-Subset Metrics")
    lines.append("| Subset | Queries | Hits | Recall | Avg Score | Avg Latency |")
    lines.append("|--------|---------|------|--------|-----------|-------------|")
    for subset_name, m in sorted(report.per_subset.items()):
        lines.append(
            f"| {subset_name} | {m.n_queries} | {m.n_hits} | {m.recall:.2%} | "
            f"{m.avg_score:.4f} | {m.avg_latency_ms:.0f} ms |"
        )
    lines.append("")

    lines.append("## Per-Query Detail")
    for r in report.per_query:
        status = "HIT" if r.is_hit else "MISS"
        lines.append(
            f"- [{status}] `{r.query_id}` (rank={r.found_at_rank}, "
            f"score={r.top_score:.3f}, {r.latency_ms}ms): \"{r.query[:80]}\""
        )

    return "\n".join(lines)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="rag_auditor",
        description="Audit RAG retrieval quality against curated ground truth",
    )
    parser.add_argument(
        "--ground-truth", type=Path, default=None,
        help="Path to ground truth YAML (default: agent_sdk/eval_sets/rag_ground_truth.yaml)",
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="Run only the first 5 queries",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s  %(message)s",
    )

    report = run_audit(
        ground_truth_path=args.ground_truth,
        quick=args.quick,
    )

    print(
        f"\nAudit {report.run_id}: {report.total_queries} queries, "
        f"recall={report.overall_recall:.2%}, alerts={len(report.alerts)}"
    )
    sys.exit(1 if report.alerts else 0)


if __name__ == "__main__":
    main()
