"""Tests for ufpr_automation.notify.telegram — run-summary formatting and HTTP."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
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

    def _make_email(self, sid, subject, categoria, acao, conf):
        """Build a duck-typed email stub accepted by format_run_summary."""
        cls = SimpleNamespace(categoria=categoria, acao_necessaria=acao, confianca=conf)
        return SimpleNamespace(stable_id=sid, subject=subject, classification=cls)

    def test_langgraph_state_shape(self):
        emails = [
            self._make_email("id0", "Urgente: prazo amanhã", "Urgente", "Agir já", 0.95),
            self._make_email(
                "id1",
                "Re: Termo de Estágio para assinatura",
                "Estágios",
                "Revisar anexos e abrir processo SEI",
                0.92,
            ),
            self._make_email(
                "id2", "Matrícula equivalência", "Acadêmico / Matrícula", "Arquivar", 0.8
            ),
            self._make_email(
                "id3", "Requerimento diverso", "Requerimentos", "Redigir resposta", 0.6
            ),
            self._make_email("id4", "Outros assuntos", "Outros", "Human review", 0.55),
        ]
        classifications = {e.stable_id: e.classification for e in emails}
        state = {
            "emails": emails,
            "classifications": classifications,
            "tier0_hits": ["id0", "id1"],
            "auto_draft": ["id1"],
            "human_review": ["id3", "id4"],
            "manual_escalation": [],
            "drafts_saved": ["id1"],
            "drafts_skipped_already_replied": ["id2"],
            "corpus_captured": [{"thread_id": "t1"}],
            "procedures_logged": 3,
            "sei_operations": [
                {"stable_id": "id1", "op": "attach_document", "success": True},
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
        assert "⚡ Tier 0 (playbook): 2" in text
        assert "🧠 Tier 1 (RAG+LLM): 3" in text
        assert "🔴 1 urgente(s)" in text
        assert "👁️ 2 revisão" in text
        assert "⚠️ 0 escalação" in text
        assert "✅ Rascunhos salvos: 1" in text
        assert "Já respondidos pela humana: 1" in text
        assert "Threads no corpus: 1" in text
        assert "SEI ops: 1 ok / 1 falha" in text
        assert "Procedimentos: 3" in text
        assert "🔴 Erros: 1" in text
        assert "agir_estagios" in text
        # Per-email digest present and the urgent one sorts first.
        assert "— Detalhes —" in text
        assert "🔴 URGENTE" in text
        urgent_idx = text.index("🔴 URGENTE")
        review_idx = text.index("👁️ Revisão")
        assert urgent_idx < review_idx, "urgent email should render before review bucket"
        assert "🤖 Auto-draft" in text
        assert "⏭️ Já respondido" in text

    def test_digest_caps_long_lists(self):
        emails = [
            self._make_email(f"id{i}", f"Email {i}", "Outros", f"ação {i}", 0.5) for i in range(25)
        ]
        state = {
            "emails": emails,
            "classifications": {e.stable_id: e.classification for e in emails},
            "human_review": [e.stable_id for e in emails],
        }
        text = tg.format_run_summary(
            state,
            duration_s=10,
            start_time=self._start(),
            channel="gmail",
        )
        assert "e mais 10 email(s) não exibido(s)" in text

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
