"""State definition for the LangGraph email processing pipeline."""

from __future__ import annotations

from typing import Any, TypedDict

from ufpr_automation.core.models import EmailClassification, EmailData


class EmailState(TypedDict, total=False):
    """State that flows through the LangGraph pipeline.

    Each key is updated by the node that produces it.
    """

    # Input
    channel: str  # "gmail" or "owa"

    # Perceber output
    emails: list[EmailData]

    # RAG output (email stable_id -> formatted context)
    rag_contexts: dict[str, str]

    # Pensar output (email stable_id -> classification)
    classifications: dict[str, EmailClassification]

    # Routing decisions
    auto_draft: list[str]       # stable_ids for auto-draft (high confidence)
    human_review: list[str]     # stable_ids for human review (medium confidence)
    manual_escalation: list[str]  # stable_ids for manual handling (low confidence)

    # SEI/SIGA context (email stable_id -> consultation data)
    sei_contexts: dict[str, Any]
    siga_contexts: dict[str, Any]

    # Feedback output
    feedback_recorded: int      # number of classifications recorded in FeedbackStore

    # Procedure learning
    procedures_logged: int

    # Agir output
    drafts_saved: list[str]     # stable_ids of successfully saved drafts

    # Error tracking
    errors: list[dict]
