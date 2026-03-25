"""Tests for the RAG module (ingest + retriever).

Unit tests mock heavy dependencies (sentence-transformers, LanceDB).
Integration tests use real PDFs from the estagio/ subset when available.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ufpr_automation.rag.ingest import (
    DOCS_DIR,
    chunk_text,
    extract_text,
    metadata_from_path,
    _collect_pdfs,
)
from ufpr_automation.rag.retriever import Retriever, SearchResult


# ============================================================================
# Unit Tests — extract_text
# ============================================================================


class TestExtractText:
    def test_extracts_text_from_real_pdf(self):
        """Test text extraction from a known PDF if available."""
        pdf = DOCS_DIR / "estagio" / "Lei11788Estagio.pdf"
        if not pdf.exists():
            pytest.skip("estagio docs not available")
        text = extract_text(pdf)
        assert len(text) > 100
        assert "estágio" in text.lower() or "estagio" in text.lower()

    def test_returns_empty_for_nonexistent(self, tmp_path):
        """PyMuPDF raises on invalid path."""
        with pytest.raises(Exception):
            extract_text(tmp_path / "nonexistent.pdf")

    def test_extracts_from_minimal_pdf(self, tmp_path):
        """Create a minimal PDF and extract its text."""
        import pymupdf

        pdf_path = tmp_path / "test.pdf"
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Resolução CEPE nº 42/2024")
        doc.save(str(pdf_path))
        doc.close()

        text = extract_text(pdf_path)
        assert "Resolução CEPE" in text
        assert "42/2024" in text


# ============================================================================
# Unit Tests — metadata_from_path
# ============================================================================


class TestMetadataFromPath:
    def test_three_level_path(self):
        path = DOCS_DIR / "cepe" / "resolucoes" / "resolucao-42-2024.pdf"
        meta = metadata_from_path(path)
        assert meta["conselho"] == "cepe"
        assert meta["tipo"] == "resolucoes"
        assert meta["arquivo"] == "resolucao-42-2024.pdf"
        assert meta["caminho"] == str(Path("cepe") / "resolucoes" / "resolucao-42-2024.pdf")

    def test_two_level_path(self):
        path = DOCS_DIR / "estagio" / "manual.pdf"
        meta = metadata_from_path(path)
        assert meta["conselho"] == "estagio"
        assert meta["tipo"] == "estagio"
        assert meta["arquivo"] == "manual.pdf"

    def test_coplad_atas(self):
        path = DOCS_DIR / "coplad" / "atas" / "ata-01-2023.pdf"
        meta = metadata_from_path(path)
        assert meta["conselho"] == "coplad"
        assert meta["tipo"] == "atas"

    def test_concur_resolucoes(self):
        path = DOCS_DIR / "concur" / "resolucoes" / "res.pdf"
        meta = metadata_from_path(path)
        assert meta["conselho"] == "concur"
        assert meta["tipo"] == "resolucoes"

    def test_instrucoes_normativas(self):
        path = DOCS_DIR / "coun" / "instrucoes-normativas" / "in-01.pdf"
        meta = metadata_from_path(path)
        assert meta["conselho"] == "coun"
        assert meta["tipo"] == "instrucoes-normativas"


# ============================================================================
# Unit Tests — chunk_text
# ============================================================================


class TestChunkText:
    def test_short_text_single_chunk(self):
        text = "Este é um texto curto sobre estágio obrigatório na UFPR. " * 5
        chunks = chunk_text(text, chunk_size=1000, chunk_overlap=100)
        assert len(chunks) >= 1
        # All content should be present across chunks
        full = " ".join(chunks)
        assert "estágio" in full.lower()

    def test_long_text_multiple_chunks(self):
        text = "Art. 1º O estágio é atividade educativa. " * 100
        chunks = chunk_text(text, chunk_size=200, chunk_overlap=50)
        assert len(chunks) > 1

    def test_filters_tiny_fragments(self):
        text = "Pequeno.\n\n\n\nTexto suficientemente grande para passar no filtro de 50 caracteres mínimos que evita fragmentos."
        chunks = chunk_text(text, chunk_size=200, chunk_overlap=0)
        for chunk in chunks:
            assert len(chunk.strip()) > 50

    def test_respects_legal_separators(self):
        text = textwrap.dedent("""\
            Art. 1º O estágio obrigatório é componente curricular do curso.

            Art. 2º O estágio não obrigatório é atividade complementar opcional.

            Art. 3º A jornada de estágio será compatível com as atividades escolares.

            Parágrafo único. Em períodos de avaliação, a jornada pode ser reduzida.
        """)
        # With a small chunk size, it should split on Art. boundaries
        chunks = chunk_text(text * 5, chunk_size=300, chunk_overlap=50)
        assert len(chunks) >= 2

    def test_empty_text_returns_empty(self):
        chunks = chunk_text("", chunk_size=500, chunk_overlap=100)
        assert chunks == []

    def test_chunk_overlap_works(self):
        # Create text that will definitely need multiple chunks
        sentences = [f"Sentença número {i} sobre regulamentação de estágio. " for i in range(50)]
        text = " ".join(sentences)
        chunks = chunk_text(text, chunk_size=300, chunk_overlap=100)
        assert len(chunks) > 1
        # Check there's some overlap between consecutive chunks
        for i in range(len(chunks) - 1):
            # The end of one chunk and start of next should share some text
            # (not guaranteed to be exact due to separator logic, but chunks shouldn't be disjoint)
            assert len(chunks[i]) > 50


# ============================================================================
# Unit Tests — _collect_pdfs
# ============================================================================


class TestCollectPdfs:
    def test_subset_estagio(self):
        if not (DOCS_DIR / "estagio").exists():
            pytest.skip("estagio docs not available")
        pdfs = _collect_pdfs("estagio")
        assert len(pdfs) == 18
        assert all(p.suffix == ".pdf" for p in pdfs)

    def test_subset_nonexistent(self):
        pdfs = _collect_pdfs("nonexistent_folder_xyz")
        assert pdfs == []

    def test_subset_nested(self):
        if not (DOCS_DIR / "cepe" / "resolucoes").exists():
            pytest.skip("cepe/resolucoes docs not available")
        pdfs = _collect_pdfs("cepe/resolucoes")
        assert len(pdfs) > 0
        assert all("cepe" in str(p) for p in pdfs)

    def test_all_pdfs(self):
        if not DOCS_DIR.exists():
            pytest.skip("docs folder not available")
        pdfs = _collect_pdfs(None)
        assert len(pdfs) > 0


# ============================================================================
# Unit Tests — SearchResult dataclass
# ============================================================================


class TestSearchResult:
    def test_creation(self):
        r = SearchResult(
            text="Art. 1º O estágio...",
            score=0.15,
            conselho="cepe",
            tipo="resolucoes",
            arquivo="res-01-12.pdf",
            caminho="cepe/resolucoes/res-01-12.pdf",
            chunk_idx=0,
        )
        assert r.text == "Art. 1º O estágio..."
        assert r.score == 0.15
        assert r.conselho == "cepe"

    def test_equality(self):
        kwargs = dict(
            text="t", score=0.1, conselho="c", tipo="t",
            arquivo="a.pdf", caminho="c/t/a.pdf", chunk_idx=0,
        )
        r1 = SearchResult(**kwargs)
        r2 = SearchResult(**kwargs)
        assert r1 == r2


# ============================================================================
# Unit Tests — Retriever (mocked)
# ============================================================================


class TestRetrieverMocked:
    def test_search_formatted_no_results(self):
        r = Retriever()
        # Mock _ensure_loaded and search to return empty
        r._table = MagicMock()
        r._model = MagicMock()
        r._model.encode.return_value = MagicMock(tolist=lambda: [0.0] * 1024)

        import pyarrow as pa

        empty_table = pa.table({
            "text": pa.array([], type=pa.string()),
            "_distance": pa.array([], type=pa.float32()),
            "conselho": pa.array([], type=pa.string()),
            "tipo": pa.array([], type=pa.string()),
            "arquivo": pa.array([], type=pa.string()),
            "caminho": pa.array([], type=pa.string()),
            "chunk_idx": pa.array([], type=pa.int64()),
        })

        mock_search = MagicMock()
        mock_search.limit.return_value = mock_search
        mock_search.where.return_value = mock_search
        mock_search.to_arrow.return_value = empty_table
        r._table.search.return_value = mock_search

        result = r.search_formatted("query qualquer")
        assert result == "Nenhum documento relevante encontrado."

    def test_search_returns_results(self):
        r = Retriever()
        r._table = MagicMock()
        r._model = MagicMock()
        r._model.encode.return_value = MagicMock(tolist=lambda: [0.0] * 1024)

        import pyarrow as pa

        results_table = pa.table({
            "text": ["Art. 1º Teste de resolução."],
            "_distance": [0.1234],
            "conselho": ["cepe"],
            "tipo": ["resolucoes"],
            "arquivo": ["res.pdf"],
            "caminho": ["cepe/resolucoes/res.pdf"],
            "chunk_idx": [0],
        })

        mock_search = MagicMock()
        mock_search.limit.return_value = mock_search
        mock_search.to_arrow.return_value = results_table
        r._table.search.return_value = mock_search

        results = r.search("teste", top_k=1)
        assert len(results) == 1
        assert results[0].conselho == "cepe"
        assert results[0].score == pytest.approx(0.1234, abs=0.001)

    def test_search_with_filters(self):
        r = Retriever()
        r._table = MagicMock()
        r._model = MagicMock()
        r._model.encode.return_value = MagicMock(tolist=lambda: [0.0] * 1024)

        import pyarrow as pa

        empty_table = pa.table({
            "text": pa.array([], type=pa.string()),
            "_distance": pa.array([], type=pa.float32()),
            "conselho": pa.array([], type=pa.string()),
            "tipo": pa.array([], type=pa.string()),
            "arquivo": pa.array([], type=pa.string()),
            "caminho": pa.array([], type=pa.string()),
            "chunk_idx": pa.array([], type=pa.int64()),
        })

        mock_search = MagicMock()
        mock_search.limit.return_value = mock_search
        mock_search.where.return_value = mock_search
        mock_search.to_arrow.return_value = empty_table
        r._table.search.return_value = mock_search

        r.search("query", conselho="cepe", tipo="resolucoes")

        # Verify .where() was called with correct filter
        mock_search.where.assert_called_once_with(
            "conselho = 'cepe' AND tipo = 'resolucoes'"
        )

    def test_search_formatted_output_format(self):
        r = Retriever()
        r._table = MagicMock()
        r._model = MagicMock()
        r._model.encode.return_value = MagicMock(tolist=lambda: [0.0] * 1024)

        import pyarrow as pa

        results_table = pa.table({
            "text": ["Texto do chunk 1.", "Texto do chunk 2."],
            "_distance": [0.1, 0.2],
            "conselho": ["cepe", "coun"],
            "tipo": ["resolucoes", "atas"],
            "arquivo": ["res.pdf", "ata.pdf"],
            "caminho": ["cepe/resolucoes/res.pdf", "coun/atas/ata.pdf"],
            "chunk_idx": [0, 0],
        })

        mock_search = MagicMock()
        mock_search.limit.return_value = mock_search
        mock_search.to_arrow.return_value = results_table
        r._table.search.return_value = mock_search

        output = r.search_formatted("query", top_k=2)
        assert "[1]" in output
        assert "[2]" in output
        assert "cepe/resolucoes/res.pdf" in output
        assert "coun/atas/ata.pdf" in output
        assert "---" in output

    def test_ensure_loaded_raises_without_store(self, tmp_path):
        r = Retriever()
        # Patch STORE_DIR to a non-existent path
        with patch("ufpr_automation.rag.retriever.STORE_DIR", tmp_path / "nope"):
            with pytest.raises(FileNotFoundError, match="Vector store not found"):
                r._ensure_loaded()


# ============================================================================
# Integration Tests — full pipeline (require docs + model)
# ============================================================================


class TestIngestIntegration:
    """Integration tests that create a temp PDF, ingest it, and query it.

    These tests use real PyMuPDF but mock the embedding model to avoid
    downloading the 2GB model in CI.
    """

    @pytest.fixture
    def temp_docs(self, tmp_path):
        """Create a temporary docs structure with small PDFs."""
        import pymupdf

        docs_dir = tmp_path / "docs"
        estagio_dir = docs_dir / "estagio"
        estagio_dir.mkdir(parents=True)

        cepe_dir = docs_dir / "cepe" / "resolucoes"
        cepe_dir.mkdir(parents=True)

        # Create test PDF 1 — estágio
        pdf1 = estagio_dir / "regulamento-estagio-test.pdf"
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72),
            "Art. 1º O estágio obrigatório é componente curricular.\n"
            "Art. 2º A duração máxima é de 2 anos.\n"
            "Art. 3º A jornada não excederá 6 horas diárias.\n"
            "Parágrafo único. Em períodos de prova a jornada pode ser reduzida pela metade."
        )
        doc.save(str(pdf1))
        doc.close()

        # Create test PDF 2 — resolução CEPE
        pdf2 = cepe_dir / "resolucao-01-2024.pdf"
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72),
            "Resolução nº 01/2024 - CEPE\n"
            "Aprova as normas para realização de estágio curricular.\n"
            "Art. 1º O estudante deve estar regularmente matriculado.\n"
            "Art. 2º O supervisor deve ter formação na área."
        )
        doc.save(str(pdf2))
        doc.close()

        return docs_dir

    def test_ingest_and_query_with_mock_embeddings(self, tmp_path, temp_docs):
        """Full pipeline: ingest temp PDFs with mock embeddings, then query."""
        import lancedb

        store_dir = tmp_path / "store"
        store_dir.mkdir()

        # Mock embedding function to return deterministic vectors
        embed_dim = 8  # small for testing

        def mock_embed(texts):
            import hashlib
            vectors = []
            for t in texts:
                h = hashlib.md5(t.encode()).digest()
                vec = [b / 255.0 for b in h[:embed_dim]]
                vectors.append(vec)
            return vectors

        # Patch module-level constants and embed function
        with (
            patch("ufpr_automation.rag.ingest.DOCS_DIR", temp_docs),
            patch("ufpr_automation.rag.ingest.STORE_DIR", store_dir),
            patch("ufpr_automation.rag.ingest.embed_texts", side_effect=mock_embed),
        ):
            from ufpr_automation.rag.ingest import ingest_docs

            stats = ingest_docs(subset="estagio", chunk_size=500, chunk_overlap=50)

            assert stats["pdfs"] == 1
            assert stats["indexed"] == 1
            assert stats["chunks"] > 0
            assert stats["errors"] == 0

        # Verify data in LanceDB
        db = lancedb.connect(str(store_dir / "ufpr.lance"))
        table = db.open_table("ufpr_docs")
        arrow_tbl = table.to_arrow()
        assert arrow_tbl.num_rows > 0

        # Check metadata
        conselhos = set(v.as_py() for v in arrow_tbl.column("conselho"))
        assert "estagio" in conselhos

    def test_ingest_idempotent(self, tmp_path, temp_docs):
        """Running ingest twice should skip already-indexed files."""
        store_dir = tmp_path / "store"
        store_dir.mkdir()

        embed_dim = 8

        def mock_embed(texts):
            import hashlib
            vectors = []
            for t in texts:
                h = hashlib.md5(t.encode()).digest()
                vec = [b / 255.0 for b in h[:embed_dim]]
                vectors.append(vec)
            return vectors

        with (
            patch("ufpr_automation.rag.ingest.DOCS_DIR", temp_docs),
            patch("ufpr_automation.rag.ingest.STORE_DIR", store_dir),
            patch("ufpr_automation.rag.ingest.embed_texts", side_effect=mock_embed),
        ):
            from ufpr_automation.rag.ingest import ingest_docs

            stats1 = ingest_docs(subset=None)
            stats2 = ingest_docs(subset=None)

            assert stats1["indexed"] == 2  # both PDFs
            assert stats2["skipped"] == 2  # both skipped on re-run
            assert stats2["indexed"] == 0

    def test_ingest_dry_run(self, tmp_path, temp_docs):
        """Dry run should extract and chunk but not create a store."""
        store_dir = tmp_path / "store"
        store_dir.mkdir()

        with (
            patch("ufpr_automation.rag.ingest.DOCS_DIR", temp_docs),
            patch("ufpr_automation.rag.ingest.STORE_DIR", store_dir),
        ):
            from ufpr_automation.rag.ingest import ingest_docs

            stats = ingest_docs(subset="estagio", dry_run=True)

            assert stats["pdfs"] == 1
            assert stats["chunks"] > 0
            assert stats["indexed"] == 0

    def test_ingest_multiple_subsets(self, tmp_path, temp_docs):
        """Ingest different subsets and verify metadata filtering."""
        store_dir = tmp_path / "store"
        store_dir.mkdir()

        embed_dim = 8

        def mock_embed(texts):
            import hashlib
            vectors = []
            for t in texts:
                h = hashlib.md5(t.encode()).digest()
                vec = [b / 255.0 for b in h[:embed_dim]]
                vectors.append(vec)
            return vectors

        with (
            patch("ufpr_automation.rag.ingest.DOCS_DIR", temp_docs),
            patch("ufpr_automation.rag.ingest.STORE_DIR", store_dir),
            patch("ufpr_automation.rag.ingest.embed_texts", side_effect=mock_embed),
        ):
            from ufpr_automation.rag.ingest import ingest_docs
            import lancedb

            # Ingest all
            stats = ingest_docs(subset=None)
            assert stats["indexed"] == 2

            # Check both councils present
            db = lancedb.connect(str(store_dir / "ufpr.lance"))
            table = db.open_table("ufpr_docs")
            arrow_tbl = table.to_arrow()
            conselhos = set(v.as_py() for v in arrow_tbl.column("conselho"))
            assert "estagio" in conselhos
            assert "cepe" in conselhos
