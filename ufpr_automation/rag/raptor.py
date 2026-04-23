"""RAPTOR — Recursive Abstractive Processing for Tree-Organized Retrieval.

Builds a hierarchical index over the existing LanceDB chunks:
  1. Embed leaf chunks (already done by ingest.py)
  2. Cluster embeddings using Gaussian Mixture Models (soft assignment)
  3. Summarize each cluster using the LLM
  4. Embed summaries -> new "level 1" nodes
  5. Recurse: cluster level-1 nodes -> summarize -> embed -> level 2 ...
  6. Stop when a single cluster remains or max_levels reached

Retrieval uses "collapsed tree" search: query searches ALL levels
simultaneously and returns the most relevant nodes regardless of level.

Usage:
    python -m ufpr_automation.rag.raptor              # build RAPTOR tree
    python -m ufpr_automation.rag.raptor --max-levels 3
    python -m ufpr_automation.rag.raptor --dry-run     # show cluster stats only

Reference:
    Sarthi et al., "RAPTOR: Recursive Abstractive Processing for
    Tree-Organized Retrieval", ICLR 2024.
"""

from __future__ import annotations

import argparse
import time

import numpy as np

from ufpr_automation.config import settings
from ufpr_automation.utils.logging import logger

STORE_DIR = settings.RAG_STORE_DIR
TABLE_NAME = "ufpr_docs"
RAPTOR_TABLE = "ufpr_raptor"


# ---------------------------------------------------------------------------
# Clustering (GMM with soft assignment)
# ---------------------------------------------------------------------------


def cluster_embeddings(
    embeddings: np.ndarray,
    max_clusters: int = 10,
    random_state: int = 42,
) -> list[list[int]]:
    """Cluster embeddings using Gaussian Mixture Models.

    Returns a list of clusters, where each cluster is a list of indices.
    Uses BIC to select the optimal number of components.
    """
    from sklearn.mixture import GaussianMixture

    n_samples = len(embeddings)
    if n_samples <= 1:
        return [list(range(n_samples))]

    # Reduce dimensionality if needed for GMM stability
    if embeddings.shape[1] > 50:
        from sklearn.decomposition import PCA

        n_components = min(50, n_samples - 1)
        pca = PCA(n_components=n_components, random_state=random_state)
        reduced = pca.fit_transform(embeddings)
    else:
        reduced = embeddings

    # Select optimal number of clusters via BIC
    max_k = min(max_clusters, n_samples // 2, n_samples - 1)
    max_k = max(max_k, 2)

    best_bic = float("inf")
    best_k = 2

    for k in range(2, max_k + 1):
        try:
            gmm = GaussianMixture(
                n_components=k,
                covariance_type="full",
                random_state=random_state,
                max_iter=100,
            )
            gmm.fit(reduced)
            bic = gmm.bic(reduced)
            if bic < best_bic:
                best_bic = bic
                best_k = k
        except Exception:
            continue

    # Fit final GMM with best k
    gmm = GaussianMixture(
        n_components=best_k,
        covariance_type="full",
        random_state=random_state,
    )
    gmm.fit(reduced)

    # Soft assignment: assign each point to clusters where probability > threshold
    probs = gmm.predict_proba(reduced)
    threshold = 0.1

    clusters: list[list[int]] = [[] for _ in range(best_k)]
    for i, row in enumerate(probs):
        assigned = False
        for j, p in enumerate(row):
            if p > threshold:
                clusters[j].append(i)
                assigned = True
        if not assigned:
            # Fallback: assign to highest probability cluster
            clusters[int(np.argmax(row))].append(i)

    # Filter out empty clusters
    return [c for c in clusters if c]


# ---------------------------------------------------------------------------
# Summarization
# ---------------------------------------------------------------------------


def summarize_cluster(texts: list[str], model_id: str | None = None) -> str:
    """Summarize a cluster of text chunks using the LLM.

    Args:
        texts: List of text chunks in the cluster.
        model_id: LLM model to use (defaults to settings.LLM_MODEL).

    Returns:
        A concise summary of the cluster's content.
    """
    import litellm

    model = model_id or settings.LLM_MODEL
    combined = "\n\n---\n\n".join(texts[:20])  # limit to avoid context overflow

    prompt = (
        "Voce e um especialista em legislacao universitaria brasileira. "
        "Resuma o conteudo abaixo de forma concisa, mantendo os pontos principais, "
        "numeros de resolucoes, artigos e datas mencionados.\n\n"
        f"Conteudo:\n{combined}\n\n"
        "Resumo conciso:"
    )

    try:
        response = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.warning("Falha ao sumarizar cluster: %s", e)
        # Fallback: concatenate first sentences
        fallback = " ".join(t.split(". ")[0] + "." for t in texts[:5])
        return fallback


# ---------------------------------------------------------------------------
# RAPTOR tree builder
# ---------------------------------------------------------------------------


def build_raptor_tree(
    max_levels: int = 3,
    max_clusters: int = 10,
    dry_run: bool = False,
) -> dict:
    """Build the RAPTOR hierarchical index over existing LanceDB chunks.

    Args:
        max_levels: Maximum recursion depth for the tree.
        max_clusters: Maximum clusters per level.
        dry_run: If True, compute clusters but don't summarize or index.

    Returns:
        Stats dict with counts per level.
    """
    import lancedb

    from ufpr_automation.rag.ingest import embed_texts

    db = lancedb.connect(str(STORE_DIR / "ufpr.lance"))

    # Load leaf chunks from base table
    if TABLE_NAME not in db.list_tables().tables:
        logger.error("Base table '%s' not found. Run ingest first.", TABLE_NAME)
        return {"error": "base table not found"}

    base_table = db.open_table(TABLE_NAME)
    arrow_tbl = base_table.to_arrow()

    texts = [v.as_py() for v in arrow_tbl.column("text")]
    vectors = np.array([v.as_py() for v in arrow_tbl.column("vector")])

    stats = {"levels": [], "total_nodes": len(texts)}
    logger.info("RAPTOR: %d leaf chunks loaded", len(texts))

    # Build records for all RAPTOR levels
    all_records = []
    current_texts = texts
    current_vectors = vectors
    current_metadata = [
        {
            "conselho": arrow_tbl.column("conselho")[i].as_py(),
            "tipo": arrow_tbl.column("tipo")[i].as_py(),
            "arquivo": arrow_tbl.column("arquivo")[i].as_py(),
            "caminho": arrow_tbl.column("caminho")[i].as_py(),
        }
        for i in range(arrow_tbl.num_rows)
    ]

    for level in range(1, max_levels + 1):
        if len(current_texts) <= 2:
            logger.info("RAPTOR: stopping at level %d (too few nodes)", level)
            break

        logger.info("RAPTOR: building level %d from %d nodes...", level, len(current_texts))

        # Cluster
        clusters = cluster_embeddings(current_vectors, max_clusters=max_clusters)
        logger.info("  %d clusters formed", len(clusters))

        level_stats = {"level": level, "input_nodes": len(current_texts), "clusters": len(clusters)}

        if dry_run:
            stats["levels"].append(level_stats)
            break

        # Summarize each cluster
        summaries = []
        summary_metadata = []
        for ci, cluster_indices in enumerate(clusters):
            cluster_texts = [current_texts[i] for i in cluster_indices]
            summary = summarize_cluster(cluster_texts)
            summaries.append(summary)

            # Metadata: most common conselho/tipo in cluster
            cluster_meta = [current_metadata[i] for i in cluster_indices]
            most_common_conselho = max(
                set(m["conselho"] for m in cluster_meta),
                key=lambda x: sum(1 for m in cluster_meta if m["conselho"] == x),
            )
            summary_metadata.append(
                {
                    "conselho": most_common_conselho,
                    "tipo": "raptor_summary",
                    "arquivo": f"raptor_L{level}_C{ci}",
                    "caminho": f"raptor/level_{level}/cluster_{ci}",
                }
            )
            logger.info(
                "  Cluster %d: %d chunks -> summary (%d chars)",
                ci,
                len(cluster_indices),
                len(summary),
            )

        # Embed summaries
        summary_vectors = embed_texts(summaries)

        # Build records
        for text, vec, meta in zip(summaries, summary_vectors, summary_metadata):
            all_records.append(
                {
                    "text": text,
                    "vector": vec,
                    "conselho": meta["conselho"],
                    "tipo": meta["tipo"],
                    "arquivo": meta["arquivo"],
                    "caminho": meta["caminho"],
                    "chunk_idx": 0,
                    "raptor_level": level,
                }
            )

        level_stats["summaries"] = len(summaries)
        stats["levels"].append(level_stats)
        stats["total_nodes"] += len(summaries)

        # Prepare for next level
        current_texts = summaries
        current_vectors = np.array(summary_vectors)
        current_metadata = summary_metadata

    # Store RAPTOR nodes in a separate table
    if all_records and not dry_run:
        logger.info(
            "RAPTOR: inserting %d summary nodes into '%s'...", len(all_records), RAPTOR_TABLE
        )

        # Add raptor_level to base table records (level 0) for collapsed tree search
        if RAPTOR_TABLE in db.list_tables().tables:
            db.drop_table(RAPTOR_TABLE)

        db.create_table(RAPTOR_TABLE, data=all_records)
        logger.info("RAPTOR: done.")

    return stats


# ---------------------------------------------------------------------------
# Collapsed tree retrieval
# ---------------------------------------------------------------------------


class RaptorRetriever:
    """Search across all RAPTOR levels simultaneously (collapsed tree).

    Queries both the base table (leaf chunks) and the RAPTOR table
    (summaries at all levels), merging results by relevance score.
    """

    def __init__(self, model_name: str = "intfloat/multilingual-e5-large"):
        self._model_name = model_name
        self._model = None
        self._db = None

    def _ensure_loaded(self):
        if self._db is not None:
            return

        import lancedb

        # Use the process-wide shared embedder (see rag/_embedder.py) so the
        # LangGraph Fleet sub-agents don't each load their own ~2 GB copy of
        # the model weights into RAM.
        from ufpr_automation.rag._embedder import get_shared_embedder

        db_path = STORE_DIR / "ufpr.lance"
        if not db_path.exists():
            raise FileNotFoundError(f"Vector store not found at {db_path}")

        self._db = lancedb.connect(str(db_path))
        self._model = get_shared_embedder(self._model_name)

    def _embed_query(self, query: str) -> list[float]:
        vec = self._model.encode(f"query: {query}", normalize_embeddings=True)
        return vec.tolist()

    def search(
        self,
        query: str,
        *,
        conselho: str | None = None,
        top_k: int = 10,
    ) -> list[dict]:
        """Search across all levels of the RAPTOR tree.

        Returns results from both leaf chunks and summary nodes,
        sorted by relevance score.
        """
        self._ensure_loaded()
        query_vec = self._embed_query(query)

        results = []

        # Search base table (leaf chunks)
        if TABLE_NAME in self._db.list_tables().tables:
            base_table = self._db.open_table(TABLE_NAME)
            search = base_table.search(query_vec).limit(top_k)
            if conselho:
                search = search.where(f"conselho = '{conselho}'")
            tbl = search.to_arrow()
            for i in range(tbl.num_rows):
                results.append(
                    {
                        "text": tbl.column("text")[i].as_py(),
                        "score": float(tbl.column("_distance")[i].as_py()),
                        "level": 0,
                        "conselho": tbl.column("conselho")[i].as_py(),
                        "caminho": tbl.column("caminho")[i].as_py(),
                    }
                )

        # Search RAPTOR table (summary nodes)
        if RAPTOR_TABLE in self._db.list_tables().tables:
            raptor_table = self._db.open_table(RAPTOR_TABLE)
            search = raptor_table.search(query_vec).limit(top_k)
            if conselho:
                search = search.where(f"conselho = '{conselho}'")
            tbl = search.to_arrow()
            for i in range(tbl.num_rows):
                results.append(
                    {
                        "text": tbl.column("text")[i].as_py(),
                        "score": float(tbl.column("_distance")[i].as_py()),
                        "level": int(tbl.column("raptor_level")[i].as_py()),
                        "conselho": tbl.column("conselho")[i].as_py(),
                        "caminho": tbl.column("caminho")[i].as_py(),
                    }
                )

        # Sort by score (lower distance = more relevant)
        results.sort(key=lambda r: r["score"])
        return results[:top_k]

    def search_formatted(
        self,
        query: str,
        *,
        conselho: str | None = None,
        top_k: int = 5,
    ) -> str:
        """Search and return formatted string for LLM context injection."""
        results = self.search(query, conselho=conselho, top_k=top_k)
        if not results:
            return "Nenhum documento relevante encontrado."

        parts = []
        for i, r in enumerate(results, 1):
            level_tag = f"L{r['level']}" if r["level"] > 0 else "leaf"
            parts.append(
                f"[{i}] [{level_tag}] {r['caminho']} (score: {r['score']:.4f})\n{r['text']}"
            )
        return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Build RAPTOR hierarchical index")
    parser.add_argument("--max-levels", type=int, default=3)
    parser.add_argument("--max-clusters", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    t0 = time.time()
    stats = build_raptor_tree(
        max_levels=args.max_levels,
        max_clusters=args.max_clusters,
        dry_run=args.dry_run,
    )
    elapsed = time.time() - t0

    print(f"\nRAPTOR stats: {stats}")
    print(f"Elapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
