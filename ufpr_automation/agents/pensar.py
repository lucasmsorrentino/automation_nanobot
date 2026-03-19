"""PensarAgent — Think phase of the Perceber → Pensar → Agir loop.

Responsibilities:
    Classify each email and generate a draft reply using the Gemini LLM.

Key design decision: classification calls are made **concurrently** via
asyncio.gather(), so N unread emails result in N parallel API calls rather
than N sequential ones.  This is the "multi-agent" parallelism in Marco I.
"""

from __future__ import annotations

import asyncio

from ufpr_automation.core.models import EmailClassification, EmailData
from ufpr_automation.llm.client import GeminiClient


class PensarAgent:
    """Think agent: classifies one email and generates a draft reply.

    A single PensarAgent instance is created per email classification task.
    The orchestrator runs multiple PensarAgents concurrently using
    asyncio.gather().

    Args:
        client: Shared GeminiClient instance (thread-safe for concurrent calls).
        email: The EmailData to classify.
    """

    def __init__(self, client: GeminiClient, email: EmailData) -> None:
        self._client = client
        self._email = email

    async def run(self) -> EmailClassification:
        """Classify the email and return a structured classification + draft."""
        return await self._client.classify_email_async(self._email)


async def run_pensar_concurrently(emails: list[EmailData]) -> list[EmailClassification]:
    """Run one PensarAgent per email, all concurrently.

    This is the multi-agent heart of the pipeline: each email gets its own
    independent LLM call, all fired at the same time.

    Args:
        emails: Unread emails with fully populated ``body`` fields.

    Returns:
        List of EmailClassification objects in the same order as *emails*.
    """
    if not emails:
        return []

    print("\n" + "=" * 60)
    print(f"🧠 PENSAR — {len(emails)} agente(s) classificando em paralelo")
    print("=" * 60)

    # One shared client (one HTTP connection pool, one API key auth)
    client = GeminiClient()

    agents = [PensarAgent(client, email) for email in emails]
    tasks = [agent.run() for agent in agents]

    print(f"  ⏳ Disparando {len(tasks)} chamada(s) assíncronas ao Gemini...")
    classifications = await asyncio.gather(*tasks)

    for email, cls in zip(emails, classifications):
        print(f"\n  📧 {email.subject[:55]}")
        print(f"     Categoria : {cls.categoria}")
        print(f"     Resumo    : {cls.resumo}")
        print(f"     Ação      : {cls.acao_necessaria}")
        if cls.sugestao_resposta:
            lines = cls.sugestao_resposta.split("\n")
            print(f"     Rascunho  : {lines[0][:70]}{'…' if len(lines) > 1 else ''}")

    print(f"\n✅ PensarAgent concluído — {len(classifications)} classificação(ões)")
    return list(classifications)
