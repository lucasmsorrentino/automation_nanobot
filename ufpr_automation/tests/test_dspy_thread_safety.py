"""Regression test for the DSPy + Fleet thread-conflict bug.

Context: LangGraph dispatches Fleet sub-agents in separate worker threads,
and each sub-agent called ``dspy.configure(lm=lm)`` — which DSPy rejects
from any thread other than the first one to call it
(``dspy.settings can only be changed by the thread that initially configured it``).

Fix: ``_classify_with_dspy`` uses ``dspy.settings.context(lm=lm)``
(thread-local override) instead of ``dspy.configure``. This test proves
the new path runs correctly from N concurrent threads.
"""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from ufpr_automation.core.models import EmailData


@pytest.fixture
def emails():
    out = []
    for i in range(5):
        e = EmailData(sender=f"t{i}@ufpr.br", subject=f"s{i}", body=f"b{i}")
        e.stable_id = f"e{i}"
        out.append(e)
    return out


def test_classify_with_dspy_is_thread_safe(emails, monkeypatch):
    """N threads call ``_classify_with_dspy`` concurrently with their own LM.

    Before the fix this raised ``dspy.settings can only be changed by the
    thread that initially configured it`` from every thread except the
    first. After the fix (``settings.context``) every thread succeeds.
    """
    import dspy

    from ufpr_automation.graph import nodes as graph_nodes

    # Stub SelfRefineModule so the test doesn't need a compiled prompt
    # or a real LM endpoint. The module's ``__call__`` just returns a
    # prediction whose attributes the classifier post-processor reads.
    class _StubPrediction:
        categoria = "Outros"
        resumo = "stub"
        acao_necessaria = "Revisão Manual"
        sugestao_resposta = ""
        confianca = 0.5

    class _StubModule:
        def __init__(self):
            pass

        def load(self, path):  # mimic dspy.Module.load
            pass

        def __call__(self, **kwargs):
            # Touch dspy.settings.lm to assert the thread-local LM is
            # visible inside ``settings.context`` (what the real DSPy
            # modules would do).
            assert dspy.settings.lm is not None
            return _StubPrediction()

    # Pretend a compiled prompt file exists so ``_classify_with_dspy``
    # doesn't raise its defensive RuntimeError.
    from pathlib import Path

    fake_path = Path("/nonexistent/pretend-compiled.json")
    monkeypatch.setattr(fake_path.__class__, "exists", lambda self: True)

    with (
        patch(
            "ufpr_automation.dspy_modules.modules.SelfRefineModule",
            _StubModule,
        ),
        patch(
            "ufpr_automation.dspy_modules.modules.prediction_to_classification",
            lambda pred: pred,
        ),
        patch.object(graph_nodes, "_compiled_prompt_paths", return_value=[fake_path]),
    ):
        errors: list[tuple[int, str]] = []
        results: list[tuple[int, dict]] = []

        def worker(i: int):
            try:
                res = graph_nodes._classify_with_dspy(
                    [emails[i]], {emails[i].stable_id: ""}
                )
                results.append((i, res))
            except Exception as exc:  # pragma: no cover - assertion
                errors.append((i, str(exc)))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(emails))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert not errors, f"DSPy threw from worker threads: {errors}"
    assert len(results) == len(emails)
    # Each thread produced one classification for its own email.
    for i, res in results:
        assert emails[i].stable_id in res
