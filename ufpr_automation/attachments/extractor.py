"""Extract readable text from email attachments.

Supports PDF (PyMuPDF), DOCX (python-docx), XLSX (openpyxl), and plain text.
Images and scanned PDFs are flagged with needs_ocr=True for future OCR support.
"""

from __future__ import annotations

from pathlib import Path

from ufpr_automation.core.models import AttachmentData
from ufpr_automation.utils.logging import logger

# Minimum chars per page to consider a PDF as having extractable text.
# Below this threshold, the PDF is likely scanned/image-based.
_MIN_CHARS_PER_PAGE = 20


def extract_text_from_attachment(att: AttachmentData) -> str:
    """Extract text from an attachment based on its MIME type.

    Updates att.extracted_text and att.needs_ocr in place.

    Returns:
        The extracted text (also stored in att.extracted_text).
    """
    mime = att.mime_type.lower()
    path = Path(att.local_path)

    if not path.exists():
        logger.warning("Anexo nao encontrado: %s", att.local_path)
        return ""

    try:
        if mime == "application/pdf":
            text = _extract_pdf(path)
        elif mime in (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        ):
            text = _extract_docx(path)
        elif mime in (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel",
        ):
            text = _extract_xlsx(path)
        elif mime.startswith("text/"):
            text = path.read_text(encoding="utf-8", errors="replace")
        elif mime.startswith("image/"):
            att.needs_ocr = True
            att.extracted_text = ""
            logger.debug("Anexo imagem '%s' — OCR necessario (fase 2)", att.filename)
            return ""
        else:
            logger.debug("Tipo MIME nao suportado para extracao: %s (%s)", mime, att.filename)
            att.extracted_text = ""
            return ""
    except Exception as e:
        logger.warning("Falha ao extrair texto de '%s': %s", att.filename, e)
        att.needs_ocr = True
        att.extracted_text = ""
        return ""

    if not text.strip():
        att.needs_ocr = True
        att.extracted_text = ""
        return ""

    att.extracted_text = text
    return text


def _extract_pdf(path: Path) -> str:
    """Extract text from a PDF using PyMuPDF."""
    import pymupdf

    doc = pymupdf.open(str(path))
    pages = []
    for page in doc:
        text = page.get_text()
        if text.strip():
            pages.append(text)
    num_pages = len(doc)
    doc.close()

    full_text = "\n\n".join(pages)

    # Detect scanned PDFs: very little text relative to page count
    if num_pages > 0 and len(full_text) / num_pages < _MIN_CHARS_PER_PAGE:
        return ""  # Caller will set needs_ocr

    return full_text


def _extract_docx(path: Path) -> str:
    """Extract text from a DOCX file using python-docx."""
    try:
        from docx import Document
    except ImportError:
        logger.warning("python-docx nao instalado — pip install python-docx")
        return ""

    doc = Document(str(path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


def _extract_xlsx(path: Path) -> str:
    """Extract text from an XLSX file using openpyxl."""
    try:
        from openpyxl import load_workbook
    except ImportError:
        logger.warning("openpyxl nao instalado — pip install openpyxl")
        return ""

    wb = load_workbook(str(path), read_only=True, data_only=True)
    lines = []
    for sheet in wb.sheetnames:
        ws = wb[sheet]
        lines.append(f"[Planilha: {sheet}]")
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) if c is not None else "" for c in row]
            line = " | ".join(cells)
            if line.strip(" |"):
                lines.append(line)
    wb.close()
    return "\n".join(lines)
