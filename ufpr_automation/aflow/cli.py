"""CLI for AFlow topology evaluator.

Usage:
    python -m ufpr_automation.aflow.cli --topologies all --limit 20
    python -m ufpr_automation.aflow.cli --topologies baseline,fleet --limit 10
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from ufpr_automation.aflow.optimizer import pick_best_topology
from ufpr_automation.aflow.topologies import list_topologies

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AFlow topology evaluator")
    parser.add_argument(
        "--topologies",
        default="all",
        help="Comma-separated topology names or 'all' (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max number of eval examples (default: 20)",
    )
    parser.add_argument(
        "--report-dir",
        default=None,
        help="Directory to write the JSON report (default: ufpr_automation/aflow/reports)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    if args.topologies == "all":
        topologies = list_topologies()
    else:
        topologies = [t.strip() for t in args.topologies.split(",") if t.strip()]

    if args.report_dir is None:
        report_dir = Path(__file__).parent / "reports"
    else:
        report_dir = Path(args.report_dir)

    best, results = pick_best_topology(
        topologies=topologies,
        limit=args.limit,
        report_dir=report_dir,
    )

    print(f"\nAFlow evaluation complete: {len(results)} topologies tested")
    print(f"{'Topology':<30} {'Accuracy':>10} {'Latency':>12} {'Errors':>8}")
    print("-" * 62)
    for r in results:
        marker = " *" if r.topology == best else ""
        print(
            f"{r.topology:<30} {r.accuracy:>10.2%} {r.latency_mean_ms:>10.1f}ms "
            f"{r.errors:>8}{marker}"
        )
    print(f"\nBest topology: {best}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
