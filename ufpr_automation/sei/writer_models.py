"""Result models and input dataclasses for SEIWriter operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SEIDocClassification:
    """How a document should be classified when attached to SEI.

    Mirrors the SEI "Incluir Documento" form hierarchy:

        sei_tipo        → "Externo" (uploaded file) or "Despacho" (native)
        sei_subtipo     → "Termo" | "Relatório" (only for Externo)
        sei_classificacao → "Inicial" | "Aditivo" | "Rescisão" | "Parcial" | "Final"
        sigiloso        → True for all student-identifying docs (LGPD)
        motivo_sigilo   → SEI "Hipótese Legal" dropdown value
        data_documento  → ISO YYYY-MM-DD or "" (empty = today)

    Populated by looking up the semantic label in
    ``workspace/SEI_DOC_CATALOG.yaml`` (see ``get_doc_classification``).
    """

    sei_tipo: str  # "Externo" | "Despacho"
    sei_subtipo: str = ""
    sei_classificacao: str = ""
    sigiloso: bool = True
    motivo_sigilo: str = "Informação Pessoal"
    data_documento: str = ""  # "" = today


@dataclass
class AttachResult:
    """Result of attaching a document to a SEI process."""

    success: bool
    processo_id: str
    file_path: Path
    classification: SEIDocClassification | None = None
    artifacts: list[Path] = field(default_factory=list)
    error: str | None = None
    dry_run: bool = False


@dataclass
class DraftResult:
    """Result of saving a despacho draft to a SEI process."""

    success: bool
    processo_id: str
    tipo: str
    artifacts: list[Path] = field(default_factory=list)
    error: str | None = None
    dry_run: bool = False


@dataclass
class AcompanhamentoEspecialResult:
    """Result of adding a SEI process to an Acompanhamento Especial group.

    POP-38. ``grupo`` is the free-text group name (e.g. ``"Estágio não
    obrigatório"``). In Marco IV this is persisted as dry_run only —
    live flow is blocked on a fresh selector capture (see
    ``sei/SELECTOR_AUDIT.md §1``).
    """

    success: bool
    processo_id: str
    grupo: str
    observacao: str = ""
    artifacts: list[Path] = field(default_factory=list)
    error: str | None = None
    dry_run: bool = False


@dataclass
class CreateProcessResult:
    """Result of initiating a new SEI process.

    ``processo_id`` is populated on success with the SEI-assigned process
    number (format XXXXX.XXXXXX/YYYY-ZZ) so downstream attachments can be
    routed to the newly created process.
    """

    success: bool
    tipo_processo: str
    especificacao: str
    interessado: str
    processo_id: str = ""  # populated on success
    artifacts: list[Path] = field(default_factory=list)
    error: str | None = None
    dry_run: bool = False
