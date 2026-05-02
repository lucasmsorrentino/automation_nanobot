"""Tests for ufpr_automation.rag.raptor — critical pure-logic paths.

Covers:
- cluster_embeddings (GMM + PCA + soft assignment + empty-cluster filter)
- summarize_cluster (LLM path mocked; fallback path exercised on exception)
- RaptorRetriever.search_formatted (empty/populated rendering, score ordering)

The heavy I/O path (build_raptor_tree → lancedb) is left to integration
tests; here we focus on inputs/outputs of the deterministic helpers.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest


@pytest.fixture
def three_cluster_embeddings():
    """Three well-separated Gaussian clusters in 8-D (64 points total)."""
    rng = np.random.default_rng(0)
    c1 = rng.normal(loc=[5, 0, 0, 0, 0, 0, 0, 0], scale=0.1, size=(20, 8))
    c2 = rng.normal(loc=[0, 5, 0, 0, 0, 0, 0, 0], scale=0.1, size=(20, 8))
    c3 = rng.normal(loc=[0, 0, 5, 0, 0, 0, 0, 0], scale=0.1, size=(24, 8))
    return np.vstack([c1, c2, c3]).astype(np.float32)


class TestClusterEmbeddings:
    def test_returns_at_least_one_cluster_for_nonempty_input(self, three_cluster_embeddings):
        from ufpr_automation.rag.advanced.raptor import cluster_embeddings

        clusters = cluster_embeddings(three_cluster_embeddings, max_clusters=5)
        assert len(clusters) >= 1
        # every cluster is non-empty (the function filters empties)
        assert all(len(c) > 0 for c in clusters)

    def test_all_indices_are_accounted_for(self, three_cluster_embeddings):
        """Every input row lands in at least one cluster (soft assignment +
        the 'highest-probability fallback' guarantees nothing is dropped)."""
        from ufpr_automation.rag.advanced.raptor import cluster_embeddings

        n = len(three_cluster_embeddings)
        clusters = cluster_embeddings(three_cluster_embeddings, max_clusters=5)
        covered: set[int] = set()
        for c in clusters:
            covered.update(c)
        assert covered == set(range(n))

    def test_single_sample_returns_single_cluster(self):
        from ufpr_automation.rag.advanced.raptor import cluster_embeddings

        emb = np.array([[1.0, 2.0, 3.0]], dtype=np.float32)
        clusters = cluster_embeddings(emb)
        assert clusters == [[0]]

    def test_empty_input_returns_empty_cluster(self):
        from ufpr_automation.rag.advanced.raptor import cluster_embeddings

        emb = np.zeros((0, 4), dtype=np.float32)
        clusters = cluster_embeddings(emb)
        assert clusters == [[]]

    def test_high_dim_triggers_pca(self):
        """With >50 features, cluster_embeddings reduces via PCA before GMM.

        Uses well-separated clusters in high-dim to avoid GMM numerical
        issues on purely random data (the real embedding output always
        has structure; fully random isotropic Gaussians in 128-D can be
        near-singular after PCA down to min(50, n-1)).
        """
        from ufpr_automation.rag.advanced.raptor import cluster_embeddings

        rng = np.random.default_rng(1)
        n_per = 40
        dim = 128
        c1 = rng.normal(loc=np.eye(dim)[0] * 10, scale=0.1, size=(n_per, dim))
        c2 = rng.normal(loc=np.eye(dim)[1] * 10, scale=0.1, size=(n_per, dim))
        emb = np.vstack([c1, c2]).astype(np.float32)
        clusters = cluster_embeddings(emb, max_clusters=4)
        assert sum(len(c) for c in clusters) >= 2 * n_per
        # covered every row
        covered = set()
        for c in clusters:
            covered.update(c)
        assert covered == set(range(2 * n_per))


class TestSummarizeCluster:
    def test_uses_litellm_response_content(self):
        from ufpr_automation.rag.advanced import raptor

        fake_msg = MagicMock()
        fake_msg.content = "  Resumo mockado.  "
        fake_choice = MagicMock()
        fake_choice.message = fake_msg
        fake_response = MagicMock()
        fake_response.choices = [fake_choice]

        with patch.object(
            raptor,
            "summarize_cluster",
            wraps=raptor.summarize_cluster,
        ):
            with patch("litellm.completion", return_value=fake_response) as comp:
                out = raptor.summarize_cluster(["chunk 1", "chunk 2"], model_id="test/m")
        assert out == "Resumo mockado."
        # passed the right model + joined text
        kwargs = comp.call_args.kwargs
        assert kwargs["model"] == "test/m"
        assert "chunk 1" in kwargs["messages"][0]["content"]
        assert "chunk 2" in kwargs["messages"][0]["content"]

    def test_truncates_to_20_texts_to_avoid_overflow(self):
        from ufpr_automation.rag.advanced import raptor

        fake_msg = MagicMock()
        fake_msg.content = "ok"
        fake_choice = MagicMock()
        fake_choice.message = fake_msg
        fake_response = MagicMock()
        fake_response.choices = [fake_choice]

        texts = [f"chunk {i}" for i in range(50)]
        with patch("litellm.completion", return_value=fake_response) as comp:
            raptor.summarize_cluster(texts, model_id="test/m")
        prompt = comp.call_args.kwargs["messages"][0]["content"]
        assert "chunk 19" in prompt
        assert "chunk 20" not in prompt  # 21st text dropped

    def test_falls_back_on_litellm_exception(self):
        from ufpr_automation.rag.advanced import raptor

        with patch("litellm.completion", side_effect=RuntimeError("boom")):
            out = raptor.summarize_cluster(
                [
                    "Primeira sentença. Segunda parte.",
                    "Outra sentença. Detalhes.",
                ],
                model_id="test/m",
            )
        # Fallback concatenates first-sentence of each input, up to 5
        assert "Primeira sentença." in out
        assert "Outra sentença." in out


class TestRaptorRetrieverFormatting:
    def test_search_formatted_empty(self):
        from ufpr_automation.rag.advanced.raptor import RaptorRetriever

        r = RaptorRetriever()
        with patch.object(r, "search", return_value=[]):
            out = r.search_formatted("qualquer query")
        assert out == "Nenhum documento relevante encontrado."

    def test_search_formatted_tags_leaf_vs_level(self):
        from ufpr_automation.rag.advanced.raptor import RaptorRetriever

        r = RaptorRetriever()
        results = [
            {
                "text": "texto folha",
                "score": 0.1,
                "level": 0,
                "conselho": "cepe",
                "caminho": "cepe/resolucoes/1.pdf",
            },
            {
                "text": "resumo nivel 2",
                "score": 0.3,
                "level": 2,
                "conselho": "cepe",
                "caminho": "raptor/level_2/cluster_0",
            },
        ]
        with patch.object(r, "search", return_value=results):
            out = r.search_formatted("q")
        assert "[leaf]" in out
        assert "[L2]" in out
        assert "texto folha" in out
        assert "resumo nivel 2" in out
        # score rendered with 4 decimals
        assert "0.1000" in out
        assert "0.3000" in out
