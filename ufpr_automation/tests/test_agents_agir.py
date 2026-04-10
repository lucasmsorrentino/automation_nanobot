"""Tests for ufpr_automation.agents.agir — act phase (save drafts only)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ufpr_automation.agents.agir import AgirAgent
from ufpr_automation.core.models import EmailClassification, EmailData


def _classification(sugestao: str = "Prezado, obrigado.") -> EmailClassification:
    return EmailClassification(
        categoria="Outros",
        resumo="Resumo",
        acao_necessaria="Redigir Resposta",
        sugestao_resposta=sugestao,
        confianca=0.9,
    )


@pytest.fixture
def two_emails() -> list[EmailData]:
    emails = []
    for i, sender in enumerate(["a@ufpr.br", "b@ufpr.br"]):
        e = EmailData(
            sender=sender,
            subject=f"Subject {i}",
            body=f"Body {i}",
            email_index=i,
            is_unread=True,
        )
        e.compute_stable_id()
        emails.append(e)
    return emails


class TestAgirAgentRun:
    @pytest.mark.asyncio
    async def test_empty_inputs_return_empty(self, mock_page):
        agent = AgirAgent(mock_page)
        result = await agent.run([], [])
        assert result == []

    @pytest.mark.asyncio
    async def test_skips_emails_without_suggestion(self, mock_page, two_emails):
        """Emails with empty sugestao_resposta should be skipped, not clicked."""
        classifications = [
            _classification(sugestao=""),  # skipped
            _classification(sugestao="  "),  # also skipped (whitespace only)
        ]

        with patch(
            "ufpr_automation.agents.agir._click_email_at_index", new=AsyncMock()
        ) as click_mock, patch(
            "ufpr_automation.agents.agir.verify_opened_email",
            new=AsyncMock(return_value=True),
        ), patch(
            "ufpr_automation.agents.agir.save_draft_reply", new=AsyncMock()
        ) as save_mock, patch(
            "ufpr_automation.agents.agir.dismiss_owa_dialog", new=AsyncMock()
        ):
            agent = AgirAgent(mock_page)
            result = await agent.run(two_emails, classifications)

        assert result == [False, False]
        click_mock.assert_not_called()
        save_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_saves_draft_and_forwards_text(self, mock_page, two_emails):
        """save_draft_reply should be awaited once per email with the right args."""
        classifications = [
            _classification(sugestao="Resposta 1"),
            _classification(sugestao="Resposta 2"),
        ]

        save_mock = AsyncMock(return_value=True)
        dismiss_mock = AsyncMock()
        click_mock = AsyncMock()

        with patch(
            "ufpr_automation.agents.agir._click_email_at_index", new=click_mock
        ), patch(
            "ufpr_automation.agents.agir.verify_opened_email",
            new=AsyncMock(return_value=True),
        ), patch(
            "ufpr_automation.agents.agir.save_draft_reply", new=save_mock
        ), patch(
            "ufpr_automation.agents.agir.dismiss_owa_dialog", new=dismiss_mock
        ):
            agent = AgirAgent(mock_page)
            result = await agent.run(two_emails, classifications)

        assert result == [True, True]
        assert save_mock.await_count == 2

        # The reply text should match the classification's sugestao_resposta for
        # each email (in order).
        call_texts = [call.args[1] for call in save_mock.await_args_list]
        assert call_texts == ["Resposta 1", "Resposta 2"]
        # _click_email_at_index should have received the positional email_index.
        click_indices = [call.args[1] for call in click_mock.await_args_list]
        assert click_indices == [0, 1]
        # A dialog dismissal should happen between/after each draft save.
        assert dismiss_mock.await_count == 2

    @pytest.mark.asyncio
    async def test_verification_mismatch_skips_save(self, mock_page, two_emails):
        """If verify_opened_email returns False, save_draft should be skipped."""
        classifications = [
            _classification(sugestao="Resposta 1"),
            _classification(sugestao="Resposta 2"),
        ]

        save_mock = AsyncMock(return_value=True)

        with patch(
            "ufpr_automation.agents.agir._click_email_at_index", new=AsyncMock()
        ), patch(
            "ufpr_automation.agents.agir.verify_opened_email",
            new=AsyncMock(side_effect=[False, True]),
        ), patch(
            "ufpr_automation.agents.agir.save_draft_reply", new=save_mock
        ), patch(
            "ufpr_automation.agents.agir.dismiss_owa_dialog", new=AsyncMock()
        ):
            agent = AgirAgent(mock_page)
            result = await agent.run(two_emails, classifications)

        # First email was rejected by verification -> no save call for it.
        assert result == [False, True]
        assert save_mock.await_count == 1
        assert save_mock.await_args_list[0].args[1] == "Resposta 2"

    @pytest.mark.asyncio
    async def test_save_failure_is_recorded(self, mock_page, two_emails):
        """save_draft_reply returning False should propagate to the result list."""
        classifications = [
            _classification(sugestao="Resposta 1"),
            _classification(sugestao="Resposta 2"),
        ]

        with patch(
            "ufpr_automation.agents.agir._click_email_at_index", new=AsyncMock()
        ), patch(
            "ufpr_automation.agents.agir.verify_opened_email",
            new=AsyncMock(return_value=True),
        ), patch(
            "ufpr_automation.agents.agir.save_draft_reply",
            new=AsyncMock(side_effect=[True, False]),
        ), patch(
            "ufpr_automation.agents.agir.dismiss_owa_dialog", new=AsyncMock()
        ):
            agent = AgirAgent(mock_page)
            result = await agent.run(two_emails, classifications)

        assert result == [True, False]
