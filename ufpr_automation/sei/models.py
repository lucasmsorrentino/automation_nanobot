"""Domain models for SEI (Sistema Eletronico de Informacoes) integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Despacho types matching SOUL.md section 14
DespachoTipo = Literal["tce_inicial", "aditivo", "rescisao"]


@dataclass
class DocumentoSEI:
    """A document within a SEI process."""

    numero_sei: str = ""
    tipo: str = ""  # TCE, Relatório, Termo Aditivo, Termo de Rescisão, Despacho
    data_inclusao: str = ""
    assinantes: list[str] = field(default_factory=list)


@dataclass
class ProcessoSEI:
    """Represents a SEI process with its metadata and documents."""

    numero: str = ""  # XXXXX.XXXXXX/XXXX-XX
    tipo: str = ""  # Estágio, Memorando, etc.
    interessados: list[str] = field(default_factory=list)
    status: str = ""  # Aberto, Em trâmite, Encerrado
    unidade_atual: str = ""  # Unidade onde o processo está
    documentos: list[DocumentoSEI] = field(default_factory=list)
    ultima_movimentacao: str = ""
    observacoes: str = ""


@dataclass
class DespachoDraft:
    """A draft despacho prepared from SOUL.md templates, NOT yet submitted."""

    tipo: DespachoTipo = "tce_inicial"
    conteudo: str = ""  # Full formatted text of the despacho
    processo_sei: str = ""  # Process number
    campos_pendentes: list[str] = field(default_factory=list)  # Unfilled [BRACKET] fields
    template_usado: str = ""  # Which template section was used
