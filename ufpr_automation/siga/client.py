"""SIGA client for querying student status and validating internship eligibility.

All operations are READ-ONLY. No modifications are made in SIGA.
Eligibility rules are based on SOUL.md section 11 and coordinator guidance.
Selectors come from the grounded manifest (siga_selectors.yaml).
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

from ufpr_automation.siga import browser as siga_browser
from ufpr_automation.siga.models import EligibilityResult, EnrollmentInfo, StudentStatus
from ufpr_automation.utils.logging import logger

# Disciplines that indicate >= 1 year remaining in the curriculum
_ANNUAL_ESTAGIO = "OD501"  # Estágio Supervisionado (annual, 360h)
_TCC1 = "ODDA6"  # TCC1 (prerequisite for TCC2)

_SPINNER_TIMEOUT = 60000


async def _wait_tab_content(page: Page, pane_id: str, timeout: int = _SPINNER_TIMEOUT) -> None:
    """Wait for Vue.js async content inside a specific tab pane."""
    pane = page.locator(f"#{pane_id}")
    spinner = pane.locator("text=Carregando")
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        if await spinner.count() == 0:
            break
        try:
            if not await spinner.first.is_visible():
                break
        except Exception:
            break
        await asyncio.sleep(2)
    await asyncio.sleep(0.5)


class SIGAClient:
    """Client for read-only operations on SIGA via Playwright."""

    def __init__(self, page: Page):
        self._page = page

    async def _ensure_logged_in(self) -> bool:
        """Guard: abort early if the SIGA session is not authenticated.

        Without this, every query method would first hit a 15s
        ``wait_for_load_state("networkidle")`` inside ``_navigate_to_student``
        (unreachable when not logged in), wasting time and surfacing a
        confusing Playwright timeout instead of a clear 'not authenticated'
        signal.
        """
        if await siga_browser.is_logged_in(self._page):
            return True
        logger.warning("SIGA: sessao nao autenticada — abortando consulta")
        return False

    async def _navigate_to_student(self, grr: str) -> bool:
        """Navigate sidebar Discentes > Consultar, search by GRR, click matching row.

        **Fix 2026-04-22**: a lista de discentes usa paginação server-side
        (default: 20 por página) e o campo ``input[placeholder='Nome ou
        Documento']`` filtra **client-side** apenas sobre a página carregada
        — se o aluno estiver além da 20ª linha, o filtro não acha. Mitigação:
        bumpar o combo ``Items por página`` para 300 antes do filter.

        **Fix 2026-04-30**: o smoke da Letícia (GRR20244602) retornou silenciosamente
        ``LOUIE PEDROSA DE SOUZA`` (GRR20231692) — bug de **identidade trocada**.
        Causa: ``table tbody tr a:first`` pegava a 1ª linha **da tabela inteira**,
        não filtrada (filtro client-side com debounce não estabilizou em 2s; ou
        outras causas). Fix:
          1. Esperar até a row com o GRR alvo aparecer (com fallback pra row
             contendo só os dígitos sem "GRR"). Sem timeout-feliz, returna False.
          2. Clicar no link **dentro daquela row específica**, não em ``.first``
             global.
          3. Defensive guard pós-click: extrair o GRR do header da página de
             detalhes; se diferente do solicitado, logar ERROR e retornar False.
             Esse guard é a rede de segurança final que protege todos os 4
             call sites (``check_student_status``, ``get_historico``,
             ``get_integralizacao``, ``validate_internship_eligibility``).
        """
        grr_clean = re.sub(r"[^0-9]", "", grr)
        expected_grr = f"GRR{grr_clean}"
        logger.info("SIGA: consultando aluno %s", expected_grr)

        discentes = self._page.locator("a:has-text('Discentes')").first
        await discentes.click()
        await asyncio.sleep(0.5)

        consultar = self._page.locator("a:has-text('Consultar')").first
        await consultar.click()
        await self._page.wait_for_load_state("domcontentloaded", timeout=15000)
        await asyncio.sleep(1.5)

        # Per-page combo (first <select> on the page, options 10/20/50/100/300).
        # Saltamos para 300 para que o filtro client-side do campo abaixo veja
        # a lista toda (ou quase toda) do perfil atual.
        try:
            page_size_combo = self._page.locator("select").first
            if await page_size_combo.count() > 0:
                options = await page_size_combo.locator("option").all_text_contents()
                if any("300" in o for o in options):
                    await page_size_combo.select_option("300")
                    await asyncio.sleep(2)
                    logger.debug("SIGA: paginacao ajustada para 300/pagina")
        except Exception as e:
            logger.debug("SIGA: falha ao ajustar paginacao (nao-fatal): %s", e)

        search_field = self._page.locator("input[placeholder*='Nome ou Documento']").first
        await search_field.fill(grr_clean)

        # Esperar até a row com o GRR alvo ficar visível (filter client-side
        # com debounce; sleep fixo de 2s era unreliable). Tentamos primeiro
        # com prefixo "GRR" no texto da row; alguns SIGA layouts mostram só
        # os dígitos no cell, então fallback para grr_clean puro.
        target_row = self._page.locator(
            f"table tbody tr:has-text('{expected_grr}')"
        ).first
        try:
            await target_row.wait_for(state="visible", timeout=8000)
        except Exception:
            target_row = self._page.locator(
                f"table tbody tr:has-text('{grr_clean}')"
            ).first
            try:
                await target_row.wait_for(state="visible", timeout=4000)
            except Exception:
                logger.warning(
                    "SIGA: aluno %s nao encontrado apos filter — "
                    "filtro client-side nao listou a row, ou aluno nao "
                    "esta no profile/perfil atual",
                    expected_grr,
                )
                return False

        link_in_target_row = target_row.locator("a").first
        if await link_in_target_row.count() == 0:
            logger.warning(
                "SIGA: row com %s nao tem link clicavel — DOM mudou?",
                expected_grr,
            )
            return False

        await link_in_target_row.click()
        await self._page.wait_for_load_state("domcontentloaded", timeout=15000)

        # Defensive guard: confirmar que a pagina aberta corresponde ao GRR
        # pedido. Se diferente, ABORTAR — nao retornar o aluno errado pra
        # cima da call chain, onde checkers e SEI ops podem ser disparadas
        # contra a pessoa errada.
        actual_grr = await self._extract_grr_from_header()
        if actual_grr and actual_grr != expected_grr:
            logger.error(
                "SIGA: identidade trocada apos navegacao — pediu %s, pagina mostra %s. "
                "Abortando consulta. (provavel bug no filter client-side ou "
                "race no debounce do search field)",
                expected_grr,
                actual_grr,
            )
            return False
        if not actual_grr:
            # Header sem GRR detectavel — nao abortamos (header pode ter
            # markup inesperado), mas logamos pra debug futuro.
            logger.debug(
                "SIGA: nao consegui extrair GRR do header pos-navegacao para %s; "
                "guard de identidade desativado para esta consulta",
                expected_grr,
            )

        return True

    async def _extract_grr_from_header(self) -> str | None:
        """Extract the GRR shown in the student detail page header.

        Returns ``GRR<digits>`` or None if header is missing/malformed.
        Used by ``_navigate_to_student`` as a post-navigation safety check
        and by ``_extract_info_gerais`` to populate ``info["grr"]``.
        """
        header = self._page.locator("h2:has-text('Discente')").first
        if await header.count() == 0:
            return None
        txt = (await header.text_content() or "").strip()
        m = re.search(r"GRR\d+", txt)
        return m.group() if m else None

    async def _click_tab(self, tab_text: str, pane_id: str) -> None:
        """Click a student detail tab and wait for its content to load."""
        tab = self._page.locator(f"a:has-text('{tab_text}')").first
        await tab.click()
        await _wait_tab_content(self._page, pane_id)

    async def _extract_info_gerais(self) -> dict[str, str]:
        """Extract basic info from the Informações Gerais tab (default)."""
        info: dict[str, str] = {}
        pane = self._page.locator("#tab_informacoes")

        for label_text, key in [
            ("Status", "status"),
            ("Data de Matrícula", "data_matricula"),
        ]:
            el = pane.locator(
                f"xpath=.//*[contains(text(),'{label_text}')]/following-sibling::*[1]"
            )
            if await el.count() > 0:
                info[key] = (await el.first.text_content() or "").strip()

        grr_from_header = await self._extract_grr_from_header()
        if grr_from_header:
            info["grr"] = grr_from_header
        header = self._page.locator("h2:has-text('Discente')").first
        if await header.count() > 0:
            txt = (await header.text_content() or "").strip()
            parts = txt.split(" - ")
            if len(parts) >= 2:
                info["nome"] = parts[1].strip().split(" - ")[0].strip()

        return info

    async def check_student_status(self, grr: str) -> StudentStatus | None:
        """Look up a student's academic status by GRR."""
        try:
            if not await self._ensure_logged_in():
                return None
            if not await self._navigate_to_student(grr):
                return None

            info = await self._extract_info_gerais()
            grr_clean = re.sub(r"[^0-9]", "", grr)
            student = StudentStatus(grr=f"GRR{grr_clean}")
            student.nome = info.get("nome", "")
            student.situacao = info.get("status", "")

            logger.info("SIGA: aluno %s — %s — %s", student.grr, student.nome, student.situacao)
            return student

        except Exception as e:
            logger.error("SIGA: falha ao consultar aluno %s: %s", grr, e)
            return None

    async def get_historico(self, grr: str | None = None) -> dict:
        """Extract Histórico tab data: IRA, reprovações per semester.

        If grr is provided, navigates to the student first.
        Otherwise assumes we're already on the student detail page.
        Returns dict with keys: ira, curriculo, semesters, reprovacoes_total,
        reprovacoes_por_frequencia, reprovacoes_por_nota.
        """
        if grr:
            if not await self._ensure_logged_in():
                return {}
            if not await self._navigate_to_student(grr):
                return {}

        await self._click_tab("Histórico", "tab_historico")

        result: dict = {
            "ira": 0.0,
            "curriculo": "",
            "semesters": [],
            "reprovacoes_total": 0,
            "reprovacoes_por_frequencia": 0,
            "reprovacoes_por_nota": 0,
            "reprovacoes_por_tipo": {},
        }

        pane = self._page.locator("#tab_historico")

        # IRA
        ira_el = pane.locator("label:has-text('IRA') + p, label:has-text('IRA') ~ p.h4").first
        if await ira_el.count() > 0:
            ira_text = (await ira_el.text_content() or "").strip()
            try:
                result["ira"] = float(ira_text)
            except ValueError:
                pass

        # Currículo
        cur_el = pane.locator("label:has-text('Currículo') + p").first
        if await cur_el.count() > 0:
            result["curriculo"] = (await cur_el.text_content() or "").strip()

        # Count reprovações from all Situação cells
        tables = pane.locator("table#tabela")
        table_count = await tables.count()
        reprov_counts: dict[str, int] = {}

        for t in range(table_count):
            rows = tables.nth(t).locator("tbody tr")
            row_count = await rows.count()
            for r in range(row_count):
                cells = rows.nth(r).locator("td")
                cell_count = await cells.count()
                if cell_count >= 8:
                    sit_text = (await cells.nth(7).text_content() or "").strip()
                    if sit_text.startswith("Reprovado"):
                        reprov_counts[sit_text] = reprov_counts.get(sit_text, 0) + 1

        result["reprovacoes_por_tipo"] = reprov_counts
        result["reprovacoes_total"] = sum(reprov_counts.values())
        result["reprovacoes_por_frequencia"] = reprov_counts.get(
            "Reprovado por Frequência", 0
        ) + reprov_counts.get("Reprovado por Frequ\u00eancia", 0)
        result["reprovacoes_por_nota"] = reprov_counts.get("Reprovado por Nota", 0)

        return result

    async def get_integralizacao(self, grr: str | None = None) -> dict:
        """Extract Integralização tab data: CH summary, discipline statuses.

        Returns dict with keys: curriculo, ch_obrigatorias, ch_optativas,
        ch_formativas, ch_total, integralizado, disciplines (list of dicts),
        nao_vencidas (list of discipline siglas not yet passed).
        """
        if grr:
            if not await self._ensure_logged_in():
                return {}
            if not await self._navigate_to_student(grr):
                return {}

        await self._click_tab("Integralização", "tab_integralizacao")

        result: dict = {
            "curriculo": "",
            "ch_obrigatorias": "",
            "ch_optativas": "",
            "ch_formativas": "",
            "ch_total": "",
            "integralizado": False,
            "disciplines": [],
            "nao_vencidas": [],
        }

        pane = self._page.locator("#tab_integralizacao")

        # Summary fields
        for key, label in [
            ("ch_obrigatorias", "CH Obrigatórias"),
            ("ch_optativas", "CH Optativas"),
            ("ch_formativas", "CH Atividades Formativas"),
            ("ch_total", "CH Total"),
        ]:
            el = pane.locator(f"label:has-text('{label}') + p").first
            if await el.count() > 0:
                result[key] = (await el.text_content() or "").strip()

        cur_el = pane.locator("label:has-text('Currículo') + p").first
        if await cur_el.count() > 0:
            result["curriculo"] = (await cur_el.text_content() or "").strip()

        # Integralizado status
        status_badge = pane.locator("span.label").first
        if await status_badge.count() > 0:
            status_text = (await status_badge.text_content() or "").strip()
            result["integralizado"] = (
                "integralizado" in status_text.lower() and "não" not in status_text.lower()
            )

        # Extract all disciplines from tables
        tables = pane.locator("table#tabela")
        table_count = await tables.count()
        nao_vencidas: list[str] = []
        disciplines: list[dict] = []

        for t in range(table_count):
            rows = tables.nth(t).locator("tbody tr")
            row_count = await rows.count()
            for r in range(row_count):
                cells = rows.nth(r).locator("td")
                cell_count = await cells.count()
                if cell_count >= 4:
                    sigla = (await cells.nth(0).text_content() or "").strip()
                    nome = (await cells.nth(1).text_content() or "").strip()
                    ch = (await cells.nth(2).text_content() or "").strip()
                    sit = (await cells.nth(3).text_content() or "").strip()
                    vencida_em = ""
                    obs = ""
                    if cell_count >= 5:
                        vencida_em = (await cells.nth(4).text_content() or "").strip()
                    if cell_count >= 6:
                        obs = (await cells.nth(5).text_content() or "").strip()

                    disc = {
                        "sigla": sigla,
                        "disciplina": nome,
                        "carga_horaria": ch,
                        "situacao": sit,
                        "vencida_em": vencida_em,
                        "observacoes": obs,
                    }
                    disciplines.append(disc)
                    if "Não Vencida" in sit or "Vencida" not in sit:
                        nao_vencidas.append(sigla)

        result["disciplines"] = disciplines
        result["nao_vencidas"] = nao_vencidas
        return result

    async def check_enrollment(self, grr: str) -> EnrollmentInfo | None:
        """Check enrollment details for the current semester."""
        try:
            grr_clean = re.sub(r"[^0-9]", "", grr)
            logger.info("SIGA: consultando matricula GRR%s", grr_clean)
            enrollment = EnrollmentInfo(grr=f"GRR{grr_clean}")
            return enrollment
        except Exception as e:
            logger.error("SIGA: falha ao consultar matricula %s: %s", grr, e)
            return None

    async def validate_internship_eligibility(
        self, grr: str, vigencia_meses: int = 12
    ) -> EligibilityResult:
        """Validate if a student is eligible for internship.

        Checks:
        - Matrícula must be active
        - >2 reprovações total -> soft block (request justification)
        - Currículo integralizado -> hard block
        - Cannot graduate before internship ends (OD501/ODDA6 check)

        Note: verificação de estágios já ativos / concedente duplicada saiu
        do SIGA em 2026-04-30 — responsabilidade do SEI cascade
        (``_consult_sei_for_email`` + checker ``sei_processo_vigente_duplicado``).
        Carga horária 30h/semana também não é mais validada aqui — substituída
        pela regra de período em ``tce_jornada_antes_meio_dia``.

        Args:
            grr: Student registration number.
            vigencia_meses: Internship duration in months (default 12).
        """
        result = EligibilityResult()
        reasons: list[str] = []
        warnings: list[str] = []

        if not await self._ensure_logged_in():
            result.reasons = ["SIGA nao autenticado"]
            return result

        student = await self.check_student_status(grr)
        if not student:
            result.reasons = [f"Aluno {grr} nao encontrado no SIGA"]
            return result
        result.student = student

        # Rule: matrícula must be active
        situacao_lower = student.situacao.lower()
        if any(s in situacao_lower for s in ["trancada", "cancelada", "cancelado"]):
            reasons.append(
                f"Matricula {student.situacao} — estagio nao permitido "
                "(SOUL.md secao 11: matricula trancada ou registro cancelado)"
            )

        # Rule: currículo not yet completed
        integ = await self.get_integralizacao()
        result.integralizacao_data = integ
        if integ.get("integralizado"):
            reasons.append(
                "Curriculo ja integralizado — estagio nao obrigatorio vedado (SOUL.md secao 11)"
            )

        # Rule: check if student can graduate before internship ends
        nao_vencidas = integ.get("nao_vencidas", [])
        disciplines = integ.get("disciplines", [])

        disc_map = {d["sigla"]: d for d in disciplines}

        od501 = disc_map.get(_ANNUAL_ESTAGIO)
        odda6 = disc_map.get(_TCC1)

        if vigencia_meses <= 6:
            pass
        else:
            has_time = False
            if od501 and "Não Vencida" in od501.get("situacao", ""):
                has_time = True
            if odda6 and "Não Vencida" in odda6.get("situacao", ""):
                has_time = True
            if _ANNUAL_ESTAGIO in nao_vencidas or _TCC1 in nao_vencidas:
                has_time = True

            if not has_time and nao_vencidas:
                few_remaining = len(nao_vencidas) <= 3
                if few_remaining:
                    warnings.append(
                        f"Aluno com apenas {len(nao_vencidas)} disciplina(s) pendente(s) "
                        f"({', '.join(nao_vencidas[:5])}). Verificar se pode se formar "
                        f"antes do fim da vigencia do estagio ({vigencia_meses} meses)."
                    )

        # Rule: >2 reprovações -> soft block (justification needed)
        historico = await self.get_historico()
        result.historico_data = historico
        total_reprov = historico.get("reprovacoes_total", 0)
        if total_reprov > 2:
            warnings.append(
                f"Aluno com {total_reprov} reprovacoes no historico. "
                "Bom rendimento academico e requisito para estagio — "
                "solicitar justificativa formal ao aluno."
            )

        enrollment = await self.check_enrollment(grr)
        result.enrollment = enrollment

        result.eligible = len(reasons) == 0
        result.reasons = reasons
        result.warnings = warnings
        return result
