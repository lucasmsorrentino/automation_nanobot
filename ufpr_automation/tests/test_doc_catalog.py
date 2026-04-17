"""Tests for procedures/doc_catalog.py — SEI document classification loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from ufpr_automation.procedures.doc_catalog import (
    get_doc_classification,
    list_labels,
    reload_catalog,
)
from ufpr_automation.sei.writer_models import SEIDocClassification

SAMPLE_CATALOG = """\
TCE:
  sei_tipo: Externo
  sei_subtipo: Termo
  sei_classificacao: Inicial
  sigiloso: true
  motivo_sigilo: "Informação Pessoal"

Relatório Parcial:
  sei_tipo: Externo
  sei_subtipo: Relatório
  sei_classificacao: Parcial
  sigiloso: true
  motivo_sigilo: "Informação Pessoal"
"""


@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure each test starts with a clean LRU cache."""
    reload_catalog()
    yield
    reload_catalog()


@pytest.fixture
def catalog_path(tmp_path: Path) -> Path:
    p = tmp_path / "SEI_DOC_CATALOG.yaml"
    p.write_text(SAMPLE_CATALOG, encoding="utf-8")
    return p


class TestGetDocClassification:
    def test_exact_match(self, catalog_path):
        cls = get_doc_classification("TCE", path=catalog_path)
        assert cls is not None
        assert isinstance(cls, SEIDocClassification)
        assert cls.sei_tipo == "Externo"
        assert cls.sei_subtipo == "Termo"
        assert cls.sei_classificacao == "Inicial"
        assert cls.sigiloso is True
        assert cls.motivo_sigilo == "Informação Pessoal"

    def test_case_insensitive(self, catalog_path):
        cls = get_doc_classification("tce", path=catalog_path)
        assert cls is not None
        assert cls.sei_subtipo == "Termo"

    def test_multi_word_label(self, catalog_path):
        cls = get_doc_classification("Relatório Parcial", path=catalog_path)
        assert cls is not None
        assert cls.sei_subtipo == "Relatório"
        assert cls.sei_classificacao == "Parcial"

    def test_unknown_label_returns_none(self, catalog_path):
        assert get_doc_classification("Inexistente", path=catalog_path) is None

    def test_missing_file_returns_none(self, tmp_path):
        assert get_doc_classification("TCE", path=tmp_path / "nope.yaml") is None


class TestListLabels:
    def test_returns_all_labels(self, catalog_path):
        labels = list_labels(path=catalog_path)
        assert "TCE" in labels
        assert "Relatório Parcial" in labels
        assert len(labels) == 2


class TestRealCatalog:
    """Smoke test against the actual workspace/SEI_DOC_CATALOG.yaml."""

    def test_real_catalog_loads(self):
        cls = get_doc_classification("TCE")
        assert cls is not None
        assert cls.sei_tipo == "Externo"

    def test_real_catalog_has_expected_labels(self):
        labels = list_labels()
        expected = [
            "TCE",
            "Termo Aditivo",
            "Termo de Rescisão",
            "Relatório Parcial",
            "Relatório Final",
            "Ficha de Avaliação",
        ]
        for lbl in expected:
            assert lbl in labels, f"Missing label: {lbl}"
