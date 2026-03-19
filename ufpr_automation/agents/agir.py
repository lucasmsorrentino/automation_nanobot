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
from ufpr_automation.outlook.body_extractor import _click_email_at_index
from ufpr_automation.outlook.responder import save_draft_reply


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
        print("\n" + "=" * 60)
        print("✍️  AGIR — Salvando rascunhos no OWA")
        print("=" * 60)

        results: list[bool] = []

        for email, cls in zip(emails, classifications):
            subject_short = email.subject[:55]

            if not cls.sugestao_resposta.strip():
                print(f"\n  ⏭️  [{subject_short}]")
                print(f"      Sem sugestão de resposta — pulando (ação: {cls.acao_necessaria})")
                results.append(False)
                continue

            print(f"\n  📧 [{subject_short}]")
            print(f"      Abrindo e-mail {email.email_index} para responder...")

            # Re-open the email (reading pane may have changed since Perceber)
            await _click_email_at_index(self._page, email.email_index)
            await self._page.wait_for_timeout(1_000)

            success = await save_draft_reply(self._page, cls.sugestao_resposta)
            results.append(success)

        saved = sum(results)
        print(f"\n✅ AgirAgent concluído — {saved}/{len(emails)} rascunho(s) salvo(s)")
        print("🔔 NOTIFICAÇÃO: Revise os rascunhos no OWA antes de enviar.")
        return results
