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

    def _build_messages(
        self, email: EmailData, rag_context: str | None = None
    ) -> list[dict]:
        """Build the messages list for litellm completion.

        Args:
            email: The email to classify.
            rag_context: Optional RAG-retrieved normative documents to inject.
        """
        content = email.body if email.body else email.preview
        content_label = "Corpo completo" if email.body else "Preview"

        rag_section = ""
        if rag_context:
            rag_section = (
                "\n\n=== NORMAS E DOCUMENTOS RECUPERADOS (base vetorial) ===\n\n"
                f"{rag_context}\n\n"
                "Use as normas acima como referência para classificar e redigir a resposta. "
                "Cite a resolução ou documento específico quando aplicável.\n"
            )

        # Build attachment context if available
        attachment_section = ""
        if email.attachments:
            attachment_section = "\n\n=== ANEXOS DO E-MAIL ===\n"
            for att in email.attachments:
                if att.extracted_text:
                    truncated = att.extracted_text[:3000]
                    attachment_section += f"\n[Anexo: {att.filename}]\n{truncated}\n"
                elif att.needs_ocr:
                    attachment_section += (
                        f"\n[Anexo: {att.filename} — documento escaneado, "
                        "texto nao disponivel]\n"
                    )
                else:
                    attachment_section += (
                        f"\n[Anexo: {att.filename} ({att.mime_type}) — "
                        "tipo nao suportado para extracao]\n"
                    )

        user_prompt = (
            "Por favor, analise o seguinte e-mail recebido na caixa de entrada:\n\n"
            f"Remetente: {email.sender}\n"
            f"Assunto: {email.subject}\n"
            f"{content_label}:\n{content}\n"
            f"{attachment_section}"
            f"{rag_section}\n"
            "Classifique o e-mail e redija uma resposta adequada seguindo as normas "
            "da UFPR contidas no seu contexto.\n\n"
            "Responda SOMENTE com um JSON válido contendo as chaves: "
            '"categoria", "resumo", "acao_necessaria", "sugestao_resposta", "confianca".\n'
            "Categorias válidas: Estágios, Ofícios, Memorandos, Requerimentos, "
            "Portarias, Informes, Urgente, Correio Lixo, Outros.\n"
            '"confianca" é um número entre 0.0 e 1.0 indicando sua certeza na '
            "classificação e na resposta sugerida (0.0 = muito incerto, 1.0 = totalmente seguro)."
        )
        return [
            {"role": "system", "content": self.system_instruction},
            {"role": "user", "content": user_prompt},
        ]

    # ------------------------------------------------------------------
    # Sync classification
    # ------------------------------------------------------------------

    def classify_email(
        self, email: EmailData, rag_context: str | None = None
    ) -> EmailClassification:
        """Classify and draft a reply for *email* (synchronous)."""
        try:
            response = litellm.completion(
                model=self.model_id,
                messages=self._build_messages(email, rag_context),
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

    async def classify_email_async(
        self, email: EmailData, rag_context: str | None = None
    ) -> EmailClassification:
        """Classify and draft a reply for *email* (asynchronous).

        Uses litellm.acompletion() so multiple emails can be
        classified concurrently via asyncio.gather().

        Raises on failure — partial failure handling in run_pensar_concurrently()
        ensures that individual errors don't break the whole pipeline.
        """
        response = await litellm.acompletion(
            model=self.model_id,
            messages=self._build_messages(email, rag_context),
            temperature=0.2,
        )
        raw = response.choices[0].message.content
        text = self._extract_json(raw)
        adapter = TypeAdapter(EmailClassification)
        return adapter.validate_python(json.loads(text))

    # ------------------------------------------------------------------
    # Self-Refine: generate → critique → refine (Madaan et al., NeurIPS 2023)
    # ------------------------------------------------------------------

    async def self_refine_async(
        self,
        email: EmailData,
        classification: EmailClassification,
        rag_context: str | None = None,
    ) -> EmailClassification:
        """Apply one cycle of self-critique and refinement to a classification.

        1. Critique: evaluate the draft against UFPR-specific criteria
        2. If issues found: refine the draft incorporating the critique
        3. If no issues: return the original classification unchanged

        Args:
            email: The original email that was classified.
            classification: The initial classification to critique.
            rag_context: RAG context used in the initial classification.

        Returns:
            Refined EmailClassification (or original if no issues found).
        """
        # Step 1: Critique
        critique_prompt = (
            "Você é um revisor de correspondência institucional da UFPR. "
            "Analise criticamente o rascunho de resposta abaixo e identifique problemas.\n\n"
            f"E-mail original:\n"
            f"  Remetente: {email.sender}\n"
            f"  Assunto: {email.subject}\n"
            f"  Corpo: {(email.body or email.preview)[:500]}\n\n"
            f"Classificação: {classification.categoria}\n"
            f"Resumo: {classification.resumo}\n"
            f"Ação necessária: {classification.acao_necessaria}\n"
            f"Rascunho de resposta:\n{classification.sugestao_resposta}\n"
        )
        if rag_context:
            critique_prompt += (
                f"\nNormas recuperadas (RAG):\n{rag_context[:1000]}\n"
            )
        critique_prompt += (
            "\nAvalie os seguintes critérios:\n"
            "1. A resposta cita a resolução/norma correta?\n"
            "2. O tom é adequado para correspondência oficial da universidade?\n"
            "3. A classificação da categoria está correta?\n"
            "4. A resposta está completa e atende à demanda do remetente?\n"
            "5. Há erros factuais ou informações incorretas?\n\n"
            "Se NÃO houver problemas, responda exatamente: SEM PROBLEMAS\n"
            "Se houver problemas, liste-os de forma concisa."
        )

        critique_response = await litellm.acompletion(
            model=self.model_id,
            messages=[
                {"role": "system", "content": self.system_instruction},
                {"role": "user", "content": critique_prompt},
            ],
            temperature=0.1,
        )
        critique = critique_response.choices[0].message.content.strip()

        # If no issues found, return original
        if "SEM PROBLEMAS" in critique.upper():
            logger.debug("  Self-Refine: sem problemas detectados para '%s'", email.subject[:40])
            return classification

        logger.info("  Self-Refine: problemas detectados para '%s' — refinando", email.subject[:40])
        logger.debug("  Crítica: %s", critique[:200])

        # Step 2: Refine
        refine_prompt = (
            "Você recebeu a seguinte crítica sobre um rascunho de resposta institucional.\n"
            "Corrija os problemas identificados e gere uma versão melhorada.\n\n"
            f"E-mail original:\n"
            f"  Remetente: {email.sender}\n"
            f"  Assunto: {email.subject}\n"
            f"  Corpo: {(email.body or email.preview)[:500]}\n\n"
            f"Classificação original: {classification.categoria}\n"
            f"Rascunho original:\n{classification.sugestao_resposta}\n\n"
            f"Crítica:\n{critique}\n\n"
        )
        if rag_context:
            refine_prompt += f"Normas recuperadas (RAG):\n{rag_context[:1000]}\n\n"

        refine_prompt += (
            "Responda SOMENTE com um JSON válido contendo as chaves: "
            '"categoria", "resumo", "acao_necessaria", "sugestao_resposta", "confianca".\n'
            "Corrija os problemas apontados na crítica."
        )

        refine_response = await litellm.acompletion(
            model=self.model_id,
            messages=[
                {"role": "system", "content": self.system_instruction},
                {"role": "user", "content": refine_prompt},
            ],
            temperature=0.2,
        )
        raw = refine_response.choices[0].message.content
        text = self._extract_json(raw)
        adapter = TypeAdapter(EmailClassification)
        return adapter.validate_python(json.loads(text))


# Backward-compatible alias
GeminiClient = LLMClient
