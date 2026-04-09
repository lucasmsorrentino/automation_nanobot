"""Tests for sei/ module — models, client utilities, despacho drafts."""

from __future__ import annotations

from ufpr_automation.sei.client import SEIClient, extract_grr, extract_sei_process_number
from ufpr_automation.sei.models import DocumentoSEI, ProcessoSEI


class TestExtractSEIProcessNumber:
    def test_valid_process_number(self):
        text = "O processo SEI 23075.123456/2026-01 foi encaminhado."
        assert extract_sei_process_number(text) == "23075.123456/2026-01"

    def test_no_match(self):
        assert extract_sei_process_number("Sem processo aqui") is None

    def test_multiple_matches_returns_first(self):
        text = "Processos 23075.111111/2026-01 e 23075.222222/2026-02"
        assert extract_sei_process_number(text) == "23075.111111/2026-01"

    def test_embedded_in_longer_text(self):
        text = "Ref: TCE n. 123 (SEI 23075.654321/2025-99) do aluno"
        assert extract_sei_process_number(text) == "23075.654321/2025-99"


class TestExtractGRR:
    def test_grr_with_prefix(self):
        assert extract_grr("aluno GRR20191234") == "GRR20191234"

    def test_grr_with_space(self):
        assert extract_grr("GRR 20191234") == "GRR20191234"

    def test_gr_prefix(self):
        assert extract_grr("matricula GR20191234") == "GRR20191234"

    def test_no_match(self):
        assert extract_grr("Sem matricula aqui") is None

    def test_case_insensitive(self):
        assert extract_grr("grr20191234") == "GRR20191234"


class TestProcessoSEI:
    def test_default_values(self):
        p = ProcessoSEI()
        assert p.numero == ""
        assert p.documentos == []
        assert p.interessados == []

    def test_with_documents(self):
        doc = DocumentoSEI(numero_sei="1234567", tipo="TCE")
        p = ProcessoSEI(
            numero="23075.123456/2026-01",
            tipo="Estagio",
            documentos=[doc],
        )
        assert len(p.documentos) == 1
        assert p.documentos[0].tipo == "TCE"


class TestDespachoDraft:
    def test_prepare_tce_inicial(self):
        draft = SEIClient.prepare_despacho_draft("tce_inicial")
        assert draft.tipo == "tce_inicial"
        assert "Compromisso de Estagio" in draft.conteudo
        assert "NUMERO_TCE" in draft.campos_pendentes
        assert "SOUL.md" in draft.template_usado

    def test_prepare_aditivo(self):
        draft = SEIClient.prepare_despacho_draft("aditivo")
        assert draft.tipo == "aditivo"
        assert "Aditivo" in draft.conteudo
        assert "NUMERO_ADITIVO" in draft.campos_pendentes

    def test_prepare_rescisao(self):
        draft = SEIClient.prepare_despacho_draft("rescisao")
        assert draft.tipo == "rescisao"
        assert "Rescisao" in draft.conteudo

    def test_fill_dados(self):
        dados = {
            "NUMERO_TCE": "12345",
            "NUMERO_PROCESSO_SEI": "23075.123456/2026-01",
            "GRR_MATRICULA": "GRR20191234",
        }
        draft = SEIClient.prepare_despacho_draft("tce_inicial", dados=dados)
        assert "12345" in draft.conteudo
        assert "GRR20191234" in draft.conteudo
        assert draft.processo_sei == "23075.123456/2026-01"
        # Filled fields should not appear in pendentes
        assert "NUMERO_TCE" not in draft.campos_pendentes
        assert "GRR_MATRICULA" not in draft.campos_pendentes

    def test_header_and_footer(self):
        draft = SEIClient.prepare_despacho_draft("tce_inicial")
        assert "UNIVERSIDADE FEDERAL DO PARANA" in draft.conteudo
        assert "Stephania Padovani" in draft.conteudo
        assert "Coordenadora do Curso de Design Grafico" in draft.conteudo
