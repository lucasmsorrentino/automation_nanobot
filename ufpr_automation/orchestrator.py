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
    # Phase 2 — PENSAR  (concurrent LLM calls)                            #
    # ------------------------------------------------------------------ #
    classifications = await run_pensar_concurrently(emails)

    # Attach classifications back to EmailData objects for the summary
    for email, cls in zip(emails, classifications):
        email.classification = cls

    # ------------------------------------------------------------------ #
    # Phase 3 — AGIR                                                       #
    # ------------------------------------------------------------------ #
    agir = AgirAgent(page)
    results = await agir.run(emails, classifications)

    drafts_saved = sum(results)

    return {
        "total_unread": len(emails),
        "classified": len(classifications),
        "drafts_saved": drafts_saved,
        "emails": emails,
    }


def print_summary(result: dict) -> None:
    """Print a human-readable pipeline summary."""
    print("\n" + "=" * 60)
    print("📊 RESUMO DO PIPELINE")
    print("=" * 60)
    print(f"  E-mails não lidos processados : {result['total_unread']}")
    print(f"  Classificações geradas        : {result['classified']}")
    print(f"  Rascunhos salvos              : {result['drafts_saved']}")
    print("=" * 60)

    if result["emails"]:
        print("\n  Detalhes por e-mail:")
        for i, email in enumerate(result["emails"], 1):
            cls = email.classification
            cat = cls.categoria if cls else "—"
            action = cls.acao_necessaria if cls else "—"
            has_draft = "✅ rascunho salvo" if (cls and cls.sugestao_resposta) else "⏭️  sem resposta"
            print(f"\n  {i}. {email.subject[:55]}")
            print(f"     Categoria: {cat}  |  Ação: {action}")
            print(f"     Status  : {has_draft}")

    print(
        "\n🔔 Revise os rascunhos no OWA (pasta Rascunhos) antes de enviar."
        "\n   Nenhum e-mail foi enviado automaticamente."
    )
