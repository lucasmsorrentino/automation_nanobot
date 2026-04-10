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
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable, Literal, Optional

from ufpr_automation.utils.logging import logger

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


def _parse_br_date(s: str) -> Optional[date]:
    """Parse DD/MM/YYYY into a ``date`` or return ``None``."""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def _working_days_between(start: date, end: date) -> int:
    """Count working days (Mon-Fri) between two dates, exclusive of start,
    inclusive of end. Does NOT account for national/academic holidays.
    """
    if end <= start:
        return 0
    days = 0
    cur = start + timedelta(days=1)
    while cur <= end:
        if cur.weekday() < 5:  # 0=Mon .. 4=Fri
            days += 1
        cur += timedelta(days=1)
    return days


def _siga_val(ctx: CheckContext, key: str, default: Any = None) -> Any:
    """Safe lookup in the SIGA context (empty when SIGA wasn't consulted)."""
    if not ctx.siga_context:
        return default
    return ctx.siga_context.get(key, default)


def _siga_missing_result(check_id: str) -> CheckResult:
    """Standard soft-block when SIGA data is required but unavailable.

    The checker can't verify the rule without SIGA, so the pipeline must
    escalate to human review instead of assuming pass/fail.
    """
    return CheckResult(
        check_id=check_id,
        status="soft_block",
        reason="SIGA não consultado — requer verificação manual",
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
                "Currículo já integralizado — estágio não-obrigatório "
                "exige aluno ainda em curso."
            ),
        )
    return CheckResult(check_id="siga_curriculo_integralizado", status="pass")


@register("siga_ch_simultaneos_30h")
def siga_ch_simultaneos_30h(ctx: CheckContext) -> CheckResult:
    """HARD block if sum of simultaneous internships + new TCE > 30h/week."""
    ativos = _siga_val(ctx, "estagios_ativos", []) or []
    if not isinstance(ativos, list):
        return CheckResult(
            check_id="siga_ch_simultaneos_30h",
            status="hard_block",
            reason=f"formato inesperado de estagios_ativos: {type(ativos).__name__}",
        )
    existing = 0.0
    for est in ativos:
        try:
            existing += float(est.get("ch_semanal", 0))
        except (TypeError, ValueError, AttributeError):
            continue
    try:
        new_ch = float(ctx.vars.get("horas_semanais", "0"))
    except (TypeError, ValueError):
        new_ch = 0.0
    total = existing + new_ch
    if total > 30:
        return CheckResult(
            check_id="siga_ch_simultaneos_30h",
            status="hard_block",
            reason=(
                f"Carga horária total de estágios simultâneos seria "
                f"{total:.1f}h/semana (existentes: {existing:.1f}h + "
                f"novo TCE: {new_ch:.1f}h) — limite legal é 30h/semana."
            ),
        )
    return CheckResult(check_id="siga_ch_simultaneos_30h", status="pass")


@register("siga_concedente_duplicada")
def siga_concedente_duplicada(ctx: CheckContext) -> CheckResult:
    """HARD block — dois estágios simultâneos na mesma concedente."""
    ativos = _siga_val(ctx, "estagios_ativos", []) or []
    concedente = ctx.vars.get("nome_concedente", "").strip().lower()
    if not concedente:
        return CheckResult(
            check_id="siga_concedente_duplicada",
            status="hard_block",
            reason="nome_concedente não extraído do TCE — não é possível validar",
        )
    for est in ativos:
        existing = str(est.get("concedente", "")).strip().lower()
        if existing and existing == concedente:
            return CheckResult(
                check_id="siga_concedente_duplicada",
                status="hard_block",
                reason=(
                    f"Aluno já possui estágio ativo na mesma concedente "
                    f"({ctx.vars['nome_concedente']}) — Lei 11.788/2008 "
                    f"veda duplicidade."
                ),
            )
    return CheckResult(check_id="siga_concedente_duplicada", status="pass")


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
                "TCE não especifica o horário da jornada de estágio. "
                "Peça ao aluno para corrigir o TCE incluindo o horário "
                "(ex.: 'das 13h00 às 19h00, de segunda a sexta')."
            ),
        )
    return CheckResult(check_id="tce_jornada_sem_horario", status="pass")


@register("tce_jornada_antes_meio_dia")
def tce_jornada_antes_meio_dia(ctx: CheckContext) -> CheckResult:
    """HARD block — jornada começando antes das 12h00 conflita com aulas
    (exceto se o aluno já integralizou todas as disciplinas).

    As aulas do curso de Design Gráfico são de manhã, portanto estágios
    que começam antes do meio-dia atrapalham a frequência. A exceção é
    quando o aluno já cursou todas as disciplinas obrigatórias (SIGA →
    aba integralização) — nesse caso o bloqueio é dispensado.
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

    # Começa antes do meio-dia — verificar exceção de integralização
    integralizado = _siga_val(ctx, "curriculo_integralizado", None)
    if integralizado is True:
        return CheckResult(
            check_id="tce_jornada_antes_meio_dia",
            status="pass",  # exceção aplica — já cumpriu todas as disciplinas
        )
    return CheckResult(
        check_id="tce_jornada_antes_meio_dia",
        status="hard_block",
        reason=(
            f"Jornada de estágio começa às {horario}, antes do meio-dia, "
            f"mas as aulas do Curso de Design Gráfico são pela manhã. "
            f"Exceção: aluno que já integralizou todas as disciplinas da "
            f"grade (verificar aba 'Integralização' no SIGA)."
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
        return CheckResult(
            check_id="sei_processo_vigente_duplicado",
            status="soft_block",
            reason="SEI não consultado — requer verificação manual",
        )
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


def registered_checkers() -> list[str]:
    """Return the list of currently-registered check IDs (for debugging)."""
    return sorted(_CHECKERS.keys())
