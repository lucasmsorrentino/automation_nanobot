"""Tests for llm/client.py — LLMClient with mocked LiteLLM calls."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ufpr_automation.core.models import EmailClassification, EmailData


@pytest.fixture
def sample_email():
    return EmailData(
        sender="professor@ufpr.br",
        subject="Solicitação de Estágio",
        body="Prezado, solicito aprovação do estágio...",
    )


@pytest.fixture
def valid_classification_json():
    return json.dumps({
        "categoria": "Estágios",
        "resumo": "Solicitação de aprovação de estágio.",
        "acao_necessaria": "Redigir Resposta",
        "sugestao_resposta": "Prezado(a), recebemos sua solicitação...",
    })


def _mock_completion_response(text: str) -> MagicMock:
    """Build a mock litellm response with the given text content."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = text
    return response


class TestLLMClientSync:
    def test_classify_email_valid_response(self, sample_email, valid_classification_json):
        with (
            patch("ufpr_automation.llm.client.settings") as mock_settings,
            patch("ufpr_automation.llm.client.litellm") as mock_litellm,
        ):
            mock_settings.MINIMAX_API_KEY = "fake-key"
            mock_settings.GEMINI_API_KEY = ""
            mock_settings.LLM_PROVIDER = "minimax"
            mock_settings.LLM_MODEL = "minimax/MiniMax-Text-01"
            mock_settings.PACKAGE_ROOT = MagicMock()
            mock_settings.ASSINATURA_EMAIL = None

            mock_litellm.completion.return_value = _mock_completion_response(
                valid_classification_json
            )

            from ufpr_automation.llm.client import LLMClient

            client = LLMClient(system_instruction="test")
            result = client.classify_email(sample_email)

            assert isinstance(result, EmailClassification)
            assert result.categoria == "Estágios"
            assert result.sugestao_resposta != ""

    def test_classify_email_error_returns_outros(self, sample_email):
        with (
            patch("ufpr_automation.llm.client.settings") as mock_settings,
            patch("ufpr_automation.llm.client.litellm") as mock_litellm,
        ):
            mock_settings.MINIMAX_API_KEY = "fake-key"
            mock_settings.GEMINI_API_KEY = ""
            mock_settings.LLM_PROVIDER = "minimax"
            mock_settings.LLM_MODEL = "minimax/MiniMax-Text-01"
            mock_settings.PACKAGE_ROOT = MagicMock()
            mock_settings.ASSINATURA_EMAIL = None

            mock_litellm.completion.side_effect = RuntimeError("API error")

            from ufpr_automation.llm.client import LLMClient

            client = LLMClient(system_instruction="test")
            result = client.classify_email(sample_email)

            assert result.categoria == "Outros"
            assert "Erro" in result.resumo


class TestLLMClientAsync:
    @pytest.mark.asyncio
    async def test_classify_email_async_valid(self, sample_email, valid_classification_json):
        with (
            patch("ufpr_automation.llm.client.settings") as mock_settings,
            patch("ufpr_automation.llm.client.litellm") as mock_litellm,
        ):
            mock_settings.MINIMAX_API_KEY = "fake-key"
            mock_settings.GEMINI_API_KEY = ""
            mock_settings.LLM_PROVIDER = "minimax"
            mock_settings.LLM_MODEL = "minimax/MiniMax-Text-01"
            mock_settings.PACKAGE_ROOT = MagicMock()
            mock_settings.ASSINATURA_EMAIL = None

            mock_litellm.acompletion = AsyncMock(
                return_value=_mock_completion_response(valid_classification_json)
            )

            from ufpr_automation.llm.client import LLMClient

            client = LLMClient(system_instruction="test")
            result = await client.classify_email_async(sample_email)

            assert isinstance(result, EmailClassification)
            assert result.categoria == "Estágios"

    @pytest.mark.asyncio
    async def test_classify_email_async_raises_on_error(self, sample_email):
        with (
            patch("ufpr_automation.llm.client.settings") as mock_settings,
            patch("ufpr_automation.llm.client.litellm") as mock_litellm,
        ):
            mock_settings.MINIMAX_API_KEY = "fake-key"
            mock_settings.GEMINI_API_KEY = ""
            mock_settings.LLM_PROVIDER = "minimax"
            mock_settings.LLM_MODEL = "minimax/MiniMax-Text-01"
            mock_settings.PACKAGE_ROOT = MagicMock()
            mock_settings.ASSINATURA_EMAIL = None

            mock_litellm.acompletion = AsyncMock(
                side_effect=RuntimeError("API error")
            )

            from ufpr_automation.llm.client import LLMClient

            client = LLMClient(system_instruction="test")
            with pytest.raises(RuntimeError, match="API error"):
                await client.classify_email_async(sample_email)
