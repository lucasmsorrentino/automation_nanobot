"""PerceberAgent — Sense phase of the Perceber → Pensar → Agir loop.

Responsibilities:
    1. Scrape the OWA inbox for all visible emails.
    2. For each unread email, open it and extract the FULL body text.

The browser context (Playwright Page) is managed externally (by the
orchestrator) and passed in, so the agent does not open or close the browser.
"""

from __future__ import annotations

from playwright.async_api import Page

from ufpr_automation.core.models import EmailData
from ufpr_automation.outlook.body_extractor import extract_email_body
from ufpr_automation.outlook.scraper import scrape_inbox


class PerceberAgent:
    """Sense agent: navigates OWA and collects full email data.

    Args:
        page: An authenticated Playwright page already on the OWA inbox.
    """

    def __init__(self, page: Page) -> None:
        self._page = page

    async def run(self) -> list[EmailData]:
        """Scrape inbox and extract full body for every unread email.

        Returns:
            List of EmailData objects, each with ``body`` populated.
            Only unread emails are returned.
        """
        print("\n" + "=" * 60)
        print("👁️  PERCEBER — Escaneando caixa de entrada")
        print("=" * 60)

        all_emails = await scrape_inbox(self._page)
        unread = [e for e in all_emails if e.is_unread]

        if not unread:
            print("📭 Nenhum e-mail não lido encontrado.")
            return []

        print(f"\n📩 {len(unread)} e-mail(s) não lido(s) — extraindo corpos completos...")

        for i, email in enumerate(unread):
            email.email_index = i  # positional index in the visible inbox list
            print(f"  [{i + 1}/{len(unread)}] {email.subject[:60]}")
            email.body = await extract_email_body(self._page, i)
            body_preview = email.body[:80].replace("\n", " ") if email.body else "(vazio)"
            print(f"           Corpo: {body_preview}…")

        print(f"\n✅ PerceberAgent concluído — {len(unread)} e-mail(s) com corpo extraído")
        return unread
