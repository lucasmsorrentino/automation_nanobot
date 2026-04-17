"""Tests for agent_sdk/feedback_chat — Feedback Review Chat bootstrap."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from ufpr_automation.agent_sdk.feedback_chat import (
    ChatSession,
    _load_last_run,
    build_bootstrap_prompt,
    prepare_session,
    summarize_last_run,
)


def _entry(hash_="abc123", cat="Estágios", acao="Abrir Processo SEI", conf=0.92, **extra):
    base = {
        "email_hash": hash_,
        "sender": "aluno@ufpr.br",
        "subject": "TCE inicial",
        "body": "segue tce",
        "classification": {
            "categoria": cat,
            "resumo": "r",
            "acao_necessaria": acao,
            "sugestao_resposta": "s",
            "confianca": conf,
        },
    }
    base.update(extra)
    return base


def _write_last_run(path: Path, entries: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# _load_last_run
# ---------------------------------------------------------------------------


class TestLoadLastRun:
    def test_loads_multiple_entries(self, tmp_path):
        p = tmp_path / "last_run.jsonl"
        _write_last_run(p, [_entry("a"), _entry("b")])
        entries = _load_last_run(p)
        assert len(entries) == 2

    def test_missing_returns_empty(self, tmp_path):
        assert _load_last_run(tmp_path / "nope.jsonl") == []


# ---------------------------------------------------------------------------
# summarize_last_run
# ---------------------------------------------------------------------------


class TestSummarize:
    def test_empty_returns_zero_totals(self):
        s = summarize_last_run([])
        assert s["total"] == 0
        assert s["by_categoria"] == {}

    def test_counts_by_categoria(self):
        entries = [
            _entry(cat="Estágios"),
            _entry(cat="Estágios"),
            _entry(cat="Outros"),
        ]
        s = summarize_last_run(entries)
        assert s["total"] == 3
        assert s["by_categoria"]["Estágios"] == 2
        assert s["by_categoria"]["Outros"] == 1

    def test_confidence_buckets(self):
        entries = [
            _entry(conf=0.95),
            _entry(conf=0.70),
            _entry(conf=0.40),
        ]
        s = summarize_last_run(entries)
        buckets = s["confidence_buckets"]
        assert buckets["high"] == 1
        assert buckets["medium"] == 1
        assert buckets["low"] == 1

    def test_counts_by_acao(self):
        entries = [
            _entry(acao="Redigir Resposta"),
            _entry(acao="Abrir Processo SEI"),
            _entry(acao="Redigir Resposta"),
        ]
        s = summarize_last_run(entries)
        assert s["by_acao"]["Redigir Resposta"] == 2


# ---------------------------------------------------------------------------
# build_bootstrap_prompt
# ---------------------------------------------------------------------------


class TestBuildBootstrap:
    def test_contains_briefing_and_summary(self):
        entries = [_entry(cat="Estágios")]
        summary = summarize_last_run(entries)
        prompt = build_bootstrap_prompt(entries, summary)
        # Briefing text markers
        assert "Feedback Review Chat" in prompt or "Briefing" in prompt
        # Summary
        assert "Total de emails" in prompt or "total" in prompt.lower()
        # Email listing
        assert "Estágios" in prompt

    def test_truncates_at_20_emails(self):
        entries = [_entry(hash_=f"id{i}") for i in range(25)]
        summary = summarize_last_run(entries)
        prompt = build_bootstrap_prompt(entries, summary)
        assert "e mais 5 emails" in prompt

    def test_empty_entries_still_builds(self):
        prompt = build_bootstrap_prompt([], summarize_last_run([]))
        assert isinstance(prompt, str)
        assert len(prompt) > 0


# ---------------------------------------------------------------------------
# prepare_session
# ---------------------------------------------------------------------------


class TestPrepareSession:
    def test_creates_session_dir_with_artifacts(self, tmp_path):
        last_run = tmp_path / "last_run.jsonl"
        _write_last_run(last_run, [_entry()])

        session = prepare_session(
            last_run_path=last_run,
            chat_dir=tmp_path / "sessions",
        )

        assert isinstance(session, ChatSession)
        assert session.session_dir.exists()
        assert (session.session_dir / "bootstrap.md").exists()
        assert (session.session_dir / "summary.json").exists()
        assert (session.session_dir / "meta.json").exists()

    def test_meta_contains_run_id_and_timestamp(self, tmp_path):
        last_run = tmp_path / "last_run.jsonl"
        _write_last_run(last_run, [_entry()])

        session = prepare_session(
            last_run_path=last_run,
            chat_dir=tmp_path / "sessions",
        )
        meta = json.loads((session.session_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["run_id"] == session.run_id
        assert "started_at" in meta
        assert meta["total_emails"] == 1

    def test_empty_last_run_still_builds_session(self, tmp_path):
        session = prepare_session(
            last_run_path=tmp_path / "missing.jsonl",
            chat_dir=tmp_path / "sessions",
        )
        assert session.last_run_summary["total"] == 0
        assert session.session_dir.exists()


# ---------------------------------------------------------------------------
# Streamlit independence (regression)
# ---------------------------------------------------------------------------


class TestStreamlitIndependence:
    """Ensures feedback/web.py does not import from agent_sdk/."""

    def test_feedback_web_does_not_import_agent_sdk(self):
        from ufpr_automation.feedback import web

        src = Path(web.__file__).read_text(encoding="utf-8")
        # Must not reference agent_sdk (either by import or string path)
        assert "agent_sdk" not in src, (
            "feedback/web.py must not depend on agent_sdk/ — "
            "Streamlit is the mandatory fallback path when Claude CLI is unavailable"
        )


# ---------------------------------------------------------------------------
# launch_claude — fallback behavior
# ---------------------------------------------------------------------------


class TestLaunchClaude:
    def test_unavailable_claude_returns_exit_2(self, tmp_path, capsys):
        from ufpr_automation.agent_sdk.feedback_chat import launch_claude

        session = prepare_session(
            last_run_path=tmp_path / "missing.jsonl",
            chat_dir=tmp_path / "sessions",
        )

        with patch("ufpr_automation.agent_sdk.runner.is_claude_available", return_value=False):
            exit_code = launch_claude(session)

        assert exit_code == 2
        captured = capsys.readouterr()
        assert "Streamlit" in captured.err
