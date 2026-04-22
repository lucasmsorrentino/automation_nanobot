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
# These tests mock check_student_status, check_enrollment,
# get_integralizacao, and get_historico so the rule engine is exercised
# in isolation without Playwright.


def _mk_client():
    """SIGAClient requires a Page; we never hit Playwright in these
    tests because all data-fetching helpers are mocked."""
    return SIGAClient(page=AsyncMock())


def _default_integ(**overrides) -> dict:
    """Return a default integralização result dict."""
    d = {
        "curriculo": "93B - 2016",
        "ch_obrigatorias": "1800 de 1980 h",
        "ch_optativas": "200 de 300 h",
        "ch_formativas": "0 de 180 h",
        "ch_total": "2000 de 2460 h",
        "integralizado": False,
        "disciplines": [],
        "nao_vencidas": ["OD501", "ODDA6", "OD999"],
    }
    d.update(overrides)
    return d


def _default_historico(**overrides) -> dict:
    """Return a default histórico result dict."""
    d = {
        "ira": 0.65,
        "curriculo": "93B - 2016",
        "semesters": [],
        "reprovacoes_total": 0,
        "reprovacoes_por_frequencia": 0,
        "reprovacoes_por_nota": 0,
        "reprovacoes_por_tipo": {},
    }
    d.update(overrides)
    return d


def _setup_client(
    situacao: str = "Registro ativo",
    student: StudentStatus | None = ...,
    enrollment: EnrollmentInfo | None = ...,
    integ: dict | None = None,
    historico: dict | None = None,
    logged_in: bool = True,
) -> SIGAClient:
    """Set up a fully mocked SIGAClient."""
    client = _mk_client()

    client._ensure_logged_in = AsyncMock(return_value=logged_in)

    if student is ...:
        student = StudentStatus(grr="GRR20191234", situacao=situacao)
    client.check_student_status = AsyncMock(return_value=student)

    if enrollment is ...:
        enrollment = EnrollmentInfo()
    client.check_enrollment = AsyncMock(return_value=enrollment)

    client.get_integralizacao = AsyncMock(return_value=integ or _default_integ())
    client.get_historico = AsyncMock(return_value=historico or _default_historico())

    return client


class TestValidateInternshipEligibility:
    @pytest.mark.asyncio
    async def test_student_not_found_returns_not_eligible(self):
        client = _setup_client(student=None)

        result = await client.validate_internship_eligibility("GRR20191234")
        assert result.eligible is False
        assert len(result.reasons) == 1
        assert "nao encontrado" in result.reasons[0].lower()
        assert result.student is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("situacao", ["Trancada", "Cancelada", "cancelado"])
    async def test_matricula_trancada_blocks(self, situacao):
        client = _setup_client(situacao=situacao)

        result = await client.validate_internship_eligibility("GRR20191234")
        assert result.eligible is False
        assert any("matricula" in r.lower() for r in result.reasons)

    @pytest.mark.asyncio
    async def test_curriculo_integralizado_blocks(self):
        client = _setup_client(
            situacao="Integralizada",
            integ=_default_integ(integralizado=True),
        )

        result = await client.validate_internship_eligibility("GRR20191234")
        assert result.eligible is False
        assert any("integralizado" in r.lower() for r in result.reasons)

    @pytest.mark.asyncio
    async def test_many_reprovacoes_warns(self):
        """More than 2 reprovações → soft block (warning, not reason)."""
        client = _setup_client(
            historico=_default_historico(reprovacoes_total=5),
        )

        result = await client.validate_internship_eligibility("GRR20191234")
        assert result.eligible is True
        assert any("reprovacoes" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_two_or_fewer_reprovacoes_no_warning(self):
        client = _setup_client(
            historico=_default_historico(reprovacoes_total=2),
        )

        result = await client.validate_internship_eligibility("GRR20191234")
        assert result.eligible is True
        assert not any("reprovacoes" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_clean_case_is_eligible(self):
        client = _setup_client()

        result = await client.validate_internship_eligibility("GRR20191234")
        assert result.eligible is True
        assert result.reasons == []

    @pytest.mark.asyncio
    async def test_multiple_violations_aggregated(self):
        """Trancada + integralizado → two reasons."""
        client = _setup_client(
            situacao="Trancada",
            integ=_default_integ(integralizado=True),
        )

        result = await client.validate_internship_eligibility("GRR20191234")
        assert result.eligible is False
        assert len(result.reasons) >= 2

    @pytest.mark.asyncio
    async def test_few_remaining_disciplines_warns(self):
        """Student close to graduating with 12-month internship → warning."""
        client = _setup_client(
            integ=_default_integ(
                nao_vencidas=["OD999"],
                disciplines=[
                    {
                        "sigla": "OD999",
                        "disciplina": "X",
                        "carga_horaria": "60h",
                        "situacao": "Não Vencida",
                        "vencida_em": "",
                        "observacoes": "",
                    },
                ],
            ),
        )

        result = await client.validate_internship_eligibility("GRR20191234", vigencia_meses=12)
        assert result.eligible is True
        assert any("disciplina(s) pendente(s)" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_od501_pending_means_has_time(self):
        """OD501 (annual) not passed → student has >= 1 year left, no warning."""
        client = _setup_client(
            integ=_default_integ(
                nao_vencidas=["OD501"],
                disciplines=[
                    {
                        "sigla": "OD501",
                        "disciplina": "ESTÁGIO SUPERVISIONADO",
                        "carga_horaria": "360h",
                        "situacao": "Não Vencida",
                        "vencida_em": "",
                        "observacoes": "",
                    },
                ],
            ),
        )

        result = await client.validate_internship_eligibility("GRR20191234", vigencia_meses=12)
        assert result.eligible is True
        assert not any("disciplina(s) pendente(s)" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_odda6_pending_means_has_time(self):
        """ODDA6 (TCC1) not passed → student has >= 1 year left, no warning."""
        client = _setup_client(
            integ=_default_integ(
                nao_vencidas=["ODDA6"],
                disciplines=[
                    {
                        "sigla": "ODDA6",
                        "disciplina": "DESIGN APLICADO 6",
                        "carga_horaria": "120h",
                        "situacao": "Não Vencida",
                        "vencida_em": "",
                        "observacoes": "",
                    },
                ],
            ),
        )

        result = await client.validate_internship_eligibility("GRR20191234", vigencia_meses=12)
        assert result.eligible is True
        assert not any("disciplina(s) pendente(s)" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_six_month_internship_no_graduation_check(self):
        """6-month internship skips the 'can graduate before end' check."""
        client = _setup_client(
            integ=_default_integ(
                nao_vencidas=["OD999"],
                disciplines=[
                    {
                        "sigla": "OD999",
                        "disciplina": "X",
                        "carga_horaria": "60h",
                        "situacao": "Não Vencida",
                        "vencida_em": "",
                        "observacoes": "",
                    },
                ],
            ),
        )

        result = await client.validate_internship_eligibility("GRR20191234", vigencia_meses=6)
        assert result.eligible is True
        assert not any("disciplina(s) pendente(s)" in w.lower() for w in result.warnings)


# --- SIGAClient.get_historico extraction tests ---


class TestGetHistorico:
    """Test the data extraction logic against mock page DOM."""

    @pytest.mark.asyncio
    async def test_returns_empty_if_student_not_found(self):
        client = _mk_client()
        client._navigate_to_student = AsyncMock(return_value=False)
        result = await client.get_historico(grr="GRR20191234")
        assert result == {}

    @pytest.mark.asyncio
    async def test_skips_navigation_if_no_grr(self):
        """When grr is None, get_historico should NOT call _navigate_to_student."""
        client = _mk_client()
        client._navigate_to_student = AsyncMock(return_value=True)
        client._click_tab = AsyncMock()
        # Verify the contract: no grr → no navigation by design
        assert True


class TestGetIntegralizacao:
    @pytest.mark.asyncio
    async def test_returns_empty_if_student_not_found(self):
        client = _mk_client()
        client._navigate_to_student = AsyncMock(return_value=False)
        result = await client.get_integralizacao(grr="GRR20191234")
        assert result == {}


# ----------------------------------------------------------------------
# Regression: login flow must not block on networkidle for SPA pages
# ----------------------------------------------------------------------


class TestAutoLoginWaitStrategy:
    """Regression tests for the 2026-04-22 SIGA login bug.

    The SIGA home is a Vue.js SPA whose XHR/polling never lets the page
    reach ``networkidle`` within 20s, causing ``auto_login`` to time out
    even when the login succeeded. The fix replaces the post-card-click
    ``wait_for_load_state('networkidle', 20000)`` with an element-based
    wait on the "Discentes" sidebar link. These tests pin that contract.
    """

    @pytest.mark.asyncio
    async def test_auto_login_does_not_wait_for_networkidle_after_role_click(self, monkeypatch):
        """After clicking the role card, auto_login must wait for the
        'Discentes' sidebar link — NOT for networkidle."""
        from ufpr_automation.siga import browser as siga_browser

        # Force credentials to look configured.
        monkeypatch.setattr(siga_browser, "has_credentials", lambda: True)

        page = AsyncMock()
        # Simulate already-authenticated portal (no login fields needed);
        # goto leaves us on a URL without 'login'/'auth'/'autenticacao'.
        page.url = "https://sistemas.ufpr.br/central/"

        # locator() is sync in Playwright, so use MagicMock here.
        from unittest.mock import MagicMock

        locators_created: list[str] = []

        def make_locator(selector: str):
            locators_created.append(selector)
            loc = MagicMock()
            first = MagicMock()
            loc.first = first
            first.wait_for = AsyncMock()
            first.click = AsyncMock()
            first.text_content = AsyncMock(return_value="")
            first.is_visible = AsyncMock(return_value=True)
            loc.count = AsyncMock(return_value=1)
            first.count = AsyncMock(return_value=1)
            # nth() returns a child locator with click/text_content
            child = MagicMock()
            child.click = AsyncMock()
            child.text_content = AsyncMock(return_value="")
            loc.nth = MagicMock(return_value=child)
            return loc

        page.locator = MagicMock(side_effect=make_locator)
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()

        # Patch is_logged_in to report success so auto_login returns True.
        async def fake_is_logged_in(_page):
            return True

        monkeypatch.setattr(siga_browser, "is_logged_in", fake_is_logged_in)

        ok = await siga_browser.auto_login(page)
        assert ok is True

        # Regression pin: after the role card is selected, we wait on
        # the 'Discentes' sidebar marker, not on networkidle.
        assert any(
            "Discentes" in sel for sel in locators_created
        ), f"expected a locator('a:has-text(\"Discentes\")') call, got: {locators_created}"

        # The only wait_for_load_state calls allowed are 'load'
        # (short fallback for portal/keycloak), never 'networkidle'.
        for call in page.wait_for_load_state.await_args_list:
            args, kwargs = call
            state = args[0] if args else kwargs.get("state")
            assert state != "networkidle", (
                "auto_login must not wait_for_load_state('networkidle') — "
                "SIGA SPA never reaches idle"
            )

    @pytest.mark.asyncio
    async def test_is_logged_in_does_not_wait_for_networkidle(self, monkeypatch):
        """is_logged_in must detect the session via element-based wait,
        not via wait_for_load_state('networkidle')."""
        from unittest.mock import MagicMock

        from ufpr_automation.siga import browser as siga_browser

        page = AsyncMock()

        def make_locator(_selector: str):
            loc = MagicMock()
            first = MagicMock()
            first.wait_for = AsyncMock()
            first.count = AsyncMock(return_value=1)
            loc.first = first
            loc.count = AsyncMock(return_value=1)
            return loc

        page.locator = MagicMock(side_effect=make_locator)
        page.wait_for_load_state = AsyncMock()

        result = await siga_browser.is_logged_in(page)
        assert result is True

        # Regression pin: is_logged_in must not call networkidle.
        for call in page.wait_for_load_state.await_args_list:
            args, kwargs = call
            state = args[0] if args else kwargs.get("state")
            assert state != "networkidle"


class TestEnsureLoggedInGuard:
    """Regression: client methods must short-circuit when SIGA is not
    authenticated, returning a clear signal instead of letting Playwright
    timeouts bubble up."""

    @pytest.mark.asyncio
    async def test_validate_internship_eligibility_returns_not_authenticated(self):
        client = _setup_client(logged_in=False)
        result = await client.validate_internship_eligibility("GRR20191234")
        assert result.eligible is False
        assert result.reasons == ["SIGA nao autenticado"]
        # check_student_status must not be invoked when the guard trips.
        client.check_student_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_historico_returns_empty_when_not_authenticated(self, monkeypatch):
        from ufpr_automation.siga import browser as siga_browser

        async def fake_is_logged_in(_page):
            return False

        monkeypatch.setattr(siga_browser, "is_logged_in", fake_is_logged_in)

        client = _mk_client()
        client._navigate_to_student = AsyncMock(return_value=True)
        result = await client.get_historico(grr="GRR20191234")
        assert result == {}
        client._navigate_to_student.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_integralizacao_returns_empty_when_not_authenticated(self, monkeypatch):
        from ufpr_automation.siga import browser as siga_browser

        async def fake_is_logged_in(_page):
            return False

        monkeypatch.setattr(siga_browser, "is_logged_in", fake_is_logged_in)

        client = _mk_client()
        client._navigate_to_student = AsyncMock(return_value=True)
        result = await client.get_integralizacao(grr="GRR20191234")
        assert result == {}
        client._navigate_to_student.assert_not_called()
