"""Domain models for the UFPR Automation system.

Contains data classes representing the core entities the system works with.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from pydantic import BaseModel, Field


class EmailClassification(BaseModel):
    """Structured output for LLM email classification."""
    
    categoria: str = Field(
        description="Categoria do e-mail (ex: Estágios, Ofícios, Memorandos, Requerimentos, Portarias, Informes, Urgente, Correio Lixo)"
    )
    resumo: str = Field(
        description="Breve resumo (1 a 2 sentenças) do conteúdo e intent principal do e-mail."
    )
    acao_necessaria: str = Field(
        description="Qual a próxima ação a ser tomada (ex: Arquivar, Redigir Resposta, Encaminhar para Secretaria, Solicitar Assinatura)."
    )
    sugestao_resposta: str = Field(
        description="Sugestão de resposta formal redigida em nome do setor para ser enviada, seguindo os templates disponíveis e a assinatura da equipe. Vazio se não for necessário responder."
    )


@dataclass
class EmailData:
    """Represents a single email extracted from the OWA inbox.

    Attributes:
        sender: Name or email address of the sender.
        subject: Email subject line.
        preview: First lines of the email body (preview text).
        is_unread: Whether the email has been read.
        timestamp: When the email was received (if available).
        classification: Output of the LLM analysis.
    """

    sender: str = ""
    subject: str = ""
    preview: str = ""
    is_unread: bool = False
    timestamp: str = ""
    classification: Optional[EmailClassification] = None

    def __str__(self) -> str:
        status = "📩" if self.is_unread else "📧"
        class_str = f" [{self.classification.categoria}]" if self.classification is not None else ""
        return f"{status} [{self.sender}] {self.subject}{class_str}"

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "sender": self.sender,
            "subject": self.subject,
            "preview": self.preview,
            "is_unread": self.is_unread,
            "timestamp": self.timestamp,
            "classification": self.classification.model_dump() if self.classification is not None else None,
        }


