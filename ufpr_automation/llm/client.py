"""Client to interact with Gemini 1.5 Pro via Google GenAI SDK."""

import json
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types
from pydantic import TypeAdapter

from ufpr_automation.config import settings
from ufpr_automation.core.models import EmailData, EmailClassification


class GeminiClient:
    """Client for generating email classifications using Gemini."""

    def __init__(self):
        """Initialize the Gemini client using settings."""
        if not settings.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not set in settings or .env!")

        # Initialize the official google-genai client
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
        
        # Handle the model name correctly (nanobot format might be gemini/gemini-1.5-pro)
        self.model_id = settings.LLM_MODEL.replace("gemini/", "", 1) if settings.LLM_MODEL.startswith("gemini/") else settings.LLM_MODEL
        
        # Load system instructions
        self.system_instruction = self._build_system_instruction()

    def _build_system_instruction(self) -> str:
        """Combine AGENTS.md (Persona) and SOUL.md (Norms) into a single system instruction."""
        workspace_dir = settings.PACKAGE_ROOT / "workspace"
        
        # Read AGENTS.md
        agents_file = workspace_dir / "AGENTS.md"
        agents_content = agents_file.read_text(encoding="utf-8") if agents_file.exists() else "Você é um assistente da UFPR."
        
        # Read SOUL.md
        soul_file = workspace_dir / "SOUL.md"
        soul_content = soul_file.read_text(encoding="utf-8") if soul_file.exists() else ""
        
        # Inject the signature template if it exists
        if settings.ASSINATURA_EMAIL:
            soul_content = soul_content.replace("{{ ASSINATURA_EMAIL }}", settings.ASSINATURA_EMAIL)
            
        return f"{agents_content}\n\n=== NORMAS E CONHECIMENTO INSTITUCIONAL ===\n\n{soul_content}"

    def classify_email(self, email: EmailData) -> EmailClassification:
        """Classify an email and suggest a response using Gemini."""
        prompt = (
            f"Por favor, analise o seguinte e-mail recebido na caixa de entrada técnica:\n\n"
            f"Remetente: {email.sender}\n"
            f"Assunto: {email.subject}\n"
            f"Corpo/Preview: {email.preview}\n\n"
            f"Classifique o e-mail preenchendo os campos obrigatórios e sugira uma resposta adequada "
            f"seguindo as normas da UFPR contidas no seu contexto."
        )

        try:
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=self.system_instruction,
                    response_mime_type="application/json",
                    response_schema=EmailClassification,
                    temperature=0.2, # Low temperature for consistent classification
                ),
            )
            
            # The google-genai response.text is guaranteed to match the JSON Schema
            parsed_json = json.loads(response.text)
            
            # Use Pydantic to validate and convert the dict into an EmailClassification object
            adapter = TypeAdapter(EmailClassification)
            classification = adapter.validate_python(parsed_json)
            
            return classification
            
        except Exception as e:
            # Fallback for errors to not break the pipeline
            print(f"⚠️ Erro ao classificar e-mail '{email.subject}' com Gemini: {e}")
            return EmailClassification(
                categoria="Erro",
                resumo=f"Erro na análise LLM: {str(e)}",
                acao_necessaria="Revisão Manual",
                sugestao_resposta=""
            )
