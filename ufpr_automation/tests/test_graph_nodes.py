"""Tests for graph/nodes.py — LangGraph pipeline node functions."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from ufpr_automation.core.models import EmailClassification, EmailData
from ufpr_automation.graph.nodes import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    rotear,
)


@pytest.fixture
def sample_emails():
    emails = []
    for i, (sender, subject) in enumerate([
        ("prof@ufpr.br", "Solicitação de Estágio"),
        ("sec@ufpr.br", "Informe Reunião"),
        ("spam@fake.com", "Promoção imperdível"),
    ]):
        e = EmailData(sender=sender, subject=subject, body=f"Corpo do email {i}")
        e.compute_stable_id()
        emails.append(e)
    return emails


@pytest.fixture
def sample_classifications(sample_emails):
    return {
        sample_emails[0].stable_id: EmailClassification(
            categoria="Estágios",
            resumo="Solicitação de estágio",
            acao_necessaria="Redigir Resposta",
            sugestao_resposta="Prezado...",
            confianca=0.98,  # HIGH → auto-draft
        ),
        sample_emails[1].stable_id: EmailClassification(
            categoria="Informes",
            resumo="Aviso de reunião",
            acao_necessaria="Arquivar",
            sugestao_resposta="Obrigado pelo aviso.",
            confianca=0.80,  # MEDIUM → human review
        ),
        sample_emails[2].stable_id: EmailClassification(
            categoria="Correio Lixo",
            resumo="Spam detectado",
            acao_necessaria="Ignorar",
            sugestao_resposta="",
            confianca=0.55,  # LOW → manual escalation
        ),
    }


class TestRotear:
    """Test confidence-based routing logic."""

    def test_high_confidence_auto_draft(self, sample_emails, sample_classifications):
        state = {"classifications": sample_classifications}
        result = rotear(state)

        assert sample_emails[0].stable_id in result["auto_draft"]
        assert sample_emails[0].stable_id not in result["human_review"]
        assert sample_emails[0].stable_id not in result["manual_escalation"]

    def test_medium_confidence_human_review(self, sample_emails, sample_classifications):
        state = {"classifications": sample_classifications}
        result = rotear(state)

        assert sample_emails[1].stable_id in result["human_review"]
        assert sample_emails[1].stable_id not in result["auto_draft"]

    def test_low_confidence_manual_escalation(self, sample_emails, sample_classifications):
        state = {"classifications": sample_classifications}
        result = rotear(state)

        assert sample_emails[2].stable_id in result["manual_escalation"]
        assert sample_emails[2].stable_id not in result["auto_draft"]
        assert sample_emails[2].stable_id not in result["human_review"]

    def test_empty_classifications(self):
        state = {"classifications": {}}
        result = rotear(state)
        assert result["auto_draft"] == []
        assert result["human_review"] == []
        assert result["manual_escalation"] == []

    def test_threshold_boundary_high(self, sample_emails):
        """Exactly at CONFIDENCE_HIGH boundary should be auto_draft."""
        cls = EmailClassification(
            categoria="Estágios", resumo="test", acao_necessaria="test",
            sugestao_resposta="test", confianca=CONFIDENCE_HIGH,
        )
        state = {"classifications": {sample_emails[0].stable_id: cls}}
        result = rotear(state)
        assert sample_emails[0].stable_id in result["auto_draft"]

    def test_threshold_boundary_medium(self, sample_emails):
        """Just below CONFIDENCE_HIGH should be human_review."""
        cls = EmailClassification(
            categoria="Estágios", resumo="test", acao_necessaria="test",
            sugestao_resposta="test", confianca=CONFIDENCE_HIGH - 0.01,
        )
        state = {"classifications": {sample_emails[0].stable_id: cls}}
        result = rotear(state)
        assert sample_emails[0].stable_id in result["human_review"]


class TestSaveRunResults:
    """Test that pipeline results are saved for feedback review."""

    def test_saves_jsonl(self, sample_emails, sample_classifications, tmp_path):
        from ufpr_automation.graph.nodes import _save_run_results

        with patch("ufpr_automation.feedback.store.FEEDBACK_DIR", tmp_path):
            _save_run_results(sample_emails, sample_classifications)

        results_file = tmp_path / "last_run.jsonl"
        assert results_file.exists()

        lines = results_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3

        first = json.loads(lines[0])
        assert "email_hash" in first
        assert "sender" in first
        assert "subject" in first
        assert "classification" in first
        assert first["classification"]["categoria"] in [
            "Estágios", "Informes", "Correio Lixo",
        ]
