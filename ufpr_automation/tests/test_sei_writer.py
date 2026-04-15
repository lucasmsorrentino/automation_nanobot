"""Tests for SEIWriter — safety regression suite."""
import inspect
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ufpr_automation.sei import writer as writer_module
from ufpr_automation.sei.writer import SEIWriter, _is_forbidden
from ufpr_automation.sei.writer_models import (
    SEIDocClassification,
)

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

    def test_writer_public_api_is_only_whitelisted_write_ops(self):
        public_methods = {
            name for name in dir(SEIWriter)
            if not name.startswith("_") and callable(getattr(SEIWriter, name))
        }
        # Allow run_id property; everything else must be one of the three
        # authorized write operations (attach/draft/create).
        public_methods.discard("run_id")
        assert public_methods == {
            "attach_document",
            "save_despacho_draft",
            "create_process",
            "add_to_acompanhamento_especial",
        }, (
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
    # page.on() and page.remove_listener() are SYNC in real Playwright; override
    # the AsyncMock defaults so tests don't emit "coroutine never awaited"
    # warnings when live-mode paths call them.
    page.on = MagicMock()
    page.remove_listener = MagicMock()
    return page


@pytest.fixture
def writer(mock_page, tmp_path, monkeypatch):
    from ufpr_automation.config import settings
    monkeypatch.setattr(settings, "SEI_WRITE_ARTIFACTS_DIR", tmp_path)
    # Force dry_run so tests are isolated from ambient SEI_WRITE_MODE in .env
    # (tests that want live mode override via monkeypatch locally).
    return SEIWriter(mock_page, run_id="test-run-1234", dry_run=True)


@pytest.fixture
def tce_classification():
    return SEIDocClassification(
        sei_tipo="Externo",
        sei_subtipo="Termo",
        sei_classificacao="Inicial",
    )


class TestAttachDocument:
    @pytest.mark.asyncio
    async def test_attach_returns_failure_for_missing_file(self, writer, tce_classification):
        result = await writer.attach_document(
            "12345.000123/2026-01",
            Path("/nonexistent/file.pdf"),
            tce_classification,
        )
        assert result.success is False
        assert "file_not_found" in result.error

    @pytest.mark.asyncio
    async def test_attach_captures_screenshot(self, writer, tce_classification, tmp_path):
        fake_pdf = tmp_path / "doc.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 fake")
        result = await writer.attach_document(
            "12345.000123/2026-01",
            fake_pdf,
            tce_classification,
        )
        assert result.success is True
        # Dry-run captures one pre-state screenshot; no post-click artifact
        # exists because no click happens.
        assert len(result.artifacts) >= 1

    @pytest.mark.asyncio
    async def test_attach_writes_audit_log(self, writer, tce_classification, tmp_path):
        fake_pdf = tmp_path / "doc.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 fake")
        await writer.attach_document("12345.000123/2026-01", fake_pdf, tce_classification)
        audit_path = tmp_path / "audit.jsonl"
        assert audit_path.exists()
        content = audit_path.read_text(encoding="utf-8")
        assert "attach_document" in content
        assert "12345.000123/2026-01" in content
        # Classification fields must be persisted for later audit.
        assert "Termo" in content
        assert "Inicial" in content


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


class TestCreateProcess:
    @pytest.mark.asyncio
    async def test_create_dryrun_returns_synthetic_id(self, writer):
        result = await writer.create_process(
            tipo_processo="Graduação/Ensino Técnico: Estágios não Obrigatórios",
            especificacao="Design Gráfico",
            interessado="ALANIS ROCHA - GRR20230091",
        )
        assert result.success is True
        assert result.dry_run is True
        assert result.processo_id == f"DRYRUN-{writer.run_id}"
        assert result.tipo_processo.startswith("Graduação")
        assert result.interessado == "ALANIS ROCHA - GRR20230091"

    @pytest.mark.asyncio
    async def test_create_dryrun_writes_audit(self, writer, tmp_path):
        await writer.create_process(
            tipo_processo="Estágios não Obrigatórios",
            especificacao="Design Gráfico",
            interessado="ALANIS ROCHA - GRR20230091",
            motivo="Termo de Compromisso",
        )
        audit_path = tmp_path / "audit.jsonl"
        assert audit_path.exists()
        content = audit_path.read_text(encoding="utf-8")
        assert "create_process" in content
        assert "ALANIS ROCHA - GRR20230091" in content
        assert "dry_run" in content

    @pytest.mark.asyncio
    async def test_create_live_mode_no_longer_raises_not_implemented(
        self, mock_page, tmp_path, monkeypatch
    ):
        """Live mode is wired up — must not raise NotImplementedError.

        With a mocked Page the Playwright flow will fail differently (e.g.,
        AttributeError / TypeError from AsyncMock internals) — the only
        contract we guard here is that the old placeholder is gone.
        """
        from ufpr_automation.config import settings
        monkeypatch.setattr(settings, "SEI_WRITE_ARTIFACTS_DIR", tmp_path)
        live_writer = SEIWriter(mock_page, run_id="live-test", dry_run=False)
        with pytest.raises(Exception) as exc_info:
            await live_writer.create_process(
                tipo_processo="Estágios não Obrigatórios",
                especificacao="Design Gráfico",
                interessado="ALANIS ROCHA - GRR20230091",
            )
        assert not isinstance(exc_info.value, NotImplementedError), (
            "live mode should be wired up, not blocked by NotImplementedError"
        )


class TestAttachDocumentLiveMode:
    @pytest.mark.asyncio
    async def test_attach_live_mode_no_longer_raises_not_implemented(
        self, mock_page, tce_classification, tmp_path, monkeypatch
    ):
        from ufpr_automation.config import settings
        monkeypatch.setattr(settings, "SEI_WRITE_ARTIFACTS_DIR", tmp_path)
        live_writer = SEIWriter(mock_page, run_id="live-test", dry_run=False)
        fake_pdf = tmp_path / "doc.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 fake")
        with pytest.raises(Exception) as exc_info:
            await live_writer.attach_document(
                "12345.000123/2026-01", fake_pdf, tce_classification
            )
        assert not isinstance(exc_info.value, NotImplementedError)


class TestSaveDespachoDraftLiveMode:
    @pytest.mark.asyncio
    async def test_draft_live_mode_no_longer_raises_not_implemented(
        self, mock_page, tmp_path, monkeypatch
    ):
        """save_despacho_draft wraps live-mode errors in a failed DraftResult
        (see the broad except at the bottom of the method). We only guarantee
        here that the old NotImplementedError gate is gone — with a mocked
        page, the live flow will fail and surface error != None.

        We patch ``get_form`` so the test is independent of whether a real
        ``sei_selectors.yaml`` capture manifest is present on disk. With a
        stub form the flow gets past selector loading and fails on the
        mocked Playwright page as originally intended.
        """
        from ufpr_automation.config import settings
        monkeypatch.setattr(settings, "SEI_WRITE_ARTIFACTS_DIR", tmp_path)
        live_writer = SEIWriter(mock_page, run_id="live-test", dry_run=False)
        stub_form = {"fields": {}}
        with patch("ufpr_automation.graphrag.templates.get_registry") as gr, \
             patch(
                 "ufpr_automation.sei.writer_selectors.get_form",
                 return_value=stub_form,
             ):
            gr.return_value.get.return_value = "Despacho body: [NOME]"
            result = await live_writer.save_despacho_draft(
                "12345.000123/2026-01",
                tipo="tce_inicial",
                variables={"NOME": "Aluno"},
            )
        assert result.success is False
        assert result.error is not None
        assert "NotImplementedError" not in (result.error or "")
        assert "selector capture" not in (result.error or "")


# ============================================================================
# End-to-end dry-run smoke test
# ----------------------------------------------------------------------------
# Exercises the full Estágios chain: create_process → attach_document
# → save_despacho_draft with a mocked page, and verifies audit.jsonl captures
# all three operations in order with mode=dry_run. Protects the dry-run path
# against regressions while live mode is blocked on selector capture
# (see SDD_SEI_SELECTOR_CAPTURE.md).
# ============================================================================

class TestSEIWriterDryRunEndToEnd:
    @pytest.mark.asyncio
    async def test_full_estagios_chain_dryrun(
        self, writer, tce_classification, tmp_path
    ):
        # 1. create_process → synthetic id
        create_result = await writer.create_process(
            tipo_processo="Graduação/Ensino Técnico: Estágios não Obrigatórios",
            especificacao="Design Gráfico",
            interessado="ALANIS ROCHA - GRR20230091",
        )
        assert create_result.success is True
        assert create_result.dry_run is True
        processo_id = create_result.processo_id
        assert processo_id.startswith("DRYRUN-")

        # 2. attach_document → TCE PDF
        fake_tce = tmp_path / "tce.pdf"
        fake_tce.write_bytes(b"%PDF-1.4 fake-tce-content")
        attach_result = await writer.attach_document(
            processo_id, fake_tce, tce_classification
        )
        assert attach_result.success is True
        assert attach_result.dry_run is True
        assert attach_result.processo_id == processo_id

        # 3. save_despacho_draft using body_override (no TemplateRegistry lookup)
        draft_result = await writer.save_despacho_draft(
            processo_id,
            tipo="tce_inicial",
            variables={"NOME_ALUNO": "ALANIS ROCHA", "GRR": "GRR20230091"},
            body_override=(
                "Despacho: encaminha-se o TCE de [NOME_ALUNO] ([GRR]) "
                "para análise da Coordenação."
            ),
        )
        assert draft_result.success is True
        assert draft_result.dry_run is True
        assert draft_result.processo_id == processo_id
        assert draft_result.tipo == "tce_inicial"

        # 4. audit.jsonl must have 3 records in order, all with mode=dry_run
        audit_path = tmp_path / "audit.jsonl"
        assert audit_path.exists()
        records = [
            json.loads(line)
            for line in audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(records) == 3
        assert [r["op"] for r in records] == [
            "create_process",
            "attach_document",
            "save_despacho_draft",
        ]
        for r in records:
            assert r["mode"] == "dry_run"
            assert r["run_id"] == "test-run-1234"

        # 5. Classification and template override are persisted in audit
        assert records[1]["sei_subtipo"] == "Termo"
        assert records[1]["sei_classificacao"] == "Inicial"
        assert records[1]["file_sha256"]
        assert records[2]["content_sha256"]
        assert records[2]["content_length"] > 0

        # 6. No clicks happened — the forbidden-selector guard was never
        # triggered, and the mock page's click was never awaited.
        writer._page.click.assert_not_called()


# ============================================================================
# Live-mode unit tests for extracted helpers
# ----------------------------------------------------------------------------
# Full end-to-end live-mode coverage requires a real SEI instance; these tests
# cover the surgical helpers added by the Sprint 3 fix (template despacho
# default loading) so regressions are caught without a live SEI.
# ============================================================================

class TestClearEditorBodyHelper:
    """Sprint 3 fix — save_despacho_draft clears the CKEditor body before
    typing, in case 'Texto Inicial = Nenhum' was not honored and the default
    template loaded. Regression: writer used to call .type() directly, which
    appended to the default template instead of replacing it."""

    @pytest.mark.asyncio
    async def test_clear_editor_body_presses_ctrl_a_then_delete(self):
        popup = AsyncMock()
        await SEIWriter._clear_editor_body(popup)
        press_calls = [c.args[0] for c in popup.keyboard.press.call_args_list]
        assert press_calls == ["Control+A", "Delete"], (
            f"expected Ctrl+A then Delete, got {press_calls}"
        )

    @pytest.mark.asyncio
    async def test_clear_editor_body_waits_briefly_after_delete(self):
        popup = AsyncMock()
        await SEIWriter._clear_editor_body(popup)
        popup.wait_for_timeout.assert_awaited_once()
        (timeout_ms,) = popup.wait_for_timeout.call_args.args
        assert 100 <= timeout_ms <= 500, (
            f"wait_for_timeout should be short (100–500ms), got {timeout_ms}"
        )

    @pytest.mark.asyncio
    async def test_clear_editor_body_does_not_type_or_click(self):
        """Guard: the helper must only press keys, never type text nor click
        buttons — typing here would corrupt the subsequent fill, and clicking
        could hit a forbidden selector in the editor toolbar."""
        popup = AsyncMock()
        await SEIWriter._clear_editor_body(popup)
        popup.keyboard.type.assert_not_called()
        popup.click.assert_not_called()


class TestAddToAcompanhamentoEspecial:
    """POP-38 skeleton — dry_run path only until new selector capture lands."""

    @pytest.mark.asyncio
    async def test_dry_run_returns_success_without_click(self, writer):
        result = await writer.add_to_acompanhamento_especial(
            "23075.000123/2026-01",
            grupo="Estágio não obrigatório",
        )
        assert result.success is True
        assert result.dry_run is True
        assert result.processo_id == "23075.000123/2026-01"
        assert result.grupo == "Estágio não obrigatório"
        # no click ever happens in dry_run
        writer._page.click.assert_not_called()

    @pytest.mark.asyncio
    async def test_dry_run_writes_audit_log(self, writer, tmp_path):
        await writer.add_to_acompanhamento_especial(
            "23075.000123/2026-01",
            grupo="Estágio não obrigatório",
            observacao="TCE inicial — monitorar vigência",
        )
        audit_path = tmp_path / "audit.jsonl"
        assert audit_path.exists()
        lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
        last = json.loads(lines[-1])
        assert last["op"] == "add_to_acompanhamento_especial"
        assert last["processo_id"] == "23075.000123/2026-01"
        assert last["grupo"] == "Estágio não obrigatório"
        assert last["observacao"] == "TCE inicial — monitorar vigência"
        assert last["mode"] == "dry_run"

    @pytest.mark.asyncio
    async def test_live_mode_raises_not_implemented(self, mock_page, tmp_path, monkeypatch):
        from ufpr_automation.config import settings
        monkeypatch.setattr(settings, "SEI_WRITE_ARTIFACTS_DIR", tmp_path)
        live_writer = SEIWriter(mock_page, run_id="live-test", dry_run=False)
        with pytest.raises(NotImplementedError, match="acompanhamento_especial"):
            await live_writer.add_to_acompanhamento_especial(
                "23075.000123/2026-01",
                grupo="Estágio não obrigatório",
            )
        # no click ever happens — guard against accidental live wiring
        mock_page.click.assert_not_called()
