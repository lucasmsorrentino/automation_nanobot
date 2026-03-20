"""Integration test for the Pensar pipeline with mocked Gemini responses."""

from __future__ import annotations

import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ufpr_automation.core.models import EmailClassification, EmailData

# Ensure google.genai is mockable even if not installed
if "google.genai" not in sys.modules:
    sys.modules["google"] = MagicMock()
    sys.modules["google.genai"] = MagicMock()
    sys.modules["google.genai.types"] = MagicMock()


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


class TestRunPensarConcurrently:
    @pytest.mark.asyncio
    async def test_all_succeed(self):
        emails = [_make_email("a@ufpr.br", "Sub A"), _make_email("b@ufpr.br", "Sub B")]

        with (
            patch("ufpr_automation.llm.client.settings") as mock_settings,
            patch("ufpr_automation.llm.client.genai") as mock_genai,
        ):
            mock_settings.GEMINI_API_KEY = "fake"
            mock_settings.LLM_MODEL = "gemini-1.5-pro"
            mock_settings.PACKAGE_ROOT = MagicMock()
            mock_settings.ASSINATURA_EMAIL = None

            mock_response = MagicMock()
            mock_response.text = _make_classification_json()
            mock_genai.Client.return_value.aio.models.generate_content = AsyncMock(
                return_value=mock_response
            )

            from ufpr_automation.agents.pensar import run_pensar_concurrently

            ok_emails, classifications = await run_pensar_concurrently(emails)

            assert len(ok_emails) == 2
            assert len(classifications) == 2
            assert all(isinstance(c, EmailClassification) for c in classifications)

    @pytest.mark.asyncio
    async def test_partial_failure(self):
        emails = [_make_email("a@ufpr.br", "OK"), _make_email("b@ufpr.br", "FAIL")]

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("Gemini quota exceeded")
            resp = MagicMock()
            resp.text = _make_classification_json()
            return resp

        with (
            patch("ufpr_automation.llm.client.settings") as mock_settings,
            patch("ufpr_automation.llm.client.genai") as mock_genai,
        ):
            mock_settings.GEMINI_API_KEY = "fake"
            mock_settings.LLM_MODEL = "gemini-1.5-pro"
            mock_settings.PACKAGE_ROOT = MagicMock()
            mock_settings.ASSINATURA_EMAIL = None

            mock_genai.Client.return_value.aio.models.generate_content = AsyncMock(
                side_effect=side_effect
            )

            from ufpr_automation.agents.pensar import run_pensar_concurrently

            ok_emails, classifications = await run_pensar_concurrently(emails)

            assert len(ok_emails) == 1
            assert len(classifications) == 1
            assert ok_emails[0].subject == "OK"
