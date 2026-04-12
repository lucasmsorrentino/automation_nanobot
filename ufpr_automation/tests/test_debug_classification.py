"""Tests for agent_sdk/debug_classification — Classification Debugger."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ufpr_automation.agent_sdk.debug_classification import (
    DebugTrace,
    _generate_proposals,
    _load_last_run,
    debug_email,
    format_report,
    run_debug,
)


def _write_last_run(path: Path, entries: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


SAMPLE_ENTRY = {
    "email_hash": "abc123def456",
    "sender": "João <joao@ufpr.br>",
    "subject": "TCE inicial do aluno",
    "body": "Segue TCE inicial do aluno João Silva para estágio não obrigatório",
    "classification": {
        "categoria": "Estágios",
        "resumo": "TCE inicial",
        "acao_necessaria": "Abrir Processo SEI",
        "sugestao_resposta": "Processo aberto.",
        "confianca": 0.92,
    },
}


# ---------------------------------------------------------------------------
# _load_last_run
# ---------------------------------------------------------------------------

class TestLoadLastRun:
    def test_loads_entries(self, tmp_path):
        p = tmp_path / "last_run.jsonl"
        _write_last_run(p, [SAMPLE_ENTRY])
        entries = _load_last_run(p)
        assert "abc123def456" in entries
        assert entries["abc123def456"]["subject"] == "TCE inicial do aluno"

    def test_missing_file_returns_empty(self, tmp_path):
        assert _load_last_run(tmp_path / "nope.jsonl") == {}

    def test_skips_bad_lines(self, tmp_path):
        p = tmp_path / "last_run.jsonl"
        p.write_text('{"email_hash":"ok"}\nnot json\n{"email_hash":"ok2"}\n', encoding="utf-8")
        entries = _load_last_run(p)
        assert len(entries) == 2


# ---------------------------------------------------------------------------
# debug_email
# ---------------------------------------------------------------------------

class TestDebugEmail:
    def test_with_entry_in_last_run(self, tmp_path):
        p = tmp_path / "last_run.jsonl"
        _write_last_run(p, [SAMPLE_ENTRY])

        with patch("ufpr_automation.agent_sdk.debug_classification.replay_tier0") as mock_t0, \
             patch("ufpr_automation.agent_sdk.debug_classification._load_procedure_records", return_value=[]), \
             patch("ufpr_automation.agent_sdk.debug_classification._load_feedback_for", return_value=None):
            mock_t0.return_value = {
                "match": True,
                "intent_name": "estagio_tce_inicial",
                "score": 0.95,
                "method": "keyword",
                "matched_keywords": ["TCE inicial"],
                "stale": False,
            }
            trace = debug_email("abc123def456", last_run_path=p)

        assert trace.stable_id == "abc123def456"
        assert trace.email_subject == "TCE inicial do aluno"
        assert trace.tier0_match is True
        assert trace.tier0_intent_name == "estagio_tce_inicial"
        assert trace.pipeline_categoria == "Estágios"

    def test_missing_entry_returns_empty_trace(self, tmp_path):
        p = tmp_path / "last_run.jsonl"
        p.write_text("", encoding="utf-8")

        with patch("ufpr_automation.agent_sdk.debug_classification._load_procedure_records", return_value=[]), \
             patch("ufpr_automation.agent_sdk.debug_classification._load_feedback_for", return_value=None):
            trace = debug_email("nonexistent", last_run_path=p)

        assert trace.stable_id == "nonexistent"
        assert trace.email_subject == ""
        assert trace.tier0_match is False

    def test_with_correction(self, tmp_path):
        p = tmp_path / "last_run.jsonl"
        _write_last_run(p, [SAMPLE_ENTRY])

        correction = {
            "original_cat": "Estágios",
            "corrected_cat": "Acadêmico / Matrícula",
            "notes": "Não era estágio, era matrícula",
        }

        with patch("ufpr_automation.agent_sdk.debug_classification.replay_tier0",
                    return_value={"match": False, "reason": "no match"}), \
             patch("ufpr_automation.agent_sdk.debug_classification._load_procedure_records", return_value=[]), \
             patch("ufpr_automation.agent_sdk.debug_classification._load_feedback_for",
                    return_value=correction):
            trace = debug_email("abc123def456", last_run_path=p)

        assert trace.has_correction is True
        assert trace.corrected_categoria == "Acadêmico / Matrícula"
        assert trace.correction_notes == "Não era estágio, era matrícula"


# ---------------------------------------------------------------------------
# _generate_proposals
# ---------------------------------------------------------------------------

class TestGenerateProposals:
    def test_mismatch_without_tier0_proposes_new_intent(self):
        trace = DebugTrace(
            stable_id="abc",
            pipeline_categoria="Estágios",
            has_correction=True,
            corrected_categoria="Acadêmico / Matrícula",
            tier0_match=False,
        )
        proposals = _generate_proposals(trace)
        types = [p["type"] for p in proposals]
        assert "intent_creation" in types
        assert "feedback_entry" in types

    def test_tier0_match_no_correction_proposes_review(self):
        trace = DebugTrace(
            stable_id="abc",
            pipeline_categoria="Estágios",
            tier0_match=True,
            tier0_intent_name="estagio_tce",
            tier0_score=0.95,
            tier0_method="keyword",
        )
        proposals = _generate_proposals(trace)
        assert any(p["type"] == "review_needed" for p in proposals)

    def test_no_tier0_no_correction_proposes_expansion(self):
        trace = DebugTrace(
            stable_id="abc",
            pipeline_categoria="Formativas",
            tier0_match=False,
        )
        proposals = _generate_proposals(trace)
        assert any(p["type"] == "intent_expansion" for p in proposals)

    def test_stale_tier0_with_correction_proposes_refresh(self):
        trace = DebugTrace(
            stable_id="abc",
            pipeline_categoria="Estágios",
            has_correction=True,
            corrected_categoria="Outros",
            tier0_match=True,
            tier0_intent_name="old_intent",
            tier0_stale=True,
        )
        proposals = _generate_proposals(trace)
        assert any(p["type"] == "intent_refresh" for p in proposals)


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------

class TestFormatReport:
    def test_report_contains_key_sections(self):
        trace = DebugTrace(
            stable_id="abc123",
            email_subject="Test Subject",
            email_sender="test@test.com",
            pipeline_categoria="Estágios",
            tier0_match=True,
            tier0_intent_name="estagio_test",
            tier0_score=0.95,
            tier0_method="keyword",
        )
        report = format_report(trace)
        assert "# Classification Debug" in report
        assert "Test Subject" in report
        assert "Tier 0 Replay" in report
        assert "estagio_test" in report
        assert "Pipeline Classification" in report

    def test_report_no_tier0(self):
        trace = DebugTrace(
            stable_id="xyz",
            pipeline_categoria="Outros",
            tier0_match=False,
        )
        report = format_report(trace)
        assert "Tier 1 (RAG + LLM)" in report


# ---------------------------------------------------------------------------
# run_debug
# ---------------------------------------------------------------------------

class TestRunDebug:
    def test_writes_report_files(self, tmp_path):
        last_run = tmp_path / "last_run.jsonl"
        _write_last_run(last_run, [SAMPLE_ENTRY])

        with patch("ufpr_automation.agent_sdk.debug_classification.replay_tier0",
                    return_value={"match": False}), \
             patch("ufpr_automation.agent_sdk.debug_classification._load_procedure_records", return_value=[]), \
             patch("ufpr_automation.agent_sdk.debug_classification._load_feedback_for", return_value=None):
            traces = run_debug(
                ["abc123def456"],
                last_run_path=last_run,
                report_dir=tmp_path / "reports",
            )

        assert len(traces) == 1
        reports = list((tmp_path / "reports").rglob("*.md"))
        assert len(reports) == 1
        content = reports[0].read_text(encoding="utf-8")
        assert "abc123def456" in content

    def test_multiple_ids(self, tmp_path):
        entry2 = {**SAMPLE_ENTRY, "email_hash": "second_id_123"}
        last_run = tmp_path / "last_run.jsonl"
        _write_last_run(last_run, [SAMPLE_ENTRY, entry2])

        with patch("ufpr_automation.agent_sdk.debug_classification.replay_tier0",
                    return_value={"match": False}), \
             patch("ufpr_automation.agent_sdk.debug_classification._load_procedure_records", return_value=[]), \
             patch("ufpr_automation.agent_sdk.debug_classification._load_feedback_for", return_value=None):
            traces = run_debug(
                ["abc123def456", "second_id_123"],
                last_run_path=last_run,
                report_dir=tmp_path / "reports",
            )

        assert len(traces) == 2
        reports = list((tmp_path / "reports").rglob("*.md"))
        assert len(reports) == 2
