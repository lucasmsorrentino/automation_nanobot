"""Tests for SEIWriter — safety regression suite."""
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ufpr_automation.sei import writer as writer_module
from ufpr_automation.sei.writer import SEIWriter, _FORBIDDEN_SELECTORS, _is_forbidden
from ufpr_automation.sei.writer_models import AttachResult, DraftResult


# ============================================================================
# CRITICAL SAFETY REGRESSION TESTS — these must NEVER be skipped or removed
# ============================================================================

class TestWriterArchitecturalSafety:
    """Verify SEIWriter does NOT expose any sign/send/protocol methods."""

    def test_writer_has_no_sign_method(self):
        assert not hasattr(SEIWriter, "sign")
        assert not hasattr(SEIWriter, "assinar")

    def test_writer_has_no_send_method(self):
        assert not hasattr(SEIWriter, "send")
        assert not hasattr(SEIWriter, "send_process")
        assert not hasattr(SEIWriter, "enviar")
        assert not hasattr(SEIWriter, "enviar_processo")

    def test_writer_has_no_protocol_method(self):
        assert not hasattr(SEIWriter, "protocol")
        assert not hasattr(SEIWriter, "protocol_submit")
        assert not hasattr(SEIWriter, "protocolar")

    def test_writer_has_no_finalize_method(self):
        assert not hasattr(SEIWriter, "finalize")

    def test_writer_public_api_is_only_attach_and_draft(self):
        public_methods = {
            name for name in dir(SEIWriter)
            if not name.startswith("_") and callable(getattr(SEIWriter, name))
        }
        # Allow run_id property and constructor; everything else must be one
        # of the two write operations.
        public_methods.discard("run_id")
        assert public_methods == {"attach_document", "save_despacho_draft"}, (
            f"SEIWriter exposes unexpected methods: {public_methods}. "
            f"Adding new write operations requires explicit safety review."
        )

    def test_no_method_body_references_forbidden_keywords(self):
        """Static check: no method body contains literal 'Assinar' or 'Enviar' selectors."""
        src = inspect.getsource(writer_module)
        # Strip the comment/docstring areas — focus on method bodies.
        # The _FORBIDDEN_SELECTORS list itself contains these tokens, which
        # is fine; we just want to ensure no .click('Assinar') sneaks in.
        forbidden_click_patterns = [
            "click(\"text=Assinar",
            "click('text=Assinar",
            "click(\"text=Enviar",
            "click('text=Enviar",
            "click(\"text=Protocolar",
            "click('text=Protocolar",
        ]
        for pat in forbidden_click_patterns:
            assert pat not in src, f"Forbidden click pattern found: {pat}"


class TestForbiddenSelectorGuard:
    """The _is_forbidden helper and _safe_click runtime guard."""

    def test_is_forbidden_detects_assinar(self):
        assert _is_forbidden("text=Assinar")
        assert _is_forbidden("#btnAssinar")
        assert _is_forbidden("button:has-text('Assinar')")

    def test_is_forbidden_detects_enviar_processo(self):
        assert _is_forbidden("text=Enviar Processo")
        assert _is_forbidden("#btnEnviar")

    def test_is_forbidden_detects_protocolar(self):
        assert _is_forbidden("text=Protocolar")
        assert _is_forbidden("#btnProtocolar")

    def test_is_forbidden_allows_salvar(self):
        assert not _is_forbidden("text=Salvar")
        assert not _is_forbidden("#btnSalvar")
        assert not _is_forbidden("button:has-text('Salvar')")

    def test_is_forbidden_handles_empty(self):
        assert not _is_forbidden("")
        assert not _is_forbidden(None)

    def test_assert_not_forbidden_raises_for_assinar(self):
        with pytest.raises(PermissionError, match="forbidden selector"):
            SEIWriter._assert_not_forbidden("text=Assinar")

    def test_assert_not_forbidden_passes_for_salvar(self):
        # Should not raise
        SEIWriter._assert_not_forbidden("text=Salvar")


# ============================================================================
# Functional tests
# ============================================================================

@pytest.fixture
def mock_page():
    page = AsyncMock()
    page.screenshot = AsyncMock()
    page.content = AsyncMock(return_value="<html>fake</html>")
    page.click = AsyncMock()
    return page


@pytest.fixture
def writer(mock_page, tmp_path, monkeypatch):
    from ufpr_automation.config import settings
    monkeypatch.setattr(settings, "SEI_WRITE_ARTIFACTS_DIR", tmp_path)
    return SEIWriter(mock_page, run_id="test-run-1234")


class TestAttachDocument:
    @pytest.mark.asyncio
    async def test_attach_returns_failure_for_missing_file(self, writer):
        result = await writer.attach_document(
            "12345.000123/2026-01",
            Path("/nonexistent/file.pdf"),
        )
        assert result.success is False
        assert "file_not_found" in result.error

    @pytest.mark.asyncio
    async def test_attach_captures_screenshots(self, writer, tmp_path):
        fake_pdf = tmp_path / "doc.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 fake")
        result = await writer.attach_document(
            "12345.000123/2026-01",
            fake_pdf,
        )
        assert result.success is True
        assert len(result.artifacts) >= 2  # pre + post

    @pytest.mark.asyncio
    async def test_attach_writes_audit_log(self, writer, tmp_path):
        fake_pdf = tmp_path / "doc.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 fake")
        await writer.attach_document("12345.000123/2026-01", fake_pdf)
        audit_path = tmp_path / "audit.jsonl"
        assert audit_path.exists()
        content = audit_path.read_text(encoding="utf-8")
        assert "attach_document" in content
        assert "12345.000123/2026-01" in content


class TestSaveDespachoDraft:
    @pytest.mark.asyncio
    async def test_save_returns_failure_when_template_unavailable(self, writer):
        with patch("ufpr_automation.graphrag.templates.get_registry") as gr:
            gr.return_value.get.return_value = None
            result = await writer.save_despacho_draft(
                "12345.000123/2026-01",
                tipo="tce_inicial",
                variables={},
            )
        assert result.success is False
        assert result.error == "template_unavailable"

    @pytest.mark.asyncio
    async def test_save_uses_template_registry(self, writer):
        with patch("ufpr_automation.graphrag.templates.get_registry") as gr:
            gr.return_value.get.return_value = "Despacho TCE: [NOME]"
            result = await writer.save_despacho_draft(
                "12345.000123/2026-01",
                tipo="tce_inicial",
                variables={"NOME": "Aluno X"},
            )
        assert result.success is True
        assert result.tipo == "tce_inicial"
        gr.return_value.get.assert_called_once_with("tce_inicial")

    @pytest.mark.asyncio
    async def test_save_writes_audit_with_content_hash(self, writer, tmp_path):
        with patch("ufpr_automation.graphrag.templates.get_registry") as gr:
            gr.return_value.get.return_value = "Despacho body"
            await writer.save_despacho_draft(
                "12345.000123/2026-01",
                tipo="tce_inicial",
                variables={},
            )
        audit_path = tmp_path / "audit.jsonl"
        content = audit_path.read_text(encoding="utf-8")
        assert "save_despacho_draft" in content
        assert "content_sha256" in content


class TestSafeClickGuard:
    @pytest.mark.asyncio
    async def test_safe_click_blocks_forbidden_at_runtime(self, writer):
        with pytest.raises(PermissionError, match="forbidden selector"):
            await writer._safe_click("text=Assinar")

    @pytest.mark.asyncio
    async def test_safe_click_passes_for_salvar(self, writer, mock_page):
        await writer._safe_click("text=Salvar")
        mock_page.click.assert_awaited_once_with("text=Salvar")
