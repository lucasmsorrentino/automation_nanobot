"""AgirAgent — Act phase of the Perceber → Pensar → Agir loop.

Responsibilities:
    For each email that has a suggested reply, open it in the reading pane
    and save the LLM-generated text as a draft reply.

Safety guarantee: this agent NEVER sends emails.  Every action results in a
draft that requires explicit human review and manual sending.
"""

from __future__ import annotations

from playwright.async_api import Page

from ufpr_automation.core.models import EmailClassification, EmailData
from ufpr_automation.outlook.body_extractor import _click_email_at_index, verify_opened_email
from ufpr_automation.outlook.responder import save_draft_reply
from ufpr_automation.utils.logging import logger


class AgirAgent:
    """Act agent: saves LLM-generated replies as OWA drafts.

    Args:
        page: An authenticated Playwright page on the OWA inbox.
    """

    def __init__(self, page: Page) -> None:
        self._page = page

    async def run(
        self,
        emails: list[EmailData],
        classifications: list[EmailClassification],
    ) -> list[bool]:
        """Save a draft reply for each email that has a suggested response.

        Args:
            emails: List returned by PerceberAgent (with email_index set).
            classifications: List returned by run_pensar_concurrently(),
                             same order as *emails*.

        Returns:
            List of booleans indicating success for each email.
        """
        logger.info("=" * 60)
        logger.info("AGIR — Salvando rascunhos no OWA")
        logger.info("=" * 60)

        results: list[bool] = []

        for email, cls in zip(emails, classifications):
            subject_short = email.subject[:55]

            if not cls.sugestao_resposta.strip():
                logger.info("  [%s] Sem sugestão de resposta — pulando (ação: %s)",
                            subject_short, cls.acao_necessaria)
                results.append(False)
                continue

            logger.info("  [%s] Abrindo e-mail %d para responder...",
                        subject_short, email.email_index)

            # Re-open the email (reading pane may have changed since Perceber)
            # _click_email_at_index already waits for the reading pane to render
            await _click_email_at_index(self._page, email.email_index)

            # Verify the opened email matches what we expect (guards against inbox shift)
            if not await verify_opened_email(self._page, email):
                logger.warning(
                    "  E-mail aberto não corresponde ao esperado (id: %s) — pulando",
                    email.stable_id[:8],
                )
                results.append(False)
                continue

            success = await save_draft_reply(self._page, cls.sugestao_resposta)
            results.append(success)

        saved = sum(results)
        logger.info("AgirAgent concluído — %d/%d rascunho(s) salvo(s)", saved, len(emails))
        logger.info("Revise os rascunhos no OWA antes de enviar.")
        return results
