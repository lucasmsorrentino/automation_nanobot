"""Tests for ufpr_automation.agents.perceber — sense phase."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ufpr_automation.agents.perceber import PerceberAgent
from ufpr_automation.core.models import EmailData


@pytest.fixture
def canned_emails() -> list[EmailData]:
    return [
        EmailData(
            sender="aluno1@ufpr.br",
            subject="Matricula",
            preview="Duvida sobre matricula",
            is_unread=True,
        ),
        EmailData(
            sender="aluno2@ufpr.br",
            subject="Estagio",
            preview="Sobre TCE",
            is_unread=True,
        ),
        EmailData(
            sender="sistema@ufpr.br",
            subject="Notificacao lida",
            preview="Ja foi vista",
            is_unread=False,
        ),
    ]


class TestPerceberAgentRun:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_unread(self, mock_page):
        """If scrape_inbox returns nothing (or only read emails), run() returns []."""
        with patch(
            "ufpr_automation.agents.perceber.scrape_inbox",
            new=AsyncMock(return_value=[]),
        ), patch(
            "ufpr_automation.agents.perceber.extract_email_body",
            new=AsyncMock(return_value=""),
        ) as mock_extract:
            agent = PerceberAgent(mock_page)
            result = await agent.run()

        assert result == []
        # extract_email_body must NOT be called when no unread emails exist.
        mock_extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_filters_read_emails(self, mock_page, canned_emails):
        """Only unread emails should be returned (and have bodies extracted)."""
        with patch(
            "ufpr_automation.agents.perceber.scrape_inbox",
            new=AsyncMock(return_value=canned_emails),
        ), patch(
            "ufpr_automation.agents.perceber.extract_email_body",
            new=AsyncMock(return_value="Corpo extraido"),
        ) as mock_extract:
            agent = PerceberAgent(mock_page)
            result = await agent.run()

        assert len(result) == 2
        assert all(e.is_unread for e in result)
        assert {e.sender for e in result} == {"aluno1@ufpr.br", "aluno2@ufpr.br"}
        # Body should have been extracted exactly once per unread email.
        assert mock_extract.call_count == 2

    @pytest.mark.asyncio
    async def test_populates_body_and_stable_id(self, mock_page, canned_emails):
        """Each returned email should have body and stable_id populated."""
        extracted_body = "Corpo completo do e-mail do aluno."
        with patch(
            "ufpr_automation.agents.perceber.scrape_inbox",
            new=AsyncMock(return_value=canned_emails),
        ), patch(
            "ufpr_automation.agents.perceber.extract_email_body",
            new=AsyncMock(return_value=extracted_body),
        ):
            agent = PerceberAgent(mock_page)
            result = await agent.run()

        for i, email in enumerate(result):
            assert email.body == extracted_body
            assert email.stable_id  # hash populated
            assert email.email_index == i  # positional index assigned

    @pytest.mark.asyncio
    async def test_passes_page_to_scrape_inbox(self, mock_page):
        """The PerceberAgent should forward its page to scrape_inbox."""
        with patch(
            "ufpr_automation.agents.perceber.scrape_inbox",
            new=AsyncMock(return_value=[]),
        ) as mock_scrape, patch(
            "ufpr_automation.agents.perceber.extract_email_body",
            new=AsyncMock(return_value=""),
        ):
            agent = PerceberAgent(mock_page)
            await agent.run()

        mock_scrape.assert_awaited_once_with(mock_page)
