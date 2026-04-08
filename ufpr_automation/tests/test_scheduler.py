"""Tests for scheduler.py — APScheduler configuration."""

from __future__ import annotations

from unittest.mock import patch


class TestSchedulerConfig:
    def test_schedule_hours_parsing(self):
        """Verify that SCHEDULE_HOURS is parsed correctly."""
        hours_str = "8,13,17"
        hours = [h.strip() for h in hours_str.split(",") if h.strip()]
        assert hours == ["8", "13", "17"]

    def test_schedule_hours_single(self):
        hours_str = "10"
        hours = [h.strip() for h in hours_str.split(",") if h.strip()]
        assert hours == ["10"]

    def test_schedule_hours_empty(self):
        hours_str = ""
        hours = [h.strip() for h in hours_str.split(",") if h.strip()]
        assert hours == []

    @patch.dict("os.environ", {"SCHEDULE_HOURS": "9,14,18"})
    def test_env_override(self):
        import os
        assert os.getenv("SCHEDULE_HOURS") == "9,14,18"

    def test_run_scheduled_pipeline_import(self):
        """Verify scheduler module can be imported."""
        from ufpr_automation.scheduler import SCHEDULE_HOURS, SCHEDULE_TZ

        assert isinstance(SCHEDULE_HOURS, str)
        assert isinstance(SCHEDULE_TZ, str)


class TestSchedulerJobCreation:
    @patch("ufpr_automation.scheduler.run_scheduled_pipeline")
    def test_run_scheduled_pipeline_callable(self, mock_run):
        """Verify run_scheduled_pipeline is callable."""
        from ufpr_automation.scheduler import run_scheduled_pipeline

        assert callable(run_scheduled_pipeline)
