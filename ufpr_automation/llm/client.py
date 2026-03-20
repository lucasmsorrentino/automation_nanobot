"""Client to interact with Gemini 1.5 Pro via Google GenAI SDK.

Used by PensarAgent to classify emails and generate draft responses.
Supports both sync (classify_email) and async (classify_email_async) calls
so PensarAgent can run multiple classifications concurrently.
"""

import json
from typing import Optional

from google import genai
from google.genai import types
from pydantic import TypeAdapter

from ufpr_automation.config import settings
from ufpr_automation.core.models import EmailClassification, EmailData
from ufpr_automation.utils.logging import logger


class GeminiClient:
    """Client for generating email classifications using Gemini.

    Args:
        system_instruction: Override the default system instruction.
            If None, builds it from workspace AGENTS.md + SOUL.md.
    """

    def __init__(self, system_instruction: Optional[str] = None):
        if not settings.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not set in settings or .env!")

        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)

        # Strip the "gemini/" prefix that nanobot config adds
        self.model_id = (
            settings.LLM_MODEL.replace("gemini/", "", 1)
            if settings.LLM_MODEL.startswith("gemini/")
            else settings.LLM_MODEL
        )

        self.system_instruction = system_instruction or self._build_system_instruction()

    # ------------------------------------------------------------------
    # System prompt construction
    # ------------------------------------------------------------------

    def _build_system_instruction(self) -> str:
        """Combine AGENTS.md (persona) and SOUL.md (norms) into one system prompt."""
        workspace_dir = settings.PACKAGE_ROOT / "workspace"

        agents_file = workspace_dir / "AGENTS.md"
        agents_content = (
            agents_file.read_text(encoding="utf-8")
            if agents_file.exists()
            else "Você é um assistente da UFPR."
        )

        soul_file = workspace_dir / "SOUL.md"
        soul_content = soul_file.read_text(encoding="utf-8") if soul_file.exists() else ""

        if settings.ASSINATURA_EMAIL:
            soul_content = soul_content.replace("{{ ASSINATURA_EMAIL }}", settings.ASSINATURA_EMAIL)

        return (
            f"{agents_content}\n\n"
            "=== NORMAS E CONHECIMENTO INSTITUCIONAL ===\n\n"
            f"{soul_content}"
        )

    # ------------------------------------------------------------------
    # Shared config factory
    # ------------------------------------------------------------------

    def _generation_config(self) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=self.system_instruction,
            response_mime_type="application/json",
            response_schema=EmailClassification,
            temperature=0.2,
        )

    def _build_prompt(self, email: EmailData) -> str:
        """Build the classification prompt, preferring full body over preview."""
        content = email.body if email.body else email.preview
        content_label = "Corpo completo" if email.body else "Preview"
        return (
            "Por favor, analise o seguinte e-mail recebido na caixa de entrada:\n\n"
            f"Remetente: {email.sender}\n"
            f"Assunto: {email.subject}\n"
            f"{content_label}:\n{content}\n\n"
            "Classifique o e-mail e redija uma resposta adequada seguindo as normas "
            "da UFPR contidas no seu contexto."
        )

    # ------------------------------------------------------------------
    # Sync classification
    # ------------------------------------------------------------------

    def classify_email(self, email: EmailData) -> EmailClassification:
        """Classify and draft a reply for *email* (synchronous)."""
        try:
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=self._build_prompt(email),
                config=self._generation_config(),
            )
            adapter = TypeAdapter(EmailClassification)
            return adapter.validate_python(json.loads(response.text))

        except Exception as e:
            logger.warning("Erro ao classificar '%s': %s", email.subject, e)
            return EmailClassification(
                categoria="Outros",
                resumo=f"Erro na análise LLM: {e}",
                acao_necessaria="Revisão Manual",
                sugestao_resposta="",
            )

    # ------------------------------------------------------------------
    # Async classification (used by PensarAgent for concurrent processing)
    # ------------------------------------------------------------------

    async def classify_email_async(self, email: EmailData) -> EmailClassification:
        """Classify and draft a reply for *email* (asynchronous).

        Uses the google-genai async interface so multiple emails can be
        classified concurrently via asyncio.gather().

        Raises on failure — partial failure handling in run_pensar_concurrently()
        ensures that individual errors don't break the whole pipeline.
        """
        response = await self.client.aio.models.generate_content(
            model=self.model_id,
            contents=self._build_prompt(email),
            config=self._generation_config(),
        )
        adapter = TypeAdapter(EmailClassification)
        return adapter.validate_python(json.loads(response.text))
