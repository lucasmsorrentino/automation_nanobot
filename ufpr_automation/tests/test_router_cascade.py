"""Tests for llm/router.py — cascaded_completion and cascaded_completion_sync.

Extends test_router.py with tests for the actual cascading call logic
(retries, fallback between models, retriable vs non-retriable errors).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ufpr_automation.llm.router import (
    TaskType,
    cascaded_completion,
    cascaded_completion_sync,
    log_cascade_config,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(text: str = "response") -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = text
    return resp


def _settings(**overrides):
    """Create mock settings with sensible defaults."""
    defaults = {
        "LLM_MODEL": "minimax/MiniMax-M2",
        "LLM_CLASSIFY_MODEL": "",
        "LLM_DRAFT_MODEL": "",
        "LLM_FALLBACK_MODEL": "",
        "LLM_CASCADE_RETRIES": 2,
        "LLM_TIMEOUT_SECONDS": 120,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


MESSAGES = [{"role": "user", "content": "test prompt"}]


# ===========================================================================
# cascaded_completion (async)
# ===========================================================================


class TestCascadedCompletion:
    @pytest.mark.asyncio
    async def test_success_on_first_try(self):
        expected = _mock_response("ok")

        with patch("ufpr_automation.llm.router.settings", _settings()):
            with patch("litellm.acompletion", new_callable=AsyncMock, return_value=expected):
                result = await cascaded_completion(
                    TaskType.CLASSIFY, messages=MESSAGES,
                )

        assert result == expected

    @pytest.mark.asyncio
    async def test_retries_on_retriable_error(self):
        expected = _mock_response("ok")

        with patch("ufpr_automation.llm.router.settings", _settings(LLM_CASCADE_RETRIES=3)):
            with patch(
                "litellm.acompletion",
                new_callable=AsyncMock,
                side_effect=[
                    Exception("Connection timeout"),
                    Exception("Connection timeout"),
                    expected,
                ],
            ) as mock_ac:
                result = await cascaded_completion(
                    TaskType.CLASSIFY, messages=MESSAGES,
                )

        assert result == expected
        assert mock_ac.call_count == 3

    @pytest.mark.asyncio
    async def test_falls_back_to_next_model(self):
        expected = _mock_response("fallback ok")

        with patch(
            "ufpr_automation.llm.router.settings",
            _settings(LLM_CLASSIFY_MODEL="ollama/qwen3:8b", LLM_CASCADE_RETRIES=1),
        ):
            with patch(
                "litellm.acompletion",
                new_callable=AsyncMock,
                side_effect=[
                    Exception("Connection refused"),  # ollama down
                    expected,  # fallback to MiniMax
                ],
            ) as mock_ac:
                result = await cascaded_completion(
                    TaskType.CLASSIFY, messages=MESSAGES,
                )

        assert result == expected
        assert mock_ac.call_count == 2
        calls = mock_ac.call_args_list
        assert calls[0][1]["model"] == "ollama/qwen3:8b"
        assert calls[1][1]["model"] == "minimax/MiniMax-M2"

    @pytest.mark.asyncio
    async def test_non_retriable_skips_retries(self):
        """Non-retriable errors skip remaining retries for the current model."""
        with patch(
            "ufpr_automation.llm.router.settings",
            _settings(LLM_CLASSIFY_MODEL="ollama/qwen3:8b", LLM_CASCADE_RETRIES=3),
        ):
            with patch(
                "litellm.acompletion",
                new_callable=AsyncMock,
                side_effect=[
                    Exception("Invalid API key (401)"),  # non-retriable
                    _mock_response("ok"),  # fallback succeeds
                ],
            ) as mock_ac:
                result = await cascaded_completion(
                    TaskType.CLASSIFY, messages=MESSAGES,
                )

        # Should NOT have retried the primary model (only 1 attempt)
        assert mock_ac.call_count == 2

    @pytest.mark.asyncio
    async def test_raises_when_all_fail(self):
        with patch(
            "ufpr_automation.llm.router.settings",
            _settings(LLM_CASCADE_RETRIES=1),
        ):
            with patch(
                "litellm.acompletion",
                new_callable=AsyncMock,
                side_effect=Exception("Connection refused"),
            ):
                with pytest.raises(Exception, match="Connection refused"):
                    await cascaded_completion(
                        TaskType.CLASSIFY, messages=MESSAGES,
                    )

    @pytest.mark.asyncio
    async def test_full_chain_with_fallback_model(self):
        """Test 3-model chain: primary -> default -> fallback."""
        expected = _mock_response("last resort")

        with patch(
            "ufpr_automation.llm.router.settings",
            _settings(
                LLM_CLASSIFY_MODEL="ollama/qwen3:8b",
                LLM_FALLBACK_MODEL="deepseek/deepseek-chat",
                LLM_CASCADE_RETRIES=1,
            ),
        ):
            with patch(
                "litellm.acompletion",
                new_callable=AsyncMock,
                side_effect=[
                    Exception("Connection refused"),  # ollama
                    Exception("Rate limit exceeded (429)"),  # minimax
                    expected,  # deepseek
                ],
            ) as mock_ac:
                result = await cascaded_completion(
                    TaskType.CLASSIFY, messages=MESSAGES,
                )

        assert result == expected
        calls = mock_ac.call_args_list
        assert calls[0][1]["model"] == "ollama/qwen3:8b"
        assert calls[1][1]["model"] == "minimax/MiniMax-M2"
        assert calls[2][1]["model"] == "deepseek/deepseek-chat"


# ===========================================================================
# cascaded_completion_sync
# ===========================================================================


class TestCascadedCompletionSync:
    def test_success_on_first_try(self):
        expected = _mock_response("ok")

        with patch("ufpr_automation.llm.router.settings", _settings()):
            with patch("litellm.completion", return_value=expected):
                result = cascaded_completion_sync(
                    TaskType.DRAFT, messages=MESSAGES,
                )

        assert result == expected

    def test_falls_back_on_failure(self):
        expected = _mock_response("fallback")

        with patch(
            "ufpr_automation.llm.router.settings",
            _settings(LLM_DRAFT_MODEL="openai/gpt-4o", LLM_CASCADE_RETRIES=1),
        ):
            with patch(
                "litellm.completion",
                side_effect=[
                    Exception("Service unavailable 503"),
                    expected,
                ],
            ):
                result = cascaded_completion_sync(
                    TaskType.DRAFT, messages=MESSAGES,
                )

        assert result == expected

    def test_raises_when_all_fail(self):
        with patch(
            "ufpr_automation.llm.router.settings",
            _settings(LLM_CASCADE_RETRIES=1),
        ):
            with patch(
                "litellm.completion",
                side_effect=Exception("total failure"),
            ):
                with pytest.raises(Exception, match="total failure"):
                    cascaded_completion_sync(
                        TaskType.DRAFT, messages=MESSAGES,
                    )

    def test_non_retriable_skips_to_next_model(self):
        expected = _mock_response("ok")

        with patch(
            "ufpr_automation.llm.router.settings",
            _settings(LLM_DRAFT_MODEL="openai/gpt-4o", LLM_CASCADE_RETRIES=3),
        ):
            with patch(
                "litellm.completion",
                side_effect=[
                    Exception("JSON parse error"),  # non-retriable
                    expected,
                ],
            ) as mock_c:
                result = cascaded_completion_sync(
                    TaskType.DRAFT, messages=MESSAGES,
                )

        assert result == expected
        # Only 1 attempt on primary (non-retriable), then fallback
        assert mock_c.call_count == 2


# ===========================================================================
# log_cascade_config
# ===========================================================================


class TestLogCascadeConfig:
    def test_logs_disabled_when_no_overrides(self):
        with (
            patch("ufpr_automation.llm.router.settings", _settings()),
            patch("ufpr_automation.llm.router.logger") as mock_logger,
        ):
            log_cascade_config()

        mock_logger.info.assert_called()
        call_str = str(mock_logger.info.call_args_list[0])
        assert "disabled" in call_str.lower() or "single model" in call_str.lower()

    def test_logs_enabled_when_overrides_set(self):
        with (
            patch(
                "ufpr_automation.llm.router.settings",
                _settings(LLM_CLASSIFY_MODEL="ollama/qwen3:8b"),
            ),
            patch("ufpr_automation.llm.router.logger") as mock_logger,
        ):
            log_cascade_config()

        mock_logger.info.assert_called()
        call_str = str(mock_logger.info.call_args_list[0])
        assert "enabled" in call_str.lower()
