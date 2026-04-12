"""Tests for agent_sdk/intent_drafter — Tier 0 playbook auto-learning."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ufpr_automation.agent_sdk.intent_drafter import (
    EmailCluster,
    _content_hash,
    _existing_intent_names,
    _normalize_subject,
    build_cluster_prompt,
    cluster_tier1_emails,
    run_intent_drafter,
)
from ufpr_automation.procedures.store import ProcedureRecord


# ---------------------------------------------------------------------------
# _normalize_subject
# ---------------------------------------------------------------------------

class TestNormalizeSubject:
    def test_strips_re_fwd(self):
        assert _normalize_subject("Re: TCE do aluno") == "tce aluno"
        assert _normalize_subject("Fwd: Prorrogação estágio") == "prorrogação estágio"

    def test_strips_grr_and_numbers(self):
        assert _normalize_subject("TCE João GRR20210001 12345") == "tce joão"

    def test_keeps_first_three_words(self):
        assert _normalize_subject("Solicitação de declaração de horas formativas extra") == "solicitação declaração horas"

    def test_empty_returns_empty(self):
        assert _normalize_subject("") == ""
        assert _normalize_subject("Re: ") == ""


# ---------------------------------------------------------------------------
# _existing_intent_names
# ---------------------------------------------------------------------------

class TestExistingIntentNames:
    def test_parses_procedures_md(self, tmp_path):
        md = tmp_path / "PROCEDURES.md"
        md.write_text(
            '```intent\nintent_name: foo_bar\nkeywords: ["foo"]\ncategoria: Outros\n```\n'
            '```intent\nintent_name: baz_qux\nkeywords: ["baz"]\ncategoria: Outros\n```\n',
            encoding="utf-8",
        )
        names = _existing_intent_names(md)
        assert names == {"foo_bar", "baz_qux"}

    def test_missing_file_returns_empty(self, tmp_path):
        assert _existing_intent_names(tmp_path / "nope.md") == set()


# ---------------------------------------------------------------------------
# _content_hash
# ---------------------------------------------------------------------------

class TestContentHash:
    def test_deterministic(self):
        assert _content_hash("abc") == _content_hash("abc")

    def test_different_inputs(self):
        assert _content_hash("a") != _content_hash("b")

    def test_length_12(self):
        assert len(_content_hash("anything")) == 12


# ---------------------------------------------------------------------------
# cluster_tier1_emails
# ---------------------------------------------------------------------------

def _write_procedures_jsonl(path: Path, records: list[dict]) -> None:
    """Write procedure records as JSONL."""
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            pr = ProcedureRecord(**rec)
            f.write(pr.model_dump_json() + "\n")


class TestClusterTier1Emails:
    def test_no_data_returns_empty(self, tmp_path):
        clusters = cluster_tier1_emails(
            last_days=30,
            min_frequency=1,
            procedures_path=tmp_path / "procedures.jsonl",
            feedback_path=tmp_path / "feedback.jsonl",
        )
        assert clusters == []

    def test_clusters_by_pattern(self, tmp_path):
        proc_path = tmp_path / "procedures.jsonl"
        fb_path = tmp_path / "feedback.jsonl"
        fb_path.write_text("", encoding="utf-8")

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        records = [
            {"timestamp": now, "email_subject": f"TCE aluno {i}",
             "email_categoria": "Estágios", "outcome": "draft_saved"}
            for i in range(6)
        ]
        _write_procedures_jsonl(proc_path, records)

        clusters = cluster_tier1_emails(
            last_days=30, min_frequency=5,
            procedures_path=proc_path, feedback_path=fb_path,
        )
        assert len(clusters) == 1
        assert clusters[0].categoria == "Estágios"
        assert clusters[0].count == 6

    def test_filters_tier0_hits(self, tmp_path):
        proc_path = tmp_path / "procedures.jsonl"
        fb_path = tmp_path / "feedback.jsonl"
        fb_path.write_text("", encoding="utf-8")

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        # 6 emails but all Tier 0 → should be excluded
        records = [
            {"timestamp": now, "email_subject": f"TCE aluno {i}",
             "email_categoria": "Estágios", "outcome": "tier0_hit"}
            for i in range(6)
        ]
        _write_procedures_jsonl(proc_path, records)

        clusters = cluster_tier1_emails(
            last_days=30, min_frequency=5,
            procedures_path=proc_path, feedback_path=fb_path,
        )
        assert clusters == []

    def test_min_frequency_threshold(self, tmp_path):
        proc_path = tmp_path / "procedures.jsonl"
        fb_path = tmp_path / "feedback.jsonl"
        fb_path.write_text("", encoding="utf-8")

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        # Only 3 emails — below min_frequency=5
        records = [
            {"timestamp": now, "email_subject": f"Declaração {i}",
             "email_categoria": "Formativas", "outcome": "draft_saved"}
            for i in range(3)
        ]
        _write_procedures_jsonl(proc_path, records)

        clusters = cluster_tier1_emails(
            last_days=30, min_frequency=5,
            procedures_path=proc_path, feedback_path=fb_path,
        )
        assert clusters == []


# ---------------------------------------------------------------------------
# build_cluster_prompt
# ---------------------------------------------------------------------------

class TestBuildClusterPrompt:
    def test_contains_cluster_info(self):
        cluster = EmailCluster(
            categoria="Estágios",
            pattern="tce prorrogação",
            sample_subjects=["TCE Prorrogação João", "TCE Prorrogação Maria"],
            count=10,
        )
        prompt = build_cluster_prompt(cluster, {"existing_intent"}, "SOUL excerpt...")
        assert "Estágios" in prompt
        assert "tce prorrogação" in prompt
        assert "10 emails" in prompt
        assert "existing_intent" in prompt

    def test_includes_corrections(self):
        cluster = EmailCluster(
            categoria="Acadêmico / Matrícula",
            pattern="trancamento",
            sample_subjects=["Trancamento total"],
            count=5,
            feedback_corrections=[
                {"subject": "Trancamento", "original_cat": "Outros",
                 "corrected_cat": "Acadêmico / Matrícula", "notes": "era matrícula"}
            ],
        )
        prompt = build_cluster_prompt(cluster, set(), "")
        assert "Correções humanas" in prompt
        assert "era matrícula" in prompt


# ---------------------------------------------------------------------------
# run_intent_drafter (dry_run mode)
# ---------------------------------------------------------------------------

class TestRunIntentDrafterDryRun:
    def test_dry_run_no_clusters(self, tmp_path):
        stats = run_intent_drafter(
            last_days=30,
            min_frequency=5,
            dry_run=True,
            procedures_path=tmp_path / "procedures.jsonl",
            feedback_path=tmp_path / "feedback.jsonl",
            candidates_path=tmp_path / "CANDIDATES.md",
        )
        assert stats["clusters"] == 0
        assert stats["candidates"] == 0

    def test_dry_run_with_clusters(self, tmp_path):
        proc_path = tmp_path / "procedures.jsonl"
        fb_path = tmp_path / "feedback.jsonl"
        fb_path.write_text("", encoding="utf-8")
        cand_path = tmp_path / "CANDIDATES.md"

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        records = [
            {"timestamp": now, "email_subject": f"Declaração AFC {i}",
             "email_categoria": "Formativas", "outcome": "draft_saved"}
            for i in range(6)
        ]
        _write_procedures_jsonl(proc_path, records)

        stats = run_intent_drafter(
            last_days=30,
            min_frequency=5,
            dry_run=True,
            procedures_path=proc_path,
            feedback_path=fb_path,
            candidates_path=cand_path,
        )
        assert stats["clusters"] == 1
        assert stats["candidates"] == 1
        # Dry run still writes marker comments
        assert cand_path.exists()
        content = cand_path.read_text(encoding="utf-8")
        assert "DRY_RUN" in content

    def test_idempotency_skips_existing_hash(self, tmp_path):
        proc_path = tmp_path / "procedures.jsonl"
        fb_path = tmp_path / "feedback.jsonl"
        fb_path.write_text("", encoding="utf-8")
        cand_path = tmp_path / "CANDIDATES.md"

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        records = [
            {"timestamp": now, "email_subject": f"Declaração AFC {i}",
             "email_categoria": "Formativas", "outcome": "draft_saved"}
            for i in range(6)
        ]
        _write_procedures_jsonl(proc_path, records)

        # Run once
        stats1 = run_intent_drafter(
            last_days=30, min_frequency=5, dry_run=True,
            procedures_path=proc_path, feedback_path=fb_path, candidates_path=cand_path,
        )
        assert stats1["candidates"] == 1

        # Run again — should skip because hash already present
        stats2 = run_intent_drafter(
            last_days=30, min_frequency=5, dry_run=True,
            procedures_path=proc_path, feedback_path=fb_path, candidates_path=cand_path,
        )
        assert stats2["skipped"] == 1
        assert stats2["candidates"] == 0


# ---------------------------------------------------------------------------
# run_intent_drafter with mocked Claude
# ---------------------------------------------------------------------------

class TestRunIntentDrafterWithClaude:
    def test_successful_candidate_generation(self, tmp_path):
        from ufpr_automation.agent_sdk.runner import ClaudeRunResult

        proc_path = tmp_path / "procedures.jsonl"
        fb_path = tmp_path / "feedback.jsonl"
        fb_path.write_text("", encoding="utf-8")
        cand_path = tmp_path / "CANDIDATES.md"

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        records = [
            {"timestamp": now, "email_subject": f"Declaração horas formativas {i}",
             "email_categoria": "Formativas", "outcome": "draft_saved"}
            for i in range(6)
        ]
        _write_procedures_jsonl(proc_path, records)

        mock_yaml = (
            '# PROPOSTA:\n```intent\n'
            'intent_name: formativas_declaracao_horas\n'
            'keywords:\n  - "declaração horas formativas"\n'
            'categoria: "Formativas"\n'
            'action: "Redigir Resposta"\n'
            'confidence: 0.5\n'
            'sources:\n  - "pendente_revisao_humana"\n'
            'template: "Prezado(a) [NOME_ALUNO], segue declaração."\n'
            '```'
        )

        mock_result = ClaudeRunResult(
            success=True, task="intent_drafter", run_id="test123",
            started_at=now, duration_s=5.0, prompt_chars=1000,
            output_text=mock_yaml,
        )

        with patch("ufpr_automation.agent_sdk.runner.is_claude_available", return_value=True), \
             patch("ufpr_automation.agent_sdk.runner.subprocess.run") as mock_run:
            # Mock subprocess.run to avoid calling real claude
            mock_run.return_value = type("Proc", (), {
                "returncode": 0, "stdout": mock_yaml, "stderr": ""
            })()
            stats = run_intent_drafter(
                last_days=30, min_frequency=5, dry_run=False,
                procedures_path=proc_path, feedback_path=fb_path, candidates_path=cand_path,
            )

        assert stats["candidates"] == 1
        assert cand_path.exists()
        content = cand_path.read_text(encoding="utf-8")
        assert "formativas_declaracao_horas" in content
        assert "Hash:" in content

    def test_invalid_yaml_from_claude_skipped(self, tmp_path):
        proc_path = tmp_path / "procedures.jsonl"
        fb_path = tmp_path / "feedback.jsonl"
        fb_path.write_text("", encoding="utf-8")
        cand_path = tmp_path / "CANDIDATES.md"

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        records = [
            {"timestamp": now, "email_subject": f"Pedido {i}",
             "email_categoria": "Outros", "outcome": "escalated"}
            for i in range(6)
        ]
        _write_procedures_jsonl(proc_path, records)

        invalid_yaml_output = "```yaml\ninvalid: [broken yaml {{{\n```"

        with patch("ufpr_automation.agent_sdk.runner.is_claude_available", return_value=True), \
             patch("ufpr_automation.agent_sdk.runner.subprocess.run") as mock_run:
            mock_run.return_value = type("Proc", (), {
                "returncode": 0, "stdout": invalid_yaml_output, "stderr": ""
            })()
            stats = run_intent_drafter(
                last_days=30, min_frequency=5, dry_run=False,
                procedures_path=proc_path, feedback_path=fb_path, candidates_path=cand_path,
            )

        assert stats["candidates"] == 0
        # File not created when no valid candidates
        assert not cand_path.exists()

    def test_claude_unavailable_returns_error(self, tmp_path):
        proc_path = tmp_path / "procedures.jsonl"
        fb_path = tmp_path / "feedback.jsonl"
        fb_path.write_text("", encoding="utf-8")

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        records = [
            {"timestamp": now, "email_subject": f"TCE {i}",
             "email_categoria": "Estágios", "outcome": "draft_saved"}
            for i in range(6)
        ]
        _write_procedures_jsonl(proc_path, records)

        with patch("ufpr_automation.agent_sdk.runner.subprocess.run", side_effect=FileNotFoundError):
            stats = run_intent_drafter(
                last_days=30, min_frequency=5, dry_run=False,
                procedures_path=proc_path, feedback_path=fb_path,
            )

        assert stats["error"] == "claude_unavailable"
        assert stats["candidates"] == 0
