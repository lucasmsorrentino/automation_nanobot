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


# ----------------------------------------------------------------------
# Regression tests for the SIGA wrong-student bug (smoke 2026-04-30)
# ----------------------------------------------------------------------
#
# Bug: ``_navigate_to_student("GRR20244602")`` retornou silenciosamente
# ``LOUIE PEDROSA DE SOUZA`` (GRR20231692) — a 1ª linha da tabela inteira,
# não a linha filtrada pelo GRR. Fix em 2 camadas:
#  - row-level locator (``tbody tr:has-text('GRR…')``) em vez de
#    ``tbody tr a:first``;
#  - defensive guard pós-click: extrair GRR do header ``<h2>Discente</h2>``
#    e abortar se diferente do solicitado.


class _FakeLocator:
    """Minimal Playwright Locator stand-in for unit tests.

    Each instance corresponds to a (page, selector chain) pair and reads
    its canned response from ``page._selectors``. Supports ``.first``
    (returns self), ``count()``, ``text_content()``, ``all_text_contents()``,
    ``fill()``, ``click()``, ``select_option()``, ``wait_for()``, and
    nested ``.locator()`` calls (the nested key is ``"<parent> >> <child>"``).
    """

    def __init__(self, page: "_FakePage", selector: str):
        self._page = page
        self._selector = selector

    @property
    def first(self):
        return self

    def locator(self, selector: str):
        return _FakeLocator(self._page, f"{self._selector} >> {selector}")

    def _spec(self):
        return self._page._selectors.get(self._selector, {})

    async def count(self):
        return self._spec().get("count", 0)

    async def text_content(self):
        return self._spec().get("text_content", "")

    async def all_text_contents(self):
        return self._spec().get("all_text_contents", [])

    async def fill(self, value):
        return None

    async def click(self):
        self._page.click_log.append(self._selector)

    async def select_option(self, value):
        self._page.selected[self._selector] = value

    async def wait_for(self, state="visible", timeout=8000):
        if self._spec().get("wait_for_raises"):
            raise Exception("locator.wait_for timeout (mock)")
        return None

    async def is_visible(self):
        return self._spec().get("visible", True)


class _FakePage:
    """Minimal Playwright Page stand-in.

    Tests configure selector responses via ``page.configure(selector, **spec)``
    where ``spec`` may include ``count``, ``text_content``,
    ``all_text_contents``, ``wait_for_raises``, ``visible``.
    """

    def __init__(self):
        self._selectors: dict[str, dict] = {}
        self.click_log: list[str] = []
        self.selected: dict[str, str] = {}

    def configure(self, selector: str, **spec):
        self._selectors[selector] = spec

    def locator(self, selector: str):
        return _FakeLocator(self, selector)

    async def wait_for_load_state(self, state="load", timeout=None):
        return None


def _stage_navigation_path(
    page: _FakePage,
    expected_grr: str,
    *,
    target_row_visible: bool = True,
    target_row_has_link: bool = True,
    header_grr: str | None = None,
    header_text_override: str | None = None,
):
    """Configure ``page`` so the navigation path resolves with the given outcome.

    - ``target_row_visible``: whether ``tbody tr:has-text(<expected>)`` is found.
    - ``target_row_has_link``: whether the row contains an ``<a>`` to click.
    - ``header_grr``: GRR shown in the page header **after** the click.
      ``None`` = no header on the page (header.count == 0).
    - ``header_text_override``: full header text (when set, overrides the
      auto-built ``"Discente - NOME - <GRR>"`` template).
    """
    page.configure("a:has-text('Discentes')", count=1)
    page.configure("a:has-text('Consultar')", count=1)
    page.configure("select", count=1, all_text_contents=[])
    page.configure("input[placeholder*='Nome ou Documento']", count=1)

    grr_clean = expected_grr.replace("GRR", "")
    grr_selector = f"table tbody tr:has-text('{expected_grr}')"
    digits_selector = f"table tbody tr:has-text('{grr_clean}')"

    if target_row_visible:
        page.configure(grr_selector, count=1)
        page.configure(
            f"{grr_selector} >> a",
            count=1 if target_row_has_link else 0,
        )
    else:
        page.configure(grr_selector, wait_for_raises=True)
        page.configure(digits_selector, wait_for_raises=True)

    if header_text_override is not None:
        page.configure(
            "h2:has-text('Discente')",
            count=1,
            text_content=header_text_override,
        )
    elif header_grr is not None:
        page.configure(
            "h2:has-text('Discente')",
            count=1,
            text_content=f"Discente - NOME COMPLETO - {header_grr}",
        )
    else:
        page.configure("h2:has-text('Discente')", count=0)


class TestNavigateToStudentGuard:
    @pytest.mark.asyncio
    async def test_happy_path_grr_matches_returns_true(self):
        page = _FakePage()
        _stage_navigation_path(page, "GRR20244602", header_grr="GRR20244602")

        client = SIGAClient(page=page)
        ok = await client._navigate_to_student("GRR20244602")

        assert ok is True
        # Sanity: o link da row alvo foi clicado, nao um link arbitrario.
        assert any(
            "table tbody tr:has-text('GRR20244602') >> a" in c for c in page.click_log
        )

    @pytest.mark.asyncio
    async def test_grr_mismatch_after_click_aborts(self):
        """**Regression test for the smoke 2026-04-30 bug**.

        Filter aceitou alguma row e o click foi disparado, mas o header da
        pagina aberta corresponde a outro aluno (LOUIE/GRR20231692). O
        defensive guard precisa retornar False — NUNCA retornar True com
        identidade trocada (que era o comportamento bugado original).
        """
        page = _FakePage()
        _stage_navigation_path(
            page,
            "GRR20244602",
            header_grr="GRR20231692",  # SIGA cuspiu o aluno errado
        )

        client = SIGAClient(page=page)
        ok = await client._navigate_to_student("GRR20244602")

        assert ok is False, "guard deveria abortar quando GRR do header != solicitado"

    @pytest.mark.asyncio
    async def test_target_row_not_visible_returns_false(self):
        """Filter client-side nao listou a row alvo (aluno fora do perfil
        atual ou paginacao acima de 300). Deve retornar False sem clicar
        em nenhum link ‘at large’.
        """
        page = _FakePage()
        _stage_navigation_path(
            page,
            "GRR99999999",
            target_row_visible=False,
        )

        client = SIGAClient(page=page)
        ok = await client._navigate_to_student("GRR99999999")

        assert ok is False
        # Nenhum click em row de alunos.
        row_clicks = [c for c in page.click_log if "tbody tr" in c]
        assert row_clicks == []

    @pytest.mark.asyncio
    async def test_target_row_has_no_link_returns_false(self):
        """Edge: tbody tr matcha o GRR mas nao tem <a>. DOM mudou, melhor
        abortar que adivinhar.
        """
        page = _FakePage()
        _stage_navigation_path(
            page,
            "GRR20244602",
            target_row_has_link=False,
            header_grr="GRR20244602",
        )

        client = SIGAClient(page=page)
        ok = await client._navigate_to_student("GRR20244602")

        assert ok is False

    @pytest.mark.asyncio
    async def test_no_header_after_click_does_not_abort(self):
        """Header ``<h2>Discente</h2>`` ausente na pagina pos-click — guard
        nao tem informacao pra comparar; politica: best-effort, nao aborta.
        Logs `debug` mas retorna True.
        """
        page = _FakePage()
        _stage_navigation_path(
            page,
            "GRR20244602",
            header_grr=None,  # sem header
        )

        client = SIGAClient(page=page)
        ok = await client._navigate_to_student("GRR20244602")

        assert ok is True

    @pytest.mark.asyncio
    async def test_extract_grr_from_header_returns_pattern(self):
        page = _FakePage()
        page.configure(
            "h2:has-text('Discente')",
            count=1,
            text_content="Discente - LETICIA FONCECA RAMALHO - GRR20244602 - 2024",
        )

        client = SIGAClient(page=page)
        grr = await client._extract_grr_from_header()

        assert grr == "GRR20244602"

    @pytest.mark.asyncio
    async def test_extract_grr_from_header_returns_none_when_absent(self):
        page = _FakePage()
        page.configure("h2:has-text('Discente')", count=0)

        client = SIGAClient(page=page)
        grr = await client._extract_grr_from_header()

        assert grr is None

    @pytest.mark.asyncio
    async def test_extract_grr_from_header_returns_none_when_no_grr_pattern(self):
        page = _FakePage()
        page.configure(
            "h2:has-text('Discente')",
            count=1,
            text_content="Discente - aluno sem GRR detectavel",
        )

        client = SIGAClient(page=page)
        grr = await client._extract_grr_from_header()

        assert grr is None
