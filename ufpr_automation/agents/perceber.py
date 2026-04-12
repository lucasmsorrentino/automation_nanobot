"""PerceberAgent — Sense phase of the Perceber → Pensar → Agir loop.

Responsibilities:
    1. Scrape the OWA inbox for all visible emails.
    2. For each unread email, open it and extract the FULL body text.

The browser context (Playwright Page) is managed externally (by the
orchestrator) and passed in, so the agent does not open or close the browser.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

from ufpr_automation.core.models import EmailData
from ufpr_automation.outlook.body_extractor import extract_email_body
from ufpr_automation.outlook.scraper import scrape_inbox
from ufpr_automation.utils.logging import logger


class PerceberAgent:
    """Sense agent: navigates OWA and collects full email data.

    Args:
        page: An authenticated Playwright page already on the OWA inbox.
    """

    def __init__(self, page: "Page") -> None:
        self._page = page

    async def run(self) -> list[EmailData]:
        """Scrape inbox and extract full body for every unread email.

        Returns:
            List of EmailData objects, each with ``body`` populated.
            Only unread emails are returned.
        """
        logger.info("=" * 60)
        logger.info("PERCEBER — Escaneando caixa de entrada")
        logger.info("=" * 60)

        all_emails = await scrape_inbox(self._page)
        unread = [e for e in all_emails if e.is_unread]

        if not unread:
            logger.info("Nenhum e-mail não lido encontrado.")
            return []

        logger.info("%d e-mail(s) não lido(s) — extraindo corpos completos...", len(unread))

        for i, email in enumerate(unread):
            email.email_index = i  # positional index (fallback for clicking)
            email.compute_stable_id()  # hash-based identity for verification
            logger.info(
                "  [%d/%d] %s  (id: %s)", i + 1, len(unread),
                email.subject[:60], email.stable_id[:8],
            )
            email.body = await extract_email_body(self._page, i)
            body_preview = email.body[:80].replace("\n", " ") if email.body else "(vazio)"
            logger.debug("           Corpo: %s", body_preview)

        logger.info("PerceberAgent concluído — %d e-mail(s) com corpo extraído", len(unread))
        return unread
