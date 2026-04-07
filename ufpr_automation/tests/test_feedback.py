"""Tests for feedback/store.py — FeedbackStore JSONL persistence."""

from __future__ import annotations

import json

import pytest

from ufpr_automation.core.models import EmailClassification
from ufpr_automation.feedback.store import FeedbackStore


@pytest.fixture
def store(tmp_path):
    return FeedbackStore(path=tmp_path / "test_feedback.jsonl")


@pytest.fixture
def original_cls():
    return EmailClassification(
        categoria="Outros",
        resumo="Classificação incorreta",
        acao_necessaria="Ignorar",
        sugestao_resposta="",
    )


@pytest.fixture
def corrected_cls():
    return EmailClassification(
        categoria="Estágios",
        resumo="Solicitação de estágio",
        acao_necessaria="Redigir Resposta",
        sugestao_resposta="Prezado, recebemos sua solicitação...",
    )


class TestFeedbackStore:
    def test_add_and_count(self, store, original_cls, corrected_cls):
        assert store.count() == 0

        store.add(
            email_hash="abc123",
            original=original_cls,
            corrected=corrected_cls,
            email_sender="prof@ufpr.br",
            email_subject="Estágio",
        )

        assert store.count() == 1

    def test_add_multiple_and_list(self, store, original_cls, corrected_cls):
        store.add("hash1", original_cls, corrected_cls, email_subject="Email 1")
        store.add("hash2", original_cls, corrected_cls, email_subject="Email 2")

        records = store.list_all()
        assert len(records) == 2
        assert records[0].email_hash == "hash1"
        assert records[1].email_hash == "hash2"

    def test_record_fields(self, store, original_cls, corrected_cls):
        store.add(
            email_hash="abc123",
            original=original_cls,
            corrected=corrected_cls,
            email_sender="prof@ufpr.br",
            email_subject="Estágio Obrigatório",
            notes="Categoria estava errada",
        )

        record = store.list_all()[0]
        assert record.email_hash == "abc123"
        assert record.email_sender == "prof@ufpr.br"
        assert record.email_subject == "Estágio Obrigatório"
        assert record.original.categoria == "Outros"
        assert record.corrected.categoria == "Estágios"
        assert record.notes == "Categoria estava errada"
        assert record.timestamp  # ISO format

    def test_empty_store(self, store):
        assert store.count() == 0
        assert store.list_all() == []

    def test_persistence(self, tmp_path, original_cls, corrected_cls):
        path = tmp_path / "feedback.jsonl"

        store1 = FeedbackStore(path=path)
        store1.add("hash1", original_cls, corrected_cls)

        store2 = FeedbackStore(path=path)
        assert store2.count() == 1
        records = store2.list_all()
        assert records[0].email_hash == "hash1"

    def test_jsonl_format(self, store, original_cls, corrected_cls):
        store.add("hash1", original_cls, corrected_cls)

        with open(store.path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["email_hash"] == "hash1"
        assert data["original"]["categoria"] == "Outros"
        assert data["corrected"]["categoria"] == "Estágios"
