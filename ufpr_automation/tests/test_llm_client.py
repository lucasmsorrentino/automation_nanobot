"""Tests for llm/client.py — LLMClient with mocked cascade calls."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ufpr_automation.core.models import AttachmentData, EmailClassification, EmailData
from ufpr_automation.llm.client import LLMClient


@pytest.fixture
def sample_email():
    return EmailData(
        sender="professor@ufpr.br",
        subject="Solicitação de Estágio",
        body="Prezado, solicito aprovação do estágio...",
    )


@pytest.fixture
def valid_classification_json():
    return json.dumps(
        {
            "categoria": "Estágios",
            "resumo": "Solicitação de aprovação de estágio.",
            "acao_necessaria": "Redigir Resposta",
            "sugestao_resposta": "Prezado(a), recebemos sua solicitação...",
        }
    )


def _mock_completion_response(text: str) -> MagicMock:
    """Build a mock litellm response with the given text content."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = text
    return response


# ---------------------------------------------------------------------------
# _extract_json — static method for stripping markdown fences
# ---------------------------------------------------------------------------


class TestExtractJson:
    def test_plain_json(self):
        raw = '{"categoria": "Estágios"}'
        assert LLMClient._extract_json(raw) == '{"categoria": "Estágios"}'

    def test_json_in_code_fence(self):
        raw = '```json\n{"categoria": "Estágios"}\n```'
        assert LLMClient._extract_json(raw) == '{"categoria": "Estágios"}'

    def test_json_in_bare_code_fence(self):
        raw = '```\n{"key": "value"}\n```'
        assert LLMClient._extract_json(raw) == '{"key": "value"}'

    def test_json_with_surrounding_text(self):
        raw = 'Here is the result:\n```json\n{"x": 1}\n```\nDone.'
        assert LLMClient._extract_json(raw) == '{"x": 1}'

    def test_no_fence_strips_whitespace(self):
        raw = "  \n  {}\n  "
        assert LLMClient._extract_json(raw) == "{}"


# ---------------------------------------------------------------------------
# _build_messages — prompt construction
# ---------------------------------------------------------------------------


class TestBuildMessages:
    def _make_client(self):
        with patch("ufpr_automation.llm.client.settings") as mock_settings:
            mock_settings.MINIMAX_API_KEY = "fake"
            mock_settings.GEMINI_API_KEY = ""
            mock_settings.LLM_PROVIDER = "minimax"
            mock_settings.LLM_MODEL = "minimax/test"
            mock_settings.PACKAGE_ROOT = MagicMock()
            mock_settings.ASSINATURA_EMAIL = None
            return LLMClient(system_instruction="You are a test assistant.")

    def test_basic_structure(self):
        client = self._make_client()
        email = EmailData(sender="a@b.com", subject="Test", body="Hello")
        msgs = client._build_messages(email)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"

    def test_includes_sender_and_subject(self):
        client = self._make_client()
        email = EmailData(sender="aluno@ufpr.br", subject="TCE João", body="corpo")
        msgs = client._build_messages(email)
        user_content = msgs[1]["content"]
        assert "aluno@ufpr.br" in user_content
        assert "TCE João" in user_content

    def test_rag_context_injected(self):
        client = self._make_client()
        email = EmailData(sender="a@b.com", subject="Test", body="Hello")
        msgs = client._build_messages(email, rag_context="Resolução 42/2025 dispõe...")
        user_content = msgs[1]["content"]
        assert "NORMAS E DOCUMENTOS RECUPERADOS" in user_content
        assert "Resolução 42/2025" in user_content

    def test_no_rag_context(self):
        client = self._make_client()
        email = EmailData(sender="a@b.com", subject="Test", body="Hello")
        msgs = client._build_messages(email)
        user_content = msgs[1]["content"]
        assert "NORMAS E DOCUMENTOS RECUPERADOS" not in user_content

    def test_attachment_with_text_included(self):
        client = self._make_client()
        email = EmailData(
            sender="a@b.com",
            subject="Test",
            body="Hello",
            attachments=[
                AttachmentData(
                    filename="tce.pdf",
                    mime_type="application/pdf",
                    extracted_text="Termo de Compromisso de Estágio",
                ),
            ],
        )
        msgs = client._build_messages(email)
        user_content = msgs[1]["content"]
        assert "ANEXOS DO E-MAIL" in user_content
        assert "Termo de Compromisso" in user_content

    def test_attachment_needs_ocr_noted(self):
        client = self._make_client()
        email = EmailData(
            sender="a@b.com",
            subject="Test",
            body="Hello",
            attachments=[
                AttachmentData(filename="scan.pdf", mime_type="application/pdf", needs_ocr=True),
            ],
        )
        msgs = client._build_messages(email)
        user_content = msgs[1]["content"]
        assert "escaneado" in user_content

    def test_uses_preview_when_no_body(self):
        client = self._make_client()
        email = EmailData(sender="a@b.com", subject="Test", body="", preview="Preview text")
        msgs = client._build_messages(email)
        user_content = msgs[1]["content"]
        assert "Preview text" in user_content

    def test_categories_listed(self):
        client = self._make_client()
        email = EmailData(sender="a@b.com", subject="Test", body="Hello")
        msgs = client._build_messages(email)
        user_content = msgs[1]["content"]
        assert "Estágios" in user_content
        assert "Correio Lixo" in user_content
        assert "Outros" in user_content


class TestLLMClientSync:
    def test_classify_email_valid_response(self, sample_email, valid_classification_json):
        with (
            patch("ufpr_automation.llm.client.settings") as mock_settings,
            patch(
                "ufpr_automation.llm.client.cascaded_completion_sync",
                return_value=_mock_completion_response(valid_classification_json),
            ),
        ):
            mock_settings.MINIMAX_API_KEY = "fake-key"
            mock_settings.GEMINI_API_KEY = ""
            mock_settings.LLM_PROVIDER = "minimax"
            mock_settings.LLM_MODEL = "minimax/MiniMax-Text-01"
            mock_settings.PACKAGE_ROOT = MagicMock()
            mock_settings.ASSINATURA_EMAIL = None

            from ufpr_automation.llm.client import LLMClient

            client = LLMClient(system_instruction="test")
            result = client.classify_email(sample_email)

            assert isinstance(result, EmailClassification)
            assert result.categoria == "Estágios"
            assert result.sugestao_resposta != ""

    def test_classify_email_error_returns_outros(self, sample_email):
        with (
            patch("ufpr_automation.llm.client.settings") as mock_settings,
            patch(
                "ufpr_automation.llm.client.cascaded_completion_sync",
                side_effect=RuntimeError("API error"),
            ),
        ):
            mock_settings.MINIMAX_API_KEY = "fake-key"
            mock_settings.GEMINI_API_KEY = ""
            mock_settings.LLM_PROVIDER = "minimax"
            mock_settings.LLM_MODEL = "minimax/MiniMax-Text-01"
            mock_settings.PACKAGE_ROOT = MagicMock()
            mock_settings.ASSINATURA_EMAIL = None

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
            patch(
                "ufpr_automation.llm.client.cascaded_completion",
                new_callable=AsyncMock,
                return_value=_mock_completion_response(valid_classification_json),
            ),
        ):
            mock_settings.MINIMAX_API_KEY = "fake-key"
            mock_settings.GEMINI_API_KEY = ""
            mock_settings.LLM_PROVIDER = "minimax"
            mock_settings.LLM_MODEL = "minimax/MiniMax-Text-01"
            mock_settings.PACKAGE_ROOT = MagicMock()
            mock_settings.ASSINATURA_EMAIL = None

            from ufpr_automation.llm.client import LLMClient

            client = LLMClient(system_instruction="test")
            result = await client.classify_email_async(sample_email)

            assert isinstance(result, EmailClassification)
            assert result.categoria == "Estágios"

    @pytest.mark.asyncio
    async def test_classify_email_async_raises_on_error(self, sample_email):
        with (
            patch("ufpr_automation.llm.client.settings") as mock_settings,
            patch(
                "ufpr_automation.llm.client.cascaded_completion",
                new_callable=AsyncMock,
                side_effect=RuntimeError("API error"),
            ),
        ):
            mock_settings.MINIMAX_API_KEY = "fake-key"
            mock_settings.GEMINI_API_KEY = ""
            mock_settings.LLM_PROVIDER = "minimax"
            mock_settings.LLM_MODEL = "minimax/MiniMax-Text-01"
            mock_settings.PACKAGE_ROOT = MagicMock()
            mock_settings.ASSINATURA_EMAIL = None

            from ufpr_automation.llm.client import LLMClient

            client = LLMClient(system_instruction="test")
            with pytest.raises(RuntimeError, match="API error"):
                await client.classify_email_async(sample_email)


# ---------------------------------------------------------------------------
# self_refine_async — critique → refine cycle
# ---------------------------------------------------------------------------


class TestSelfRefine:
    @pytest.mark.asyncio
    async def test_no_problems_returns_original(self, sample_email):
        """When critique says 'SEM PROBLEMAS', the original classification is returned."""
        original = EmailClassification(
            categoria="Estágios",
            resumo="Solicitação de estágio",
            acao_necessaria="Redigir Resposta",
            sugestao_resposta="Prezado...",
            confianca=0.9,
        )
        critique_resp = _mock_completion_response("SEM PROBLEMAS")

        with (
            patch("ufpr_automation.llm.client.settings") as mock_settings,
            patch(
                "ufpr_automation.llm.client.cascaded_completion",
                new_callable=AsyncMock,
                return_value=critique_resp,
            ),
        ):
            mock_settings.MINIMAX_API_KEY = "fake"
            mock_settings.GEMINI_API_KEY = ""
            mock_settings.LLM_PROVIDER = "minimax"
            mock_settings.LLM_MODEL = "minimax/test"
            mock_settings.PACKAGE_ROOT = MagicMock()
            mock_settings.ASSINATURA_EMAIL = None

            client = LLMClient(system_instruction="test")
            result = await client.self_refine_async(sample_email, original)

        assert result is original

    @pytest.mark.asyncio
    async def test_problems_triggers_refine(self, sample_email):
        """When critique finds issues, a refined classification is returned."""
        original = EmailClassification(
            categoria="Outros",
            resumo="Classificação errada",
            acao_necessaria="Redigir Resposta",
            sugestao_resposta="Draft errado",
            confianca=0.5,
        )
        refined_json = json.dumps({
            "categoria": "Estágios",
            "resumo": "Solicitação de estágio corrigida",
            "acao_necessaria": "Redigir Resposta",
            "sugestao_resposta": "Prezado, corrigido...",
            "confianca": 0.85,
        })

        critique_resp = _mock_completion_response("1. Categoria errada, deveria ser Estágios.")
        refine_resp = _mock_completion_response(refined_json)

        with (
            patch("ufpr_automation.llm.client.settings") as mock_settings,
            patch(
                "ufpr_automation.llm.client.cascaded_completion",
                new_callable=AsyncMock,
                side_effect=[critique_resp, refine_resp],
            ) as mock_cascade,
        ):
            mock_settings.MINIMAX_API_KEY = "fake"
            mock_settings.GEMINI_API_KEY = ""
            mock_settings.LLM_PROVIDER = "minimax"
            mock_settings.LLM_MODEL = "minimax/test"
            mock_settings.PACKAGE_ROOT = MagicMock()
            mock_settings.ASSINATURA_EMAIL = None

            client = LLMClient(system_instruction="test")
            result = await client.self_refine_async(sample_email, original)

        assert result is not original
        assert result.categoria == "Estágios"
        assert result.confianca == 0.85
        # Two calls: critique + refine
        assert mock_cascade.call_count == 2

    @pytest.mark.asyncio
    async def test_with_rag_context(self, sample_email):
        """RAG context is included in both critique and refine prompts."""
        original = EmailClassification(
            categoria="Estágios",
            resumo="ok",
            acao_necessaria="Redigir Resposta",
            sugestao_resposta="Draft",
            confianca=0.9,
        )
        critique_resp = _mock_completion_response("SEM PROBLEMAS")

        with (
            patch("ufpr_automation.llm.client.settings") as mock_settings,
            patch(
                "ufpr_automation.llm.client.cascaded_completion",
                new_callable=AsyncMock,
                return_value=critique_resp,
            ) as mock_cascade,
        ):
            mock_settings.MINIMAX_API_KEY = "fake"
            mock_settings.GEMINI_API_KEY = ""
            mock_settings.LLM_PROVIDER = "minimax"
            mock_settings.LLM_MODEL = "minimax/test"
            mock_settings.PACKAGE_ROOT = MagicMock()
            mock_settings.ASSINATURA_EMAIL = None

            client = LLMClient(system_instruction="test")
            await client.self_refine_async(
                sample_email, original, rag_context="Resolução 42/2025"
            )

        # RAG context should appear in the critique prompt
        critique_call = mock_cascade.call_args_list[0]
        user_msg = critique_call[1]["messages"][1]["content"]
        assert "Resolução 42/2025" in user_msg
