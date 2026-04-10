"""Tests for ufpr_automation.utils.logging and ufpr_automation.utils.debug."""

from __future__ import annotations

import importlib
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestLogger:
    def test_logger_is_logging_logger(self):
        from ufpr_automation.utils.logging import logger
        assert isinstance(logger, logging.Logger)
        assert logger.name == "ufpr_automation"

    def test_logger_has_handlers(self):
        """After _build_logger runs once, handlers must be attached."""
        from ufpr_automation.utils.logging import logger
        assert len(logger.handlers) >= 1

    def test_logger_reuses_existing_handlers_on_reload(self):
        """Re-importing should not duplicate handlers."""
        from ufpr_automation.utils import logging as logging_mod
        before = len(logging_mod.logger.handlers)
        importlib.reload(logging_mod)
        after = len(logging_mod.logger.handlers)
        # Reload re-runs _build_logger — the early-return short-circuit should
        # ensure handlers are not duplicated.
        assert after == before

    def test_logger_can_emit_without_raising(self, caplog):
        """Emit a message and ensure no exception is raised from our handlers."""
        from ufpr_automation.utils.logging import logger
        with caplog.at_level(logging.INFO, logger="ufpr_automation"):
            logger.info("test message — UTF-8 ok (acento e emoji 🚀)")
        # caplog should capture our message.
        assert any(
            "test message" in record.getMessage() for record in caplog.records
        )

    def test_stdout_reconfigure_helper_tolerates_missing_attribute(self, monkeypatch):
        """The UTF-8 reconfigure block should not crash on a stdout without
        ``.reconfigure`` (older Python, or a mocked sys.stdout).

        We simulate this by replacing sys.stdout with a plain MagicMock (no
        reconfigure attribute) and re-importing the module.
        """
        import sys as real_sys

        # Build a stdout stand-in that EXPLICITLY raises AttributeError when
        # ``reconfigure`` is accessed (mimicking Python <3.7 or test doubles).
        class _NoReconfigureStdout:
            def write(self, _s):
                return None

            def flush(self):
                return None

            # Purposefully do NOT define .reconfigure.
            def __getattr__(self, name):
                if name == "reconfigure":
                    raise AttributeError(name)
                raise AttributeError(name)

        fake_stdout = _NoReconfigureStdout()
        fake_stderr = _NoReconfigureStdout()

        monkeypatch.setattr(real_sys, "stdout", fake_stdout)
        monkeypatch.setattr(real_sys, "stderr", fake_stderr)
        monkeypatch.setattr(real_sys, "platform", "win32")

        # Re-importing the module should NOT raise even though neither
        # stdout nor stderr expose .reconfigure.
        from ufpr_automation.utils import logging as logging_mod
        importlib.reload(logging_mod)

        # Sanity: logger still exists after reload.
        assert isinstance(logging_mod.logger, logging.Logger)


class TestDebugCapture:
    @pytest.mark.asyncio
    async def test_capture_debug_info_writes_expected_files(
        self, mock_page, tmp_path
    ):
        """capture_debug_info should write a screenshot, DOM html, and info json."""
        from ufpr_automation.utils.debug import capture_debug_info

        mock_page.content = AsyncMock(return_value="<html>hello</html>")
        mock_page.title = AsyncMock(return_value="Test Title")
        mock_page.url = "https://example.com/"
        mock_page.screenshot = AsyncMock(return_value=None)

        await capture_debug_info(mock_page, output_dir=tmp_path)

        assert (tmp_path / "inbox_dom.html").exists()
        assert (tmp_path / "page_info.json").exists()
        # Screenshot is written via page.screenshot (mocked) — verify it was called.
        mock_page.screenshot.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_capture_debug_info_writes_page_info_json(
        self, mock_page, tmp_path
    ):
        import json
        from ufpr_automation.utils.debug import capture_debug_info

        mock_page.content = AsyncMock(return_value="<html></html>")
        mock_page.title = AsyncMock(return_value="Titulo")
        mock_page.url = "https://outlook.office.com/"
        mock_page.screenshot = AsyncMock(return_value=None)

        await capture_debug_info(mock_page, output_dir=tmp_path)

        info = json.loads((tmp_path / "page_info.json").read_text(encoding="utf-8"))
        assert info["title"] == "Titulo"
        assert info["url"] == "https://outlook.office.com/"
