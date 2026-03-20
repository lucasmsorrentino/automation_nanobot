"""Tests for llm/client.py — GeminiClient with mocked API calls."""

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


class TestGeminiClientSync:
    def test_classify_email_valid_response(self, sample_email, valid_classification_json):
        with (
            patch("ufpr_automation.llm.client.settings") as mock_settings,
            patch("ufpr_automation.llm.client.genai") as mock_genai,
        ):
            mock_settings.GEMINI_API_KEY = "fake-key"
            mock_settings.LLM_MODEL = "gemini/gemini-1.5-pro"
            mock_settings.PACKAGE_ROOT = MagicMock()
            mock_settings.ASSINATURA_EMAIL = None

            mock_response = MagicMock()
            mock_response.text = valid_classification_json
            mock_genai.Client.return_value.models.generate_content.return_value = mock_response

            from ufpr_automation.llm.client import GeminiClient

            client = GeminiClient(system_instruction="test")
            result = client.classify_email(sample_email)

            assert isinstance(result, EmailClassification)
            assert result.categoria == "Estágios"
            assert result.sugestao_resposta != ""

    def test_classify_email_error_returns_outros(self, sample_email):
        with (
            patch("ufpr_automation.llm.client.settings") as mock_settings,
            patch("ufpr_automation.llm.client.genai") as mock_genai,
        ):
            mock_settings.GEMINI_API_KEY = "fake-key"
            mock_settings.LLM_MODEL = "gemini-1.5-pro"
            mock_settings.PACKAGE_ROOT = MagicMock()
            mock_settings.ASSINATURA_EMAIL = None

            mock_genai.Client.return_value.models.generate_content.side_effect = (
                RuntimeError("API error")
            )

            from ufpr_automation.llm.client import GeminiClient

            client = GeminiClient(system_instruction="test")
            result = client.classify_email(sample_email)

            assert result.categoria == "Outros"
            assert "Erro" in result.resumo


class TestGeminiClientAsync:
    @pytest.mark.asyncio
    async def test_classify_email_async_valid(self, sample_email, valid_classification_json):
        with (
            patch("ufpr_automation.llm.client.settings") as mock_settings,
            patch("ufpr_automation.llm.client.genai") as mock_genai,
        ):
            mock_settings.GEMINI_API_KEY = "fake-key"
            mock_settings.LLM_MODEL = "gemini/gemini-1.5-pro"
            mock_settings.PACKAGE_ROOT = MagicMock()
            mock_settings.ASSINATURA_EMAIL = None

            mock_response = MagicMock()
            mock_response.text = valid_classification_json
            mock_genai.Client.return_value.aio.models.generate_content = AsyncMock(
                return_value=mock_response
            )

            from ufpr_automation.llm.client import GeminiClient

            client = GeminiClient(system_instruction="test")
            result = await client.classify_email_async(sample_email)

            assert isinstance(result, EmailClassification)
            assert result.categoria == "Estágios"

    @pytest.mark.asyncio
    async def test_classify_email_async_raises_on_error(self, sample_email):
        with (
            patch("ufpr_automation.llm.client.settings") as mock_settings,
            patch("ufpr_automation.llm.client.genai") as mock_genai,
        ):
            mock_settings.GEMINI_API_KEY = "fake-key"
            mock_settings.LLM_MODEL = "gemini-1.5-pro"
            mock_settings.PACKAGE_ROOT = MagicMock()
            mock_settings.ASSINATURA_EMAIL = None

            mock_genai.Client.return_value.aio.models.generate_content = AsyncMock(
                side_effect=RuntimeError("API error")
            )

            from ufpr_automation.llm.client import GeminiClient

            client = GeminiClient(system_instruction="test")
            with pytest.raises(RuntimeError, match="API error"):
                await client.classify_email_async(sample_email)
