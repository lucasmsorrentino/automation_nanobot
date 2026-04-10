"""Tests for TemplateRegistry."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest  # noqa: F401  (imported for consistency with sibling test modules)

from ufpr_automation.graphrag.templates import TemplateRegistry, get_registry


class TestTemplateRegistry:
    def test_get_returns_template_from_neo4j(self):
        mock_client = MagicMock()
        mock_client.run_query.return_value = [{"conteudo": "MOCK TEMPLATE BODY"}]
        reg = TemplateRegistry(client=mock_client)
        assert reg.get("tce_inicial") == "MOCK TEMPLATE BODY"
        assert mock_client.run_query.call_count == 1

    def test_get_caches_results(self):
        mock_client = MagicMock()
        mock_client.run_query.return_value = [{"conteudo": "BODY"}]
        reg = TemplateRegistry(client=mock_client)
        reg.get("tce_inicial")
        reg.get("tce_inicial")
        assert mock_client.run_query.call_count == 1

    def test_get_returns_none_when_empty(self):
        mock_client = MagicMock()
        mock_client.run_query.return_value = []
        reg = TemplateRegistry(client=mock_client)
        assert reg.get("nonexistent") is None

    def test_get_returns_none_on_exception(self):
        mock_client = MagicMock()
        mock_client.run_query.side_effect = Exception("connection refused")
        reg = TemplateRegistry(client=mock_client)
        assert reg.get("tce_inicial") is None

    def test_get_all_returns_dict(self):
        mock_client = MagicMock()
        mock_client.run_query.return_value = [
            {"tipo": "tce_inicial", "conteudo": "A"},
            {"tipo": "aditivo", "conteudo": "B"},
        ]
        reg = TemplateRegistry(client=mock_client)
        result = reg.get_all()
        assert result == {"tce_inicial": "A", "aditivo": "B"}

    def test_invalidate_clears_cache(self):
        mock_client = MagicMock()
        mock_client.run_query.return_value = [{"conteudo": "BODY"}]
        reg = TemplateRegistry(client=mock_client)
        reg.get("tce_inicial")
        reg.invalidate()
        reg.get("tce_inicial")
        assert mock_client.run_query.call_count == 2

    def test_get_registry_returns_singleton(self):
        reg1 = get_registry()
        reg2 = get_registry()
        assert reg1 is reg2
