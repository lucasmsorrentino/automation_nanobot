"""Completeness/blocking checks for Tier 0 intents.

Each intent in ``workspace/PROCEDURES.md`` declares a list of
``blocking_checks`` by string ID. This module registers the actual check
functions keyed by those IDs. The ``agir_estagios`` node calls
:func:`run_checks` with the intent + extracted variables + SIGA/SEI
context and aggregates the results into a ``CheckSummary`` that decides
whether to (a) proceed with SEI write ops, (b) require student
justification (soft block), or (c) refuse and reply with blockers
(hard block).

Checks follow a tri-state model::

    pass         — condition satisfied, no impediment
    soft_block   — requires student justification / supervisor action
                    before proceeding; the pipeline must draft a reply
                    asking for the missing info rather than auto-creating
                    the SEI process
    hard_block   — condition makes the request inadmissible; the
                    pipeline must reply refusing and citing the reason

Adding a new check:
    1. Add a string ID to the intent's ``blocking_checks`` list in
       PROCEDURES.md.
    2. Decorate a function with ``@register("that_id")`` in this module.
    3. The function receives a :class:`CheckContext` and returns a
       :class:`CheckResult`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any, Callable, Literal, Optional

from ufpr_automation.utils.dates import (
    parse_br_date_to_date as _parse_br_date,
    working_days_between as _working_days_between,
)
from ufpr_automation.utils.logging import logger
from ufpr_automation.utils.text import strip_accents_lower as _strip_accents_lower

if TYPE_CHECKING:
    from ufpr_automation.core.models import EmailData
    from ufpr_automation.procedures.playbook import Intent


CheckStatus = Literal["pass", "soft_block", "hard_block"]


@dataclass
class CheckResult:
    """Outcome of a single blocking check."""

    check_id: str
    status: CheckStatus
    reason: str = ""  # populated when not ``pass``; shown in replies
    # When True, this block is an internal pipeline concern (e.g. SIGA not
    # consulted yet, SEI context missing) — gate SEI write ops, but do NOT
    # surface it in the email draft to the aluno since they can't fix it.
    # The agir_estagios node logs it + routes to human review instead.
    internal_only: bool = False


@dataclass
class CheckContext:
    """Everything a checker needs to evaluate an intent against an email."""

    email: "EmailData"
    intent: "Intent"
    vars: dict[str, str]
    siga_context: Optional[dict[str, Any]] = None
    sei_context: Optional[dict[str, Any]] = None


@dataclass
class CheckSummary:
    """Aggregated result across all blocking checks for one intent."""

    results: list[CheckResult] = field(default_factory=list)

    @property
    def hard_blocks(self) -> list[CheckResult]:
        return [r for r in self.results if r.status == "hard_block"]

    @property
    def soft_blocks(self) -> list[CheckResult]:
        return [r for r in self.results if r.status == "soft_block"]

    @property
    def passed(self) -> list[CheckResult]:
        return [r for r in self.results if r.status == "pass"]

    @property
    def can_proceed(self) -> bool:
        """True only if there are no hard blocks AND no soft blocks."""
        return not self.hard_blocks and not self.soft_blocks

    @property
    def needs_justification(self) -> bool:
        """True if there are soft blocks but no hard blocks."""
        return bool(self.soft_blocks) and not self.hard_blocks

    def human_readable(self) -> str:
        """Format the summary for inclusion in email replies or logs."""
        lines = []
        if self.hard_blocks:
            lines.append("Impedimentos (hard):")
            for r in self.hard_blocks:
                lines.append(f"  - {r.check_id}: {r.reason}")
        if self.soft_blocks:
            lines.append("Requer justificativa (soft):")
            for r in self.soft_blocks:
                lines.append(f"  - {r.check_id}: {r.reason}")
        if not lines:
            lines.append("Todas as condições satisfeitas.")
        return "\n".join(lines)


CheckerFn = Callable[[CheckContext], CheckResult]

# Registry populated via @register decorator at module import time.
_CHECKERS: dict[str, CheckerFn] = {}


def register(check_id: str) -> Callable[[CheckerFn], CheckerFn]:
    """Decorator that binds a checker function to a ``check_id`` used in
    PROCEDURES.md intents.
    """

    def deco(fn: CheckerFn) -> CheckerFn:
        if check_id in _CHECKERS:
            logger.warning("Checker duplicado registrado: %s", check_id)
        _CHECKERS[check_id] = fn
        return fn

    return deco


def run_checks(intent: "Intent", ctx: CheckContext) -> CheckSummary:
    """Run all blocking checks declared in the intent against the context.

    A check ID not found in the registry is treated as ``hard_block``
    with reason ``"checker_not_registered"`` — this is intentionally
    conservative to surface typos in PROCEDURES.md instead of silently
    passing.
    """
    summary = CheckSummary()
    for check_id in intent.blocking_checks:
        fn = _CHECKERS.get(check_id)
        if fn is None:
            summary.results.append(
                CheckResult(
                    check_id=check_id,
                    status="hard_block",
                    reason="checker_not_registered",
                )
            )
            continue
        try:
            summary.results.append(fn(ctx))
        except Exception as e:
            logger.error("Checker %s raised: %s", check_id, e)
            summary.results.append(
                CheckResult(
                    check_id=check_id,
                    status="hard_block",
                    reason=f"checker_error: {e}",
                )
            )
    return summary


# ============================================================================
# Helpers
# ============================================================================


def _siga_val(ctx: CheckContext, key: str, default: Any = None) -> Any:
    """Safe lookup in the SIGA context (empty when SIGA wasn't consulted)."""
    if not ctx.siga_context:
        return default
    return ctx.siga_context.get(key, default)


def _siga_missing_result(check_id: str) -> CheckResult:
    """Standard soft-block when SIGA data is required but unavailable.

    The checker can't verify the rule without SIGA, so the pipeline must
    gate the SEI write ops. But the aluno can't fix "SIGA not consulted"
    — that's an internal pipeline state — so mark ``internal_only=True``
    to keep it out of the email draft (still logged, still routes to
    human review).
    """
    return CheckResult(
        check_id=check_id,
        status="soft_block",
        reason="SIGA não consultado — requer verificação manual",
        internal_only=True,
    )


def _sei_missing_result(check_id: str) -> CheckResult:
    """Same pattern as ``_siga_missing_result`` for SEI-dependent checkers."""
    return CheckResult(
        check_id=check_id,
        status="soft_block",
        reason="SEI não consultado — requer verificação manual",
        internal_only=True,
    )


# ============================================================================
# SIGA-dependent checkers
# ============================================================================


@register("siga_matricula_ativa")
def siga_matricula_ativa(ctx: CheckContext) -> CheckResult:
    """HARD block if student is not actively enrolled.

    Non-active statuses: TRANCADA, CANCELADA, ABANDONADA, INTEGRALIZADA.
    """
    status = _siga_val(ctx, "matricula_status")
    if status is None:
        return _siga_missing_result("siga_matricula_ativa")
    if str(status).upper() != "ATIVA":
        return CheckResult(
            check_id="siga_matricula_ativa",
            status="hard_block",
            reason=f"Matrícula {status} — estágio não permitido",
        )
    return CheckResult(check_id="siga_matricula_ativa", status="pass")


@register("siga_reprovacoes_ultimo_semestre")
def siga_reprovacoes_ultimo_semestre(ctx: CheckContext) -> CheckResult:
    """SOFT block if the student had more than one failure last semester.

    Rule: > 1 reprovação exige justificativa formal do aluno antes de a
    Coordenação homologar o estágio (baixo desempenho).
    """
    count = _siga_val(ctx, "reprovacoes_ultimo_semestre")
    if count is None:
        return _siga_missing_result("siga_reprovacoes_ultimo_semestre")
    try:
        count = int(count)
    except (TypeError, ValueError):
        return CheckResult(
            check_id="siga_reprovacoes_ultimo_semestre",
            status="hard_block",
            reason=f"valor inválido de reprovações: {count!r}",
        )
    if count > 1:
        return CheckResult(
            check_id="siga_reprovacoes_ultimo_semestre",
            status="soft_block",
            reason=(
                f"Aluno teve {count} reprovações no semestre anterior. "
                "Solicitar justificativa formal antes de prosseguir — "
                "baixo desempenho acadêmico pode motivar indeferimento "
                "pela Coordenação."
            ),
        )
    return CheckResult(check_id="siga_reprovacoes_ultimo_semestre", status="pass")


@register("siga_reprovacao_por_falta")
def siga_reprovacao_por_falta(ctx: CheckContext) -> CheckResult:
    """HARD block — specific rule of the Design Gráfico course."""
    rep_falta = _siga_val(ctx, "reprovacao_por_falta_ultimo_semestre")
    if rep_falta is None:
        return _siga_missing_result("siga_reprovacao_por_falta")
    if rep_falta:
        return CheckResult(
            check_id="siga_reprovacao_por_falta",
            status="hard_block",
            reason=(
                "Aluno reprovou por falta no semestre anterior — regra "
                "específica do Curso de Design Gráfico impede estágio."
            ),
        )
    return CheckResult(check_id="siga_reprovacao_por_falta", status="pass")


@register("siga_curriculo_integralizado")
def siga_curriculo_integralizado(ctx: CheckContext) -> CheckResult:
    """HARD block — aluno integralizado não pode iniciar estágio não-obrig."""
    integ = _siga_val(ctx, "curriculo_integralizado")
    if integ is None:
        return _siga_missing_result("siga_curriculo_integralizado")
    if integ:
        return CheckResult(
            check_id="siga_curriculo_integralizado",
            status="hard_block",
            reason=(
                "Currículo já integralizado — estágio não-obrigatório exige aluno ainda em curso."
            ),
        )
    return CheckResult(check_id="siga_curriculo_integralizado", status="pass")


# NOTE: ``siga_ch_simultaneos_30h`` e ``siga_concedente_duplicada`` foram
# removidos em 2026-04-30. Verificacao de estagio ativo / duplicado e
# responsabilidade do **SEI cascade** (busca processos vigentes via
# Acompanhamento Especial em ``_consult_sei_for_email`` + checker
# ``sei_processo_vigente_duplicado``), nao do SIGA — ``estagios_ativos``
# nao e fetchado do SIGA hoje, e nem deveria ser, ja que o SEI tem a
# fonte de verdade dos processos abertos. A regra de carga horaria foi
# substituida pela regra de **periodo** (manha vs. tarde) implementada em
# ``tce_jornada_antes_meio_dia`` abaixo.


# ============================================================================
# Date / TCE content checkers (no SIGA needed)
# ============================================================================


@register("data_inicio_retroativa")
def data_inicio_retroativa(ctx: CheckContext) -> CheckResult:
    """HARD block — não é permitida homologação com data retroativa."""
    data_inicio = _parse_br_date(ctx.vars.get("data_inicio", ""))
    if data_inicio is None:
        return CheckResult(
            check_id="data_inicio_retroativa",
            status="hard_block",
            reason="data_inicio não extraída do TCE",
        )
    today = date.today()
    if data_inicio < today:
        return CheckResult(
            check_id="data_inicio_retroativa",
            status="hard_block",
            reason=(
                f"Data de início {data_inicio.strftime('%d/%m/%Y')} é "
                f"anterior a hoje {today.strftime('%d/%m/%Y')} — "
                f"homologação retroativa não é permitida "
                f"(Resolução 46/10-CEPE)."
            ),
        )
    return CheckResult(check_id="data_inicio_retroativa", status="pass")


@register("data_inicio_antecedencia_minima")
def data_inicio_antecedencia_minima(ctx: CheckContext) -> CheckResult:
    """HARD block if fewer than 2 working days between today and início.

    A ``retroativa`` case is caught separately by ``data_inicio_retroativa``
    — this checker only handles the "too close" case for future dates.
    """
    data_inicio = _parse_br_date(ctx.vars.get("data_inicio", ""))
    if data_inicio is None:
        return CheckResult(
            check_id="data_inicio_antecedencia_minima",
            status="hard_block",
            reason="data_inicio não extraída do TCE",
        )
    today = date.today()
    if data_inicio < today:
        return CheckResult(check_id="data_inicio_antecedencia_minima", status="pass")
    wd = _working_days_between(today, data_inicio)
    if wd < 2:
        return CheckResult(
            check_id="data_inicio_antecedencia_minima",
            status="hard_block",
            reason=(
                f"TCE chegou com antecedência de {wd} dia(s) útil(eis) "
                f"(mínimo exigido: 2). Peça ao aluno para reenviar com "
                f"data de início posterior ou, se possível, informar que "
                f"o estágio precisa começar mais tarde."
            ),
        )
    return CheckResult(check_id="data_inicio_antecedencia_minima", status="pass")


@register("tce_jornada_sem_horario")
def tce_jornada_sem_horario(ctx: CheckContext) -> CheckResult:
    """HARD block — o TCE precisa especificar o horário da jornada."""
    if not ctx.vars.get("jornada_horario_inicio"):
        return CheckResult(
            check_id="tce_jornada_sem_horario",
            status="hard_block",
            reason=(
                "O TCE precisa especificar o horário da jornada de estágio. "
                "Por favor, ajuste o documento incluindo o horário "
                "(ex.: 'das 13h00 às 19h00, de segunda a sexta') e reenvie."
            ),
        )
    return CheckResult(check_id="tce_jornada_sem_horario", status="pass")


# Disciplinas que NAO exigem aula presencial de manha — alunos com so
# essas pendentes podem estagiar de manha sem prejuizo academico. Lista
# vinda do regulamento do curso de Design Grafico:
#   OD501  — Estagio Supervisionado (anual, 360h, sem aula regular)
#   ODDA6  — TCC1 (orientacao individual)
#   ODDA7  — TCC2 (orientacao individual)
_DISCIPLINAS_SEM_AULA_MANHA = frozenset({"OD501", "ODDA6", "ODDA7"})


@register("tce_jornada_antes_meio_dia")
def tce_jornada_antes_meio_dia(ctx: CheckContext) -> CheckResult:
    """HARD block — jornada começando antes das 12h00 conflita com aulas.

    As aulas do curso de Design Gráfico são pela manhã, portanto estágios
    que começam antes do meio-dia atrapalham a frequência. **Duas exceções**:

    1. Aluno já integralizou todas as disciplinas da grade
       (``curriculo_integralizado=True`` no SIGA).
    2. Aluno só tem pendentes disciplinas que NÃO exigem aula presencial
       de manhã — TCC1 (ODDA6), TCC2 (ODDA7) e Estágio Supervisionado
       (OD501). Ou seja, ``set(nao_vencidas) ⊆ {OD501, ODDA6, ODDA7}``.
       Nesse caso o aluno pode estagiar tanto de manhã quanto de tarde
       porque o que falta na grade não conflita com horário matinal.

    Sem dados de SIGA (campo ausente no contexto), bloqueia — fail-safe:
    melhor pedir verificação manual do que liberar manhã indevidamente.
    """
    horario = ctx.vars.get("jornada_horario_inicio", "")
    if not horario:
        # Já coberto por tce_jornada_sem_horario; evita duplicar bloqueio.
        return CheckResult(check_id="tce_jornada_antes_meio_dia", status="pass")
    try:
        hh = int(horario.split(":")[0])
    except (ValueError, IndexError):
        return CheckResult(
            check_id="tce_jornada_antes_meio_dia",
            status="hard_block",
            reason=f"horário inválido: {horario!r}",
        )
    if hh >= 12:
        return CheckResult(check_id="tce_jornada_antes_meio_dia", status="pass")

    # Comeca antes do meio-dia — verificar exceções.
    # Excecao 1: ja cumpriu tudo.
    if _siga_val(ctx, "curriculo_integralizado", None) is True:
        return CheckResult(check_id="tce_jornada_antes_meio_dia", status="pass")

    # Excecao 2: so pendentes sao TCC1/TCC2/Estagio Supervisionado.
    nao_vencidas = _siga_val(ctx, "nao_vencidas", None)
    if isinstance(nao_vencidas, list):
        pendentes = {str(s).strip().upper() for s in nao_vencidas if s}
        if pendentes and pendentes.issubset(_DISCIPLINAS_SEM_AULA_MANHA):
            return CheckResult(check_id="tce_jornada_antes_meio_dia", status="pass")

    return CheckResult(
        check_id="tce_jornada_antes_meio_dia",
        status="hard_block",
        reason=(
            f"Jornada de estágio começa às {horario}, antes do meio-dia, "
            f"mas as aulas do Curso de Design Gráfico são pela manhã. "
            f"Exceções: (a) aluno que já integralizou todas as disciplinas "
            f"OU (b) aluno cujas únicas pendências são TCC1 (ODDA6), "
            f"TCC2 (ODDA7) e/ou Estágio Supervisionado (OD501) — "
            f"verificar aba 'Integralização' no SIGA."
        ),
    )


# ============================================================================
# SEI-dependent checkers
# ============================================================================


@register("sei_processo_vigente_duplicado")
def sei_processo_vigente_duplicado(ctx: CheckContext) -> CheckResult:
    """HARD block if a VIGENTE process of the same tipo already exists
    for this student.

    "Vigente" means not yet finalized/archived. A new TCE should only
    open a new process when the previous one is finalized; if an active
    process already exists, the current email is probably related to
    that one (aditivo, rescisão, relatório) and was misclassified.
    """
    if not ctx.sei_context:
        return _sei_missing_result("sei_processo_vigente_duplicado")
    processos_vigentes = ctx.sei_context.get("processos_vigentes", []) or []
    tipo_alvo = ctx.intent.sei_process_type.strip().lower()
    for proc in processos_vigentes:
        proc_tipo = str(proc.get("tipo", "")).strip().lower()
        if tipo_alvo and tipo_alvo in proc_tipo:
            return CheckResult(
                check_id="sei_processo_vigente_duplicado",
                status="hard_block",
                reason=(
                    f"Já existe processo SEI vigente do mesmo tipo para "
                    f"este aluno: {proc.get('numero', '?')} — o novo TCE "
                    f"provavelmente deveria ser anexado a ele, não "
                    f"iniciar processo novo."
                ),
            )
    return CheckResult(check_id="sei_processo_vigente_duplicado", status="pass")


@register("sei_processo_tce_existente")
def sei_processo_tce_existente(ctx: CheckContext) -> CheckResult:
    """HARD block if NO vigente SEI process of the TCE type exists for this
    student. Inverse of ``sei_processo_vigente_duplicado``: aditivo /
    conclusão / rescisão must append to the existing TCE process — if no
    such process exists, the email is likely misclassified (should be a
    new TCE, not an aditivo) or the student is in another unit.
    """
    if not ctx.sei_context:
        return _sei_missing_result("sei_processo_tce_existente")
    processos_vigentes = ctx.sei_context.get("processos_vigentes", []) or []
    tipo_alvo = "estágios não obrigatórios"  # aditivo/conclusão só aplicam a este tipo
    for proc in processos_vigentes:
        proc_tipo = str(proc.get("tipo", "")).strip().lower()
        if tipo_alvo in proc_tipo:
            return CheckResult(check_id="sei_processo_tce_existente", status="pass")
    return CheckResult(
        check_id="sei_processo_tce_existente",
        status="hard_block",
        reason=(
            "Não foi encontrado processo SEI vigente do tipo 'Estágios não "
            "Obrigatórios' para este aluno. Aditivo/conclusão/rescisão devem "
            "ser anexados ao processo do TCE original — verifique se o email "
            "não é, na verdade, um pedido de novo estágio."
        ),
    )


@register("aditivo_antes_vencimento_tce")
def aditivo_antes_vencimento_tce(ctx: CheckContext) -> CheckResult:
    """HARD block if the aditivo request arrives after the TCE vigente's
    data_fim. Lei 11.788/08 + Resolução 46/10-CEPE: expired stages cannot
    be prorrogated retroactively — only rescisão applies.

    Reads TCE data_fim from SEI context (``tce_data_fim`` key populated by
    sei.client when it locates the TCE original in the processo vigente).
    """
    tce_data_fim_raw = (ctx.sei_context or {}).get("tce_data_fim")
    if not tce_data_fim_raw:
        return CheckResult(
            check_id="aditivo_antes_vencimento_tce",
            status="soft_block",
            reason=(
                "Data de término do TCE vigente não disponível no contexto "
                "SEI — requer verificação manual."
            ),
            internal_only=True,
        )
    data_fim = _parse_br_date(str(tce_data_fim_raw))
    if data_fim is None:
        return CheckResult(
            check_id="aditivo_antes_vencimento_tce",
            status="soft_block",
            reason=f"Data de término do TCE ilegível: {tce_data_fim_raw!r}",
        )
    today = date.today()
    if today > data_fim:
        return CheckResult(
            check_id="aditivo_antes_vencimento_tce",
            status="hard_block",
            reason=(
                f"TCE venceu em {data_fim.strftime('%d/%m/%Y')} — aditivo "
                f"deve chegar ANTES do vencimento. Após o vencimento o "
                f"estágio encerra-se automaticamente (Lei 11.788/08); "
                f"solicite nova abertura de processo em vez de aditivo."
            ),
        )
    return CheckResult(check_id="aditivo_antes_vencimento_tce", status="pass")


@register("duracao_total_ate_24_meses")
def duracao_total_ate_24_meses(ctx: CheckContext) -> CheckResult:
    """HARD block if TCE + aditivos somam mais de 24 meses na mesma
    concedente (Lei 11.788/08 Art. 11).

    Reads ``tce_data_inicio`` (original, da SEI) e ``data_termino_novo``
    (proposed end date do aditivo, das vars extraídas).
    """
    tce_inicio_raw = (ctx.sei_context or {}).get("tce_data_inicio")
    termino_novo_raw = ctx.vars.get("data_termino_novo") or ctx.vars.get("data_fim")
    if not tce_inicio_raw or not termino_novo_raw:
        return CheckResult(
            check_id="duracao_total_ate_24_meses",
            status="soft_block",
            reason=(
                "Data de início do TCE original ou novo término não "
                "disponíveis — requer verificação manual da duração total."
            ),
        )
    inicio = _parse_br_date(str(tce_inicio_raw))
    termino = _parse_br_date(str(termino_novo_raw))
    if inicio is None or termino is None:
        return CheckResult(
            check_id="duracao_total_ate_24_meses",
            status="soft_block",
            reason=(f"Datas ilegíveis: inicio={tce_inicio_raw!r} termino={termino_novo_raw!r}"),
        )
    # 24 months ≈ 730 days; use calendar month arithmetic for precision.
    max_termino = date(inicio.year + 2, inicio.month, min(inicio.day, 28))
    if termino > max_termino:
        return CheckResult(
            check_id="duracao_total_ate_24_meses",
            status="hard_block",
            reason=(
                f"Duração total ({inicio.strftime('%d/%m/%Y')} a "
                f"{termino.strftime('%d/%m/%Y')}) ultrapassa 24 meses "
                f"na mesma concedente (Lei 11.788/08 Art. 11). Limite: "
                f"{max_termino.strftime('%d/%m/%Y')}."
            ),
        )
    return CheckResult(check_id="duracao_total_ate_24_meses", status="pass")


@register("relatorio_final_assinado_orientador")
def relatorio_final_assinado_orientador(ctx: CheckContext) -> CheckResult:
    """HARD block if the Relatório Final attachment does not show evidence
    of the orientador's signature. Best-effort text-based check — looks
    for signature markers near the "orientador" token in the extracted
    attachment text. Returns soft_block when no attachment text is
    available (OCR missing / extraction failed).

    Signature markers considered valid:
        - "assinado eletronicamente"
        - "assinado digitalmente"
        - "[assinatura]"
        - "carimbo e assinatura"
    """
    attachments = getattr(ctx.email, "attachments", None) or []
    relatorio_text = ""
    for att in attachments:
        name = (getattr(att, "filename", "") or "").lower()
        text = getattr(att, "extracted_text", "") or ""
        if "relat" in name and "final" in name and text:
            relatorio_text = text.lower()
            break
    if not relatorio_text:
        return CheckResult(
            check_id="relatorio_final_assinado_orientador",
            status="soft_block",
            reason=(
                "Relatório Final não encontrado entre os anexos ou texto "
                "não extraído (OCR?) — requer verificação manual da "
                "assinatura do orientador."
            ),
        )
    signature_markers = (
        "assinado eletronicamente",
        "assinado digitalmente",
        "[assinatura]",
        "carimbo e assinatura",
    )
    # Search for any signature marker within 400 chars of the token "orientador"
    import re

    for m in re.finditer(r"orientador", relatorio_text):
        window = relatorio_text[max(0, m.start() - 400) : m.end() + 400]
        if any(mk in window for mk in signature_markers):
            return CheckResult(check_id="relatorio_final_assinado_orientador", status="pass")
    return CheckResult(
        check_id="relatorio_final_assinado_orientador",
        status="hard_block",
        reason=(
            "Relatório Final não apresenta evidência de assinatura do "
            "professor orientador (esperado: 'assinado eletronicamente', "
            "'assinado digitalmente', ou carimbo/assinatura próximo do "
            "nome do orientador). Exigência Lei 11.788/08 Art. 9º §1º."
        ),
    )


# ============================================================================
# Supervisor elegibility
# ============================================================================

# Keywords that signal the supervisor's formação/cargo is compatible with
# Design Gráfico. Compared against `formacao_supervisor` after stripping
# accents + lowercasing. Sources:
#   - SOUL.md §7 (roles/supervisor)
#   - base_conhecimento/estagios/GUIA_ESTAGIOS_DG.txt §SUPERVISOR
#   - Art. 9 Lei 11.788/2008 + Art. 10 Resolução CEPE 46/10
#
# Added conservatively — when in doubt, the soft_block triggers a request
# for the Declaração de Experiência do Supervisor (form PROGRAD) which the
# supervisor's chefia imediata signs. Better to over-ask than to let an
# incompatible supervisor through silently.
_SUPERVISOR_AREAS_AFINS_DESIGN = {
    "design",                   # cobre design grafico, de produto, de interiores, etc.
    "arquitetura",              # arquitetura e urbanismo
    "artes visuais",
    "artes plasticas",
    "comunicacao visual",
    "comunicacao social",        # cobre Comunicacao Social com qualquer habilitacao
    "publicidade",               # cobre Publicidade isolada ou em habilitacao
    "propaganda",                # cobre Propaganda isolada ou em habilitacao
    "publicidade e propaganda",  # forma literal mais comum em diplomas (PUCPR, etc.)
    "marketing",
    "multimidia",
    "producao cultural",
    "producao multimidia",
    "game design",
    "ux",                       # ux design, ui/ux
    "interaction design",
    "direcao de arte",
    "diagramacao",
    "editoracao",
    "ilustracao",
    "motion",                   # motion design / motion graphics
    "animacao",
    "fotografia",
    "cinema",
    "audiovisual",
    "midias digitais",
    "tecnologia em design",
}


@register("supervisor_formacao_compativel")
def supervisor_formacao_compativel(ctx: CheckContext) -> CheckResult:
    """SOFT block — supervisor must have formação/experiência em área afim a
    Design, senão exige Declaração de Experiência do Supervisor.

    Regra (Art. 9 Lei 11.788/2008 + Art. 10 Res. CEPE 46/10): o supervisor
    no local de estágio precisa ter formação ou experiência profissional
    na área do curso do estagiário. Quando a formação capturada do TCE
    não aparenta ser afim a Design, pedir que o aluno providencie
    Declaração de Experiência do Supervisor (formulário PROGRAD) assinada
    pela chefia imediata do supervisor.

    Se ``formacao_supervisor`` não foi extraído do TCE, retorna ``pass``
    silencioso — não é papel deste checker detectar TCE mal formatado;
    outros checkers (ou revisão humana) pegam esse caso.
    """
    formacao = ctx.vars.get("formacao_supervisor", "")
    nome_sup = ctx.vars.get("nome_supervisor", "o(a) supervisor(a)")

    if not formacao:
        # Dado ausente: TCE padrão CIEE traz só "SUPERVISOR: NOME" sem
        # campo de formação. Em vez de passar silencioso (que esconde a
        # exigência legal), soft-block pedindo pra aluno trazer a formação
        # do supervisor ou a Declaração de Experiência já. É 1 checker a
        # mais no draft combinado, mas preferível ao retrabalho de pedir
        # depois que o resto foi ajustado.
        return CheckResult(
            check_id="supervisor_formacao_compativel",
            status="soft_block",
            reason=(
                f"Formação/cargo de {nome_sup} não consta no TCE. "
                f"Art. 9 Lei 11.788/2008 + Art. 10 Res. CEPE 46/10 "
                f"exigem formação ou experiência comprovada na área do "
                f"curso. Por favor, informe a formação do supervisor na "
                f"resposta OU já providencie a Declaração de Experiência "
                f"do Supervisor (form PROGRAD: "
                f"http://www.prograd.ufpr.br/estagio/formularios/form/declaracao_experiencia.php, "
                f"assinada pela chefia imediata)."
            ),
        )

    norm = _strip_accents_lower(formacao)
    for keyword in _SUPERVISOR_AREAS_AFINS_DESIGN:
        if keyword in norm:
            return CheckResult(check_id="supervisor_formacao_compativel", status="pass")

    # Nenhuma palavra-chave de área afim casou — exigir declaração.
    return CheckResult(
        check_id="supervisor_formacao_compativel",
        status="soft_block",
        reason=(
            f"Formação do supervisor ({formacao!r}) não aparenta ser afim a "
            f"Design. Art. 9 Lei 11.788/2008 + Art. 10 Res. CEPE 46/10 "
            f"exigem formação/experiência na área. Solicite Declaração de "
            f"Experiência do Supervisor (form PROGRAD — "
            f"http://www.prograd.ufpr.br/estagio/formularios/form/declaracao_experiencia.php), "
            f"assinada pela chefia imediata de {nome_sup}."
        ),
    )


def registered_checkers() -> list[str]:
    """Return the list of currently-registered check IDs (for debugging)."""
    return sorted(_CHECKERS.keys())
