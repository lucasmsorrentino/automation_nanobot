"""Pick the best topology by running each one through the evaluator."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ufpr_automation.aflow.evaluator import EvalResult, evaluate
from ufpr_automation.aflow.topologies import list_topologies

logger = logging.getLogger(__name__)


def _load_eval_examples(limit: int = 20) -> list[dict]:
    """Load evaluation examples from feedback store, falling back to synthetic."""
    examples: list[dict] = []
    try:
        from ufpr_automation.feedback.store import FeedbackStore

        store = FeedbackStore()
        # FeedbackStore exposes list_all(); iterate records and coerce to
        # the minimal dict shape this module needs.
        for record in store.list_all():
            examples.append(
                {
                    "email": {
                        "subject": getattr(record, "email_subject", ""),
                        "sender": getattr(record, "email_sender", ""),
                    },
                    "expected_categoria": (
                        getattr(record.corrected, "categoria", None)
                        or getattr(record.original, "categoria", "")
                    ),
                }
            )
            if len(examples) >= limit:
                break
    except Exception as e:
        logger.info("Falling back to synthetic examples: %s", e)

    if not examples:
        # Cold start — synthetic examples
        try:
            from ufpr_automation.dspy_modules.optimize import _load_feedback_examples

            for ex in _load_feedback_examples():
                examples.append(
                    {
                        "email": {
                            "subject": getattr(ex, "email_subject", ""),
                            "body": getattr(ex, "email_body", ""),
                            "sender": getattr(ex, "email_sender", ""),
                        },
                        "expected_categoria": getattr(ex, "expected_categoria", "Outros"),
                    }
                )
                if len(examples) >= limit:
                    break
        except Exception as e:
            logger.warning("Could not load synthetic examples: %s", e)

    return examples[:limit]


def pick_best_topology(
    topologies: list[str] | None = None,
    examples: list[dict] | None = None,
    invoke_fn: Callable | None = None,
    limit: int = 20,
    report_dir: Path | None = None,
) -> tuple[str, list[EvalResult]]:
    """Run all topologies and pick the one with the highest accuracy.

    Returns ``(best_topology_name, all_results)``. Writes a JSON report to
    ``report_dir / {timestamp}.json`` if ``report_dir`` is provided.
    """
    if topologies is None:
        topologies = list_topologies()
    if examples is None:
        examples = _load_eval_examples(limit=limit)

    results: list[EvalResult] = []
    for name in topologies:
        logger.info(
            "AFlow: evaluating topology %s on %d examples", name, len(examples)
        )
        result = evaluate(name, examples, invoke_fn=invoke_fn)
        results.append(result)

    # Tie-break: highest accuracy, then lowest latency, then lowest errors
    best = max(
        results,
        key=lambda r: (r.accuracy, -r.latency_mean_ms, -r.errors),
    )

    if report_dir is not None:
        report_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        report_path = report_dir / f"{ts}.json"
        report = {
            "timestamp": ts,
            "topologies_evaluated": topologies,
            "n_examples": len(examples),
            "best": best.topology,
            "results": [
                {
                    "topology": r.topology,
                    "accuracy": r.accuracy,
                    "latency_mean_ms": r.latency_mean_ms,
                    "latency_p95_ms": r.latency_p95_ms,
                    "cost_estimate": r.cost_estimate,
                    "errors": r.errors,
                    "metric": r.metric,
                }
                for r in results
            ],
        }
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        logger.info("AFlow report written to %s", report_path)

    return best.topology, results
