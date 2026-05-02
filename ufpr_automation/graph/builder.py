"""Build the LangGraph StateGraph for the UFPR email pipeline.

Usage:
    from ufpr_automation.graph.builder import build_graph
    graph = build_graph(channel="gmail")
    result = graph.invoke({"channel": "gmail"})
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from ufpr_automation.graph.fleet import dispatch_tier1, process_one_email
from ufpr_automation.graph.nodes import (
    agir_estagios,
    agir_gmail,
    capturar_corpus_humano,
    consultar_tier0_sei_siga,
    perceber_gmail,
    perceber_owa,
    prewarm_sessions,
    registrar_feedback,
    registrar_procedimento,
    rotear,
    tier0_lookup,
)
from ufpr_automation.graph.state import EmailState


def _has_emails(state: EmailState) -> str:
    """Route based on whether emails were found."""
    return "tier0_lookup" if state.get("emails") else "end"


def build_graph(channel: str = "gmail", checkpointer=None) -> StateGraph:
    """Build and compile the email processing StateGraph.

    Args:
        channel: "gmail" or "owa" -- selects the perceber node.
        checkpointer: Optional LangGraph checkpointer for persistence.

    Returns:
        Compiled StateGraph ready to invoke.
    """
    # AFlow topology dispatch — when AFLOW_TOPOLOGY is set to anything other
    # than "fleet" (the default Fleet-based topology built below), delegate
    # to the AFlow variant registry. The "fleet" guard is critical to avoid
    # a circular import/recursion: aflow.topologies.topology_fleet calls
    # build_graph() again, so we must short-circuit here for that case.
    from ufpr_automation.config import settings as _settings

    topology_override = _settings.AFLOW_TOPOLOGY
    if topology_override and topology_override != "fleet":
        try:
            from ufpr_automation.aflow.topologies import get_topology

            factory = get_topology(topology_override)
            if factory.__name__ != "topology_fleet":
                return factory(channel=channel, checkpointer=checkpointer)
        except (KeyError, ImportError) as e:
            import logging as _logging

            _logging.getLogger(__name__).warning(
                "AFLOW_TOPOLOGY=%s invalid (%s); using default fleet topology",
                topology_override,
                e,
            )

    graph = StateGraph(EmailState)

    # Add nodes
    if channel == "gmail":
        graph.add_node("perceber", perceber_gmail)
        graph.add_node("agir", agir_gmail)
    else:
        graph.add_node("perceber", perceber_owa)
        graph.add_node("agir", agir_gmail)  # fallback to gmail drafts even with OWA input

    graph.add_node("tier0_lookup", tier0_lookup)

    # Optional sync node between tier0_lookup and the Fleet fan-out that
    # warms SEI/SIGA sessions when needed, avoiding concurrent login races
    # across parallel sub-agents. Gated by PREWARM_SESSIONS_ENABLED env var;
    # when disabled, the node is a cheap no-op.
    graph.add_node("prewarm_sessions", prewarm_sessions)

    # Consult SEI + SIGA for Tier 0 HITS with non-trivial sei_action
    # (aditivo / conclusão / rescisão / new TCE). Without this, agir_estagios
    # runs checkers with empty sei_context / siga_context and soft-blocks
    # defensively, sending nonsensical "please provide data you already sent"
    # replies to students. Tier 1 emails continue to consult inside
    # process_one_email. See bug note in nodes.py:consultar_tier0_sei_siga.
    graph.add_node("consultar_tier0_sei_siga", consultar_tier0_sei_siga)

    # Fleet sub-agent — runs the full Tier 1 pipeline (rag_retrieve +
    # classificar + optional SEI/SIGA consult) for ONE email. Invoked in
    # parallel via Send fan-out from `dispatch_tier1`.
    graph.add_node("process_one_email", process_one_email)

    graph.add_node("rotear", rotear)
    graph.add_node("registrar_feedback", registrar_feedback)
    graph.add_node("agir_estagios", agir_estagios)
    graph.add_node("capturar_corpus_humano", capturar_corpus_humano)
    graph.add_node("registrar_procedimento", registrar_procedimento)

    # Define edges — Tier 0 (playbook) runs first; only the residual Tier 1
    # set goes through the Fleet fan-out. `dispatch_tier1` returns either
    # "rotear" (all resolved by Tier 0) or a list of Send objects.
    graph.set_entry_point("perceber")
    graph.add_conditional_edges(
        "perceber", _has_emails, {"tier0_lookup": "tier0_lookup", "end": END}
    )
    graph.add_edge("tier0_lookup", "prewarm_sessions")
    graph.add_edge("prewarm_sessions", "consultar_tier0_sei_siga")
    graph.add_conditional_edges(
        "consultar_tier0_sei_siga",
        dispatch_tier1,
        ["process_one_email", "rotear"],
    )
    graph.add_edge("process_one_email", "rotear")

    # SEI/SIGA consultation happens inside process_one_email, so we go
    # directly from rotear to registrar_feedback.
    graph.add_edge("rotear", "registrar_feedback")

    graph.add_edge("registrar_feedback", "agir_estagios")
    graph.add_edge("agir_estagios", "agir")
    graph.add_edge("agir", "capturar_corpus_humano")
    graph.add_edge("capturar_corpus_humano", "registrar_procedimento")
    graph.add_edge("registrar_procedimento", END)

    return graph.compile(checkpointer=checkpointer)


def build_graph_with_checkpointer(channel: str = "gmail"):
    """Build graph with SQLite checkpointing for fault tolerance.

    Returns:
        Tuple of (compiled_graph, checkpointer).
    """
    from langgraph.checkpoint.sqlite import SqliteSaver

    from ufpr_automation.config import settings

    db_path = settings.PACKAGE_ROOT / "graph_data" / "checkpoints.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    checkpointer = SqliteSaver.from_conn_string(str(db_path))
    graph = build_graph(channel=channel, checkpointer=checkpointer)
    return graph, checkpointer
