"""Shared pytest fixtures for the UFPR Automation test suite.

Provides:
    - ``mock_page``: an ``AsyncMock`` that emulates a Playwright ``Page`` with
      sensible async defaults for the methods exercised by the outlook/agents
      modules.
    - ``sample_email``: a minimal ``EmailData`` instance with ``stable_id``
      pre-computed so tests that compare hashes behave deterministically.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ufpr_automation.core.models import EmailData


@pytest.fixture
def mock_page():
    """Return an ``AsyncMock`` with Playwright ``Page``-like async defaults.

    We don't bind ``spec=Page`` because importing ``playwright.async_api.Page``
    and using it as a spec can pull in the full Playwright async machinery,
    which is overkill for unit tests. Instead we provide sensible stub
    behaviour for the handful of methods the source code actually calls.
    """
    page = AsyncMock()

    # `page.locator(...)` is a SYNC call in real Playwright that returns a
    # Locator (which itself has async methods). Mirror that by making
    # ``locator`` a regular MagicMock that returns an ``AsyncMock``.
    def _locator(_selector, *_args, **_kwargs):
        loc = AsyncMock()
        loc.click = AsyncMock(return_value=None)
        loc.fill = AsyncMock(return_value=None)
        loc.wait_for = AsyncMock(return_value=None)
        loc.text_content = AsyncMock(return_value="")
        loc.is_visible = AsyncMock(return_value=True)
        return loc

    page.locator = MagicMock(side_effect=_locator)

    # Common async methods.
    page.content = AsyncMock(return_value="<html></html>")
    page.screenshot = AsyncMock(return_value=b"")
    page.goto = AsyncMock(return_value=None)
    page.wait_for_load_state = AsyncMock(return_value=None)
    page.wait_for_selector = AsyncMock(return_value=None)
    page.wait_for_timeout = AsyncMock(return_value=None)
    page.wait_for_url = AsyncMock(return_value=None)
    page.title = AsyncMock(return_value="Mocked Page")
    page.query_selector = AsyncMock(return_value=None)
    page.query_selector_all = AsyncMock(return_value=[])
    page.evaluate = AsyncMock(return_value=None)

    # URL is a plain attribute in Playwright, not a coroutine.
    page.url = "https://outlook.office.com/mail/inbox"

    # Keyboard is also a regular attribute returning an object with async methods.
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock(return_value=None)
    page.keyboard.type = AsyncMock(return_value=None)

    return page


@pytest.fixture
def sample_email() -> EmailData:
    """Return a minimal unread ``EmailData`` with ``stable_id`` populated."""
    email = EmailData(
        sender="aluno@ufpr.br",
        subject="Solicitacao de ajuste de matricula",
        preview="Prezada coordenacao, gostaria de ajustar minha matricula...",
        body=(
            "Prezada coordenacao,\n\n"
            "Gostaria de ajustar minha matricula na disciplina XYZ.\n\n"
            "Atenciosamente,\nAluno Teste"
        ),
        email_index=0,
        is_unread=True,
        timestamp="2026-04-10T10:00:00",
    )
    email.compute_stable_id()
    return email
