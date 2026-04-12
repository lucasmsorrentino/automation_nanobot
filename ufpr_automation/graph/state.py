"""State definition for the LangGraph email processing pipeline."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from ufpr_automation.core.models import EmailClassification, EmailData


def _merge_dict(a: dict, b: dict) -> dict:
    """Reducer: merge two dicts by union.

    Used by LangGraph to combine partial state updates emitted by parallel
    Fleet sub-agents (via ``Send``). Without a reducer, concurrent branches
    would last-write-wins and silently lose data.
    """
    if not a:
        return b
    if not b:
        return a
    return {**a, **b}


class EmailState(TypedDict, total=False):
    """State that flows through the LangGraph pipeline.

    Fields populated by parallel Fleet sub-agents use ``Annotated[..., reducer]``
    so LangGraph merges concurrent branch outputs instead of last-write-wins.
    """

    # Input
    channel: str  # "gmail" or "owa"
    limit: int  # optional cap on how many unread emails to fetch (None/absent = default)

    # Perceber output
    emails: list[EmailData]

    # Tier 0 (Hybrid Memory): stable_ids of emails resolved by the playbook
    # *before* RAG/LLM. Set by tier0_lookup; consulted by rag_retrieve and
    # classificar so they can short-circuit and skip those emails.
    tier0_hits: list[str]

    # Tier 0 near-miss scores — stable_id -> best semantic similarity even
    # when below the routing threshold. Used by the AFlow skip_rag_high_tier0
    # topology to skip RAG retrieval for emails that came close to a match.
    tier0_near_miss_scores: Annotated[dict[str, float], _merge_dict]

    # RAG output (email stable_id -> formatted context: vector + graph + reflexion)
    # Reduced — populated by Fleet sub-agents in parallel.
    rag_contexts: Annotated[dict[str, str], _merge_dict]

    # Pensar output (email stable_id -> classification)
    # Reduced — populated by Fleet sub-agents in parallel.
    classifications: Annotated[dict[str, EmailClassification], _merge_dict]

    # Routing decisions (still set by `rotear` after fan-in)
    auto_draft: list[str]       # stable_ids for auto-draft (high confidence)
    human_review: list[str]     # stable_ids for human review (medium confidence)
    manual_escalation: list[str]  # stable_ids for manual handling (low confidence)

    # SEI/SIGA context (email stable_id -> consultation data)
    # Reduced — populated by Fleet sub-agents in parallel.
    sei_contexts: Annotated[dict[str, Any], _merge_dict]
    siga_contexts: Annotated[dict[str, Any], _merge_dict]

    # Feedback output
    feedback_recorded: int      # number of classifications recorded in FeedbackStore

    # Procedure learning
    procedures_logged: int

    # Agir Estágios output (SEI operations performed in dry-run/live mode)
    sei_operations: list[dict]  # list of {stable_id, op, success, ...} per SEI action

    # Agir output
    drafts_saved: list[str]     # stable_ids of successfully saved drafts

    # Error tracking — list concatenation reducer so sub-agents may append.
    errors: Annotated[list[dict], operator.add]
