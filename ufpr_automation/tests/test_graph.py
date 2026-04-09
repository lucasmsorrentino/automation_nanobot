"""Tests for graph/ — LangGraph builder, state, and node functions.

Tests the graph structure, conditional routing, and individual node behavior
with all external dependencies (Gmail, OWA, LLM, RAG) mocked.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from ufpr_automation.core.models import EmailClassification, EmailData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_email(sender: str = "prof@ufpr.br", subject: str = "Teste") -> EmailData:
    email = EmailData(sender=sender, subject=subject, body="corpo do email")
    email.compute_stable_id()
    return email


def _make_cls(
    categoria: str = "Estágios",
    confianca: float = 0.95,
    sugestao: str = "Prezado(a), recebemos...",
) -> EmailClassification:
    return EmailClassification(
        categoria=categoria,
        resumo="Resumo",
        acao_necessaria="Redigir Resposta",
        sugestao_resposta=sugestao,
        confianca=confianca,
    )


# ===========================================================================
# builder.py — _has_emails routing function
# ===========================================================================


class TestHasEmails:
    def test_routes_to_rag_when_emails_present(self):
        from ufpr_automation.graph.builder import _has_emails

        state = {"emails": [_make_email()]}
        assert _has_emails(state) == "rag_retrieve"

    def test_routes_to_end_when_no_emails(self):
        from ufpr_automation.graph.builder import _has_emails

        assert _has_emails({"emails": []}) == "end"
        assert _has_emails({}) == "end"


# ===========================================================================
# builder.py — build_graph structure
# ===========================================================================


class TestBuildGraph:
    """Test graph compilation and node presence (no invocation)."""

    def test_gmail_channel_compiles(self):
        from ufpr_automation.graph.builder import build_graph

        graph = build_graph(channel="gmail")
        # The compiled graph should be callable
        assert callable(getattr(graph, "invoke", None))

    def test_owa_channel_compiles(self):
        from ufpr_automation.graph.builder import build_graph

        graph = build_graph(channel="owa")
        assert callable(getattr(graph, "invoke", None))

    def test_graph_has_expected_nodes(self):
        from ufpr_automation.graph.builder import build_graph

        graph = build_graph(channel="gmail")
        # LangGraph compiled graph exposes .get_graph() with node info
        g = graph.get_graph()
        # g.nodes may be a dict or list of strings depending on version
        if isinstance(g.nodes, dict):
            node_ids = set(g.nodes.keys())
        else:
            node_ids = set(g.nodes)
        assert "perceber" in node_ids
        assert "rag_retrieve" in node_ids
        assert "classificar" in node_ids
        assert "rotear" in node_ids
        assert "agir" in node_ids


# ===========================================================================
# nodes.py — perceber_gmail
# ===========================================================================


class TestPerceberGmail:
    def test_returns_emails_on_success(self):
        from ufpr_automation.graph.nodes import perceber_gmail

        mock_client = MagicMock()
        mock_client.list_unread.return_value = [_make_email(), _make_email("b@ufpr.br", "Sub B")]

        with patch("ufpr_automation.gmail.client.GmailClient", return_value=mock_client):
            result = perceber_gmail({"errors": []})

        assert len(result["emails"]) == 2
        assert result["errors"] == []

    def test_returns_empty_on_error(self):
        from ufpr_automation.graph.nodes import perceber_gmail

        mock_client = MagicMock()
        mock_client.list_unread.side_effect = RuntimeError("IMAP error")

        with patch("ufpr_automation.gmail.client.GmailClient", return_value=mock_client):
            result = perceber_gmail({"errors": []})

        assert result["emails"] == []
        assert len(result["errors"]) == 1
        assert result["errors"][0]["node"] == "perceber_gmail"

    def test_preserves_existing_errors(self):
        from ufpr_automation.graph.nodes import perceber_gmail

        mock_client = MagicMock()
        mock_client.list_unread.side_effect = RuntimeError("fail")
        prior = [{"node": "prior", "error": "old"}]

        with patch("ufpr_automation.gmail.client.GmailClient", return_value=mock_client):
            result = perceber_gmail({"errors": prior})

        assert len(result["errors"]) == 2


# ===========================================================================
# nodes.py — rag_retrieve
# ===========================================================================


class TestRagRetrieve:
    def test_returns_empty_for_no_emails(self):
        from ufpr_automation.graph.nodes import rag_retrieve

        result = rag_retrieve({"emails": []})
        assert result["rag_contexts"] == {}

    def test_returns_contexts_for_emails(self):
        from ufpr_automation.graph.nodes import rag_retrieve

        email = _make_email(subject="Estagio obrigatorio")
        mock_retriever = MagicMock()
        mock_retriever.search_formatted.return_value = "Art. 1 ..."

        with (
            patch("ufpr_automation.graph.nodes._get_retriever", return_value=mock_retriever),
            patch("ufpr_automation.graph.nodes._get_reflexion_context", return_value={}),
        ):
            result = rag_retrieve({"emails": [email]})

        assert email.stable_id in result["rag_contexts"]
        assert "Art. 1" in result["rag_contexts"][email.stable_id]

    def test_skips_empty_rag_results(self):
        from ufpr_automation.graph.nodes import rag_retrieve

        email = _make_email()
        mock_retriever = MagicMock()
        mock_retriever.search_formatted.return_value = "Nenhum documento relevante encontrado."

        with (
            patch("ufpr_automation.graph.nodes._get_retriever", return_value=mock_retriever),
            patch("ufpr_automation.graph.nodes._get_reflexion_context", return_value={}),
        ):
            result = rag_retrieve({"emails": [email]})

        assert result["rag_contexts"] == {}

    def test_appends_reflexion_context(self):
        from ufpr_automation.graph.nodes import rag_retrieve

        email = _make_email()
        mock_retriever = MagicMock()
        mock_retriever.search_formatted.return_value = "RAG context"
        reflexion_ctx = {email.stable_id: "=== ERROS ANTERIORES ==="}

        with (
            patch("ufpr_automation.graph.nodes._get_retriever", return_value=mock_retriever),
            patch("ufpr_automation.graph.nodes._get_reflexion_context", return_value=reflexion_ctx),
        ):
            result = rag_retrieve({"emails": [email]})

        ctx = result["rag_contexts"][email.stable_id]
        assert "RAG context" in ctx
        assert "ERROS ANTERIORES" in ctx

    def test_graceful_on_rag_unavailable(self):
        from ufpr_automation.graph.nodes import rag_retrieve

        email = _make_email()

        with patch(
            "ufpr_automation.graph.nodes._get_retriever",
            side_effect=Exception("LanceDB not found"),
        ):
            result = rag_retrieve({"emails": [email]})

        assert result["rag_contexts"] == {}


# ===========================================================================
# nodes.py — classificar
# ===========================================================================


class TestClassificar:
    def test_returns_empty_for_no_emails(self):
        from ufpr_automation.graph.nodes import classificar

        with patch("ufpr_automation.llm.router.log_cascade_config"):
            result = classificar({"emails": [], "rag_contexts": {}})

        assert result["classifications"] == {}

    def test_calls_dspy_when_available(self):
        from ufpr_automation.graph.nodes import classificar

        email = _make_email()
        cls = _make_cls()

        with (
            patch("ufpr_automation.llm.router.log_cascade_config"),
            patch(
                "ufpr_automation.graph.nodes._classify_with_dspy",
                return_value={email.stable_id: cls},
            ) as mock_dspy,
        ):
            result = classificar({"emails": [email], "rag_contexts": {}})

        mock_dspy.assert_called_once()
        assert email.stable_id in result["classifications"]


# ===========================================================================
# nodes.py — agir_gmail
# ===========================================================================


class TestAgirGmail:
    def test_saves_drafts_for_eligible_emails(self):
        from ufpr_automation.graph.nodes import agir_gmail

        email = _make_email()
        cls = _make_cls(sugestao="Prezado, segue resposta...")

        mock_gmail = MagicMock()
        mock_gmail.save_draft.return_value = True

        state = {
            "emails": [email],
            "classifications": {email.stable_id: cls},
            "auto_draft": [email.stable_id],
            "human_review": [],
        }

        with (
            patch("ufpr_automation.gmail.client.GmailClient", return_value=mock_gmail),
            patch("ufpr_automation.graph.nodes._save_run_results"),
        ):
            result = agir_gmail(state)

        assert email.stable_id in result["drafts_saved"]
        mock_gmail.save_draft.assert_called_once()
        mock_gmail.mark_read.assert_called_once()

    def test_skips_email_without_response(self):
        from ufpr_automation.graph.nodes import agir_gmail

        email = _make_email()
        cls = _make_cls(sugestao="")  # empty response

        mock_gmail = MagicMock()
        state = {
            "emails": [email],
            "classifications": {email.stable_id: cls},
            "auto_draft": [email.stable_id],
            "human_review": [],
        }

        with (
            patch("ufpr_automation.gmail.client.GmailClient", return_value=mock_gmail),
            patch("ufpr_automation.graph.nodes._save_run_results"),
        ):
            result = agir_gmail(state)

        assert result["drafts_saved"] == []
        mock_gmail.save_draft.assert_not_called()

    def test_no_drafts_when_no_eligible(self):
        from ufpr_automation.graph.nodes import agir_gmail

        email = _make_email()
        cls = _make_cls(confianca=0.3)  # low confidence -> manual escalation

        state = {
            "emails": [email],
            "classifications": {email.stable_id: cls},
            "auto_draft": [],
            "human_review": [],
            "manual_escalation": [email.stable_id],
        }

        with patch("ufpr_automation.graph.nodes._save_run_results"):
            result = agir_gmail(state)

        assert result["drafts_saved"] == []

    def test_extracts_email_from_angle_brackets(self):
        from ufpr_automation.graph.nodes import agir_gmail

        email = _make_email(sender="Prof Silva <prof.silva@ufpr.br>")
        cls = _make_cls(sugestao="Prezado, resposta aqui.")

        mock_gmail = MagicMock()
        mock_gmail.save_draft.return_value = True

        state = {
            "emails": [email],
            "classifications": {email.stable_id: cls},
            "auto_draft": [email.stable_id],
            "human_review": [],
        }

        with (
            patch("ufpr_automation.gmail.client.GmailClient", return_value=mock_gmail),
            patch("ufpr_automation.graph.nodes._save_run_results"),
        ):
            agir_gmail(state)

        call_kwargs = mock_gmail.save_draft.call_args
        assert call_kwargs[1]["to_addr"] == "prof.silva@ufpr.br" or \
               call_kwargs[0][0] == "prof.silva@ufpr.br"
