"""LangGraph Fleet — parallel per-email Tier 1 sub-agents.

Each Tier 1 email gets dispatched as a :class:`langgraph.types.Send` to
:func:`process_one_email`, which runs the full Tier 1 pipeline for that
single email (RAG retrieve + classify + optional SEI/SIGA consult) and
returns a partial state. LangGraph's reducers (see
:mod:`ufpr_automation.graph.state`) merge the parallel branch outputs
back into the main ``EmailState`` so downstream nodes see a unified view.

Design notes:
    - :func:`dispatch_tier1` is registered as a conditional edge after
      ``tier0_lookup``. When every email was already resolved by Tier 0
      it returns the string ``"rotear"`` (direct routing) instead of a
      fan-out list, so LangGraph skips the Fleet entirely.
    - Error isolation: :func:`process_one_email` wraps the whole sub-agent
      body in try/except and appends any catastrophic failure to
      ``state["errors"]`` via the ``operator.add`` reducer.
    - Heavy imports (retriever, GraphRAG, DSPy) are deferred into
      :func:`process_one_email` so graph compilation stays cheap.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, TypedDict

from langgraph.types import Send

from ufpr_automation.config import settings
from ufpr_automation.core.models import EmailData
from ufpr_automation.graph.state import EmailState

logger = logging.getLogger(__name__)


# Module-level semaphore limiting how many Fleet sub-agents may run the heavy
# RAG + classify body concurrently. Each ``process_one_email`` call acquires a
# slot before doing any work and releases it on return / exception.
#
# Tunable via the ``FLEET_MAX_CONCURRENT_SUBAGENTS`` env var
# (see :mod:`ufpr_automation.config.settings`); default is 2. Raise when the
# host has more RAM/CPU; lower to 1 to serialize the Fleet completely (useful
# for debugging reproducibility).
_SUBAGENT_SEMAPHORE = threading.Semaphore(settings.FLEET_MAX_CONCURRENT_SUBAGENTS)


class SubState(TypedDict, total=False):
    """Per-email state passed to a Fleet sub-agent via :class:`Send`."""

    email: EmailData
    stable_id: str


def dispatch_tier1(state: EmailState) -> list[Send] | str:
    """Conditional edge router after ``tier0_lookup``.

    Returns:
        - ``"rotear"`` if every email was resolved by Tier 0 (no Tier 1
          work needed) — the graph routes directly to ``rotear``.
        - A list of :class:`Send` objects otherwise, one per Tier 1 email,
          each invoking :func:`process_one_email` in parallel.
    """
    emails = state.get("emails", [])
    tier0_hits = set(state.get("tier0_hits", []))
    tier1_emails = [e for e in emails if e.stable_id not in tier0_hits]

    if not tier1_emails:
        logger.info("Fleet: no Tier 1 emails, skipping fan-out")
        return "rotear"

    logger.info("Fleet: dispatching %d Tier 1 sub-agents", len(tier1_emails))
    return [Send("process_one_email", {"email": e, "stable_id": e.stable_id}) for e in tier1_emails]


def process_one_email(sub: SubState) -> dict[str, Any]:
    """Sub-agent — runs the full Tier 1 pipeline for ONE email.

    Steps:
        1. Vector RAG retrieval (``_get_retriever().search_formatted``).
        2. Graph context (``_get_graph_context``).
        3. Reflexion context (``_get_reflexion_context_single``).
        4. Classification via DSPy or LiteLLM (gated by ``_should_use_dspy``).
        5. Conditional SEI/SIGA consultation for ``Estágios`` classifications.

    Returns a partial state dict whose dict fields are merged into the
    parent state by the reducers declared in :mod:`ufpr_automation.graph.state`.

    Errors at each stage are isolated: a failure in RAG does not prevent
    classification, and a catastrophic failure is appended to ``errors``
    (via the ``operator.add`` reducer) instead of propagating.
    """
    email: EmailData = sub["email"]
    stable_id: str = sub["stable_id"]

    # Gate all heavy work (RAG + GraphRAG + Reflexion + LLM classify +
    # SEI/SIGA consults) behind the module-level semaphore so we don't OOM
    # when LangGraph's Send API fans out more sub-agents than the host can
    # afford to run in parallel. Sub-agents beyond the cap block here until
    # a slot frees up.
    queued_wait_start = threading.get_ident()
    with _SUBAGENT_SEMAPHORE:
        logger.info(
            "Fleet[%s] sub-agent started (thread=%s, max_concurrent=%d)",
            stable_id[:8],
            queued_wait_start,
            settings.FLEET_MAX_CONCURRENT_SUBAGENTS,
        )

        # Lazy imports — avoid loading heavy modules during graph build
        from ufpr_automation.graph.nodes import (
            _classify_with_dspy,
            _classify_with_litellm,
            _consult_sei_for_email,
            _consult_siga_for_email,
            _get_graph_context,
            _get_reflexion_context_single,
            _get_retriever,
            _should_use_dspy,
        )

        result: dict[str, Any] = {
            "rag_contexts": {},
            "classifications": {},
            "sei_contexts": {},
            "siga_contexts": {},
            "errors": [],
        }

        try:
            # 1. Vector RAG retrieval
            try:
                retriever = _get_retriever()
            except Exception as e:
                logger.debug("Fleet[%s] RAG retriever unavailable: %s", stable_id[:8], e)
                retriever = None

            rag_text = ""
            if retriever is not None:
                try:
                    rag_text = retriever.search_formatted(
                        f"{email.subject}\n{email.body or email.preview}",
                        top_k=5,
                    )
                    if rag_text == "Nenhum documento relevante encontrado.":
                        rag_text = ""
                except Exception as e:
                    logger.warning("Fleet[%s] RAG retrieval failed: %s", stable_id[:8], e)
                    rag_text = ""

            # 2. Graph context (Neo4j GraphRAG)
            try:
                graph_ctx = _get_graph_context(email)
                if graph_ctx:
                    rag_text = (rag_text + "\n\n" + graph_ctx).strip()
            except Exception as e:
                logger.warning("Fleet[%s] graph context failed: %s", stable_id[:8], e)

            # 3. Reflexion context (past error reflections)
            try:
                refl_ctx = _get_reflexion_context_single(email)
                if refl_ctx:
                    rag_text = (rag_text + "\n\n" + refl_ctx).strip()
            except Exception as e:
                logger.warning("Fleet[%s] reflexion failed: %s", stable_id[:8], e)

            result["rag_contexts"][stable_id] = rag_text

            # 4. Classify (DSPy gated, fallback to LiteLLM)
            rag_contexts = {stable_id: rag_text}
            try:
                use_dspy = _should_use_dspy()
            except Exception as e:
                logger.warning("Fleet[%s] DSPy gate failed: %s", stable_id[:8], e)
                use_dspy = False

            if use_dspy:
                cls_dict = _classify_with_dspy([email], rag_contexts)
            else:
                cls_dict = _classify_with_litellm([email], rag_contexts)

            if stable_id in cls_dict:
                result["classifications"][stable_id] = cls_dict[stable_id]

            # 5. Optional SEI/SIGA consultation (only for Estágios)
            cls = cls_dict.get(stable_id)
            if cls is not None and getattr(cls, "categoria", None) == "Estágios":
                try:
                    sei_data = _consult_sei_for_email(email, cls)
                    if sei_data is not None:
                        result["sei_contexts"][stable_id] = sei_data
                except Exception as e:
                    logger.warning("Fleet[%s] SEI consult failed: %s", stable_id[:8], e)

                try:
                    siga_data = _consult_siga_for_email(email, cls)
                    if siga_data is not None:
                        result["siga_contexts"][stable_id] = siga_data
                except Exception as e:
                    logger.warning("Fleet[%s] SIGA consult failed: %s", stable_id[:8], e)

        except Exception as e:
            logger.error("Fleet[%s] sub-agent failed entirely: %s", stable_id[:8], e)
            result["errors"].append(
                {
                    "stable_id": stable_id,
                    "stage": "fleet_subagent",
                    "error": str(e),
                }
            )

        return result
