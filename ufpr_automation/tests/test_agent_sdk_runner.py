"""Tests for agent_sdk/runner.py — Claude CLI subprocess wrapper."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from ufpr_automation.agent_sdk.runner import (
    ClaudeRunResult,
    is_claude_available,
    run_claude_oneshot,
)


@pytest.fixture(autouse=True)
def _redirect_audit(monkeypatch, tmp_path):
    """Route all audit writes to tmp_path so tests don't pollute the real dir."""
    monkeypatch.setattr(
        "ufpr_automation.agent_sdk.runner.AGENT_SDK_DIR", tmp_path / "agent_sdk"
    )


class TestClaudeRunResult:
    def test_dataclass_defaults(self):
        r = ClaudeRunResult(
            success=True, task="test", run_id="abc",
            started_at="2026-01-01T00:00:00", duration_s=1.5, prompt_chars=100,
        )
        assert r.output_text == ""
        assert r.output_json is None
        assert r.artifacts == []
        assert r.error is None
        assert r.exit_code == 0


class TestIsClaudeAvailable:
    def test_returns_true_when_claude_in_path(self):
        with patch("ufpr_automation.agent_sdk.runner.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert is_claude_available() is True

    def test_returns_false_when_not_found(self):
        with patch(
            "ufpr_automation.agent_sdk.runner.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            assert is_claude_available() is False

    def test_returns_false_on_timeout(self):
        with patch(
            "ufpr_automation.agent_sdk.runner.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=10),
        ):
            assert is_claude_available() is False


class TestRunClaudeOneshot:
    def test_dry_run_does_not_call_subprocess(self, tmp_path):
        result = run_claude_oneshot(
            task="test_task",
            prompt="Hello, test!",
            dry_run=True,
        )
        assert result.success is True
        assert result.output_text == "[DRY_RUN]"
        assert result.duration_s == 0.0
        assert result.prompt_chars == len("Hello, test!")
        assert len(result.artifacts) == 1
        assert result.artifacts[0].name == "prompt.md"
        assert result.artifacts[0].read_text(encoding="utf-8") == "Hello, test!"

    def test_successful_text_invocation(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Claude says hello"
        mock_proc.stderr = ""

        with patch("ufpr_automation.agent_sdk.runner.subprocess.run", return_value=mock_proc):
            result = run_claude_oneshot(
                task="greet",
                prompt="Say hello",
            )
        assert result.success is True
        assert result.output_text == "Claude says hello"
        assert result.exit_code == 0
        assert len(result.artifacts) == 3  # prompt.md, stdout.txt, stderr.txt

    def test_successful_json_invocation(self, tmp_path):
        payload = {"categoria": "Estágios", "confidence": 0.95}
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps(payload)
        mock_proc.stderr = ""

        with patch("ufpr_automation.agent_sdk.runner.subprocess.run", return_value=mock_proc):
            result = run_claude_oneshot(
                task="classify",
                prompt="Classify this",
                output_format="json",
            )
        assert result.success is True
        assert result.output_json == payload

    def test_timeout_returns_failure(self, tmp_path):
        with patch(
            "ufpr_automation.agent_sdk.runner.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=60),
        ):
            result = run_claude_oneshot(
                task="slow",
                prompt="Takes too long",
                timeout_s=60,
            )
        assert result.success is False
        assert "timeout" in result.error

    def test_claude_not_found_returns_failure(self, tmp_path):
        with patch(
            "ufpr_automation.agent_sdk.runner.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = run_claude_oneshot(
                task="missing",
                prompt="No claude",
            )
        assert result.success is False
        assert "not found" in result.error

    def test_nonzero_exit_code_is_failure(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = "Error: quota exceeded"
        mock_proc.stderr = "rate limit"

        with patch("ufpr_automation.agent_sdk.runner.subprocess.run", return_value=mock_proc):
            result = run_claude_oneshot(
                task="limited",
                prompt="Try this",
            )
        assert result.success is False
        assert result.exit_code == 1
        assert result.stderr == "rate limit"

    def test_invalid_json_output_still_succeeds(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "not valid json {{"
        mock_proc.stderr = ""

        with patch("ufpr_automation.agent_sdk.runner.subprocess.run", return_value=mock_proc):
            result = run_claude_oneshot(
                task="bad_json",
                prompt="Give me json",
                output_format="json",
            )
        assert result.success is True
        assert result.output_json is None  # parse failed gracefully
        assert result.output_text == "not valid json {{"

    def test_extra_args_forwarded(self, tmp_path):
        mock_proc = MagicMock(returncode=0, stdout="ok", stderr="")

        with patch("ufpr_automation.agent_sdk.runner.subprocess.run", return_value=mock_proc) as mock_run:
            run_claude_oneshot(
                task="custom",
                prompt="test",
                extra_args=["--model", "opus"],
            )
        call_args = mock_run.call_args
        argv = call_args[0][0]
        assert "--model" in argv
        assert "opus" in argv


class TestAuditTrail:
    def test_dry_run_writes_prompt_file(self, tmp_path):
        result = run_claude_oneshot(
            task="audit_test",
            prompt="Audit me",
            dry_run=True,
        )
        prompt_file = result.artifacts[0]
        assert prompt_file.exists()
        assert prompt_file.read_text(encoding="utf-8") == "Audit me"

    def test_live_run_writes_audit_jsonl(self, tmp_path):
        mock_proc = MagicMock(returncode=0, stdout="done", stderr="")

        with patch("ufpr_automation.agent_sdk.runner.subprocess.run", return_value=mock_proc):
            run_claude_oneshot(task="jsonl_test", prompt="Log me")

        audit_path = tmp_path / "agent_sdk" / "audit.jsonl"
        assert audit_path.exists()
        lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) >= 1
        record = json.loads(lines[-1])
        assert record["task"] == "jsonl_test"
        assert record["success"] is True

    def test_stdout_stderr_files_written(self, tmp_path):
        mock_proc = MagicMock(returncode=0, stdout="output here", stderr="warn here")

        with patch("ufpr_automation.agent_sdk.runner.subprocess.run", return_value=mock_proc):
            result = run_claude_oneshot(task="files_test", prompt="test")

        stdout_file = next(p for p in result.artifacts if p.name == "stdout.txt")
        stderr_file = next(p for p in result.artifacts if p.name == "stderr.txt")
        assert stdout_file.read_text(encoding="utf-8") == "output here"
        assert stderr_file.read_text(encoding="utf-8") == "warn here"
