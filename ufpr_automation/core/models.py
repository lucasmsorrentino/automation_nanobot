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


_VALID_CATEGORIAS: list[str] = list(Categoria.__args__)  # type: ignore[attr-defined]

# Map common LLM free-form outputs (including legacy categories) to valid Categoria values.
# Keys are lowercased, matched via equality then substring.
_CATEGORY_ALIASES: dict[str, str] = {
    # Estágios
    "estagio": "Estágios",
    "estagios": "Estágios",
    "estágio": "Estágios",
    "estágios": "Estágios",
    "termo aditivo": "Estágios",
    "tce": "Estágios",
    "rescisão de estágio": "Estágios",
    "vaga de estágio": "Estágios",
    # Acadêmico / Matrícula
    "matrícula": "Acadêmico / Matrícula",
    "matricula": "Acadêmico / Matrícula",
    "rematrícula": "Acadêmico / Matrícula",
    "rematricula": "Acadêmico / Matrícula",
    "trancamento": "Acadêmico / Matrícula",
    # Acadêmico / Equivalência de Disciplinas
    "equivalência": "Acadêmico / Equivalência de Disciplinas",
    "equivalencia": "Acadêmico / Equivalência de Disciplinas",
    "equivalência de disciplinas": "Acadêmico / Equivalência de Disciplinas",
    # Acadêmico / Aproveitamento de Disciplinas
    "aproveitamento": "Acadêmico / Aproveitamento de Disciplinas",
    "aproveitamento de disciplinas": "Acadêmico / Aproveitamento de Disciplinas",
    "dispensa": "Acadêmico / Aproveitamento de Disciplinas",
    # Acadêmico / Ajuste de Disciplinas
    "ajuste": "Acadêmico / Ajuste de Disciplinas",
    "ajuste de disciplinas": "Acadêmico / Ajuste de Disciplinas",
    "ajuste de matrícula": "Acadêmico / Ajuste de Disciplinas",
    "inclusão de disciplina": "Acadêmico / Ajuste de Disciplinas",
    "exclusão de disciplina": "Acadêmico / Ajuste de Disciplinas",
    # Diplomação / Diploma
    "diploma": "Diplomação / Diploma",
    "diplomação": "Diplomação / Diploma",
    "diplomacao": "Diplomação / Diploma",
    "emissão de diploma": "Diplomação / Diploma",
    "histórico": "Diplomação / Diploma",
    "historico": "Diplomação / Diploma",
    # Diplomação / Colação de Grau
    "colação": "Diplomação / Colação de Grau",
    "colacao": "Diplomação / Colação de Grau",
    "colação de grau": "Diplomação / Colação de Grau",
    "assinatura ata": "Diplomação / Colação de Grau",
    "ata de colação": "Diplomação / Colação de Grau",
    # Extensão
    "extensão": "Extensão",
    "extensao": "Extensão",
    "atividade de extensão": "Extensão",
    "projeto de extensão": "Extensão",
    # Formativas
    "formativas": "Formativas",
    "horas formativas": "Formativas",
    "atividade formativa": "Formativas",
    "atividades formativas": "Formativas",
    # Requerimentos (genérico — fallback legítimo)
    "requerimento": "Requerimentos",
    "requerimentos": "Requerimentos",
    "solicitação": "Requerimentos",
    "solicitacao": "Requerimentos",
    "consulta": "Requerimentos",
    "dúvida": "Requerimentos",
    "duvida": "Requerimentos",
    # Urgente
    "urgente": "Urgente",
    "urgência": "Urgente",
    # Correio Lixo
    "spam": "Correio Lixo",
    "correio lixo": "Correio Lixo",
    "lixo": "Correio Lixo",
    "propaganda": "Correio Lixo",
    "promocional": "Correio Lixo",
    "divulgação": "Correio Lixo",
    "divulgacao": "Correio Lixo",
    # Outros
    "outros": "Outros",
    # === Legacy categories (migration from pre-sub-label taxonomy) ===
    "ofícios": "Outros",
    "oficios": "Outros",
    "ofício": "Outros",
    "oficio": "Outros",
    "memorando": "Outros",
    "memorandos": "Outros",
    "portaria": "Outros",
    "portarias": "Outros",
    "informe": "Outros",
    "informes": "Outros",
    "informativo": "Outros",
    "processo": "Outros",
    "coordenação": "Outros",
    "coordenacao": "Outros",
}


def normalize_categoria(raw: str) -> str:
    """Normalize a free-form category string to a valid ``Categoria`` literal.

    Resolution order:
    1. Exact match (case-insensitive).
    2. Alias map (lowercased, equality).
    3. Substring match against alias keys.
    4. Fallback to ``"Outros"``.
    """
    stripped = (raw or "").strip()
    for valid in _VALID_CATEGORIAS:
        if stripped.lower() == valid.lower():
            return valid
    key = stripped.lower()
    if key in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[key]
    for alias, mapped in _CATEGORY_ALIASES.items():
        if alias in key:
            return mapped
    return "Outros"


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
    gmail_msg_id: str = ""  # IMAP UID for mark_read / fetch
    gmail_message_id: str = ""  # RFC Message-ID header for threading
    # Attachments
    attachments: list[AttachmentData] = field(default_factory=list)
    has_attachments: bool = False
    # True when the most recent message in this Gmail thread was sent by the
    # human coordinator (see ``INSTITUTIONAL_EMAIL`` in settings). Set by
    # ``perceber_gmail``; consumed downstream to skip drafting and to route
    # the thread into the learning corpus label.
    already_replied_by_us: bool = False
    thread_id: str = ""

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
            "classification": self.classification.model_dump()
            if self.classification is not None
            else None,
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
            "already_replied_by_us": self.already_replied_by_us,
            "thread_id": self.thread_id,
        }
