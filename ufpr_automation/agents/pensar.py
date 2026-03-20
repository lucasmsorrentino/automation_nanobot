"""PensarAgent — Think phase of the Perceber → Pensar → Agir loop.

Responsibilities:
    Classify each email and generate a draft reply using the LLM (via LiteLLM).

Key design decision: classification calls are made **concurrently** via
asyncio.gather(), so N unread emails result in N parallel API calls rather
than N sequential ones.  This is the "multi-agent" parallelism in Marco I.
"""

from __future__ import annotations

import asyncio

from ufpr_automation.core.models import EmailClassification, EmailData
from ufpr_automation.llm.client import LLMClient
from ufpr_automation.utils.logging import logger

# Maximum concurrent LLM calls to avoid API quota exhaustion
MAX_CONCURRENT_LLM_CALLS = 5


class PensarAgent:
    """Think agent: classifies one email and generates a draft reply.

    A single PensarAgent instance is created per email classification task.
    The orchestrator runs multiple PensarAgents concurrently using
    asyncio.gather().

    Args:
        client: Shared LLMClient instance (thread-safe for concurrent calls).
        email: The EmailData to classify.
    """

    def __init__(self, client: LLMClient, email: EmailData) -> None:
        self._client = client
        self._email = email

    async def run(self, semaphore: asyncio.Semaphore) -> EmailClassification:
        """Classify the email and return a structured classification + draft."""
        async with semaphore:
            return await self._client.classify_email_async(self._email)


async def run_pensar_concurrently(
    emails: list[EmailData],
) -> tuple[list[EmailData], list[EmailClassification]]:
    """Run one PensarAgent per email, all concurrently.

    This is the multi-agent heart of the pipeline: each email gets its own
    independent LLM call, all fired at the same time.  Individual failures
    are caught and reported, and the pipeline continues with the successful
    classifications.

    Args:
        emails: Unread emails with fully populated ``body`` fields.

    Returns:
        Tuple of (successful_emails, classifications) — same order, with
        failed emails filtered out.
    """
    if not emails:
        return [], []

    logger.info("=" * 60)
    logger.info("PENSAR — %d agente(s) classificando em paralelo", len(emails))
    logger.info("=" * 60)

    # One shared client (one HTTP connection pool, one API key auth)
    client = LLMClient()

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)
    agents = [PensarAgent(client, email) for email in emails]
    tasks = [agent.run(semaphore) for agent in agents]

    logger.info(
        "Disparando %d chamada(s) assíncronas ao LLM (máx %d simultâneas)...",
        len(tasks), MAX_CONCURRENT_LLM_CALLS,
    )
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Separate successes from failures
    successful_emails: list[EmailData] = []
    classifications: list[EmailClassification] = []
    failures: list[tuple[EmailData, Exception]] = []

    for email, result in zip(emails, results):
        if isinstance(result, Exception):
            failures.append((email, result))
        else:
            successful_emails.append(email)
            classifications.append(result)

    # Report successes
    for email, cls in zip(successful_emails, classifications):
        logger.info("  %s | %s | %s", email.subject[:55], cls.categoria, cls.acao_necessaria)
        if cls.sugestao_resposta:
            lines = cls.sugestao_resposta.split("\n")
            logger.debug("     Rascunho: %s", lines[0][:70])

    # Report failures
    if failures:
        logger.warning("%d classificação(ões) falharam:", len(failures))
        for email, exc in failures:
            logger.warning("  %s — %s: %s", email.subject[:55], type(exc).__name__, exc)

    logger.info(
        "PensarAgent concluído — %d/%d classificação(ões) bem-sucedidas",
        len(classifications), len(emails),
    )
    return successful_emails, classifications
