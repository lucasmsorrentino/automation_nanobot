"""Tests for llm/router.py — Model cascading and fallback logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ufpr_automation.llm.router import (
    TaskType,
    _build_model_chain,
    _is_retriable_error,
    get_fallback_model,
    get_model,
    is_cascading_enabled,
)


class TestModelSelection:
    """Test model selection based on task type and config."""

    @patch("ufpr_automation.llm.router.settings")
    def test_no_cascading_returns_default(self, mock_settings):
        mock_settings.LLM_MODEL = "minimax/MiniMax-M2"
        mock_settings.LLM_CLASSIFY_MODEL = ""
        mock_settings.LLM_DRAFT_MODEL = ""
        mock_settings.LLM_FALLBACK_MODEL = ""

        assert get_model(TaskType.CLASSIFY) == "minimax/MiniMax-M2"
        assert get_model(TaskType.DRAFT) == "minimax/MiniMax-M2"
        assert get_model(TaskType.CRITIQUE) == "minimax/MiniMax-M2"
        assert get_model(TaskType.REFINE) == "minimax/MiniMax-M2"

    @patch("ufpr_automation.llm.router.settings")
    def test_classify_model_override(self, mock_settings):
        mock_settings.LLM_MODEL = "minimax/MiniMax-M2"
        mock_settings.LLM_CLASSIFY_MODEL = "ollama/qwen3:8b"
        mock_settings.LLM_DRAFT_MODEL = ""
        mock_settings.LLM_FALLBACK_MODEL = ""

        assert get_model(TaskType.CLASSIFY) == "ollama/qwen3:8b"
        assert get_model(TaskType.DRAFT) == "minimax/MiniMax-M2"

    @patch("ufpr_automation.llm.router.settings")
    def test_draft_model_override(self, mock_settings):
        mock_settings.LLM_MODEL = "minimax/MiniMax-M2"
        mock_settings.LLM_CLASSIFY_MODEL = ""
        mock_settings.LLM_DRAFT_MODEL = "openai/gpt-4o"

        assert get_model(TaskType.CLASSIFY) == "minimax/MiniMax-M2"
        assert get_model(TaskType.DRAFT) == "openai/gpt-4o"
        assert get_model(TaskType.CRITIQUE) == "openai/gpt-4o"
        assert get_model(TaskType.REFINE) == "openai/gpt-4o"

    @patch("ufpr_automation.llm.router.settings")
    def test_both_overrides(self, mock_settings):
        mock_settings.LLM_MODEL = "minimax/MiniMax-M2"
        mock_settings.LLM_CLASSIFY_MODEL = "ollama/qwen3:8b"
        mock_settings.LLM_DRAFT_MODEL = "openai/gpt-4o"

        assert get_model(TaskType.CLASSIFY) == "ollama/qwen3:8b"
        assert get_model(TaskType.DRAFT) == "openai/gpt-4o"


class TestFallbackChain:
    """Test fallback model chain construction."""

    @patch("ufpr_automation.llm.router.settings")
    def test_no_fallback_configured(self, mock_settings):
        mock_settings.LLM_MODEL = "minimax/MiniMax-M2"
        mock_settings.LLM_CLASSIFY_MODEL = ""
        mock_settings.LLM_DRAFT_MODEL = ""
        mock_settings.LLM_FALLBACK_MODEL = ""

        chain = _build_model_chain(TaskType.CLASSIFY)
        assert chain == ["minimax/MiniMax-M2"]

    @patch("ufpr_automation.llm.router.settings")
    def test_override_falls_back_to_default(self, mock_settings):
        mock_settings.LLM_MODEL = "minimax/MiniMax-M2"
        mock_settings.LLM_CLASSIFY_MODEL = "ollama/qwen3:8b"
        mock_settings.LLM_DRAFT_MODEL = ""
        mock_settings.LLM_FALLBACK_MODEL = ""

        chain = _build_model_chain(TaskType.CLASSIFY)
        assert chain == ["ollama/qwen3:8b", "minimax/MiniMax-M2"]

    @patch("ufpr_automation.llm.router.settings")
    def test_full_chain_with_explicit_fallback(self, mock_settings):
        mock_settings.LLM_MODEL = "minimax/MiniMax-M2"
        mock_settings.LLM_CLASSIFY_MODEL = "ollama/qwen3:8b"
        mock_settings.LLM_DRAFT_MODEL = ""
        mock_settings.LLM_FALLBACK_MODEL = "deepseek/deepseek-chat"

        chain = _build_model_chain(TaskType.CLASSIFY)
        assert chain == ["ollama/qwen3:8b", "minimax/MiniMax-M2", "deepseek/deepseek-chat"]

    @patch("ufpr_automation.llm.router.settings")
    def test_no_duplicates_in_chain(self, mock_settings):
        mock_settings.LLM_MODEL = "minimax/MiniMax-M2"
        mock_settings.LLM_CLASSIFY_MODEL = ""
        mock_settings.LLM_DRAFT_MODEL = ""
        mock_settings.LLM_FALLBACK_MODEL = "minimax/MiniMax-M2"

        chain = _build_model_chain(TaskType.CLASSIFY)
        assert chain == ["minimax/MiniMax-M2"]


class TestCascadingEnabled:
    """Test is_cascading_enabled detection."""

    @patch("ufpr_automation.llm.router.settings")
    def test_disabled_when_no_overrides(self, mock_settings):
        mock_settings.LLM_CLASSIFY_MODEL = ""
        mock_settings.LLM_DRAFT_MODEL = ""
        assert not is_cascading_enabled()

    @patch("ufpr_automation.llm.router.settings")
    def test_enabled_with_classify_override(self, mock_settings):
        mock_settings.LLM_CLASSIFY_MODEL = "ollama/qwen3:8b"
        mock_settings.LLM_DRAFT_MODEL = ""
        assert is_cascading_enabled()


class TestRetriableErrors:
    """Test error classification for retry logic."""

    def test_timeout_is_retriable(self):
        assert _is_retriable_error(Exception("Connection timeout after 30s"))

    def test_rate_limit_is_retriable(self):
        assert _is_retriable_error(Exception("Rate limit exceeded (429)"))

    def test_503_is_retriable(self):
        assert _is_retriable_error(Exception("Service unavailable 503"))

    def test_connection_refused_is_retriable(self):
        assert _is_retriable_error(Exception("Connection refused"))

    def test_auth_error_is_not_retriable(self):
        assert not _is_retriable_error(Exception("Invalid API key (401)"))

    def test_validation_error_is_not_retriable(self):
        assert not _is_retriable_error(Exception("JSON parse error"))
