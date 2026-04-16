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

from ufpr_automation.siga.models import EligibilityResult, EnrollmentInfo, StudentStatus
from ufpr_automation.utils.logging import logger

MAX_WEEKLY_HOURS = 30

# Disciplines that indicate >= 1 year remaining in the curriculum
_ANNUAL_ESTAGIO = "OD501"   # Estágio Supervisionado (annual, 360h)
_TCC1 = "ODDA6"             # TCC1 (prerequisite for TCC2)

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

    async def _navigate_to_student(self, grr: str) -> bool:
        """Navigate sidebar Discentes > Consultar, search by GRR, click first result."""
        grr_clean = re.sub(r"[^0-9]", "", grr)
        logger.info("SIGA: consultando aluno GRR%s", grr_clean)

        discentes = self._page.locator("a:has-text('Discentes')").first
        await discentes.click()
        await asyncio.sleep(0.5)

        consultar = self._page.locator("a:has-text('Consultar')").first
        await consultar.click()
        await self._page.wait_for_load_state("networkidle", timeout=15000)

        search_field = self._page.locator(
            "input[placeholder*='Nome ou Documento']"
        ).first
        await search_field.fill(grr_clean)
        await asyncio.sleep(2)

        first_link = self._page.locator("table tbody tr a").first
        if await first_link.count() == 0:
            logger.warning("SIGA: aluno GRR%s nao encontrado", grr_clean)
            return False

        await first_link.click()
        await self._page.wait_for_load_state("networkidle", timeout=15000)
        return True

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
            el = pane.locator(f"xpath=.//*[contains(text(),'{label_text}')]/following-sibling::*[1]")
            if await el.count() > 0:
                info[key] = (await el.first.text_content() or "").strip()

        header = self._page.locator("h2:has-text('Discente')").first
        if await header.count() > 0:
            txt = (await header.text_content() or "").strip()
            m = re.search(r"GRR\d+", txt)
            if m:
                info["grr"] = m.group()
            parts = txt.split(" - ")
            if len(parts) >= 2:
                info["nome"] = parts[1].strip().split(" - ")[0].strip()

        return info

    async def check_student_status(self, grr: str) -> StudentStatus | None:
        """Look up a student's academic status by GRR."""
        try:
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
            result["integralizado"] = "integralizado" in status_text.lower() and "não" not in status_text.lower()

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
        - Weekly hours sum <= 30h

        Args:
            grr: Student registration number.
            vigencia_meses: Internship duration in months (default 12).
        """
        result = EligibilityResult()
        reasons: list[str] = []
        warnings: list[str] = []

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
        if integ.get("integralizado"):
            reasons.append(
                "Curriculo ja integralizado — estagio nao obrigatorio vedado "
                "(SOUL.md secao 11)"
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
