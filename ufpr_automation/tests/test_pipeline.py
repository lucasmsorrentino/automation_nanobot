"""Integration test for the Pensar pipeline with mocked cascade calls."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ufpr_automation.core.models import EmailClassification, EmailData


def _make_email(sender: str, subject: str) -> EmailData:
    email = EmailData(sender=sender, subject=subject, body="corpo do email")
    email.compute_stable_id()
    return email


def _make_classification_json(categoria: str = "Estágios") -> str:
    return json.dumps({
        "categoria": categoria,
        "resumo": "Resumo automático.",
        "acao_necessaria": "Arquivar",
        "sugestao_resposta": "",
    })


def _mock_completion_response(text: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = text
    return response


class TestRunPensarConcurrently:
    @pytest.mark.asyncio
    async def test_all_succeed(self):
        emails = [_make_email("a@ufpr.br", "Sub A"), _make_email("b@ufpr.br", "Sub B")]

        with (
            patch("ufpr_automation.llm.client.settings") as mock_settings,
            patch(
                "ufpr_automation.llm.client.cascaded_completion",
                new_callable=AsyncMock,
                return_value=_mock_completion_response(_make_classification_json()),
            ),
        ):
            mock_settings.MINIMAX_API_KEY = "fake"
            mock_settings.GEMINI_API_KEY = ""
            mock_settings.LLM_PROVIDER = "minimax"
            mock_settings.LLM_MODEL = "minimax/MiniMax-Text-01"
            mock_settings.PACKAGE_ROOT = MagicMock()
            mock_settings.ASSINATURA_EMAIL = None

            from ufpr_automation.agents.pensar import run_pensar_concurrently

            ok_emails, classifications = await run_pensar_concurrently(emails)

            assert len(ok_emails) == 2
            assert len(classifications) == 2
            assert all(isinstance(c, EmailClassification) for c in classifications)

    @pytest.mark.asyncio
    async def test_partial_failure(self):
        emails = [_make_email("a@ufpr.br", "OK"), _make_email("b@ufpr.br", "FAIL")]

        async def side_effect(task, *, messages, **kwargs):
            # Fail all LLM calls related to the "FAIL" email
            for msg in messages:
                if "FAIL" in msg.get("content", ""):
                    raise RuntimeError("API quota exceeded")
            return _mock_completion_response(_make_classification_json())

        with (
            patch("ufpr_automation.llm.client.settings") as mock_settings,
            patch(
                "ufpr_automation.llm.client.cascaded_completion",
                new_callable=AsyncMock,
                side_effect=side_effect,
            ),
        ):
            mock_settings.MINIMAX_API_KEY = "fake"
            mock_settings.GEMINI_API_KEY = ""
            mock_settings.LLM_PROVIDER = "minimax"
            mock_settings.LLM_MODEL = "minimax/MiniMax-Text-01"
            mock_settings.PACKAGE_ROOT = MagicMock()
            mock_settings.ASSINATURA_EMAIL = None

            from ufpr_automation.agents.pensar import run_pensar_concurrently

            ok_emails, classifications = await run_pensar_concurrently(emails)

            assert len(ok_emails) == 1
            assert len(classifications) == 1
            assert ok_emails[0].subject == "OK"
