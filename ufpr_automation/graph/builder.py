"""Build the LangGraph StateGraph for the UFPR email pipeline.

Usage:
    from ufpr_automation.graph.builder import build_graph
    graph = build_graph(channel="gmail")
    result = graph.invoke({"channel": "gmail"})
"""

from __future__ import annotations

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


def _has_emails(state: EmailState) -> str:
    """Route based on whether emails were found."""
    return "tier0_lookup" if state.get("emails") else "end"


def _needs_tier1(state: EmailState) -> str:
    """Skip RAG entirely if every email was resolved by the Tier 0 playbook."""
    emails = state.get("emails", [])
    tier0_hits = set(state.get("tier0_hits", []))
    if emails and len(tier0_hits) >= len(emails):
        return "rotear"
    return "rag_retrieve"


def _needs_sei_siga(state: EmailState) -> str:
    """Route to SEI/SIGA consultation if any email is classified as Estagios."""
    classifications = state.get("classifications", {})
    for cls in classifications.values():
        if cls.categoria == "Estágios":
            return "consultar_sei"
    return "registrar_feedback"


def build_graph(channel: str = "gmail", checkpointer=None) -> StateGraph:
    """Build and compile the email processing StateGraph.

    Args:
        channel: "gmail" or "owa" -- selects the perceber node.
        checkpointer: Optional LangGraph checkpointer for persistence.

    Returns:
        Compiled StateGraph ready to invoke.
    """
    graph = StateGraph(EmailState)

    # Add nodes
    if channel == "gmail":
        graph.add_node("perceber", perceber_gmail)
        graph.add_node("agir", agir_gmail)
    else:
        graph.add_node("perceber", perceber_owa)
        graph.add_node("agir", agir_gmail)  # fallback to gmail drafts even with OWA input

    graph.add_node("tier0_lookup", tier0_lookup)
    graph.add_node("rag_retrieve", rag_retrieve)
    graph.add_node("classificar", classificar)
    graph.add_node("rotear", rotear)
    graph.add_node("consultar_sei", consultar_sei)
    graph.add_node("consultar_siga", consultar_siga)
    graph.add_node("registrar_feedback", registrar_feedback)
    graph.add_node("registrar_procedimento", registrar_procedimento)

    # Define edges — Tier 0 (playbook) runs first; only the residual Tier 1
    # set goes through RAG + classificar.
    graph.set_entry_point("perceber")
    graph.add_conditional_edges(
        "perceber", _has_emails, {"tier0_lookup": "tier0_lookup", "end": END}
    )
    graph.add_conditional_edges(
        "tier0_lookup",
        _needs_tier1,
        {"rag_retrieve": "rag_retrieve", "rotear": "rotear"},
    )
    graph.add_edge("rag_retrieve", "classificar")
    graph.add_edge("classificar", "rotear")

    # After routing: if any email is Estagios, consult SEI/SIGA before acting
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
