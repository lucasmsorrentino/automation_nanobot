"""Tests for the GraphRAG module (Neo4j knowledge graph)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ============================================================================
# Schema tests
# ============================================================================


class TestSchema:
    """Test schema constraints and indexes."""

    def test_constraints_are_defined(self):
        from ufpr_automation.graphrag.schema import CONSTRAINTS

        assert len(CONSTRAINTS) >= 8
        # All should be CREATE CONSTRAINT
        for c in CONSTRAINTS:
            assert "CREATE CONSTRAINT" in c

    def test_fulltext_indexes_defined(self):
        from ufpr_automation.graphrag.schema import FULLTEXT_INDEXES

        assert len(FULLTEXT_INDEXES) >= 1
        assert "FULLTEXT INDEX" in FULLTEXT_INDEXES[0]

    def test_apply_constraints_calls_client(self):
        from ufpr_automation.graphrag.schema import CONSTRAINTS, FULLTEXT_INDEXES, apply_constraints

        mock_client = MagicMock()
        apply_constraints(mock_client)
        expected_calls = len(CONSTRAINTS) + len(FULLTEXT_INDEXES)
        assert mock_client.run_write.call_count == expected_calls


# ============================================================================
# Client tests (mocked driver)
# ============================================================================


class TestNeo4jClient:
    """Test Neo4j client wrapper with mocked driver."""

    def _make_client(self):
        """Create a Neo4jClient with a mocked driver injected."""
        import sys
        # Ensure neo4j module is available (mock it if not installed)
        mock_neo4j = MagicMock()
        sys.modules.setdefault("neo4j", mock_neo4j)

        from ufpr_automation.graphrag.client import Neo4jClient

        mock_driver = MagicMock()
        client = Neo4jClient.__new__(Neo4jClient)
        client._uri = "bolt://test:7687"
        client._username = "u"
        client._password = "p"
        client._database = "testdb"
        client._driver = mock_driver
        return client, mock_driver

    def test_health_check_success(self):
        client, mock_driver = self._make_client()
        mock_driver.verify_connectivity.return_value = None
        assert client.health_check() is True

    def test_health_check_failure(self):
        client, mock_driver = self._make_client()
        mock_driver.verify_connectivity.side_effect = Exception("down")
        assert client.health_check() is False

    def test_run_query(self):
        client, mock_driver = self._make_client()
        mock_record = MagicMock()
        mock_record.data.return_value = {"cnt": 42}
        mock_session = MagicMock()
        mock_session.run.return_value = [mock_record]
        mock_driver.session.return_value = mock_session
        result = client.run_query("MATCH (n) RETURN count(n) AS cnt")
        assert result == [{"cnt": 42}]

    def test_context_manager(self):
        client, mock_driver = self._make_client()
        with client:
            pass
        mock_driver.close.assert_called_once()

    def test_node_count(self):
        client, mock_driver = self._make_client()
        mock_record = MagicMock()
        mock_record.data.return_value = {"cnt": 100}
        mock_session = MagicMock()
        mock_session.run.return_value = [mock_record]
        mock_driver.session.return_value = mock_session
        assert client.node_count() == 100

    def test_relationship_count(self):
        client, mock_driver = self._make_client()
        mock_record = MagicMock()
        mock_record.data.return_value = {"cnt": 50}
        mock_session = MagicMock()
        mock_session.run.return_value = [mock_record]
        mock_driver.session.return_value = mock_session
        assert client.relationship_count() == 50


# ============================================================================
# Retriever tests (mocked client)
# ============================================================================


class TestGraphRetriever:
    """Test graph retriever logic with mocked Neo4j client."""

    def _make_retriever(self):
        from ufpr_automation.graphrag.retriever import GraphRetriever

        mock_client = MagicMock()
        retriever = GraphRetriever(client=mock_client)
        return retriever, mock_client

    def test_match_fluxo_tce_nao_obrigatorio(self):
        retriever, _ = self._make_retriever()
        result = retriever._match_fluxo("TCE Estágio", "novo estágio", "Estágios")
        assert result == "TCE Não Obrigatório"

    def test_match_fluxo_aditivo(self):
        retriever, _ = self._make_retriever()
        result = retriever._match_fluxo("Prorrogação", "aditivo estágio", "Estágios")
        assert result == "Termo Aditivo"

    def test_match_fluxo_rescisao(self):
        retriever, _ = self._make_retriever()
        result = retriever._match_fluxo("Encerramento", "rescisão do estágio", "Estágios")
        assert result == "Rescisão"

    def test_match_fluxo_certificacao(self):
        retriever, _ = self._make_retriever()
        result = retriever._match_fluxo("Certificado", "certificado de estágio", "Estágios")
        assert result == "Certificação"

    def test_match_fluxo_obrigatorio(self):
        retriever, _ = self._make_retriever()
        result = retriever._match_fluxo("Estágio obrigatório", "OD501", "Estágios")
        assert result == "TCE Obrigatório"

    def test_match_fluxo_convalidacao(self):
        retriever, _ = self._make_retriever()
        result = retriever._match_fluxo("Convalidação", "iniciação científica", "Estágios")
        assert result == "Convalidação"

    def test_match_fluxo_keyword_fallback(self):
        retriever, _ = self._make_retriever()
        # No category, just keywords
        result = retriever._match_fluxo("Termo de Compromisso", "novo tce", None)
        assert result == "TCE Não Obrigatório"

    def test_match_fluxo_no_match(self):
        retriever, _ = self._make_retriever()
        result = retriever._match_fluxo("Reunião do colegiado", "pauta da reunião", None)
        assert result is None

    def test_get_workflow_context(self):
        retriever, mock_client = self._make_retriever()
        mock_client.run_query.return_value = [
            {"fluxo": "TCE Não Obrigatório", "desc": "Solicitação inicial",
             "prazo": "10 dias úteis", "bloqueio": None,
             "ordem": 1, "etapa": "Aluno preenche TCE", "papel": "Estagiário", "sistema": None},
            {"fluxo": "TCE Não Obrigatório", "desc": "Solicitação inicial",
             "prazo": "10 dias úteis", "bloqueio": None,
             "ordem": 2, "etapa": "Secretaria abre processo SEI", "papel": "Secretário", "sistema": "SEI"},
        ]
        ctx = retriever._get_workflow_context("TCE Não Obrigatório")
        assert "Fluxo: TCE Não Obrigatório" in ctx
        assert "10 dias úteis" in ctx
        assert "Aluno preenche TCE" in ctx
        assert "via: SEI" in ctx

    def test_get_workflow_context_empty(self):
        retriever, mock_client = self._make_retriever()
        mock_client.run_query.return_value = []
        assert retriever._get_workflow_context("Inexistente") == ""

    def test_get_templates_context(self):
        retriever, mock_client = self._make_retriever()
        mock_client.run_query.return_value = [
            {"nome": "Email: Estágio deferido", "tipo": "email", "desc": "Após aprovação"},
            {"nome": "Despacho SEI: TCE Inicial", "tipo": "despacho_sei", "desc": "Novo estágio"},
        ]
        ctx = retriever._get_templates_context("TCE Não Obrigatório")
        assert "Templates disponíveis" in ctx
        assert "Email: Estágio deferido" in ctx

    def test_get_siga_hints_student_related(self):
        retriever, mock_client = self._make_retriever()
        mock_client.run_query.return_value = [
            {"aba": "informacoes", "assunto": "Status de matrícula",
             "verificar": "Status atual"},
            {"aba": "estagio", "assunto": "Estágio",
             "verificar": "Estágios vinculados ao discente"},
        ]
        ctx = retriever._get_siga_hints("Matrícula do aluno", "aluno GRR20210001")
        assert "SIGA" in ctx

    def test_get_siga_hints_not_student(self):
        retriever, mock_client = self._make_retriever()
        ctx = retriever._get_siga_hints("Reunião do colegiado", "pauta da reunião")
        # Should not query SIGA for non-student emails
        assert ctx == ""

    def test_get_org_context_estagio(self):
        retriever, mock_client = self._make_retriever()
        mock_client.run_query.return_value = [
            {"nome": "COAPPE", "email": "estagio@ufpr.br", "tel": "(41) 3310-2706",
             "desc": "Estágios", "parent_sigla": "PROGRAP"},
        ]
        ctx = retriever._get_org_context("Estágio", "tce do estágio")
        assert "COAPPE" in ctx
        assert "estagio@ufpr.br" in ctx

    def test_get_org_context_no_match(self):
        retriever, _ = self._make_retriever()
        ctx = retriever._get_org_context("Reunião", "pauta da reunião")
        assert ctx == ""

    def test_get_context_for_email_combines_sections(self):
        retriever, mock_client = self._make_retriever()

        call_count = [0]

        def side_effect(query, params=None):
            call_count[0] += 1
            if "TEM_ETAPA" in query:
                return [
                    {"fluxo": "TCE Não Obrigatório", "desc": "Teste",
                     "prazo": "", "bloqueio": None,
                     "ordem": 1, "etapa": "Etapa 1", "papel": "Secretário", "sistema": None},
                ]
            if "USADO_EM" in query:
                return [{"nome": "Email: teste", "tipo": "email", "desc": "Teste"}]
            return []

        mock_client.run_query.side_effect = side_effect
        ctx = retriever.get_context_for_email("TCE estágio", "novo tce", "Estágios")
        assert "GraphRAG" in ctx
        assert "Fluxo" in ctx

    def test_get_context_for_email_empty_when_no_match(self):
        retriever, mock_client = self._make_retriever()
        mock_client.run_query.return_value = []
        ctx = retriever.get_context_for_email("Reunião", "pauta genérica", None)
        assert ctx == ""

    def test_get_sei_process_type(self):
        retriever, mock_client = self._make_retriever()
        mock_client.run_query.return_value = [
            {"nome": "Graduação/Ensino Técnico: Estágios não Obrigatórios", "freq": 238}
        ]
        result = retriever.get_sei_process_type("Estágios")
        assert result["freq"] == 238

    def test_get_workflow_steps(self):
        retriever, mock_client = self._make_retriever()
        mock_client.run_query.return_value = [
            {"ordem": 1, "descricao": "Step 1", "papel": "Secretário", "sistema": "SEI"},
        ]
        steps = retriever.get_workflow_steps("TCE Não Obrigatório")
        assert len(steps) == 1
        assert steps[0]["papel"] == "Secretário"

    def test_search_nodes(self):
        retriever, mock_client = self._make_retriever()
        mock_client.run_query.return_value = [
            {"tipo": "Norma", "nome": "Lei do Estágio", "id": "Lei 11.788/2008",
             "descricao": "Lei federal", "score": 2.5},
        ]
        results = retriever.search_nodes("estágio")
        assert len(results) == 1
        assert results[0]["tipo"] == "Norma"

    def test_search_nodes_fallback_on_error(self):
        retriever, mock_client = self._make_retriever()
        mock_client.run_query.side_effect = Exception("no fulltext index")
        results = retriever.search_nodes("estágio")
        assert results == []


# ============================================================================
# Seed tests (mocked client)
# ============================================================================


class TestSeed:
    """Test seed functions with mocked Neo4j client."""

    def _mock_client(self):
        client = MagicMock()
        client.run_query.return_value = [{"cnt": 10}]
        client.node_count.return_value = 100
        client.relationship_count.return_value = 200
        return client

    def test_seed_orgaos(self):
        from ufpr_automation.graphrag.seed import _seed_orgaos

        client = self._mock_client()
        count = _seed_orgaos(client)
        assert count == 10
        assert client.run_write.called

    def test_seed_pessoas(self):
        from ufpr_automation.graphrag.seed import _seed_pessoas

        client = self._mock_client()
        count = _seed_pessoas(client)
        assert count == 10

    def test_seed_sistemas(self):
        from ufpr_automation.graphrag.seed import _seed_sistemas

        client = self._mock_client()
        count = _seed_sistemas(client)
        assert count == 10

    def test_seed_papeis(self):
        from ufpr_automation.graphrag.seed import _seed_papeis

        client = self._mock_client()
        count = _seed_papeis(client)
        assert count == 10

    def test_seed_normas(self):
        from ufpr_automation.graphrag.seed import _seed_normas

        client = self._mock_client()
        count = _seed_normas(client)
        assert count == 10

    def test_seed_documentos(self):
        from ufpr_automation.graphrag.seed import _seed_documentos

        client = self._mock_client()
        count = _seed_documentos(client)
        assert count == 10

    def test_seed_tipos_processo(self):
        from ufpr_automation.graphrag.seed import _seed_tipos_processo

        client = self._mock_client()
        count = _seed_tipos_processo(client)
        assert count == 10
        # Should have called run_write for each process type + link queries
        assert client.run_write.call_count >= 20  # 20 types + link queries

    def test_seed_fluxos(self):
        from ufpr_automation.graphrag.seed import _seed_fluxos

        client = self._mock_client()
        count = _seed_fluxos(client)
        assert count == 10  # mocked count
        # Should have many run_write calls (fluxo + etapas + systems)
        assert client.run_write.call_count >= 30

    def test_seed_templates(self):
        from ufpr_automation.graphrag.seed import _seed_templates

        client = self._mock_client()
        count = _seed_templates(client)
        assert count == 10

    def test_seed_all(self):
        from ufpr_automation.graphrag.seed import seed_all

        client = self._mock_client()
        stats = seed_all(client, clear=False)
        assert "_total_nodes" in stats
        assert "_total_relationships" in stats
        assert stats["_total_nodes"] == 100
        assert stats["_total_relationships"] == 200
        # Should NOT call clear_graph when clear=False
        client.clear_graph.assert_not_called()

    def test_seed_all_with_clear(self):
        from ufpr_automation.graphrag.seed import seed_all

        client = self._mock_client()
        seed_all(client, clear=True)
        client.clear_graph.assert_called_once()


# ============================================================================
# Integration with graph/nodes.py (mocked)
# ============================================================================


class TestGraphNodeIntegration:
    """Test that rag_retrieve integrates GraphRAG when available."""

    @patch("ufpr_automation.graphrag.retriever.GraphRetriever")
    @patch("ufpr_automation.graph.nodes._get_retriever")
    def test_rag_retrieve_includes_graph_context(self, mock_get_retriever, mock_graph_cls):
        from ufpr_automation.core.models import EmailData
        from ufpr_automation.graph.nodes import rag_retrieve

        # Mock vector retriever
        mock_retriever = MagicMock()
        mock_retriever.search_formatted.return_value = "Vector RAG context"
        mock_get_retriever.return_value = mock_retriever

        # Mock graph retriever
        mock_graph = MagicMock()
        mock_graph.get_context_for_email.return_value = "Graph context: workflow steps"
        mock_graph_cls.return_value = mock_graph

        email = EmailData(
            stable_id="test-123",
            sender="aluno@ufpr.br",
            subject="TCE Estágio",
            preview="Gostaria de iniciar estágio",
        )
        state = {"emails": [email]}
        result = rag_retrieve(state)

        assert "test-123" in result["rag_contexts"]
        ctx = result["rag_contexts"]["test-123"]
        assert "Vector RAG context" in ctx
        assert "Graph context" in ctx

    def test_rag_retrieve_works_without_graphrag(self):
        """GraphRAG should gracefully degrade when Neo4j is not available."""
        from ufpr_automation.core.models import EmailData
        from ufpr_automation.graph.nodes import _get_graph_context

        email = MagicMock()
        email.subject = "Teste"
        email.body = "Corpo do email"
        email.preview = "Preview"

        # This should not raise even if neo4j is not installed
        with patch(
            "ufpr_automation.graphrag.retriever.GraphRetriever",
            side_effect=ImportError("neo4j not installed"),
        ):
            result = _get_graph_context(email)
            assert result == ""
