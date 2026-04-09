"""Retriever for UFPR institutional documents from LanceDB vector store.

Usage:
    from ufpr_automation.rag.retriever import Retriever

    r = Retriever()
    results = r.search("prazo máximo para estágio obrigatório")
    results = r.search("resolução sobre estágio", conselho="cepe", tipo="resolucoes")

CLI:
    python -m ufpr_automation.rag.retriever "prazo de estágio obrigatório"
    python -m ufpr_automation.rag.retriever "aprovação de currículo" --conselho cepe --top-k 5
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Force UTF-8 stdout on Windows so documents containing characters outside
# cp1252 (e.g. ligatures like "fi" = \ufb01) don't crash the CLI mid-print.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass  # older Python without reconfigure()

from ufpr_automation.config import settings

STORE_DIR = settings.RAG_STORE_DIR
TABLE_NAME = "ufpr_docs"


@dataclass
class SearchResult:
    """A single search result from the vector store."""

    text: str
    score: float
    conselho: str
    tipo: str
    arquivo: str
    caminho: str
    chunk_idx: int


class Retriever:
    """Semantic search over UFPR institutional documents."""

    def __init__(self, model_name: str = "intfloat/multilingual-e5-large"):
        self._model_name = model_name
        self._model = None
        self._db = None
        self._table = None

    def _ensure_loaded(self):
        """Lazy-load model and open LanceDB table."""
        if self._table is not None:
            return

        import lancedb

        db_path = STORE_DIR / "ufpr.lance"
        if not db_path.exists():
            raise FileNotFoundError(
                f"Vector store not found at {db_path}. "
                "Run `python -m ufpr_automation.rag.ingest` first."
            )

        self._db = lancedb.connect(str(db_path))
        if TABLE_NAME not in self._db.list_tables().tables:
            raise ValueError(
                f"Table '{TABLE_NAME}' not found. "
                "Run `python -m ufpr_automation.rag.ingest` first."
            )
        self._table = self._db.open_table(TABLE_NAME)

        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(self._model_name)

    def _embed_query(self, query: str) -> list[float]:
        """Embed a query string. Prepends 'query: ' for E5 models."""
        vec = self._model.encode(
            f"query: {query}", normalize_embeddings=True
        )
        return vec.tolist()

    def search(
        self,
        query: str,
        *,
        conselho: str | None = None,
        tipo: str | None = None,
        top_k: int = 10,
    ) -> list[SearchResult]:
        """Semantic search with optional metadata filters.

        Args:
            query: Natural language query in Portuguese.
            conselho: Filter by council (cepe, coun, coplad, concur, estagio).
            tipo: Filter by doc type (atas, resolucoes, instrucoes-normativas, estagio).
            top_k: Number of results to return.

        Returns:
            List of SearchResult ordered by relevance (highest score first).
        """
        self._ensure_loaded()
        query_vec = self._embed_query(query)

        search = self._table.search(query_vec).limit(top_k)

        # Apply metadata filters
        filters = []
        if conselho:
            filters.append(f"conselho = '{conselho}'")
        if tipo:
            filters.append(f"tipo = '{tipo}'")
        if filters:
            search = search.where(" AND ".join(filters))

        tbl = search.to_arrow()

        results = []
        for i in range(tbl.num_rows):
            results.append(
                SearchResult(
                    text=tbl.column("text")[i].as_py(),
                    score=float(tbl.column("_distance")[i].as_py()),
                    conselho=tbl.column("conselho")[i].as_py(),
                    tipo=tbl.column("tipo")[i].as_py(),
                    arquivo=tbl.column("arquivo")[i].as_py(),
                    caminho=tbl.column("caminho")[i].as_py(),
                    chunk_idx=int(tbl.column("chunk_idx")[i].as_py()),
                )
            )
        return results

    def search_formatted(
        self,
        query: str,
        *,
        conselho: str | None = None,
        tipo: str | None = None,
        top_k: int = 5,
    ) -> str:
        """Search and return results as a formatted string for LLM context injection."""
        results = self.search(query, conselho=conselho, tipo=tipo, top_k=top_k)
        if not results:
            return "Nenhum documento relevante encontrado."

        parts = []
        for i, r in enumerate(results, 1):
            parts.append(
                f"[{i}] {r.caminho} (score: {r.score:.4f})\n{r.text}"
            )
        return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Search UFPR docs vector store")
    parser.add_argument("query", type=str, help="Search query in Portuguese")
    parser.add_argument("--conselho", type=str, default=None)
    parser.add_argument("--tipo", type=str, default=None)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    r = Retriever()
    print(r.search_formatted(
        args.query, conselho=args.conselho, tipo=args.tipo, top_k=args.top_k
    ))


if __name__ == "__main__":
    main()
