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
from dataclasses import dataclass

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
    orgao_emissor: str = "DESCONHECIDO"
    is_coordenacao: bool = False


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
                f"Table '{TABLE_NAME}' not found. Run `python -m ufpr_automation.rag.ingest` first."
            )
        self._table = self._db.open_table(TABLE_NAME)

        # Use the process-wide shared embedder (see rag/_embedder.py) so the
        # LangGraph Fleet sub-agents don't each load their own ~2 GB copy of
        # the model weights into RAM.
        from ufpr_automation.rag._embedder import get_shared_embedder

        self._model = get_shared_embedder(self._model_name)

    def _embed_query(self, query: str) -> list[float]:
        """Embed a query string. Prepends 'query: ' for E5 models."""
        vec = self._model.encode(f"query: {query}", normalize_embeddings=True)
        return vec.tolist()

    def search(
        self,
        query: str,
        *,
        conselho: str | None = None,
        tipo: str | None = None,
        orgao: str | None = None,
        only_coordenacao: bool = False,
        top_k: int = 10,
    ) -> list[SearchResult]:
        """Semantic search with optional metadata filters.

        Args:
            query: Natural language query in Portuguese.
            conselho: Filter by council (cepe, coun, coplad, concur, estagio).
            tipo: Filter by doc type (atas, resolucoes, instrucoes-normativas, estagio).
            orgao: Filter by orgao_emissor sigla (CEPE, COUN, COPLAD, CONCUR,
                CCDG, MEC, PROGRAP, COAPPE, UFPR, UFPR_ABERTA).
            only_coordenacao: If True, restrict to docs where is_coordenacao=true
                (i.e. orgao_emissor='CCDG'). Convenience flag.
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
        if orgao:
            filters.append(f"orgao_emissor = '{orgao}'")
        if only_coordenacao:
            filters.append("is_coordenacao = true")
        if filters:
            search = search.where(" AND ".join(filters))

        tbl = search.to_arrow()
        # Some pre-existing chunks (indexed before Frente 3 / 2026-04-27) may
        # not have orgao_emissor / is_coordenacao columns. Probe once.
        has_orgao_col = "orgao_emissor" in tbl.column_names
        has_is_coord_col = "is_coordenacao" in tbl.column_names

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
                    orgao_emissor=(
                        tbl.column("orgao_emissor")[i].as_py()
                        if has_orgao_col
                        else "DESCONHECIDO"
                    ),
                    is_coordenacao=(
                        bool(tbl.column("is_coordenacao")[i].as_py())
                        if has_is_coord_col
                        else False
                    ),
                )
            )
        return results

    def search_formatted(
        self,
        query: str,
        *,
        conselho: str | None = None,
        tipo: str | None = None,
        orgao: str | None = None,
        only_coordenacao: bool = False,
        top_k: int = 5,
    ) -> str:
        """Search and return results as a formatted string for LLM context injection."""
        results = self.search(
            query,
            conselho=conselho,
            tipo=tipo,
            orgao=orgao,
            only_coordenacao=only_coordenacao,
            top_k=top_k,
        )
        if not results:
            return "Nenhum documento relevante encontrado."

        parts = []
        for i, r in enumerate(results, 1):
            parts.append(f"[{i}] {r.caminho} (score: {r.score:.4f})\n{r.text}")
        return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Search UFPR docs vector store")
    parser.add_argument("query", type=str, help="Search query in Portuguese")
    parser.add_argument("--conselho", type=str, default=None)
    parser.add_argument("--tipo", type=str, default=None)
    parser.add_argument(
        "--orgao",
        type=str,
        default=None,
        help="Sigla do órgão emissor (CEPE, COUN, COPLAD, CONCUR, CCDG, MEC, "
        "PROGRAP, COAPPE, UFPR, UFPR_ABERTA)",
    )
    parser.add_argument(
        "--only-coordenacao",
        action="store_true",
        help="Restringir a documentos próprios da Coordenação (orgao_emissor=CCDG).",
    )
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    r = Retriever()
    print(
        r.search_formatted(
            args.query,
            conselho=args.conselho,
            tipo=args.tipo,
            orgao=args.orgao,
            only_coordenacao=args.only_coordenacao,
            top_k=args.top_k,
        )
    )


if __name__ == "__main__":
    main()
