"""Template registry — fetches despacho templates from the Neo4j knowledge graph."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ufpr_automation.sei.models import DespachoTipo

logger = logging.getLogger(__name__)


class TemplateRegistry:
    """Fetches and caches despacho templates from the GraphRAG knowledge graph."""

    def __init__(self, client=None):
        self._client = client
        self._cache: dict[str, str] = {}

    def _get_client(self):
        if self._client is None:
            from ufpr_automation.graphrag.client import Neo4jClient

            self._client = Neo4jClient()
        return self._client

    def get(self, tipo: "DespachoTipo") -> str | None:
        """Fetch the full template body for the given tipo. Returns None on failure."""
        if tipo in self._cache:
            return self._cache[tipo]
        try:
            client = self._get_client()
            rows = client.run_query(
                "MATCH (t:Template {despacho_tipo: $tipo}) RETURN t.conteudo AS conteudo LIMIT 1",
                {"tipo": tipo},
            )
            if not rows:
                logger.warning("No template found in graph for despacho_tipo=%s", tipo)
                return None
            conteudo = rows[0].get("conteudo")
            if conteudo:
                self._cache[tipo] = conteudo
            return conteudo
        except Exception as e:
            logger.error("Failed to fetch template from Neo4j: %s", e)
            return None

    def get_all(self) -> dict[str, str]:
        """Fetch all despacho templates from the graph."""
        try:
            client = self._get_client()
            rows = client.run_query(
                "MATCH (t:Template) WHERE t.despacho_tipo IS NOT NULL "
                "RETURN t.despacho_tipo AS tipo, t.conteudo AS conteudo"
            )
            result = {row["tipo"]: row["conteudo"] for row in rows if row.get("conteudo")}
            self._cache.update(result)
            return result
        except Exception as e:
            logger.error("Failed to fetch templates from Neo4j: %s", e)
            return {}

    def invalidate(self) -> None:
        """Clear the in-memory cache (for tests)."""
        self._cache.clear()


_registry: TemplateRegistry | None = None


def get_registry() -> TemplateRegistry:
    """Module-level singleton accessor."""
    global _registry
    if _registry is None:
        _registry = TemplateRegistry()
    return _registry
