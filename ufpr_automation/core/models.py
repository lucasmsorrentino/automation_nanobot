"""Domain models for the UFPR Automation system.

Contains data classes representing the core entities the system works with.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal, Optional

from pydantic import BaseModel, Field

# Valid email categories — used as a Literal type to constrain LLM output.
# Hierarchical labels use " / " as separator (e.g. "Acadêmico / Matrícula").
Categoria = Literal[
    "Estágios",
    "Acadêmico / Matrícula",
    "Acadêmico / Equivalência de Disciplinas",
    "Acadêmico / Aproveitamento de Disciplinas",
    "Acadêmico / Ajuste de Disciplinas",
    "Diplomação / Diploma",
    "Diplomação / Colação de Grau",
    "Extensão",
    "Formativas",
    "Requerimentos",
    "Urgente",
    "Correio Lixo",
    "Outros",
]


class EmailClassification(BaseModel):
    """Structured output for LLM email classification."""

    categoria: Categoria = Field(
        description=(
            "Categoria do e-mail (use exatamente um destes valores, com acentos e barras): "
            "Estágios, Acadêmico / Matrícula, Acadêmico / Equivalência de Disciplinas, "
            "Acadêmico / Aproveitamento de Disciplinas, Acadêmico / Ajuste de Disciplinas, "
            "Diplomação / Diploma, Diplomação / Colação de Grau, Extensão, Formativas, "
            "Requerimentos, Urgente, Correio Lixo, Outros."
        )
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
    confianca: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Nível de confiança na classificação e resposta (0.0 = baixa, 1.0 = alta). "
                    "Considere: clareza da demanda, certeza da regulamentação aplicável, "
                    "e adequação da resposta sugerida.",
    )


@dataclass
class AttachmentData:
    """Represents a single email attachment.

    Attributes:
        filename: Original filename of the attachment.
        mime_type: MIME type (e.g. application/pdf, image/jpeg).
        size_bytes: File size in bytes.
        local_path: Path where the file was saved locally after download.
        extracted_text: Text content extracted from the attachment.
        needs_ocr: True if text extraction failed (scanned PDF, image).
    """

    filename: str = ""
    mime_type: str = ""
    size_bytes: int = 0
    local_path: str = ""
    extracted_text: str = ""
    needs_ocr: bool = False


@dataclass
class EmailData:
    """Represents a single email extracted from the OWA inbox.

    Attributes:
        sender: Name or email address of the sender.
        subject: Email subject line.
        preview: First lines of the email body (preview text).
        body: Full email body text, populated by PerceberAgent after clicking into the email.
        email_index: Position in the inbox list (fallback for clicking).
        is_unread: Whether the email has been read.
        timestamp: When the email was received (if available).
        stable_id: Hash of sender+subject+timestamp for identity verification.
        classification: Output of the LLM analysis (populated by PensarAgent).
    """

    sender: str = ""
    subject: str = ""
    preview: str = ""
    body: str = ""
    email_index: int = -1
    is_unread: bool = False
    timestamp: str = ""
    stable_id: str = ""
    classification: Optional[EmailClassification] = None
    # Gmail-specific fields (populated when using Gmail channel)
    gmail_msg_id: str = ""         # IMAP UID for mark_read / fetch
    gmail_message_id: str = ""     # RFC Message-ID header for threading
    # Attachments
    attachments: list[AttachmentData] = field(default_factory=list)
    has_attachments: bool = False

    def compute_stable_id(self) -> str:
        """Generate a stable hash from sender + subject + timestamp.

        This replaces positional index as the primary email identifier,
        making the system resilient to inbox changes between pipeline phases.
        """
        key = f"{self.sender}|{self.subject}|{self.timestamp}"
        self.stable_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        return self.stable_id

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
            "body": self.body,
            "email_index": self.email_index,
            "is_unread": self.is_unread,
            "timestamp": self.timestamp,
            "stable_id": self.stable_id,
            "classification": self.classification.model_dump() if self.classification is not None else None,
            "has_attachments": self.has_attachments,
            "attachments": [
                {
                    "filename": a.filename,
                    "mime_type": a.mime_type,
                    "size_bytes": a.size_bytes,
                    "needs_ocr": a.needs_ocr,
                }
                for a in self.attachments
            ],
        }


