"""Tests for attachment extraction module."""

import pytest

from ufpr_automation.core.models import AttachmentData


class TestExtractTextFromAttachment:
    """Test extract_text_from_attachment for various file types."""

    def test_plain_text(self, tmp_path):
        """Text files should be read directly."""
        from ufpr_automation.attachments.extractor import extract_text_from_attachment

        txt_file = tmp_path / "test.txt"
        txt_file.write_text("Conteudo de teste do anexo.", encoding="utf-8")

        att = AttachmentData(
            filename="test.txt",
            mime_type="text/plain",
            size_bytes=txt_file.stat().st_size,
            local_path=str(txt_file),
        )
        result = extract_text_from_attachment(att)
        assert "Conteudo de teste do anexo" in result
        assert att.extracted_text == result
        assert not att.needs_ocr

    def test_csv_file(self, tmp_path):
        """CSV files (text/csv) should be read as text."""
        from ufpr_automation.attachments.extractor import extract_text_from_attachment

        csv_file = tmp_path / "data.csv"
        csv_file.write_text("nome,idade\nJoao,25\nMaria,30", encoding="utf-8")

        att = AttachmentData(
            filename="data.csv",
            mime_type="text/csv",
            size_bytes=csv_file.stat().st_size,
            local_path=str(csv_file),
        )
        result = extract_text_from_attachment(att)
        assert "Joao" in result
        assert "Maria" in result

    def test_image_flags_ocr(self, tmp_path):
        """Image attachments should set needs_ocr=True."""
        from ufpr_automation.attachments.extractor import extract_text_from_attachment

        img_file = tmp_path / "scan.jpg"
        img_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        att = AttachmentData(
            filename="scan.jpg",
            mime_type="image/jpeg",
            size_bytes=img_file.stat().st_size,
            local_path=str(img_file),
        )
        result = extract_text_from_attachment(att)
        assert result == ""
        assert att.needs_ocr is True

    def test_unsupported_mime(self, tmp_path):
        """Unsupported MIME types should return empty and not crash."""
        from ufpr_automation.attachments.extractor import extract_text_from_attachment

        bin_file = tmp_path / "data.bin"
        bin_file.write_bytes(b"\x00" * 100)

        att = AttachmentData(
            filename="data.bin",
            mime_type="application/octet-stream",
            size_bytes=100,
            local_path=str(bin_file),
        )
        result = extract_text_from_attachment(att)
        assert result == ""
        assert not att.needs_ocr

    def test_missing_file(self):
        """Missing file should return empty and not crash."""
        from ufpr_automation.attachments.extractor import extract_text_from_attachment

        att = AttachmentData(
            filename="ghost.pdf",
            mime_type="application/pdf",
            size_bytes=1000,
            local_path="/nonexistent/path/ghost.pdf",
        )
        result = extract_text_from_attachment(att)
        assert result == ""

    def test_pdf_extraction(self, tmp_path):
        """PDF with text should extract successfully."""
        pytest.importorskip("pymupdf")
        import pymupdf

        from ufpr_automation.attachments.extractor import extract_text_from_attachment

        # Create a simple PDF with text
        pdf_path = tmp_path / "test.pdf"
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Termo de Compromisso de Estagio")
        doc.save(str(pdf_path))
        doc.close()

        att = AttachmentData(
            filename="test.pdf",
            mime_type="application/pdf",
            size_bytes=pdf_path.stat().st_size,
            local_path=str(pdf_path),
        )
        result = extract_text_from_attachment(att)
        assert "Termo de Compromisso" in result
        assert not att.needs_ocr

    def test_docx_extraction(self, tmp_path):
        """DOCX should extract paragraph text."""
        docx_mod = pytest.importorskip("docx")

        from ufpr_automation.attachments.extractor import extract_text_from_attachment

        docx_path = tmp_path / "oficio.docx"
        doc = docx_mod.Document()
        doc.add_paragraph("Oficio numero 123/2025")
        doc.add_paragraph("Prezado Senhor Coordenador")
        doc.save(str(docx_path))

        att = AttachmentData(
            filename="oficio.docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size_bytes=docx_path.stat().st_size,
            local_path=str(docx_path),
        )
        result = extract_text_from_attachment(att)
        assert "Oficio numero 123" in result
        assert "Coordenador" in result

    def test_xlsx_extraction(self, tmp_path):
        """XLSX should extract cell content."""
        openpyxl = pytest.importorskip("openpyxl")

        from ufpr_automation.attachments.extractor import extract_text_from_attachment

        xlsx_path = tmp_path / "planilha.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Alunos"
        ws.append(["Nome", "Matricula"])
        ws.append(["Joao Silva", "GRR20201234"])
        wb.save(str(xlsx_path))

        att = AttachmentData(
            filename="planilha.xlsx",
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            size_bytes=xlsx_path.stat().st_size,
            local_path=str(xlsx_path),
        )
        result = extract_text_from_attachment(att)
        assert "Joao Silva" in result
        assert "GRR20201234" in result


class TestAttachmentDataModel:
    """Test the AttachmentData dataclass."""

    def test_default_values(self):
        att = AttachmentData()
        assert att.filename == ""
        assert att.mime_type == ""
        assert att.size_bytes == 0
        assert att.local_path == ""
        assert att.extracted_text == ""
        assert att.needs_ocr is False

    def test_email_data_attachments(self):
        from ufpr_automation.core.models import EmailData

        email = EmailData(subject="Teste com anexo")
        assert email.attachments == []
        assert email.has_attachments is False

        email.attachments.append(AttachmentData(filename="doc.pdf", mime_type="application/pdf"))
        email.has_attachments = True
        assert len(email.attachments) == 1
        assert email.has_attachments is True

    def test_email_to_dict_with_attachments(self):
        from ufpr_automation.core.models import EmailData

        email = EmailData(
            subject="Teste",
            has_attachments=True,
            attachments=[
                AttachmentData(filename="a.pdf", mime_type="application/pdf", size_bytes=1024),
            ],
        )
        d = email.to_dict()
        assert d["has_attachments"] is True
        assert len(d["attachments"]) == 1
        assert d["attachments"][0]["filename"] == "a.pdf"
