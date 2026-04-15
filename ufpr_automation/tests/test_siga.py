"""Tests for siga/ module — models and eligibility validation logic."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ufpr_automation.siga.client import SIGAClient
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


# ----------------------------------------------------------------------
# SIGAClient.validate_internship_eligibility — decision-logic tests
# ----------------------------------------------------------------------
#
# These tests mock the two helpers (``check_student_status`` and
# ``check_enrollment``) so we can exercise the rule engine in isolation
# without Playwright.  The SOUL.md §11 rules being validated:
#
#   1. student not found → single reason, not eligible
#   2. situacao trancada / cancelada → blocking reason
#   3. curriculo integralizado → blocking reason for non-obrigatorio
#   4. reprovacao por falta in previous semester → blocking reason
#   5. horas_estagio_semanais >= 30 → blocking reason (Lei 11.788 Art. 10)
#   6. horas_estagio_semanais >= 24 → warning (approaching limit)
#   7. horas_integralizadas below curriculo minimum → warning
#   8. no violations → eligible=True, no reasons

def _mk_client():
    """SIGAClient requires a Page; we never hit Playwright in these
    tests because both data-fetching helpers are mocked."""
    return SIGAClient(page=AsyncMock())


class TestValidateInternshipEligibility:
    @pytest.mark.asyncio
    async def test_student_not_found_returns_not_eligible(self):
        client = _mk_client()
        client.check_student_status = AsyncMock(return_value=None)
        client.check_enrollment = AsyncMock(return_value=None)

        result = await client.validate_internship_eligibility("GRR20191234")
        assert result.eligible is False
        assert len(result.reasons) == 1
        assert "nao encontrado" in result.reasons[0].lower()
        assert result.student is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("situacao", ["Trancada", "Cancelada", "cancelado"])
    async def test_matricula_trancada_blocks(self, situacao):
        client = _mk_client()
        client.check_student_status = AsyncMock(
            return_value=StudentStatus(grr="GRR20191234", situacao=situacao)
        )
        client.check_enrollment = AsyncMock(return_value=EnrollmentInfo())

        result = await client.validate_internship_eligibility("GRR20191234")
        assert result.eligible is False
        assert any("matricula" in r.lower() for r in result.reasons)

    @pytest.mark.asyncio
    async def test_curriculo_integralizado_blocks(self):
        client = _mk_client()
        client.check_student_status = AsyncMock(
            return_value=StudentStatus(grr="GRR20191234", situacao="Integralizada")
        )
        client.check_enrollment = AsyncMock(return_value=EnrollmentInfo())

        result = await client.validate_internship_eligibility("GRR20191234")
        assert result.eligible is False
        assert any("integralizado" in r.lower() for r in result.reasons)

    @pytest.mark.asyncio
    async def test_reprovacao_por_falta_blocks(self):
        client = _mk_client()
        client.check_student_status = AsyncMock(
            return_value=StudentStatus(grr="GRR20191234", situacao="Regular")
        )
        client.check_enrollment = AsyncMock(
            return_value=EnrollmentInfo(reprovacao_por_falta_anterior=True)
        )

        result = await client.validate_internship_eligibility("GRR20191234")
        assert result.eligible is False
        assert any("reprovacao" in r.lower() for r in result.reasons)

    @pytest.mark.asyncio
    async def test_weekly_hours_at_limit_blocks(self):
        """30h/week is the Lei 11.788 Art. 10 cap — reaching it blocks."""
        client = _mk_client()
        client.check_student_status = AsyncMock(
            return_value=StudentStatus(grr="GRR20191234", situacao="Regular")
        )
        client.check_enrollment = AsyncMock(
            return_value=EnrollmentInfo(horas_estagio_semanais=30)
        )

        result = await client.validate_internship_eligibility("GRR20191234")
        assert result.eligible is False
        assert any("11.788" in r or "30h" in r for r in result.reasons)

    @pytest.mark.asyncio
    async def test_weekly_hours_near_limit_warns(self):
        """>=24h (30 - 6) should warn but not block."""
        client = _mk_client()
        client.check_student_status = AsyncMock(
            return_value=StudentStatus(grr="GRR20191234", situacao="Regular")
        )
        client.check_enrollment = AsyncMock(
            return_value=EnrollmentInfo(horas_estagio_semanais=25)
        )

        result = await client.validate_internship_eligibility("GRR20191234")
        assert result.eligible is True
        assert result.reasons == []
        assert any("proxima do limite" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_curriculo_2016_low_hours_warns(self):
        client = _mk_client()
        client.check_student_status = AsyncMock(
            return_value=StudentStatus(
                grr="GRR20191234",
                situacao="Regular",
                horas_integralizadas=500,
                curriculo="2016",
            )
        )
        client.check_enrollment = AsyncMock(return_value=EnrollmentInfo())

        result = await client.validate_internship_eligibility("GRR20191234")
        assert result.eligible is True
        assert any("1.440h" in w for w in result.warnings)

    @pytest.mark.asyncio
    async def test_curriculo_2020_low_hours_warns(self):
        client = _mk_client()
        client.check_student_status = AsyncMock(
            return_value=StudentStatus(
                grr="GRR20191234",
                situacao="Regular",
                horas_integralizadas=500,
                curriculo="2020",
            )
        )
        client.check_enrollment = AsyncMock(return_value=EnrollmentInfo())

        result = await client.validate_internship_eligibility("GRR20191234")
        assert result.eligible is True
        assert any("1.035h" in w for w in result.warnings)

    @pytest.mark.asyncio
    async def test_clean_case_is_eligible(self):
        client = _mk_client()
        client.check_student_status = AsyncMock(
            return_value=StudentStatus(
                grr="GRR20191234",
                situacao="Regular",
                horas_integralizadas=1500,
                curriculo="2020",
            )
        )
        client.check_enrollment = AsyncMock(
            return_value=EnrollmentInfo(horas_estagio_semanais=10)
        )

        result = await client.validate_internship_eligibility("GRR20191234")
        assert result.eligible is True
        assert result.reasons == []
        assert result.warnings == []

    @pytest.mark.asyncio
    async def test_multiple_violations_aggregated(self):
        """Trancada + reprovacao + hours-at-limit → three reasons."""
        client = _mk_client()
        client.check_student_status = AsyncMock(
            return_value=StudentStatus(grr="GRR20191234", situacao="Trancada")
        )
        client.check_enrollment = AsyncMock(
            return_value=EnrollmentInfo(
                reprovacao_por_falta_anterior=True,
                horas_estagio_semanais=30,
            )
        )

        result = await client.validate_internship_eligibility("GRR20191234")
        assert result.eligible is False
        assert len(result.reasons) == 3
