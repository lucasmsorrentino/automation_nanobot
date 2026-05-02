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


@pytest.fixture
def make_email():
    """Factory para ``EmailData`` em testes.

    Substitui as 5+ reimplementacoes de ``_make_email`` espalhadas por
    ``test_graph.py``, ``test_agir_estagios.py``, ``test_pipeline.py``,
    ``test_tier0_lookup.py``, ``test_graph_expanded.py``. Aceita superset
    de params: se ``stable_id`` for passado explicito, usa esse; senao
    chama ``compute_stable_id()``.

    Uso:
        def test_foo(make_email):
            email = make_email(sender="aluno@ufpr.br", subject="TCE")
    """
    from ufpr_automation.core.models import EmailData

    def _factory(
        sender: str = "prof@ufpr.br",
        subject: str = "Teste",
        body: str = "corpo do email",
        stable_id: str | None = None,
    ) -> EmailData:
        e = EmailData(sender=sender, subject=subject, body=body)
        if stable_id is not None:
            e.stable_id = stable_id
        else:
            e.compute_stable_id()
        return e

    return _factory


@pytest.fixture
def make_classification():
    """Factory para ``EmailClassification`` em testes.

    Substitui as 5+ reimplementacoes de ``_make_cls``/``_make_classification``
    espalhadas pelos test files. Aceita superset de params.

    Uso:
        def test_foo(make_classification):
            cls = make_classification(categoria="Estágios", confianca=0.85)
    """
    from ufpr_automation.core.models import EmailClassification

    def _factory(
        categoria: str = "Estágios",
        confianca: float = 0.95,
        sugestao: str = "Prezado(a), recebemos...",
        resumo: str = "Resumo",
        acao_necessaria: str = "Redigir Resposta",
    ) -> EmailClassification:
        return EmailClassification(
            categoria=categoria,
            resumo=resumo,
            acao_necessaria=acao_necessaria,
            sugestao_resposta=sugestao,
            confianca=confianca,
        )

    return _factory


@pytest.fixture
def require_rag_docs():
    """Skip o teste se RAG docs nao estao disponiveis localmente.

    Alguns testes em ``test_rag.py`` skipam quando ``RAG_DOCS_DIR`` nao
    contem subpastas esperadas (estagio/, cepe/resolucoes/) — caso comum
    em CI ou em maquinas onde G:/Meu Drive/ufpr_rag nao esta sincronizado.
    Esta fixture centraliza o skip.

    Uso:
        def test_rag_estagio(require_rag_docs):
            docs_dir = require_rag_docs("estagio")
            ...
    """
    import os
    from pathlib import Path

    def _check(subset: str = ""):
        rag_docs_dir = Path(os.getenv("RAG_DOCS_DIR", "ufpr_automation/docs"))
        target = rag_docs_dir / subset if subset else rag_docs_dir
        if not target.exists():
            pytest.skip(f"RAG docs nao disponiveis: {target}")
        return target

    return _check
