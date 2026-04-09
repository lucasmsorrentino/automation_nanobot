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

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

from ufpr_automation.agents.pensar import run_pensar_concurrently
from ufpr_automation.core.models import EmailClassification, EmailData
from ufpr_automation.utils.logging import logger


def _save_run_results_gmail(
    emails: list[EmailData], classifications: list[EmailClassification]
) -> None:
    """Save classification results for feedback review CLI."""
    from ufpr_automation.feedback.store import FEEDBACK_DIR

    results_file = FEEDBACK_DIR / "last_run.jsonl"
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)

    with open(results_file, "w", encoding="utf-8") as f:
        for email_obj, cls in zip(emails, classifications):
            entry = {
                "email_hash": email_obj.stable_id,
                "sender": email_obj.sender,
                "subject": email_obj.subject,
                "body": (email_obj.body or email_obj.preview)[:500],
                "classification": cls.model_dump(),
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


async def run_pipeline_gmail() -> dict:
    """Execute the pipeline using Gmail IMAP as the email source.

    Reads forwarded emails from Gmail, classifies them via LLM,
    and saves draft replies back to Gmail's Drafts folder.

    Returns:
        Summary dict matching run_pipeline() format.
    """
    from ufpr_automation.gmail.client import GmailClient

    from ufpr_automation.attachments import extract_text_from_attachment

    gmail = GmailClient()
    emails = gmail.list_unread()

    # Extract text from attachments
    total_atts = 0
    for email_obj in emails:
        for att in email_obj.attachments:
            extract_text_from_attachment(att)
            total_atts += 1
    if total_atts:
        logger.info("Anexos: %d arquivo(s) processado(s) para extracao de texto", total_atts)

    if not emails:
        return {
            "total_unread": 0,
            "classified": 0,
            "drafts_saved": 0,
            "emails": [],
        }

    # Phase 2 — PENSAR (concurrent LLM calls)
    classified_emails, classifications = await run_pensar_concurrently(emails)

    for email_obj, cls in zip(classified_emails, classifications):
        email_obj.classification = cls

    # Save results for feedback review CLI
    _save_run_results_gmail(classified_emails, classifications)

    # Phase 3 — AGIR (save drafts to Gmail)
    drafts_saved = 0
    for email_obj, cls in zip(classified_emails, classifications):
        if not cls.sugestao_resposta.strip():
            logger.info("  [%s] Sem sugestão de resposta — pulando", email_obj.subject[:55])
            continue

        # Extract sender email address for the reply
        sender = email_obj.sender
        # Handle "Name <email@addr>" format
        if "<" in sender and ">" in sender:
            sender = sender.split("<")[1].rstrip(">")

        ok = gmail.save_draft(
            to_addr=sender,
            subject=email_obj.subject,
            body=cls.sugestao_resposta,
            in_reply_to=email_obj.gmail_message_id,
        )
        if ok:
            drafts_saved += 1
            gmail.mark_read(email_obj.gmail_msg_id)

    return {
        "total_unread": len(emails),
        "classified": len(classifications),
        "drafts_saved": drafts_saved,
        "emails": emails,
    }


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

    from ufpr_automation.agents.agir import AgirAgent
    from ufpr_automation.agents.perceber import PerceberAgent

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
