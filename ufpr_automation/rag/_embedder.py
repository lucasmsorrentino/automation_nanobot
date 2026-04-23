"""Process-wide shared ``SentenceTransformer`` singleton.

Why this exists
---------------
``intfloat/multilingual-e5-large`` is ~2 GB of model weights once loaded.
The LangGraph Fleet (Send API fan-out in :mod:`ufpr_automation.graph.fleet`)
dispatches ONE sub-agent per Tier 1 email and each sub-agent used to build
its own :class:`Retriever`, :class:`ReflexionMemory`, and optionally
:class:`RaptorRetriever` — each of which instantiated its *own*
``SentenceTransformer`` in the thread running the sub-agent. With N=3
concurrent sub-agents we saw 3 concurrent "Loading weights" progress bars
and ~6 GB of RAM allocated; with N=5 the host OOM'd (see
``ufpr_automation/TASKS.md`` "Fleet OOM").

``SentenceTransformer.encode()`` is thread-safe for inference, so ONE
shared instance across all threads is correct — the fan-out should use a
single set of model weights.

TO REVERT (once the host has enough RAM for per-thread instances):
delete this module and restore direct ``SentenceTransformer(name)`` calls
in the ``__init__`` / ``_ensure_loaded`` methods of
:class:`ufpr_automation.rag.retriever.Retriever`,
:class:`ufpr_automation.feedback.reflexion.ReflexionMemory`, and
:class:`ufpr_automation.rag.raptor.RaptorRetriever`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import guard for type hints only
    from sentence_transformers import SentenceTransformer


@lru_cache(maxsize=None)
def get_shared_embedder(
    model_name: str = "intfloat/multilingual-e5-large",
) -> "SentenceTransformer":
    """Return the process-wide shared ``SentenceTransformer`` for ``model_name``.

    The instance is cached with :func:`functools.lru_cache`, so every caller
    (regardless of thread) receives the same object. ``SentenceTransformer``
    inference is thread-safe, which lets the LangGraph Fleet sub-agents run
    ``encode()`` concurrently against a single model.

    Args:
        model_name: Sentence-transformers model id. Distinct model names get
            distinct cached instances (each paying its own load cost once).

    Returns:
        A lazily-loaded, process-wide :class:`SentenceTransformer` instance.
    """
    # Import here to keep this module import-time cheap — loading
    # ``sentence_transformers`` eagerly would defeat the lazy behaviour the
    # Retriever/ReflexionMemory classes carefully preserved.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)
