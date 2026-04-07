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
    perceber_gmail,
    perceber_owa,
    rag_retrieve,
    registrar_feedback,
    rotear,
)
from ufpr_automation.graph.state import EmailState


def _has_emails(state: EmailState) -> str:
    """Route based on whether emails were found."""
    return "rag_retrieve" if state.get("emails") else "end"


def build_graph(channel: str = "gmail", checkpointer=None) -> StateGraph:
    """Build and compile the email processing StateGraph.

    Args:
        channel: "gmail" or "owa" — selects the perceber node.
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

    graph.add_node("rag_retrieve", rag_retrieve)
    graph.add_node("classificar", classificar)
    graph.add_node("rotear", rotear)
    graph.add_node("registrar_feedback", registrar_feedback)

    # Define edges
    graph.set_entry_point("perceber")
    graph.add_conditional_edges(
        "perceber", _has_emails, {"rag_retrieve": "rag_retrieve", "end": END}
    )
    graph.add_edge("rag_retrieve", "classificar")
    graph.add_edge("classificar", "rotear")
    graph.add_edge("rotear", "registrar_feedback")
    graph.add_edge("registrar_feedback", "agir")
    graph.add_edge("agir", END)

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
