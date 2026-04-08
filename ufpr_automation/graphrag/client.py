"""Neo4j connection manager for the UFPR GraphRAG knowledge graph."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from ufpr_automation.utils.logging import logger


class Neo4jClient:
    """Thin wrapper around the Neo4j Python driver.

    Usage::

        client = Neo4jClient()
        with client.session() as session:
            result = session.run("MATCH (n) RETURN count(n) AS cnt")
            print(result.single()["cnt"])
        client.close()
    """

    def __init__(
        self,
        uri: str | None = None,
        username: str | None = None,
        password: str | None = None,
        database: str | None = None,
    ) -> None:
        from neo4j import GraphDatabase

        from ufpr_automation.config import settings

        self._uri = uri or settings.NEO4J_URI
        self._username = username or settings.NEO4J_USERNAME
        self._password = password or settings.NEO4J_PASSWORD
        self._database = database or settings.NEO4J_DATABASE

        self._driver = GraphDatabase.driver(
            self._uri,
            auth=(self._username, self._password),
        )
        logger.debug("Neo4j: conectado a %s (db=%s)", self._uri, self._database)

    # ------------------------------------------------------------------
    # Session helpers
    # ------------------------------------------------------------------

    @contextmanager
    def session(self):
        """Yield a Neo4j session, auto-closing on exit."""
        session = self._driver.session(database=self._database)
        try:
            yield session
        finally:
            session.close()

    def run_query(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict]:
        """Execute a Cypher query and return results as a list of dicts."""
        with self.session() as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]

    def run_write(self, query: str, parameters: dict[str, Any] | None = None) -> None:
        """Execute a write Cypher query inside an explicit transaction."""
        with self.session() as session:
            session.execute_write(lambda tx: tx.run(query, parameters or {}))

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """Return True if Neo4j is reachable and authenticated."""
        try:
            self._driver.verify_connectivity()
            return True
        except Exception as e:
            logger.warning("Neo4j health check falhou: %s", e)
            return False

    def node_count(self) -> int:
        """Return total number of nodes in the graph."""
        rows = self.run_query("MATCH (n) RETURN count(n) AS cnt")
        return rows[0]["cnt"] if rows else 0

    def relationship_count(self) -> int:
        """Return total number of relationships in the graph."""
        rows = self.run_query("MATCH ()-[r]->() RETURN count(r) AS cnt")
        return rows[0]["cnt"] if rows else 0

    def clear_graph(self) -> None:
        """Delete all nodes and relationships. Use with caution."""
        self.run_write("MATCH (n) DETACH DELETE n")
        logger.warning("Neo4j: grafo limpo (todos os nós e relações removidos)")

    def close(self) -> None:
        """Close the driver connection."""
        self._driver.close()
        logger.debug("Neo4j: conexão fechada")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
