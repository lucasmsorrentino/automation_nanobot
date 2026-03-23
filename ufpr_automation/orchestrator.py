"""Multi-agent orchestrator for UFPR email automation — Marco I.

Coordinates three specialized agents in sequence:

    PerceberAgent  (sequential, Playwright)
         │
         ▼  List[EmailData]  (with full body)
    PensarAgent × N  (concurrent, Gemini API)
         │
         ▼  List[EmailClassification]
    AgirAgent  (sequential, Playwright)
         │
         ▼  List[bool]  (draft saved per email)

The browser context is managed here so it is shared between PerceberAgent
(which reads emails) and AgirAgent (which saves drafts), while PensarAgent
runs its LLM calls with no browser dependency.
"""

from __future__ import annotations

from playwright.async_api import Page

from ufpr_automation.agents.agir import AgirAgent
from ufpr_automation.agents.pensar import run_pensar_concurrently
from ufpr_automation.agents.perceber import PerceberAgent
from ufpr_automation.utils.logging import logger


async def run_pipeline(page: Page) -> dict:
    """Execute the full Perceber → Pensar → Agir pipeline.

    Args:
        page: An authenticated Playwright page already on the OWA inbox.

    Returns:
        Summary dict with keys:
            - total_unread: int
            - classified: int
            - drafts_saved: int
            - emails: List[EmailData]  (with classification attached)
    """

    # ------------------------------------------------------------------ #
    # Phase 1 — PERCEBER                                                   #
    # ------------------------------------------------------------------ #
    perceber = PerceberAgent(page)
    emails = await perceber.run()

    if not emails:
        return {
            "total_unread": 0,
            "classified": 0,
            "drafts_saved": 0,
            "emails": [],
        }

    # ------------------------------------------------------------------ #
    # Phase 2 — PENSAR  (concurrent LLM calls, partial failures handled)  #
    # ------------------------------------------------------------------ #
    classified_emails, classifications = await run_pensar_concurrently(emails)

    # Attach classifications back to EmailData objects for the summary
    for email, cls in zip(classified_emails, classifications):
        email.classification = cls

    # ------------------------------------------------------------------ #
    # Phase 3 — AGIR  (only for successfully classified emails)            #
    # ------------------------------------------------------------------ #
    agir = AgirAgent(page)
    results = await agir.run(classified_emails, classifications)

    drafts_saved = sum(results)

    return {
        "total_unread": len(emails),
        "classified": len(classifications),
        "drafts_saved": drafts_saved,
        "emails": emails,
    }


def print_summary(result: dict) -> None:
    """Log a human-readable pipeline summary."""
    logger.info("=" * 60)
    logger.info("RESUMO DO PIPELINE")
    logger.info("=" * 60)
    logger.info(
        "Pipeline concluído",
        extra={
            "total_unread": result["total_unread"],
            "classified": result["classified"],
            "drafts_saved": result["drafts_saved"],
        },
    )
    logger.info("  E-mails não lidos processados : %d", result["total_unread"])
    logger.info("  Classificações geradas        : %d", result["classified"])
    logger.info("  Rascunhos salvos              : %d", result["drafts_saved"])

    if result["emails"]:
        logger.info("  Detalhes por e-mail:")
        for i, email in enumerate(result["emails"], 1):
            cls = email.classification
            cat = cls.categoria if cls else "—"
            action = cls.acao_necessaria if cls else "—"
            has_draft = "rascunho salvo" if (cls and cls.sugestao_resposta) else "sem resposta"
            logger.info("  %d. %s | %s | %s | %s", i, email.subject[:55], cat, action, has_draft)

    logger.info(
        "Revise os rascunhos no OWA (pasta Rascunhos) antes de enviar. "
        "Nenhum e-mail foi enviado automaticamente."
    )
