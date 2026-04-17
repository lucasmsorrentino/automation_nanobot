"""AFlow — minimum viable topology evaluator for the UFPR pipeline.

This is NOT a neural topology search. It is a hand-authored variant
registry plus an offline evaluator that scores each variant against a
held-out set of feedback examples and picks the best.
"""

from ufpr_automation.aflow.topologies import (
    TOPOLOGY_NAMES,
    get_topology,
    list_topologies,
)

__all__ = ["get_topology", "list_topologies", "TOPOLOGY_NAMES"]
