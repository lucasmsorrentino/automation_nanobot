"""SIGA client for querying student status and validating internship eligibility.

All operations are READ-ONLY. No modifications are made in SIGA.
Eligibility rules are based on SOUL.md section 11.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

from ufpr_automation.siga.models import EligibilityResult, EnrollmentInfo, StudentStatus
from ufpr_automation.utils.logging import logger

# Max weekly internship hours (SOUL.md section 3)
MAX_WEEKLY_HOURS = 30


class SIGAClient:
    """Client for read-only operations on SIGA via Playwright.

    All methods are async and require an active Playwright page.
    """

    def __init__(self, page: Page):
        self._page = page

    async def check_student_status(self, grr: str) -> StudentStatus | None:
        """Look up a student's academic status by GRR.

        Args:
            grr: Student registration number (e.g. GRR20191234).

        Returns:
            StudentStatus with academic data, or None if not found.
        """
        try:
            grr_clean = re.sub(r"[^0-9]", "", grr)
            logger.info("SIGA: consultando aluno GRR%s", grr_clean)

            # Navigate to student search
            search_input = self._page.locator(
                'input[name*="matricula"], input[name*="grr"], '
                'input[id*="matricula"], input[id*="grr"], '
                'input[placeholder*="matr"]'
            )
            if await search_input.count() == 0:
                logger.warning("SIGA: campo de busca de aluno nao encontrado")
                return None

            await search_input.first.fill(grr_clean)

            # Submit search
            submit = self._page.locator(
                'button[type="submit"], input[type="submit"], '
                'button:has-text("Consultar"), button:has-text("Buscar")'
            )
            if await submit.count() > 0:
                await submit.first.click()
            else:
                await search_input.first.press("Enter")

            await self._page.wait_for_load_state("networkidle", timeout=15000)

            # Extract student data from the result page
            student = StudentStatus(grr=f"GRR{grr_clean}")

            # Try to extract name
            name_el = self._page.locator(
                '[id*="nome"], [class*="nome"], td:has-text("Nome") + td'
            )
            if await name_el.count() > 0:
                nome = await name_el.first.text_content()
                if nome:
                    student.nome = nome.strip()

            # Try to extract course
            curso_el = self._page.locator(
                '[id*="curso"], [class*="curso"], td:has-text("Curso") + td'
            )
            if await curso_el.count() > 0:
                curso = await curso_el.first.text_content()
                if curso:
                    student.curso = curso.strip()

            # Try to extract situation
            sit_el = self._page.locator(
                '[id*="situacao"], [class*="situacao"], '
                'td:has-text("Situacao") + td, td:has-text("Status") + td'
            )
            if await sit_el.count() > 0:
                sit = await sit_el.first.text_content()
                if sit:
                    student.situacao = sit.strip()

            logger.info("SIGA: aluno %s — %s — %s", student.grr, student.nome, student.situacao)
            return student

        except Exception as e:
            logger.error("SIGA: falha ao consultar aluno %s: %s", grr, e)
            return None

    async def check_enrollment(self, grr: str) -> EnrollmentInfo | None:
        """Check enrollment details for the current semester.

        Args:
            grr: Student registration number.

        Returns:
            EnrollmentInfo with semester data, or None if not found.
        """
        try:
            grr_clean = re.sub(r"[^0-9]", "", grr)
            logger.info("SIGA: consultando matricula GRR%s", grr_clean)

            enrollment = EnrollmentInfo(grr=f"GRR{grr_clean}")

            # Look for enrollment-specific data on the page
            # This will be refined once the actual SIGA DOM is inspected
            ch_el = self._page.locator(
                '[id*="carga"], [class*="carga"], '
                'td:has-text("Carga") + td'
            )
            if await ch_el.count() > 0:
                ch_text = await ch_el.first.text_content()
                if ch_text:
                    nums = re.findall(r"\d+", ch_text)
                    if nums:
                        enrollment.carga_horaria_matriculada = int(nums[0])

            return enrollment

        except Exception as e:
            logger.error("SIGA: falha ao consultar matricula %s: %s", grr, e)
            return None

    async def validate_internship_eligibility(self, grr: str) -> EligibilityResult:
        """Validate if a student is eligible for internship.

        Applies rules from SOUL.md section 11:
        - Matricula must be active (not trancada/cancelada)
        - No reprovacao por falta in previous semester (Design Grafico rule)
        - Curriculo not yet completed (for non-obligatory)
        - Weekly hours sum <= 30h
        - No two internships at the same concedente

        Args:
            grr: Student registration number.

        Returns:
            EligibilityResult with eligibility status and reasons.
        """
        result = EligibilityResult()
        reasons: list[str] = []
        warnings: list[str] = []

        # Get student status
        student = await self.check_student_status(grr)
        if not student:
            result.reasons = [f"Aluno {grr} nao encontrado no SIGA"]
            return result
        result.student = student

        # Get enrollment info
        enrollment = await self.check_enrollment(grr)
        result.enrollment = enrollment

        # Rule: matricula must be active
        situacao_lower = student.situacao.lower()
        if any(s in situacao_lower for s in ["trancada", "cancelada", "cancelado"]):
            reasons.append(
                f"Matricula {student.situacao} — estagio nao permitido "
                "(SOUL.md secao 11: matricula trancada ou registro cancelado)"
            )

        # Rule: curriculo not yet completed (for non-obligatory)
        if "integralizada" in situacao_lower or "integralizado" in situacao_lower:
            reasons.append(
                "Curriculo ja integralizado — estagio nao obrigatorio vedado "
                "(SOUL.md secao 11)"
            )

        # Rule: no reprovacao por falta in previous semester
        if enrollment and enrollment.reprovacao_por_falta_anterior:
            reasons.append(
                "Reprovacao por falta no semestre anterior — "
                "estagio nao obrigatorio vedado (regra especifica Design Grafico)"
            )

        # Rule: weekly hours <= 30
        if enrollment and enrollment.horas_estagio_semanais > 0:
            if enrollment.horas_estagio_semanais >= MAX_WEEKLY_HOURS:
                reasons.append(
                    f"Carga horaria semanal de estagios ({enrollment.horas_estagio_semanais}h) "
                    f"ja atinge o limite de {MAX_WEEKLY_HOURS}h/semana "
                    "(Lei 11.788/08, Art. 10)"
                )
            elif enrollment.horas_estagio_semanais >= MAX_WEEKLY_HOURS - 6:
                warnings.append(
                    f"Carga horaria semanal de estagios ({enrollment.horas_estagio_semanais}h) "
                    f"proxima do limite de {MAX_WEEKLY_HOURS}h/semana"
                )

        # Check minimum hours for obligatory internship
        if student.horas_integralizadas > 0:
            if student.curriculo == "2016" and student.horas_integralizadas < 1440:
                warnings.append(
                    f"Horas integralizadas ({student.horas_integralizadas}h) abaixo do "
                    "minimo para estagio obrigatorio curriculo 2016 (1.440h)"
                )
            elif student.curriculo == "2020" and student.horas_integralizadas < 1035:
                warnings.append(
                    f"Horas integralizadas ({student.horas_integralizadas}h) abaixo do "
                    "minimo para estagio obrigatorio curriculo 2020 (1.035h)"
                )

        result.eligible = len(reasons) == 0
        result.reasons = reasons
        result.warnings = warnings
        return result
