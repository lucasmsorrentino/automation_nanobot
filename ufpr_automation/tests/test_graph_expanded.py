"""Tests for expanded LangGraph nodes — SEI/SIGA consultation and procedure logging."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ufpr_automation.core.models import EmailClassification, EmailData


def _make_email(subject="TCE Joao Silva - GRR20191234 - SEI 23075.123456/2026-01", **kwargs):
    """Create a sample EmailData for testing."""
    e = EmailData(
        sender="aluno@ufpr.br",
        subject=subject,
        body=kwargs.get("body", subject),
        stable_id=kwargs.get("stable_id", "test123"),
    )
    return e


def _make_cls(categoria="Estágios", **kwargs):
    """Create a sample EmailClassification."""
    return EmailClassification(
        categoria=categoria,
        resumo=kwargs.get("resumo", "Solicitacao de estagio"),
        acao_necessaria=kwargs.get("acao", "Redigir Resposta"),
        sugestao_resposta=kwargs.get("resposta", "Prezado..."),
        confianca=kwargs.get("confianca", 0.85),
    )


class TestConsultarSEI:
    def test_no_emails(self):
        from ufpr_automation.graph.nodes import consultar_sei

        result = consultar_sei({"emails": [], "classifications": {}})
        assert result["sei_contexts"] == {}

    def test_no_estagio_emails(self):
        from ufpr_automation.graph.nodes import consultar_sei

        email = _make_email(stable_id="x1")
        cls = _make_cls(categoria="Informes")
        result = consultar_sei({
            "emails": [email],
            "classifications": {"x1": cls},
        })
        assert result["sei_contexts"] == {}

    @patch("ufpr_automation.sei.browser.has_credentials", return_value=False)
    def test_no_credentials(self, mock_creds):
        from ufpr_automation.graph.nodes import consultar_sei

        email = _make_email(stable_id="x1")
        cls = _make_cls()
        result = consultar_sei({
            "emails": [email],
            "classifications": {"x1": cls},
        })
        assert result["sei_contexts"] == {}


class TestConsultarSIGA:
    def test_no_emails(self):
        from ufpr_automation.graph.nodes import consultar_siga

        result = consultar_siga({"emails": [], "classifications": {}})
        assert result["siga_contexts"] == {}

    def test_no_grr_in_email(self):
        from ufpr_automation.graph.nodes import consultar_siga

        email = _make_email(subject="Oficio generico", body="Sem matricula", stable_id="x1")
        cls = _make_cls()
        result = consultar_siga({
            "emails": [email],
            "classifications": {"x1": cls},
        })
        assert result["siga_contexts"] == {}

    @patch("ufpr_automation.siga.browser.has_credentials", return_value=False)
    def test_no_credentials(self, mock_creds):
        from ufpr_automation.graph.nodes import consultar_siga

        email = _make_email(stable_id="x1")
        cls = _make_cls()
        result = consultar_siga({
            "emails": [email],
            "classifications": {"x1": cls},
        })
        assert result["siga_contexts"] == {}


class TestRegistrarProcedimento:
    def test_empty_state(self):
        from ufpr_automation.graph.nodes import registrar_procedimento

        result = registrar_procedimento({
            "emails": [],
            "classifications": {},
            "drafts_saved": [],
            "sei_contexts": {},
            "siga_contexts": {},
            "auto_draft": [],
            "manual_escalation": [],
        })
        assert result["procedures_logged"] == 0

    def test_logs_procedure(self, tmp_path):
        from ufpr_automation.graph.nodes import registrar_procedimento

        email = _make_email(stable_id="x1")
        cls = _make_cls()

        with patch("ufpr_automation.procedures.store.PROCEDURES_FILE", tmp_path / "procs.jsonl"):
            result = registrar_procedimento({
                "emails": [email],
                "classifications": {"x1": cls},
                "drafts_saved": ["x1"],
                "sei_contexts": {"x1": {"numero": "23075.123456/2026-01"}},
                "siga_contexts": {},
                "auto_draft": ["x1"],
                "manual_escalation": [],
            })
        assert result["procedures_logged"] == 1


@pytest.mark.skipif(
    not pytest.importorskip("langgraph", reason="langgraph not installed"),
    reason="langgraph not installed",
)
class TestGraphBuilder:
    def test_needs_sei_siga_with_estagios(self):
        from ufpr_automation.graph.builder import _needs_sei_siga

        cls = _make_cls(categoria="Estágios")
        state = {"classifications": {"x1": cls}}
        assert _needs_sei_siga(state) == "consultar_sei"

    def test_needs_sei_siga_without_estagios(self):
        from ufpr_automation.graph.builder import _needs_sei_siga

        cls = _make_cls(categoria="Informes")
        state = {"classifications": {"x1": cls}}
        assert _needs_sei_siga(state) == "registrar_feedback"

    def test_needs_sei_siga_empty(self):
        from ufpr_automation.graph.builder import _needs_sei_siga

        assert _needs_sei_siga({"classifications": {}}) == "registrar_feedback"
