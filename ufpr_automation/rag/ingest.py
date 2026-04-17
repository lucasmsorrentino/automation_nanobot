"""Ingest UFPR institutional PDFs into a LanceDB vector store.

Usage:
    python -m ufpr_automation.rag.ingest                        # ingest all docs
    python -m ufpr_automation.rag.ingest --subset estagio       # only estágio docs
    python -m ufpr_automation.rag.ingest --subset cepe/resolucoes
    python -m ufpr_automation.rag.ingest --dry-run              # show stats, don't index
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import pymupdf  # PyMuPDF

from ufpr_automation.config import settings
from ufpr_automation.utils.logging import logger

DOCS_DIR = settings.RAG_DOCS_DIR
STORE_DIR = settings.RAG_STORE_DIR

# Councils and doc types that map to folder structure
COUNCILS = ("cepe", "coun", "coplad", "concur")
DOC_TYPES = ("atas", "resolucoes", "instrucoes-normativas")


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------


def extract_text(pdf_path: Path, use_ocr: bool = True) -> str:
    """Extract text from a PDF using PyMuPDF, with OCR fallback for scanned pages.

    Args:
        pdf_path: Path to the PDF file.
        use_ocr: If True and PyMuPDF returns no text, try Tesseract OCR.
    """
    doc = pymupdf.open(str(pdf_path))
    pages = []
    for page in doc:
        text = page.get_text()
        if text.strip():
            pages.append(text)
    num_pages = len(doc)
    doc.close()

    full_text = "\n\n".join(pages)

    # If we got enough text, return it
    if full_text.strip():
        return full_text

    # OCR fallback for scanned PDFs
    if use_ocr and num_pages > 0:
        return _ocr_pdf(pdf_path)

    return ""


def _ocr_pdf(pdf_path: Path) -> str:
    """Extract text from a scanned PDF via Tesseract OCR."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        logger.debug("pytesseract/Pillow not installed — skipping OCR")
        return ""

    # Auto-detect Tesseract on Windows
    if sys.platform == "win32":
        import shutil

        if not shutil.which("tesseract"):
            win_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
            if Path(win_path).exists():
                pytesseract.pytesseract.tesseract_cmd = win_path

    try:
        pytesseract.get_tesseract_version()
    except Exception:
        logger.debug("Tesseract not found on system — skipping OCR")
        return ""

    import io

    doc = pymupdf.open(str(pdf_path))
    pages_text = []
    for page in doc:
        pix = page.get_pixmap(dpi=300)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        text = pytesseract.image_to_string(img, lang="por+eng")
        if text.strip():
            pages_text.append(text.strip())
    doc.close()

    full_text = "\n\n".join(pages_text)
    if full_text:
        logger.info(
            "OCR: %d chars from '%s' (%d pages)", len(full_text), pdf_path.name, len(pages_text)
        )
    return full_text


# ---------------------------------------------------------------------------
# Metadata extraction from path
# ---------------------------------------------------------------------------


def metadata_from_path(pdf_path: Path) -> dict:
    """Derive metadata from the file's position in the docs/ tree.

    Examples:
        docs/cepe/resolucoes/foo.pdf  -> {conselho: cepe, tipo: resolucoes}
        docs/estagio/bar.pdf          -> {conselho: estagio, tipo: estagio}
    """
    rel = pdf_path.relative_to(DOCS_DIR)
    parts = rel.parts  # e.g. ("cepe", "resolucoes", "foo.pdf")

    if len(parts) >= 3:
        conselho, tipo = parts[0], parts[1]
    elif len(parts) == 2:
        conselho = parts[0]
        tipo = parts[0]  # e.g. "estagio/file.pdf" -> tipo=estagio
    else:
        conselho, tipo = "unknown", "unknown"

    # Try to extract a date from the filename (common patterns: dd.mm.yyyy, dd-mm-yyyy)
    date_match = re.search(r"(\d{2})[.\-](\d{2})[.\-](\d{4})", pdf_path.stem)
    if not date_match:
        # Try yyyy pattern at end of filename
        date_match = re.search(r"(\d{4})", pdf_path.stem)

    return {
        "conselho": conselho,
        "tipo": tipo,
        "arquivo": pdf_path.name,
        "caminho": str(rel),
    }


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def chunk_text(text: str, chunk_size: int = 1000, chunk_overlap: int = 200) -> list[str]:
    """Split text into overlapping chunks using langchain's RecursiveCharacterTextSplitter.

    Uses separators tuned for Portuguese legal/institutional documents.
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=[
            "\n\n\n",  # page breaks / major sections
            "\n\n",  # paragraphs
            "\nArt.",  # artigos de resolução
            "\nParágrafo",  # parágrafos de resolução
            "\n§",  # parágrafo symbol
            "\n",  # line breaks
            ". ",  # sentences
            " ",
        ],
        keep_separator=True,
    )
    chunks = splitter.split_text(text)
    # Filter out tiny fragments
    return [c for c in chunks if len(c.strip()) > 50]


# ---------------------------------------------------------------------------
# Embedding model
# ---------------------------------------------------------------------------

_EMBED_MODEL = None
_EMBED_MODEL_NAME = "intfloat/multilingual-e5-large"


def get_embed_model():
    """Lazy-load the sentence-transformers embedding model."""
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        from sentence_transformers import SentenceTransformer

        print(f"Loading embedding model: {_EMBED_MODEL_NAME} ...")
        _EMBED_MODEL = SentenceTransformer(_EMBED_MODEL_NAME)
        print("Model loaded.")
    return _EMBED_MODEL


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts. Prepends 'passage: ' for E5 models."""
    model = get_embed_model()
    prefixed = [f"passage: {t}" for t in texts]
    embeddings = model.encode(prefixed, show_progress_bar=True, normalize_embeddings=True)
    return embeddings.tolist()


# ---------------------------------------------------------------------------
# LanceDB indexing
# ---------------------------------------------------------------------------


def get_or_create_table(db, table_name: str = "ufpr_docs"):
    """Get existing table or return None if it doesn't exist."""
    if table_name in db.list_tables().tables:
        return db.open_table(table_name)
    return None


def ingest_docs(
    subset: str | None = None,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    dry_run: bool = False,
    table_name: str = "ufpr_docs",
    ocr_only: bool = False,
    use_ocr: bool = True,
) -> dict:
    """Main ingestion pipeline: PDF -> text -> chunks -> embeddings -> LanceDB.

    Args:
        subset: Optional filter like "estagio", "cepe/resolucoes", etc.
        chunk_size: Max characters per chunk.
        chunk_overlap: Overlap between consecutive chunks.
        dry_run: If True, extract and chunk but don't embed or index.
        table_name: Name of the LanceDB table.
        ocr_only: If True, only process PDFs that were previously empty (not indexed).
        use_ocr: If True, use Tesseract OCR for scanned PDFs (default True).

    Returns:
        Dict with stats: {pdfs, chunks, indexed, skipped, errors, ocr_recovered}.
    """
    import lancedb

    # Collect PDF paths
    pdf_paths = _collect_pdfs(subset)
    print(f"Found {len(pdf_paths)} PDFs to process.")

    if not pdf_paths:
        return {"pdfs": 0, "chunks": 0, "indexed": 0, "skipped": 0, "errors": 0, "ocr_recovered": 0}

    # Open/create LanceDB
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(STORE_DIR / "ufpr.lance"))

    # Check existing table to skip already-indexed files
    table = get_or_create_table(db, table_name)
    existing_files: set[str] = set()
    if table is not None:
        try:
            col = table.to_arrow().column("arquivo")
            existing_files = set(v.as_py() for v in col)
        except Exception:
            pass

    # In ocr_only mode, filter to just the PDFs not yet indexed
    if ocr_only:
        pdf_paths = [p for p in pdf_paths if p.name not in existing_files]
        print(f"OCR-only mode: {len(pdf_paths)} PDFs not yet indexed.")

    stats = {
        "pdfs": len(pdf_paths),
        "chunks": 0,
        "indexed": 0,
        "skipped": 0,
        "errors": 0,
        "ocr_recovered": 0,
    }

    all_records = []

    for i, pdf_path in enumerate(pdf_paths, 1):
        meta = metadata_from_path(pdf_path)

        if not ocr_only and meta["arquivo"] in existing_files:
            stats["skipped"] += 1
            continue

        print(f"[{i}/{len(pdf_paths)}] {meta['caminho']} ...", end=" ", flush=True)

        try:
            text = extract_text(pdf_path, use_ocr=use_ocr)
            if not text.strip():
                print("(empty)")
                stats["errors"] += 1
                continue

            # Track OCR recoveries
            text_direct = _extract_text_only(pdf_path)
            if not text_direct.strip() and text.strip():
                stats["ocr_recovered"] += 1
                print("(OCR) ", end="", flush=True)

            chunks = chunk_text(text, chunk_size, chunk_overlap)
            stats["chunks"] += len(chunks)
            print(f"{len(chunks)} chunks", end="", flush=True)

            if dry_run:
                print()
                continue

            # Embed
            vectors = embed_texts(chunks)

            # Build records
            for j, (chunk, vec) in enumerate(zip(chunks, vectors)):
                record = {
                    "text": chunk,
                    "vector": vec,
                    "conselho": meta["conselho"],
                    "tipo": meta["tipo"],
                    "arquivo": meta["arquivo"],
                    "caminho": meta["caminho"],
                    "chunk_idx": j,
                }
                all_records.append(record)

            stats["indexed"] += 1
            print(" -> indexed", flush=True)

        except Exception as e:
            print(f"ERROR: {e}")
            stats["errors"] += 1

    # Batch insert into LanceDB
    if all_records and not dry_run:
        print(f"\nInserting {len(all_records)} records into LanceDB ...", flush=True)
        if table is None:
            db.create_table(table_name, data=all_records)
        else:
            table.add(all_records)
        print("Done.")

    print(f"\nStats: {stats}")
    return stats


def _extract_text_only(pdf_path: Path) -> str:
    """Extract text from PDF using PyMuPDF only (no OCR). For detecting OCR recoveries."""
    doc = pymupdf.open(str(pdf_path))
    pages = [page.get_text() for page in doc if page.get_text().strip()]
    doc.close()
    return "\n\n".join(pages)


def _collect_pdfs(subset: str | None) -> list[Path]:
    """Collect PDF file paths, optionally filtered by subset."""
    if subset:
        target = DOCS_DIR / subset
        if not target.exists():
            print(f"Path not found: {target}")
            return []
        return sorted(target.rglob("*.pdf"))

    # All docs
    return sorted(DOCS_DIR.rglob("*.pdf"))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Ingest UFPR docs into vector store")
    parser.add_argument(
        "--subset",
        type=str,
        default=None,
        help="Subfolder to ingest (e.g. 'estagio', 'cepe/resolucoes')",
    )
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--chunk-overlap", type=int, default=200)
    parser.add_argument(
        "--dry-run", action="store_true", help="Extract and chunk without embedding/indexing"
    )
    parser.add_argument(
        "--ocr-only", action="store_true", help="Only process PDFs not yet indexed (OCR recovery)"
    )
    parser.add_argument(
        "--no-ocr", action="store_true", help="Disable OCR fallback for scanned PDFs"
    )
    args = parser.parse_args()

    t0 = time.time()
    ingest_docs(
        subset=args.subset,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        dry_run=args.dry_run,
        ocr_only=args.ocr_only,
        use_ocr=not args.no_ocr,
    )
    elapsed = time.time() - t0
    print(f"Elapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
