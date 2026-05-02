"""Tier 0 playbook parser and intent router (Hybrid Memory).

Loads ``workspace/PROCEDURES.md`` into a list of :class:`Intent` objects,
precomputes intent embeddings, and exposes :meth:`Playbook.lookup` which
returns the best matching intent for an email (or ``None`` for Tier 1
fallback).

The routing scoring is:

- **Keyword match** — any keyword found in the query by regex boundary
  search returns ``score=1.0`` (method="keyword").
- **Semantic match** — cosine similarity of a normalized e5-large
  embedding of ``intent_name + keywords`` against the query. Above
  ``semantic_threshold`` (default 0.90) returns ``method="semantic"``.
- Below threshold → ``None`` → Tier 1 (RAG + LLM).

Staleness: :meth:`Playbook.is_stale` compares ``intent.last_update`` with
the mtime of the RAG vector store. If the store has been re-ingested more
recently than the intent was last reviewed, the intent is considered stale
and routing falls back to Tier 1.

Usage::

    from ufpr_automation.procedures.playbook import get_playbook

    pb = get_playbook()
    match = pb.lookup("Gostaria de prorrogar meu estágio na X")
    if match and not pb.is_stale(match.intent):
        draft = pb.fill_template(match.intent, variables={"nome_aluno": "João"})
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field, field_validator

from ufpr_automation.config import settings
from ufpr_automation.core.models import EmailData
from ufpr_automation.utils.logging import logger

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Override via env var so deployments can share a playbook across machines.
PROCEDURES_MD_PATH = Path(
    os.getenv("PROCEDURES_MD_PATH", str(settings.PACKAGE_ROOT / "workspace" / "PROCEDURES.md"))
)

# Used by is_stale(): mtime of this file is treated as "latest RAG update".
RAG_STORE_FILE = settings.RAG_STORE_DIR / "ufpr.lance"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class Intent(BaseModel):
    """A single Tier 0 playbook entry.

    Beyond the classification fields (``categoria``, ``action``) an intent
    may also describe an SEI workflow step. Fields with the ``sei_`` /
    ``required_attachments`` / ``blocking_checks`` / ``despacho_template``
    prefixes are consumed by the ``agir_estagios`` node and the completeness
    checker; legacy intents that only produce an email reply leave them
    empty and continue to work unchanged.
    """

    intent_name: str
    keywords: list[str] = Field(default_factory=list)
    categoria: str
    action: str = "Redigir Resposta"
    required_fields: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    last_update: str = ""  # ISO date (YYYY-MM-DD)
    confidence: float = 0.90
    template: str = ""

    # --- SEI workflow fields (optional; empty/"none" = email-only intent) ---
    sei_action: Literal["none", "create_process", "append_to_existing"] = "none"
    sei_process_type: str = ""
    required_attachments: list[str] = Field(default_factory=list)
    blocking_checks: list[str] = Field(default_factory=list)
    despacho_template: str = ""

    # Fields that regex can't extract (free text). When declared, extract_variables
    # fires a bounded LLM call (no RAG) per missing field using the cheap CLASSIFY
    # model. Keeps the intent in Tier 0 (zero RAG) while relaxing the "zero LLM"
    # constraint for fields that genuinely need semantic parsing.
    llm_extraction_fields: list[str] = Field(default_factory=list)

    @field_validator("intent_name")
    @classmethod
    def _non_empty_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("intent_name must be non-empty")
        return v.strip()

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence must be in [0.0, 1.0]")
        return v

    def last_update_date(self) -> Optional[date]:
        """Parse ``last_update`` as a date (or ``None`` if absent/invalid)."""
        if not self.last_update:
            return None
        try:
            return datetime.strptime(self.last_update.strip(), "%Y-%m-%d").date()
        except ValueError:
            return None


@dataclass
class PlaybookMatch:
    """Result of :meth:`Playbook.lookup`."""

    intent: Intent
    score: float
    method: str  # "keyword" or "semantic"
    # Optional: keywords that actually matched (for explainability)
    matched_keywords: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parser — extracts ```intent``` / ```yaml``` blocks from a markdown file
# ---------------------------------------------------------------------------

# Match fenced blocks tagged ``intent`` (preferred) or ``yaml``.
_INTENT_BLOCK_RE = re.compile(
    r"^```(?:intent|yaml)\s*\n(.*?)^```",
    re.DOTALL | re.MULTILINE,
)


def parse_procedures_md(path: Path) -> list[Intent]:
    """Parse a PROCEDURES.md file into a list of :class:`Intent`.

    Fenced code blocks with the tag ``intent`` (or ``yaml`` for flexibility)
    are extracted and loaded via PyYAML. Blocks that fail validation are
    logged and skipped so a single malformed entry does not break the entire
    playbook.
    """
    if not path.exists():
        logger.warning("Playbook: %s nao encontrado", path)
        return []

    text = path.read_text(encoding="utf-8")
    intents: list[Intent] = []

    for match in _INTENT_BLOCK_RE.finditer(text):
        block = match.group(1)
        try:
            data = yaml.safe_load(block)
        except yaml.YAMLError as e:
            logger.warning("Playbook: YAML invalido num bloco: %s", e)
            continue
        if not isinstance(data, dict):
            logger.debug("Playbook: bloco ignorado (nao e mapping)")
            continue
        try:
            intents.append(Intent.model_validate(data))
        except Exception as e:
            name = data.get("intent_name", "<sem nome>") if isinstance(data, dict) else "?"
            logger.warning("Playbook: intent '%s' invalido: %s", name, e)

    # Check for duplicate intent names — last one wins but we warn
    seen: dict[str, int] = {}
    for i, intent in enumerate(intents):
        if intent.intent_name in seen:
            logger.warning(
                "Playbook: intent duplicado '%s' (posicoes %d e %d)",
                intent.intent_name,
                seen[intent.intent_name],
                i,
            )
        seen[intent.intent_name] = i

    return intents


# ---------------------------------------------------------------------------
# Variable extraction — regex-based, best-effort
# ---------------------------------------------------------------------------


def _extract_sender_name(sender: str) -> str:
    """Extract a human-readable name from an RFC-2822 ``From:`` value.

    Examples::

        "João Silva <joao@ufpr.br>" -> "João Silva"
        "joao@ufpr.br"              -> "joao"
        "<joao@ufpr.br>"            -> "joao"
    """
    if not sender:
        return ""
    sender = sender.strip()
    # "Name <addr>" form
    m = re.match(r"^\s*([^<]+?)\s*<[^>]+>\s*$", sender)
    if m:
        name = m.group(1).strip().strip('"')
        if name:
            return name
    # Bare address — use local part before @
    m = re.match(r"^\s*<?([^@<>]+)@", sender)
    if m:
        return m.group(1)
    return sender


_FORWARD_MARKER_RE = re.compile(
    r"(?:----*\s*Forwarded\s+message\s*----*"
    r"|----*\s*Mensagem\s+encaminhada\s*----*"
    r"|----*\s*Mensagem\s+[Oo]riginal\s*----*)",
    re.IGNORECASE,
)
_FORWARD_ORIGINAL_FROM_RE = re.compile(
    r"(?:^|\n)\s*(?:De|From):\s*([^<\n]+?)\s*<",
    re.IGNORECASE,
)


def _extract_forwarded_original_sender(body: str) -> str:
    """Return the name of the ORIGINAL sender when ``body`` is a forward.

    Gmail/Outlook/Thunderbird all wrap forwarded content in a header block
    like ``---------- Forwarded message ---------`` / ``Mensagem encaminhada``
    followed by ``De: Nome <addr>`` (or ``From:``). When a professor/staffer
    forwards a student's TCE, the outer ``From:`` is the forwarder and
    extracting ``nome_aluno`` from it misattributes the student — the intent
    template then addresses the wrong person ("estudante Stephania Padovani"
    when the real student is Alanis). Prefer the inner sender in that case.

    Returns empty string when no forward marker exists or no inner ``De:/From:``
    line is found. Conservative — falls through to normal extraction.
    """
    if not body:
        return ""
    marker = _FORWARD_MARKER_RE.search(body)
    if not marker:
        return ""
    # Only scan the text AFTER the forward marker; the forwarder's own sig
    # before the marker should not match.
    after = body[marker.end():]
    m = _FORWARD_ORIGINAL_FROM_RE.search(after)
    if not m:
        return ""
    name = m.group(1).strip().strip('"').strip("'").rstrip(".,;")
    if len(name) < 3 or "@" in name:
        return ""
    # lower-case single-word senders like "alanis lima" look funny in "Prezado
    # alanis lima,"; normalize to Title Case. Multi-word with caps already
    # (e.g. "Alanis Rocha Lima") passes through unchanged.
    if name.islower() or name.isupper():
        name = " ".join(w.capitalize() for w in name.split())
    return name


_TCE_RE = re.compile(
    r"(?:TCE|Termo\s+de\s+Compromisso(?:\s+de\s+Est[áa]gio)?)"
    r"\s*(?:n[º°o]\.?|num\.?|nr?\.?)?\s*[:\-]?\s*(\d{2,6}(?:[/\-]\d{2,6})?)",
    re.IGNORECASE,
)
_SEI_RE = re.compile(r"\b(\d{5}\.\d{6}/\d{4}-\d{2})\b")
# Matches "GRR20244602", "GRR: 20244602", "GRR-20244602", "GRR 20244602" and
# also "Matrícula 20244602" / "matricula: 20244602" (alternative label seen in
# TCE PDFs and casual emails). The 6-10 digit window keeps it strict enough to
# avoid catching arbitrary numbers like CPF/RG fragments.
_GRR_RE = re.compile(
    r"(?:\bGRR\s*[:\-]?\s*|\bMatr[ií]cula\s*[:\-]?\s*)(\d{6,10})\b",
    re.IGNORECASE,
)
from ufpr_automation.utils.dates import (
    DATE_EXTENSO_RE as _DATE_EXTENSO_RE,
    DATE_RE as _DATE_RE,
    MESES_PT as _MESES_PT,
    parse_br_date_to_str as _parse_br_date,
)

# TCE-specific regex — operate on attachment text (PDFs digitalized into the email)
# TCE PDFs use various labels for the company: "Concedente:", "Empresa:",
# "Razão Social:" (CIEE template), "Organização:", "Instituição:".
_CONCEDENTE_RE = re.compile(
    r"(?:Concedente|CONCEDENTE|Empresa|Parte\s+Concedente|Raz[ãa]o\s+Social"
    r"|Organiza[çc][ãa]o|Institui[çc][ãa]o)"
    r"\s*[:\-]?\s*([^\n\r]{5,120})",
    re.IGNORECASE,
)
_PERIODO_RE = re.compile(
    r"(?:per[ií]odo|vig[êe]ncia|in[íi]cio)[^\n]{0,50}?(\d{2}/\d{2}/\d{4})"
    r"[^\n]{0,30}?(?:a|at[ée]|t[ée]rmino)[^\n]{0,30}?(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)
_JORNADA_DIARIA_RE = re.compile(
    r"(\d{1,2}(?:[.,]\d)?)\s*(?:horas?|h)\s*(?:di[áa]rias?|por\s*dia|ao\s*dia)",
    re.IGNORECASE,
)
_JORNADA_SEMANAL_RE = re.compile(
    r"(\d{1,2}(?:[.,]\d)?)\s*(?:horas?|h)\s*(?:semanais?|por\s*semana)",
    re.IGNORECASE,
)
_HORARIO_RE = re.compile(
    r"(\d{1,2})\s*[:h](\d{2})?\s*(?:às|as|até|-|–)\s*(\d{1,2})\s*[:h](\d{2})?",
    re.IGNORECASE,
)

# Supervisor-specific regex — operate on TCE attachment text. Require an
# explicit ':' after the label so we don't match the same word in running
# prose. TCE CIEE typical layout: "SUPERVISOR: CAMILA DOS SANTOS KLIDZIO\n
# TEL: ...\nFORMAÇÃO: BACHAREL EM ADMINISTRAÇÃO DE EMPRESAS". Validated
# 2026-04-22 against Marlon's TCE (GRR20223876).
_SUPERVISOR_NOME_RE = re.compile(
    r"\bSupervisor(?:\s*\(?\s*a\s*\)?)?(?:\s+no\s+local\s+de\s+est[aá]gio)?"
    r"\s*:\s*([A-ZÁÉÍÓÚÂÊÎÔÛÀÃÕÇ][A-ZÁÉÍÓÚÂÊÎÔÛÀÃÕÇa-záéíóúâêîôûàãõç\s\.]{4,80}?)"
    r"(?=\s*(?:\n|TEL|Forma[çc][aã]o|Cargo|Gradua[çc][aã]o|CPF|RG|Matr[ií]cula|$))",
    re.IGNORECASE,
)
_SUPERVISOR_FORMACAO_RE = re.compile(
    r"\b(?:Forma[çc][aã]o(?:\s+do\s+Supervisor)?|Gradua[çc][aã]o(?:\s+do\s+Supervisor)?"
    r"|Cargo(?:\s+do\s+Supervisor)?|Profiss[aã]o)"
    r"\s*:\s*([A-ZÁÉÍÓÚÂÊÎÔÛÀÃÕÇa-záéíóúâêîôûàãõç][^\n\r]{3,100}?)"
    r"(?=\s*(?:\n|CPF|RG|Matr[ií]cula|CREA|CAU|E-?mail|$))",
    re.IGNORECASE,
)

# Aditivo-specific regex — operate on attachment text (PDF do Termo Aditivo).
# Matches "Termo Aditivo nº 1", "ADITIVO Nº 02", "Aditivo 3".
# The negative lookahead `(?!\s+AO\s)` prevents capturing the TCE number in
# "ADITIVO AO TERMO DE COMPROMISSO Nº 12345" — in that phrasing the aditivo
# itself has no number yet, so we fall through and let _TCE_RE grab the 12345.
_ADITIVO_RE = re.compile(
    r"(?:TERMO\s+)?ADITIVO(?!\s+AO\s)"
    r"\s*(?:n[º°o]\.?|num\.?|nr?\.?)?\s*[:\-]?\s*"
    r"(\d{1,4}(?:[/\-]\d{2,6})?)",
    re.IGNORECASE,
)

# Matches phrases that introduce the *new* end date in an aditivo — e.g.
# "nova vigência até DD/MM/YYYY", "fica prorrogado até 30 de junho de 2026".
# The capture is a raw date string that must be normalized via _parse_br_date.
_DATA_TERMINO_NOVO_RE = re.compile(
    r"(?:nova\s+vig[êe]ncia"
    r"|prorroga(?:[çc][ãa]o|do|da|r|-se)"
    r"|fica\s+prorrogad[oa]"
    r"|novo\s+t[ée]rmino"
    r"|nova\s+data\s+(?:de\s+)?t[ée]rmino"
    r"|nova\s+data\s+final)"
    r"[^\n]{0,80}?"
    r"(\d{1,2}/\d{1,2}/\d{4}|\d{1,2}\s+de\s+\w+\s+de\s+\d{4})",
    re.IGNORECASE,
)


# LLM extraction prompts per field. Each prompt must instruct the model to
# return either the extracted value verbatim (no explanation) or the literal
# string "NONE" when the field cannot be found. Keeps parsing trivial.
_LLM_FIELD_EXTRACTORS: dict[str, str] = {
    "lista_pendencias": (
        "Liste as pendências/problemas citados no email (ex: 'falta assinatura "
        "da concedente', 'CPF ausente', 'plano de atividades não anexado'). "
        "Uma por linha, cada uma prefixada com '- '. Se não houver pendências "
        "mencionadas, responda exatamente NONE."
    ),
}


def _llm_extract_fields(email: EmailData, fields: list[str]) -> dict[str, str]:
    """Best-effort LLM extraction for fields regex couldn't populate.

    Fires one bounded call per field against the cheap CLASSIFY model (no RAG,
    no Self-Refine). Failures are swallowed — the field simply stays absent,
    and the caller falls back to Tier 1 via :func:`missing_required_fields`.
    """
    if not fields:
        return {}

    # Lazy import so `procedures/playbook.py` import-time cost stays flat for
    # intents that don't declare llm_extraction_fields.
    from ufpr_automation.llm.router import TaskType, cascaded_completion_sync

    out: dict[str, str] = {}
    body = email.body or email.preview or ""
    user_prefix = f"Assunto: {email.subject}\n\n{body}"

    for field in fields:
        instruction = _LLM_FIELD_EXTRACTORS.get(field)
        if not instruction:
            continue
        try:
            response = cascaded_completion_sync(
                TaskType.CLASSIFY,
                messages=[
                    {
                        "role": "system",
                        "content": "Você extrai campos de emails. Responda apenas com o valor pedido.",
                    },
                    {"role": "user", "content": f"{instruction}\n\n---\n{user_prefix}"},
                ],
                temperature=0.0,
            )
            content = (response.choices[0].message.content or "").strip()
        except Exception as e:
            logger.warning("Tier 0 LLM extraction falhou (%s): %s", field, e)
            continue
        if content and content.strip().upper() != "NONE":
            out[field] = content

    return out


def _attachments_text(email: EmailData) -> str:
    """Concatenate extracted text from all attachments.

    Used by TCE/Aditivo intents that need to pull dates, concedente name,
    and jornada from the actual document rather than the email body.
    """
    parts: list[str] = []
    for att in getattr(email, "attachments", None) or []:
        text = getattr(att, "extracted_text", "") or ""
        if text:
            parts.append(text)
    return "\n".join(parts)


def extract_variables(email: EmailData, intent: Intent) -> dict[str, str]:
    """Best-effort variable extraction from an email for a Tier 0 intent.

    Returns a dict of ``{field_name: value}``. Missing fields are simply
    absent from the dict — the caller decides whether to fall back to
    Tier 1 via :func:`missing_required_fields`.

    Fields handled:
        - nome_aluno               (from sender header)
        - nome_aluno_maiusculas    (uppercase variant for despacho templates)
        - assinatura_email         (from settings.ASSINATURA_EMAIL)
        - numero_tce               (regex in subject+body+attachments)
        - numero_processo_sei      (idem)
        - grr                      (idem)
        - data_inicio / data_fim   (first/last date found in body OR attachments)
        - nome_concedente          (TCE attachment text)
        - nome_concedente_maiusculas (uppercase variant for despacho templates)
        - horas_diarias            (TCE attachment text)
        - horas_semanais           (TCE attachment text)
        - jornada_horario_inicio   (TCE attachment text; HH:MM)
        - numero_aditivo           (Termo Aditivo PDF)
        - data_termino_novo        (new end date, normalized DD/MM/YYYY)
    """
    vars: dict[str, str] = {}

    # For forwarded emails (prof/staff forwarding a student's TCE), the outer
    # `From:` is the forwarder — prefer the inner `De:/From:` from the forward
    # block so `nome_aluno` points at the actual student. Falls back to the
    # outer sender when the body has no forward markers.
    original_body = email.body or email.preview
    forwarded_name = _extract_forwarded_original_sender(original_body)
    sender_name = forwarded_name or _extract_sender_name(email.sender)
    if sender_name:
        vars["nome_aluno"] = sender_name
        vars["nome_aluno_maiusculas"] = sender_name.upper()

    if settings.ASSINATURA_EMAIL:
        vars["assinatura_email"] = settings.ASSINATURA_EMAIL

    body_text = f"{email.subject}\n{email.body or email.preview}"
    attach_text = _attachments_text(email)
    # Search body first, then fall back to attachment text — email body
    # wins when both exist so student edits override TCE PDF boilerplate.
    combined = f"{body_text}\n{attach_text}"

    m = _TCE_RE.search(combined)
    if m:
        vars["numero_tce"] = m.group(1)

    m = _SEI_RE.search(combined)
    if m:
        vars["numero_processo_sei"] = m.group(1)

    m = _GRR_RE.search(combined)
    if m:
        vars["grr"] = m.group(1)

    # Prefer "período DD/MM/YYYY a DD/MM/YYYY" from the TCE text; otherwise
    # fall back to first/last bare date in the combined text.
    m = _PERIODO_RE.search(attach_text) or _PERIODO_RE.search(body_text)
    if m:
        vars["data_inicio"] = m.group(1)
        vars["data_fim"] = m.group(2)
        vars.setdefault("data_termino", m.group(2))  # legacy alias
    else:
        dates = _DATE_RE.findall(combined)
        if dates:
            vars.setdefault("data_inicio", dates[0])
            if len(dates) >= 2:
                vars.setdefault("data_fim", dates[-1])
                vars.setdefault("data_termino", dates[-1])

    # Attachment-only fields (TCE body boilerplate)
    if attach_text:
        m = _CONCEDENTE_RE.search(attach_text)
        if m:
            concedente = m.group(1).strip().rstrip(".;,")
            vars["nome_concedente"] = concedente
            vars["nome_concedente_maiusculas"] = concedente.upper()

        m = _JORNADA_DIARIA_RE.search(attach_text)
        if m:
            vars["horas_diarias"] = m.group(1).replace(",", ".")

        m = _JORNADA_SEMANAL_RE.search(attach_text)
        if m:
            vars["horas_semanais"] = m.group(1).replace(",", ".")

        m = _HORARIO_RE.search(attach_text)
        if m:
            hh = int(m.group(1))
            mm = int(m.group(2) or 0)
            vars["jornada_horario_inicio"] = f"{hh:02d}:{mm:02d}"

        m = _SUPERVISOR_NOME_RE.search(attach_text)
        if m:
            vars["nome_supervisor"] = " ".join(m.group(1).split()).strip().rstrip(".,;")

        m = _SUPERVISOR_FORMACAO_RE.search(attach_text)
        if m:
            vars["formacao_supervisor"] = " ".join(m.group(1).split()).strip().rstrip(".,;")

    # Aditivo fields — numero_aditivo and data_termino_novo appear in the
    # Termo Aditivo PDF, sometimes echoed in the email body. Body wins when
    # present (student edits override PDF boilerplate).
    m = _ADITIVO_RE.search(combined)
    if m:
        vars["numero_aditivo"] = m.group(1)

    m = _DATA_TERMINO_NOVO_RE.search(attach_text) or _DATA_TERMINO_NOVO_RE.search(body_text)
    if m:
        normalized = _parse_br_date(m.group(1))
        if normalized:
            vars["data_termino_novo"] = normalized

    # Tier 0 LLM extraction pass — only for fields the intent explicitly
    # declared as requiring LLM parsing (free text that no regex covers).
    # Runs only on what regex missed; stays within Tier 0 (no RAG).
    pending_llm = [f for f in intent.llm_extraction_fields if f not in vars]
    if pending_llm:
        vars.update(_llm_extract_fields(email, pending_llm))

    # Debug trace — boolean snapshot of the critical fields per intent. Lets
    # post-mortem auditing answer "did extract_variables actually find grr
    # in this email?" without re-running the pipeline.
    logger.debug(
        "extract_variables[%s]: %d field(s) extracted "
        "(grr=%s, nome_aluno=%s, nome_concedente=%s, data_inicio=%s, data_fim=%s, "
        "numero_tce=%s, numero_aditivo=%s)",
        intent.intent_name,
        len(vars),
        bool(vars.get("grr")),
        bool(vars.get("nome_aluno")),
        bool(vars.get("nome_concedente")),
        bool(vars.get("data_inicio")),
        bool(vars.get("data_fim")),
        bool(vars.get("numero_tce")),
        bool(vars.get("numero_aditivo")),
    )

    return vars


def missing_required_fields(intent: Intent, vars: dict[str, str]) -> list[str]:
    """Return the list of required fields for which no value is present."""
    return [f for f in intent.required_fields if not vars.get(f)]


# ---------------------------------------------------------------------------
# Template filling
# ---------------------------------------------------------------------------


_PLACEHOLDER_RE = re.compile(r"\[([A-Z_][A-Z0-9_]*)\]")
_JINJA_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def fill_template(template: str, vars: dict[str, str]) -> str:
    """Substitute ``[UPPER_CASE]`` and ``{{ lower_case }}`` placeholders.

    The two placeholder conventions coexist so SOUL.md's existing
    ``{{ assinatura_email }}`` style works alongside the ``[NOME_ALUNO]``
    bracket style used elsewhere. Unknown placeholders are left untouched
    so a human reviewer can spot them.
    """
    if not template:
        return ""

    # Normalize keys so both UPPER and lower are resolvable from either form.
    lower_vars = {k.lower(): v for k, v in vars.items()}

    def _upper_sub(m: re.Match[str]) -> str:
        key = m.group(1).lower()
        return lower_vars.get(key, m.group(0))

    def _jinja_sub(m: re.Match[str]) -> str:
        key = m.group(1).lower()
        return lower_vars.get(key, m.group(0))

    result = _PLACEHOLDER_RE.sub(_upper_sub, template)
    result = _JINJA_VAR_RE.sub(_jinja_sub, result)
    return result


# ---------------------------------------------------------------------------
# Playbook — lookup with caching
# ---------------------------------------------------------------------------


class Playbook:
    """Tier 0 intent router with lazy-loaded embeddings.

    The embedding model is only loaded on the first semantic lookup, so
    tests that exercise keyword matching do not pay the model load cost.
    """

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        embedding_model: str = "intfloat/multilingual-e5-large",
        semantic_threshold: float = 0.90,
    ):
        self._path = path or PROCEDURES_MD_PATH
        self._embedding_model_name = embedding_model
        self._semantic_threshold = semantic_threshold

        self._intents: list[Intent] = []
        self._parsed = False

        self._model = None
        self._embeddings = None  # numpy.ndarray | None

    # -- parsing ---------------------------------------------------------

    def _ensure_parsed(self) -> None:
        if self._parsed:
            return
        self._intents = parse_procedures_md(self._path)
        self._parsed = True
        logger.info("Playbook: %d intent(s) carregado(s) de %s", len(self._intents), self._path)

    @property
    def intents(self) -> list[Intent]:
        self._ensure_parsed()
        return list(self._intents)

    def get(self, intent_name: str) -> Optional[Intent]:
        self._ensure_parsed()
        for intent in self._intents:
            if intent.intent_name == intent_name:
                return intent
        return None

    # -- embeddings ------------------------------------------------------

    def _ensure_embeddings(self) -> bool:
        """Lazy-load sentence-transformers + precompute intent embeddings.

        Returns True on success, False if the model / deps are unavailable.
        In that case the playbook still works in keyword-only mode.
        """
        self._ensure_parsed()
        if self._embeddings is not None:
            return True
        if not self._intents:
            return False

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            logger.info("Playbook: sentence-transformers indisponivel — modo keyword-only")
            return False

        try:
            self._model = SentenceTransformer(self._embedding_model_name)
        except Exception as e:  # pragma: no cover - network/cache failures
            logger.warning("Playbook: falha ao carregar %s: %s", self._embedding_model_name, e)
            return False

        import numpy as np

        texts = [self._intent_to_passage(i) for i in self._intents]
        embs = self._model.encode(texts, normalize_embeddings=True)
        self._embeddings = np.asarray(embs, dtype="float32")
        logger.info("Playbook: %d embedding(s) precomputado(s)", len(self._intents))
        return True

    @staticmethod
    def _intent_to_passage(intent: Intent) -> str:
        """Build the passage text that represents an intent in embedding space."""
        kw = ", ".join(intent.keywords)
        return f"passage: {intent.intent_name}. {kw}. {intent.categoria}."

    # -- lookup ----------------------------------------------------------

    def lookup(self, query: str) -> Optional[PlaybookMatch]:
        """Route *query* to a Tier 0 intent, or return ``None`` for Tier 1.

        Args:
            query: Raw text (typically ``subject + new_reply``).

        Returns:
            :class:`PlaybookMatch` on success, ``None`` if no keyword hit
            and the best semantic score is below the threshold.
        """
        self._ensure_parsed()
        if not self._intents or not query or not query.strip():
            return None

        # Tier 0.1 — keyword match (cost zero)
        kw_match = self._keyword_match(query)
        if kw_match is not None:
            return kw_match

        # Tier 0.2 — semantic match (precomputed embeddings → one query encode)
        if not self._ensure_embeddings():
            return None

        import numpy as np

        query_vec = self._model.encode(f"query: {query}", normalize_embeddings=True)
        query_vec = np.asarray(query_vec, dtype="float32")
        sims = self._embeddings @ query_vec  # cosine since both are L2-normalized
        best_idx = int(np.argmax(sims))
        best_score = float(sims[best_idx])

        if best_score > self._semantic_threshold:
            return PlaybookMatch(
                intent=self._intents[best_idx],
                score=best_score,
                method="semantic",
            )
        return None

    def best_semantic_score(self, query: str) -> float:
        """Return the best semantic similarity score regardless of threshold.

        Useful for ablations / diagnostics that need to know *how close* a
        query came to a Tier 0 match even when below the routing threshold.
        Returns 0.0 if embeddings unavailable or query empty.
        """
        self._ensure_parsed()
        if not self._intents or not query or not query.strip():
            return 0.0
        if not self._ensure_embeddings():
            return 0.0

        import numpy as np

        query_vec = self._model.encode(f"query: {query}", normalize_embeddings=True)
        query_vec = np.asarray(query_vec, dtype="float32")
        sims = self._embeddings @ query_vec
        return float(np.max(sims))

    def _keyword_match(self, query: str) -> Optional[PlaybookMatch]:
        """Return the intent with the most keyword hits, or ``None``."""
        best: tuple[Intent, list[str]] | None = None
        best_count = 0

        for intent in self._intents:
            matched = []
            for kw in intent.keywords:
                kw_norm = kw.strip()
                if not kw_norm:
                    continue
                # Word-boundary, case-insensitive. Multi-word keywords are matched
                # as literal phrases (accents/punctuation respected).
                pattern = re.escape(kw_norm)
                if re.search(pattern, query, re.IGNORECASE):
                    matched.append(kw_norm)
            if matched and len(matched) > best_count:
                best = (intent, matched)
                best_count = len(matched)

        if best is None:
            return None

        intent, matched = best
        return PlaybookMatch(intent=intent, score=1.0, method="keyword", matched_keywords=matched)

    # -- staleness -------------------------------------------------------

    def is_stale(self, intent: Intent, *, rag_mtime: Optional[float] = None) -> bool:
        """Return True if the RAG corpus is newer than ``intent.last_update``.

        Args:
            intent: The matched intent.
            rag_mtime: Override (used by tests). Defaults to the mtime of
                the LanceDB store file.
        """
        last_update = intent.last_update_date()
        if last_update is None:
            # No date declared → can't decide → assume fresh.
            return False

        if rag_mtime is None:
            if not RAG_STORE_FILE.exists():
                return False
            try:
                rag_mtime = RAG_STORE_FILE.stat().st_mtime
            except OSError:
                return False

        rag_date = datetime.fromtimestamp(rag_mtime).date()
        return rag_date > last_update

    # -- template convenience -------------------------------------------

    def fill(self, intent: Intent, vars: dict[str, str]) -> str:
        return fill_template(intent.template, vars)


# ---------------------------------------------------------------------------
# Module-level singleton — avoids re-parsing the .md file per pipeline run
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_playbook() -> Playbook:
    """Return a process-wide cached :class:`Playbook` singleton."""
    return Playbook()


def reset_playbook_cache() -> None:
    """Drop the cached singleton (used by tests that tweak PROCEDURES.md)."""
    get_playbook.cache_clear()
