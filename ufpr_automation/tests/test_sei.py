"""Tests for sei/ module — models, client utilities, despacho drafts."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ufpr_automation.graphrag.seed import _compose_despacho
from ufpr_automation.sei.client import (
    SEIClient,
    extract_grr,
    extract_sei_process_number,
    extract_year_from_numero,
    select_best_processo,
)
from ufpr_automation.sei.models import DocumentoSEI, ProcessoSEI


@pytest.fixture
def mock_template_registry():
    """Patch ``graphrag.templates.get_registry`` so SEI tests do not need Neo4j.

    The registry returned serves the real despacho templates (header + body +
    footer, composed identically to the seeder) straight from
    ``graphrag.seed._compose_despacho``, so any substring assertions against
    the canonical text remain valid.
    """
    fake = MagicMock()
    fake.get.side_effect = lambda tipo: _compose_despacho(tipo)
    with patch(
        "ufpr_automation.graphrag.templates.get_registry",
        return_value=fake,
    ):
        yield fake


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
    def test_prepare_tce_inicial(self, mock_template_registry):
        draft = SEIClient.prepare_despacho_draft("tce_inicial")
        assert draft.tipo == "tce_inicial"
        assert "Compromisso de Estagio" in draft.conteudo
        assert "NUMERO_TCE" in draft.campos_pendentes
        assert "SOUL.md" in draft.template_usado

    def test_prepare_aditivo(self, mock_template_registry):
        draft = SEIClient.prepare_despacho_draft("aditivo")
        assert draft.tipo == "aditivo"
        assert "Aditivo" in draft.conteudo
        assert "NUMERO_ADITIVO" in draft.campos_pendentes

    def test_prepare_rescisao(self, mock_template_registry):
        draft = SEIClient.prepare_despacho_draft("rescisao")
        assert draft.tipo == "rescisao"
        assert "Rescisao" in draft.conteudo

    def test_fill_dados(self, mock_template_registry):
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

    def test_header_and_footer(self, mock_template_registry):
        draft = SEIClient.prepare_despacho_draft("tce_inicial")
        assert "UNIVERSIDADE FEDERAL DO PARANA" in draft.conteudo
        assert "Stephania Padovani" in draft.conteudo
        assert "Coordenadora do Curso de Design Grafico" in draft.conteudo

    def test_neo4j_unavailable_returns_sentinel(self):
        """When Neo4j is unreachable, prepare_despacho_draft returns a
        DespachoDraft flagged with campos_pendentes=['neo4j_unavailable']."""
        fake = MagicMock()
        fake.get.return_value = None
        with patch(
            "ufpr_automation.graphrag.templates.get_registry",
            return_value=fake,
        ):
            draft = SEIClient.prepare_despacho_draft("tce_inicial")
        assert draft.tipo == "tce_inicial"
        assert draft.conteudo == ""
        assert draft.campos_pendentes == ["neo4j_unavailable"]


# ---------------------------------------------------------------------------
# Cascade search + disambiguation (2026-04-22)
# ---------------------------------------------------------------------------


class TestExtractYearFromNumero:
    def test_year_2026(self):
        assert extract_year_from_numero("23075.011886/2026-96") == 2026

    def test_year_2024(self):
        assert extract_year_from_numero("23075.047102/2024-04") == 2024

    def test_no_match(self):
        assert extract_year_from_numero("sem formato") is None

    def test_empty(self):
        assert extract_year_from_numero("") is None


class TestSelectBestProcesso:
    """Disambiguação validada contra exemplo real do usuário 2026-04-22:
    ``23075.011886/2026-96`` (ativo) vs ``23075.047102/2024-04`` (antigo).
    """

    def test_newer_year_wins(self):
        novo = ProcessoSEI(numero="23075.011886/2026-96", tipo="Estágio não obrigatório")
        antigo = ProcessoSEI(numero="23075.047102/2024-04", tipo="Estágio não obrigatório")
        best, conf = select_best_processo([antigo, novo], grr_hint="GRR20223876")
        assert best is not None
        assert best.numero == "23075.011886/2026-96"
        assert conf > 0

    def test_empty_list_returns_none(self):
        assert select_best_processo([]) == (None, 0.0)

    def test_single_candidate_returns_it(self):
        p = ProcessoSEI(numero="23075.011886/2026-96")
        best, _ = select_best_processo([p])
        assert best is p

    def test_grr_hint_matches_interessado(self):
        grr = "GRR20223876"
        # Two in same year; disambiguation should tip toward interessado match.
        p_hit = ProcessoSEI(
            numero="23075.000001/2026-01",
            tipo="Estágio não obrigatório",
            interessados=["MARLON - GRR20223876"],
        )
        p_miss = ProcessoSEI(
            numero="23075.000002/2026-02",
            tipo="Estágio não obrigatório",
            interessados=["OUTRO - GRR20200001"],
        )
        best, _ = select_best_processo([p_hit, p_miss], grr_hint=grr)
        assert best is p_hit

    def test_tied_returns_none_for_review(self):
        # Two perfectly identical candidates — tiebreaker can't resolve.
        p1 = ProcessoSEI(numero="23075.000001/2026-01", tipo="Estágio não obrigatório")
        p2 = ProcessoSEI(numero="23075.000002/2026-01", tipo="Estágio não obrigatório")
        best, conf = select_best_processo([p1, p2])
        assert best is None
        assert conf > 0  # score was non-zero, just tied

    def test_status_em_andamento_boosts(self):
        em_andamento = ProcessoSEI(
            numero="23075.111111/2024-01",
            tipo="Estágio não obrigatório",
            status="Em andamento",
        )
        arquivado = ProcessoSEI(
            numero="23075.222222/2024-02",
            tipo="Estágio não obrigatório",
            status="Arquivado",
        )
        best, _ = select_best_processo([arquivado, em_andamento])
        assert best is em_andamento


class TestParseSearchResultsTable:
    """Parser heurístico da tabela de resultados da pesquisa rápida SEI.

    Simula a estrutura baseada no exemplo do usuário:
    ``numero | usuario | data | tipo | interessados``.
    """

    def _row(self, cells: list[str]) -> MagicMock:
        row = MagicMock()
        td = MagicMock()
        td.count = AsyncMock(return_value=len(cells))

        def nth(i):
            cell = MagicMock()
            cell.text_content = AsyncMock(return_value=cells[i])
            return cell

        td.nth = MagicMock(side_effect=nth)
        row.locator = MagicMock(return_value=td)
        return row

    @pytest.mark.asyncio
    async def test_parses_two_rows(self):
        page = MagicMock()
        rows_loc = MagicMock()
        rows_loc.count = AsyncMock(return_value=2)

        r1 = self._row(
            [
                "23075.011886/2026-96",
                "lucas.sorrentino",
                "06/03/2026 13:54:55",
                "Estágio não obrigatório",
                "MARLON HENRIQUE GOMES FERNANDES - GRR20223876",
            ]
        )
        r2 = self._row(
            [
                "23075.047102/2024-04",
                "lucas.sorrentino",
                "26/08/2024 15:20:43",
                "Estágio não obrigatório",
                "Marlon Henrrique Gomes Fernandes",
            ]
        )
        rows_loc.nth = MagicMock(side_effect=lambda i: [r1, r2][i])
        page.locator = MagicMock(return_value=rows_loc)

        client = SEIClient(page)
        procs = await client._parse_search_results_table()
        assert len(procs) == 2
        assert procs[0].numero == "23075.011886/2026-96"
        assert procs[1].numero == "23075.047102/2024-04"
        assert "Estágio" in procs[0].tipo
        assert "06/03/2026" in procs[0].ultima_movimentacao
