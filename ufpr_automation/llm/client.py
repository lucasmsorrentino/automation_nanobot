"""Client to interact with LLMs via LiteLLM (currently MiniMax).

Used by PensarAgent to classify emails and generate draft responses.
Supports both sync (classify_email) and async (classify_email_async) calls
so PensarAgent can run multiple classifications concurrently.
"""

import json
import re
from typing import Optional

import litellm
from pydantic import TypeAdapter

from ufpr_automation.config import settings
from ufpr_automation.core.models import EmailClassification, EmailData
from ufpr_automation.utils.logging import logger


class LLMClient:
    """Client for generating email classifications using LiteLLM.

    Args:
        system_instruction: Override the default system instruction.
            If None, builds it from workspace AGENTS.md + SOUL.md.
    """

    def __init__(self, system_instruction: Optional[str] = None):
        # LiteLLM reads API keys from env vars (MINIMAX_API_KEY, GEMINI_API_KEY, etc.)
        # Validate that *some* key is configured for the chosen provider.
        provider = settings.LLM_PROVIDER
        key_map = {"minimax": settings.MINIMAX_API_KEY, "gemini": settings.GEMINI_API_KEY}
        api_key = key_map.get(provider, "")
        if not api_key:
            raise ValueError(f"No API key found for provider '{provider}'. Set the appropriate env var.")

        self.model_id = settings.LLM_MODEL
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
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json(text: str) -> str:
        """Strip markdown code fences (```json ... ```) if present."""
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        return m.group(1).strip() if m else text.strip()

    def _build_messages(self, email: EmailData) -> list[dict]:
        """Build the messages list for litellm completion."""
        content = email.body if email.body else email.preview
        content_label = "Corpo completo" if email.body else "Preview"
        user_prompt = (
            "Por favor, analise o seguinte e-mail recebido na caixa de entrada:\n\n"
            f"Remetente: {email.sender}\n"
            f"Assunto: {email.subject}\n"
            f"{content_label}:\n{content}\n\n"
            "Classifique o e-mail e redija uma resposta adequada seguindo as normas "
            "da UFPR contidas no seu contexto.\n\n"
            "Responda SOMENTE com um JSON válido contendo as chaves: "
            '"categoria", "resumo", "acao_necessaria", "sugestao_resposta".\n'
            "Categorias válidas: Estágios, Ofícios, Memorandos, Requerimentos, "
            "Portarias, Informes, Urgente, Correio Lixo, Outros."
        )
        return [
            {"role": "system", "content": self.system_instruction},
            {"role": "user", "content": user_prompt},
        ]

    # ------------------------------------------------------------------
    # Sync classification
    # ------------------------------------------------------------------

    def classify_email(self, email: EmailData) -> EmailClassification:
        """Classify and draft a reply for *email* (synchronous)."""
        try:
            response = litellm.completion(
                model=self.model_id,
                messages=self._build_messages(email),
                temperature=0.2,
            )
            raw = response.choices[0].message.content
            text = self._extract_json(raw)
            adapter = TypeAdapter(EmailClassification)
            return adapter.validate_python(json.loads(text))

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

        Uses litellm.acompletion() so multiple emails can be
        classified concurrently via asyncio.gather().

        Raises on failure — partial failure handling in run_pensar_concurrently()
        ensures that individual errors don't break the whole pipeline.
        """
        response = await litellm.acompletion(
            model=self.model_id,
            messages=self._build_messages(email),
            temperature=0.2,
        )
        raw = response.choices[0].message.content
        text = self._extract_json(raw)
        adapter = TypeAdapter(EmailClassification)
        return adapter.validate_python(json.loads(text))


# Backward-compatible alias
GeminiClient = LLMClient
