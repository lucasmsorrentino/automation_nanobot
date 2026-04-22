"""Tests for procedures/checkers.py — the 11 blocking checks for Estágios.

Covers each registered checker with a happy path and its primary failure
mode, plus the ``run_checks`` aggregator's behavior for unknown IDs and
checkers that raise exceptions. The goal is to protect the Marco IV hard
blocks against silent regressions while the rest of the Estágios pipeline
is being wired up.
"""

from __future__ import annotations

from datetime import date, timedelta

from ufpr_automation.core.models import EmailData
from ufpr_automation.procedures.checkers import (
    _CHECKERS,
    CheckContext,
    CheckResult,
    CheckSummary,
    _parse_br_date,
    _working_days_between,
    register,
    registered_checkers,
    run_checks,
)
from ufpr_automation.procedures.playbook import Intent

# ---------------------------------------------------------------------------
# Registry baseline
# ---------------------------------------------------------------------------


EXPECTED_CHECKERS = {
    # Inicial TCE (estagio_nao_obrig_acuse_inicial)
    "siga_matricula_ativa",
    "siga_reprovacoes_ultimo_semestre",
    "siga_reprovacao_por_falta",
    "siga_curriculo_integralizado",
    "siga_ch_simultaneos_30h",
    "siga_concedente_duplicada",
    "data_inicio_retroativa",
    "data_inicio_antecedencia_minima",
    "tce_jornada_sem_horario",
    "tce_jornada_antes_meio_dia",
    "sei_processo_vigente_duplicado",
    # Aditivo / Conclusão (Marco IV — 2026-04-14)
    "sei_processo_tce_existente",
    "aditivo_antes_vencimento_tce",
    "duracao_total_ate_24_meses",
    "relatorio_final_assinado_orientador",
    # Supervisor elegibility (2026-04-22) — Art. 9 Lei 11.788 + Res. CEPE 46/10
    "supervisor_formacao_compativel",
}


def test_all_checkers_registered():
    registered = set(registered_checkers())
    assert registered == EXPECTED_CHECKERS, (
        f"Unexpected checker registry. "
        f"Missing: {EXPECTED_CHECKERS - registered}. "
        f"Extra: {registered - EXPECTED_CHECKERS}."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(
    *,
    intent: Intent | None = None,
    vars: dict[str, str] | None = None,
    siga: dict | None = None,
    sei: dict | None = None,
) -> CheckContext:
    email = EmailData(sender="aluno@ufpr.br", subject="test", body="")
    return CheckContext(
        email=email,
        intent=intent or Intent(intent_name="t", categoria="Estágios", keywords=["t"]),
        vars=vars or {},
        siga_context=siga,
        sei_context=sei,
    )


def _br(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _invoke(check_id: str, ctx: CheckContext) -> CheckResult:
    return _CHECKERS[check_id](ctx)


# ---------------------------------------------------------------------------
# SIGA-dependent checkers
# ---------------------------------------------------------------------------


class TestSigaMatriculaAtiva:
    def test_pass_when_ativa(self):
        r = _invoke("siga_matricula_ativa", _make_ctx(siga={"matricula_status": "ATIVA"}))
        assert r.status == "pass"

    def test_hard_block_when_trancada(self):
        r = _invoke("siga_matricula_ativa", _make_ctx(siga={"matricula_status": "TRANCADA"}))
        assert r.status == "hard_block"
        assert "TRANCADA" in r.reason

    def test_soft_block_when_siga_missing(self):
        r = _invoke("siga_matricula_ativa", _make_ctx(siga=None))
        assert r.status == "soft_block"
        assert "SIGA" in r.reason


class TestSigaReprovacoesUltimoSemestre:
    def test_pass_when_one_reprovacao(self):
        r = _invoke(
            "siga_reprovacoes_ultimo_semestre",
            _make_ctx(siga={"reprovacoes_ultimo_semestre": 1}),
        )
        assert r.status == "pass"

    def test_soft_block_when_more_than_one(self):
        r = _invoke(
            "siga_reprovacoes_ultimo_semestre",
            _make_ctx(siga={"reprovacoes_ultimo_semestre": 2}),
        )
        assert r.status == "soft_block"
        assert "justificativa" in r.reason.lower()

    def test_hard_block_for_invalid_value(self):
        r = _invoke(
            "siga_reprovacoes_ultimo_semestre",
            _make_ctx(siga={"reprovacoes_ultimo_semestre": "muitas"}),
        )
        assert r.status == "hard_block"

    def test_soft_block_when_siga_missing(self):
        r = _invoke("siga_reprovacoes_ultimo_semestre", _make_ctx(siga=None))
        assert r.status == "soft_block"


class TestSigaReprovacaoPorFalta:
    def test_pass_when_false(self):
        r = _invoke(
            "siga_reprovacao_por_falta",
            _make_ctx(siga={"reprovacao_por_falta_ultimo_semestre": False}),
        )
        assert r.status == "pass"

    def test_hard_block_when_true(self):
        r = _invoke(
            "siga_reprovacao_por_falta",
            _make_ctx(siga={"reprovacao_por_falta_ultimo_semestre": True}),
        )
        assert r.status == "hard_block"
        assert "Design Gráfico" in r.reason


class TestSigaCurriculoIntegralizado:
    def test_pass_when_not_integralizado(self):
        r = _invoke(
            "siga_curriculo_integralizado",
            _make_ctx(siga={"curriculo_integralizado": False}),
        )
        assert r.status == "pass"

    def test_hard_block_when_integralizado(self):
        r = _invoke(
            "siga_curriculo_integralizado",
            _make_ctx(siga={"curriculo_integralizado": True}),
        )
        assert r.status == "hard_block"


class TestSigaChSimultaneos30h:
    def test_pass_under_30h(self):
        r = _invoke(
            "siga_ch_simultaneos_30h",
            _make_ctx(
                siga={"estagios_ativos": [{"ch_semanal": 10}]},
                vars={"horas_semanais": "15"},
            ),
        )
        assert r.status == "pass"

    def test_pass_at_exactly_30h(self):
        r = _invoke(
            "siga_ch_simultaneos_30h",
            _make_ctx(
                siga={"estagios_ativos": [{"ch_semanal": 20}]},
                vars={"horas_semanais": "10"},
            ),
        )
        assert r.status == "pass"  # 30 is not > 30

    def test_hard_block_over_30h(self):
        r = _invoke(
            "siga_ch_simultaneos_30h",
            _make_ctx(
                siga={"estagios_ativos": [{"ch_semanal": 20}]},
                vars={"horas_semanais": "20"},
            ),
        )
        assert r.status == "hard_block"
        assert "40.0" in r.reason

    def test_pass_with_no_existing_and_missing_hours(self):
        r = _invoke(
            "siga_ch_simultaneos_30h",
            _make_ctx(siga={"estagios_ativos": []}, vars={}),
        )
        assert r.status == "pass"


class TestSigaConcedenteDuplicada:
    def test_pass_when_different_concedente(self):
        r = _invoke(
            "siga_concedente_duplicada",
            _make_ctx(
                siga={"estagios_ativos": [{"concedente": "Empresa A"}]},
                vars={"nome_concedente": "Empresa B"},
            ),
        )
        assert r.status == "pass"

    def test_hard_block_when_same_concedente(self):
        r = _invoke(
            "siga_concedente_duplicada",
            _make_ctx(
                siga={"estagios_ativos": [{"concedente": "Empresa A"}]},
                vars={"nome_concedente": "empresa a"},  # case-insensitive
            ),
        )
        assert r.status == "hard_block"
        assert "Lei 11.788" in r.reason

    def test_hard_block_when_concedente_missing(self):
        r = _invoke(
            "siga_concedente_duplicada",
            _make_ctx(siga={"estagios_ativos": []}, vars={}),
        )
        assert r.status == "hard_block"
        assert "não extraído" in r.reason


# ---------------------------------------------------------------------------
# Date checkers (no SIGA dependency)
# ---------------------------------------------------------------------------


class TestDataInicioRetroativa:
    def test_pass_future_date(self):
        future = date.today() + timedelta(days=30)
        r = _invoke(
            "data_inicio_retroativa",
            _make_ctx(vars={"data_inicio": _br(future)}),
        )
        assert r.status == "pass"

    def test_hard_block_past_date(self):
        past = date.today() - timedelta(days=1)
        r = _invoke(
            "data_inicio_retroativa",
            _make_ctx(vars={"data_inicio": _br(past)}),
        )
        assert r.status == "hard_block"
        assert "retroativa" in r.reason

    def test_hard_block_missing_date(self):
        r = _invoke("data_inicio_retroativa", _make_ctx(vars={}))
        assert r.status == "hard_block"
        assert "não extraída" in r.reason


class TestDataInicioAntecedenciaMinima:
    def test_pass_far_future(self):
        # +14 calendar days guarantees > 2 working days regardless of weekday.
        far = date.today() + timedelta(days=14)
        r = _invoke(
            "data_inicio_antecedencia_minima",
            _make_ctx(vars={"data_inicio": _br(far)}),
        )
        assert r.status == "pass"

    def test_hard_block_today(self):
        # Zero working days ahead.
        r = _invoke(
            "data_inicio_antecedencia_minima",
            _make_ctx(vars={"data_inicio": _br(date.today())}),
        )
        assert r.status == "hard_block"
        assert "dia(s) útil" in r.reason

    def test_pass_when_retroativa_deferred_to_sibling_checker(self):
        # Past dates return pass so data_inicio_retroativa handles them
        # without double-blocking.
        past = date.today() - timedelta(days=10)
        r = _invoke(
            "data_inicio_antecedencia_minima",
            _make_ctx(vars={"data_inicio": _br(past)}),
        )
        assert r.status == "pass"


# ---------------------------------------------------------------------------
# Jornada / TCE content checkers
# ---------------------------------------------------------------------------


class TestTceJornadaSemHorario:
    def test_pass_with_horario(self):
        r = _invoke(
            "tce_jornada_sem_horario",
            _make_ctx(vars={"jornada_horario_inicio": "13:00"}),
        )
        assert r.status == "pass"

    def test_hard_block_without_horario(self):
        r = _invoke("tce_jornada_sem_horario", _make_ctx(vars={}))
        assert r.status == "hard_block"
        assert "horário" in r.reason


class TestTceJornadaAntesMeioDia:
    def test_pass_after_noon(self):
        r = _invoke(
            "tce_jornada_antes_meio_dia",
            _make_ctx(vars={"jornada_horario_inicio": "13:00"}),
        )
        assert r.status == "pass"

    def test_pass_exactly_noon(self):
        r = _invoke(
            "tce_jornada_antes_meio_dia",
            _make_ctx(vars={"jornada_horario_inicio": "12:00"}),
        )
        assert r.status == "pass"

    def test_hard_block_before_noon_without_integralizacao(self):
        r = _invoke(
            "tce_jornada_antes_meio_dia",
            _make_ctx(
                vars={"jornada_horario_inicio": "08:00"},
                siga={"curriculo_integralizado": False},
            ),
        )
        assert r.status == "hard_block"
        assert "meio-dia" in r.reason

    def test_pass_before_noon_when_integralizado(self):
        r = _invoke(
            "tce_jornada_antes_meio_dia",
            _make_ctx(
                vars={"jornada_horario_inicio": "08:00"},
                siga={"curriculo_integralizado": True},
            ),
        )
        assert r.status == "pass"

    def test_pass_when_horario_missing_to_avoid_double_block(self):
        # Missing horário is already a hard block in tce_jornada_sem_horario;
        # this checker must not duplicate the block.
        r = _invoke("tce_jornada_antes_meio_dia", _make_ctx(vars={}))
        assert r.status == "pass"


# ---------------------------------------------------------------------------
# SEI checker
# ---------------------------------------------------------------------------


class TestSeiProcessoVigenteDuplicado:
    def test_soft_block_when_sei_not_consulted(self):
        intent = Intent(
            intent_name="tce_inicial",
            categoria="Estágios",
            keywords=["tce"],
            sei_process_type="Estágios não Obrigatórios",
        )
        r = _invoke("sei_processo_vigente_duplicado", _make_ctx(intent=intent, sei=None))
        assert r.status == "soft_block"
        assert "SEI" in r.reason

    def test_pass_when_no_vigente_of_same_type(self):
        intent = Intent(
            intent_name="tce_inicial",
            categoria="Estágios",
            keywords=["tce"],
            sei_process_type="Estágios não Obrigatórios",
        )
        r = _invoke(
            "sei_processo_vigente_duplicado",
            _make_ctx(
                intent=intent,
                sei={"processos_vigentes": [{"tipo": "Diploma", "numero": "X/2025"}]},
            ),
        )
        assert r.status == "pass"

    def test_hard_block_when_same_type_vigente(self):
        intent = Intent(
            intent_name="tce_inicial",
            categoria="Estágios",
            keywords=["tce"],
            sei_process_type="Graduação/Ensino Técnico: Estágios não Obrigatórios",
        )
        r = _invoke(
            "sei_processo_vigente_duplicado",
            _make_ctx(
                intent=intent,
                sei={
                    "processos_vigentes": [
                        {
                            "tipo": "Graduação/Ensino Técnico: Estágios Não Obrigatórios",
                            "numero": "23075.123/2026-01",
                        }
                    ]
                },
            ),
        )
        assert r.status == "hard_block"
        assert "23075.123/2026-01" in r.reason


# ---------------------------------------------------------------------------
# run_checks aggregator
# ---------------------------------------------------------------------------


class TestRunChecks:
    def test_aggregates_all_passes(self):
        intent = Intent(
            intent_name="t",
            categoria="Estágios",
            keywords=["t"],
            blocking_checks=[
                "siga_matricula_ativa",
                "tce_jornada_sem_horario",
            ],
        )
        ctx = _make_ctx(
            intent=intent,
            vars={"jornada_horario_inicio": "14:00"},
            siga={"matricula_status": "ATIVA"},
        )
        summary = run_checks(intent, ctx)
        assert summary.can_proceed is True
        assert len(summary.results) == 2
        assert all(r.status == "pass" for r in summary.results)

    def test_hard_block_wins_over_soft(self):
        intent = Intent(
            intent_name="t",
            categoria="Estágios",
            keywords=["t"],
            blocking_checks=[
                "siga_matricula_ativa",  # hard
                "siga_reprovacoes_ultimo_semestre",  # soft
            ],
        )
        ctx = _make_ctx(
            intent=intent,
            siga={"matricula_status": "TRANCADA", "reprovacoes_ultimo_semestre": 3},
        )
        summary = run_checks(intent, ctx)
        assert summary.can_proceed is False
        assert summary.needs_justification is False  # hard block supersedes
        assert len(summary.hard_blocks) == 1
        assert len(summary.soft_blocks) == 1

    def test_soft_block_triggers_needs_justification(self):
        intent = Intent(
            intent_name="t",
            categoria="Estágios",
            keywords=["t"],
            blocking_checks=["siga_reprovacoes_ultimo_semestre"],
        )
        ctx = _make_ctx(
            intent=intent,
            siga={"reprovacoes_ultimo_semestre": 3},
        )
        summary = run_checks(intent, ctx)
        assert summary.can_proceed is False
        assert summary.needs_justification is True

    def test_unknown_checker_id_is_hard_block(self):
        intent = Intent(
            intent_name="t",
            categoria="Estágios",
            keywords=["t"],
            blocking_checks=["checker_que_nao_existe"],
        )
        summary = run_checks(intent, _make_ctx(intent=intent))
        assert len(summary.hard_blocks) == 1
        assert summary.hard_blocks[0].reason == "checker_not_registered"

    def test_checker_exception_becomes_hard_block(self):
        """A raising checker must degrade to hard_block, not crash the pipeline."""

        @register("__test_boom")
        def _boom(ctx):
            raise RuntimeError("simulated bug")

        try:
            intent = Intent(
                intent_name="t",
                categoria="Estágios",
                keywords=["t"],
                blocking_checks=["__test_boom"],
            )
            summary = run_checks(intent, _make_ctx(intent=intent))
            assert len(summary.hard_blocks) == 1
            assert "simulated bug" in summary.hard_blocks[0].reason
        finally:
            _CHECKERS.pop("__test_boom", None)

    def test_human_readable_summary_formats_blocks(self):
        summary = CheckSummary(
            results=[
                CheckResult("a", "hard_block", "hard reason"),
                CheckResult("b", "soft_block", "soft reason"),
                CheckResult("c", "pass"),
            ]
        )
        out = summary.human_readable()
        assert "Impedimentos (hard)" in out
        assert "a: hard reason" in out
        assert "Requer justificativa (soft)" in out
        assert "b: soft reason" in out

    def test_human_readable_all_pass(self):
        summary = CheckSummary(results=[CheckResult("a", "pass")])
        assert "Todas as condições satisfeitas" in summary.human_readable()


# ---------------------------------------------------------------------------
# Aditivo / Conclusão checkers (Marco IV)
# ---------------------------------------------------------------------------


class TestSeiProcessoTceExistente:
    def test_soft_block_when_sei_not_consulted(self):
        r = _invoke("sei_processo_tce_existente", _make_ctx(sei=None))
        assert r.status == "soft_block"

    def test_pass_when_vigente_tce_process_exists(self):
        r = _invoke(
            "sei_processo_tce_existente",
            _make_ctx(
                sei={
                    "processos_vigentes": [
                        {
                            "numero": "23075.000001/2026-00",
                            "tipo": "Graduação/Ensino Técnico: Estágios não Obrigatórios",
                        },
                    ]
                }
            ),
        )
        assert r.status == "pass"

    def test_hard_block_when_no_matching_tce_process(self):
        r = _invoke(
            "sei_processo_tce_existente",
            _make_ctx(
                sei={
                    "processos_vigentes": [
                        {
                            "numero": "23075.000002/2026-00",
                            "tipo": "Graduação: Aproveitamento de Disciplinas",
                        },
                    ]
                }
            ),
        )
        assert r.status == "hard_block"
        assert "TCE original" in r.reason


class TestAditivoAntesVencimentoTce:
    def test_soft_block_when_data_fim_missing(self):
        r = _invoke("aditivo_antes_vencimento_tce", _make_ctx(sei={}))
        assert r.status == "soft_block"

    def test_pass_when_today_before_data_fim(self):
        future = date.today() + timedelta(days=30)
        r = _invoke(
            "aditivo_antes_vencimento_tce",
            _make_ctx(sei={"tce_data_fim": _br(future)}),
        )
        assert r.status == "pass"

    def test_hard_block_when_tce_already_expired(self):
        past = date.today() - timedelta(days=5)
        r = _invoke(
            "aditivo_antes_vencimento_tce",
            _make_ctx(sei={"tce_data_fim": _br(past)}),
        )
        assert r.status == "hard_block"
        assert "venceu" in r.reason.lower()


class TestDuracaoTotalAte24Meses:
    def test_soft_block_when_dates_missing(self):
        r = _invoke("duracao_total_ate_24_meses", _make_ctx())
        assert r.status == "soft_block"

    def test_pass_when_total_under_24_months(self):
        inicio = date(2025, 6, 1)
        termino = date(2026, 12, 1)  # 18 meses
        r = _invoke(
            "duracao_total_ate_24_meses",
            _make_ctx(
                sei={"tce_data_inicio": _br(inicio)},
                vars={"data_termino_novo": _br(termino)},
            ),
        )
        assert r.status == "pass"

    def test_hard_block_when_total_exceeds_24_months(self):
        inicio = date(2024, 1, 15)
        termino = date(2026, 3, 15)  # 26 meses
        r = _invoke(
            "duracao_total_ate_24_meses",
            _make_ctx(
                sei={"tce_data_inicio": _br(inicio)},
                vars={"data_termino_novo": _br(termino)},
            ),
        )
        assert r.status == "hard_block"
        assert "24 meses" in r.reason


class TestRelatorioFinalAssinadoOrientador:
    def _email_with_attachment(self, filename: str, text: str) -> CheckContext:
        from ufpr_automation.core.models import AttachmentData

        att = AttachmentData(filename=filename, extracted_text=text)
        email = EmailData(sender="a@ufpr.br", subject="fim", body="", attachments=[att])
        return CheckContext(
            email=email,
            intent=Intent(intent_name="t", categoria="Estágios", keywords=["t"]),
            vars={},
        )

    def test_soft_block_when_relatorio_missing(self):
        ctx = self._email_with_attachment("outro.pdf", "conteúdo")
        r = _invoke("relatorio_final_assinado_orientador", ctx)
        assert r.status == "soft_block"

    def test_pass_when_signature_marker_near_orientador(self):
        ctx = self._email_with_attachment(
            "relatorio_final.pdf",
            "... conclusões ... Prof. Silva, orientador. Assinado eletronicamente em 10/04/2026.",
        )
        r = _invoke("relatorio_final_assinado_orientador", ctx)
        assert r.status == "pass"

    def test_hard_block_when_no_signature_near_orientador(self):
        ctx = self._email_with_attachment(
            "relatorio_final.pdf",
            "... orientador: Prof. Silva. Sem assinatura nenhuma por aqui.",
        )
        r = _invoke("relatorio_final_assinado_orientador", ctx)
        assert r.status == "hard_block"


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------


class TestParseBrDate:
    def test_valid_date(self):
        assert _parse_br_date("15/04/2026") == date(2026, 4, 15)

    def test_with_whitespace(self):
        assert _parse_br_date("  01/01/2025  ") == date(2025, 1, 1)

    def test_empty_string(self):
        assert _parse_br_date("") is None

    def test_invalid_format(self):
        assert _parse_br_date("2026-04-15") is None

    def test_invalid_date(self):
        assert _parse_br_date("32/13/2026") is None


class TestWorkingDaysBetween:
    def test_same_day(self):
        d = date(2026, 4, 15)  # Wednesday
        assert _working_days_between(d, d) == 0

    def test_end_before_start(self):
        assert _working_days_between(date(2026, 4, 16), date(2026, 4, 15)) == 0

    def test_one_working_day(self):
        # Wed to Thu = 1 working day
        assert _working_days_between(date(2026, 4, 15), date(2026, 4, 16)) == 1

    def test_over_weekend(self):
        # Fri to Mon = 1 working day (Mon)
        assert _working_days_between(date(2026, 4, 17), date(2026, 4, 20)) == 1

    def test_full_week(self):
        # Mon to next Mon = 5 working days
        assert _working_days_between(date(2026, 4, 13), date(2026, 4, 20)) == 5

    def test_two_weeks(self):
        # Mon to Mon+14 = 10 working days
        assert _working_days_between(date(2026, 4, 13), date(2026, 4, 27)) == 10


# ---------------------------------------------------------------------------
# Supervisor formação compatível (2026-04-22)
# ---------------------------------------------------------------------------


class TestSupervisorFormacaoCompativel:
    """Soft block quando formação do supervisor não é afim a Design.

    Regra: Art. 9 Lei 11.788/2008 + Art. 10 Res. CEPE 46/10. Quando ativa,
    a coordenação deve pedir Declaração de Experiência do Supervisor
    (form PROGRAD assinado pela chefia imediata).
    """

    def test_pass_when_design_grafico(self):
        r = _invoke(
            "supervisor_formacao_compativel",
            _make_ctx(vars={"formacao_supervisor": "Design Gráfico"}),
        )
        assert r.status == "pass"

    def test_pass_when_arquitetura(self):
        r = _invoke(
            "supervisor_formacao_compativel",
            _make_ctx(vars={"formacao_supervisor": "Arquitetura e Urbanismo"}),
        )
        assert r.status == "pass"

    def test_pass_case_insensitive_and_accent_insensitive(self):
        r = _invoke(
            "supervisor_formacao_compativel",
            _make_ctx(vars={"formacao_supervisor": "PUBLICIDADE"}),
        )
        assert r.status == "pass"
        r2 = _invoke(
            "supervisor_formacao_compativel",
            _make_ctx(vars={"formacao_supervisor": "comunicação visual"}),
        )
        assert r2.status == "pass"

    def test_soft_block_when_engenharia_civil(self):
        r = _invoke(
            "supervisor_formacao_compativel",
            _make_ctx(
                vars={
                    "formacao_supervisor": "Engenharia Civil",
                    "nome_supervisor": "João Silva",
                }
            ),
        )
        assert r.status == "soft_block"
        assert "Declaração de Experiência" in r.reason
        assert "prograd.ufpr.br" in r.reason
        assert "João Silva" in r.reason

    def test_soft_block_when_ciencias_contabeis(self):
        r = _invoke(
            "supervisor_formacao_compativel",
            _make_ctx(vars={"formacao_supervisor": "Ciências Contábeis"}),
        )
        assert r.status == "soft_block"

    def test_pass_when_formacao_missing(self):
        """Sem dado extraído, não bloqueia — outros checkers cuidam."""
        r = _invoke("supervisor_formacao_compativel", _make_ctx(vars={}))
        assert r.status == "pass"

    def test_pass_when_ux_design(self):
        r = _invoke(
            "supervisor_formacao_compativel",
            _make_ctx(vars={"formacao_supervisor": "UX Design Senior"}),
        )
        assert r.status == "pass"

    def test_pass_when_fotografia(self):
        r = _invoke(
            "supervisor_formacao_compativel",
            _make_ctx(vars={"formacao_supervisor": "Fotografia Profissional"}),
        )
        assert r.status == "pass"
