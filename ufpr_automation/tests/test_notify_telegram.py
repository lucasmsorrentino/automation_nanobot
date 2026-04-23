"""Tests for ufpr_automation.notify.telegram — run-summary formatting and HTTP."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from ufpr_automation.notify import telegram as tg


class TestFormatDuration:
    def test_seconds_only(self):
        assert tg._format_duration(45) == "45s"

    def test_minutes_and_seconds(self):
        assert tg._format_duration(125) == "2m05s"

    def test_hours(self):
        assert tg._format_duration(3665) == "1h01m"


class TestFormatRunSummary:
    def _start(self):
        return datetime(2026, 4, 23, 8, 0, 0)

    def test_error_path_short_circuits_state(self):
        text = tg.format_run_summary(
            None,
            duration_s=42,
            start_time=self._start(),
            channel="gmail",
            error="ConnectionError: gmail timed out",
        )
        assert "🔴" in text
        assert "falhou" in text
        assert "gmail" in text
        assert "ConnectionError" in text

    def test_langgraph_state_shape(self):
        state = {
            "emails": [object()] * 5,
            "classifications": {f"id{i}": object() for i in range(5)},
            "tier0_hits": ["id0", "id1", "id2"],
            "drafts_saved": ["id3", "id4"],
            "drafts_skipped_already_replied": ["id0"],
            "corpus_captured": [{"thread_id": "t1"}],
            "procedures_logged": 3,
            "sei_operations": [
                {"stable_id": "id3", "op": "attach_document", "success": True},
                {"stable_id": "id4", "op": "error", "error": "boom"},
            ],
            "errors": [{"node": "agir_estagios", "stable_id": "id4", "error": "boom"}],
        }
        text = tg.format_run_summary(
            state,
            duration_s=204,
            start_time=self._start(),
            channel="gmail",
        )
        assert "UFPR Automation" in text
        assert "📧 5 email" in text
        assert "⚡ Tier 0 (playbook): 3" in text
        assert "🧠 Tier 1 (RAG+LLM): 2" in text
        assert "✅ Rascunhos salvos: 2" in text
        assert "Já respondidos pela humana: 1" in text
        assert "Threads no corpus: 1" in text
        assert "SEI ops: 1 ok / 1 falha" in text
        assert "Procedimentos registrados: 3" in text
        assert "🔴 Erros: 1" in text
        assert "agir_estagios" in text

    def test_orchestrator_state_shape(self):
        state = {
            "total_unread": 4,
            "classified": 4,
            "drafts_saved": 4,
            "emails": [],
        }
        text = tg.format_run_summary(
            state,
            duration_s=30,
            start_time=self._start(),
            channel="gmail",
        )
        assert "📧 4 email" in text
        assert "✅ Rascunhos salvos: 4" in text
        assert "🟢 Sem erros" in text

    def test_empty_state_renders_cleanly(self):
        text = tg.format_run_summary(
            {},
            duration_s=1,
            start_time=self._start(),
            channel="owa",
        )
        assert "📧 0 email" in text
        assert "owa" in text
        assert "🟢 Sem erros" in text


class TestSendMessage:
    def test_noop_when_unconfigured(self):
        with (
            patch.object(tg.settings, "TELEGRAM_BOT_TOKEN", ""),
            patch.object(tg.settings, "TELEGRAM_CHAT_ID", ""),
        ):
            assert tg.send_message("hello") is False

    def test_posts_to_telegram_api_when_configured(self):
        fake_resp = MagicMock()
        fake_resp.__enter__ = lambda self: self
        fake_resp.__exit__ = lambda self, *a: None
        fake_resp.read.return_value = b'{"ok": true, "result": {}}'

        with (
            patch.object(tg.settings, "TELEGRAM_BOT_TOKEN", "TOKEN"),
            patch.object(tg.settings, "TELEGRAM_CHAT_ID", "42"),
            patch(
                "ufpr_automation.notify.telegram.urllib.request.urlopen", return_value=fake_resp
            ) as mock_open,
        ):
            ok = tg.send_message("hello")
        assert ok is True
        call_args = mock_open.call_args
        req = call_args[0][0]
        assert "botTOKEN/sendMessage" in req.full_url
        body = req.data.decode("utf-8")
        assert "chat_id=42" in body
        assert "text=hello" in body

    def test_swallows_http_errors(self):
        with (
            patch.object(tg.settings, "TELEGRAM_BOT_TOKEN", "TOKEN"),
            patch.object(tg.settings, "TELEGRAM_CHAT_ID", "42"),
            patch(
                "ufpr_automation.notify.telegram.urllib.request.urlopen",
                side_effect=OSError("network down"),
            ),
        ):
            assert tg.send_message("hello") is False

    def test_returns_false_when_api_reports_not_ok(self):
        fake_resp = MagicMock()
        fake_resp.__enter__ = lambda self: self
        fake_resp.__exit__ = lambda self, *a: None
        fake_resp.read.return_value = b'{"ok": false, "description": "chat not found"}'

        with (
            patch.object(tg.settings, "TELEGRAM_BOT_TOKEN", "TOKEN"),
            patch.object(tg.settings, "TELEGRAM_CHAT_ID", "42"),
            patch("ufpr_automation.notify.telegram.urllib.request.urlopen", return_value=fake_resp),
        ):
            assert tg.send_message("hello") is False


class TestNotifyRunSummary:
    def test_delegates_to_send_message(self):
        with patch("ufpr_automation.notify.telegram.send_message", return_value=True) as mock_send:
            ok = tg.notify_run_summary(
                {"emails": [], "drafts_saved": []},
                duration_s=5,
                start_time=datetime(2026, 4, 23),
                channel="gmail",
            )
        assert ok is True
        text_arg = mock_send.call_args[0][0]
        assert "UFPR Automation" in text_arg

    def test_never_raises_on_format_error(self):
        with patch(
            "ufpr_automation.notify.telegram.format_run_summary",
            side_effect=RuntimeError("bad state"),
        ):
            assert (
                tg.notify_run_summary(
                    {},
                    duration_s=0,
                    start_time=datetime(2026, 4, 23),
                    channel="gmail",
                )
                is False
            )
