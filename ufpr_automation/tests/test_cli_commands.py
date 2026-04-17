"""Tests for ufpr_automation.cli.commands — argparse + dispatch behaviour."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ufpr_automation.cli import commands


class TestParseArgs:
    def test_defaults(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["ufpr_automation"])
        args = commands.parse_args()
        assert args.dry_run is False
        assert args.headed is False
        assert args.debug is False
        assert args.perceber_only is False
        assert args.channel is None
        assert args.langgraph is False
        assert args.schedule is False
        assert args.once is False

    def test_dry_run_flag(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["ufpr_automation", "--dry-run"])
        args = commands.parse_args()
        assert args.dry_run is True

    def test_channel_gmail(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["ufpr_automation", "--channel", "gmail"])
        args = commands.parse_args()
        assert args.channel == "gmail"

    def test_channel_owa(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["ufpr_automation", "--channel", "owa"])
        args = commands.parse_args()
        assert args.channel == "owa"

    def test_channel_invalid_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["ufpr_automation", "--channel", "carrier-pigeon"])
        with pytest.raises(SystemExit):
            commands.parse_args()

    def test_schedule_once(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["ufpr_automation", "--schedule", "--once"])
        args = commands.parse_args()
        assert args.schedule is True
        assert args.once is True

    def test_langgraph_and_headed(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["ufpr_automation", "--langgraph", "--headed"])
        args = commands.parse_args()
        assert args.langgraph is True
        assert args.headed is True

    def test_perceber_only(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["ufpr_automation", "--perceber-only"])
        args = commands.parse_args()
        assert args.perceber_only is True


class TestMainDispatch:
    """Verify commands.main() routes arguments to the correct code path."""

    def test_schedule_once_runs_once_and_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["ufpr_automation", "--schedule", "--once"])

        fake_scheduler = MagicMock()
        fake_scheduler.run_scheduled_pipeline = MagicMock()
        fake_scheduler.start_scheduler = MagicMock()

        with patch.dict("sys.modules", {"ufpr_automation.scheduler": fake_scheduler}):
            commands.main()

        fake_scheduler.run_scheduled_pipeline.assert_called_once_with()
        fake_scheduler.start_scheduler.assert_not_called()

    def test_schedule_daemon_calls_start_scheduler(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["ufpr_automation", "--schedule"])

        fake_scheduler = MagicMock()
        fake_scheduler.run_scheduled_pipeline = MagicMock()
        fake_scheduler.start_scheduler = MagicMock()

        with patch.dict("sys.modules", {"ufpr_automation.scheduler": fake_scheduler}):
            commands.main()

        fake_scheduler.start_scheduler.assert_called_once_with()
        fake_scheduler.run_scheduled_pipeline.assert_not_called()

    def test_dry_run_calls_run_dry_run(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["ufpr_automation", "--dry-run"])

        # Use a completed future-like coroutine replacement.
        fake_coro = AsyncMock()

        with (
            patch.object(commands, "run_dry_run", fake_coro),
            patch.object(commands.asyncio, "run") as mock_run,
        ):
            commands.main()

        # asyncio.run should be called with the dry-run coroutine.
        mock_run.assert_called_once()
        # (We don't care about the exact object — just that dispatch happened.)

    def test_gmail_channel_dispatches_run_gmail(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["ufpr_automation", "--channel", "gmail"])

        with (
            patch.object(commands, "run_gmail_channel") as gmail_mock,
            patch.object(commands.asyncio, "run") as mock_run,
            patch.object(commands, "run_main") as owa_mock,
        ):
            commands.main()

        mock_run.assert_called_once()
        # gmail was invoked (one call), owa was not.
        assert gmail_mock.called
        assert not owa_mock.called

    def test_owa_default_dispatches_run_main(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["ufpr_automation", "--channel", "owa"])

        with (
            patch.object(commands, "run_main") as owa_mock,
            patch.object(commands.asyncio, "run") as mock_run,
            patch.object(commands, "run_gmail_channel") as gmail_mock,
        ):
            commands.main()

        mock_run.assert_called_once()
        assert owa_mock.called
        assert not gmail_mock.called


class TestCliPackageImport:
    def test_cli_package_imports(self):
        """The cli package itself should be importable with no side effects."""
        import ufpr_automation.cli  # noqa: F401

    def test_commands_module_has_main(self):
        assert callable(commands.main)
        assert callable(commands.parse_args)
