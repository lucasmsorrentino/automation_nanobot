"""Tests for siga/ module — models and eligibility validation logic."""

from __future__ import annotations

from ufpr_automation.siga.models import EligibilityResult, EnrollmentInfo, StudentStatus


class TestStudentStatus:
    def test_default_values(self):
        s = StudentStatus()
        assert s.grr == ""
        assert s.situacao == ""
        assert s.horas_integralizadas == 0

    def test_with_values(self):
        s = StudentStatus(
            grr="GRR20191234",
            nome="Joao Silva",
            curso="Design Grafico",
            situacao="Regular",
            periodo_atual=6,
            horas_integralizadas=1200,
            curriculo="2020",
        )
        assert s.grr == "GRR20191234"
        assert s.situacao == "Regular"


class TestEnrollmentInfo:
    def test_default_values(self):
        e = EnrollmentInfo()
        assert e.reprovacao_por_falta_anterior is False
        assert e.horas_estagio_semanais == 0

    def test_with_active_internship(self):
        e = EnrollmentInfo(
            grr="GRR20191234",
            estagios_ativos=1,
            horas_estagio_semanais=20,
        )
        assert e.estagios_ativos == 1
        assert e.horas_estagio_semanais == 20


class TestEligibilityResult:
    def test_eligible_by_default_is_false(self):
        r = EligibilityResult()
        assert r.eligible is False

    def test_eligible_with_no_reasons(self):
        r = EligibilityResult(eligible=True, reasons=[], warnings=[])
        assert r.eligible is True

    def test_ineligible_with_reasons(self):
        r = EligibilityResult(
            eligible=False,
            reasons=["Matricula trancada"],
            warnings=[],
        )
        assert not r.eligible
        assert len(r.reasons) == 1

    def test_eligible_with_warnings(self):
        r = EligibilityResult(
            eligible=True,
            reasons=[],
            warnings=["Carga horaria proxima do limite"],
        )
        assert r.eligible
        assert len(r.warnings) == 1
