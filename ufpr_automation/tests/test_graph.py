"""Tests for graph/ — LangGraph builder, state, and node functions.

Tests the graph structure, conditional routing, and individual node behavior
with all external dependencies (Gmail, OWA, LLM, RAG) mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ufpr_automation.core.models import EmailClassification, EmailData

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_email(sender: str = "prof@ufpr.br", subject: str = "Teste") -> EmailData:
    """Local factory — mantida por compat. Novos testes devem usar a
    fixture ``make_email`` de ``conftest.py``."""
    email = EmailData(sender=sender, subject=subject, body="corpo do email")
    email.compute_stable_id()
    return email


def _make_cls(
    categoria: str = "Estágios",
    confianca: float = 0.95,
    sugestao: str = "Prezado(a), recebemos...",
) -> EmailClassification:
    """Local factory — mantida por compat. Novos testes devem usar a
    fixture ``make_classification`` de ``conftest.py``."""
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
    def test_routes_to_tier0_when_emails_present(self):
        # After Hybrid Memory: perceber -> tier0_lookup -> (maybe rag_retrieve)
        from ufpr_automation.graph.builder import _has_emails

        state = {"emails": [_make_email()]}
        assert _has_emails(state) == "tier0_lookup"

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
        assert "tier0_lookup" in node_ids
        # Fleet fan-out replaces the sequential rag_retrieve / classificar
        # / consultar_sei / consultar_siga chain with a single per-email
        # sub-agent node invoked in parallel via Send.
        assert "process_one_email" in node_ids
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

    def test_extracts_attachment_text(self):
        """Regression: perceber_gmail must extract text from each attachment so
        Tier 0 regex (TCE, concedente, dates) can match content that lives in
        PDFs rather than the email body. Missing this wiring caused the Fleet
        pipeline to never Tier-0-hit Estágios intents even with attachments.
        """
        from ufpr_automation.core.models import AttachmentData
        from ufpr_automation.graph.nodes import perceber_gmail

        email = _make_email()
        email.attachments = [
            AttachmentData(filename="tce.pdf", local_path="/tmp/tce.pdf"),
            AttachmentData(filename="anexo2.pdf", local_path="/tmp/anexo2.pdf"),
        ]
        mock_client = MagicMock()
        mock_client.list_unread.return_value = [email]

        with (
            patch("ufpr_automation.gmail.client.GmailClient", return_value=mock_client),
            patch("ufpr_automation.attachments.extract_text_from_attachment") as mock_extract,
        ):
            result = perceber_gmail({"errors": []})

        assert len(result["emails"]) == 1
        assert mock_extract.call_count == 2
        called_attachments = [c.args[0] for c in mock_extract.call_args_list]
        assert called_attachments[0].filename == "tce.pdf"
        assert called_attachments[1].filename == "anexo2.pdf"


# Testes ``TestRagRetrieve`` e ``TestClassificar`` removidos em
# 2026-05-02 (Onda 2.3) junto com as funcoes legacy batch ``rag_retrieve``
# e ``classificar``. O Fleet topology default (``process_one_email`` em
# ``graph/fleet.py``) cobre RAG retrieval + classify per-email; o
# comportamento do path quente continua coberto por ``test_graph_fleet.py``,
# ``test_graphrag.py`` e os tests de ``classify_email_async`` em
# ``test_llm_client.py``.


# ===========================================================================
# nodes.py — agir_gmail
# ===========================================================================


class TestStateReducers:
    """Reducers merge concurrent Fleet sub-agent outputs into EmailState."""

    def test_merge_dict_combines_disjoint(self):
        from ufpr_automation.graph.state import _merge_dict

        a = {"e1": "ctx1"}
        b = {"e2": "ctx2"}
        assert _merge_dict(a, b) == {"e1": "ctx1", "e2": "ctx2"}

    def test_merge_dict_handles_empty(self):
        from ufpr_automation.graph.state import _merge_dict

        a = {"e1": "ctx1"}
        assert _merge_dict({}, a) == a
        assert _merge_dict(a, {}) == a
        assert _merge_dict({}, {}) == {}

    def test_merge_dict_later_wins_on_conflict(self):
        """Overlapping keys: later dict wins (dict-spread semantics)."""
        from ufpr_automation.graph.state import _merge_dict

        a = {"e1": "old"}
        b = {"e1": "new"}
        assert _merge_dict(a, b) == {"e1": "new"}


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
        assert (
            call_kwargs[1]["to_addr"] == "prof.silva@ufpr.br"
            or call_kwargs[0][0] == "prof.silva@ufpr.br"
        )
