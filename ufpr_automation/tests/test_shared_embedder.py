"""Tests for the shared SentenceTransformer singleton and the Fleet
sub-agent concurrency semaphore.

Covers:
    - ``rag._embedder.get_shared_embedder`` returns the SAME object on
      repeated calls with the same model_name (identity), so multiple
      callers (Retriever, ReflexionMemory, RaptorRetriever) share one
      ~2 GB set of model weights process-wide.
    - ``graph.fleet.process_one_email`` respects ``_SUBAGENT_SEMAPHORE``
      — when the semaphore is narrowed to 1, two concurrent sub-agent
      invocations serialize instead of running in parallel.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

from ufpr_automation.core.models import EmailClassification, EmailData


# ---------------------------------------------------------------------------
# Shared SentenceTransformer singleton
# ---------------------------------------------------------------------------


class TestSharedEmbedder:
    """Validate ``get_shared_embedder`` returns a process-wide singleton."""

    def test_returns_same_object_twice(self):
        """Same ``model_name`` → identical object (lru_cache behaviour).

        The real SentenceTransformer load is ~2 GB and slow, so we patch
        it with a lightweight stand-in. The identity check proves the
        cache hit path — the inner constructor is only called once.
        """
        from ufpr_automation.rag import _embedder

        # Bust the cache so this test is order-independent.
        _embedder.get_shared_embedder.cache_clear()

        class _FakeST:
            def __init__(self, name):
                self.name = name

        call_count = {"n": 0}

        def _fake_ctor(name):
            call_count["n"] += 1
            return _FakeST(name)

        with patch("sentence_transformers.SentenceTransformer", side_effect=_fake_ctor):
            first = _embedder.get_shared_embedder("unit-test/model-A")
            second = _embedder.get_shared_embedder("unit-test/model-A")

        assert first is second, "get_shared_embedder must return the same cached object"
        assert call_count["n"] == 1, "SentenceTransformer must only be constructed once per name"

        # Clean up the cache so we don't leak the fake into later tests.
        _embedder.get_shared_embedder.cache_clear()

    def test_distinct_names_get_distinct_instances(self):
        """Different model names still pay their own one-time load cost."""
        from ufpr_automation.rag import _embedder

        _embedder.get_shared_embedder.cache_clear()

        class _FakeST:
            def __init__(self, name):
                self.name = name

        with patch("sentence_transformers.SentenceTransformer", side_effect=_FakeST):
            a = _embedder.get_shared_embedder("unit-test/model-A")
            b = _embedder.get_shared_embedder("unit-test/model-B")

        assert a is not b
        assert a.name == "unit-test/model-A"
        assert b.name == "unit-test/model-B"

        _embedder.get_shared_embedder.cache_clear()


# ---------------------------------------------------------------------------
# Fleet sub-agent concurrency semaphore
# ---------------------------------------------------------------------------


def _email(stable_id: str, subject: str = "test") -> EmailData:
    e = EmailData(sender="test@ufpr.br", subject=subject, body="test body")
    e.stable_id = stable_id
    return e


def _cls(categoria: str = "Outros", confianca: float = 0.7) -> EmailClassification:
    return EmailClassification(
        categoria=categoria,
        resumo="x",
        acao_necessaria="Revisão Manual",
        sugestao_resposta="",
        confianca=confianca,
    )


class TestSubagentSemaphore:
    """Validate ``process_one_email`` serialises on ``_SUBAGENT_SEMAPHORE``."""

    def test_two_concurrent_calls_serialize_under_semaphore_of_1(self):
        """With ``Semaphore(1)``, two threads calling ``process_one_email``
        must NOT overlap: while thread A sleeps inside the semaphore,
        thread B is blocked acquiring. We detect overlap with a shared
        counter incremented on enter / decremented on exit of the
        (patched) classifier; max observed value must stay at 1.

        Patches are applied ONCE in the outer scope (they cover both
        worker threads) because ``unittest.mock.patch`` mutates module
        attributes globally — layering per-thread patch contexts races
        the module attribute restoration and is not safe under
        concurrency.
        """
        from ufpr_automation.graph import fleet

        # Narrow the semaphore to 1. We restore the original at the end.
        original_semaphore = fleet._SUBAGENT_SEMAPHORE
        fleet._SUBAGENT_SEMAPHORE = threading.Semaphore(1)

        in_flight = 0
        max_in_flight = 0
        lock = threading.Lock()

        cls = _cls("Outros", 0.7)

        def _slow_classify(_emails, _rag_contexts):
            nonlocal in_flight, max_in_flight
            with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            # Sleep long enough that a second thread would overlap if it
            # could — but short enough to keep the test snappy.
            time.sleep(0.2)
            with lock:
                in_flight -= 1
            # Classifier returns {stable_id: cls}; we extract stable_id
            # from the email it was given.
            return {_emails[0].stable_id: cls}

        results: list[dict] = []
        errors: list[BaseException] = []

        def _run(stable_id: str):
            try:
                results.append(
                    fleet.process_one_email(
                        {"email": _email(stable_id), "stable_id": stable_id}
                    )
                )
            except BaseException as e:  # pragma: no cover - surfaced via assert
                errors.append(e)

        try:
            with (
                patch("ufpr_automation.graph.nodes._get_retriever", return_value=None),
                patch("ufpr_automation.graph.nodes._get_graph_context", return_value=""),
                patch(
                    "ufpr_automation.graph.nodes._get_reflexion_context_single",
                    return_value="",
                ),
                patch("ufpr_automation.graph.nodes._should_use_dspy", return_value=False),
                patch(
                    "ufpr_automation.graph.nodes._classify_with_litellm",
                    side_effect=_slow_classify,
                ),
            ):
                t1 = threading.Thread(target=_run, args=("e1",))
                t2 = threading.Thread(target=_run, args=("e2",))
                t1.start()
                t2.start()
                t1.join(timeout=5.0)
                t2.join(timeout=5.0)

            assert not errors, f"sub-agent threads raised: {errors!r}"
            assert len(results) == 2
            assert max_in_flight == 1, (
                f"semaphore failed to serialize sub-agents — max concurrent observed "
                f"was {max_in_flight}, expected 1"
            )
            # Both invocations must have succeeded.
            ids_classified = set()
            for r in results:
                ids_classified.update(r["classifications"].keys())
            assert ids_classified == {"e1", "e2"}
        finally:
            fleet._SUBAGENT_SEMAPHORE = original_semaphore

    def test_semaphore_of_2_allows_two_concurrent(self):
        """Sanity check: with ``Semaphore(2)`` two sub-agents DO overlap."""
        from ufpr_automation.graph import fleet

        original_semaphore = fleet._SUBAGENT_SEMAPHORE
        fleet._SUBAGENT_SEMAPHORE = threading.Semaphore(2)

        in_flight = 0
        max_in_flight = 0
        lock = threading.Lock()
        both_started = threading.Event()
        started_count = 0

        cls = _cls("Outros", 0.7)

        def _slow_classify(_emails, _rag_contexts):
            nonlocal in_flight, max_in_flight, started_count
            with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
                started_count += 1
                if started_count >= 2:
                    both_started.set()
            # Wait until the OTHER thread has also entered, or give up
            # after a short timeout so a regression doesn't hang CI.
            both_started.wait(timeout=2.0)
            with lock:
                in_flight -= 1
            return {_emails[0].stable_id: cls}

        def _run(stable_id: str):
            fleet.process_one_email(
                {"email": _email(stable_id), "stable_id": stable_id}
            )

        try:
            with (
                patch("ufpr_automation.graph.nodes._get_retriever", return_value=None),
                patch("ufpr_automation.graph.nodes._get_graph_context", return_value=""),
                patch(
                    "ufpr_automation.graph.nodes._get_reflexion_context_single",
                    return_value="",
                ),
                patch("ufpr_automation.graph.nodes._should_use_dspy", return_value=False),
                patch(
                    "ufpr_automation.graph.nodes._classify_with_litellm",
                    side_effect=_slow_classify,
                ),
            ):
                t1 = threading.Thread(target=_run, args=("e1",))
                t2 = threading.Thread(target=_run, args=("e2",))
                t1.start()
                t2.start()
                t1.join(timeout=5.0)
                t2.join(timeout=5.0)

            assert max_in_flight == 2, (
                f"with Semaphore(2), sub-agents should overlap — observed max {max_in_flight}"
            )
        finally:
            fleet._SUBAGENT_SEMAPHORE = original_semaphore
