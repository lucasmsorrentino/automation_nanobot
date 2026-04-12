"""Hand-authored LangGraph topology variants.

Each topology factory returns a compiled StateGraph. They share the
perceber -> tier0_lookup -> ... -> registrar_procedimento backbone but differ
in the Tier 1 processing strategy and post-classification routing.

Variants:
- baseline: Linear pre-Fleet pipeline (rag_retrieve -> classificar -> rotear
  -> consultar_sei -> consultar_siga -> registrar_feedback).
- fleet: Wave 2 parallel fan-out (process_one_email per Tier 1 email).
- skip_rag_high_tier0: Like baseline but skips rag_retrieve when the
  Tier 0 semantic score is above 0.85 (used for ablation).
- no_self_refine: Like fleet but disables Self-Refine inside classify.
- fleet_no_siga: Like fleet but skips SIGA consultation entirely (used
  to measure SIGA's latency contribution).

All topologies must accept a ``channel`` arg and an optional ``checkpointer``
for parity with the existing ``build_graph`` signature.
"""
from __future__ import annotations

from typing import Callable

TOPOLOGY_NAMES = (
    "baseline",
    "fleet",
    "skip_rag_high_tier0",
    "no_self_refine",
    "fleet_no_siga",
)


def topology_baseline(channel: str = "gmail", checkpointer=None):
    """Linear pre-Fleet topology — sequential rag_retrieve -> classificar."""
    from langgraph.graph import END, StateGraph

    from ufpr_automation.graph.nodes import (
        agir_gmail,
        classificar,
        consultar_sei,
        consultar_siga,
        perceber_gmail,
        perceber_owa,
        rag_retrieve,
        registrar_feedback,
        registrar_procedimento,
        rotear,
        tier0_lookup,
    )
    from ufpr_automation.graph.state import EmailState

    graph = StateGraph(EmailState)
    if channel == "gmail":
        graph.add_node("perceber", perceber_gmail)
    else:
        graph.add_node("perceber", perceber_owa)
    graph.add_node("agir", agir_gmail)
    graph.add_node("tier0_lookup", tier0_lookup)
    graph.add_node("rag_retrieve", rag_retrieve)
    graph.add_node("classificar", classificar)
    graph.add_node("rotear", rotear)
    graph.add_node("consultar_sei", consultar_sei)
    graph.add_node("consultar_siga", consultar_siga)
    graph.add_node("registrar_feedback", registrar_feedback)
    graph.add_node("registrar_procedimento", registrar_procedimento)

    def _has_emails(state):
        return "tier0_lookup" if state.get("emails") else "end"

    def _needs_tier1(state):
        emails = state.get("emails", [])
        tier0_hits = set(state.get("tier0_hits", []))
        if emails and len(tier0_hits) >= len(emails):
            return "rotear"
        return "rag_retrieve"

    def _needs_sei_siga(state):
        for cls in state.get("classifications", {}).values():
            if getattr(cls, "categoria", None) == "Estágios":
                return "consultar_sei"
        return "registrar_feedback"

    graph.set_entry_point("perceber")
    graph.add_conditional_edges(
        "perceber",
        _has_emails,
        {"tier0_lookup": "tier0_lookup", "end": END},
    )
    graph.add_conditional_edges(
        "tier0_lookup",
        _needs_tier1,
        {"rag_retrieve": "rag_retrieve", "rotear": "rotear"},
    )
    graph.add_edge("rag_retrieve", "classificar")
    graph.add_edge("classificar", "rotear")
    graph.add_conditional_edges(
        "rotear",
        _needs_sei_siga,
        {
            "consultar_sei": "consultar_sei",
            "registrar_feedback": "registrar_feedback",
        },
    )
    graph.add_edge("consultar_sei", "consultar_siga")
    graph.add_edge("consultar_siga", "registrar_feedback")
    graph.add_edge("registrar_feedback", "agir")
    graph.add_edge("agir", "registrar_procedimento")
    graph.add_edge("registrar_procedimento", END)

    return graph.compile(checkpointer=checkpointer)


def topology_fleet(channel: str = "gmail", checkpointer=None):
    """Wave 2 Fleet topology — parallel process_one_email per Tier 1 email.

    Delegates to the existing build_graph in builder.py, which is now
    Fleet-based after WS3.
    """
    # Lazy import to avoid circular dep with builder.py's own dispatcher
    from ufpr_automation.graph.builder import build_graph

    return build_graph(channel=channel, checkpointer=checkpointer)


def topology_skip_rag_high_tier0(channel: str = "gmail", checkpointer=None):
    """Baseline variant that skips rag_retrieve for emails with Tier 0 near-miss > threshold.

    tier0_lookup now emits per-email best semantic scores (even when below
    the routing threshold) into ``state["tier0_near_miss_scores"]``. When
    ``AFLOW_TOPOLOGY=skip_rag_high_tier0`` is set, ``rag_retrieve`` consults
    those scores and skips RAG retrieval for any email whose near-miss score
    exceeded ``SKIP_RAG_NEAR_MISS_THRESHOLD`` (default 0.80). Ablation tests
    how much incremental accuracy the RAG step provides for emails that
    were already "almost" a Tier 0 hit.
    """
    return topology_baseline(channel=channel, checkpointer=checkpointer)


def topology_no_self_refine(channel: str = "gmail", checkpointer=None):
    """Fleet variant that disables Self-Refine in classify (faster, less accurate).

    The ``AFLOW_TOPOLOGY=no_self_refine`` env var is checked by
    ``_classify_with_litellm`` in ``nodes.py`` which skips the
    ``self_refine_async`` call, producing a single-pass classification.
    """
    return topology_fleet(channel=channel, checkpointer=checkpointer)


def topology_fleet_no_siga(channel: str = "gmail", checkpointer=None):
    """Fleet variant that skips SIGA consultation. Measures SIGA latency cost.

    The ``AFLOW_TOPOLOGY=fleet_no_siga`` env var is checked by
    ``process_one_email`` in ``fleet.py`` which skips the SIGA consult step.
    """
    return topology_fleet(channel=channel, checkpointer=checkpointer)


_TOPOLOGY_FACTORIES: dict[str, Callable] = {
    "baseline": topology_baseline,
    "fleet": topology_fleet,
    "skip_rag_high_tier0": topology_skip_rag_high_tier0,
    "no_self_refine": topology_no_self_refine,
    "fleet_no_siga": topology_fleet_no_siga,
}


def get_topology(name: str) -> Callable:
    """Return the factory function for the named topology.

    Raises:
        KeyError: if ``name`` is not a registered topology.
    """
    name = name.lower()
    if name not in _TOPOLOGY_FACTORIES:
        raise KeyError(
            f"Unknown topology '{name}'. Valid: {sorted(_TOPOLOGY_FACTORIES)}"
        )
    return _TOPOLOGY_FACTORIES[name]


def list_topologies() -> list[str]:
    """Return the list of registered topology names."""
    return list(_TOPOLOGY_FACTORIES.keys())
