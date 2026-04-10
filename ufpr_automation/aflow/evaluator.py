"""Offline evaluator for AFlow topology variants.

Runs each topology against a held-out set of feedback examples and scores
it via composite_metric (or whatever metric the caller specifies). Returns
an EvalResult with accuracy, latency stats, cost estimate, and error count.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class EvalResult:
    """Result of evaluating one topology against the eval set."""

    topology: str
    n_examples: int
    accuracy: float = 0.0
    latency_mean_ms: float = 0.0
    latency_p95_ms: float = 0.0
    cost_estimate: float = 0.0
    errors: int = 0
    metric: str = "composite"
    detail: dict[str, Any] = field(default_factory=dict)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    k = int(round((pct / 100) * (len(sorted_v) - 1)))
    return sorted_v[max(0, min(k, len(sorted_v) - 1))]


def evaluate(
    topology_name: str,
    examples: list[dict],
    metric_fn: Callable | None = None,
    metric_name: str = "composite",
    invoke_fn: Callable | None = None,
) -> EvalResult:
    """Evaluate one topology against a list of examples.

    Args:
        topology_name: name in TOPOLOGY_NAMES.
        examples: list of dicts with at least ``email`` and ``expected_categoria``.
        metric_fn: callable (predicted, expected) -> float in [0, 1]. If None,
            uses a simple 1.0/0.0 category match.
        metric_name: name to record in the result.
        invoke_fn: callable (compiled_graph, example) -> (predicted, est_cost).
            If None, a stub-friendly default is used that does NOT actually
            call the LLM (for unit tests). The CLI provides a real one.

    Returns:
        EvalResult with metrics filled in.
    """
    if metric_fn is None:
        try:
            # Imported to validate the metrics module is reachable; the actual
            # DSPy metric has an (example, pred, trace) signature that's not a
            # fit for our simpler (predicted, expected) interface, so we still
            # use a plain equality check here.
            from ufpr_automation.dspy_modules.metrics import category_match  # noqa: F401

            metric_fn = lambda pred, exp: 1.0 if pred == exp else 0.0  # noqa: E731
            metric_name = "category_match"
        except ImportError:
            metric_fn = lambda pred, exp: 1.0 if pred == exp else 0.0  # noqa: E731

    if invoke_fn is None:
        invoke_fn = _stub_invoke

    from ufpr_automation.aflow.topologies import get_topology

    n = len(examples)
    if n == 0:
        return EvalResult(topology=topology_name, n_examples=0, metric=metric_name)

    factory = get_topology(topology_name)
    try:
        graph = factory()
    except Exception as e:
        logger.error("Failed to build topology %s: %s", topology_name, e)
        return EvalResult(
            topology=topology_name,
            n_examples=n,
            errors=n,
            metric=metric_name,
            detail={"build_error": str(e)},
        )

    latencies: list[float] = []
    correct = 0
    errors = 0
    cost_total = 0.0

    for i, ex in enumerate(examples):
        t0 = time.time()
        try:
            predicted, est_cost = invoke_fn(graph, ex)
            latencies.append((time.time() - t0) * 1000)
            cost_total += est_cost
            expected = ex.get("expected_categoria", "")
            score = metric_fn(predicted, expected)
            if score >= 0.5:
                correct += 1
        except Exception as e:
            latencies.append((time.time() - t0) * 1000)
            errors += 1
            logger.warning("Eval %s example %d failed: %s", topology_name, i, e)

    return EvalResult(
        topology=topology_name,
        n_examples=n,
        accuracy=correct / n if n > 0 else 0.0,
        latency_mean_ms=sum(latencies) / len(latencies) if latencies else 0.0,
        latency_p95_ms=_percentile(latencies, 95.0),
        cost_estimate=cost_total,
        errors=errors,
        metric=metric_name,
    )


def _stub_invoke(graph, example: dict) -> tuple[str, float]:
    """Default invoke_fn for unit tests — returns the example's expected category.

    This makes the evaluator trivially testable without spinning up the LLM.
    The CLI provides a real ``invoke_fn`` that actually runs the graph.
    """
    return example.get("expected_categoria", "Outros"), 0.0
