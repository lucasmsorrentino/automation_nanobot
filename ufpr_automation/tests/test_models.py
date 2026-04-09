"""Tests for core/models.py — EmailData and EmailClassification."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ufpr_automation.core.models import EmailClassification, EmailData


class TestEmailClassification:
    def test_valid_categoria(self):
        cls = EmailClassification(
            categoria="Estágios",
            resumo="Resumo do e-mail.",
            acao_necessaria="Arquivar",
            sugestao_resposta="",
        )
        assert cls.categoria == "Estágios"

    def test_invalid_categoria_rejected(self):
        with pytest.raises(ValidationError):
            EmailClassification(
                categoria="CategoriaInválida",
                resumo="Resumo.",
                acao_necessaria="Arquivar",
                sugestao_resposta="",
            )

    def test_all_valid_categorias(self):
        valid = [
            "Estágios",
            "Acadêmico / Matrícula",
            "Acadêmico / Equivalência de Disciplinas",
            "Acadêmico / Aproveitamento de Disciplinas",
            "Acadêmico / Ajuste de Disciplinas",
            "Diplomação / Diploma",
            "Diplomação / Colação de Grau",
            "Extensão",
            "Formativas",
            "Requerimentos",
            "Urgente",
            "Correio Lixo",
            "Outros",
        ]
        for cat in valid:
            cls = EmailClassification(
                categoria=cat,
                resumo="r",
                acao_necessaria="a",
                sugestao_resposta="",
            )
            assert cls.categoria == cat

    def test_model_dump_roundtrip(self):
        cls = EmailClassification(
            categoria="Diplomação / Diploma",
            resumo="Solicitação de emissão de diploma.",
            acao_necessaria="Encaminhar para Secretaria",
            sugestao_resposta="Prezado(a), encaminhamos...",
        )
        data = cls.model_dump()
        restored = EmailClassification(**data)
        assert restored == cls


class TestEmailData:
    def test_defaults(self):
        email = EmailData()
        assert email.sender == ""
        assert email.email_index == -1
        assert email.stable_id == ""
        assert email.classification is None

    def test_compute_stable_id_deterministic(self):
        email = EmailData(sender="alice@ufpr.br", subject="Estágio", timestamp="2026-01-01")
        id1 = email.compute_stable_id()
        id2 = email.compute_stable_id()
        assert id1 == id2
        assert len(id1) == 16

    def test_stable_id_changes_with_inputs(self):
        e1 = EmailData(sender="alice@ufpr.br", subject="Estágio", timestamp="2026-01-01")
        e2 = EmailData(sender="bob@ufpr.br", subject="Estágio", timestamp="2026-01-01")
        e1.compute_stable_id()
        e2.compute_stable_id()
        assert e1.stable_id != e2.stable_id

    def test_str_unread(self):
        email = EmailData(sender="Alice", subject="Teste", is_unread=True)
        assert "📩" in str(email)
        assert "[Alice]" in str(email)

    def test_str_read(self):
        email = EmailData(sender="Alice", subject="Teste", is_unread=False)
        assert "📧" in str(email)

    def test_to_dict_includes_stable_id(self):
        email = EmailData(sender="a", subject="b", timestamp="c")
        email.compute_stable_id()
        d = email.to_dict()
        assert "stable_id" in d
        assert d["stable_id"] == email.stable_id

    def test_to_dict_with_classification(self):
        cls = EmailClassification(
            categoria="Estágios",
            resumo="r",
            acao_necessaria="a",
            sugestao_resposta="s",
        )
        email = EmailData(sender="x", subject="y", classification=cls)
        d = email.to_dict()
        assert d["classification"]["categoria"] == "Estágios"
