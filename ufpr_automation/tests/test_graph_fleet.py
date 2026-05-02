"""Tests for LangGraph Fleet dispatch and sub-agent."""

from __future__ import annotations

from unittest.mock import patch

from langgraph.types import Send

from ufpr_automation.core.models import EmailClassification, EmailData
from ufpr_automation.graph.fleet import dispatch_tier1, process_one_email


def _email(stable_id: str, subject: str = "test") -> EmailData:
    e = EmailData(sender="test@ufpr.br", subject=subject, body="test body")
    e.stable_id = stable_id
    return e


def _cls(categoria: str = "Outros", confianca: float = 0.7) -> EmailClassification:
    return EmailClassification(
        categoria=categoria,
        resumo="x",
        acao_necessaria="Revisão Manual",
        sugestao_resposta="",
        confianca=confianca,
    )


class TestDispatchTier1:
    def test_returns_rotear_when_all_tier0(self):
        emails = [_email("e1"), _email("e2")]
        state = {"emails": emails, "tier0_hits": ["e1", "e2"]}
        result = dispatch_tier1(state)
        assert result == "rotear"

    def test_returns_send_list_for_tier1(self):
        emails = [_email("e1"), _email("e2"), _email("e3")]
        state = {"emails": emails, "tier0_hits": ["e1"]}
        result = dispatch_tier1(state)
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(s, Send) for s in result)
        assert all(s.node == "process_one_email" for s in result)
        sent_ids = {s.arg["stable_id"] for s in result}
        assert sent_ids == {"e2", "e3"}

    def test_returns_send_list_for_all_when_no_tier0(self):
        emails = [_email("e1"), _email("e2")]
        state = {"emails": emails}
        result = dispatch_tier1(state)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_returns_rotear_for_empty_emails(self):
        state = {"emails": [], "tier0_hits": []}
        result = dispatch_tier1(state)
        assert result == "rotear"


class TestProcessOneEmail:
    def test_classifies_single_email_via_litellm(self):
        email = _email("e1", "matricula")
        cls = _cls("Outros", 0.7)
        with (
            patch("ufpr_automation.graph.nodes._get_retriever", return_value=None),
            patch("ufpr_automation.graph.nodes._get_graph_context", return_value=""),
            patch("ufpr_automation.graph.nodes._get_reflexion_context_single", return_value=""),
            patch(
                "ufpr_automation.graph.nodes._classify_with_litellm",
                return_value={"e1": cls},
            ),
        ):
            result = process_one_email({"email": email, "stable_id": "e1"})
        assert "e1" in result["classifications"]
        assert result["classifications"]["e1"] is cls
        assert result["errors"] == []

    def test_stores_rag_context_in_result(self):
        email = _email("e1")
        cls = _cls()

        class FakeRetriever:
            def search_formatted(self, query, top_k):
                return "Art. 1 ..."

        with (
            patch(
                "ufpr_automation.graph.nodes._get_retriever",
                return_value=FakeRetriever(),
            ),
            patch("ufpr_automation.graph.nodes._get_graph_context", return_value=""),
            patch("ufpr_automation.graph.nodes._get_reflexion_context_single", return_value=""),
            patch(
                "ufpr_automation.graph.nodes._classify_with_litellm",
                return_value={"e1": cls},
            ),
        ):
            result = process_one_email({"email": email, "stable_id": "e1"})
        assert "Art. 1" in result["rag_contexts"]["e1"]

    def test_skips_sei_siga_for_non_estagios(self):
        email = _email("e1", "matricula")
        cls = _cls("Outros", 0.7)
        with (
            patch("ufpr_automation.graph.nodes._get_retriever", return_value=None),
            patch("ufpr_automation.graph.nodes._get_graph_context", return_value=""),
            patch("ufpr_automation.graph.nodes._get_reflexion_context_single", return_value=""),
            patch(
                "ufpr_automation.graph.nodes._classify_with_litellm",
                return_value={"e1": cls},
            ),
            patch("ufpr_automation.graph.nodes._consult_sei_for_email") as sei_mock,
            patch("ufpr_automation.graph.nodes._consult_siga_for_email") as siga_mock,
        ):
            process_one_email({"email": email, "stable_id": "e1"})
        sei_mock.assert_not_called()
        siga_mock.assert_not_called()

    def test_consults_sei_siga_for_estagios(self):
        email = _email("e1", "estagio")
        cls = _cls("Estágios", 0.9)
        with (
            patch("ufpr_automation.graph.nodes._get_retriever", return_value=None),
            patch("ufpr_automation.graph.nodes._get_graph_context", return_value=""),
            patch("ufpr_automation.graph.nodes._get_reflexion_context_single", return_value=""),
            patch(
                "ufpr_automation.graph.nodes._classify_with_litellm",
                return_value={"e1": cls},
            ),
            patch(
                "ufpr_automation.graph.nodes._consult_sei_for_email",
                return_value={"sei": "data"},
            ),
            patch(
                "ufpr_automation.graph.nodes._consult_siga_for_email",
                return_value={"siga": "data"},
            ),
        ):
            result = process_one_email({"email": email, "stable_id": "e1"})
        assert result["sei_contexts"] == {"e1": {"sei": "data"}}
        assert result["siga_contexts"] == {"e1": {"siga": "data"}}

    def test_sei_siga_returning_none_does_not_populate(self):
        """Estágios email with no process number / GRR → helpers return None."""
        email = _email("e1", "estagio")
        cls = _cls("Estágios", 0.9)
        with (
            patch("ufpr_automation.graph.nodes._get_retriever", return_value=None),
            patch("ufpr_automation.graph.nodes._get_graph_context", return_value=""),
            patch("ufpr_automation.graph.nodes._get_reflexion_context_single", return_value=""),
            patch(
                "ufpr_automation.graph.nodes._classify_with_litellm",
                return_value={"e1": cls},
            ),
            patch("ufpr_automation.graph.nodes._consult_sei_for_email", return_value=None),
            patch("ufpr_automation.graph.nodes._consult_siga_for_email", return_value=None),
        ):
            result = process_one_email({"email": email, "stable_id": "e1"})
        assert result["sei_contexts"] == {}
        assert result["siga_contexts"] == {}

    def test_rag_failure_does_not_block_classification(self):
        """If RAG fails, classification should still run and succeed."""
        email = _email("e1")
        cls = _cls()
        with (
            patch(
                "ufpr_automation.graph.nodes._get_retriever",
                side_effect=RuntimeError("boom"),
            ),
            patch("ufpr_automation.graph.nodes._get_graph_context", return_value=""),
            patch("ufpr_automation.graph.nodes._get_reflexion_context_single", return_value=""),
            patch(
                "ufpr_automation.graph.nodes._classify_with_litellm",
                return_value={"e1": cls},
            ),
        ):
            result = process_one_email({"email": email, "stable_id": "e1"})
        assert "e1" in result["classifications"]
        assert result["rag_contexts"]["e1"] == ""
        assert result["errors"] == []

