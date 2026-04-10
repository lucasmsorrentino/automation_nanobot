"""Tests for ufpr_automation.outlook.browser — session and credential helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ufpr_automation.outlook import browser as browser_mod


class TestHasCredentials:
    def test_returns_true_when_both_set(self):
        with patch.object(browser_mod, "OWA_EMAIL", "user@ufpr.br"), \
             patch.object(browser_mod, "OWA_PASSWORD", "supersecret"):
            assert browser_mod.has_credentials() is True

    def test_returns_false_when_email_missing(self):
        with patch.object(browser_mod, "OWA_EMAIL", ""), \
             patch.object(browser_mod, "OWA_PASSWORD", "supersecret"):
            assert browser_mod.has_credentials() is False

    def test_returns_false_when_password_missing(self):
        with patch.object(browser_mod, "OWA_EMAIL", "user@ufpr.br"), \
             patch.object(browser_mod, "OWA_PASSWORD", ""):
            assert browser_mod.has_credentials() is False

    def test_returns_false_when_both_empty(self):
        with patch.object(browser_mod, "OWA_EMAIL", ""), \
             patch.object(browser_mod, "OWA_PASSWORD", ""):
            assert browser_mod.has_credentials() is False


class TestHasSavedSession:
    def test_returns_false_when_file_does_not_exist(self, tmp_path):
        fake_state = tmp_path / "state.json"
        with patch.object(browser_mod, "SESSION_STATE_FILE", fake_state):
            assert browser_mod.has_saved_session() is False

    def test_returns_false_when_file_empty(self, tmp_path):
        fake_state = tmp_path / "state.json"
        fake_state.write_text("", encoding="utf-8")
        with patch.object(browser_mod, "SESSION_STATE_FILE", fake_state):
            assert browser_mod.has_saved_session() is False

    def test_returns_true_when_file_non_empty(self, tmp_path):
        fake_state = tmp_path / "state.json"
        fake_state.write_text('{"cookies": []}', encoding="utf-8")
        with patch.object(browser_mod, "SESSION_STATE_FILE", fake_state):
            assert browser_mod.has_saved_session() is True


class TestIsLoggedIn:
    @pytest.mark.asyncio
    async def test_login_page_url_returns_false(self, mock_page):
        mock_page.url = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
        assert await browser_mod.is_logged_in(mock_page) is False

    @pytest.mark.asyncio
    async def test_live_login_url_returns_false(self, mock_page):
        mock_page.url = "https://login.live.com/login"
        assert await browser_mod.is_logged_in(mock_page) is False

    @pytest.mark.asyncio
    async def test_inbox_url_with_visible_selector_returns_true(self, mock_page):
        mock_page.url = "https://outlook.office.com/mail/inbox"
        mock_page.wait_for_selector = AsyncMock(return_value=object())
        assert await browser_mod.is_logged_in(mock_page) is True

    @pytest.mark.asyncio
    async def test_inbox_url_without_any_selector_returns_false(self, mock_page):
        mock_page.url = "https://outlook.office.com/mail/inbox"
        mock_page.wait_for_selector = AsyncMock(side_effect=Exception("timeout"))
        assert await browser_mod.is_logged_in(mock_page) is False


class TestSendTelegramNotification:
    @pytest.mark.asyncio
    async def test_no_token_is_noop(self, capsys):
        with patch.object(browser_mod, "TELEGRAM_BOT_TOKEN", ""), \
             patch.object(browser_mod, "TELEGRAM_CHAT_ID", ""):
            # Should not raise and should print a warning instead.
            await browser_mod._send_telegram_notification("hello")
        out = capsys.readouterr().out
        assert "Telegram" in out
