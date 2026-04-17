"""Tests for ufpr_automation.agents.pensar — think phase."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ufpr_automation.agents.pensar import (
    MAX_CONCURRENT_LLM_CALLS,
    PensarAgent,
    run_pensar_concurrently,
)
from ufpr_automation.core.models import EmailClassification, EmailData


def _make_classification(categoria: str = "Outros", confianca: float = 0.9) -> EmailClassification:
    return EmailClassification(
        categoria=categoria,
        resumo="Resumo de teste",
        acao_necessaria="Redigir Resposta",
        sugestao_resposta="Prezado, obrigado pelo contato.",
        confianca=confianca,
    )


class TestPensarAgentRun:
    @pytest.mark.asyncio
    async def test_classifies_and_runs_self_refine(self, sample_email):
        """PensarAgent.run() should classify then self-refine."""
        refined = _make_classification(categoria="Estágios", confianca=0.95)
        initial = _make_classification(categoria="Outros", confianca=0.7)

        client = MagicMock()
        client.classify_email_async = AsyncMock(return_value=initial)
        client.self_refine_async = AsyncMock(return_value=refined)

        agent = PensarAgent(client, sample_email, rag_context="norma XYZ")
        semaphore = asyncio.Semaphore(1)
        result = await agent.run(semaphore)

        # Verified both methods were awaited in order.
        client.classify_email_async.assert_awaited_once_with(sample_email, rag_context="norma XYZ")
        client.self_refine_async.assert_awaited_once_with(
            sample_email, initial, rag_context="norma XYZ"
        )
        # Self-refine output is what gets returned.
        assert result is refined

    @pytest.mark.asyncio
    async def test_self_refine_failure_falls_back_to_initial(self, sample_email):
        """If self_refine_async raises, the initial classification is used."""
        initial = _make_classification()

        client = MagicMock()
        client.classify_email_async = AsyncMock(return_value=initial)
        client.self_refine_async = AsyncMock(side_effect=RuntimeError("boom"))

        agent = PensarAgent(client, sample_email)
        result = await agent.run(asyncio.Semaphore(1))

        assert result is initial

    @pytest.mark.asyncio
    async def test_respects_semaphore(self, sample_email):
        """The agent should acquire the semaphore before calling the LLM."""
        client = MagicMock()
        client.classify_email_async = AsyncMock(return_value=_make_classification())
        client.self_refine_async = AsyncMock(return_value=_make_classification())

        semaphore = asyncio.Semaphore(1)
        await semaphore.acquire()  # Exhaust the semaphore.

        agent = PensarAgent(client, sample_email)
        task = asyncio.create_task(agent.run(semaphore))

        # Task should NOT have started calling the LLM yet (semaphore blocked).
        await asyncio.sleep(0.01)
        assert not client.classify_email_async.await_count

        # Release the semaphore and confirm it now runs.
        semaphore.release()
        await task
        assert client.classify_email_async.await_count == 1


class TestRunPensarConcurrently:
    @pytest.mark.asyncio
    async def test_empty_input_returns_empty_tuple(self):
        emails, cls = await run_pensar_concurrently([])
        assert emails == []
        assert cls == []

    @pytest.mark.asyncio
    async def test_classifies_all_emails_concurrently(self):
        emails = [
            EmailData(sender=f"a{i}@ufpr.br", subject=f"Assunto {i}", body=f"Corpo {i}")
            for i in range(3)
        ]
        for e in emails:
            e.compute_stable_id()

        classification = _make_classification()

        fake_client = MagicMock()
        fake_client.classify_email_async = AsyncMock(return_value=classification)
        fake_client.self_refine_async = AsyncMock(return_value=classification)

        with (
            patch("ufpr_automation.agents.pensar.LLMClient", return_value=fake_client),
            patch("ufpr_automation.agents.pensar._fetch_rag_contexts", return_value={}),
        ):
            ok_emails, results = await run_pensar_concurrently(emails)

        assert len(ok_emails) == 3
        assert len(results) == 3
        assert fake_client.classify_email_async.await_count == 3

    @pytest.mark.asyncio
    async def test_partial_failures_are_filtered(self):
        emails = [
            EmailData(sender="ok@ufpr.br", subject="ok", body="corpo ok"),
            EmailData(sender="fail@ufpr.br", subject="fail", body="corpo fail"),
        ]
        for e in emails:
            e.compute_stable_id()

        good = _make_classification()

        async def _classify(email, rag_context=None):
            if email.sender == "fail@ufpr.br":
                raise RuntimeError("LLM exploded")
            return good

        fake_client = MagicMock()
        fake_client.classify_email_async = AsyncMock(side_effect=_classify)
        fake_client.self_refine_async = AsyncMock(return_value=good)

        with (
            patch("ufpr_automation.agents.pensar.LLMClient", return_value=fake_client),
            patch("ufpr_automation.agents.pensar._fetch_rag_contexts", return_value={}),
        ):
            ok_emails, results = await run_pensar_concurrently(emails)

        # Only the successful email remains.
        assert len(ok_emails) == 1
        assert ok_emails[0].sender == "ok@ufpr.br"
        assert len(results) == 1


class TestMaxConcurrentConstant:
    def test_max_concurrent_is_positive(self):
        assert MAX_CONCURRENT_LLM_CALLS > 0
