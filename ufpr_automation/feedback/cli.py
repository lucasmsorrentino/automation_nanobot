"""CLI for reviewing and recording human feedback on email classifications.

Usage:
    python -m ufpr_automation.feedback review    # interactive review
    python -m ufpr_automation.feedback stats      # show feedback statistics
    python -m ufpr_automation.feedback export      # export as JSON for DSPy
"""

from __future__ import annotations

import argparse
import json
import sys

from ufpr_automation.feedback.store import FeedbackStore


def cmd_stats(store: FeedbackStore) -> None:
    """Print feedback statistics."""
    records = store.list_all()
    if not records:
        print("Nenhum registro de feedback encontrado.")
        print(f"Arquivo: {store.path}")
        return

    print(f"Total de correções: {len(records)}")
    print(f"Arquivo: {store.path}")
    print()

    # Category distribution
    cat_changes: dict[str, int] = {}
    for r in records:
        key = f"{r.original.categoria} → {r.corrected.categoria}"
        cat_changes[key] = cat_changes.get(key, 0) + 1

    print("Mudanças de categoria:")
    for change, count in sorted(cat_changes.items(), key=lambda x: -x[1]):
        print(f"  {change}: {count}")

    # Time range
    timestamps = [r.timestamp for r in records]
    print(f"\nPeríodo: {min(timestamps)[:10]} a {max(timestamps)[:10]}")


def cmd_export(store: FeedbackStore) -> None:
    """Export feedback records as JSON (for DSPy training data)."""
    records = store.list_all()
    if not records:
        print("Nenhum registro de feedback para exportar.", file=sys.stderr)
        sys.exit(1)

    data = [r.model_dump() for r in records]
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Feedback CLI — UFPR Automation")
    parser.add_argument(
        "command",
        choices=["stats", "export"],
        help="Command to run: stats | export",
    )
    args = parser.parse_args()

    store = FeedbackStore()

    if args.command == "stats":
        cmd_stats(store)
    elif args.command == "export":
        cmd_export(store)


if __name__ == "__main__":
    main()
